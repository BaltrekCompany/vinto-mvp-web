-- FOFF-03 D03: technical review receipts, NOT operational captures.
-- Additive and immutable. A 202 is a retained request for supervised review.
-- Original measurements are stored in authenticated-session intake; do not
-- store passwords/tokens/seeds or trust client timestamps as operational time.
CREATE TABLE vinto_txn.offline_conversion_review (
  capture_id uuid PRIMARY KEY,
  author_user_id uuid NOT NULL REFERENCES vinto_master."user"(id),
  device_key uuid NOT NULL,
  assignment_id uuid NOT NULL REFERENCES vinto_txn.assignment(id),
  form_code text NOT NULL CHECK (form_code IN ('VINTO-P1-11','VINTO-P1-12','VINTO-P1-13','VINTO-P1-16')),
  form_version integer NOT NULL CHECK (form_version > 0),
  machine_code text NOT NULL,
  payload_sha256 text NOT NULL CHECK (payload_sha256 ~ '^[0-9a-f]{64}$'),
  request_payload jsonb NOT NULL CHECK (jsonb_typeof(request_payload) = 'object'),
  original_context jsonb NOT NULL CHECK (jsonb_typeof(original_context) = 'object'),
  reason text NOT NULL CHECK (reason IN ('assignment_stale','assignment_not_active','line_not_in_production','preparation_expired','capture_scope_expired')),
  client_captured_at timestamptz,
  received_at timestamptz NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX offline_conversion_review_author_idx
  ON vinto_txn.offline_conversion_review(author_user_id, received_at DESC);
CREATE TRIGGER immutable_offline_conversion_review
  BEFORE UPDATE OR DELETE ON vinto_txn.offline_conversion_review
  FOR EACH ROW EXECUTE FUNCTION vinto_audit.reject_mutation();
GRANT SELECT, INSERT ON vinto_txn.offline_conversion_review TO vinto_app;
