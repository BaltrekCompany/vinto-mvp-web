# VINTO E1-09 — Diseño de consulta SQL de solo lectura para esquema pre-E1

**Estado: DISEÑO APROBABLE, CONSULTAS NO EJECUTADAS.**  
Release verificado por Codex SSH: \`86e4ec4fa6f6bf95c0e099279d8c51a016c7a6a4\`, coincidente con \`main\`. Servicios MVP y \`vinto-mvp-postgres\` saludables. El release no incluye \`0013\` ni \`WORK_ORDER_LINE_EXECUTION_ENABLED\` (esperado).

## Límites y decisión

El código versionado hasta 0012 permite diseñar las consultas. **No prueba qué migraciones hay instaladas en PostgreSQL real.** Primero confirmar host, base, rol, permisos y versión de esquema; ejecutar el bloque de conteos solo si las comprobaciones pasan.

Usar SOLO PostgreSQL dedicado \`vinto-mvp-postgres\`, base operativa identificada por el despliegue del MVP, y NO \`postgres-vinto\` (TVC), NO puerto \`6543\`, NO operaciones fuera del MVP.

\`deploy/mvp/scripts/lib_common.sh\` proporciona \`pg_run_sql_inline\`, pero **crea y luego elimina un archivo .pgpass temporal** dentro del contenedor (aunque no modifica tablas). Por tanto, no ejecutar ese helper bajo una orden de "cero modificación de archivos" sin autorización específica. No extraer, imprimir, copiar ni pasar contraseñas por argumentos de línea de comandos; tampoco hacer \`source\` de .env. Si no existe conexión autorizada no interactiva y segura, detenerse y declarar "SIN ACCESO SQL CONFIRMADO". No crear roles ni cambiar grants para este diagnóstico.

### Requisitos obligatorios del ejecutor

1. Acceso previamente autorizado, preferentemente rol de solo lectura sobre tablas del MVP. Si el rol tiene capacidad de escritura, SQL se debe limitar mediante \`BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY\`; aun así, la conexión requiere aprobación del usuario y no equivale a rol de privilegios mínimos.
2. \`psql -X -v ON_ERROR_STOP=1\` con comandos SQL revisados, sin \`psqlrc\`, sin comandos de shell desde psql ni formato que exponga valores individuales.
3. \`SET LOCAL statement_timeout = '10000ms'\`, \`SET LOCAL lock_timeout = '1000ms'\`. No dejar una transacción abierta. Ante error: \`ROLLBACK\`/terminar sesión.
4. No escribir tablas, crear vistas, crear tablas temporales, usar \`EXPLAIN ANALYZE\`, \`pg_advisory_lock\`, \`pg_dump\`, scripts de migración, copiar datos fuera, ni ejecutar \`migrate.py\`.
5. Solo métricas agregadas y metadatos técnicos; no nombres de usuarios, identificadores de OT/asignación, textos de captura o secretos.
6. El SELECT no debe pedir \`FOR UPDATE\`/bloqueo de filas. Si las lecturas exigen privilegios o esquemas no disponibles, registrar NO VERIFICADO, sin remediación automática.

## Fase SQL-A — metadata y permisos (primer bloque, tras autorización)

Ejecutar en una sola sesión psql dirigida explícitamente al contenedor/base del MVP; no usar otro destino. No intentar inferir la base a partir de un nombre supuesto ni imprimir URLs completas. Este bloque NO requiere 0013.

\`\`\`sql
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '10000ms';
SET LOCAL lock_timeout = '1000ms';

SELECT current_database() AS database_name,
       current_user AS connected_role,
       current_setting('transaction_read_only') AS read_only,
       current_setting('transaction_isolation') AS isolation;

SELECT to_regclass('vinto_meta.schema_migration') IS NOT NULL AS has_history,
       to_regclass('vinto_txn.work_order') IS NOT NULL AS has_work_orders,
       to_regclass('vinto_txn.assignment') IS NOT NULL AS has_assignments,
       to_regclass('vinto_master.machine') IS NOT NULL AS has_machines,
       to_regclass('vinto_txn.work_order_line_execution') IS NOT NULL
           AS has_execution_0013;

SELECT table_schema, table_name, column_name
FROM information_schema.columns
WHERE (table_schema, table_name) IN (
    ('vinto_txn', 'work_order'),
    ('vinto_txn', 'assignment'),
    ('vinto_txn', 'work_order_version'),
    ('vinto_txn', 'work_order_line'),
    ('vinto_master', 'machine'),
    ('vinto_master', 'sector'),
    ('vinto_meta', 'schema_migration')
)
AND column_name IN (
    'id', 'status', 'work_order_id', 'work_order_line_id',
    'work_order_version_id', 'machine_id', 'sector_id', 'kind',
    'line_code', 'version_number', 'version', 'filename', 'checksum',
    'code', 'operating_date'
)
ORDER BY table_schema, table_name, column_name;

COMMIT;
\`\`\`

**Punto de decisión:** solo si \`has_history=true\`, \`has_work_orders=true\`, \`has_assignments=true\`, \`has_machines=true\` y columnas de esquema esperadas están presentes, considerar fase SQL-B. Si la migración 0013 **está** instalada a pesar de que el release no la conoce, marcar \`SCHEMA_AHEAD_OF_RELEASE\` y detenerse para auditoría; no activar flags ni intervenir.

**Comprobación de historial**, solo si existe y es legible \`vinto_meta.schema_migration\`:

\`\`\`sql
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '10000ms';
SELECT version, filename
FROM vinto_meta.schema_migration
ORDER BY version;
COMMIT;
\`\`\`

No imprimir checksums completos innecesariamente. Comparar las versiones con \`0001..0012\` del checkout activo; la presencia inesperada de \`0013+\` es bloqueo para continuar con la suposición de esquema pre-E1. Si no hay permisos de lectura sobre historial, registrar NO VERIFICADO, no elevar privilegios.

## Fase SQL-B — agregados del estado funcional (solo tras PASS de A)

\`\`\`sql
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '10000ms';
SET LOCAL lock_timeout = '1000ms';

SELECT status, count(*)::bigint AS ot_count
FROM vinto_txn.work_order
GROUP BY status ORDER BY status;

SELECT status, count(*)::bigint AS assignment_count
FROM vinto_txn.assignment
GROUP BY status ORDER BY status;

-- Afectación al encendido de E1: asignaciones "active" no equivalen
-- al estado lógico "in_production" (nuevo modelo 0013).
SELECT s.code AS sector, m.code AS machine,
       count(*)::bigint AS active_assignments,
       count(DISTINCT ov.work_order_id)::bigint AS distinct_work_orders
FROM vinto_txn.assignment a
JOIN vinto_master.machine m ON m.id=a.machine_id
JOIN vinto_master.sector s ON s.id=m.sector_id
JOIN vinto_txn.work_order_line ol ON ol.id=a.work_order_line_id
JOIN vinto_txn.work_order_version ov ON ov.id=ol.work_order_version_id
WHERE a.status='active'
GROUP BY s.code,m.code ORDER BY s.code,m.code;

-- Inconsistencias agregadas: estado de OT y tipo de versión.
SELECT count(*) FILTER (WHERE wo.status='closed')::bigint
            AS active_on_closed_ots,
       count(*) FILTER (WHERE ov.kind<>'operational')::bigint
            AS active_from_nonoperational_versions
FROM vinto_txn.assignment a
JOIN vinto_txn.work_order_line ol ON ol.id=a.work_order_line_id
JOIN vinto_txn.work_order_version ov ON ov.id=ol.work_order_version_id
JOIN vinto_txn.work_order wo ON wo.id=ov.work_order_id
WHERE a.status='active';

-- Regla pre-E1: nunca dos OT distintas habilitadas en una misma máquina.
SELECT count(*)::bigint AS machines_with_distinct_active_ots
FROM (
  SELECT a.machine_id
  FROM vinto_txn.assignment a
  JOIN vinto_txn.work_order_line ol ON ol.id=a.work_order_line_id
  JOIN vinto_txn.work_order_version ov ON ov.id=ol.work_order_version_id
  WHERE a.status='active'
  GROUP BY a.machine_id
  HAVING count(DISTINCT ov.work_order_id)>1
) violations;

-- Cantidad de líneas originales en OT en progreso, para planear la
-- reconciliación 0013. No se exponen IDs ni cantidades por producto.
SELECT count(*)::bigint AS baseline_lines_in_progress
FROM vinto_txn.work_order_line bl
JOIN vinto_txn.work_order_version bv ON bv.id=bl.work_order_version_id
JOIN vinto_txn.work_order wo ON wo.id=bv.work_order_id
WHERE bv.kind='baseline' AND bv.version_number=1 AND wo.status='in_progress';

COMMIT;
\`\`\`

Este bloque no intenta leer \`work_order_line_execution\` si está ausente, ni presume que una asignación \`active\` produce físicamente. No se infiere un saldo cancelado ni se transfieren cantidades entre turnos.

## Interpretación y NO-GO

- \`0013\` ausente + base \`0001..0012\`: estado esperado antes de E1. Si hay OT en curso o asignaciones activas, reportar sus conteos y diseñar **corte funcional con Supervisión** antes de activar el nuevo control.
- \`0013\` instalada pese a checkout sin 0013: investigar deriva de esquema (no desplegar hasta aclararlo).
- Cualquier asignación \`active\` de una OT cerrada, asignación de versión no operativa o varias OT activas en misma máquina: bloqueante para GO del nuevo modelo.
- **Incluso con cero incidencias:** todavía faltan la futura migración 0013, privilegios adecuados, reconciliación del esquema postmigración, validación funcional y rollback. No es autorización de merge ni despliegue.

## Salida esperada de Codex

- Identidad de la base **solo por nombre**, rol utilizado (sin contraseña) y validación de \`READ ONLY\`.
- Rango de migraciones aplicado y si la tabla \`0013\` existe.
- Tabla de agregados por estado y por sector/máquina.
- Alertas de integridad; sin filas con OT individuales ni usuarios.
- Lista PASS/FAIL/NO VERIFICADO y decisión separada "GO para fase SQL-B" y "GO/NO-GO de despliegue".
