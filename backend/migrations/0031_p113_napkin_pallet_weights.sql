-- CV-P113-01: pesos nominales de productos P1-13 con unidad Pack en INInventario (columna T).
-- Archivo homologado: INArticulo-MFMatrialOP (1)(3).xlsx; SHA256=9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228.
-- No modificar catalogo ni pallets existentes. 11503 (unidad UN) se EXCLUYE hasta homologar conversion kg/jaba.
-- Los productos 11104/11202 carecen de ruta y siguen bloqueados por la politica de receta.
INSERT INTO vinto_master.pallet_nominal_weight
    (article_code, revision, nominal_weight_kg, source_unit, source_sha256)
VALUES
  ('11102', 1, 1.33, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11103', 1, 2.48, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11104', 1, 2.94, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11110', 1, 1.3962, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11202', 1, 2.36, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11203', 1, 2.02, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11204', 1, 2.66, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11205', 1, 2.89, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11206', 1, 2.723, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11307', 1, 1.6, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11308', 1, 1, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11309', 1, 1, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11313', 1, 1, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11314', 1, 1, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11316', 1, 1, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11317', 1, 1, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11318', 1, 1, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11319', 1, 1, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11320', 1, 1, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11321', 1, 1, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228'),
  ('11502', 1, 6, 'PACK', '9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228');
