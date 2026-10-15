-- CLOUD-01B-2: consultas de solo lectura para verificar manualmente el contrato de privilegios.
-- No modifican nada. Pueden ejecutarse como cualquier rol (has_*_privilege no requiere privilegios
-- especiales para preguntar sobre otro rol, salvo pertenecer a un rol con visibilidad suficiente;
-- como superusuario o como vinto_migrator se ven todos los roles sin restricción).
--
-- PG54-FINAL: 'public' NO es una fila real de pg_roles (es el pseudo-rol que representa "todos"), así
-- que un "WHERE rolname IN (...,'public')" contra pg_roles nunca lo incluye — se filtra en silencio,
-- dando una falsa sensación de que se comprobó. Las consultas de abajo comprueban 'public' por separado,
-- como literal pasado directamente a has_*_privilege(), nunca vía una fila de pg_roles.

\set ON_ERROR_STOP on

-- Propiedad de los 6 esquemas: debe ser vinto_migrator en los 6.
SELECT nspname AS esquema, pg_get_userbyid(nspowner) AS propietario
FROM pg_namespace WHERE nspname LIKE 'vinto_%' ORDER BY nspname;

-- Propiedad de todas las tablas: debe ser vinto_migrator en todas (ninguna tabla debe quedar en
-- propiedad de vinto_app, vinto_reference ni vinto_test_admin: principio 1 y 2).
SELECT schemaname, tablename, tableowner FROM pg_tables WHERE schemaname LIKE 'vinto_%' ORDER BY 1, 2;

-- USAGE efectivo por rol y esquema (incluye 'public' explícitamente, no vía pg_roles).
SELECT role, nspname, has_schema_privilege(role, nspname, 'USAGE') AS usage
FROM (SELECT rolname AS role FROM pg_roles WHERE rolname IN ('vinto_app','vinto_migrator','vinto_reference','vinto_test_admin')
      UNION ALL SELECT 'public') roles
CROSS JOIN (SELECT nspname FROM pg_namespace WHERE nspname LIKE 'vinto_%') schemas
ORDER BY 1, 2;

-- CONNECT efectivo sobre la base actual, por rol (incluye 'public' explícitamente).
SELECT role, has_database_privilege(role, current_database(), 'CONNECT') AS connect
FROM (SELECT rolname AS role FROM pg_roles WHERE rolname IN ('vinto_app','vinto_migrator','vinto_reference','vinto_test_admin')
      UNION ALL SELECT 'public') roles;

-- EXECUTE efectivo sobre vinto_txn.management_start_year, por rol (debe ser true solo para vinto_app
-- y vinto_migrator, false para vinto_reference/vinto_test_admin/public — corregido en PG54-FINAL con un
-- REVOKE explícito sobre el objeto ya creado: ver backend/roles/04_function_grants.sql).
SELECT role, has_function_privilege(role, 'vinto_txn.management_start_year(date)', 'EXECUTE') AS execute
FROM (SELECT rolname AS role FROM pg_roles WHERE rolname IN ('vinto_app','vinto_migrator','vinto_reference','vinto_test_admin')
      UNION ALL SELECT 'public') roles;
