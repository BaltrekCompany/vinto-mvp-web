-- MF-13-01D.3B.3 / D.3B.4: PREFLIGHT de roles y privilegios REALES para el release único. SOLO LECTURA (no modifica nada). Cualquier rol con visibilidad suficiente puede ejecutarlo
-- (superusuario o vinto_migrator), conectado a la base del release. No lo ejecuta deploy.sh: lo ejecuta una persona y GUARDA la salida como evidencia del punto de control.
--
--   psql -v ON_ERROR_STOP=1 -f 08_release_preflight.sql        (sin contraseñas ni URLs en la salida)
--
-- No asumir que los roles reales coinciden con los de las pruebas: este modelo de privilegios puede no estar adoptado todavía en la base del release. Cada fila del RESUMEN (último
-- bloque) responde a una pregunta del procedimiento; cualquier valor inesperado detiene el release en ese punto de control.

\set ON_ERROR_STOP on

-- 1. Roles del modelo y sus atributos (esperado: ninguno superusuario/CREATEDB/CREATEROLE salvo vinto_test_admin en DEV/QA, que NO debe existir en el release).
SELECT rolname AS rol, rolcanlogin AS login, rolsuper AS superusuario, rolcreatedb AS createdb, rolcreaterole AS createrole, rolinherit AS inherit
FROM pg_roles WHERE rolname IN ('vinto_app', 'vinto_migrator', 'vinto_reference', 'vinto_identity', 'vinto_test_admin') ORDER BY 1;

-- 2. Propietario de las tablas de identidad y de catálogo (esperado: vinto_migrator en todas; ni vinto_app ni vinto_identity son propietarios ni miembros del propietario).
SELECT t.tbl AS tabla, pg_get_userbyid(c.relowner) AS propietario,
       pg_has_role('vinto_app', c.relowner, 'USAGE') AS app_es_propietario_o_miembro,
       CASE WHEN to_regrole('vinto_identity') IS NOT NULL THEN pg_has_role('vinto_identity', c.relowner, 'USAGE') END AS identity_es_propietario_o_miembro
FROM unnest(ARRAY['vinto_master.profile', 'vinto_master.machine', 'vinto_master.sector', 'vinto_master.user', 'vinto_master.user_profile', 'vinto_master.user_sector',
                  'vinto_master.user_machine_form_grant', 'vinto_auth.credential', 'vinto_auth.session', 'vinto_auth.auth_event']) AS t(tbl)
JOIN pg_class c ON c.oid = to_regclass(t.tbl) ORDER BY 1;

-- 3. Privilegios EFECTIVOS por tabla: vinto_app frente a vinto_identity (S=SELECT I=INSERT U=UPDATE D=DELETE). PUBLIC no debe tener nada sobre estas tablas.
SELECT t.tbl AS tabla,
       concat_ws('', CASE WHEN has_table_privilege('vinto_app', t.tbl, 'SELECT') THEN 'S' END, CASE WHEN has_table_privilege('vinto_app', t.tbl, 'INSERT') THEN 'I' END,
                 CASE WHEN has_table_privilege('vinto_app', t.tbl, 'UPDATE') THEN 'U' END, CASE WHEN has_table_privilege('vinto_app', t.tbl, 'DELETE') THEN 'D' END) AS vinto_app,
       CASE WHEN to_regrole('vinto_identity') IS NOT NULL THEN concat_ws('', CASE WHEN has_table_privilege('vinto_identity', t.tbl, 'SELECT') THEN 'S' END,
                 CASE WHEN has_table_privilege('vinto_identity', t.tbl, 'INSERT') THEN 'I' END, CASE WHEN has_table_privilege('vinto_identity', t.tbl, 'UPDATE') THEN 'U' END,
                 CASE WHEN has_table_privilege('vinto_identity', t.tbl, 'DELETE') THEN 'D' END) END AS vinto_identity,
       concat_ws('', CASE WHEN has_table_privilege('public', t.tbl, 'SELECT') THEN 'S' END, CASE WHEN has_table_privilege('public', t.tbl, 'INSERT') THEN 'I' END,
                 CASE WHEN has_table_privilege('public', t.tbl, 'UPDATE') THEN 'U' END, CASE WHEN has_table_privilege('public', t.tbl, 'DELETE') THEN 'D' END) AS public
FROM unnest(ARRAY['vinto_master.profile', 'vinto_master.machine', 'vinto_master.sector', 'vinto_master.user', 'vinto_master.user_profile', 'vinto_master.user_sector',
                  'vinto_master.user_machine_form_grant', 'vinto_auth.credential', 'vinto_auth.session', 'vinto_auth.auth_event', 'vinto_audit.audit_event']) AS t(tbl)
WHERE to_regrole('vinto_app') IS NOT NULL ORDER BY 1;

-- 4. RESUMEN por fase (un booleano por pregunta). «ready_for_*» = se cumplen las precondiciones de esa fase; «*_applied» = la fase ya está aplicada.
WITH
roles AS (SELECT to_regrole('vinto_app') IS NOT NULL AS app_exists, to_regrole('vinto_identity') IS NOT NULL AS identity_exists,
                 coalesce((SELECT rolsuper FROM pg_roles WHERE rolname = 'vinto_app'), false) AS app_super,
                 coalesce((SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles WHERE rolname = 'vinto_identity'), false) AS identity_powerful),
owners AS (SELECT coalesce(bool_or(pg_has_role('vinto_app', c.relowner, 'USAGE')), false) AS app_owns
           FROM unnest(ARRAY['vinto_master.profile', 'vinto_master.user', 'vinto_auth.credential', 'vinto_auth.session']) AS t(tbl) JOIN pg_class c ON c.oid = to_regclass(t.tbl)),
d3b1 AS (SELECT count(*) FILTER (WHERE has_table_privilege('vinto_app', t.tbl, 'SELECT') AND (NOT has_table_privilege('vinto_app', t.tbl, 'INSERT') OR NOT has_table_privilege('vinto_app', t.tbl, 'UPDATE'))) AS n
         FROM unnest(ARRAY['vinto_master.profile', 'vinto_master.machine', 'vinto_master.sector']) AS t(tbl) WHERE to_regrole('vinto_app') IS NOT NULL),
d3b4 AS (SELECT count(*) FILTER (WHERE has_table_privilege('vinto_app', 'vinto_auth.session', 'SELECT') AND NOT has_table_privilege('vinto_app', t.tbl, 'INSERT')) AS n
         FROM unnest(ARRAY['vinto_master.user', 'vinto_master.user_profile', 'vinto_master.user_sector', 'vinto_auth.credential', 'vinto_auth.session', 'vinto_auth.auth_event']) AS t(tbl)
         WHERE to_regrole('vinto_app') IS NOT NULL),
identity_ok AS (SELECT coalesce(bool_and(has_table_privilege('vinto_identity', p.relation, p.privilege)), false) AS complete
                FROM (VALUES ('vinto_master.user', 'SELECT'), ('vinto_master.user', 'INSERT'), ('vinto_master.user', 'UPDATE'), ('vinto_master.user_profile', 'INSERT'),
                             ('vinto_master.user_machine_form_grant', 'INSERT'), ('vinto_master.user_machine_form_grant', 'UPDATE'), ('vinto_master.user_sector', 'INSERT'),
                             ('vinto_master.user_sector', 'DELETE'), ('vinto_auth.credential', 'SELECT'), ('vinto_auth.credential', 'INSERT'), ('vinto_auth.credential', 'UPDATE'),
                             ('vinto_auth.session', 'INSERT'), ('vinto_auth.session', 'UPDATE'), ('vinto_auth.auth_event', 'INSERT'), ('vinto_audit.audit_event', 'INSERT'))
                     AS p(relation, privilege) WHERE to_regrole('vinto_identity') IS NOT NULL),
connect_ok AS (SELECT CASE WHEN to_regrole('vinto_identity') IS NOT NULL THEN has_database_privilege('vinto_identity', current_database(), 'CONNECT') ELSE false END AS ok)
SELECT roles.app_exists                                           AS vinto_app_existe,
       roles.identity_exists                                      AS vinto_identity_existe,
       NOT roles.app_super AND NOT owners.app_owns                AS vinto_app_no_es_superusuario_ni_propietario,
       roles.identity_exists AND NOT roles.identity_powerful      AS vinto_identity_sin_atributos_peligrosos,
       d3b1.n = 3                                                 AS d3b1_aplicado,
       roles.identity_exists AND identity_ok.complete AND connect_ok.ok AS d3b2_privilegios_completos,
       d3b4.n = 6                                                 AS d3b4_aplicado,
       roles.app_exists AND NOT roles.app_super AND NOT owners.app_owns AND d3b1.n = 0                                     AS ready_for_d3b1,
       roles.app_exists AND NOT roles.app_super AND NOT owners.app_owns AND d3b1.n = 3 AND roles.identity_exists AND NOT roles.identity_powerful
         AND identity_ok.complete AND connect_ok.ok AND d3b4.n = 0                                                         AS ready_for_d3b4
FROM roles, owners, d3b1, d3b4, identity_ok, connect_ok;
