-- RB-CRIA-01: crías P1-07 con identidad UUID, madre por etiqueta declarada (opción A).
-- Adición compatible: F3, numeraciones oficiales, historial y estado existente intactos.
ALTER TABLE vinto_txn.bobbin
  ADD COLUMN rewind_child_position smallint,
  ADD COLUMN rewind_mother_label text;

ALTER TABLE vinto_txn.bobbin
  ADD CONSTRAINT rewind_pair_check
    CHECK ((rewind_child_position IS NULL) = (rewind_mother_label IS NULL)),
  ADD CONSTRAINT rewind_position_check
    CHECK (rewind_child_position IS NULL OR (rewind_child_position BETWEEN 1 AND 22 AND rewind_child_position <> 12)),
  ADD CONSTRAINT rewind_row_check
    CHECK (rewind_child_position IS NULL OR (
       sequence_number IS NULL AND management_start_year IS NULL
       AND source_capture_id IS NOT NULL AND machine_id IS NOT NULL AND article_version_id IS NOT NULL
       AND weight_kg IS NOT NULL AND weight_kg > 0
       AND start_time IS NOT NULL AND end_time IS NOT NULL AND diameter_mm IS NOT NULL
       AND rewind_mother_label IS NOT NULL AND length(btrim(rewind_mother_label)) BETWEEN 1 AND 10000
       AND code = 'CRIA-' || replace(source_capture_id::text, '-', '') || '-' || rewind_child_position::text
    ));

CREATE UNIQUE INDEX bobbin_rewind_capture_position_uidx ON vinto_txn.bobbin
  (source_capture_id, rewind_child_position) WHERE rewind_child_position IS NOT NULL;

CREATE FUNCTION vinto_txn.guard_rewind_child() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source_record record;
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.rewind_child_position IS NOT NULL AND (
      NEW.rewind_child_position IS DISTINCT FROM OLD.rewind_child_position OR
      NEW.rewind_mother_label IS DISTINCT FROM OLD.rewind_mother_label OR
      NEW.code IS DISTINCT FROM OLD.code OR
      NEW.source_capture_id IS DISTINCT FROM OLD.source_capture_id OR
      NEW.machine_id IS DISTINCT FROM OLD.machine_id OR
      NEW.article_version_id IS DISTINCT FROM OLD.article_version_id OR
      NEW.weight_kg IS DISTINCT FROM OLD.weight_kg OR
      NEW.start_time IS DISTINCT FROM OLD.start_time OR
      NEW.end_time IS DISTINCT FROM OLD.end_time OR
      NEW.diameter_mm IS DISTINCT FROM OLD.diameter_mm OR
      NEW.sequence_number IS DISTINCT FROM OLD.sequence_number
  ) THEN
     RAISE EXCEPTION 'Rewinding child identity is immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.rewind_child_position IS NOT NULL AND (TG_OP='INSERT' OR OLD.rewind_child_position IS NULL) THEN
    SELECT c.machine_id, l.article_version_id, f.code AS form_code, fv.version_number,
           c.status AS capture_status, s.code AS sector_code,
           (SELECT d.value_text FROM vinto_txn.capture_detail d
              JOIN vinto_config.field_definition fd ON fd.id=d.field_definition_id
              WHERE d.capture_id=c.id AND fd.key='etiqueta_numero_de_bobina'
              LIMIT 1) AS mother_label
      INTO source_record
    FROM vinto_txn.capture c
    JOIN vinto_config.form_version fv ON fv.id=c.form_version_id
    JOIN vinto_config.form f ON f.id=fv.form_id
    JOIN vinto_txn.assignment a ON a.id=c.assignment_id
    JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
    JOIN vinto_master.machine m ON m.id=c.machine_id
    JOIN vinto_master.sector s ON s.id=m.sector_id
    WHERE c.id=NEW.source_capture_id;
    IF NOT FOUND OR source_record.form_code <> 'VINTO-P1-07' OR
       source_record.version_number < 3 OR source_record.sector_code <> 'REBOBINADO' OR
       source_record.capture_status NOT IN ('submitted', 'closed') OR
       source_record.machine_id IS DISTINCT FROM NEW.machine_id OR
       source_record.article_version_id IS DISTINCT FROM NEW.article_version_id OR
       source_record.mother_label IS DISTINCT FROM NEW.rewind_mother_label THEN
       RAISE EXCEPTION 'Rewinding child must match submitted P1-07 source' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER guard_rewind_child BEFORE INSERT OR UPDATE ON vinto_txn.bobbin
 FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_rewind_child();

CREATE FUNCTION vinto_txn.require_rewind_child_quality() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.rewind_child_position IS NOT NULL AND NOT EXISTS (
     SELECT 1 FROM vinto_txn.quality_release WHERE bobbin_id=NEW.id
  ) THEN
     RAISE EXCEPTION 'Rewinding child requires quality_release row' USING ERRCODE='23514';
  END IF;
  RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER require_rewind_child_quality AFTER INSERT ON vinto_txn.bobbin
 DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION vinto_txn.require_rewind_child_quality();
