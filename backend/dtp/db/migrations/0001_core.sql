-- 0001_core.sql  (SRS-004, 015, 016, 020, 024; Annex D1/D3)
-- Canonical store. Tenant-scoped composite FKs, append-only revisions, row-level security
-- (FORCE) for the non-owner application role, transactional outbox, atomic budgets.
-- Runs as the schema-owner role; application connects as twin_app (NOT owner, NOT superuser).

CREATE TABLE IF NOT EXISTS schema_migrations (
  version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE tenants (
  id uuid PRIMARY KEY, name text NOT NULL, created_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE users (
  id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenants(id),
  email text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id), UNIQUE (tenant_id, email));

CREATE TABLE memberships (
  tenant_id uuid NOT NULL, user_id uuid NOT NULL, role text NOT NULL
    CHECK (role IN ('owner','analyst','domain_reviewer','research_operator','administrator','reader')),
  PRIMARY KEY (tenant_id, user_id, role),
  FOREIGN KEY (tenant_id, user_id) REFERENCES users(tenant_id, id));

CREATE TABLE cases (
  id uuid PRIMARY KEY, tenant_id uuid NOT NULL REFERENCES tenants(id),
  title text NOT NULL, objective text, horizon_days integer CHECK (horizon_days > 0),
  country text NOT NULL, currency text NOT NULL CHECK (currency ~ '^[A-Z]{3}$'),
  tax_basis text NOT NULL CHECK (tax_basis IN ('NET','GROSS','NOT_APPLICABLE','UNKNOWN')),
  defaulted_fields text[] NOT NULL DEFAULT '{}',
  state text NOT NULL DEFAULT 'OPEN' CHECK (state IN ('OPEN','PAUSED','CLOSED','ARCHIVED')),
  revision integer NOT NULL DEFAULT 1, origin text NOT NULL CHECK (origin IN ('REAL','FIXTURE')),
  created_by uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, created_by) REFERENCES users(tenant_id, id));

-- Claims: one row per revision; never updated except review_state transitions via guarded fn.
CREATE TABLE claim_revisions (
  tenant_id uuid NOT NULL, claim_id uuid NOT NULL, revision integer NOT NULL CHECK (revision >= 1),
  case_id uuid NOT NULL, predicate text NOT NULL, proposition text NOT NULL,
  value jsonb, epistemic_state text NOT NULL
    CHECK (epistemic_state IN ('KNOWN','INFERRED','ASSUMED','UNKNOWN','CONTRADICTED')),
  review_state text NOT NULL DEFAULT 'PROPOSED'
    CHECK (review_state IN ('PROPOSED','NEEDS_REVIEW','ACCEPTED','REJECTED','WITHDRAWN')),
  valid_from timestamptz, valid_to timestamptz,                       -- [valid_from, valid_to)
  recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),         -- first known
  origin text NOT NULL CHECK (origin IN ('REAL','FIXTURE')),
  material boolean NOT NULL DEFAULT false,
  evidence_refs jsonb NOT NULL DEFAULT '[]', actor_id uuid NOT NULL,
  PRIMARY KEY (tenant_id, claim_id, revision),
  FOREIGN KEY (tenant_id, case_id) REFERENCES cases(tenant_id, id),
  FOREIGN KEY (tenant_id, actor_id) REFERENCES users(tenant_id, id),
  CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_from < valid_to),
  CHECK (epistemic_state <> 'UNKNOWN' OR value IS NULL));
CREATE INDEX claim_asknown_idx ON claim_revisions (tenant_id, case_id, claim_id, recorded_at);

-- Immutable snapshots (SRS-015)
CREATE TABLE world_snapshots (
  id uuid PRIMARY KEY, tenant_id uuid NOT NULL, case_id uuid NOT NULL,
  knowledge_cutoff timestamptz NOT NULL, schema_version text NOT NULL,
  content_hash text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, case_id) REFERENCES cases(tenant_id, id));
CREATE TABLE snapshot_members (
  tenant_id uuid NOT NULL, snapshot_id uuid NOT NULL, claim_id uuid NOT NULL, revision integer NOT NULL,
  PRIMARY KEY (tenant_id, snapshot_id, claim_id),
  FOREIGN KEY (tenant_id, snapshot_id) REFERENCES world_snapshots(tenant_id, id),
  FOREIGN KEY (tenant_id, claim_id, revision) REFERENCES claim_revisions(tenant_id, claim_id, revision));

-- Events + transactional outbox + consumer receipts (SRS-020)
CREATE TABLE events (
  event_id uuid PRIMARY KEY, tenant_id uuid NOT NULL, case_id uuid,
  aggregate_id uuid NOT NULL, aggregate_revision integer NOT NULL CHECK (aggregate_revision >= 1),
  event_type text NOT NULL, occurred_at timestamptz, recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  correlation_id uuid NOT NULL, causation_id uuid, actor_id uuid NOT NULL,
  payload_refs jsonb NOT NULL DEFAULT '[]', origin text NOT NULL CHECK (origin IN ('REAL','FIXTURE')),
  seq bigint GENERATED ALWAYS AS IDENTITY,
  UNIQUE (tenant_id, aggregate_id, aggregate_revision, event_type));
CREATE TABLE outbox (
  event_id uuid PRIMARY KEY REFERENCES events(event_id), tenant_id uuid NOT NULL,
  published_at timestamptz, attempts integer NOT NULL DEFAULT 0);
CREATE INDEX outbox_pending_idx ON outbox (tenant_id) WHERE published_at IS NULL;
CREATE TABLE consumer_receipts (
  tenant_id uuid NOT NULL, consumer text NOT NULL, event_id uuid NOT NULL REFERENCES events(event_id),
  processed_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (consumer, event_id));

-- Command idempotency
CREATE TABLE idempotency_keys (
  tenant_id uuid NOT NULL, actor_id uuid NOT NULL, key text NOT NULL,
  request_hash text NOT NULL, response jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, actor_id, key));

-- Budgets: atomic reservation; never negative (SRS-024). Amounts in integer micro-units.
CREATE TABLE budget_accounts (
  id uuid PRIMARY KEY, tenant_id uuid NOT NULL, case_id uuid NOT NULL,
  resource text NOT NULL CHECK (resource IN ('USD_MICROS','TOKENS','CALLS','SECONDS')),
  limit_amount bigint NOT NULL CHECK (limit_amount >= 0),
  reserved bigint NOT NULL DEFAULT 0 CHECK (reserved >= 0),
  consumed bigint NOT NULL DEFAULT 0 CHECK (consumed >= 0),
  CHECK (reserved + consumed <= limit_amount),
  UNIQUE (tenant_id, id), UNIQUE (tenant_id, case_id, resource),
  FOREIGN KEY (tenant_id, case_id) REFERENCES cases(tenant_id, id));
CREATE TABLE budget_reservations (
  id uuid PRIMARY KEY, tenant_id uuid NOT NULL, account_id uuid NOT NULL,
  amount bigint NOT NULL CHECK (amount > 0), state text NOT NULL DEFAULT 'RESERVED'
    CHECK (state IN ('RESERVED','SETTLED','RELEASED','UNKNOWN_OUTCOME')),
  settled_amount bigint, task_key text NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, account_id, task_key),
  FOREIGN KEY (tenant_id, account_id) REFERENCES budget_accounts(tenant_id, id));

CREATE TABLE audit_records (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, tenant_id uuid NOT NULL,
  actor_id uuid, action text NOT NULL, subject text, detail jsonb NOT NULL DEFAULT '{}',
  at timestamptz NOT NULL DEFAULT clock_timestamp());

-- ---------- immutability guards ----------
CREATE FUNCTION forbid_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION '% on % is not permitted (immutable)', TG_OP, TG_TABLE_NAME; END $$;
CREATE TRIGGER snapshots_immutable BEFORE UPDATE OR DELETE ON world_snapshots
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER snapshot_members_immutable BEFORE UPDATE OR DELETE ON snapshot_members
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER events_immutable BEFORE UPDATE OR DELETE ON events
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER audit_immutable BEFORE UPDATE OR DELETE ON audit_records
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- claim revisions: payload immutable; only review_state may move, along Annex D1 edges.
CREATE FUNCTION guard_claim_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN RAISE EXCEPTION 'claim revisions cannot be deleted'; END IF;
  IF (NEW.tenant_id, NEW.claim_id, NEW.revision, NEW.case_id, NEW.predicate, NEW.proposition, NEW.value,
      NEW.epistemic_state, NEW.valid_from, NEW.valid_to, NEW.recorded_at, NEW.origin, NEW.evidence_refs)
     IS DISTINCT FROM
     (OLD.tenant_id, OLD.claim_id, OLD.revision, OLD.case_id, OLD.predicate, OLD.proposition, OLD.value,
      OLD.epistemic_state, OLD.valid_from, OLD.valid_to, OLD.recorded_at, OLD.origin, OLD.evidence_refs)
  THEN RAISE EXCEPTION 'claim revision payload is immutable; create a new revision'; END IF;
  IF NOT ((OLD.review_state='PROPOSED' AND NEW.review_state IN ('NEEDS_REVIEW','ACCEPTED','REJECTED'))
       OR (OLD.review_state='NEEDS_REVIEW' AND NEW.review_state IN ('ACCEPTED','REJECTED'))
       OR (OLD.review_state='ACCEPTED' AND NEW.review_state='WITHDRAWN')) THEN
    RAISE EXCEPTION 'illegal claim review transition % -> %', OLD.review_state, NEW.review_state;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER claim_guard BEFORE UPDATE OR DELETE ON claim_revisions
  FOR EACH ROW EXECUTE FUNCTION guard_claim_update();

-- ---------- application role + RLS ----------
-- twin_app is created by the migration runner (password from env); grants below.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='twin_app') THEN
    RAISE EXCEPTION 'role twin_app must exist before migration (created by runner)';
  END IF;
END $$;

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['users','memberships','cases','claim_revisions','world_snapshots',
    'snapshot_members','events','outbox','consumer_receipts','idempotency_keys','budget_accounts',
    'budget_reservations','audit_records'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format($p$CREATE POLICY tenant_isolation ON %I
      USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
      WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)$p$, t);
  END LOOP;
END $$;
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_self ON tenants
  USING (id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (id = nullif(current_setting('app.tenant_id', true), '')::uuid);

GRANT USAGE ON SCHEMA public TO twin_app;
GRANT SELECT, INSERT ON tenants, users, memberships, cases, world_snapshots, snapshot_members,
  events, consumer_receipts, idempotency_keys, budget_reservations, audit_records TO twin_app;
GRANT SELECT, INSERT, UPDATE (review_state) ON claim_revisions TO twin_app;
GRANT SELECT, INSERT, UPDATE (published_at, attempts) ON outbox TO twin_app;
GRANT SELECT, INSERT, UPDATE (reserved, consumed) ON budget_accounts TO twin_app;
GRANT UPDATE (state, settled_amount) ON budget_reservations TO twin_app;
GRANT UPDATE (state, revision) ON cases TO twin_app;
