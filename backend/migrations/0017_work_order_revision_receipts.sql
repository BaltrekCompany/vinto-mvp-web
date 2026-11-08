-- E2-C1: in-app revision notices and append-only acknowledgements by the
-- authenticated operator, bound to the exact assigned, published OT version.
-- Additive and empty on install. No rewrites of assignments, E1 execution,
-- captures or any historical OT/version data. No production capture gate yet.

CREATE TABLE vinto_txn.work_order_revision_receipt (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  assignment_id uuid NOT NULL REFERENCES vinto_txn.assignment(id) ON DELETE RESTRICT,
  version_id uuid NOT NULL REFERENCES vinto_txn.work_order_version(id) ON DELETE RESTRICT,
  user_id uuid NOT NULL REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
  acknowledged_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  CONSTRAINT work_order_revision_receipt_unique
    UNIQUE (assignment_id, version_id, user_id)
);

CREATE INDEX work_order_revision_receipt_user_idx
  ON vinto_txn.work_order_revision_receipt(user_id, assignment_id);

CREATE FUNCTION vinto_txn.guard_work_order_revision_receipt()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor uuid;
DECLARE assigned_version uuid;
BEGIN
  IF TG_OP <> 'INSERT' THEN
    RAISE EXCEPTION 'Revision acknowledgement history is immutable'
      USING ERRCODE = '23514';
  END IF;

  actor := nullif(current_setting('vinto.actor_id', true), '')::uuid;
  IF actor IS NULL OR actor IS DISTINCT FROM NEW.user_id
     OR nullif(current_setting('vinto.reason', true), '') IS NULL
     OR nullif(current_setting('vinto.request_id', true), '') IS NULL THEN
    RAISE EXCEPTION 'Revision acknowledgement requires authenticated actor and audit context'
      USING ERRCODE = '23514';
  END IF;

  -- The assignment and its recorded version MUST still be active at insert.
  -- FOR SHARE prevents concurrent finishing from passing between validation
  -- and commit. Never trust client machine, sector, or version identifiers.
  SELECT l.work_order_version_id INTO assigned_version
    FROM vinto_txn.assignment a
    JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
    WHERE a.id=NEW.assignment_id AND a.status='active'
    FOR SHARE OF a;

  IF assigned_version IS NULL OR assigned_version IS DISTINCT FROM NEW.version_id
     OR NOT EXISTS (
       SELECT 1 FROM vinto_txn.work_order_version v
       WHERE v.id=NEW.version_id AND v.kind='operational'
         AND v.published_at IS NOT NULL AND v.reprogram_reason IS NOT NULL
     ) THEN
    RAISE EXCEPTION 'Revision acknowledgement is not a currently assigned published revision'
      USING ERRCODE = '23514';
  END IF;

  NEW.acknowledged_at := clock_timestamp();
  RETURN NEW;
END $$;

CREATE TRIGGER a_guard_work_order_revision_receipt
  BEFORE INSERT OR UPDATE OR DELETE ON vinto_txn.work_order_revision_receipt
  FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_work_order_revision_receipt();

CREATE TRIGGER immutable_truncate
  BEFORE TRUNCATE ON vinto_txn.work_order_revision_receipt
  FOR EACH STATEMENT EXECUTE FUNCTION vinto_audit.reject_mutation();

CREATE TRIGGER audit_changes
  AFTER INSERT ON vinto_txn.work_order_revision_receipt
  FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

REVOKE ALL ON vinto_txn.work_order_revision_receipt FROM PUBLIC;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vinto_app') THEN
    GRANT SELECT, INSERT ON vinto_txn.work_order_revision_receipt TO vinto_app;
  END IF;
END $$;

-- Guard rails against unwanted data mutation while applying the migration.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM vinto_txn.work_order_revision_receipt) THEN
    RAISE EXCEPTION '0017: unexpected receipt rows during additive migration';
  END IF;
END $$;
