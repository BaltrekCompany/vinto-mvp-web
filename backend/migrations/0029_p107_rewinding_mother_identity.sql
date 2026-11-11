-- RB-P107-MQ-01: identidad persistente de la madre DECLARADA en cada captura P1-07 v3+.
-- NO identifica una bobina F3, NO consume secuencia industrial, NO crea quality_release,
-- NO toca estados de crías. Se añade una fila bobbin técnica por captura para reutilizar
-- el motor de formularios de Calidad en un incremento posterior, sin modificar F3.
ALTER TABLE vinto_txn.bobbin
  ADD COLUMN rewind_mother_capture_id uuid;

ALTER TABLE vinto_txn.bobbin
  ADD CONSTRAINT rewind_mother_capture_fk
    FOREIGN KEY (rewind_mother_capture_id)
    REFERENCES vinto_txn.capture (id) ON DELETE RESTRICT,
  ADD CONSTRAINT rewind_mother_identity_check
    CHECK (rewind_mother_capture_id IS NULL OR (
      rewind_child_position IS NULL AND rewind_mother_label IS NULL
      AND sequence_number IS NULL AND management_start_year IS NULL
      AND source_capture_id = rewind_mother_capture_id
      AND machine_id IS NOT NULL AND article_version_id IS NOT NULL
      AND code = 'MADRE-' || replace(rewind_mother_capture_id::text, '-', '')
    ));

CREATE UNIQUE INDEX bobbin_p107_mother_capture_uidx ON vinto_txn.bobbin
  (rewind_mother_capture_id) WHERE rewind_mother_capture_id IS NOT NULL;

CREATE FUNCTION vinto_txn.guard_p107_mother() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE source_record record;
BEGIN
  IF TG_OP = 'UPDATE' AND OLD.rewind_mother_capture_id IS NOT NULL
     AND (NEW.rewind_mother_capture_id IS DISTINCT FROM OLD.rewind_mother_capture_id
       OR NEW.code IS DISTINCT FROM OLD.code
       OR NEW.source_capture_id IS DISTINCT FROM OLD.source_capture_id
       OR NEW.machine_id IS DISTINCT FROM OLD.machine_id
       OR NEW.article_version_id IS DISTINCT FROM OLD.article_version_id
       OR NEW.rewind_child_position IS DISTINCT FROM OLD.rewind_child_position
       OR NEW.sequence_number IS DISTINCT FROM OLD.sequence_number) THEN
    RAISE EXCEPTION 'P1-07 mother identity is immutable' USING ERRCODE='23514';
  END IF;

  IF NEW.rewind_mother_capture_id IS NOT NULL
     AND (TG_OP = 'INSERT' OR OLD.rewind_mother_capture_id IS NULL) THEN
    SELECT c.machine_id, l.article_version_id, f.code AS form_code,
           fv.version_number, c.status AS capture_status, s.code AS sector_code,
           (SELECT d.value_text FROM vinto_txn.capture_detail d
              JOIN vinto_config.field_definition fd ON fd.id=d.field_definition_id
              WHERE d.capture_id=c.id AND fd.key='etiqueta_numero_de_bobina'
              LIMIT 1) AS declared_mother_label
      INTO source_record
      FROM vinto_txn.capture c
      JOIN vinto_config.form_version fv ON fv.id=c.form_version_id
      JOIN vinto_config.form f ON f.id=fv.form_id
      JOIN vinto_txn.assignment a ON a.id=c.assignment_id
      JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
      JOIN vinto_master.machine m ON m.id=c.machine_id
      JOIN vinto_master.sector s ON s.id=m.sector_id
      WHERE c.id=NEW.rewind_mother_capture_id;
    IF NOT FOUND
       OR source_record.form_code <> 'VINTO-P1-07'
       OR source_record.version_number < 3
       OR source_record.sector_code <> 'REBOBINADO'
       OR source_record.capture_status NOT IN ('submitted','closed')
       OR source_record.machine_id IS DISTINCT FROM NEW.machine_id
       OR source_record.article_version_id IS DISTINCT FROM NEW.article_version_id
       OR source_record.declared_mother_label IS NULL
       OR btrim(source_record.declared_mother_label) = '' THEN
      RAISE EXCEPTION 'P1-07 mother must reference its submitted production capture' USING ERRCODE='23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER guard_p107_mother BEFORE INSERT OR UPDATE ON vinto_txn.bobbin
  FOR EACH ROW EXECUTE FUNCTION vinto_txn.guard_p107_mother();

-- Backfill compatible: solamente capturas P1-07 v3+ que YA generaron crías,
-- sin inventar madres para v1/v2, sin cambiar ninguna fila existente.
INSERT INTO vinto_txn.bobbin
  (code, source_capture_id, article_version_id, machine_id, rewind_mother_capture_id)
SELECT 'MADRE-' || replace(c.id::text, '-', ''), c.id, l.article_version_id,
       c.machine_id, c.id
FROM vinto_txn.capture c
JOIN vinto_config.form_version fv ON fv.id=c.form_version_id
JOIN vinto_config.form f ON f.id=fv.form_id
JOIN vinto_txn.assignment a ON a.id=c.assignment_id
JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
WHERE f.code='VINTO-P1-07' AND fv.version_number >= 3
  AND c.status IN ('submitted','closed')
  AND EXISTS (
    SELECT 1 FROM vinto_txn.bobbin child
    WHERE child.source_capture_id=c.id AND child.rewind_child_position IS NOT NULL
  )
  AND NOT EXISTS (
    SELECT 1 FROM vinto_txn.bobbin mother WHERE mother.rewind_mother_capture_id=c.id
  );
