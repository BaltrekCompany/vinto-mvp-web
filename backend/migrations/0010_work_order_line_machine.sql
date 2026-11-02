-- 0010 MF13-03.B PR1: machine per work order line (multi-machine work orders, schema only).
--
-- Expand step. Nothing here changes how the deployed backend behaves:
--   * work_order.machine_id stays (NOT NULL, unchanged) as the legacy "primary" machine.
--   * Every existing line receives the machine of its work order, so single-machine data is equivalent.
--   * A BEFORE trigger fills machine_id when an INSERT omits it, so the deployed backend (which does not know the
--     column) keeps creating lines, and copying baseline lines into the operational version, exactly as before.
--   * assignment_one_active_machine and the activation semantics are NOT touched.
-- Rollback before any line uses a machine different from its work order: backend/rollbacks/0010_work_order_line_machine_rollback.sql

-- 1. Column, nullable until the backfill has run.
ALTER TABLE vinto_txn.work_order_line ADD COLUMN machine_id uuid;

-- 2. Backfill. Published lines are immutable (guard_order_line), so only that ONE trigger is switched off, only on
--    this table, only inside this transaction (DDL is transactional: a failure restores it). Audit (z_touch,
--    audit_changes) and every other integrity control stay active, so each backfilled row leaves an audit event
--    carrying the reason below.
SELECT set_config('vinto.reason', 'MF13-03B PR1 backfill work_order_line.machine_id from work_order.machine_id', true);
ALTER TABLE vinto_txn.work_order_line DISABLE TRIGGER guard_order_line;
UPDATE vinto_txn.work_order_line line
   SET machine_id = wo.machine_id
  FROM vinto_txn.work_order_version version
  JOIN vinto_txn.work_order wo ON wo.id = version.work_order_id
 WHERE version.id = line.work_order_version_id AND line.machine_id IS NULL;
ALTER TABLE vinto_txn.work_order_line ENABLE TRIGGER guard_order_line;

-- 3. Post-conditions: nothing left unfilled and the immutability guard is enabled again (origin mode 'O').
DO $$
BEGIN
 IF EXISTS (SELECT 1 FROM vinto_txn.work_order_line WHERE machine_id IS NULL) THEN
   RAISE EXCEPTION '0010 backfill left work_order_line rows without machine_id';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgrelid = 'vinto_txn.work_order_line'::regclass
                  AND tgname = 'guard_order_line' AND tgenabled = 'O') THEN
   RAISE EXCEPTION '0010 left guard_order_line disabled';
 END IF;
END $$;

-- 4. Integrity.
ALTER TABLE vinto_txn.work_order_line ALTER COLUMN machine_id SET NOT NULL;
ALTER TABLE vinto_txn.work_order_line ADD CONSTRAINT work_order_line_machine_fk
  FOREIGN KEY (machine_id) REFERENCES vinto_master.machine (id) ON DELETE RESTRICT;
CREATE INDEX work_order_line_machine_fk_idx ON vinto_txn.work_order_line (machine_id);

-- 5. Machine / article coherence plus default for omitted machine_id (fires before NOT NULL is checked).
--    Baseline lines: default = machine of the work order; the article must be enabled for the machine in
--    article_machine (the same rule the backend applies on create/publish, now also in the database).
--    Operational lines are copies: default = machine of the baseline line with the same line_code (falling back
--    to the work order machine), and an explicit machine must equal that baseline line's machine. article_machine
--    is deliberately not re-checked on copies, so a later change to article_machine cannot block activation of an
--    already published work order.
CREATE FUNCTION vinto_txn.validate_order_line_machine() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE version_kind text; order_id uuid; order_machine uuid; baseline_machine uuid;
BEGIN
 SELECT version.kind, version.work_order_id, wo.machine_id INTO version_kind, order_id, order_machine
   FROM vinto_txn.work_order_version version JOIN vinto_txn.work_order wo ON wo.id = version.work_order_id
  WHERE version.id = NEW.work_order_version_id;
 IF version_kind = 'operational' THEN
   SELECT baseline_line.machine_id INTO baseline_machine
     FROM vinto_txn.work_order_line baseline_line
     JOIN vinto_txn.work_order_version baseline ON baseline.id = baseline_line.work_order_version_id
    WHERE baseline.work_order_id = order_id AND baseline.kind = 'baseline' AND baseline_line.line_code = NEW.line_code
    ORDER BY baseline.version_number LIMIT 1;
   IF NEW.machine_id IS NULL THEN NEW.machine_id := coalesce(baseline_machine, order_machine); END IF;
   IF baseline_machine IS NOT NULL AND NEW.machine_id <> baseline_machine THEN
     RAISE EXCEPTION 'Operational line machine must match its baseline line' USING ERRCODE = '23514';
   END IF;
   RETURN NEW;
 END IF;
 IF NEW.machine_id IS NULL THEN NEW.machine_id := order_machine; END IF;
 IF NOT EXISTS (SELECT 1 FROM vinto_master.article_version article_version
                  JOIN vinto_master.article_machine article_machine ON article_machine.article_id = article_version.article_id
                 WHERE article_version.id = NEW.article_version_id AND article_machine.machine_id = NEW.machine_id) THEN
   RAISE EXCEPTION 'Order line article is not allowed for the line machine' USING ERRCODE = '23514';
 END IF;
 RETURN NEW;
END $$;

CREATE TRIGGER validate_order_line_machine BEFORE INSERT OR UPDATE ON vinto_txn.work_order_line
  FOR EACH ROW EXECUTE FUNCTION vinto_txn.validate_order_line_machine();

-- 6. An assignment must use the machine of ITS LINE (before: of the work order header). Identical result for every
--    existing row, because step 2 copied the header machine into each line. The only change in behaviour is that
--    a future line on another machine cannot be assigned to the header machine by an older backend (fail closed).
--    Body is otherwise the 0001 definition.
CREATE OR REPLACE FUNCTION vinto_txn.validate_assignment() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE machine_sector uuid; assigned_machine uuid;
BEGIN
 SELECT line.machine_id INTO assigned_machine FROM vinto_txn.work_order_line line WHERE line.id = NEW.work_order_line_id;
 SELECT sector_id INTO machine_sector FROM vinto_master.machine WHERE id = NEW.machine_id;
 IF assigned_machine IS DISTINCT FROM NEW.machine_id OR NOT EXISTS
   (SELECT 1 FROM vinto_config.shift_schedule WHERE id = NEW.shift_schedule_id AND sector_id = machine_sector
    AND NEW.operating_date >= valid_from AND (valid_to IS NULL OR NEW.operating_date <= valid_to)) THEN
   RAISE EXCEPTION 'Assignment machine/shift mismatch' USING ERRCODE = '23514';
 END IF;
 RETURN NEW;
END $$;
