-- CLOUD-01B-2: CONNECT/TEMPORARY sobre la base de negocio y protección frente a PUBLIC.
--
-- Ejecuta este archivo el administrador del clúster, conectado a la base de negocio objetivo
-- (dev/qa/operativa o la base efímera de prueba). Requiere pasar :dbname, por ejemplo:
--   psql -v dbname=vinto_cloud01b2 -f 01_database_grants.sql -d vinto_cloud01b2
--
-- OBS-PG-03 / principio 8: se revoca explícitamente el CONNECT que PostgreSQL concede a PUBLIC por
-- defecto sobre cualquier base nueva, y se concede solo a los 3 roles que de verdad necesitan conectarse
-- a esta base de negocio. vinto_test_admin NO recibe CONNECT aquí: opera sobre bases *_test efímeras
-- propias y sobre la base de mantenimiento "postgres" (CREATEDB no depende de este GRANT).

\set ON_ERROR_STOP on

REVOKE CONNECT, TEMPORARY ON DATABASE :"dbname" FROM PUBLIC;

GRANT CONNECT ON DATABASE :"dbname" TO vinto_app, vinto_migrator, vinto_reference;

-- CREATE sobre la base (no sobre un esquema: los esquemas todavía no existen en una base nueva) es lo
-- que permite a vinto_migrator ejecutar "CREATE SCHEMA vinto_master;" etc. dentro de 0001_initial_schema.sql,
-- y más adelante "CREATE SCHEMA IF NOT EXISTS vinto_meta" (backend/migrate.py:76). Solo vinto_migrator lo
-- recibe: ni vinto_app ni vinto_reference deben poder crear un esquema nuevo (principio 1/5/6).
GRANT CREATE ON DATABASE :"dbname" TO vinto_migrator;

-- TEMPORARY (tablas temporales de sesión) no lo necesita ningún rol hoy: ninguna consulta de
-- backend/app crea una tabla temporal. Se documenta la ausencia en vez de concederlo "por si acaso".
