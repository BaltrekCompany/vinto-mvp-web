-- CV-P112-01: pallet por captura P1-12 v4, numerado por OT + linea.
-- Solo tablas aditivas. P1-12 v1/v2/v3 y datos de maestros previos no se alteran.
-- Fuente del peso: INArticulo-MFMatrialOP (1).xlsx, hoja INInventario, columna Peso;
-- articulo 10351 = 1.74 KG, unidad origen Pack. VINTO confirmo uso por jaba.
-- Importacion inicial: 52 articulos permitidos para GAMBINI/SINCRO_II/SINCRO_III.
-- Nuevos cambios de pesos se versionaran por revision sin cambiar capturas pasadas.
CREATE TABLE vinto_master.pallet_nominal_weight (
  article_code text NOT NULL,
  revision integer NOT NULL CHECK (revision > 0),
  nominal_weight_kg numeric(18,6) NOT NULL CHECK (nominal_weight_kg > 0),
  source_unit text NOT NULL CHECK (source_unit = 'PACK'),
  source_sha256 text NOT NULL CHECK (source_sha256 ~ '^[a-f0-9]{64}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (article_code, revision)
);

INSERT INTO vinto_master.pallet_nominal_weight
  (article_code, revision, nominal_weight_kg, source_unit, source_sha256) VALUES
  ('10326', 1, 0.87, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10327', 1, 2.1, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10328', 1, 6.48, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10329', 1, 2.9, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10330', 1, 1.2, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10331', 1, 2.9, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10332', 1, 6.48, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10333', 1, 2.1, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10334', 1, 10.944, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10335', 1, 0.73, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10336', 1, 1.46, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10337', 1, 6.05, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10338', 1, 3.5, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10339', 1, 3.5, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10340', 1, 2.06294, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10342', 1, 3.02, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10344', 1, 3.63, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10345', 1, 2.06, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10347', 1, 2.29, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10348', 1, 2.29, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10349', 1, 3.5, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10350', 1, 1.74, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10351', 1, 1.74, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10352', 1, 2.49, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10353', 1, 2.57, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10354', 1, 2.57, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10355', 1, 1.644, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10356', 1, 1.846, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10357', 1, 1.846, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10358', 1, 4.32, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10359', 1, 7.2, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10360', 1, 2.56, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10403', 1, 0.97, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10425', 1, 0.8016, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10427', 1, 1.5768, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10428', 1, 0.9462, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10430', 1, 0.8184, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10432', 1, 0.6108, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10433', 1, 0.9282, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10434', 1, 0.6048, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10435', 1, 0.6048, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10436', 1, 0.6048, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10437', 1, 0.6048, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10438', 1, 0.6048, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10503', 1, 3.74, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('10504', 1, 3.74, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11402', 1, 2.79552, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11403', 1, 2.33, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11404', 1, 2.91, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11405', 1, 2.23642, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11406', 1, 3.41, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11499', 1, 2.89184, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228');

CREATE TRIGGER immutable_pallet_nominal_weight
  BEFORE UPDATE OR DELETE ON vinto_master.pallet_nominal_weight
  FOR EACH ROW EXECUTE FUNCTION vinto_audit.reject_mutation();

CREATE TABLE vinto_txn.production_pallet (
  capture_id uuid PRIMARY KEY REFERENCES vinto_txn.capture(id),
  work_order_id uuid NOT NULL REFERENCES vinto_txn.work_order(id),
  line_code text NOT NULL,
  machine_id uuid NOT NULL REFERENCES vinto_master.machine(id),
  article_version_id uuid NOT NULL REFERENCES vinto_master.article_version(id),
  pallet_number integer NOT NULL CHECK (pallet_number > 0),
  quantity_jabas integer NOT NULL CHECK (quantity_jabas > 0),
  nominal_weight_kg numeric(18,6) NOT NULL CHECK (nominal_weight_kg > 0),
  total_weight_kg numeric(28,6) NOT NULL CHECK (total_weight_kg > 0),
  weight_source_sha256 text NOT NULL CHECK (weight_source_sha256 ~ '^[a-f0-9]{64}$'),
  created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
  UNIQUE (work_order_id, line_code, pallet_number),
  CHECK (total_weight_kg = quantity_jabas * nominal_weight_kg)
);

CREATE INDEX production_pallet_work_order_line_idx
  ON vinto_txn.production_pallet (work_order_id, line_code, pallet_number DESC);

CREATE TRIGGER immutable_production_pallet
  BEFORE UPDATE OR DELETE ON vinto_txn.production_pallet
  FOR EACH ROW EXECUTE FUNCTION vinto_audit.reject_mutation();
