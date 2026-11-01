-- PROPUESTA MF-13-01D.3B — NO SE APLICA EN NINGÚN DESPLIEGUE (no la ejecuta deploy.sh ni figura en backend/roles/README.md).
-- Es el prototipo que verifica tests/test_grants_hardening_design.py en PostgreSQL aislado: separación del rol de aplicación en
--   __BUSINESS__  rol de NEGOCIO (hoy vinto_app): capturas, asignaciones, órdenes, lecturas. Pierde el DML sobre identidad y autorización.
--   __IDENTITY__  rol de IDENTIDAD/ADMINISTRACIÓN (nuevo): autenticación, sesiones, usuarios, perfiles, concesiones de sector y de máquina-formulario.
-- Se ejecuta DESPUÉS de dar a __BUSINESS__ los privilegios actuales de backend/roles/03_table_grants.sql (+ la 0007) y sustituye los placeholders.
-- Principio: lo que un SQL inyectado en un endpoint de negocio pueda hacer no debe incluir darse permisos, perfiles, sesiones ni contraseñas.
--
-- ORDEN OBLIGATORIO (lo verifica la prueba): D3B1 → D3B2 → [código D.3B.2 desplegado y verificado con ambos roles] → D3B4.
-- Ninguna revocación sobre una tabla que un consumidor todavía escribe o lee con el rol de negocio puede ejecutarse antes de que ese consumidor use el rol de identidad.
-- Las secciones « @phase » delimitan lo que cada fase ejecuta; la prueba las aplica por separado.

-- @phase D3B1
-- ---- D.3B.1: privilegios SIN consumidores (sin cambios de código) ----------------------------------------------------------------------------------
-- Ningún módulo de la aplicación escribe profile, machine ni sector (solo vinto_reference): se retira INSERT y UPDATE de tabla al rol de negocio.
-- PostgreSQL exige UPDATE (de al menos UNA columna) para cualquier bloqueo de fila: el motor de autorización toma FOR SHARE sobre estas filas dentro de las capturas.
-- Un privilegio de columna sobre updated_at basta y no permite cambiar nada relevante. Ambas sentencias van en la MISMA transacción en el script real.
REVOKE INSERT, UPDATE ON vinto_master.profile, vinto_master.machine, vinto_master.sector FROM __BUSINESS__;
GRANT UPDATE (updated_at) ON vinto_master.profile, vinto_master.machine, vinto_master.sector TO __BUSINESS__;

-- @phase D3B2
-- ---- D.3B.2: rol de identidad (SOLO concede; no revoca nada) --------------------------------------------------------------------------------------
-- Es aditivo: el rol de negocio conserva todo lo que ya tiene. Hereda lo que hoy tiene vinto_app sobre identidad/autorización, y solo eso.
GRANT USAGE ON SCHEMA vinto_master, vinto_config, vinto_audit, vinto_auth TO __IDENTITY__;
GRANT SELECT ON ALL TABLES IN SCHEMA vinto_master, vinto_config TO __IDENTITY__;
GRANT SELECT, INSERT, UPDATE ON vinto_master."user", vinto_master.user_profile, vinto_master.user_machine_form_grant TO __IDENTITY__;
GRANT SELECT, INSERT, DELETE ON vinto_master.user_sector TO __IDENTITY__;
GRANT UPDATE (active, updated_at, updated_by) ON vinto_master.profile TO __IDENTITY__;
GRANT SELECT, INSERT, UPDATE ON vinto_auth.credential, vinto_auth.session TO __IDENTITY__;
GRANT SELECT, INSERT ON vinto_auth.auth_event TO __IDENTITY__;
GRANT INSERT ON vinto_audit.audit_event TO __IDENTITY__;  -- los triggers de auditoría son SECURITY INVOKER

-- @phase D3B4
-- ---- D.3B.4: CORTE (solo tras verificar login, logout, administración, CLI y capturas con AMBOS roles reales) -----------------------------------------
-- Guarda 1: los dos roles deben ser distintos; con el mismo rol este corte dejaría sin administración a todos.
-- Guarda 2: el rol de identidad debe tener ya TODO lo que el de negocio está a punto de perder. Si no, el corte aborta sin cambiar nada.
DO $guard$
DECLARE missing text;
BEGIN
  IF '__IDENTITY__' = '__BUSINESS__' THEN
    RAISE EXCEPTION 'D.3B.4 blocked: identity and business roles are the same role' USING ERRCODE = 'P0001';
  END IF;
  SELECT string_agg(needed.relation || ':' || needed.privilege, ', ') INTO missing
    FROM (VALUES ('vinto_master."user"', 'SELECT'), ('vinto_master."user"', 'INSERT'), ('vinto_master."user"', 'UPDATE'),
                 ('vinto_master.user_profile', 'SELECT'), ('vinto_master.user_profile', 'INSERT'), ('vinto_master.user_profile', 'UPDATE'),
                 ('vinto_master.user_machine_form_grant', 'SELECT'), ('vinto_master.user_machine_form_grant', 'INSERT'), ('vinto_master.user_machine_form_grant', 'UPDATE'),
                 ('vinto_master.user_sector', 'SELECT'), ('vinto_master.user_sector', 'INSERT'), ('vinto_master.user_sector', 'DELETE'),
                 ('vinto_auth.credential', 'SELECT'), ('vinto_auth.credential', 'INSERT'), ('vinto_auth.credential', 'UPDATE'),
                 ('vinto_auth.session', 'SELECT'), ('vinto_auth.session', 'INSERT'), ('vinto_auth.session', 'UPDATE'),
                 ('vinto_auth.auth_event', 'SELECT'), ('vinto_auth.auth_event', 'INSERT'),
                 ('vinto_audit.audit_event', 'INSERT')) AS needed(relation, privilege)
   WHERE NOT has_table_privilege('__IDENTITY__', needed.relation, needed.privilege);
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION 'D.3B.4 blocked: the identity role lacks %', missing USING ERRCODE = 'P0001';
  END IF;
END $guard$;

REVOKE INSERT, UPDATE, DELETE ON vinto_master."user", vinto_master.user_profile, vinto_master.user_sector, vinto_master.user_machine_form_grant,
                                 vinto_auth.credential, vinto_auth.session, vinto_auth.auth_event FROM __BUSINESS__;

-- el negocio solo necesita de la credencial lo que lee resolve_session: nunca el hash de la contraseña
REVOKE SELECT ON vinto_auth.credential FROM __BUSINESS__;
GRANT SELECT (user_id, username, must_change) ON vinto_auth.credential TO __BUSINESS__;

-- renovar la actividad de una sesión (resolve_session) es lo único que el negocio escribe en vinto_auth.session
GRANT UPDATE (last_seen_at) ON vinto_auth.session TO __BUSINESS__;

-- bloqueos FOR SHARE del motor sobre las filas de identidad (ver D3B1)
GRANT UPDATE (updated_at) ON vinto_master."user", vinto_master.user_profile, vinto_master.user_machine_form_grant TO __BUSINESS__;

-- @phase ROLLBACK_D3B4
-- ---- Reversión del corte: SOLO concede al rol de negocio lo que tenía (no toca al rol de identidad) -------------------------------------------------
-- Tras esta fase ambos roles pueden administrar: nunca hay un estado en que ninguno pueda. Solo después se puede quitar IDENTITY_DATABASE_URL.
GRANT SELECT, INSERT, UPDATE ON vinto_master."user", vinto_master.user_profile, vinto_master.user_machine_form_grant, vinto_auth.credential, vinto_auth.session TO __BUSINESS__;
GRANT SELECT, INSERT, DELETE ON vinto_master.user_sector TO __BUSINESS__;
GRANT INSERT ON vinto_auth.auth_event TO __BUSINESS__;

-- @phase ROLLBACK_D3B1
-- ---- Reversión de D.3B.1 ----------------------------------------------------------------------------------------------------------------------------
GRANT INSERT, UPDATE ON vinto_master.profile, vinto_master.machine, vinto_master.sector TO __BUSINESS__;
