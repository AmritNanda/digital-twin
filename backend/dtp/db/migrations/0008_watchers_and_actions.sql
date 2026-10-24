-- 0008_watchers_and_actions.sql: Watchers, Experiments, Calibration, and Action Gateway (SRS-043 - SRS-047, AT-035, AT-036, AT-045, AT-047)

CREATE TABLE IF NOT EXISTS watchers (
    id text PRIMARY KEY,
    tenant_id uuid NOT NULL,
    case_id uuid NOT NULL,
    name text NOT NULL,
    source_connector text NOT NULL,
    schedule_cron text NOT NULL,
    status text NOT NULL CHECK (status IN ('ACTIVE', 'PAUSED', 'DEGRADED', 'DISABLED')),
    last_run_at timestamptz,
    last_content_hash text,
    rate_limit_per_day integer NOT NULL DEFAULT 100,
    invocations_today integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases(tenant_id, id)
);

CREATE TABLE IF NOT EXISTS experiments (
    id text PRIMARY KEY,
    tenant_id uuid NOT NULL,
    case_id uuid NOT NULL,
    title text NOT NULL,
    origin text NOT NULL CHECK (origin IN ('REAL', 'FIXTURE')),
    status text NOT NULL CHECK (status IN ('DRAFT', 'IN_REVIEW', 'APPROVED', 'RUNNING', 'PAUSED', 'COMPLETED', 'ABORTED', 'ANALYZED')),
    hypothesis text NOT NULL,
    target_metric text NOT NULL,
    sample_size integer,
    treatment_allocation float CHECK (treatment_allocation >= 0.0 AND treatment_allocation <= 1.0),
    observations jsonb NOT NULL DEFAULT '[]',
    calibration_metrics jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases(tenant_id, id)
);

CREATE TABLE IF NOT EXISTS action_receipts (
    id text PRIMARY KEY,
    tenant_id uuid NOT NULL,
    case_id uuid NOT NULL,
    action_type text NOT NULL,
    payload jsonb NOT NULL,
    approval_hash text NOT NULL,
    idempotency_key text NOT NULL,
    status text NOT NULL CHECK (status IN ('PENDING', 'EXECUTED', 'FAILED', 'UNKNOWN', 'RECONCILED')),
    execution_receipt jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    executed_at timestamptz,
    UNIQUE (tenant_id, idempotency_key),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases(tenant_id, id)
);

-- RLS
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['watchers', 'experiments', 'action_receipts'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format($p$CREATE POLICY tenant_isolation ON %I
      USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
      WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)$p$, t);
  END LOOP;
END $$;

-- Grants for non-superuser RLS role twin_app
GRANT SELECT, INSERT, UPDATE, DELETE ON watchers TO twin_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON experiments TO twin_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON action_receipts TO twin_app;
