-- Rollback of 0012_assignment_single_mode_guard.sql. NOT a migration: migrate.py never reads this folder.
--
-- Removes only the trigger and its function; it never reads, finishes, deletes or edits assignments or captures, so it can
-- always run (there is no data precondition). 0011 protections stay. Run in ONE transaction as the table owner
-- (vinto_migrator), e.g.:
--   psql -v ON_ERROR_STOP=1 --single-transaction -f 0012_assignment_single_mode_guard_rollback.sql
-- It also removes the 0012 row from vinto_meta.schema_migration so `migrate.py --check` stays consistent.
-- Real limitation: after the rollback the gate-OFF rule is again enforced by the application only. The backend keeps
-- setting vinto.assignment_multi_line; with no trigger it is inert.

DROP TRIGGER validate_assignment_single_mode ON vinto_txn.assignment;
DROP FUNCTION vinto_txn.validate_assignment_single_mode();
DELETE FROM vinto_meta.schema_migration WHERE version = 12;
