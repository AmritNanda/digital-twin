-- Claim an action before calling an external system so concurrent workers cannot dispatch it twice.
ALTER TABLE action_receipts DROP CONSTRAINT action_receipts_status_check;
ALTER TABLE action_receipts ADD CONSTRAINT action_receipts_status_check
    CHECK (status IN ('PENDING', 'DISPATCHING', 'EXECUTED', 'FAILED', 'UNKNOWN', 'RECONCILED'));
