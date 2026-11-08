-- E2-D2-B0: additive handoff reservation storage for supervised pre-start reprogramming.
-- No backfill, no updates to OT, E1, assignment, F3/F6, or receipt history.
-- In this phase the application role can only SELECT. No production reservation
-- can be created by the API until B1 adds an audited, guarded writer.
CREATE TABLE vinto_txn.work_order_line_reprogram_handoff (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    work_order_id uuid NOT NULL REFERENCES vinto_txn.work_order(id) ON DELETE RESTRICT,
    baseline_line_id uuid NOT NULL REFERENCES vinto_txn.work_order_line(id) ON DELETE RESTRICT,
    machine_id uuid NOT NULL REFERENCES vinto_master.machine(id) ON DELETE RESTRICT,
    prior_assignment_id uuid NOT NULL REFERENCES vinto_txn.assignment(id) ON DELETE RESTRICT,
    expected_version_number integer NOT NULL CHECK (expected_version_number >= 2),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'published', 'reassigned', 'acknowledged', 'cancelled')),
    requested_by uuid NOT NULL REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
    reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 10 AND 300),
    published_version_id uuid REFERENCES vinto_txn.work_order_version(id) ON DELETE RESTRICT,
    replacement_assignment_id uuid REFERENCES vinto_txn.assignment(id) ON DELETE RESTRICT,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    created_by uuid REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
    updated_by uuid REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
    CONSTRAINT e2d2_handoff_pending_version_check CHECK (
      (status = 'pending' AND published_version_id IS NULL AND replacement_assignment_id IS NULL)
      OR (status IN ('published', 'reassigned', 'acknowledged', 'cancelled'))
    ),
    CONSTRAINT e2d2_handoff_reassignment_check CHECK (
      replacement_assignment_id IS NULL OR published_version_id IS NOT NULL
    )
);

-- One outstanding handoff per immutable baseline line. This also prevents
-- duplicate in-flight reservations across different operational OT versions.
CREATE UNIQUE INDEX e2d2_handoff_one_open_per_line
 ON vinto_txn.work_order_line_reprogram_handoff (baseline_line_id)
 WHERE status IN ('pending', 'published', 'reassigned');

CREATE INDEX e2d2_handoff_ot_status_idx
 ON vinto_txn.work_order_line_reprogram_handoff (work_order_id, status);

-- Standard VINTO audit; later B1 must additionally validate each transition
-- and identity under OT -> machine -> assignment -> E1 -> handoff locks.
CREATE TRIGGER z_touch
 BEFORE INSERT OR UPDATE ON vinto_txn.work_order_line_reprogram_handoff
 FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();

CREATE TRIGGER audit_changes
 AFTER INSERT OR UPDATE OR DELETE ON vinto_txn.work_order_line_reprogram_handoff
 FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

REVOKE ALL ON vinto_txn.work_order_line_reprogram_handoff FROM PUBLIC;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_app') THEN
    GRANT SELECT ON vinto_txn.work_order_line_reprogram_handoff TO vinto_app;
    -- Deliberately NO INSERT/UPDATE/DELETE until B1 transaction writer is approved.
  END IF;
END $$;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM vinto_txn.work_order_line_reprogram_handoff) THEN
    RAISE EXCEPTION '0019 must not create reservation rows';
  END IF;
END $$;
