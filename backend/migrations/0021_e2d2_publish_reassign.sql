-- E2-D2-B1.2: expand the audited handoff lifecycle, no data backfill.
-- B1.1 is immutable. This migration only authorizes pending -> published
-- and published -> reassigned after checking immutable OT version and
-- assignment links. B2 is responsible for operator acknowledgement.
CREATE OR REPLACE FUNCTION vinto_txn.guard_e2d2_handoff_b11()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE actor uuid; handoff_code text;
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'Handoff history cannot be deleted' USING ERRCODE='23514';
  END IF;
  actor := nullif(current_setting('vinto.actor_id', true),'')::uuid;
  IF actor IS NULL
    OR nullif(current_setting('vinto.request_id',true),'') IS NULL
    OR nullif(current_setting('vinto.reason',true),'') IS NULL THEN
    RAISE EXCEPTION 'Handoff requires authenticated audit context' USING ERRCODE='23514';
  END IF;

  IF TG_OP = 'INSERT' THEN
    IF NEW.status <> 'pending' OR NEW.requested_by IS DISTINCT FROM actor
      OR NEW.published_version_id IS NOT NULL OR NEW.replacement_assignment_id IS NOT NULL
      OR NEW.completed_at IS NOT NULL THEN
      RAISE EXCEPTION 'Handoff must begin as pending' USING ERRCODE='23514';
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
               AND v.kind='operational' AND v.published_at IS NOT NULL)
             = NEW.expected_version_number
        AND NOT EXISTS (
          SELECT 1 FROM vinto_txn.capture c
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

  -- Immutable identifier, prior assignment, expected version, supervisor
  -- and reason; the published/replacement references have tightly staged
  -- transitions below. Only update audit fields are otherwise mutable.
  IF ROW(NEW.id, NEW.work_order_id, NEW.baseline_line_id, NEW.machine_id,
         NEW.prior_assignment_id, NEW.expected_version_number,
         NEW.requested_by, NEW.reason, NEW.created_at, NEW.created_by)
      IS DISTINCT FROM
     ROW(OLD.id, OLD.work_order_id, OLD.baseline_line_id, OLD.machine_id,
         OLD.prior_assignment_id, OLD.expected_version_number,
         OLD.requested_by, OLD.reason, OLD.created_at, OLD.created_by)
  THEN
    RAISE EXCEPTION 'Handoff identity immutable' USING ERRCODE='23514';
  END IF;

  IF OLD.status='pending' AND NEW.status='cancelled' THEN
    IF NEW.published_version_id IS NOT NULL OR NEW.replacement_assignment_id IS NOT NULL
      OR NEW.completed_at IS NULL OR NEW.completed_at<OLD.created_at THEN
      RAISE EXCEPTION 'Invalid cancellation' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;

  SELECT bl.line_code INTO handoff_code
    FROM vinto_txn.work_order_line bl WHERE bl.id=OLD.baseline_line_id;

  IF OLD.status='pending' AND NEW.status='published' THEN
    IF NEW.completed_at IS NOT NULL OR NEW.replacement_assignment_id IS NOT NULL
      OR NEW.published_version_id IS NULL OR NOT EXISTS (
        SELECT 1 FROM vinto_txn.work_order_version v
        WHERE v.id=NEW.published_version_id
          AND v.work_order_id=OLD.work_order_id
          AND v.kind='operational'
          AND v.published_at IS NOT NULL
          AND v.version_number=OLD.expected_version_number+1
          AND v.reprogram_line_code=handoff_code
          AND EXISTS (
            SELECT 1 FROM vinto_txn.work_order_version base
            WHERE base.id=v.based_on_version_id
              AND base.work_order_id=v.work_order_id
              AND base.version_number=OLD.expected_version_number
          )
      ) THEN
      RAISE EXCEPTION 'Invalid published revision' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;

  IF OLD.status='published' AND NEW.status='reassigned' THEN
    IF NEW.completed_at IS NOT NULL
      OR NEW.published_version_id IS DISTINCT FROM OLD.published_version_id
      OR NEW.replacement_assignment_id IS NULL OR NOT EXISTS (
        SELECT 1 FROM vinto_txn.assignment a
        JOIN vinto_txn.work_order_line ol ON ol.id=a.work_order_line_id
        WHERE a.id=NEW.replacement_assignment_id AND a.status='active'
          AND a.machine_id=OLD.machine_id AND ol.machine_id=OLD.machine_id
          AND ol.work_order_version_id=OLD.published_version_id
          AND ol.line_code=handoff_code
      ) OR EXISTS (
        SELECT 1 FROM vinto_txn.assignment a
        WHERE a.id=OLD.prior_assignment_id AND a.status='active'
      ) THEN
      RAISE EXCEPTION 'Invalid reassignment' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
  END IF;

  RAISE EXCEPTION 'Forbidden handoff transition' USING ERRCODE='23514';
END $$;

-- OT versions are global; only one open D2 handoff per OT can hold
-- a well-defined expected version. Prevent independent lines from ending
-- with a stale published/reassigned reservation.
CREATE UNIQUE INDEX e2d2_one_open_handoff_per_order
 ON vinto_txn.work_order_line_reprogram_handoff (work_order_id)
 WHERE status IN ('pending','published','reassigned');

DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vinto_app') THEN
  GRANT UPDATE (published_version_id,replacement_assignment_id)
  ON vinto_txn.work_order_line_reprogram_handoff TO vinto_app;
 END IF;
END $$;

DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM vinto_txn.work_order_line_reprogram_handoff) THEN
  RAISE EXCEPTION '0021 requires empty handoff table during preproduction rollout';
 END IF;
END $$;
