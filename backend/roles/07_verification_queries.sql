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

-- MF-13-01D.3B.1: detección de deriva del endurecimiento inicial. Tras adoptar 03b_d3b1_restrict_catalog_writes.sql, TODA fila debe tener
-- d3b1_compliant = true. false significa que alguien re-ejecutó 03_table_grants.sql sin 03b (restaura INSERT/UPDATE de tabla), o que 03b aún no se aplicó.
-- vinto_reference conserva INSERT/UPDATE: es el responsable del catálogo (import_reference.py).
SELECT t.tbl AS tabla,
       has_table_privilege('vinto_app', t.tbl, 'SELECT') AS app_select,
       has_table_privilege('vinto_app', t.tbl, 'INSERT') AS app_insert_tabla,
       has_table_privilege('vinto_app', t.tbl, 'UPDATE') AS app_update_tabla,
       has_column_privilege('vinto_app', t.tbl, 'updated_at', 'UPDATE') AS app_update_updated_at,
       (SELECT count(*) FROM pg_attribute a WHERE a.attrelid = t.tbl::regclass AND a.attnum > 0 AND NOT a.attisdropped
          AND (has_column_privilege('vinto_app', t.tbl, a.attname, 'INSERT')
               OR (a.attname <> 'updated_at' AND has_column_privilege('vinto_app', t.tbl, a.attname, 'UPDATE')))) AS app_columnas_con_escritura_extra,
       CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_reference')
            THEN has_table_privilege('vinto_reference', t.tbl, 'INSERT') AND has_table_privilege('vinto_reference', t.tbl, 'UPDATE') END AS reference_insert_update,
       has_table_privilege('vinto_app', t.tbl, 'SELECT')
         AND NOT has_table_privilege('vinto_app', t.tbl, 'INSERT') AND NOT has_table_privilege('vinto_app', t.tbl, 'UPDATE')
         AND has_column_privilege('vinto_app', t.tbl, 'updated_at', 'UPDATE')
         AND (SELECT count(*) FROM pg_attribute a WHERE a.attrelid = t.tbl::regclass AND a.attnum > 0 AND NOT a.attisdropped
                AND (has_column_privilege('vinto_app', t.tbl, a.attname, 'INSERT')
                     OR (a.attname <> 'updated_at' AND has_column_privilege('vinto_app', t.tbl, a.attname, 'UPDATE')))) = 0 AS d3b1_compliant
FROM pg_roles r
CROSS JOIN unnest(ARRAY['vinto_master.profile', 'vinto_master.machine', 'vinto_master.sector']) AS t(tbl)
WHERE r.rolname = 'vinto_app'
ORDER BY 1;

-- MF-13-01D.3B.2: ¿está listo el rol de identidad? Una fila por tabla: privilegios EFECTIVOS de vinto_identity (para comparar con vinto_app mientras D.3B.4 no se aplique).
-- Cada fila debe mostrar identity_select/insert/update coherentes con la matriz de docs/MF-13-01D3B2-integracion-rol-identidad.md. Sin filas = el rol vinto_identity no existe (D.3B.2 no adoptado).
SELECT t.tbl AS tabla,
       has_table_privilege('vinto_identity', t.tbl, 'SELECT') AS identity_select,
       has_table_privilege('vinto_identity', t.tbl, 'INSERT') AS identity_insert,
       has_table_privilege('vinto_identity', t.tbl, 'UPDATE') AS identity_update,
       has_table_privilege('vinto_identity', t.tbl, 'DELETE') AS identity_delete,
       has_table_privilege('vinto_app', t.tbl, 'INSERT') AS app_insert,
       has_table_privilege('vinto_app', t.tbl, 'UPDATE') AS app_update
FROM pg_roles r
CROSS JOIN unnest(ARRAY['vinto_master.user', 'vinto_master.user_profile', 'vinto_master.user_machine_form_grant', 'vinto_master.user_sector',
                        'vinto_auth.credential', 'vinto_auth.session', 'vinto_auth.auth_event', 'vinto_audit.audit_event']) AS t(tbl)
WHERE r.rolname = 'vinto_identity'
ORDER BY 1;

-- MF-13-01D.3B.4: estado del corte por tabla (privilegios EFECTIVOS de vinto_app sobre identidad). Tras el corte TODAS las filas deben tener d3b4_compliant = true; antes del corte (o si
-- alguien re-ejecutó 03_table_grants.sql sin 03d) todas false. Sin filas = vinto_app no existe.
SELECT t.tbl AS tabla,
       has_table_privilege('vinto_app', t.tbl, 'SELECT') AS app_select_tabla,
       has_table_privilege('vinto_app', t.tbl, 'INSERT') AS app_insert_tabla,
       has_table_privilege('vinto_app', t.tbl, 'UPDATE') AS app_update_tabla,
       has_table_privilege('vinto_app', t.tbl, 'DELETE') AS app_delete_tabla,
       NOT has_table_privilege('vinto_app', t.tbl, 'INSERT') AND NOT has_table_privilege('vinto_app', t.tbl, 'UPDATE') AND NOT has_table_privilege('vinto_app', t.tbl, 'DELETE')
         AND (t.tbl <> 'vinto_auth.credential' OR (NOT has_table_privilege('vinto_app', t.tbl, 'SELECT') AND NOT has_column_privilege('vinto_app', t.tbl, 'password_hash', 'SELECT')
                                                   AND has_column_privilege('vinto_app', t.tbl, 'username', 'SELECT')))
         AND (t.tbl <> 'vinto_auth.auth_event' OR NOT has_table_privilege('vinto_app', t.tbl, 'SELECT'))
         AND (t.tbl = 'vinto_auth.credential' OR t.tbl = 'vinto_auth.auth_event' OR has_table_privilege('vinto_app', t.tbl, 'SELECT')) AS d3b4_compliant
FROM pg_roles r
CROSS JOIN unnest(ARRAY['vinto_master.user', 'vinto_master.user_profile', 'vinto_master.user_sector', 'vinto_master.user_machine_form_grant',
                        'vinto_auth.credential', 'vinto_auth.session', 'vinto_auth.auth_event']) AS t(tbl)
WHERE r.rolname = 'vinto_app'
ORDER BY 1;
