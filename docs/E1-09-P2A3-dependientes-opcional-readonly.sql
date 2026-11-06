-- VINTO E1-09 P2-A3 — REFERENCIAS DIRECTAS DE CAPTURAS / BOBINAS / CALIDAD.
-- OPCIONAL y SOLO cuando P2-A2 indique lectura_efectiva=true para:
-- capture, assignment, work_order_line, work_order_version, work_order,
-- capture_group_row, capture_detail, bobbin, bobbin_relation, quality_release.
-- Si alguno es NO VERIFICADO, ausente o false, NO EJECUTAR.
-- Nunca acceder a vinto_meta, nunca cambiar privilegios, no publicar filas.
-- Los conteos NO detectan todas las relaciones semánticas, import_record
-- ni auditoría JSON; no autorizan un borrado en base activa.
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '10000ms';
SET LOCAL lock_timeout = '1000ms';

SELECT 1 / CASE WHEN current_database()='vinto_piloto'
                 AND current_user='vinto_app'
                 AND current_setting('transaction_read_only')='on'
                 AND current_setting('transaction_isolation')='repeatable read'
                 AND to_regclass('vinto_txn.work_order_line_execution') IS NULL
                 AND has_table_privilege(current_user,'vinto_txn.capture_group_row','SELECT')
                 AND has_table_privilege(current_user,'vinto_txn.capture_detail','SELECT')
                 AND has_table_privilege(current_user,'vinto_txn.bobbin','SELECT')
                 AND has_table_privilege(current_user,'vinto_txn.bobbin_relation','SELECT')
                 AND has_table_privilege(current_user,'vinto_txn.quality_release','SELECT')
                THEN 1 ELSE 0 END AS guard_p2a3_ok;

WITH linked_capture AS (
    SELECT wo.status AS status_ot,c.id AS capture_id
    FROM vinto_txn.capture c
    JOIN vinto_txn.assignment a ON a.id=c.assignment_id
    JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
    JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
    JOIN vinto_txn.work_order wo ON wo.id=v.work_order_id
), cap AS (
    SELECT status_ot,count(*)::bigint AS n FROM linked_capture GROUP BY status_ot
), detail AS (
    SELECT lc.status_ot,count(*)::bigint AS n
    FROM linked_capture lc
    JOIN vinto_txn.capture_detail cd ON cd.capture_id=lc.capture_id
    GROUP BY lc.status_ot
), grp AS (
    SELECT lc.status_ot,count(*)::bigint AS n
    FROM linked_capture lc
    JOIN vinto_txn.capture_group_row gr ON gr.capture_id=lc.capture_id
    GROUP BY lc.status_ot
), bob AS (
    SELECT lc.status_ot,count(*)::bigint AS n
    FROM linked_capture lc
    JOIN vinto_txn.bobbin b ON b.source_capture_id=lc.capture_id
    GROUP BY lc.status_ot
), br AS (
    SELECT lc.status_ot,count(*)::bigint AS n
    FROM linked_capture lc
    JOIN vinto_txn.bobbin_relation rel ON rel.capture_id=lc.capture_id
    GROUP BY lc.status_ot
), qual AS (
    SELECT lc.status_ot,count(*)::bigint AS n
    FROM linked_capture lc
    JOIN vinto_txn.bobbin b ON b.source_capture_id=lc.capture_id
    JOIN vinto_txn.quality_release q ON q.bobbin_id=b.id
    GROUP BY lc.status_ot
)
SELECT cap.status_ot,cap.n AS capturas_vinculadas,
       coalesce(detail.n,0)::bigint AS detalles_captura,
       coalesce(grp.n,0)::bigint AS filas_grupo,
       coalesce(bob.n,0)::bigint AS bobinas_fuente_captura,
       coalesce(br.n,0)::bigint AS relaciones_bobina_por_captura,
       coalesce(qual.n,0)::bigint AS decisiones_calidad_bobina_fuente
FROM cap
LEFT JOIN detail USING(status_ot)
LEFT JOIN grp USING(status_ot)
LEFT JOIN bob USING(status_ot)
LEFT JOIN br USING(status_ot)
LEFT JOIN qual USING(status_ot)
ORDER BY cap.status_ot;

-- Capturas SIN asignación y referencias directas a otras tablas.
-- Solo resumen, NO asumir que pertenecen a una OT conocida.
WITH raw AS (
    SELECT c.id FROM vinto_txn.capture c WHERE c.assignment_id IS NULL
), raw_count AS (
    SELECT count(*)::bigint AS n FROM raw
), details AS (
    SELECT count(*)::bigint AS n FROM raw c
    JOIN vinto_txn.capture_detail cd ON cd.capture_id=c.id
), groups AS (
    SELECT count(*)::bigint AS n FROM raw c
    JOIN vinto_txn.capture_group_row gr ON gr.capture_id=c.id
), bobbins AS (
    SELECT count(*)::bigint AS n FROM raw c
    JOIN vinto_txn.bobbin b ON b.source_capture_id=c.id
), relations AS (
    SELECT count(*)::bigint AS n FROM raw c
    JOIN vinto_txn.bobbin_relation r ON r.capture_id=c.id
), quality AS (
    SELECT count(*)::bigint AS n FROM raw c
    JOIN vinto_txn.bobbin b ON b.source_capture_id=c.id
    JOIN vinto_txn.quality_release q ON q.bobbin_id=b.id
)
SELECT raw_count.n AS capturas_sin_assignment,
       details.n AS detalles,
       groups.n AS filas_grupo,
       bobbins.n AS bobinas,
       relations.n AS relaciones_bobina,
       quality.n AS decisiones_calidad
FROM raw_count,details,groups,bobbins,relations,quality;

COMMIT;
