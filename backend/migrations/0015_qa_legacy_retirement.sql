-- E1-10: explicit, auditable retirement of historical QA-only work orders.
-- Leaves OT status, versions, captures, assignments, bobbins and quality history unchanged.
-- The retirement CLI finishes *active shift assignments* first and then archives
-- eligible QA orders in one transaction. This is not a logical line completion.
-- NEVER run this migration as a stand-alone UPDATE of existing data.

ALTER TABLE vinto_txn.work_order
  ADD COLUMN qa_retired boolean NOT NULL DEFAULT false;

ALTER TABLE vinto_txn.work_order
  ADD CONSTRAINT work_order_qa_retirement_archive_chk
  CHECK (NOT qa_retired OR (status='in_progress' AND archived_at IS NOT NULL));

-- Preserve the regular archive contract from 0014. Only the exceptional
-- transition false -> true while archiving an in_progress QA OT is newly allowed.
-- Restoration of QA-retired legacy OTs is prohibited through ordinary workflows:
-- it would revive an in_progress OT without logical E1 execution state.
CREATE OR REPLACE FUNCTION vinto_txn.guard_work_order_archive()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor uuid;
BEGIN
  IF TG_OP = 'DELETE' THEN
    IF OLD.archived_at IS NOT NULL OR OLD.qa_retired THEN
      RAISE EXCEPTION 'Archived work order cannot be deleted' USING ERRCODE='23514';
    END IF;
    RETURN OLD;
  END IF;

  IF TG_OP = 'INSERT' THEN
    IF NEW.archived_at IS NOT NULL OR NEW.archived_by IS NOT NULL
       OR NEW.archived_reason IS NOT NULL OR NEW.qa_retired THEN
      RAISE EXCEPTION 'Archive metadata cannot be set on insert' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;

  IF OLD.qa_retired THEN
    RAISE EXCEPTION 'QA-retired historical work order is immutable and cannot be restored by ordinary workflows'
      USING ERRCODE='23514';
  END IF;

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
       OR length(btrim(coalesce(NEW.archived_reason,''))) NOT BETWEEN 10 AND 300 THEN
      RAISE EXCEPTION 'Archive requires actor and valid reason' USING ERRCODE='23514';
    END IF;

    IF NEW.qa_retired THEN
      -- Exception for historical QA only; the application exposes no endpoint
      -- to perform it. The operator supplies a closed, reviewed manifest.
      IF OLD.status <> 'in_progress' THEN
        RAISE EXCEPTION 'QA retirement requires an in-progress work order' USING ERRCODE='23514';
      END IF;
      IF EXISTS (
        SELECT 1 FROM vinto_txn.assignment a
        JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
        JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
        WHERE v.work_order_id=OLD.id AND a.status='active'
      ) THEN
        RAISE EXCEPTION 'QA retirement cannot retain active assignments' USING ERRCODE='23514';
      END IF;
      IF EXISTS (
        SELECT 1 FROM vinto_txn.work_order_line_execution e
        WHERE e.work_order_id=OLD.id
      ) THEN
        RAISE EXCEPTION 'QA retirement does not apply to a work order with E1 execution' USING ERRCODE='23514';
      END IF;
    ELSE
      IF OLD.status NOT IN ('draft','published') THEN
        RAISE EXCEPTION 'Ordinary archive requires draft/published order' USING ERRCODE='23514';
      END IF;
      IF EXISTS (
        SELECT 1 FROM vinto_txn.assignment a
        JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
        JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
        WHERE v.work_order_id=OLD.id
      ) THEN
        RAISE EXCEPTION 'Work order with assignments cannot be archived' USING ERRCODE='23514';
      END IF;
    END IF;
    RETURN NEW;

  ELSIF OLD.archived_at IS NOT NULL AND NEW.archived_at IS NULL THEN
    actor := nullif(current_setting('vinto.actor_id',true),'')::uuid;
    IF actor IS NULL OR NEW.archived_by IS NOT NULL OR NEW.archived_reason IS NOT NULL
       OR NEW.qa_retired THEN
      RAISE EXCEPTION 'Restore requires actor and cleared archive metadata' USING ERRCODE='23514';
    END IF;
    RETURN NEW;

  ELSIF OLD.archived_at IS NOT NULL THEN
    RAISE EXCEPTION 'Archived work order must be restored before modification' USING ERRCODE='23514';
  END IF;

  IF NEW.qa_retired IS DISTINCT FROM OLD.qa_retired THEN
    RAISE EXCEPTION 'QA retirement flag requires atomic archive' USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;

-- Existing a_guard_archive trigger (0014) reuses the updated function.
-- Existing a_guard_archive_assignment prevents any NEW assignment for an
-- archived OT. Existing version/line archive triggers remain enabled.
