-- 0002_review_time.sql: record when a review decision was made so as-known reads can
-- reproduce acceptance state at a past cutoff (AT-007), and who reviewed (separation audit).
ALTER TABLE claim_revisions ADD COLUMN reviewed_at timestamptz;
ALTER TABLE claim_revisions ADD COLUMN reviewer_id uuid;
ALTER TABLE claim_revisions ADD COLUMN review_category text;
ALTER TABLE claim_revisions ADD COLUMN self_review boolean NOT NULL DEFAULT false;
GRANT UPDATE (reviewed_at, reviewer_id, review_category, self_review) ON claim_revisions TO twin_app;

-- an accepted/rejected revision must record its review
CREATE OR REPLACE FUNCTION require_review_metadata() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.review_state IN ('ACCEPTED','REJECTED') AND (NEW.reviewed_at IS NULL OR NEW.reviewer_id IS NULL) THEN
    RAISE EXCEPTION 'review decision requires reviewed_at and reviewer_id';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER claim_review_meta BEFORE UPDATE ON claim_revisions
  FOR EACH ROW EXECUTE FUNCTION require_review_metadata();
