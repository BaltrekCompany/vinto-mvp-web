-- E1-02 ROLLBACK of 0013: OWNER/MIGRATOR ONLY, only before ANY execution rows exist.
-- The migrator itself has no automatic down migration; run only in controlled maintenance.
-- Mandatory: back up first; stop application writers; execute as ONE transaction.
-- Never delete real history merely to make this rollback succeed.
BEGIN;
DO $$
BEGIN
 IF to_regclass('vinto_txn.work_order_line_execution') IS NULL THEN
   RAISE EXCEPTION 'Rollback 0013 refused: table missing';
 END IF;
 IF EXISTS (SELECT 1 FROM vinto_txn.work_order_line_execution LIMIT 1) THEN
   RAISE EXCEPTION 'Rollback 0013 refused: execution history exists (preserve it)';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM vinto_meta.schema_migration WHERE version = 13) THEN
   RAISE EXCEPTION 'Rollback 0013 refused: migration history entry absent';
 END IF;
END $$;
DROP TABLE vinto_txn.work_order_line_execution;
DROP FUNCTION vinto_txn.guard_work_order_line_execution();
DELETE FROM vinto_meta.schema_migration WHERE version = 13;
COMMIT;
