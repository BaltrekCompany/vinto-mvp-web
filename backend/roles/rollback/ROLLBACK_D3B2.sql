-- ROLLBACK_D3B2 (MF-13-01D.3B.2): retira a vinto_identity los privilegios que concedió 03c_d3b2_identity_role_grants.sql. Lo ejecuta vinto_migrator (propietario). NO es un paso de
-- aprovisionamiento y ningún despliegue lo ejecuta. El rol NO se elimina (queda inerte; eliminarlo es una tarea aparte).
--
-- ORDEN de la reversión (nunca debe existir un estado en que ningún rol pueda administrar usuarios):
--   1. Si D.3B.4 (el corte) se aplicó: ejecutar primero ROLLBACK_D3B4 (devuelve el DML al rol de negocio). Este archivo se NIEGA a continuar si vinto_app no tiene ese DML.
--   2. Quitar IDENTITY_DATABASE_URL del entorno del servicio y reiniciar (vuelve el rol único; es la reversión de CONEXIÓN y es suficiente por sí sola).
--   3. Solo entonces, opcionalmente, ejecutar este archivo para limpiar los privilegios del rol de identidad.
-- Idempotente y transaccional.

\set ON_ERROR_STOP on

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $d3b2_rb_guard$
DECLARE
  missing text;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_identity') THEN
    RAISE EXCEPTION 'ROLLBACK_D3B2 blocked: role vinto_identity does not exist' USING ERRCODE = 'P0001';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_app') THEN
    RAISE EXCEPTION 'ROLLBACK_D3B2 blocked: role vinto_app does not exist' USING ERRCODE = 'P0001';
  END IF;
  SELECT string_agg(needed.relation || ':' || needed.privilege, ', ') INTO missing
    FROM (VALUES ('vinto_master."user"', 'INSERT'), ('vinto_master."user"', 'UPDATE'), ('vinto_master.user_profile', 'INSERT'),
                 ('vinto_master.user_machine_form_grant', 'INSERT'), ('vinto_master.user_machine_form_grant', 'UPDATE'),
                 ('vinto_master.user_sector', 'INSERT'), ('vinto_master.user_sector', 'DELETE'),
                 ('vinto_auth.credential', 'SELECT'), ('vinto_auth.credential', 'INSERT'), ('vinto_auth.credential', 'UPDATE'),
                 ('vinto_auth.session', 'INSERT'), ('vinto_auth.session', 'UPDATE'), ('vinto_auth.auth_event', 'INSERT')) AS needed(relation, privilege)
   WHERE NOT has_table_privilege('vinto_app', needed.relation, needed.privilege);
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION 'ROLLBACK_D3B2 blocked: vinto_app lacks % (D.3B.4 is applied); run ROLLBACK_D3B4 first so that some role can still administer users', missing USING ERRCODE = 'P0001';
  END IF;
END
$d3b2_rb_guard$;

REVOKE ALL ON ALL TABLES IN SCHEMA vinto_master, vinto_config, vinto_audit, vinto_auth FROM vinto_identity;
REVOKE USAGE ON SCHEMA vinto_master, vinto_config, vinto_audit, vinto_auth FROM vinto_identity;

DO $d3b2_rb_connect$
BEGIN
  EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM vinto_identity', current_database());
END
$d3b2_rb_connect$;

DO $d3b2_rb_verify$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace, LATERAL aclexplode(c.relacl) a
              WHERE n.nspname IN ('vinto_master', 'vinto_config', 'vinto_audit', 'vinto_auth') AND a.grantee = (SELECT oid FROM pg_roles WHERE rolname = 'vinto_identity')) THEN
    RAISE EXCEPTION 'ROLLBACK_D3B2 verification failed: vinto_identity still has table privileges' USING ERRCODE = 'P0001';
  END IF;
END
$d3b2_rb_verify$;

COMMIT;
