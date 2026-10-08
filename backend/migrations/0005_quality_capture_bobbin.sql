-- Quality captures belong to a physical Bobbin.
--
-- Forward-only and non-destructive: no backfill and no UPDATE/DELETE of existing rows. Every existing capture (F3, F6)
-- keeps bobbin_id IS NULL. 0001-0004 are untouched; vinto_txn.validate_capture() is not replaced.
--
-- vinto_txn.capture.bobbin_id (nullable) -> vinto_txn.bobbin(id) ON DELETE RESTRICT, with a plain index.
-- NOT unique: one Bobbin can have several quality captures (even several of the same test); the business has not
-- confirmed any cardinality.
--
-- guard_capture_bobbin keeps the link coherent without adding business rules:
--   * a capture that points to a Bobbin must use a quality form version and carry EXACTLY the historical production
--     context of that Bobbin's source F3 capture (machine, shift schedule, operating date, assignment). The quality capture
--     never re-derives that context from the active assignment, the current shift or today's date.
--   * bobbin_id is part of the immutable capture context (like machine/shift/assignment in validate_capture).

ALTER TABLE vinto_txn."capture" ADD COLUMN bobbin_id uuid;

ALTER TABLE vinto_txn."capture" ADD CONSTRAINT "capture_bobbin_fk" FOREIGN KEY (bobbin_id) REFERENCES vinto_txn."bobbin" (id) ON DELETE RESTRICT;

CREATE INDEX "capture_bobbin_fk_idx" ON vinto_txn."capture" (bobbin_id);

CREATE FUNCTION vinto_txn.guard_capture_bobbin() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE src record; form_area text;
BEGIN
 IF TG_OP = 'UPDATE' AND NEW.bobbin_id IS DISTINCT FROM OLD.bobbin_id THEN
   RAISE EXCEPTION 'Capture bobbin is immutable; create a new capture' USING ERRCODE = '23514';
 END IF;
 IF TG_OP = 'INSERT' AND NEW.bobbin_id IS NOT NULL THEN
   SELECT area INTO form_area FROM vinto_config.form_version WHERE id = NEW.form_version_id;
   IF form_area IS DISTINCT FROM 'quality' THEN
     RAISE EXCEPTION 'Only quality captures can reference a bobbin' USING ERRCODE = '23514';
   END IF;
   SELECT b.machine_id, c.shift_schedule_id, c.operating_date, c.assignment_id INTO src
   FROM vinto_txn.bobbin b JOIN vinto_txn.capture c ON c.id = b.source_capture_id
   WHERE b.id = NEW.bobbin_id AND b.sequence_number IS NOT NULL;
   IF NOT FOUND THEN
     RAISE EXCEPTION 'Quality capture requires a numbered bobbin with its source capture' USING ERRCODE = '23514';
   END IF;
   IF NEW.machine_id <> src.machine_id OR NEW.shift_schedule_id <> src.shift_schedule_id OR NEW.operating_date <> src.operating_date
     OR NEW.assignment_id IS DISTINCT FROM src.assignment_id THEN
     RAISE EXCEPTION 'Quality capture context must match its bobbin production context' USING ERRCODE = '23514';
   END IF;
 END IF;
 RETURN NEW;
END $$;

CREATE TRIGGER guard_capture_bobbin BEFORE INSERT OR UPDATE ON vinto_txn."capture" FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_capture_bobbin();
