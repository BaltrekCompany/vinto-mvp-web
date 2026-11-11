-- RB-P107-MQ-02: formularios de Calidad para madres P1-07 independientes de F3.
-- Preserva las versiones y vínculos MP1/MP3 existentes; no crea permisos de
-- usuario ni cambia estados de crías. Solo COPASA/BELOIT/OVER (máquinas P1-07).
-- Los seis formularios de Calidad se vinculan a las máquinas productoras de
-- madres declaradas, no a una supuesta bobina física F3.
INSERT INTO vinto_config.form_version_machine (form_version_id, machine_id)
SELECT fv.id, m.id
FROM vinto_config.form f
JOIN LATERAL (
  SELECT v.id, v.area FROM vinto_config.form_version v
  WHERE v.form_id=f.id AND v.status='published'
  ORDER BY v.version_number DESC LIMIT 1
) fv ON fv.area='quality'
CROSS JOIN vinto_master.machine m
JOIN vinto_master.sector s ON s.id=m.sector_id
WHERE f.active AND f.code IN (
  'VINTO-P1-19','VINTO-P1-20','VINTO-P1-21',
  'VINTO-P1-24','VINTO-P1-25','VINTO-P1-28'
)
AND m.active AND s.active AND s.code='REBOBINADO'
AND m.code IN ('COPASA','BELOIT','OVER')
ON CONFLICT (form_version_id, machine_id) DO NOTHING;

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
