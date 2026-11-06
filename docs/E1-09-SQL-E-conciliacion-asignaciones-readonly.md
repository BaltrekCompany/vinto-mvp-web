# VINTO E1-09 — SQL-E: conciliación agregada de asignaciones existentes (READ ONLY)

**Estado:** procedimiento preparado y revisado sobre DDL del MVP; **no ejecutado contra la VPS**.  
**Origen:** SQL-A/B/C/D sobre \`vinto_piloto\` (PostgreSQL 17, \`vinto-mvp-postgres\`, rol \`vinto_app\`).  
**Baseline del último corte:** 12 OT en progreso; 16 líneas baseline; 11 asignaciones activas, todas con correspondencia única; 5 líneas baseline sin asignación activa. El corte NO se asume vigente indefinidamente.  
**GitHub:** E1-02 a E1-08 ya integrados en \`main@a8a8beaf611e8d892658eeabb5a5e1b972a32316\`; la VPS fue observada previamente en release \`86e4ec4\` (NO afirmar que sigue igual sin revalidar).

## Objetivo y límites

Repetir la conciliación de 11 asignaciones a líneas baseline y clasificar las líneas **sin asignación activa** según tengan o no antecedentes \`assignment.finished\` dentro del MVP, por OT + \`line_code\` + máquina. Producir solo agregados totales, por categoría de OT y por sector/máquina. **Ningún resultado confirma trabajo físico, turno vigente ni línea lógica \`finished\`.**

- Permisos existentes exclusivamente: \`vinto_app\` sobre tablas funcionales ya verificadas por SQL-A3. **No consultar \`vinto_meta\`** (acceso denegado intencionalmente).
- Una transacción \`REPEATABLE READ READ ONLY\`, \`statement_timeout=10s\`, \`lock_timeout=1s\`, fin con \`COMMIT\`; si algún control falla, no seguir y terminar sesión.
- No ver, exportar ni publicar \`work_order.number\`, UUID, \`line_code\`, PV, usuarios, datos de captura o campos de producción. Las claves de relación se usan solamente dentro de los CTE y no se imprimen.
- No emplear \`CREATE TEMP\`, \`COPY\`, \`INSERT\`, \`UPDATE\`, \`DELETE\`, funciones de la app, \`migrate.py\`, ayudas que escriban \`.pgpass\`, acceso a \`.env\`, grants o privilegios adicionales. Ni escribir archivos en el VPS.
- Solo el contenedor exacto \`vinto-mvp-postgres\`, la base \`vinto_piloto\` y el rol \`vinto_app\`; **TVC queda fuera del alcance** (no \`postgres-vinto\`, no puerto \`6543\`).
- Ejecutar desde conexión SSH ya autorizada en Codex Desktop. ChatGPT no tiene acceso SSH directo.

## SQL-E — secuencia única para pegar por stdin

El ejecutor debe verificar primero que el contenedor exacto está saludable y que \`docker exec\` con \`psql -X -w\` autentica **sin contraseña interactiva**. Si no, parar. No copiar credenciales ni introducir una alternativa con superusuario. Este comando pasa SQL por stdin; no crea archivos deliberadamente:

~~~bash
docker exec -i vinto-mvp-postgres psql -X -w -U vinto_app -d vinto_piloto -v ON_ERROR_STOP=1 <<'SQL'
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '10000ms';
SET LOCAL lock_timeout = '1000ms';

-- E0. Fail closed si hay conexión equivocada, transacción de escritura
-- o tabla 0013 instalada (no mezclar esquema antiguo con el nuevo).
SELECT 1 / CASE WHEN current_database() = 'vinto_piloto'
                 AND current_user = 'vinto_app'
                 AND current_setting('transaction_read_only') = 'on'
                 AND current_setting('transaction_isolation') = 'repeatable read'
                 AND to_regclass('vinto_txn.work_order_line_execution') IS NULL
                THEN 1 ELSE 0 END AS guard_pre_e1_ok;

SELECT (transaction_timestamp() AT TIME ZONE 'America/La_Paz') AS corte_local_bolivia,
       current_database() AS base,
       current_user AS rol,
       current_setting('transaction_read_only') AS solo_lectura;

-- E1. Conciliación ACTIVA: 0/1/>1 coincidencias baseline por OT, line_code,
-- máquina. Identificadores internos NO aparecen en la salida.
WITH active_matches AS (
 SELECT a.id,
        ov.kind AS operational_kind,
        count(bl.id) AS matches
 FROM vinto_txn.assignment a
 JOIN vinto_txn.work_order_line ol ON ol.id = a.work_order_line_id
 JOIN vinto_txn.work_order_version ov ON ov.id = ol.work_order_version_id
 LEFT JOIN vinto_txn.work_order_version bv
   ON bv.work_order_id = ov.work_order_id
  AND bv.kind = 'baseline' AND bv.version_number = 1
 LEFT JOIN vinto_txn.work_order_line bl
   ON bl.work_order_version_id = bv.id
  AND bl.line_code = ol.line_code AND bl.machine_id = a.machine_id
 WHERE a.status = 'active'
 GROUP BY a.id, ov.kind
)
SELECT count(*)::bigint AS asignaciones_activas,
       count(*) FILTER (WHERE operational_kind = 'operational' AND matches = 1)::bigint
         AS mapeo_unico,
       count(*) FILTER (WHERE operational_kind = 'operational' AND matches = 0)::bigint
         AS sin_baseline,
       count(*) FILTER (WHERE matches > 1)::bigint AS mapeo_ambiguo,
       count(*) FILTER (WHERE operational_kind <> 'operational')::bigint
         AS origen_no_operacional
FROM active_matches;

-- E2. Universo baseline y señales de historial en asignaciones por la
-- MISMA OT + line_code + máquina. "finished" aquí es turno, NO fin lógico.
WITH baseline AS (
 SELECT bv.work_order_id, bl.line_code, bl.machine_id
 FROM vinto_txn.work_order_line bl
 JOIN vinto_txn.work_order_version bv ON bv.id = bl.work_order_version_id
 JOIN vinto_txn.work_order wo ON wo.id = bv.work_order_id
 WHERE bv.kind = 'baseline' AND bv.version_number = 1
   AND wo.status = 'in_progress'
), assignment_counts AS (
 SELECT ov.work_order_id, ol.line_code, a.machine_id,
        count(*) FILTER (WHERE a.status = 'active') AS active_n,
        count(*) FILTER (WHERE a.status = 'finished') AS finished_n
 FROM vinto_txn.assignment a
 JOIN vinto_txn.work_order_line ol ON ol.id = a.work_order_line_id
 JOIN vinto_txn.work_order_version ov ON ov.id = ol.work_order_version_id
 WHERE ov.kind = 'operational'
 GROUP BY ov.work_order_id, ol.line_code, a.machine_id
), classified AS (
 SELECT b.work_order_id, b.line_code, b.machine_id,
        coalesce(c.active_n, 0) AS active_n,
        coalesce(c.finished_n, 0) AS finished_n
 FROM baseline b
 LEFT JOIN assignment_counts c
   ON c.work_order_id = b.work_order_id
  AND c.line_code = b.line_code AND c.machine_id = b.machine_id
)
SELECT count(*)::bigint AS lineas_baseline_ot_en_progreso,
       count(*) FILTER (WHERE active_n = 1)::bigint AS lineas_con_una_activa,
       count(*) FILTER (WHERE active_n > 1)::bigint AS lineas_con_multiples_activas,
       count(*) FILTER (WHERE active_n = 0)::bigint AS lineas_sin_activa,
       count(*) FILTER (WHERE active_n = 0 AND finished_n > 0)::bigint
         AS sin_activa_con_historial_finished,
       count(*) FILTER (WHERE active_n = 0 AND finished_n = 0)::bigint
         AS sin_activa_sin_asignacion_historica,
       coalesce(sum(active_n),0)::bigint AS total_activas_mapeadas
FROM classified;

-- E3. Desglose por máquina de líneas sin asignación activa. No OT/IDs.
WITH baseline AS (
 SELECT bv.work_order_id, bl.line_code, bl.machine_id,
        s.code AS sector, m.code AS maquina
 FROM vinto_txn.work_order_line bl
 JOIN vinto_txn.work_order_version bv ON bv.id = bl.work_order_version_id
 JOIN vinto_txn.work_order wo ON wo.id = bv.work_order_id
 JOIN vinto_master.machine m ON m.id = bl.machine_id
 JOIN vinto_master.sector s ON s.id = m.sector_id
 WHERE bv.kind = 'baseline' AND bv.version_number = 1 AND wo.status = 'in_progress'
), assignment_counts AS (
 SELECT ov.work_order_id, ol.line_code, a.machine_id,
        count(*) FILTER (WHERE a.status = 'active') AS active_n,
        count(*) FILTER (WHERE a.status = 'finished') AS finished_n
 FROM vinto_txn.assignment a
 JOIN vinto_txn.work_order_line ol ON ol.id = a.work_order_line_id
 JOIN vinto_txn.work_order_version ov ON ov.id = ol.work_order_version_id
 WHERE ov.kind = 'operational'
 GROUP BY ov.work_order_id, ol.line_code, a.machine_id
)
SELECT b.sector, b.maquina,
       count(*) FILTER (WHERE coalesce(c.active_n,0) = 0)::bigint AS sin_activa,
       count(*) FILTER (WHERE coalesce(c.active_n,0) = 0 AND coalesce(c.finished_n,0) > 0)::bigint
         AS con_finished_historica,
       count(*) FILTER (WHERE coalesce(c.active_n,0) = 0 AND coalesce(c.finished_n,0) = 0)::bigint
         AS sin_asignacion_historica
FROM baseline b
LEFT JOIN assignment_counts c
  ON c.work_order_id = b.work_order_id
 AND c.line_code = b.line_code AND c.machine_id = b.machine_id
GROUP BY b.sector, b.maquina
HAVING count(*) FILTER (WHERE coalesce(c.active_n,0) = 0) > 0
ORDER BY b.sector, b.maquina;

-- E4. Distribución de OT por cantidad de asignaciones activas
-- de sus líneas baseline. Nunca imprimir claves individuales de la OT.
WITH baseline AS (
 SELECT bv.work_order_id, bl.line_code, bl.machine_id
 FROM vinto_txn.work_order_line bl
 JOIN vinto_txn.work_order_version bv ON bv.id = bl.work_order_version_id
 JOIN vinto_txn.work_order wo ON wo.id = bv.work_order_id
 WHERE bv.kind='baseline' AND bv.version_number=1 AND wo.status='in_progress'
), actives AS (
 SELECT ov.work_order_id, ol.line_code, a.machine_id,
        count(*) AS active_n
 FROM vinto_txn.assignment a
 JOIN vinto_txn.work_order_line ol ON ol.id = a.work_order_line_id
 JOIN vinto_txn.work_order_version ov ON ov.id = ol.work_order_version_id
 WHERE a.status='active' AND ov.kind='operational'
 GROUP BY ov.work_order_id, ol.line_code, a.machine_id
), order_counts AS (
 SELECT b.work_order_id, count(*) AS baseline_n,
        coalesce(sum(a.active_n),0) AS active_n
 FROM baseline b
 LEFT JOIN actives a ON a.work_order_id = b.work_order_id
                     AND a.line_code = b.line_code AND a.machine_id = b.machine_id
 GROUP BY b.work_order_id
)
SELECT CASE WHEN active_n = 0 THEN 'OT sin activa'
            WHEN active_n = 1 THEN 'OT con una activa'
            ELSE 'OT con varias activas' END AS segmento,
       count(*)::bigint AS ots,
       sum(baseline_n)::bigint AS lineas_baseline,
       sum(active_n)::bigint AS asignaciones_activas_mapeadas
FROM order_counts
GROUP BY 1 ORDER BY 1;

COMMIT;
SQL
~~~

## Conciliación y cierre de lectura

Comprobar estas igualdades **dentro de un mismo snapshot**:

1. E1: \`asignaciones_activas = mapeo_unico\`, con \`sin_baseline = mapeo_ambiguo = origen_no_operacional = 0\`.
2. E2: \`lineas_baseline = con_una_activa + con_multiples_activas + sin_activa\`; \`sin_activa = sin_activa_con_historial_finished + sin_activa_sin_asignacion_historica\`; \`total_activas_mapeadas = E1.mapeo_unico\` cuando no hay duplicados.
3. E3: suma \`sin_activa\` por máquina = E2 \`lineas_sin_activa\`.
4. E4: suma OT y líneas baseline coincide con el universo E2, y suma activas mapeadas con E1.
5. Contrastar con **último corte histórico**, solo como detección de cambios: E1 = 11/11/0/0/0; E2 = 16 baseline, 11 con activa, 5 sin activa; E4 = 4 OT sin activa (5 líneas), 7 OT con una (7 líneas), 1 OT con varias (4 líneas, cuatro asignaciones). **No forzar estas cifras**: la operación puede haber cambiado desde SQL-D.

Si el guard E0 falla, hay error SQL o alguna conciliación aritmética no cuadra, dictamen **NO VERIFICADO / NO-GO** y detenerse. Si las cifras difieren solo por actividad posterior legítima, documentar \`SNAPSHOT_DRIFT\` y realizar nueva conciliación funcional con Supervisión; **no modificar datos para reproducir cifras viejas**.

### Qué todavía no establece SQL-E

- \`assignment.finished\` demuestra únicamente que una habilitación/asignación dejó de estar activa. No representa \`work_order_line_execution.finished\` ni acredita producción completa.
- Una línea sin registros \`assignment\` emparejados no prueba que nunca existiera un proceso físico o evidencia externa.
- No se inspeccionan capturas ni datos de producción. Para hacerlo hace falta un alcance separado, verificación previa de privilegios y procedimiento privado.
- La inspección de \`vinto_meta.schema_migration\` queda pendiente con el mecanismo legítimo del migrador, **sin conceder SELECT a \`vinto_app\`**.
- La migración 0013, respaldo, deployment, cambio de bandera y QA manual requieren puertas independientes.

## Formato de decisión funcional reservado a Supervisión (NO publicar IDs)

Mantener **una matriz interna, de acceso restringido**, con las 16 líneas del corte o el universo actualizado: referencia OT/línea para el supervisor, sector/máquina, ¿la línea está físicamente produciendo ahora?, ¿ya finalizó de manera definitiva?, ¿hay continuidad pendiente en otro turno?, ¿se debe habilitar para captura?, responsable de validación, fecha/hora y decisión \`VALIDADA / POR VALIDAR / BLOQUEADA\`. Esos datos **no se publican** en issues ni en logs; solo se comparte el resumen agregado por sector/máquina y número de pendientes.

**Prioridad operativa:** MP1 y MP3 (dos asignaciones activas cada una en SQL-D), y las cinco líneas sin asignación activa. Ninguna línea se promociona automáticamente a \`in_production\`, se termina ficticiamente o se reprograma por diferencia de turnos.
