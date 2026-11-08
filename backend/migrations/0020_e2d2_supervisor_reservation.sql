-- E2-D2-B1.1: auditable supervisor reservation and cancellation only.
-- Built on immutable migration 0019. No production writes or backfill.
-- D2 remains OFF by default; Jefatura publish / reassignment / receipts remain
-- OUT OF SCOPE and will be separate PRs.
ALTER TABLE vinto_txn.work_order_line_reprogram_handoff
 ADD CONSTRAINT e2d2_b11_pending_cancelled_timestamps CHECK (
   (status='pending' AND completed_at IS NULL)
   OR (status='cancelled' AND completed_at IS NOT NULL)
   OR (status IN ('published','reassigned','acknowledged'))
 );

CREATE FUNCTION vinto_txn.guard_e2d2_handoff_b11()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor uuid;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Handoff history cannot be deleted' USING ERRCODE='23514';
  END IF;

  actor := nullif(current_setting('vinto.actor_id', true), '')::uuid;
  IF actor IS NULL
      OR nullif(current_setting('vinto.request_id', true), '') IS NULL
      OR nullif(current_setting('vinto.reason', true), '') IS NULL THEN
    RAISE EXCEPTION 'Handoff requires authenticated audit context' USING ERRCODE='23514';
  END IF;

  IF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'pending' OR NEW.requested_by IS DISTINCT FROM actor
      OR NEW.published_version_id IS NOT NULL OR NEW.replacement_assignment_id IS NOT NULL
      OR NEW.completed_at IS NOT NULL THEN
      RAISE EXCEPTION 'Handoff must begin as supervised pending' USING ERRCODE='23514';
    END IF;

    IF NOT EXISTS (
      SELECT 1
      FROM vinto_txn.work_order w
      JOIN vinto_txn.work_order_line bl ON bl.id=NEW.baseline_line_id
      JOIN vinto_txn.work_order_version bv
        ON bv.id=bl.work_order_version_id AND bv.kind='baseline'
        AND bv.version_number=1 AND bv.published_at IS NOT NULL
      JOIN vinto_txn.assignment a ON a.id=NEW.prior_assignment_id
        AND a.status='active' AND a.machine_id=NEW.machine_id
      JOIN vinto_txn.work_order_line ol ON ol.id=a.work_order_line_id
        AND ol.line_code=bl.line_code AND ol.machine_id=NEW.machine_id
      JOIN vinto_txn.work_order_version ov ON ov.id=ol.work_order_version_id
        AND ov.kind='operational' AND ov.published_at IS NOT NULL
      JOIN vinto_txn.work_order_line_execution e ON e.baseline_line_id=bl.id
        AND e.work_order_id=w.id AND e.machine_id=NEW.machine_id
        AND e.status='enabled' AND e.started_at IS NULL
      WHERE w.id=NEW.work_order_id AND bv.work_order_id=w.id
        AND ov.work_order_id=w.id AND w.status='in_progress'
        AND w.archived_at IS NULL AND NOT w.qa_retired
        AND bl.machine_id=NEW.machine_id
        AND (SELECT MAX(v.version_number)
             FROM vinto_txn.work_order_version v
             WHERE v.work_order_id=w.id
               AND v.kind='operational'
               AND v.published_at IS NOT NULL) = NEW.expected_version_number
        AND NOT EXISTS (
          SELECT 1
          FROM vinto_txn.capture c
          JOIN vinto_txn.assignment ca ON ca.id=c.assignment_id
          JOIN vinto_txn.work_order_line cl ON cl.id=ca.work_order_line_id
          JOIN vinto_txn.work_order_version cv ON cv.id=cl.work_order_version_id
          WHERE cv.work_order_id=w.id AND cl.line_code=bl.line_code
        )
    ) THEN
      RAISE EXCEPTION 'Handoff target not eligible' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;

  -- B1.1 only permits cancellation. B1.2 will add audited progress states.
  IF OLD.status <> 'pending' OR NEW.status <> 'cancelled'
    OR NEW.completed_at IS NULL OR NEW.completed_at < OLD.created_at
    OR ROW(NEW.id, NEW.work_order_id, NEW.baseline_line_id, NEW.machine_id,
           NEW.prior_assignment_id, NEW.expected_version_number,
           NEW.requested_by, NEW.reason, NEW.published_version_id,
           NEW.replacement_assignment_id, NEW.created_at, NEW.created_by)
       IS DISTINCT FROM
       ROW(OLD.id, OLD.work_order_id, OLD.baseline_line_id, OLD.machine_id,
           OLD.prior_assignment_id, OLD.expected_version_number,
           OLD.requested_by, OLD.reason, OLD.published_version_id,
           OLD.replacement_assignment_id, OLD.created_at, OLD.created_by)
  THEN
    RAISE EXCEPTION 'Handoff transition or identity change forbidden'
      USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER a_guard_e2d2_handoff_b11
 BEFORE INSERT OR UPDATE OR DELETE
 ON vinto_txn.work_order_line_reprogram_handoff
 FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_e2d2_handoff_b11();

CREATE TRIGGER immutable_truncate
 BEFORE TRUNCATE ON vinto_txn.work_order_line_reprogram_handoff
 FOR EACH STATEMENT EXECUTE FUNCTION vinto_audit.reject_mutation();

-- The user role can only initiate guarded reservations/cancel pending.
-- B1.1 grants neither DELETE nor unrestricted UPDATE (B1.2 requires a
-- separate migration for additional progress states).
DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vinto_app') THEN
  GRANT INSERT ON vinto_txn.work_order_line_reprogram_handoff TO vinto_app;
  GRANT UPDATE (status, completed_at)
    ON vinto_txn.work_order_line_reprogram_handoff TO vinto_app;
 END IF;
END $$;

DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM vinto_txn.work_order_line_reprogram_handoff) THEN
   RAISE EXCEPTION '0020 unexpectedly found pre-existing handoffs';
 END IF;
END $$;
