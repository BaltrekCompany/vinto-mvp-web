-- 0011 MF13-03.B PR3: several active assignments of the SAME work order on one machine.
--
-- Until 0010 the database guaranteed "one active assignment per machine" with the partial unique index
-- assignment_one_active_machine. That is stronger than the business rule: a machine may have several lines of ONE work
-- order available at the same time (activation = available for Operación to pick, not simultaneous production), but never
-- lines of two different work orders. A unique index cannot express "same work order" (the order is reached through
-- line -> version), so the rule moves to a trigger that is serialised per machine:
--
--   1. assignment_one_active_line (unique, partial): a line has at most one active assignment.
--   2. validate_assignment_exclusivity (BEFORE INSERT OR UPDATE): under the SAME per-machine advisory lock the backend
--      takes (key = first 8 bytes of sha256('vinto-assignment-machine:<machine id>'), re-entrant for the same session),
--      rejects an active assignment when the machine already has an active assignment of ANOTHER work order (SQLSTATE
--      23P01), or when the same logical line (work order + line_code) is already active (23505). Taking the lock inside the
--      trigger makes the check safe for direct SQL writers and for two concurrent transactions at READ COMMITTED, because
--      the lookup runs only after the previous holder committed.
--   3. Identity columns of an assignment are immutable and a finished assignment is never reactivated (23514), so history
--      and the composite FK from capture cannot be rewritten.
--
-- The old index is dropped only after (1) and (2) exist, in the same transaction. Existing data satisfies the new rules
-- (a machine had at most one active row, and a line belongs to exactly one machine since 0010), which is verified below.
-- With WORK_ORDERS_MULTI_MACHINE_ENABLED off the backend still keeps one active assignment per machine by replacing the
-- previous one, so the deployed behaviour does not change.
-- Rollback: backend/rollbacks/0011_assignment_same_work_order_lines_rollback.sql (refuses when a machine has 2+ active rows).

-- 0. Pre-conditions: the data to be protected by the new rules is already consistent.
DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM vinto_txn.assignment WHERE status = 'active' GROUP BY work_order_line_id HAVING count(*) > 1) THEN
   RAISE EXCEPTION '0011 aborted: a line has more than one active assignment';
 END IF;
 IF EXISTS (SELECT 1 FROM vinto_txn.assignment a
              JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
              JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
             WHERE a.status = 'active' GROUP BY a.machine_id HAVING count(DISTINCT v.work_order_id) > 1) THEN
   RAISE EXCEPTION '0011 aborted: a machine has active assignments of different work orders';
 END IF;
END $$;

-- 1. Replacement protections first.
CREATE UNIQUE INDEX assignment_one_active_line ON vinto_txn.assignment (work_order_line_id) WHERE status = 'active';
CREATE INDEX assignment_active_machine_idx ON vinto_txn.assignment (machine_id) WHERE status = 'active';

CREATE FUNCTION vinto_txn.validate_assignment_exclusivity() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE new_order uuid; new_code text;
BEGIN
 IF TG_OP = 'UPDATE' THEN
   IF OLD.status = 'finished' AND NEW.status <> 'finished' THEN
     RAISE EXCEPTION 'A finished assignment cannot be reactivated' USING ERRCODE = '23514';
   END IF;
   IF NEW.work_order_line_id <> OLD.work_order_line_id OR NEW.machine_id <> OLD.machine_id
      OR NEW.shift_schedule_id <> OLD.shift_schedule_id OR NEW.operating_date <> OLD.operating_date
      OR NEW.assigned_by <> OLD.assigned_by THEN
     RAISE EXCEPTION 'Assignment identity columns are immutable' USING ERRCODE = '23514';
   END IF;
 END IF;
 IF NEW.status <> 'active' THEN
   RETURN NEW;
 END IF;
 -- Same key as app.assignments.service._machine_lock: re-entrant inside the backend transaction, and the only
 -- serialisation point for any other writer.
 PERFORM pg_advisory_xact_lock(('x' || substr(encode(sha256(convert_to('vinto-assignment-machine:' || NEW.machine_id::text, 'UTF8')), 'hex'), 1, 16))::bit(64)::bigint);
 SELECT v.work_order_id, l.line_code INTO new_order, new_code
   FROM vinto_txn.work_order_line l JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
  WHERE l.id = NEW.work_order_line_id;
 IF EXISTS (SELECT 1 FROM vinto_txn.assignment a
              JOIN vinto_txn.work_order_line al ON al.id = a.work_order_line_id
              JOIN vinto_txn.work_order_version av ON av.id = al.work_order_version_id
             WHERE a.machine_id = NEW.machine_id AND a.status = 'active' AND a.id <> NEW.id AND av.work_order_id <> new_order) THEN
   RAISE EXCEPTION 'The machine already has active assignments of another work order' USING ERRCODE = '23P01';
 END IF;
 IF EXISTS (SELECT 1 FROM vinto_txn.assignment a
              JOIN vinto_txn.work_order_line al ON al.id = a.work_order_line_id
              JOIN vinto_txn.work_order_version av ON av.id = al.work_order_version_id
             WHERE a.status = 'active' AND a.id <> NEW.id AND av.work_order_id = new_order AND al.line_code = new_code) THEN
   RAISE EXCEPTION 'The line already has an active assignment' USING ERRCODE = '23505';
 END IF;
 RETURN NEW;
END $$;

-- Fires after validate_assignment (alphabetical order) and before z_touch.
CREATE TRIGGER validate_assignment_exclusivity BEFORE INSERT OR UPDATE ON vinto_txn.assignment
 FOR EACH ROW EXECUTE FUNCTION vinto_txn.validate_assignment_exclusivity();

-- 2. Only now the old protection goes away.
DROP INDEX vinto_txn.assignment_one_active_machine;

-- 3. Post-conditions.
DO $$
BEGIN
 IF to_regclass('vinto_txn.assignment_one_active_line') IS NULL OR to_regclass('vinto_txn.assignment_one_active_machine') IS NOT NULL THEN
   RAISE EXCEPTION '0011 aborted: assignment indexes are not in the expected state';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'validate_assignment_exclusivity' AND tgrelid = 'vinto_txn.assignment'::regclass AND tgenabled = 'O') THEN
   RAISE EXCEPTION '0011 aborted: exclusivity trigger is not enabled';
 END IF;
END $$;
