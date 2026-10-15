-- CLOUD-01B-2: aprovisionamiento de las identidades NÚCLEO (aplicables a CUALQUIER entorno, incluido
-- operativo): vinto_app, vinto_migrator, vinto_reference. vinto_test_admin NO está aquí — ver
-- 00b_create_test_admin_role.sql, exclusivo de DEV/QA (principio 4, corregido en PG54-05: este archivo
-- ya no crea vinto_test_admin incondicionalmente).
--
-- Ejecuta este archivo el administrador del clúster, UNA SOLA VEZ por clúster/entorno. Ninguno de los 3
-- roles recibe SUPERUSER, CREATEDB ni CREATEROLE. Ninguno puede crear otros roles.
--
-- Idempotente (PG54-05): puede ejecutarse varias veces sin error; si un rol ya existe, se omite su
-- creación (nunca se cambia su contraseña aquí — eso es rotación, un procedimiento aparte). Cada rol
-- creado por este script queda marcado con COMMENT ON ROLE, para que una ejecución posterior (o en un
-- clúster compartido por varios proyectos) pueda distinguir "ya existe y es nuestro" (se omite en
-- silencio) de "ya existe y es de otra cosa" (se aborta sin tocarlo, con un error que detiene psql
-- gracias a -v ON_ERROR_STOP=1).
--
-- Nombres en un clúster compartido: vinto_app/vinto_migrator/vinto_reference son nombres de rol
-- GLOBALES AL CLÚSTER (PostgreSQL no tiene roles por base de datos). Si el mismo clúster hospeda más de
-- un proyecto, o más de un entorno de VINTO (DEV y QA en el mismo clúster), hay dos opciones: (a) un
-- clúster por entorno (recomendado; es el supuesto de CLOUD-01B-2A), o (b) sufijar los 4 nombres de rol
-- por entorno antes de ejecutar este archivo (vinto_app_dev, vinto_app_qa, ...) editando este archivo y
-- los demás de esta carpeta de forma consistente. Este archivo no sufija automáticamente: hacerlo con
-- seguridad exige propagar el sufijo a los 9 scripts, no solo a este.
--
-- No contiene contraseñas reales: se leen de variables de ENTORNO del proceso que invoca psql (nunca de
-- un argumento -v en la línea de comandos, que quedaría visible para cualquiera con acceso a la lista de
-- procesos del contenedor/host — PG54-03). Invocar, por ejemplo:
--   APP_PASSWORD=... MIGRATOR_PASSWORD=... REFERENCE_PASSWORD=... psql -f 00_create_roles.sql
-- Las tres variables son obligatorias; \getenv falla si faltan.

\set ON_ERROR_STOP on

\getenv app_password APP_PASSWORD
\getenv migrator_password MIGRATOR_PASSWORD
\getenv reference_password REFERENCE_PASSWORD

-- vinto_app ---------------------------------------------------------------------------------------------
SELECT (NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_app'))::text AS should_create \gset
\if :should_create
CREATE ROLE vinto_app LOGIN PASSWORD :'app_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
ALTER ROLE vinto_app SET search_path = '';
COMMENT ON ROLE vinto_app IS 'cloud-01b2: rol aplicativo (DML), creado por backend/roles/00_create_roles.sql';
\else
SELECT EXISTS (SELECT 1 FROM pg_shdescription d JOIN pg_roles r ON r.oid = d.objoid
               WHERE r.rolname = 'vinto_app' AND d.description LIKE 'cloud-01b2:%')::text AS is_ours \gset
\if :is_ours
\echo 'vinto_app ya existe y es de cloud-01b2: se omite su creación'
\else
DO $$ BEGIN RAISE EXCEPTION 'vinto_app ya existe y NO está marcado como propio de cloud-01b2: posible colisión de nombres en un clúster compartido; abortando sin modificarlo (PG54-05)'; END $$;
\endif
\endif

-- vinto_migrator ------------------------------------------------------------------------------------------
SELECT (NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_migrator'))::text AS should_create \gset
\if :should_create
CREATE ROLE vinto_migrator LOGIN PASSWORD :'migrator_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
ALTER ROLE vinto_migrator SET search_path = '';
COMMENT ON ROLE vinto_migrator IS 'cloud-01b2: rol migrador (DDL, propietario), creado por backend/roles/00_create_roles.sql';
\else
SELECT EXISTS (SELECT 1 FROM pg_shdescription d JOIN pg_roles r ON r.oid = d.objoid
               WHERE r.rolname = 'vinto_migrator' AND d.description LIKE 'cloud-01b2:%')::text AS is_ours \gset
\if :is_ours
\echo 'vinto_migrator ya existe y es de cloud-01b2: se omite su creación'
\else
DO $$ BEGIN RAISE EXCEPTION 'vinto_migrator ya existe y NO está marcado como propio de cloud-01b2: posible colisión de nombres; abortando sin modificarlo (PG54-05)'; END $$;
\endif
\endif

-- vinto_reference -----------------------------------------------------------------------------------------
SELECT (NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_reference'))::text AS should_create \gset
\if :should_create
CREATE ROLE vinto_reference LOGIN PASSWORD :'reference_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
ALTER ROLE vinto_reference SET search_path = '';
COMMENT ON ROLE vinto_reference IS 'cloud-01b2: rol importador de referencias (DML acotado), creado por backend/roles/00_create_roles.sql';
\else
SELECT EXISTS (SELECT 1 FROM pg_shdescription d JOIN pg_roles r ON r.oid = d.objoid
               WHERE r.rolname = 'vinto_reference' AND d.description LIKE 'cloud-01b2:%')::text AS is_ours \gset
\if :is_ours
\echo 'vinto_reference ya existe y es de cloud-01b2: se omite su creación'
\else
DO $$ BEGIN RAISE EXCEPTION 'vinto_reference ya existe y NO está marcado como propio de cloud-01b2: posible colisión de nombres; abortando sin modificarlo (PG54-05)'; END $$;
\endif
\endif
