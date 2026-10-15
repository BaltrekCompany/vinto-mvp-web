-- CLOUD-01B-2: consultas de solo lectura para verificar manualmente el contrato de privilegios.
-- No modifican nada. Pueden ejecutarse como cualquier rol (has_*_privilege no requiere privilegios
-- especiales para preguntar sobre otro rol, salvo pertenecer a un rol con visibilidad suficiente;
-- como superusuario o como vinto_migrator se ven todos los roles sin restricción).

-- Propiedad de los 6 esquemas: debe ser vinto_migrator en los 6.
SELECT nspname AS esquema, pg_get_userbyid(nspowner) AS propietario
FROM pg_namespace WHERE nspname LIKE 'vinto_%' ORDER BY nspname;

-- Propiedad de todas las tablas: debe ser vinto_migrator en todas (ninguna tabla debe quedar en
-- propiedad de vinto_app, vinto_reference ni vinto_test_admin: principio 1 y 2).
SELECT schemaname, tablename, tableowner FROM pg_tables WHERE schemaname LIKE 'vinto_%' ORDER BY 1, 2;

-- USAGE efectivo por rol y esquema.
SELECT r.rolname, n.nspname, has_schema_privilege(r.rolname, n.nspname, 'USAGE') AS usage
FROM pg_roles r CROSS JOIN pg_namespace n
WHERE r.rolname IN ('vinto_app','vinto_migrator','vinto_reference','vinto_test_admin','public')
  AND n.nspname LIKE 'vinto_%'
ORDER BY 1, 2;

-- CONNECT efectivo sobre la base actual, por rol.
SELECT rolname, has_database_privilege(rolname, current_database(), 'CONNECT') AS connect
FROM pg_roles WHERE rolname IN ('vinto_app','vinto_migrator','vinto_reference','vinto_test_admin','public');

-- EXECUTE efectivo sobre vinto_txn.management_start_year, por rol (debe ser true solo para vinto_app
-- y vinto_migrator, false para vinto_reference/vinto_test_admin/public).
SELECT rolname, has_function_privilege(rolname, 'vinto_txn.management_start_year(date)', 'EXECUTE') AS execute
FROM pg_roles WHERE rolname IN ('vinto_app','vinto_migrator','vinto_reference','vinto_test_admin','public');
