-- Rollback of 0011_assignment_same_work_order_lines.sql. NOT a migration: migrate.py never reads this folder.
--
-- It restores "one active assignment per machine" (assignment_one_active_machine). That index cannot be rebuilt while a
-- machine has two or more active assignments, and this script NEVER finishes, deletes or edits assignments or captures to
-- make it fit: it aborts instead. Resolve the situation first with the normal `finish` endpoint (explicit, audited), or move
-- forward with a new migration. Run in ONE transaction with the application stopped or idle, as the table owner
-- (vinto_migrator), e.g.:
--   psql -v ON_ERROR_STOP=1 --single-transaction -f 0011_assignment_same_work_order_lines_rollback.sql
-- It also removes the 0011 row from vinto_meta.schema_migration so `migrate.py --check` stays consistent.
-- Captures keep their composite FK to assignment; no data is touched.

DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM vinto_txn.assignment WHERE status = 'active' GROUP BY machine_id HAVING count(*) > 1) THEN
   RAISE EXCEPTION 'Rollback refused: a machine has several active assignments; finish them explicitly or use a forward migration';
 END IF;
END $$;

CREATE UNIQUE INDEX assignment_one_active_machine ON vinto_txn.assignment (machine_id) WHERE status = 'active';
DROP TRIGGER validate_assignment_exclusivity ON vinto_txn.assignment;
DROP FUNCTION vinto_txn.validate_assignment_exclusivity();
DROP INDEX vinto_txn.assignment_active_machine_idx;
DROP INDEX vinto_txn.assignment_one_active_line;
DELETE FROM vinto_meta.schema_migration WHERE version = 11;
