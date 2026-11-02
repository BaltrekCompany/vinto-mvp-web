-- ROLLBACK_D3B4 (MF-13-01D.3B.4): restaura a vinto_app el DML sobre identidad y autorización que le retiró 03d_d3b4_cut_identity_dml.sql. Lo ejecuta vinto_migrator (propietario).
-- NO es un paso de aprovisionamiento y ningún despliegue lo ejecuta. No requiere la frase de aprobación del corte: una reversión debe poder hacerse siempre y deprisa.
--
-- ORDEN DE LA REVERSIÓN (nunca debe existir un estado en que ningún rol pueda administrar usuarios):
--   1. Ejecutar ESTE archivo. Solo CONCEDE a vinto_app lo que tenía; no toca a vinto_identity. Desde ese momento AMBOS roles administran.
--   2. Verificar login y administración (con la conexión de negocio y con la de identidad).
--   3. SOLO ENTONCES, si se quiere volver al rol único, quitar IDENTITY_DATABASE_URL y reiniciar. Hacerlo antes (con el corte aplicado) deja login y administración sin permisos (42501).
-- Restaura la ACL EXACTA anterior al corte (los privilegios de columna que concedió el corte se retiran y los de tabla vuelven). Idempotente y transaccional.

\set ON_ERROR_STOP on

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $d3b4_rb_guard$
DECLARE
  tbl text;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_app') THEN
    RAISE EXCEPTION 'ROLLBACK_D3B4 blocked: role vinto_app does not exist' USING ERRCODE = 'P0001';
  END IF;
  FOREACH tbl IN ARRAY ARRAY['vinto_master."user"', 'vinto_master.user_profile', 'vinto_master.user_sector', 'vinto_master.user_machine_form_grant',
                             'vinto_auth.credential', 'vinto_auth.session', 'vinto_auth.auth_event'] LOOP
    IF to_regclass(tbl) IS NULL THEN
      RAISE EXCEPTION 'ROLLBACK_D3B4 blocked: table % does not exist', tbl USING ERRCODE = 'P0001';
    END IF;
  END LOOP;
END
$d3b4_rb_guard$;

REVOKE SELECT (user_id, username, must_change) ON vinto_auth.credential FROM vinto_app;
REVOKE UPDATE (last_seen_at) ON vinto_auth.session FROM vinto_app;
REVOKE UPDATE (updated_at) ON vinto_master."user", vinto_master.user_profile, vinto_master.user_machine_form_grant FROM vinto_app;

GRANT SELECT, INSERT, UPDATE ON vinto_master."user", vinto_master.user_profile, vinto_master.user_machine_form_grant, vinto_auth.credential, vinto_auth.session TO vinto_app;
GRANT SELECT, INSERT, DELETE ON vinto_master.user_sector TO vinto_app;
GRANT INSERT ON vinto_auth.auth_event TO vinto_app;

DO $d3b4_rb_verify$
DECLARE
  missing text;
BEGIN
  SELECT string_agg(needed.relation || ':' || needed.privilege, ', ') INTO missing
    FROM (VALUES ('vinto_master."user"', 'SELECT'), ('vinto_master."user"', 'INSERT'), ('vinto_master."user"', 'UPDATE'),
                 ('vinto_master.user_profile', 'SELECT'), ('vinto_master.user_profile', 'INSERT'), ('vinto_master.user_profile', 'UPDATE'),
                 ('vinto_master.user_machine_form_grant', 'SELECT'), ('vinto_master.user_machine_form_grant', 'INSERT'), ('vinto_master.user_machine_form_grant', 'UPDATE'),
                 ('vinto_master.user_sector', 'SELECT'), ('vinto_master.user_sector', 'INSERT'), ('vinto_master.user_sector', 'DELETE'),
                 ('vinto_auth.credential', 'SELECT'), ('vinto_auth.credential', 'INSERT'), ('vinto_auth.credential', 'UPDATE'),
                 ('vinto_auth.session', 'SELECT'), ('vinto_auth.session', 'INSERT'), ('vinto_auth.session', 'UPDATE'),
                 ('vinto_auth.auth_event', 'INSERT')) AS needed(relation, privilege)
   WHERE NOT has_table_privilege('vinto_app', needed.relation, needed.privilege);
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION 'ROLLBACK_D3B4 verification failed: vinto_app still lacks %', missing USING ERRCODE = 'P0001';
  END IF;
  IF has_table_privilege('vinto_app', 'vinto_auth.auth_event', 'SELECT') OR has_table_privilege('vinto_app', 'vinto_master.user_sector', 'UPDATE') THEN
    RAISE EXCEPTION 'ROLLBACK_D3B4 verification failed: vinto_app has more privileges than before the cut' USING ERRCODE = 'P0001';
  END IF;
END
$d3b4_rb_verify$;

COMMIT;
