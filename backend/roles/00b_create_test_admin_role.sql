-- CLOUD-01B-2 / PG54-05: vinto_test_admin, SEPARADO de 00_create_roles.sql a propósito.
--
-- EJECUTAR SOLO EN DEV O QA. NO ejecutar nunca este archivo contra un clúster/entorno operativo: el
-- rol que crea tiene CREATEDB, y su único propósito es que las suites de prueba puedan crear y destruir
-- bases *_test efímeras por sí mismas (backend/app/ephemeral_db.py, backend/prepare_test_db.py). Antes
-- de ejecutarlo, confirmar explícitamente con quien autoriza el cambio que el clúster de destino es DEV
-- o QA, nunca el operativo (no hay ninguna comprobación automática en este script que lo impida: es una
-- decisión de quien lo ejecuta, documentada aquí para que no se tome por accidente).
--
-- Mismo patrón que 00_create_roles.sql: idempotente, marcado con COMMENT ON ROLE, contraseña leída de
-- una variable de entorno (TEST_ADMIN_PASSWORD), nunca de un argumento -v en la línea de comandos.

\set ON_ERROR_STOP on

\getenv test_admin_password TEST_ADMIN_PASSWORD

SELECT (NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_test_admin'))::text AS should_create \gset
\if :should_create
CREATE ROLE vinto_test_admin LOGIN PASSWORD :'test_admin_password' NOSUPERUSER CREATEDB NOCREATEROLE NOINHERIT;
ALTER ROLE vinto_test_admin SET search_path = '';
COMMENT ON ROLE vinto_test_admin IS 'cloud-01b2: rol de aprovisionamiento de bases *_test efímeras (SOLO DEV/QA), creado por backend/roles/00b_create_test_admin_role.sql';
\else
SELECT EXISTS (SELECT 1 FROM pg_shdescription d JOIN pg_roles r ON r.oid = d.objoid
               WHERE r.rolname = 'vinto_test_admin' AND d.description LIKE 'cloud-01b2:%')::text AS is_ours \gset
\if :is_ours
\echo 'vinto_test_admin ya existe y es de cloud-01b2: se omite su creación'
\else
DO $$ BEGIN RAISE EXCEPTION 'vinto_test_admin ya existe y NO está marcado como propio de cloud-01b2: posible colisión de nombres; abortando sin modificarlo (PG54-05)'; END $$;
\endif
\endif
