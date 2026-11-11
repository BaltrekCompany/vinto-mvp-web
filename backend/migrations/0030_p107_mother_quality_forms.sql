-- RB-P107-MQ-02: política aditiva de captura de Calidad sobre MADRE P1-07.
-- IMPORTANTE: jamás INSERT en form_version_machine de una versión publicada:
-- guard_form_child lo prohíbe, y el bundle es la autoridad inmutable de F3.
-- Solo las seis definiciones existentes y las máquinas que publican P1-07
-- (COPASA, BELOIT, OVER) son válidas para el CONTEXTO de una madre técnica.
-- Las concesiones de usuario/máquina/formulario se verifican en el backend.

-- validate_capture de 0001 se conserva literalmente para F3 y Producción;
-- esta excepción positiva es exclusiva de b.rewind_mother_capture_id.
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
 IF NOT EXISTS (SELECT 1 FROM vinto_config.form_version_machine WHERE form_version_id = NEW.form_version_id AND machine_id = NEW.machine_id)
   AND NOT EXISTS (
     SELECT 1 FROM vinto_txn.bobbin b
     JOIN vinto_master.machine m ON m.id=b.machine_id
     JOIN vinto_config.form_version fv ON fv.id=NEW.form_version_id
     JOIN vinto_config.form f ON f.id=fv.form_id
     WHERE b.id=NEW.bobbin_id
       AND b.rewind_mother_capture_id IS NOT NULL
       AND b.rewind_child_position IS NULL
       AND b.machine_id=NEW.machine_id
       AND m.code IN ('COPASA','BELOIT','OVER')
       AND fv.area='quality'
       AND f.code IN ('VINTO-P1-19','VINTO-P1-20','VINTO-P1-21',
                      'VINTO-P1-24','VINTO-P1-25','VINTO-P1-28')
   ) THEN
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

-- La guardia existente aceptaba EXCLUSIVAMENTE F3 numerada. Ampliación
-- positiva y acotada a las madres P1-07 con identidad 0029. No acepta crías.
CREATE OR REPLACE FUNCTION vinto_txn.guard_capture_bobbin() RETURNS trigger LANGUAGE plpgsql AS $$
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
   SELECT b.machine_id, c.shift_schedule_id, c.operating_date, c.assignment_id,
          b.sequence_number, b.rewind_mother_capture_id,
          f.code AS origin_form, fv.version_number AS origin_version
     INTO src
   FROM vinto_txn.bobbin b
   JOIN vinto_txn.capture c ON c.id=b.source_capture_id
   JOIN vinto_config.form_version fv ON fv.id=c.form_version_id
   JOIN vinto_config.form f ON f.id=fv.form_id
   WHERE b.id=NEW.bobbin_id
     AND (b.sequence_number IS NOT NULL OR b.rewind_mother_capture_id IS NOT NULL)
     AND b.rewind_child_position IS NULL;
   IF NOT FOUND THEN
     RAISE EXCEPTION 'Quality capture requires F3 or P1-07 mother identity' USING ERRCODE = '23514';
   END IF;
   IF src.rewind_mother_capture_id IS NOT NULL AND
      (src.origin_form <> 'VINTO-P1-07' OR src.origin_version < 3) THEN
     RAISE EXCEPTION 'Mother quality must derive from P1-07 v3+' USING ERRCODE = '23514';
   END IF;
   IF NEW.machine_id IS DISTINCT FROM src.machine_id
      OR NEW.shift_schedule_id IS DISTINCT FROM src.shift_schedule_id
      OR NEW.operating_date IS DISTINCT FROM src.operating_date
      OR NEW.assignment_id IS DISTINCT FROM src.assignment_id THEN
     RAISE EXCEPTION 'Quality capture context must match its production source' USING ERRCODE = '23514';
   END IF;
 END IF;
 RETURN NEW;
END $$;
