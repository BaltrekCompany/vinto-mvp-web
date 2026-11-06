-- E1-02 PRE-FLIGHT (read only). Run on the intended DB BEFORE 0013 / rollout.
-- No writes, no transition, no assumptions about what is producing.
-- Inventory active assignments and historical data to review with Supervisión.

-- A. Active assignments by machine: 2+ active rows are valid within the same OT.
SELECT m.code AS machine_code, count(*) AS active_assignments,
       count(DISTINCT v.work_order_id) AS different_work_orders,
       string_agg(DISTINCT wo.number, ', ' ORDER BY wo.number) AS work_orders
FROM vinto_txn.assignment a
JOIN vinto_master.machine m ON m.id = a.machine_id
JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
JOIN vinto_txn.work_order wo ON wo.id = v.work_order_id
WHERE a.status = 'active'
GROUP BY m.code ORDER BY m.code;

-- B. Detailed active assignments, with F3/capture counts; NOT a production-state determination.
SELECT wo.number AS ot, m.code AS machine_code, l.line_code, a.id AS assignment_id,
       a.operating_date, a.status AS assignment_status, a.created_at,
       COALESCE(c.captures,0) AS linked_captures,
       COALESCE(c.bobbins,0) AS linked_bobbins
FROM vinto_txn.assignment a
JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
JOIN vinto_txn.work_order wo ON wo.id = v.work_order_id
JOIN vinto_master.machine m ON m.id = a.machine_id
LEFT JOIN LATERAL (
  SELECT count(DISTINCT c.id) AS captures,
         count(DISTINCT b.id) AS bobbins
  FROM vinto_txn.capture c
  LEFT JOIN vinto_txn.bobbin b ON b.source_capture_id = c.id
  WHERE c.assignment_id = a.id
) c ON true
WHERE a.status = 'active'
ORDER BY m.code, wo.number, l.line_code, a.created_at;

-- C. Work orders with baseline lines; helps identify the review scope.
SELECT wo.number AS ot, wo.status AS ot_status,
       count(*) AS baseline_lines, count(DISTINCT l.machine_id) AS machines
FROM vinto_txn.work_order wo
JOIN vinto_txn.work_order_version v ON v.work_order_id = wo.id AND v.kind = 'baseline' AND v.version_number = 1
JOIN vinto_txn.work_order_line l ON l.work_order_version_id = v.id
GROUP BY wo.number,wo.status
ORDER BY wo.number;

-- D. Potentially inconsistent current active assignments from different OT on the same machine.
-- An empty result is expected from migration 0011.
SELECT m.code AS machine_code, count(DISTINCT v.work_order_id) AS different_work_orders
FROM vinto_txn.assignment a
JOIN vinto_master.machine m ON m.id = a.machine_id
JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
WHERE a.status = 'active'
GROUP BY m.code HAVING count(DISTINCT v.work_order_id) > 1;
