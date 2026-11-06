-- E1-09: archival/restore metadata for completed TEST scenarios, distinct from the
-- physical/logical work-order lifecycle. No backfill; all existing orders
-- remain active (unarchived). Requires 0013 first due to ordered migrations.
-- Never DELETE OT/captures, never mutate assignment status, keep E1 flag OFF.
ALTER TABLE vinto_txn.work_order
  ADD COLUMN archived_at timestamptz,
  ADD COLUMN archived_by uuid REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
  ADD COLUMN archived_reason text;

ALTER TABLE vinto_txn.work_order
  ADD CONSTRAINT work_order_archive_metadata_chk
  CHECK (
    (archived_at IS NULL AND archived_by IS NULL AND archived_reason IS NULL)
    OR
    (archived_at IS NOT NULL AND archived_by IS NOT NULL
      AND archived_reason IS NOT NULL
      AND length(btrim(archived_reason)) BETWEEN 10 AND 300)
  );
CREATE INDEX work_order_archive_active_idx
  ON vinto_txn.work_order(created_at DESC, number DESC)
  WHERE archived_at IS NULL;

-- Archive/restore is possible only for draft/published orders with no
-- assignment ever created; explicitly excludes 12 legacy in_progress OTs.
-- Server-side actor must match archival metadata. Audit trigger from 0001
-- retains all old/new metadata even after the order is restored.
CREATE FUNCTION vinto_txn.guard_work_order_archive()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor uuid;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.archived_at IS NOT NULL THEN
      RAISE EXCEPTION 'Archived work order cannot be deleted' USING ERRCODE='23514';
    END IF;
    RETURN OLD;
  END IF;
  IF TG_OP = 'INSERT' THEN
    IF NEW.archived_at IS NOT NULL OR NEW.archived_by IS NOT NULL
       OR NEW.archived_reason IS NOT NULL THEN
      RAISE EXCEPTION 'Archive metadata cannot be set on insert' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;

  -- A generic UPDATE must never bypass the archive lifecycle by editing
  -- the order identity/status alongside archive metadata.
  IF OLD.archived_at IS NOT NULL OR NEW.archived_at IS NOT NULL THEN
    IF NEW.id IS DISTINCT FROM OLD.id OR NEW.number IS DISTINCT FROM OLD.number
       OR NEW.machine_id IS DISTINCT FROM OLD.machine_id
       OR NEW.status IS DISTINCT FROM OLD.status THEN
      RAISE EXCEPTION 'Archive update cannot alter work order identity/status' USING ERRCODE='23514';
    END IF;
  END IF;

  IF OLD.archived_at IS NULL AND NEW.archived_at IS NOT NULL THEN
    actor := nullif(current_setting('vinto.actor_id',true),'')::uuid;
    IF actor IS NULL OR actor IS DISTINCT FROM NEW.archived_by
       OR OLD.status NOT IN ('draft','published')
       OR length(btrim(coalesce(NEW.archived_reason,''))) NOT BETWEEN 10 AND 300 THEN
      RAISE EXCEPTION 'Archive requires actor, reason and draft/published order' USING ERRCODE='23514';
    END IF;
    IF EXISTS (
      SELECT 1 FROM vinto_txn.assignment a
      JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
      JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
      WHERE v.work_order_id=OLD.id
    ) THEN
      RAISE EXCEPTION 'Work order with assignments cannot be archived' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  ELSIF OLD.archived_at IS NOT NULL AND NEW.archived_at IS NULL THEN
    -- Restoration must clear all archive metadata; full audit remains.
    actor := nullif(current_setting('vinto.actor_id',true),'')::uuid;
    IF actor IS NULL OR NEW.archived_by IS NOT NULL OR NEW.archived_reason IS NOT NULL THEN
      RAISE EXCEPTION 'Restore requires actor and cleared archive metadata' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  ELSIF OLD.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'Archived work order must be restored before modification' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER a_guard_archive
  BEFORE INSERT OR UPDATE OR DELETE ON vinto_txn.work_order
  FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_work_order_archive();

-- DB-level safety even against direct assignment INSERT/UPDATE, not only the
-- API. FOR SHARE serializes with the parent order's archive UPDATE, so a
-- concurrent activation cannot slip in after an archive transaction commits.
CREATE FUNCTION vinto_txn.guard_assignment_archive()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE archived timestamptz;
BEGIN
  SELECT wo.archived_at INTO archived
  FROM vinto_txn.work_order_line l
  JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
  JOIN vinto_txn.work_order wo ON wo.id=v.work_order_id
  WHERE l.id=NEW.work_order_line_id
  FOR SHARE OF wo;
  IF archived IS NOT NULL THEN
    RAISE EXCEPTION 'Archived work order cannot receive assignment writes' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER a_guard_archive_assignment
  BEFORE INSERT OR UPDATE ON vinto_txn.assignment
  FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_assignment_archive();

-- Guard baseline/operational descendants, even for direct SQL writers.
-- We do not delete or alter any existing version/line.
CREATE FUNCTION vinto_txn.guard_work_order_version_archive()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE parent_id uuid; archived timestamptz;
BEGIN
  IF TG_OP = 'DELETE' THEN parent_id := OLD.work_order_id;
  ELSE parent_id := NEW.work_order_id;
  END IF;
  SELECT archived_at INTO archived
    FROM vinto_txn.work_order WHERE id=parent_id FOR SHARE;
  IF archived IS NOT NULL THEN
    RAISE EXCEPTION 'Archived work order version is immutable' USING ERRCODE='23514';
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.work_order_id IS DISTINCT FROM NEW.work_order_id THEN
    SELECT archived_at INTO archived
      FROM vinto_txn.work_order WHERE id=OLD.work_order_id FOR SHARE;
    IF archived IS NOT NULL THEN
      RAISE EXCEPTION 'Archived work order version cannot be moved' USING ERRCODE='23514';
    END IF;
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER a_guard_archive_version
  BEFORE INSERT OR UPDATE OR DELETE ON vinto_txn.work_order_version
  FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_work_order_version_archive();

CREATE FUNCTION vinto_txn.guard_work_order_line_archive()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version_id uuid; archived timestamptz;
BEGIN
  IF TG_OP = 'DELETE' THEN version_id := OLD.work_order_version_id;
  ELSE version_id := NEW.work_order_version_id;
  END IF;
  SELECT wo.archived_at INTO archived
  FROM vinto_txn.work_order_version v
  JOIN vinto_txn.work_order wo ON wo.id=v.work_order_id
  WHERE v.id=version_id FOR SHARE OF wo;
  IF archived IS NOT NULL THEN
    RAISE EXCEPTION 'Archived work order line is immutable' USING ERRCODE='23514';
  END IF;
  IF TG_OP = 'UPDATE' AND OLD.work_order_version_id IS DISTINCT FROM NEW.work_order_version_id THEN
    SELECT wo.archived_at INTO archived
    FROM vinto_txn.work_order_version v
    JOIN vinto_txn.work_order wo ON wo.id=v.work_order_id
    WHERE v.id=OLD.work_order_version_id FOR SHARE OF wo;
    IF archived IS NOT NULL THEN
      RAISE EXCEPTION 'Archived work order line cannot be moved' USING ERRCODE='23514';
    END IF;
  END IF;
  IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER a_guard_archive_line
  BEFORE INSERT OR UPDATE OR DELETE ON vinto_txn.work_order_line
  FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_work_order_line_archive();

-- The work_order table already has UPDATE privileges for vinto_app; no new
-- table, role or default grant is created. Existing audit_events are immutable.
