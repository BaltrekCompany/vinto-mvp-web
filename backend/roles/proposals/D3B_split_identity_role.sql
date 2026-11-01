-- PROPUESTA MF-13-01D.3B — NO SE APLICA EN NINGÚN DESPLIEGUE (no la ejecuta deploy.sh ni figura en backend/roles/README.md).
-- Es el prototipo que verifica tests/test_grants_hardening_design.py en PostgreSQL 17 aislado: separación del rol de aplicación en
--   __BUSINESS__  rol de NEGOCIO (hoy vinto_app): capturas, asignaciones, órdenes, lecturas. Pierde el DML sobre identidad y autorización.
--   __IDENTITY__  rol de IDENTIDAD/ADMINISTRACIÓN (nuevo): autenticación, sesiones, usuarios, perfiles, concesiones de sector y de máquina-formulario.
-- Se ejecuta DESPUÉS de dar a __BUSINESS__ los privilegios actuales de backend/roles/03_table_grants.sql (+ la 0007) y sustituye los placeholders.
-- Principio: lo que un SQL inyectado en un endpoint de negocio pueda hacer no debe incluir darse permisos, perfiles, sesiones ni contraseñas.

-- ---- 1. rol de identidad: hereda lo que hoy tiene vinto_app sobre identidad/autorización, y solo eso -------------------------------------------
GRANT USAGE ON SCHEMA vinto_master, vinto_config, vinto_audit, vinto_auth TO __IDENTITY__;
GRANT SELECT ON ALL TABLES IN SCHEMA vinto_master, vinto_config TO __IDENTITY__;
GRANT SELECT, INSERT, UPDATE ON vinto_master."user", vinto_master.user_profile, vinto_master.user_machine_form_grant TO __IDENTITY__;
GRANT SELECT, INSERT, DELETE ON vinto_master.user_sector TO __IDENTITY__;
GRANT UPDATE (active, updated_at, updated_by) ON vinto_master.profile TO __IDENTITY__;
GRANT SELECT, INSERT, UPDATE ON vinto_auth.credential, vinto_auth.session TO __IDENTITY__;
GRANT SELECT, INSERT ON vinto_auth.auth_event TO __IDENTITY__;
GRANT INSERT ON vinto_audit.audit_event TO __IDENTITY__;  -- los triggers de auditoría son SECURITY INVOKER

-- ---- 2. rol de negocio: sin DML sobre identidad y autorización ----------------------------------------------------------------------------------
REVOKE INSERT, UPDATE, DELETE ON vinto_master."user", vinto_master.user_profile, vinto_master.profile, vinto_master.user_sector, vinto_master.user_machine_form_grant,
                                 vinto_auth.credential, vinto_auth.session, vinto_auth.auth_event FROM __BUSINESS__;
REVOKE INSERT, UPDATE ON vinto_master.machine, vinto_master.sector FROM __BUSINESS__;  -- la aplicación no las escribe (solo vinto_reference)

-- el negocio solo necesita de la credencial lo que lee resolve_session: nunca el hash de la contraseña
REVOKE SELECT ON vinto_auth.credential FROM __BUSINESS__;
GRANT SELECT (user_id, username, must_change) ON vinto_auth.credential TO __BUSINESS__;

-- renovar la actividad de una sesión (resolve_session) es lo único que el negocio escribe en vinto_auth.session
GRANT UPDATE (last_seen_at) ON vinto_auth.session TO __BUSINESS__;

-- PostgreSQL exige UPDATE (de al menos UNA columna) para cualquier bloqueo de fila: el motor de autorización toma FOR SHARE sobre estas filas dentro de las capturas.
-- Un privilegio de columna sobre updated_at basta y no permite cambiar nada relevante (los triggers de guarda rechazan todo cambio de una concesión activa que no sea revocarla).
GRANT UPDATE (updated_at) ON vinto_master."user", vinto_master.user_profile, vinto_master.profile, vinto_master.machine, vinto_master.sector,
                            vinto_master.user_machine_form_grant TO __BUSINESS__;
