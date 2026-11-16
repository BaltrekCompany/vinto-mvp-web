-- VINTO D-I -- verificacion agregada de cobertura temporal (NO EJECUTADO).
-- Fuente: backend/migrations/0001_initial_schema.sql y 0013_work_order_line_execution.sql.
-- Ejecutar desde Codex usando un rol con SELECT ya autorizado, en VPS; sin elevar privilegios.
-- NO imprime IDs ni usuarios: las claves internas se usan solo en CTE.
-- Las duraciones son intervalos de habilitacion administrativa, NO tiempo efectivo de produccion.
-- Rango semiabierto [created_at, finished_at). Para asignaciones aun activas se usa
-- el fin de la ejecucion finalizada como limite superior del analisis.
-- No usa funciones de escritura, tablas temporales ni cambios en produccion.

BEGIN TRANSACTION READ ONLY;
SET LOCAL statement_timeout = '15s';

WITH executions AS (
  SELECT e.baseline_line_id, e.work_order_id, e.machine_id,
         bl.line_code, e.started_at, e.finished_at
  FROM vinto_txn.work_order_line_execution AS e
  JOIN vinto_txn.work_order_line AS bl
    ON bl.id = e.baseline_line_id
  JOIN vinto_txn.work_order_version AS bv
    ON bv.id = bl.work_order_version_id
  WHERE bv.kind = 'baseline'
    AND bv.version_number = 1
    AND e.status = 'finished'
    AND e.started_at IS NOT NULL
    AND e.finished_at IS NOT NULL
    AND e.finished_at - e.started_at > interval '24 hours'
),
matched_assignments AS (
  SELECT e.baseline_line_id,
         GREATEST(a.created_at, e.started_at) AS interval_start,
         LEAST(COALESCE(a.finished_at, e.finished_at),
               e.finished_at) AS interval_end
  FROM executions AS e
  JOIN vinto_txn.assignment AS a
    ON a.machine_id = e.machine_id
  JOIN vinto_txn.work_order_line AS ol
    ON ol.id = a.work_order_line_id
   AND ol.line_code = e.line_code
  JOIN vinto_txn.work_order_version AS ov
    ON ov.id = ol.work_order_version_id
   AND ov.work_order_id = e.work_order_id
   AND ov.kind = 'operational'
  WHERE a.created_at < e.finished_at
    AND COALESCE(a.finished_at, e.finished_at) > e.started_at
),
clipped AS (
  SELECT ma.baseline_line_id, ma.interval_start, ma.interval_end
  FROM matched_assignments AS ma
  WHERE ma.interval_end > ma.interval_start
),
ordered_intervals AS (
  SELECT c.baseline_line_id, c.interval_start, c.interval_end,
         MAX(c.interval_end) OVER (
           PARTITION BY c.baseline_line_id
           ORDER BY c.interval_start, c.interval_end
           ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
         ) AS prev_max_end
  FROM clipped AS c
),
island_tags AS (
  SELECT oi.baseline_line_id, oi.interval_start, oi.interval_end,
         oi.prev_max_end,
         SUM(CASE WHEN oi.prev_max_end IS NULL
                    OR oi.interval_start > oi.prev_max_end
                  THEN 1 ELSE 0 END) OVER (
           PARTITION BY oi.baseline_line_id
           ORDER BY oi.interval_start, oi.interval_end
           ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
         ) AS island_no
  FROM ordered_intervals AS oi
),
islands AS (
  SELECT it.baseline_line_id, it.island_no,
         MIN(it.interval_start) AS island_start,
         MAX(it.interval_end) AS island_end
  FROM island_tags AS it
  GROUP BY it.baseline_line_id, it.island_no
),
island_steps AS (
  SELECT i.baseline_line_id, i.island_start, i.island_end,
         LAG(i.island_end) OVER (
           PARTITION BY i.baseline_line_id
           ORDER BY i.island_start, i.island_end
         ) AS prev_island_end
  FROM islands AS i
),
metrics AS (
  SELECT e.baseline_line_id, e.machine_id,
         EXTRACT(EPOCH FROM (e.finished_at - e.started_at)) AS elapsed_s,
         (SELECT COUNT(*) FROM clipped AS c
          WHERE c.baseline_line_id = e.baseline_line_id) AS assignments_count,
         (SELECT COUNT(*) FROM ordered_intervals AS oi
          WHERE oi.baseline_line_id = e.baseline_line_id
            AND oi.prev_max_end IS NOT NULL
            AND oi.interval_start < oi.prev_max_end) AS overlapping_intervals,
         (SELECT COUNT(*) FROM island_steps AS ist
          WHERE ist.baseline_line_id = e.baseline_line_id
            AND ist.prev_island_end IS NOT NULL
            AND ist.island_start > ist.prev_island_end) AS internal_gaps,
         (SELECT COALESCE(SUM(EXTRACT(EPOCH FROM
                   (i.island_end - i.island_start))), 0)
          FROM islands AS i
          WHERE i.baseline_line_id = e.baseline_line_id) AS covered_s,
         (SELECT MIN(i.island_start) FROM islands AS i
          WHERE i.baseline_line_id = e.baseline_line_id) AS first_start,
         (SELECT MAX(i.island_end) FROM islands AS i
          WHERE i.baseline_line_id = e.baseline_line_id) AS last_end,
         e.started_at, e.finished_at
  FROM executions AS e
),
classified AS (
  SELECT mt.machine_id, mt.assignments_count, mt.overlapping_intervals,
         mt.internal_gaps, mt.elapsed_s, mt.covered_s,
         (mt.elapsed_s - mt.covered_s) AS uncovered_s,
         CASE WHEN mt.first_start IS NULL THEN mt.elapsed_s
              ELSE EXTRACT(EPOCH FROM (mt.first_start - mt.started_at))
         END AS start_gap_s,
         CASE WHEN mt.last_end IS NULL THEN mt.elapsed_s
              ELSE EXTRACT(EPOCH FROM (mt.finished_at - mt.last_end))
         END AS end_gap_s
  FROM metrics AS mt
)
SELECT m.code AS machine,
       COUNT(*) AS executions_over_24h,
       COUNT(*) FILTER (WHERE c.assignments_count = 0) AS without_assignment_interval,
       COUNT(*) FILTER (WHERE c.overlapping_intervals > 0) AS with_overlaps,
       SUM(c.overlapping_intervals) AS overlap_interval_events,
       COUNT(*) FILTER (WHERE c.internal_gaps > 0) AS with_internal_gaps,
       SUM(c.internal_gaps) AS internal_gap_events,
       COUNT(*) FILTER (WHERE c.start_gap_s > 0) AS uncovered_at_start,
       COUNT(*) FILTER (WHERE c.end_gap_s > 0) AS uncovered_at_end,
       COUNT(*) FILTER (WHERE c.uncovered_s = 0) AS fully_covered,
       ROUND(SUM(c.uncovered_s) / 3600, 2) AS uncovered_calendar_hours
FROM classified AS c
JOIN vinto_master.machine AS m ON m.id = c.machine_id
GROUP BY m.code
ORDER BY m.code;

COMMIT;

-- CONTROL DE INTERPRETACION:
-- 1) La suma de executions_over_24h debe ser 16 si no hubo cambios posteriores.
-- 2) La cobertura se limita a intervalos administrativamente asignados, nunca a produccion real.
-- 3) No concluir que un hueco es un defecto sin una regla funcional aprobada.
-- 4) Si hay SQLSTATE 42501 o timeout, informar PARTIAL y NO cambiar permisos.
