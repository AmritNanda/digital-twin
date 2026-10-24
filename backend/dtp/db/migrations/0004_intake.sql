-- 0004_intake.sql (SRS-005/006/016): sources, immutable document versions, evidence spans, jobs.
CREATE TABLE document_versions (
  id uuid PRIMARY KEY, tenant_id uuid NOT NULL, case_id uuid NOT NULL,
  sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
  size_bytes bigint NOT NULL CHECK (size_bytes >= 0),
  declared_name text NOT NULL, declared_type text, detected_type text,
  data_class text NOT NULL DEFAULT 'INTERNAL' CHECK (data_class IN ('PUBLIC','INTERNAL','CONFIDENTIAL','RESTRICTED')),
  status text NOT NULL DEFAULT 'RECEIVED' CHECK (status IN
    ('RECEIVED','PARSING','PARSED','PARTIAL','NEEDS_OCR','REJECTED','FAILED')),
  parser text, parser_version text, diagnostics jsonb NOT NULL DEFAULT '[]',
  origin text NOT NULL CHECK (origin IN ('REAL','FIXTURE')),
  object_stored boolean NOT NULL DEFAULT false,
  submitted_by uuid NOT NULL, created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, case_id) REFERENCES cases(tenant_id, id),
  FOREIGN KEY (tenant_id, submitted_by) REFERENCES users(tenant_id, id));
CREATE INDEX document_versions_hash_idx ON document_versions (tenant_id, sha256);

CREATE TABLE ingestion_jobs (
  id uuid PRIMARY KEY, tenant_id uuid NOT NULL, document_version_id uuid NOT NULL,
  state text NOT NULL DEFAULT 'QUEUED' CHECK (state IN ('QUEUED','RUNNING','SUCCEEDED','PARTIAL','FAILED','REJECTED')),
  attempts integer NOT NULL DEFAULT 0, created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
  UNIQUE (tenant_id, id),
  FOREIGN KEY (tenant_id, document_version_id) REFERENCES document_versions(tenant_id, id));

CREATE TABLE evidence_spans (
  id uuid PRIMARY KEY, tenant_id uuid NOT NULL, document_version_id uuid NOT NULL,
  ordinal integer NOT NULL CHECK (ordinal >= 0),
  locator jsonb NOT NULL, text text NOT NULL, text_sha256 text NOT NULL,
  heading text, quality text NOT NULL DEFAULT 'EXACT' CHECK (quality IN ('EXACT','UNCERTAIN','OCR')),
  quality_note text, withdrawn boolean NOT NULL DEFAULT false,
  UNIQUE (tenant_id, id), UNIQUE (tenant_id, document_version_id, ordinal),
  FOREIGN KEY (tenant_id, document_version_id) REFERENCES document_versions(tenant_id, id));
CREATE INDEX evidence_spans_doc_idx ON evidence_spans (tenant_id, document_version_id, ordinal);

CREATE TRIGGER spans_payload_immutable BEFORE DELETE ON evidence_spans
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- document_versions: bytes/hash/name immutable; only parse-outcome columns may change.
CREATE FUNCTION guard_document_update() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF (NEW.id, NEW.tenant_id, NEW.case_id, NEW.sha256, NEW.size_bytes, NEW.declared_name, NEW.origin, NEW.submitted_by)
     IS DISTINCT FROM (OLD.id, OLD.tenant_id, OLD.case_id, OLD.sha256, OLD.size_bytes, OLD.declared_name, OLD.origin, OLD.submitted_by)
  THEN RAISE EXCEPTION 'document version identity is immutable'; END IF;
  IF OLD.status IN ('PARSED','PARTIAL','NEEDS_OCR','REJECTED','FAILED') AND NEW.status <> OLD.status THEN
    RAISE EXCEPTION 'terminal document status % cannot change', OLD.status; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER document_guard BEFORE UPDATE ON document_versions
  FOR EACH ROW EXECUTE FUNCTION guard_document_update();

DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['document_versions','ingestion_jobs','evidence_spans'] LOOP
    EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
    EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
    EXECUTE format($p$CREATE POLICY tenant_isolation ON %I
      USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
      WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)$p$, t);
  END LOOP;
END $$;
GRANT SELECT, INSERT ON document_versions, ingestion_jobs, evidence_spans TO twin_app;
GRANT UPDATE (status, parser, parser_version, diagnostics, detected_type, object_stored) ON document_versions TO twin_app;
GRANT UPDATE (state, attempts, finished_at) ON ingestion_jobs TO twin_app;
GRANT UPDATE (withdrawn) ON evidence_spans TO twin_app;
