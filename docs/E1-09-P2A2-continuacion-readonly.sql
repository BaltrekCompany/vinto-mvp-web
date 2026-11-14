-- E1-09 P2-A2 / VINTO — REANUDAR DIAGNÓSTICO (sin volver a correr A-G).
-- Consulta de catálogo + distribución OT/sector y capturas huérfanas.
-- Esta consulta NO accede a vinto_meta.* por nombre, NO incrementa privilegios
-- y no examina credenciales, auditoría ni contenido de capturas.
-- Ejecutar SOLO por stdin sobre vinto-mvp-postgres, psql -X -w como
-- vinto_app en vinto_piloto, ON_ERROR_STOP=1 y previa confirmación de identidad Docker.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '10000ms';
SET LOCAL lock_timeout = '1000ms';

SELECT 1 / CASE WHEN current_database()='vinto_piloto'
                 AND current_user='vinto_app'
                 AND current_setting('transaction_read_only')='on'
                 AND current_setting('transaction_isolation')='repeatable read'
                 AND to_regclass('vinto_txn.work_order') IS NOT NULL
                 AND to_regclass('vinto_txn.work_order_line_execution') IS NULL
                THEN 1 ELSE 0 END AS guard_p2a2_ok;
SELECT transaction_timestamp() AT TIME ZONE 'America/La_Paz'
         AS corte_bolivia,
       current_database() AS base, current_user AS rol;

-- H2. Catálogo público: verificar grants efectivos incluso en esquemas
-- donde vinto_app no tiene USAGE. No usar to_regclass('vinto_meta.*').
SELECT n.nspname AS esquema,
       c.relname AS tabla,
       has_schema_privilege(current_user,n.oid,'USAGE') AS uso_esquema,
       has_table_privilege(current_user,c.oid,'SELECT') AS select_tabla,
       (has_schema_privilege(current_user,n.oid,'USAGE')
         AND has_table_privilege(current_user,c.oid,'SELECT')) AS lectura_efectiva
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
WHERE c.relkind IN ('r','p') AND (n.nspname,c.relname) IN (
  ('vinto_audit','audit_event'),
  ('vinto_audit','import_record'),
  ('vinto_txn','capture_group_row'),
  ('vinto_txn','capture_detail'),
  ('vinto_txn','bobbin'),
  ('vinto_txn','bobbin_relation'),
  ('vinto_txn','quality_release'),
  ('vinto_meta','schema_migration')
)
ORDER BY n.nspname,c.relname;
-- REGLA: uso_esquema=false o select_tabla=false => NO CONSULTAR la tabla.
-- Si no hay fila para un objeto esperado, marcar NO VERIFICADO.

-- I2. Cuántas OT hay por sector de cabecera, máquina y estado.
-- Esto NO reproduce visibilidad por permiso ni versiones multimáquina.
SELECT s.code AS sector_cabecera, m.code AS maquina_cabecera,
       wo.status AS estado_ot, count(*)::bigint AS ots
FROM vinto_txn.work_order wo
JOIN vinto_master.machine m ON m.id=wo.machine_id
JOIN vinto_master.sector s ON s.id=m.sector_id
GROUP BY s.code,m.code,wo.status
ORDER BY s.code,m.code,wo.status;

-- J2. Capturas no vinculadas por assignment_id, por sector/máquina/estado.
-- No atribuirlas a ninguna OT ni a datos borrables.
SELECT s.code AS sector, m.code AS maquina, c.status AS estado_captura,
       count(*)::bigint AS capturas_sin_asignacion
FROM vinto_txn.capture c
JOIN vinto_master.machine m ON m.id=c.machine_id
JOIN vinto_master.sector s ON s.id=m.sector_id
WHERE c.assignment_id IS NULL
GROUP BY s.code,m.code,c.status
ORDER BY s.code,m.code,c.status;

COMMIT;
