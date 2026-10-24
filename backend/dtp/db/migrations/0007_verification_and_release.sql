-- 0007_verification_and_release.sql: Challenges, Verification Reports, Decisions, and Current Pointers (SRS-038 - SRS-042, AT-030 - AT-034)

DROP TABLE IF EXISTS case_current_decisions CASCADE;
DROP TABLE IF EXISTS decisions CASCADE;
DROP TABLE IF EXISTS challenges CASCADE;
DROP TABLE IF EXISTS verification_reports CASCADE;

CREATE TABLE verification_reports (
    id text PRIMARY KEY,
    tenant_id uuid NOT NULL,
    case_id uuid NOT NULL,
    target_artifact_ref jsonb NOT NULL,
    overall_outcome text NOT NULL CHECK (overall_outcome IN ('PASS', 'FAIL', 'NOT_APPLICABLE')),
    checks jsonb NOT NULL,
    blocking_reasons jsonb,
    evaluator_version text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases(tenant_id, id)
);

CREATE TABLE challenges (
    id text PRIMARY KEY,
    tenant_id uuid NOT NULL,
    case_id uuid NOT NULL,
    decision_proposal_id text,
    challenger_agent_id text NOT NULL,
    title text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('CRITICAL', 'MATERIAL', 'MINOR')),
    status text NOT NULL CHECK (status IN ('OPEN', 'TESTING', 'RESOLVED', 'UNRESOLVED', 'REJECTED', 'SUPERSEDED')),
    affected_artifact_refs jsonb NOT NULL,
    failure_proposition text NOT NULL,
    proposed_test text NOT NULL,
    reversal_criteria text NOT NULL,
    test_result text,
    resolution_notes text,
    resolved_by text,
    resolved_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases(tenant_id, id)
);

CREATE TABLE decisions (
    id text PRIMARY KEY,
    tenant_id uuid NOT NULL,
    case_id uuid NOT NULL,
    revision integer NOT NULL,
    outcome text NOT NULL CHECK (outcome IN ('RECOMMEND', 'CONDITIONAL', 'DEFER', 'NO_FEASIBLE_ACTION', 'ABSTAIN')),
    status text NOT NULL CHECK (status IN ('DRAFT', 'IN_REVIEW', 'VERIFIED', 'RELEASED', 'STALE', 'SUPERSEDED', 'WITHDRAWN')),
    selected_strategy_ref jsonb,
    objective_and_constraints jsonb NOT NULL,
    summary_payload jsonb NOT NULL,
    lineage_closure jsonb NOT NULL,
    verification_report_id text REFERENCES verification_reports(id),
    released_at timestamptz,
    released_by text,
    created_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases(tenant_id, id)
);

-- Atomic unique current decision pointer per case with optimistic concurrency (AT-034)
CREATE TABLE case_current_decisions (
    tenant_id uuid NOT NULL,
    case_id uuid NOT NULL,
    decision_id text NOT NULL REFERENCES decisions(id),
    decision_revision integer NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, case_id),
    FOREIGN KEY (tenant_id, case_id) REFERENCES cases(tenant_id, id)
);

-- RLS
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['verification_reports','challenges','decisions','case_current_decisions'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format($p$CREATE POLICY tenant_isolation ON %I
      USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
      WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)$p$, t);
  END LOOP;
END $$;

-- Grants for non-superuser RLS role twin_app
GRANT SELECT, INSERT, UPDATE ON verification_reports TO twin_app;
GRANT SELECT, INSERT, UPDATE ON challenges TO twin_app;
GRANT SELECT, INSERT, UPDATE ON decisions TO twin_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON case_current_decisions TO twin_app;
