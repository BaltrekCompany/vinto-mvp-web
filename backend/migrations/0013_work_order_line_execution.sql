-- E1-02 / VINTO: execution of a logical work-order line, distinct from shift assignment.
-- SQL candidate based on main 86e4ec4 (migrations 0001-0012). Not executed against production.
-- ATTENTION: additive migration only; no backfill, no changes to assignment/capture/OT.
-- E1-03 must enforce execution state in F3/F6 and assignment APIs before enabling the new feature.
-- The rollout flag MUST remain off until that backend and the UI are ready.

CREATE TABLE vinto_txn.work_order_line_execution (
 baseline_line_id uuid PRIMARY KEY
   REFERENCES vinto_txn.work_order_line(id) ON DELETE RESTRICT,
 work_order_id uuid NOT NULL
   REFERENCES vinto_txn.work_order(id) ON DELETE RESTRICT,
 machine_id uuid NOT NULL
   REFERENCES vinto_master.machine(id) ON DELETE RESTRICT,
 status text NOT NULL DEFAULT 'planned'
   CHECK (status IN ('planned','enabled','in_production','finished')),
 started_at timestamptz,
 started_by uuid REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
 finished_at timestamptz,
 finished_by uuid REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
 created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 created_by uuid REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
 updated_by uuid REFERENCES vinto_master."user"(id) ON DELETE RESTRICT,
 CONSTRAINT work_order_line_execution_timestamps_check CHECK (
   (status IN ('planned','enabled') AND started_at IS NULL AND started_by IS NULL AND finished_at IS NULL AND finished_by IS NULL)
   OR
   (status = 'in_production' AND started_at IS NOT NULL AND started_by IS NOT NULL AND finished_at IS NULL AND finished_by IS NULL)
   OR
   (status = 'finished' AND started_at IS NOT NULL AND started_by IS NOT NULL AND finished_at IS NOT NULL AND finished_by IS NOT NULL
     AND finished_at >= started_at)
 )
);

-- One machine can produce only one logical line at a time. Other enabled rows are allowed.
-- The unique partial index, unlike an application-only lock, protects concurrent and direct SQL writers.
CREATE UNIQUE INDEX work_order_line_execution_one_producing_machine
 ON vinto_txn.work_order_line_execution (machine_id) WHERE status = 'in_production';
CREATE INDEX work_order_line_execution_work_order_idx
 ON vinto_txn.work_order_line_execution (work_order_id);

-- Protect immutable identity and server-controlled lifecycle. The baseline is the immutable
-- version_number=1 line; operational copies are never used as the logical identity.
CREATE FUNCTION vinto_txn.guard_work_order_line_execution() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source_order uuid; source_machine uuid;
BEGIN
 IF TG_OP = 'DELETE' THEN
   RAISE EXCEPTION 'Logical line execution history cannot be deleted' USING ERRCODE = '23514';
 END IF;
 SELECT v.work_order_id, l.machine_id INTO source_order, source_machine
 FROM vinto_txn.work_order_line l
 JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
 WHERE l.id = NEW.baseline_line_id AND v.kind = 'baseline' AND v.version_number = 1;
 IF NOT FOUND OR source_order IS DISTINCT FROM NEW.work_order_id OR source_machine IS DISTINCT FROM NEW.machine_id THEN
   RAISE EXCEPTION 'Execution must reference the matching baseline line / OT / machine' USING ERRCODE = '23514';
 END IF;

 IF TG_OP = 'INSERT' THEN
   IF NEW.status <> 'planned' OR NEW.started_at IS NOT NULL OR NEW.started_by IS NOT NULL
      OR NEW.finished_at IS NOT NULL OR NEW.finished_by IS NOT NULL THEN
     RAISE EXCEPTION 'New logical line execution must begin as planned' USING ERRCODE = '23514';
   END IF;
   RETURN NEW;
 END IF;

 IF NEW.baseline_line_id IS DISTINCT FROM OLD.baseline_line_id
    OR NEW.work_order_id IS DISTINCT FROM OLD.work_order_id
    OR NEW.machine_id IS DISTINCT FROM OLD.machine_id THEN
   RAISE EXCEPTION 'Logical line execution identity is immutable' USING ERRCODE = '23514';
 END IF;
 IF NOT (
    (OLD.status = 'planned' AND NEW.status = 'enabled')
    OR (OLD.status = 'enabled' AND NEW.status = 'in_production')
    OR (OLD.status = 'in_production' AND NEW.status = 'finished')
 ) THEN
   RAISE EXCEPTION 'Invalid logical line execution transition' USING ERRCODE = '23514';
 END IF;
 IF OLD.started_at IS DISTINCT FROM NEW.started_at AND OLD.started_at IS NOT NULL THEN
   RAISE EXCEPTION 'Execution start timestamp is immutable' USING ERRCODE = '23514';
 END IF;
 IF OLD.started_by IS DISTINCT FROM NEW.started_by AND OLD.started_by IS NOT NULL THEN
   RAISE EXCEPTION 'Execution start actor is immutable' USING ERRCODE = '23514';
 END IF;
 IF OLD.finished_at IS DISTINCT FROM NEW.finished_at OR OLD.finished_by IS DISTINCT FROM NEW.finished_by THEN
   IF NEW.status <> 'finished' OR OLD.status <> 'in_production' THEN
     RAISE EXCEPTION 'Execution end values can only be set on finalization' USING ERRCODE = '23514';
   END IF;
 END IF;
 -- The future backend MUST take the existing machine advisory lock before issuing this UPDATE.
 -- No advisory lock inside this trigger: PostgreSQL already holds the UPDATE row lock
 -- when a BEFORE trigger runs, so locking the machine here could invert the lock order
 -- against capture_service (machine -> execution row) and cause a deadlock.
 -- The partial UNIQUE index above is the independent SQL-level exclusivity guarantee.
 RETURN NEW;
END $$;

CREATE TRIGGER a_guard_work_order_line_execution
 BEFORE INSERT OR UPDATE OR DELETE ON vinto_txn.work_order_line_execution
 FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_work_order_line_execution();
CREATE TRIGGER immutable_truncate
 BEFORE TRUNCATE ON vinto_txn.work_order_line_execution
 FOR EACH STATEMENT EXECUTE FUNCTION vinto_audit.reject_mutation();
CREATE TRIGGER z_touch
 BEFORE INSERT OR UPDATE ON vinto_txn.work_order_line_execution
 FOR EACH ROW EXECUTE FUNCTION vinto_audit.touch_row();
CREATE TRIGGER audit_changes
 AFTER INSERT OR UPDATE OR DELETE ON vinto_txn.work_order_line_execution
 FOR EACH ROW EXECUTE FUNCTION vinto_audit.record_change();

-- Least-privilege convention of migrations 0007+: allow only the application role,
-- and only where that role exists (local / synthetic test DBs may not provision it).
REVOKE ALL ON vinto_txn.work_order_line_execution FROM PUBLIC;
DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_app') THEN
   GRANT SELECT, INSERT, UPDATE ON vinto_txn.work_order_line_execution TO vinto_app;
 END IF;
END $$;

DO $$
BEGIN
 IF to_regclass('vinto_txn.work_order_line_execution_one_producing_machine') IS NULL THEN
   RAISE EXCEPTION '0013: missing unique machine execution index';
 END IF;
 IF NOT EXISTS (
   SELECT 1 FROM pg_trigger
   WHERE tgrelid = 'vinto_txn.work_order_line_execution'::regclass
     AND tgname = 'a_guard_work_order_line_execution' AND tgenabled = 'O'
 ) THEN
   RAISE EXCEPTION '0013: missing enabled lifecycle guard';
 END IF;
 IF EXISTS (SELECT 1 FROM vinto_txn.work_order_line_execution) THEN
   RAISE EXCEPTION '0013: unexpected data mutation during additive migration';
 END IF;
END $$;
