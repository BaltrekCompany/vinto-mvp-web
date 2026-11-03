-- 0012 MF13-03.B: database-side guard for "one active assignment per machine" while the multi-machine gate is OFF.
--
-- Since 0011 the database only enforces the gate-ON rules (a line has one active assignment; a machine never mixes work
-- orders). The gate-OFF rule ("a machine has ONE active assignment; activating another one replaces it") lived only in
-- the application, and PostgreSQL cannot observe WORK_ORDERS_MULTI_MACHINE_ENABLED (it is a server setting of the backend
-- process). A plain unique index would also forbid the legitimate gate-ON state, so it is not an option.
--
-- Design: the backend declares the mode of the transaction that writes an assignment through the transaction-local setting
-- vinto.assignment_multi_line ('on' | 'off'), set in app.assignments.service._activate_target (the only INSERT path).
-- The trigger is FAIL-SAFE: anything other than exactly 'on' (unset, 'off', garbage, an old backend, a direct SQL writer)
-- is treated as single-assignment mode, so a second active assignment on a machine is rejected (SQLSTATE 23P01). Only an
-- explicit 'on' relaxes it, and then the 0011 rules still apply. It runs under the SAME per-machine advisory lock as the
-- backend and trigger 0011 (re-entrant), so two concurrent activations cannot both pass the check.
--
-- Scope and limits (be honest about them): this protects against defects and unaware writers, not against a privileged
-- session that deliberately sets the setting to 'on'; the setting is asserted by the application, not read from
-- the real gate. INSERT only: finishing rows, and updating or reading existing rows (even a machine that still has
-- several active rows from a period with the gate on) is never blocked, and no existing data is read, changed or
-- rejected by this migration. The legitimate replace flow (finish previous, then insert) passes because the previous row is
-- already finished when the INSERT runs.
-- Rollback: backend/rollbacks/0012_assignment_single_mode_guard_rollback.sql (always possible; touches no data).
-- Pre-check (read only, optional): backend/preflights/0012_assignment_single_mode_preflight.sql.

CREATE FUNCTION vinto_txn.validate_assignment_single_mode() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.status <> 'active' OR coalesce(current_setting('vinto.assignment_multi_line', true), '') = 'on' THEN
   RETURN NEW;
 END IF;
 -- Same key as app.assignments.service._machine_lock and trigger 0011.
 PERFORM pg_advisory_xact_lock(('x' || substr(encode(sha256(convert_to('vinto-assignment-machine:' || NEW.machine_id::text, 'UTF8')), 'hex'), 1, 16))::bit(64)::bigint);
 IF EXISTS (SELECT 1 FROM vinto_txn.assignment a WHERE a.machine_id = NEW.machine_id AND a.status = 'active' AND a.id <> NEW.id) THEN
   RAISE EXCEPTION 'The machine already has an active assignment and multi-line mode is not declared' USING ERRCODE = '23P01';
 END IF;
 RETURN NEW;
END $$;

CREATE TRIGGER validate_assignment_single_mode BEFORE INSERT ON vinto_txn.assignment
 FOR EACH ROW EXECUTE FUNCTION vinto_txn.validate_assignment_single_mode();

DO $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'validate_assignment_single_mode' AND tgrelid = 'vinto_txn.assignment'::regclass AND tgenabled = 'O') THEN
   RAISE EXCEPTION '0012 aborted: single-mode trigger is not enabled';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'validate_assignment_exclusivity' AND tgrelid = 'vinto_txn.assignment'::regclass AND tgenabled = 'O') THEN
   RAISE EXCEPTION '0012 aborted: 0011 exclusivity trigger is missing';
 END IF;
END $$;
