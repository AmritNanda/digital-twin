-- 0006_durable_tasks.sql (SRS-021, SRS-022, SRS-023; AT-016, AT-018, AT-042):
-- 1. `investigations`: bounded container for cyclic work under a snapshot.
-- 2. `tasks`: durable tasks with fingerprint deduplication, priority, and lifecycle state.
-- 3. `task_dependencies`: DAG of prerequisites.
-- 4. `task_leases`: atomic fencing tokens with monotonic lease numbers and expiration timestamps.
-- 5. `agent_instances`: agent runs executing a task with capability templates, budget reservations, and depth limits.

CREATE TABLE investigations (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  case_id uuid NOT NULL,
  snapshot_id uuid NOT NULL,
  title text NOT NULL,
  state text NOT NULL DEFAULT 'CREATED' CHECK (state IN ('CREATED','RUNNING','WAITING_FOR_INPUT','COMPLETED','STOPPED','FAILED','CANCELLED')),
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, case_id) REFERENCES cases(tenant_id, id),
  FOREIGN KEY (tenant_id, snapshot_id) REFERENCES world_snapshots(tenant_id, id)
);

CREATE TABLE tasks (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  case_id uuid NOT NULL,
  investigation_id uuid NOT NULL,
  capability_id text NOT NULL,
  purpose text NOT NULL,
  fingerprint text NOT NULL,
  state text NOT NULL DEFAULT 'PROPOSED' CHECK (state IN (
    'PROPOSED','QUEUED','RUNNING','WAITING_DEPENDENCY','WAITING_INPUT',
    'RETRY_PENDING','SUCCEEDED','INCONCLUSIVE','FAILED','CANCELLED','EXPIRED'
  )),
  priority integer NOT NULL DEFAULT 50 CHECK (priority >= 1 AND priority <= 100),
  delegation_depth integer NOT NULL DEFAULT 0 CHECK (delegation_depth >= 0),
  max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
  current_attempt integer NOT NULL DEFAULT 0 CHECK (current_attempt >= 0),
  input_refs jsonb NOT NULL DEFAULT '[]',
  output_refs jsonb NOT NULL DEFAULT '[]',
  stop_reason text,
  deadline timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  UNIQUE (tenant_id, id),
  UNIQUE (tenant_id, investigation_id, fingerprint),
  FOREIGN KEY (tenant_id, case_id) REFERENCES cases(tenant_id, id),
  FOREIGN KEY (tenant_id, investigation_id) REFERENCES investigations(tenant_id, id)
);
CREATE INDEX tasks_state_prio_idx ON tasks (tenant_id, state, priority DESC);

CREATE TABLE task_dependencies (
  tenant_id uuid NOT NULL,
  task_id uuid NOT NULL,
  depends_on_task_id uuid NOT NULL,
  required_state text NOT NULL DEFAULT 'SUCCEEDED' CHECK (required_state IN ('SUCCEEDED','INCONCLUSIVE')),
  PRIMARY KEY (tenant_id, task_id, depends_on_task_id),
  FOREIGN KEY (tenant_id, task_id) REFERENCES tasks(tenant_id, id),
  FOREIGN KEY (tenant_id, depends_on_task_id) REFERENCES tasks(tenant_id, id)
);

CREATE TABLE task_leases (
  tenant_id uuid NOT NULL,
  task_id uuid NOT NULL,
  attempt_id uuid NOT NULL,
  worker_id text NOT NULL,
  fencing_token bigint NOT NULL CHECK (fencing_token >= 1),
  lease_expires_at timestamptz NOT NULL,
  acquired_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, task_id),
  FOREIGN KEY (tenant_id, task_id) REFERENCES tasks(tenant_id, id)
);

CREATE TABLE agent_instances (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  task_id uuid NOT NULL,
  attempt_id uuid NOT NULL,
  capability_id text NOT NULL,
  template_version text NOT NULL DEFAULT '1.0',
  state text NOT NULL DEFAULT 'REQUESTED' CHECK (state IN (
    'REQUESTED','ADMITTED','RUNNING','WAITING','SUCCEEDED','INCONCLUSIVE','FAILED','CANCELLED','EXPIRED'
  )),
  budget_reservation_id uuid,
  fencing_token bigint NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, task_id) REFERENCES tasks(tenant_id, id)
);

-- RLS
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['investigations','tasks','task_dependencies','task_leases','agent_instances'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format($p$CREATE POLICY tenant_isolation ON %I
      USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
      WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)$p$, t);
  END LOOP;
END $$;

GRANT SELECT, INSERT, UPDATE ON investigations, tasks, task_dependencies, task_leases, agent_instances TO twin_app;
GRANT DELETE ON task_leases TO twin_app;
