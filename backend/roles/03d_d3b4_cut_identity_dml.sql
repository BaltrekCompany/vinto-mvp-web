-- MF-13-01D.3B.4: EL CORTE. Retira a vinto_app el DML sobre identidad y autorización, y el hash de la contraseña. Lo ejecuta vinto_migrator (propietario) SOLO con APROBACIÓN
-- INDEPENDIENTE durante el release único; preparar este archivo NO autoriza su ejecución, y deploy.sh no lo ejecuta nunca.
--
-- Procedimiento:  PGOPTIONS="-c vinto.d3b4_approval=CUT-IDENTITY-DML-APPROVED" psql -v ON_ERROR_STOP=1 -f 03d_d3b4_cut_identity_dml.sql
-- (la frase NO es una medida de seguridad: es un freno para que ningún bucle de scripts ni un copia-pega lo ejecute por accidente; la aprobación real es humana y queda en el acta del release).
--
-- Orden obligatorio (aborta si no se cumple): D.3B.1 (03b) y D.3B.2 (00c, 03c) aplicados; IDENTITY_DATABASE_URL ya definida y verificada con AMBOS roles (puerta D.3B.3,
-- backend/tests/test_d3b3_two_role_gate.py). NADA se revoca antes de comprobar, en la misma transacción, que vinto_identity tiene TODO lo que vinto_app está a punto de perder.
-- Transaccional e idempotente: cualquier guarda o verificación que falle aborta sin dejar cambios. Reversión: rollback/ROLLBACK_D3B4.sql, que DEBE ejecutarse ANTES de quitar IDENTITY_DATABASE_URL.
--
-- Lo que vinto_app CONSERVA (estrictamente necesario): SELECT de tabla sobre user, user_profile, user_sector, user_machine_form_grant y session; SELECT de las columnas user_id, username
-- y must_change de credential (resolve_session); UPDATE (last_seen_at) de session (renovar actividad); UPDATE (updated_at) de user, user_profile y user_machine_form_grant (el motor de
-- autorización toma FOR SHARE sobre esas filas dentro de las capturas: PostgreSQL exige UPDATE de al menos una columna y los disparadores de guarda impiden cambios reales); INSERT en la auditoría.

\set ON_ERROR_STOP on

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $d3b4_guard$
DECLARE
  missing text;
  tbl text;
  target regrole;
  priv text;
  -- MEMBER cubre CUALQUIER membresía (también INHERIT FALSE, SET TRUE: pg_has_role(..., 'USAGE') da false pero SET ROLE sí funciona); USAGE y SET se comprueban además de forma
  -- explícita para dar el motivo exacto. 'SET' solo existe desde PostgreSQL 16; MEMBER es un superconjunto, así que la guarda no depende de él.
  privs text[] := ARRAY['MEMBER', 'USAGE'] || CASE WHEN current_setting('server_version_num')::int >= 160000 THEN ARRAY['SET'] ELSE ARRAY[]::text[] END;
BEGIN
  IF coalesce(current_setting('vinto.d3b4_approval', true), '') <> 'CUT-IDENTITY-DML-APPROVED' THEN
    RAISE EXCEPTION 'D.3B.4 blocked: independent approval missing (set vinto.d3b4_approval; see the header of 03d_d3b4_cut_identity_dml.sql)' USING ERRCODE = 'P0001';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_app') OR NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_identity') THEN
    RAISE EXCEPTION 'D.3B.4 blocked: vinto_app or vinto_identity does not exist' USING ERRCODE = 'P0001';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_app' AND rolsuper) OR EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_identity' AND (rolsuper OR rolcreatedb OR rolcreaterole)) THEN
    RAISE EXCEPTION 'D.3B.4 blocked: vinto_app must not be a superuser and vinto_identity must not be superuser, CREATEDB or CREATEROLE' USING ERRCODE = 'P0001';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_app' AND (rolcreaterole OR rolcreatedb OR rolbypassrls OR rolreplication)) THEN
    RAISE EXCEPTION 'D.3B.4 blocked: vinto_app must not have CREATEROLE, CREATEDB, BYPASSRLS or REPLICATION (it could grant itself memberships or bypass the restrictions)' USING ERRCODE = 'P0001';
  END IF;
  -- vinto_app no pertenece a NINGÚN rol, con ninguna opción (INHERIT, SET o solo ADMIN OPTION): cualquier membresía permite eludir las restricciones del corte.
  IF EXISTS (SELECT 1 FROM pg_auth_members m WHERE m.member = 'vinto_app'::regrole) THEN
    RAISE EXCEPTION 'D.3B.4 blocked: vinto_app is a member of other roles (%); a membership with INHERIT, SET or ADMIN could bypass the cut',
      (SELECT string_agg(m.roleid::regrole::text, ', ') FROM pg_auth_members m WHERE m.member = 'vinto_app'::regrole) USING ERRCODE = 'P0001';
  END IF;
  -- ninguno de los dos roles puede asumir al otro, ni vinto_app a los roles privilegiados del modelo (migrador, referencia, administración de pruebas)
  FOREACH priv IN ARRAY privs LOOP
    IF pg_has_role('vinto_app', 'vinto_identity', priv) OR pg_has_role('vinto_identity', 'vinto_app', priv) THEN
      RAISE EXCEPTION 'D.3B.4 blocked: vinto_app and vinto_identity must not be members of each other (% membership)', priv USING ERRCODE = 'P0001';
    END IF;
  END LOOP;
  FOR target IN SELECT oid::regrole FROM pg_roles WHERE rolname IN ('vinto_migrator', 'vinto_reference', 'vinto_test_admin') LOOP
    FOREACH priv IN ARRAY privs LOOP
      IF pg_has_role('vinto_app', target, priv) OR pg_has_role('vinto_identity', target, priv) THEN
        RAISE EXCEPTION 'D.3B.4 blocked: vinto_app or vinto_identity can assume the role % (% membership)', target, priv USING ERRCODE = 'P0001';
      END IF;
    END LOOP;
  END LOOP;
  FOREACH tbl IN ARRAY ARRAY['vinto_master.profile', 'vinto_master.machine', 'vinto_master.sector', 'vinto_master."user"', 'vinto_master.user_profile', 'vinto_master.user_sector',
                             'vinto_master.user_machine_form_grant', 'vinto_auth.credential', 'vinto_auth.session', 'vinto_auth.auth_event'] LOOP
    IF to_regclass(tbl) IS NULL THEN
      RAISE EXCEPTION 'D.3B.4 blocked: table % does not exist', tbl USING ERRCODE = 'P0001';
    END IF;
    FOREACH priv IN ARRAY privs LOOP
      IF pg_has_role('vinto_app', (SELECT relowner FROM pg_class WHERE oid = tbl::regclass), priv) THEN
        RAISE EXCEPTION 'D.3B.4 blocked: vinto_app owns, or can assume (% membership) the owner of, %: privileges cannot restrict an owner', priv, tbl USING ERRCODE = 'P0001';
      END IF;
      IF pg_has_role('vinto_identity', (SELECT relowner FROM pg_class WHERE oid = tbl::regclass), priv) THEN
        RAISE EXCEPTION 'D.3B.4 blocked: vinto_identity owns, or can assume (% membership) the owner of, %', priv, tbl USING ERRCODE = 'P0001';
      END IF;
    END LOOP;
  END LOOP;
  IF NOT has_table_privilege('vinto_app', 'vinto_auth.session', 'SELECT') THEN
    RAISE EXCEPTION 'D.3B.4 blocked: vinto_app has no SELECT on vinto_auth.session; run 03_table_grants.sql first' USING ERRCODE = 'P0001';
  END IF;
  -- D.3B.1 primero: el corte parte de que profile, machine y sector ya no se escriben desde el negocio.
  IF has_table_privilege('vinto_app', 'vinto_master.profile', 'INSERT') OR has_table_privilege('vinto_app', 'vinto_master.profile', 'UPDATE')
     OR has_table_privilege('vinto_app', 'vinto_master.machine', 'UPDATE') OR has_table_privilege('vinto_app', 'vinto_master.sector', 'UPDATE')
     OR has_table_privilege('vinto_app', 'vinto_master.machine', 'INSERT') OR has_table_privilege('vinto_app', 'vinto_master.sector', 'INSERT') THEN
    RAISE EXCEPTION 'D.3B.4 blocked: D.3B.1 is not applied (03b_d3b1_restrict_catalog_writes.sql); apply it first' USING ERRCODE = 'P0001';
  END IF;
  -- Nada se revoca antes de verificar al rol de identidad: debe tener YA todo lo que vinto_app está a punto de perder.
  IF NOT has_database_privilege('vinto_identity', current_database(), 'CONNECT') THEN
    RAISE EXCEPTION 'D.3B.4 blocked: vinto_identity cannot connect to this database (03c_d3b2_identity_role_grants.sql)' USING ERRCODE = 'P0001';
  END IF;
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
    RAISE EXCEPTION 'D.3B.4 blocked: the identity role lacks %', missing USING ERRCODE = 'P0001';
  END IF;
  IF NOT has_column_privilege('vinto_identity', 'vinto_master.profile', 'active', 'UPDATE') THEN
    RAISE EXCEPTION 'D.3B.4 blocked: the identity role cannot take row locks on vinto_master.profile' USING ERRCODE = 'P0001';
  END IF;
END
$d3b4_guard$;

REVOKE INSERT, UPDATE, DELETE ON vinto_master."user", vinto_master.user_profile, vinto_master.user_sector, vinto_master.user_machine_form_grant,
                                 vinto_auth.credential, vinto_auth.session, vinto_auth.auth_event FROM vinto_app;
REVOKE SELECT ON vinto_auth.credential FROM vinto_app;
GRANT SELECT (user_id, username, must_change) ON vinto_auth.credential TO vinto_app;
GRANT UPDATE (last_seen_at) ON vinto_auth.session TO vinto_app;
GRANT UPDATE (updated_at) ON vinto_master."user", vinto_master.user_profile, vinto_master.user_machine_form_grant TO vinto_app;

-- Verificación de los privilegios EFECTIVOS tras el corte (si algo no coincide exactamente, se aborta y la transacción no deja nada).
DO $d3b4_verify$
DECLARE
  tbl text;
  col record;
  writable text;
  missing text;
BEGIN
  FOREACH tbl IN ARRAY ARRAY['vinto_master."user"', 'vinto_master.user_profile', 'vinto_master.user_sector', 'vinto_master.user_machine_form_grant',
                             'vinto_auth.credential', 'vinto_auth.session', 'vinto_auth.auth_event'] LOOP
    IF has_table_privilege('vinto_app', tbl, 'INSERT') OR has_table_privilege('vinto_app', tbl, 'UPDATE') OR has_table_privilege('vinto_app', tbl, 'DELETE') THEN
      RAISE EXCEPTION 'D.3B.4 verification failed: vinto_app still has table-level INSERT/UPDATE/DELETE on % (granted by another role?)', tbl USING ERRCODE = 'P0001';
    END IF;
    FOR col IN SELECT attname FROM pg_attribute WHERE attrelid = tbl::regclass AND attnum > 0 AND NOT attisdropped LOOP
      IF has_column_privilege('vinto_app', tbl, col.attname, 'INSERT') THEN
        RAISE EXCEPTION 'D.3B.4 verification failed: INSERT still granted on %.%', tbl, col.attname USING ERRCODE = 'P0001';
      END IF;
      writable := CASE WHEN tbl = 'vinto_auth.session' THEN 'last_seen_at'
                       WHEN tbl IN ('vinto_master."user"', 'vinto_master.user_profile', 'vinto_master.user_machine_form_grant') THEN 'updated_at' ELSE '' END;
      IF has_column_privilege('vinto_app', tbl, col.attname, 'UPDATE') <> (col.attname = writable) THEN
        RAISE EXCEPTION 'D.3B.4 verification failed: unexpected UPDATE privilege state on %.%', tbl, col.attname USING ERRCODE = 'P0001';
      END IF;
    END LOOP;
  END LOOP;
  IF has_table_privilege('vinto_app', 'vinto_auth.credential', 'SELECT') OR has_column_privilege('vinto_app', 'vinto_auth.credential', 'password_hash', 'SELECT') THEN
    RAISE EXCEPTION 'D.3B.4 verification failed: vinto_app can still read the password hash' USING ERRCODE = 'P0001';
  END IF;
  IF NOT (has_column_privilege('vinto_app', 'vinto_auth.credential', 'user_id', 'SELECT') AND has_column_privilege('vinto_app', 'vinto_auth.credential', 'username', 'SELECT')
          AND has_column_privilege('vinto_app', 'vinto_auth.credential', 'must_change', 'SELECT')) THEN
    RAISE EXCEPTION 'D.3B.4 verification failed: vinto_app lost the credential columns that session resolution reads' USING ERRCODE = 'P0001';
  END IF;
  IF has_table_privilege('vinto_app', 'vinto_auth.auth_event', 'SELECT') THEN
    RAISE EXCEPTION 'D.3B.4 verification failed: vinto_app can read vinto_auth.auth_event' USING ERRCODE = 'P0001';
  END IF;
  SELECT string_agg(needed, ', ') INTO missing
    FROM unnest(ARRAY['vinto_master."user"', 'vinto_master.user_profile', 'vinto_master.user_sector', 'vinto_master.user_machine_form_grant', 'vinto_auth.session']) AS needed
   WHERE NOT has_table_privilege('vinto_app', needed, 'SELECT');
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION 'D.3B.4 verification failed: vinto_app lost SELECT on %', missing USING ERRCODE = 'P0001';
  END IF;
  -- bloqueos del motor de autorización (FOR SHARE exige UPDATE de al menos una columna) y auditoría
  SELECT string_agg(needed, ', ') INTO missing
    FROM unnest(ARRAY['vinto_master."user"', 'vinto_master.user_profile', 'vinto_master.profile', 'vinto_master.machine', 'vinto_master.sector',
                      'vinto_master.user_machine_form_grant']) AS needed
   WHERE NOT has_column_privilege('vinto_app', needed, 'updated_at', 'UPDATE');
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION 'D.3B.4 verification failed: vinto_app can no longer take the authorization engine row locks on %', missing USING ERRCODE = 'P0001';
  END IF;
  IF NOT has_table_privilege('vinto_app', 'vinto_audit.audit_event', 'INSERT') THEN
    RAISE EXCEPTION 'D.3B.4 verification failed: vinto_app lost INSERT on the audit trail' USING ERRCODE = 'P0001';
  END IF;
  -- el cambio no debe haber quitado nada al rol de identidad
  SELECT string_agg(needed.relation || ':' || needed.privilege, ', ') INTO missing
    FROM (VALUES ('vinto_master."user"', 'UPDATE'), ('vinto_master.user_profile', 'INSERT'), ('vinto_master.user_machine_form_grant', 'UPDATE'), ('vinto_master.user_sector', 'DELETE'),
                 ('vinto_auth.credential', 'SELECT'), ('vinto_auth.credential', 'UPDATE'), ('vinto_auth.session', 'INSERT'), ('vinto_auth.session', 'UPDATE'),
                 ('vinto_auth.auth_event', 'INSERT'), ('vinto_audit.audit_event', 'INSERT')) AS needed(relation, privilege)
   WHERE NOT has_table_privilege('vinto_identity', needed.relation, needed.privilege);
  IF missing IS NOT NULL THEN
    RAISE EXCEPTION 'D.3B.4 verification failed: vinto_identity lacks %', missing USING ERRCODE = 'P0001';
  END IF;
END
$d3b4_verify$;

COMMIT;
