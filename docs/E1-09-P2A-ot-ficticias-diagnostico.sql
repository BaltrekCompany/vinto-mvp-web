-- VINTO E1-09 P2-A — INVENTARIO DE OT FICTICIAS (NO BORRA NADA)
-- Commit de referencia: main@c64893e86a983a86d57f9a7406d0d736417f17e3
-- Ejecutar EXCLUSIVAMENTE con psql autenticado preexistente:
-- docker exec -i vinto-mvp-postgres psql -X -w -U vinto_app -d vinto_piloto -v ON_ERROR_STOP=1
-- No usar superusuario, no mostrar credenciales y no tocar TVC.
-- No imprime números OT, line_code, IDs, usuario o valores capturados.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '10000ms';
SET LOCAL lock_timeout = '1000ms';

-- A. Identidad y garantías. Error intencional ante un contexto distinto.
SELECT 1 / CASE WHEN current_database() = 'vinto_piloto'
                    AND current_user = 'vinto_app'
                    AND current_setting('transaction_read_only') = 'on'
                    AND current_setting('transaction_isolation') = 'repeatable read'
                    AND to_regclass('vinto_txn.work_order') IS NOT NULL
               THEN 1 ELSE 0 END AS guard_p2a_ok;
SELECT transaction_timestamp() AT TIME ZONE 'America/La_Paz' AS corte_local_bolivia,
       current_database() AS base, current_user AS rol,
       current_setting('transaction_read_only') AS solo_lectura,
       to_regclass('vinto_txn.work_order_line_execution') IS NOT NULL
         AS tabla_0013_esta_instalada;

-- B. Universo de todas las OT en BD. No equivale a "visibles para mi cuenta",
-- que se filtra por sector y permisos en la API.
SELECT status AS estado_ot, count(*)::bigint AS ots
FROM vinto_txn.work_order
GROUP BY status
ORDER BY status;

-- C. Versiones, líneas y asignaciones según estado de OT.
-- Subconsultas agregadas previenen multiplicación por JOIN de relaciones 1:N.
WITH versions AS (
  SELECT work_order_id, count(*)::bigint AS n
  FROM vinto_txn.work_order_version GROUP BY work_order_id
), lines AS (
  SELECT v.work_order_id, count(*)::bigint AS n,
         count(*) FILTER (WHERE v.kind = 'baseline' AND v.version_number = 1)::bigint AS baseline_n
  FROM vinto_txn.work_order_line l
  JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
  GROUP BY v.work_order_id
), assignments AS (
  SELECT v.work_order_id, count(*)::bigint AS n,
         count(*) FILTER (WHERE a.status = 'active')::bigint AS active_n,
         count(*) FILTER (WHERE a.status = 'finished')::bigint AS finished_n
  FROM vinto_txn.assignment a
  JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
  JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
  GROUP BY v.work_order_id
)
SELECT wo.status AS estado_ot,
       count(*)::bigint AS ots,
       coalesce(sum(v.n),0)::bigint AS versiones,
       coalesce(sum(l.n),0)::bigint AS lineas_todas,
       coalesce(sum(l.baseline_n),0)::bigint AS lineas_baseline,
       coalesce(sum(a.n),0)::bigint AS asignaciones,
       coalesce(sum(a.active_n),0)::bigint AS asignaciones_activas,
       coalesce(sum(a.finished_n),0)::bigint AS asignaciones_finalizadas
FROM vinto_txn.work_order wo
LEFT JOIN versions v ON v.work_order_id=wo.id
LEFT JOIN lines l ON l.work_order_id=wo.id
LEFT JOIN assignments a ON a.work_order_id=wo.id
GROUP BY wo.status ORDER BY wo.status;

-- D. Capturas referenciadas directamente por assignment_id, por estado de OT.
-- NO representa capturas sin assignment_id (pueden existir y necesitar revisión).
SELECT wo.status AS estado_ot, c.status AS estado_captura,
       count(*)::bigint AS capturas_asociadas
FROM vinto_txn.capture c
JOIN vinto_txn.assignment a ON a.id=c.assignment_id
JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
JOIN vinto_txn.work_order wo ON wo.id=v.work_order_id
GROUP BY wo.status,c.status ORDER BY wo.status,c.status;
SELECT count(*)::bigint AS capturas_sin_assignment_id
FROM vinto_txn.capture WHERE assignment_id IS NULL;

-- E. Tablas con FK hacia OT/versión/línea/asignación/captura (catalogo actual).
-- Cada FK se muestra con tipo de accion ON DELETE. No son conteos de filas.
SELECT c.confrelid::regclass::text AS tabla_referenciada,
       c.conrelid::regclass::text AS tabla_dependiente,
       count(*)::bigint AS restricciones_fk,
       CASE c.confdeltype WHEN 'r' THEN 'RESTRICT'
                          WHEN 'a' THEN 'NO ACTION'
                          WHEN 'c' THEN 'CASCADE'
                          WHEN 'n' THEN 'SET NULL'
                          WHEN 'd' THEN 'SET DEFAULT'
                          ELSE 'OTRA' END AS accion_delete
FROM pg_constraint c
WHERE c.contype='f'
AND c.confrelid IN (
 'vinto_txn.work_order'::regclass,
 'vinto_txn.work_order_version'::regclass,
 'vinto_txn.work_order_line'::regclass,
 'vinto_txn.assignment'::regclass,
 'vinto_txn.capture'::regclass,
 'vinto_txn.bobbin'::regclass)
GROUP BY c.confrelid, c.conrelid, c.confdeltype ORDER BY 1,2,4;

-- F. Cadena de dependencia FK partiendo de work_order, profundidad limitada.
-- Una tabla puede surgir por más de una ruta y se lista una sola vez.
WITH RECURSIVE dep AS (
 SELECT c.conrelid AS child, 1 AS depth,
        ARRAY['vinto_txn.work_order'::regclass::oid,c.conrelid] AS path
 FROM pg_constraint c
 WHERE c.contype='f' AND c.confrelid='vinto_txn.work_order'::regclass
 UNION ALL
 SELECT c.conrelid, d.depth+1, d.path || c.conrelid
 FROM dep d JOIN pg_constraint c ON c.contype='f' AND c.confrelid=d.child
 WHERE d.depth<8 AND NOT c.conrelid=ANY(d.path)
)
SELECT child::regclass::text AS tabla_dependiente,
       min(depth) AS profundidad_minima_fk
FROM dep GROUP BY child ORDER BY 2,1;

-- G. Triggers relevantes: inspección de metadatos (no se desactivan).
SELECT t.tgrelid::regclass::text AS tabla,
       t.tgname AS nombre_trigger,
       pg_get_triggerdef(t.oid) AS definicion
FROM pg_trigger t
WHERE NOT t.tgisinternal
AND t.tgrelid IN (
 'vinto_txn.work_order'::regclass,
 'vinto_txn.work_order_version'::regclass,
 'vinto_txn.work_order_line'::regclass,
 'vinto_txn.assignment'::regclass,
 'vinto_txn.capture'::regclass,
 'vinto_audit.audit_event'::regclass
)
AND (t.tgtype::int & 8) <> 0
ORDER BY 1,2;

-- H. Reparación P2-A, 2026-11-06: el uso de to_regclass('vinto_meta.*')
-- puede dar permission denied for schema vinto_meta si vinto_app no tiene
-- USAGE. CONSULTAR SOLO EL CATALOGO, por OID, sin resolver nombres privados.
-- has_table_privilege no equivale a acceso efectivo sin USAGE de esquema.
-- NO consulta historiales, datos de auditoría ni credenciales.
SELECT n.nspname AS esquema, c.relname AS tabla,
       has_schema_privilege(current_user, n.oid, 'USAGE') AS uso_esquema,
       has_table_privilege(current_user, c.oid, 'SELECT') AS select_tabla,
       (has_schema_privilege(current_user, n.oid, 'USAGE')
        AND has_table_privilege(current_user, c.oid, 'SELECT')) AS lectura_efectiva
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
WHERE c.relkind IN ('r','p')
  AND (n.nspname, c.relname) IN (
       ('vinto_audit','audit_event'),
       ('vinto_audit','import_record'),
       ('vinto_txn','bobbin'),
       ('vinto_txn','bobbin_relation'),
       ('vinto_txn','quality_release'),
       ('vinto_txn','capture_group_row'),
       ('vinto_txn','capture_detail'),
       ('vinto_meta','schema_migration')
  )
ORDER BY n.nspname, c.relname;
-- Ausencia de fila o lectura_efectiva=false: NO VERIFICADO / SIN ACCESO.
-- No intentar SELECT sobre vinto_meta ni ampliar privilegios.

COMMIT;
