-- 0003_review_log.sql: append-only review history so as-known reads reproduce acceptance AND
-- withdrawal state at any past cutoff (AT-007). claim_revisions.review_state remains the current state.
CREATE TABLE claim_review_log (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  tenant_id uuid NOT NULL, claim_id uuid NOT NULL, revision integer NOT NULL,
  state text NOT NULL CHECK (state IN ('NEEDS_REVIEW','ACCEPTED','REJECTED','WITHDRAWN')),
  actor_id uuid NOT NULL, category text, self_review boolean NOT NULL DEFAULT false,
  at timestamptz NOT NULL DEFAULT clock_timestamp(),
  FOREIGN KEY (tenant_id, claim_id, revision) REFERENCES claim_revisions(tenant_id, claim_id, revision),
  FOREIGN KEY (tenant_id, actor_id) REFERENCES users(tenant_id, id));
CREATE INDEX claim_review_log_idx ON claim_review_log (tenant_id, claim_id, revision, at);
CREATE TRIGGER review_log_immutable BEFORE UPDATE OR DELETE ON claim_review_log
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
ALTER TABLE claim_review_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE claim_review_log FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON claim_review_log
  USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
GRANT SELECT, INSERT ON claim_review_log TO twin_app;
