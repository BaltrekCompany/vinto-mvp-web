-- Read-only pre-check for migration 0012. Changes nothing; safe on any database (run with psql, as any reader of vinto_txn).
-- 0012 never rejects existing data (the guard fires on INSERT only), so these rows do NOT block the migration; they tell you
-- which machines hold several active assignments today, which is legitimate only with the multi-machine gate ON.
--   psql -v ON_ERROR_STOP=1 -f 0012_assignment_single_mode_preflight.sql
SELECT m.code AS machine, count(*) AS active_assignments, count(DISTINCT v.work_order_id) AS work_orders
  FROM vinto_txn.assignment a
  JOIN vinto_master.machine m ON m.id = a.machine_id
  JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
  JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
 WHERE a.status = 'active'
 GROUP BY m.code HAVING count(*) > 1 ORDER BY m.code;
-- 0 rows = every machine has at most one active assignment (expected with the gate OFF).
-- Rows with work_orders > 1 would violate 0011 and should be impossible; investigate before anything else.
