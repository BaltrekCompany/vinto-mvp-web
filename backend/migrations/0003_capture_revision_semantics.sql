-- Capture revision semantics. Only the revision rule of vinto_txn.validate_capture() changes; every other
-- protection from 0001 is kept exactly as it was (closed immutability, immutable context, audited corrections,
-- published form, allowed machine, device/machine and shift/sector/date coherence).
--
-- Before: every UPDATE did NEW.revision := OLD.revision + 1, so the normal first submission
-- (INSERT draft -> INSERT details -> UPDATE draft->submitted) left revision = 2.
-- Now:
--   INSERT                  -> revision = 1 (a client-supplied value is ignored)
--   OLD.status = 'draft'    -> revision unchanged for ANY update (draft -> draft, draft -> submitted, draft -> blocked):
--                              editing a draft is not a correction
--   any other UPDATE        -> revision + 1 (e.g. submitted -> submitted correction, or submitted -> draft reopening)
-- A reopened capture (submitted -> draft) counts its correction when it is reopened; the draft -> draft edits and the
-- draft -> submitted that follow keep that revision: one correction = one increment.
-- The trigger vinto_txn.validate_capture on vinto_txn.capture is not recreated: CREATE OR REPLACE keeps it attached.

CREATE OR REPLACE FUNCTION vinto_txn.validate_capture() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE machine_sector uuid; device_machine uuid;
BEGIN
 IF TG_OP = 'UPDATE' THEN
   IF OLD.status = 'closed' THEN RAISE EXCEPTION 'Closed capture is immutable' USING ERRCODE = '23514'; END IF;
   IF NEW.form_version_id <> OLD.form_version_id OR NEW.machine_id <> OLD.machine_id
     OR NEW.shift_schedule_id <> OLD.shift_schedule_id OR NEW.device_id <> OLD.device_id
     OR NEW.assignment_id IS DISTINCT FROM OLD.assignment_id OR NEW.operating_date <> OLD.operating_date
     OR NEW.recipe_version_id IS DISTINCT FROM OLD.recipe_version_id THEN
       RAISE EXCEPTION 'Capture context is immutable; create a new capture' USING ERRCODE = '23514';
   END IF;
   IF OLD.status <> 'draft' AND (nullif(NEW.correction_reason,'') IS NULL
     OR nullif(current_setting('vinto.reason',true),'') IS NULL) THEN
       RAISE EXCEPTION 'Capture correction requires an audited reason' USING ERRCODE = '23514';
   END IF;
   IF OLD.status = 'draft' THEN NEW.revision := OLD.revision;
   ELSE NEW.revision := OLD.revision + 1;
   END IF;
 ELSE NEW.revision := 1;
 END IF;
 IF NOT EXISTS (SELECT 1 FROM vinto_config.form_version WHERE id = NEW.form_version_id
   AND (status = 'published' OR TG_OP = 'UPDATE' AND status = 'retired')) THEN
   RAISE EXCEPTION 'Capture requires published form' USING ERRCODE = '23514';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM vinto_config.form_version_machine WHERE form_version_id = NEW.form_version_id AND machine_id = NEW.machine_id) THEN
   RAISE EXCEPTION 'Machine is not allowed for this form version' USING ERRCODE = '23514';
 END IF;
 SELECT sector_id INTO machine_sector FROM vinto_master.machine WHERE id = NEW.machine_id;
 SELECT machine_id INTO device_machine FROM vinto_master.device WHERE id = NEW.device_id;
 IF device_machine IS NOT NULL AND device_machine <> NEW.machine_id THEN
   RAISE EXCEPTION 'Device machine mismatch' USING ERRCODE = '23514';
 END IF;
 IF NOT EXISTS (SELECT 1 FROM vinto_config.shift_schedule WHERE id = NEW.shift_schedule_id AND sector_id = machine_sector
   AND NEW.operating_date >= valid_from AND (valid_to IS NULL OR NEW.operating_date <= valid_to)) THEN
   RAISE EXCEPTION 'Capture shift mismatch' USING ERRCODE = '23514';
 END IF;
 RETURN NEW;
END $$;
