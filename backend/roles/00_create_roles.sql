-- CLOUD-01B-2: aprovisionamiento de las 4 identidades del modelo de privilegios mínimos.
--
-- Ejecuta este archivo el administrador del clúster (el rol de arranque de PostgreSQL, p. ej. el
-- superusuario de la imagen oficial), UNA SOLA VEZ por clúster/entorno. Ninguno de los 4 roles creados
-- aquí recibe SUPERUSER, CREATEDB ni CREATEROLE, salvo vinto_test_admin (CREATEDB, y solo en DEV/QA:
-- ver nota al final de este archivo). Ninguno puede crear otros roles.
--
-- No contiene contraseñas reales: sustituir :'app_password' etc. al invocar psql, por ejemplo:
--   psql -v app_password=... -v migrator_password=... -v reference_password=... -v test_admin_password=... \
--        -f 00_create_roles.sql
-- Las variables son obligatorias; psql falla si falta alguna (ON_ERROR_STOP más abajo solo detiene en
-- el primer error de SQL, no sustituye la obligación de pasar las 4 variables).

\set ON_ERROR_STOP on

CREATE ROLE vinto_app       LOGIN PASSWORD :'app_password'       NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE ROLE vinto_migrator  LOGIN PASSWORD :'migrator_password'  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
CREATE ROLE vinto_reference LOGIN PASSWORD :'reference_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;

-- vinto_test_admin: exclusivo de DEV/QA (principio 4). En un entorno operativo este bloque se omite
-- por completo; el rol no debe existir allí, ni siquiera deshabilitado.
CREATE ROLE vinto_test_admin LOGIN PASSWORD :'test_admin_password' NOSUPERUSER CREATEDB NOCREATEROLE NOINHERIT;

-- search_path restrictivo (principio 8 / OBS-PG-03): cada rol lo fija sobre sí mismo. Ninguna consulta
-- de backend/app usa un nombre de tabla sin calificar de esquema (verificado: CLOUD-01B-2, Fase A),
-- así que esto no tiene efecto funcional alguno sobre el código existente.
ALTER ROLE vinto_app       SET search_path = '';
ALTER ROLE vinto_migrator  SET search_path = '';
ALTER ROLE vinto_reference SET search_path = '';
ALTER ROLE vinto_test_admin SET search_path = '';
