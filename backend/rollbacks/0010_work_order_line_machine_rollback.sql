-- Rollback of 0010_work_order_line_machine.sql. NOT a migration: migrate.py never reads this folder.
--
-- Safe only while no line uses a machine different from its work order header. The guard below aborts otherwise,
-- because dropping the column would silently lose which machine those lines belong to.
-- Run in ONE transaction with the application stopped or idle, as the table owner (vinto_migrator), e.g.:
--   psql -v ON_ERROR_STOP=1 --single-transaction -f 0010_work_order_line_machine_rollback.sql
-- It also removes the 0010 row from vinto_meta.schema_migration so `migrate.py --check` stays consistent.
-- No data is deleted: dropping the column loses only a value that equals work_order.machine_id for every row.

DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM vinto_txn.work_order_line line
              JOIN vinto_txn.work_order_version version ON version.id = line.work_order_version_id
              JOIN vinto_txn.work_order wo ON wo.id = version.work_order_id
             WHERE line.machine_id <> wo.machine_id) THEN
   RAISE EXCEPTION 'Rollback refused: multi-machine lines exist; use a forward migration instead';
 END IF;
END $$;

-- Original 0001 definition: the assignment machine must equal the work order header machine.
CREATE OR REPLACE FUNCTION vinto_txn.validate_assignment() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE machine_sector uuid; assigned_machine uuid;
BEGIN
 SELECT wo.machine_id INTO assigned_machine FROM vinto_txn.work_order_line line
 JOIN vinto_txn.work_order_version version ON version.id = line.work_order_version_id
 JOIN vinto_txn.work_order wo ON wo.id = version.work_order_id WHERE line.id = NEW.work_order_line_id;
 SELECT sector_id INTO machine_sector FROM vinto_master.machine WHERE id = NEW.machine_id;
 IF assigned_machine IS DISTINCT FROM NEW.machine_id OR NOT EXISTS
   (SELECT 1 FROM vinto_config.shift_schedule WHERE id = NEW.shift_schedule_id AND sector_id = machine_sector
    AND NEW.operating_date >= valid_from AND (valid_to IS NULL OR NEW.operating_date <= valid_to)) THEN
   RAISE EXCEPTION 'Assignment machine/shift mismatch' USING ERRCODE = '23514';
 END IF;
 RETURN NEW;
END $$;

DROP TRIGGER validate_order_line_machine ON vinto_txn.work_order_line;
DROP FUNCTION vinto_txn.validate_order_line_machine();
DROP INDEX vinto_txn.work_order_line_machine_fk_idx;
ALTER TABLE vinto_txn.work_order_line DROP CONSTRAINT work_order_line_machine_fk;
ALTER TABLE vinto_txn.work_order_line DROP COLUMN machine_id;
DELETE FROM vinto_meta.schema_migration WHERE version = 10;
