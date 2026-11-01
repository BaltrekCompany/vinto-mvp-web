-- MF-13-01D.3B.1: primer endurecimiento de privilegios. Ejecuta este archivo vinto_migrator (propietario), SIEMPRE justo DESPUÉS de 03_table_grants.sql.
--
-- Qué hace: retira a vinto_app los privilegios de TABLA INSERT y UPDATE sobre vinto_master.profile, machine y sector (ningún módulo de backend/app los
-- escribe: solo los escribe vinto_reference vía import_reference.py) y le concede únicamente UPDATE (updated_at). SELECT se conserva. PostgreSQL exige
-- UPDATE de al menos una columna para cualquier bloqueo de fila; el motor de autorización toma FOR SHARE sobre estas filas dentro de las capturas.
--
-- Por qué es un archivo APARTE de 03_table_grants.sql: 03 sigue concediendo el conjunto amplio (es la línea base documentada y la que usan las pruebas
-- de exposición de MF-13-01D.3B). Re-ejecutar 03 SOLA restaura INSERT/UPDATE sobre estas tres tablas (deriva). El procedimiento de aprovisionamiento es
-- 03 + 03b, siempre juntos y en ese orden; 07_verification_queries.sql detecta la deriva (d3b1_compliant = false).
--
-- No toca vinto_reference. No crea roles. No modifica datos. Idempotente. Todo ocurre en UNA transacción: cualquier guarda o verificación que falle
-- aborta con ON_ERROR_STOP y no deja cambios. Reversión: backend/roles/rollback/ROLLBACK_D3B1.sql (y retirar 03b del procedimiento de aprovisionamiento).
--
-- No impide todavía escalar privilegios mediante identidad, sesiones o concesiones (user_profile, credential, session, user_machine_form_grant...): eso
-- depende de completar D.3B.2 a D.3B.4 (docs/MF-13-01D3B-endurecimiento-privilegios-concesiones.md).

\set ON_ERROR_STOP on

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $d3b1_guard$
DECLARE
  tbl text;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_app') THEN
    RAISE EXCEPTION 'D.3B.1 blocked: role vinto_app does not exist' USING ERRCODE = 'P0001';
  END IF;
  IF (SELECT rolsuper FROM pg_roles WHERE rolname = 'vinto_app') THEN
    RAISE EXCEPTION 'D.3B.1 blocked: vinto_app is a superuser, privileges cannot restrict it' USING ERRCODE = 'P0001';
  END IF;
  FOREACH tbl IN ARRAY ARRAY['vinto_master.profile', 'vinto_master.machine', 'vinto_master.sector'] LOOP
    IF to_regclass(tbl) IS NULL THEN
      RAISE EXCEPTION 'D.3B.1 blocked: table % does not exist', tbl USING ERRCODE = 'P0001';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_attribute WHERE attrelid = tbl::regclass AND attname = 'updated_at' AND NOT attisdropped) THEN
      RAISE EXCEPTION 'D.3B.1 blocked: % has no updated_at column', tbl USING ERRCODE = 'P0001';
    END IF;
    -- MEMBER cubre cualquier membresía (también INHERIT FALSE, SET TRUE, que 'USAGE' no ve)
    IF pg_has_role('vinto_app', (SELECT relowner FROM pg_class WHERE oid = tbl::regclass), 'MEMBER') THEN
      RAISE EXCEPTION 'D.3B.1 blocked: vinto_app owns, or is a member of the owner of, %, privileges cannot restrict an owner', tbl USING ERRCODE = 'P0001';
    END IF;
    IF NOT has_table_privilege('vinto_app', tbl, 'SELECT') THEN
      RAISE EXCEPTION 'D.3B.1 blocked: vinto_app has no SELECT on %; run 03_table_grants.sql first', tbl USING ERRCODE = 'P0001';
    END IF;
  END LOOP;
END
$d3b1_guard$;

REVOKE INSERT, UPDATE ON vinto_master.profile, vinto_master.machine, vinto_master.sector FROM vinto_app;
GRANT UPDATE (updated_at) ON vinto_master.profile, vinto_master.machine, vinto_master.sector TO vinto_app;

-- Verificación del estado efectivo (si no coincide exactamente, se aborta y la transacción no deja nada):
--   SELECT de tabla sí; INSERT (tabla o columna) no; UPDATE de tabla no; UPDATE de columna solo en updated_at.
DO $d3b1_verify$
DECLARE
  tbl text;
  col record;
BEGIN
  FOREACH tbl IN ARRAY ARRAY['vinto_master.profile', 'vinto_master.machine', 'vinto_master.sector'] LOOP
    IF NOT has_table_privilege('vinto_app', tbl, 'SELECT') THEN
      RAISE EXCEPTION 'D.3B.1 verification failed: SELECT lost on %', tbl USING ERRCODE = 'P0001';
    END IF;
    IF has_table_privilege('vinto_app', tbl, 'INSERT') OR has_table_privilege('vinto_app', tbl, 'UPDATE') THEN
      RAISE EXCEPTION 'D.3B.1 verification failed: table-level INSERT/UPDATE still granted on % (granted by another role?)', tbl USING ERRCODE = 'P0001';
    END IF;
    FOR col IN SELECT attname FROM pg_attribute WHERE attrelid = tbl::regclass AND attnum > 0 AND NOT attisdropped LOOP
      IF has_column_privilege('vinto_app', tbl, col.attname, 'INSERT') THEN
        RAISE EXCEPTION 'D.3B.1 verification failed: INSERT still granted on %.%', tbl, col.attname USING ERRCODE = 'P0001';
      END IF;
      IF has_column_privilege('vinto_app', tbl, col.attname, 'UPDATE') <> (col.attname = 'updated_at') THEN
        RAISE EXCEPTION 'D.3B.1 verification failed: unexpected UPDATE privilege state on %.%', tbl, col.attname USING ERRCODE = 'P0001';
      END IF;
    END LOOP;
  END LOOP;
END
$d3b1_verify$;

COMMIT;
