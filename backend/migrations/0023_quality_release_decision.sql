-- 0023: decisiones de Calidad por BOBINA (no por linea de OT).
-- Ampliacion aditiva y compatible con decisiones historicas.
-- Ninguna fila preexistente se reescribe y ninguna decision se desbloquea.
ALTER TABLE vinto_txn.quality_release
  ADD COLUMN decision_request_id uuid,
  ADD COLUMN rejection_type text,
  ADD COLUMN rejection_classification text,
  ADD COLUMN rejection_detail text,
  ADD COLUMN corrective_action text;

ALTER TABLE vinto_txn.quality_release
  ADD CONSTRAINT quality_release_rejection_type_check
  CHECK (rejection_type IS NULL OR rejection_type IN ('rechazado', 'reutilizable')),
  ADD CONSTRAINT quality_release_rejection_classification_check
  CHECK (rejection_classification IS NULL OR rejection_classification IN
    ('dimensiones', 'formato', 'defecto_visible', 'humedad', 'propiedades_bobina', 'otros')),
  ADD CONSTRAINT quality_release_rejection_text_length_check
  CHECK ((rejection_detail IS NULL OR char_length(rejection_detail) <= 4000)
     AND (corrective_action IS NULL OR char_length(corrective_action) <= 4000));

-- El estado antiguo es la autoridad. Las nuevas columnas no imponen NOT NULL
-- a rechazos historicos; la API nueva valida los cuatro campos antes de escribir.
-- La tabla ya tiene triggers z_touch + audit_changes de 0001.
