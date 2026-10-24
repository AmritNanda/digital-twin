-- 0005_hybrid_retrieval.sql (SRS-017, SRS-018):
-- 1. Full-text search (tsvector) on evidence_spans with GIN indexing.
-- 2. Dense vector embeddings (pgvector) on evidence_spans (dimension 384 for sentence-transformers all-MiniLM-L6-v2).
-- 3. Claim-to-evidence reference closure link table `claim_evidence`.
-- 4. In-database relationship graph projection table `graph_edges` for business & artifact lineage.

CREATE EXTENSION IF NOT EXISTS vector;

-- Lexical search & vector columns on evidence_spans
ALTER TABLE evidence_spans ADD COLUMN tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED;
CREATE INDEX evidence_spans_tsv_idx ON evidence_spans USING GIN (tsv);

ALTER TABLE evidence_spans ADD COLUMN embedding vector(384);
CREATE INDEX evidence_spans_embedding_idx ON evidence_spans USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Claim evidence closure table (SRS-011, SRS-016)
CREATE TABLE claim_evidence (
  tenant_id uuid NOT NULL,
  claim_id uuid NOT NULL,
  revision integer NOT NULL,
  evidence_span_id uuid NOT NULL,
  quote text,
  support_type text NOT NULL DEFAULT 'DIRECT' CHECK (support_type IN ('DIRECT','DERIVED','CONTEXTUAL')),
  PRIMARY KEY (tenant_id, claim_id, revision, evidence_span_id),
  FOREIGN KEY (tenant_id, claim_id, revision) REFERENCES claim_revisions(tenant_id, claim_id, revision),
  FOREIGN KEY (tenant_id, evidence_span_id) REFERENCES evidence_spans(tenant_id, id)
);

-- Graph projections table (SRS-017)
CREATE TABLE graph_edges (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  case_id uuid NOT NULL,
  source_kind text NOT NULL,
  source_id uuid NOT NULL,
  target_kind text NOT NULL,
  target_id uuid NOT NULL,
  relation text NOT NULL CHECK (relation IN (
    'OFFERS','SERVES','COMPETES_WITH','SUBSTITUTES_FOR','SUPPLIES','DISTRIBUTED_VIA',
    'REQUIRES','LIMITED_BY','SUBJECT_TO','OPERATES_IN','SUPPORTED_BY','CHALLENGED_BY',
    'EXTRACTED_FROM','DERIVED_FROM','SUPERSEDES','USES_PARAMETER','USES_MODEL',
    'EVALUATES','RECOMMENDS','DEPENDS_ON'
  )),
  assertion_revision integer,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (tenant_id, case_id, source_id, target_id, relation),
  FOREIGN KEY (tenant_id, case_id) REFERENCES cases(tenant_id, id)
);
CREATE INDEX graph_edges_traversal_idx ON graph_edges (tenant_id, case_id, source_id, relation);

-- RLS
ALTER TABLE claim_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE claim_evidence FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON claim_evidence
  USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE graph_edges ENABLE ROW LEVEL SECURITY;
ALTER TABLE graph_edges FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_isolation ON graph_edges
  USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
  WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);

GRANT SELECT, INSERT ON claim_evidence TO twin_app;
GRANT SELECT, INSERT, DELETE ON graph_edges TO twin_app;
GRANT UPDATE (embedding) ON evidence_spans TO twin_app;
