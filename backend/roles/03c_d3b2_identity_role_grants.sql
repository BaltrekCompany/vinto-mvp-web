-- MF-13-01D.3B.2: privilegios del rol de identidad. Ejecuta vinto_migrator (propietario), DESPUÉS de 03_table_grants.sql (y 03b si D.3B.1 está adoptado) y de crear el rol con
-- 00c_create_identity_role.sql.
--
-- SOLO CONCEDE: no revoca nada a vinto_app ni a ningún otro rol (la separación efectiva, D.3B.4, es un paso posterior y distinto). Es aditivo e idempotente, y transaccional.
-- Concede a vinto_identity lo mismo que hoy tiene vinto_app sobre identidad/autorización, y solo eso (las sentencias GRANT son las de la fase D3B2 del prototipo aprobado en
-- backend/roles/proposals/D3B_split_identity_role.sql; una prueba exige que coincidan). Tampoco es un paso de deploy.sh. Reversión: backend/roles/rollback/ROLLBACK_D3B2.sql.

\set ON_ERROR_STOP on

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $d3b2_guard$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_identity') THEN
    RAISE EXCEPTION 'D.3B.2 blocked: role vinto_identity does not exist; run 00c_create_identity_role.sql first' USING ERRCODE = 'P0001';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_app') THEN
    RAISE EXCEPTION 'D.3B.2 blocked: role vinto_app does not exist' USING ERRCODE = 'P0001';
  END IF;
  IF (SELECT rolsuper OR rolcreatedb OR rolcreaterole FROM pg_roles WHERE rolname = 'vinto_identity') THEN
    RAISE EXCEPTION 'D.3B.2 blocked: vinto_identity must not be superuser, CREATEDB or CREATEROLE' USING ERRCODE = 'P0001';
  END IF;
  IF to_regclass('vinto_auth.credential') IS NULL OR to_regclass('vinto_master.user_machine_form_grant') IS NULL THEN
    RAISE EXCEPTION 'D.3B.2 blocked: the schema is not migrated' USING ERRCODE = 'P0001';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_class c WHERE c.oid IN ('vinto_master.sector'::regclass, 'vinto_auth.credential'::regclass) AND pg_has_role('vinto_identity', c.relowner, 'USAGE')) THEN
    RAISE EXCEPTION 'D.3B.2 blocked: vinto_identity owns (or inherits the owner of) the tables' USING ERRCODE = 'P0001';
  END IF;
END
$d3b2_guard$;

DO $d3b2_connect$
BEGIN
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO vinto_identity', current_database());
END
$d3b2_connect$;

GRANT USAGE ON SCHEMA vinto_master, vinto_config, vinto_audit, vinto_auth TO vinto_identity;
GRANT SELECT ON ALL TABLES IN SCHEMA vinto_master, vinto_config TO vinto_identity;
GRANT SELECT, INSERT, UPDATE ON vinto_master."user", vinto_master.user_profile, vinto_master.user_machine_form_grant TO vinto_identity;
GRANT SELECT, INSERT, DELETE ON vinto_master.user_sector TO vinto_identity;
GRANT UPDATE (active, updated_at, updated_by) ON vinto_master.profile TO vinto_identity;
GRANT SELECT, INSERT, UPDATE ON vinto_auth.credential, vinto_auth.session TO vinto_identity;
GRANT SELECT, INSERT ON vinto_auth.auth_event TO vinto_identity;
GRANT INSERT ON vinto_audit.audit_event TO vinto_identity;

-- Verificación: vinto_identity tiene TODO lo que la aplicación hace con la conexión de identidad, y vinto_app no perdió nada (este archivo no revoca).
DO $d3b2_verify$
DECLARE
  missing text;
BEGIN
  SELECT string_agg(needed.relation || ':' || needed.privilege, ', ') INTO missing
    FROM (VALUES ('vinto_master."user"', 'SELECT'), ('vinto_master."user"', 'INSERT'), ('vinto_master."user"', 'UPDATE'),
                 ('vinto_master.user_profile', 'SELECT'), ('vinto_master.user_profile', 'INSERT'), ('vinto_master.user_profile', 'UPDATE'),
                 ('vinto_master.user_machine_form_grant', 'SELECT'), ('vinto_master.user_machine_form_grant', 'INSERT'), ('vinto_master.user_machine_form_grant', 'UPDATE'),
                 ('vinto_master.user_sector', 'SELECT'), ('vinto_master.user_sector', 'INSERT'), ('vinto_master.user_sector', 'DELETE'),
                 ('vinto_master.profile', 'SELECT'), ('vinto_master.sector', 'SELECT'), ('vinto_master.machine', 'SELECT'),
                 ('vinto_auth.credential', 'SELECT'), ('vinto_auth.credential', 'INSERT'), ('vinto_auth.credential', 'UPDATE'),
                 ('vinto_auth.session', 'SELECT'), ('vinto_auth.session', 'INSERT'), ('vinto_auth.session', 'UPDATE'),
                 ('vinto_auth.auth_event', 'SELECT'), ('vinto_auth.auth_event', 'INSERT'),
                 ('vinto_audit.audit_event', 'INSERT')) AS needed(relation, privilege)
   WHERE NOT has_table_privilege('vinto_identity', needed.relation, needed.privilege);
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION 'D.3B.2 verification failed: vinto_identity lacks %', missing USING ERRCODE = 'P0001';
  END IF;
  IF NOT has_column_privilege('vinto_identity', 'vinto_master.profile', 'active', 'UPDATE') THEN
    RAISE EXCEPTION 'D.3B.2 verification failed: vinto_identity cannot take row locks on vinto_master.profile' USING ERRCODE = 'P0001';
  END IF;
  IF has_table_privilege('vinto_identity', 'vinto_audit.audit_event', 'UPDATE') OR has_table_privilege('vinto_identity', 'vinto_audit.audit_event', 'DELETE')
     OR has_table_privilege('vinto_identity', 'vinto_master.user_machine_form_grant', 'DELETE') THEN
    RAISE EXCEPTION 'D.3B.2 verification failed: vinto_identity has more privileges than the approved design' USING ERRCODE = 'P0001';
  END IF;
END
$d3b2_verify$;

COMMIT;
