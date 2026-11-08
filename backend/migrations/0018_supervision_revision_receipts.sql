-- E2-C2: immutable supervisory read receipts for the exact currently published
-- revised OT version (before or after assignment). No changes to E1 execution,
-- assignments, capture tables, version snapshots or production permissions.
-- Distinct from E2-C1 operator acknowledgements, which are assignment-bound.

CREATE TABLE vinto_txn.work_order_supervision_revision_receipt (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version_id uuid NOT NULL REFERENCES vinto_txn.work_order_version(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
  acknowledged_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT work_order_supervision_revision_receipt_unique
    UNIQUE (version_id, user_id)
);

CREATE INDEX work_order_supervision_revision_receipt_user_idx
  ON vinto_txn.work_order_supervision_revision_receipt(user_id, version_id);

CREATE FUNCTION vinto_txn.guard_work_order_supervision_revision_receipt()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor uuid;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'Supervision revision acknowledgement history is immutable'
      USING ERRCODE = '23514';
  END IF;

  actor := nullif(current_setting('vinto.actor_id', true), '')::uuid;
  IF actor IS NULL OR actor IS DISTINCT FROM NEW.user_id
     OR nullif(current_setting('vinto.reason', true), '') IS NULL
     OR nullif(current_setting('vinto.request_id', true), '') IS NULL THEN
    RAISE EXCEPTION 'Supervision acknowledgement requires authenticated audit context'
      USING ERRCODE = '23514';
  END IF;

  -- Reject old, archived, unpublished or baseline versions even when a caller
  -- can directly INSERT with vinto_app. The row lock serializes with Jefatura
  -- reprogramming, which locks work_order FOR UPDATE before creating a v3.
  PERFORM 1
  FROM vinto_txn.work_order_version v
  JOIN vinto_txn.work_order w ON w.id=v.work_order_id
  WHERE v.id=NEW.version_id
    AND v.kind='operational' AND v.published_at IS NOT NULL
    AND v.reprogram_reason IS NOT NULL
    AND w.status IN ('published','in_progress')
    AND w.archived_at IS NULL
    AND v.version_number=(
      SELECT MAX(latest.version_number)
      FROM vinto_txn.work_order_version latest
      WHERE latest.work_order_id=w.id AND latest.published_at IS NOT NULL
    )
  FOR SHARE OF w;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'Supervision acknowledgement is not the current published revision'
      USING ERRCODE = '23514';
  END IF;

  NEW.acknowledged_at := clock_timestamp();
  RETURN NEW;
END $$;

CREATE TRIGGER a_guard_work_order_supervision_revision_receipt
  BEFORE INSERT OR UPDATE OR DELETE
  ON vinto_txn.work_order_supervision_revision_receipt
  FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_work_order_supervision_revision_receipt();

CREATE TRIGGER immutable_truncate
  BEFORE TRUNCATE ON vinto_txn.work_order_supervision_revision_receipt
  FOR EACH STATEMENT EXECUTE FUNCTION vinto_audit.reject_mutation();

CREATE TRIGGER audit_changes
  AFTER INSERT ON vinto_txn.work_order_supervision_revision_receipt
  FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

REVOKE ALL ON vinto_txn.work_order_supervision_revision_receipt FROM PUBLIC;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vinto_app') THEN
    GRANT SELECT, INSERT ON vinto_txn.work_order_supervision_revision_receipt TO vinto_app;
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM vinto_txn.work_order_supervision_revision_receipt) THEN
    RAISE EXCEPTION '0018: unexpected receipt rows during additive migration';
  END IF;
END $$;
