-- ROLLBACK_D3B1 (MF-13-01D.3B.1): restaura a vinto_app el estado de 03_table_grants.sql sobre vinto_master.profile, machine y sector. Lo ejecuta
-- vinto_migrator (propietario). NO es un paso del aprovisionamiento: es la reversión manual de 03b_d3b1_restrict_catalog_writes.sql.
--
-- Orden: (1) ejecutar este archivo; (2) retirar 03b del procedimiento de aprovisionamiento; de lo contrario el siguiente 03 + 03b volvería a endurecer.
-- No toca vinto_reference ni ningún otro rol, no crea roles y no modifica datos. Idempotente y transaccional.

\set ON_ERROR_STOP on

BEGIN;

SET LOCAL lock_timeout = '5s';

DO $d3b1_rb_guard$
DECLARE
  tbl text;
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_app') THEN
    RAISE EXCEPTION 'ROLLBACK_D3B1 blocked: role vinto_app does not exist' USING ERRCODE = 'P0001';
  END IF;
  FOREACH tbl IN ARRAY ARRAY['vinto_master.profile', 'vinto_master.machine', 'vinto_master.sector'] LOOP
    IF to_regclass(tbl) IS NULL THEN
      RAISE EXCEPTION 'ROLLBACK_D3B1 blocked: table % does not exist', tbl USING ERRCODE = 'P0001';
    END IF;
  END LOOP;
END
$d3b1_rb_guard$;

-- el privilegio de columna se retira antes para no dejar una entrada de ACL de columna redundante junto al privilegio de tabla
REVOKE UPDATE (updated_at) ON vinto_master.profile, vinto_master.machine, vinto_master.sector FROM vinto_app;
GRANT INSERT, UPDATE ON vinto_master.profile, vinto_master.machine, vinto_master.sector TO vinto_app;

DO $d3b1_rb_verify$
DECLARE
  tbl text;
BEGIN
  FOREACH tbl IN ARRAY ARRAY['vinto_master.profile', 'vinto_master.machine', 'vinto_master.sector'] LOOP
    IF NOT (has_table_privilege('vinto_app', tbl, 'SELECT') AND has_table_privilege('vinto_app', tbl, 'INSERT') AND has_table_privilege('vinto_app', tbl, 'UPDATE')) THEN
      RAISE EXCEPTION 'ROLLBACK_D3B1 verification failed: SELECT/INSERT/UPDATE not restored on %', tbl USING ERRCODE = 'P0001';
    END IF;
  END LOOP;
END
$d3b1_rb_verify$;

COMMIT;
