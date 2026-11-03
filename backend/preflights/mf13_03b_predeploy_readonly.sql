-- MF13-03.B · consolidated pre-deployment checks. READ ONLY: no write of any kind; run with psql as any reader of the schemas involved:
--   psql -v ON_ERROR_STOP=1 -f mf13_03b_predeploy_readonly.sql
-- Every query returns rows ONLY when something needs a human decision before turning WORK_ORDERS_MULTI_MACHINE_ENABLED on. The gate itself is a backend
-- environment setting that PostgreSQL cannot see: verify it in the backend environment file, not here.
-- 0 rows in every section = nothing blocks the activation from the data side.

-- 1. Migration history must be contiguous 1..12 and the 0012 guard enabled (expected: 12 | 12 | O).
SELECT (SELECT max(version) FROM vinto_meta.schema_migration) AS last_version,
       (SELECT count(*) FROM vinto_meta.schema_migration) AS applied,
       (SELECT tgenabled FROM pg_trigger WHERE tgname = 'validate_assignment_single_mode' AND tgrelid = 'vinto_txn.assignment'::regclass) AS single_mode_trigger;

-- 2. PREREQUISITE (PR5): with the gate ON, an OPERACION/CALIDAD user only sees machines it holds an ACTIVE machine-form grant for. Active operators with NO active grant
--    would lose the historical reads and see "Sin accesos asignados" (found by the integral QA). Decide per user: grant, or leave without access.
SELECT u.id AS user_id, u.display_name, p.code AS profile
  FROM vinto_master."user" u
  JOIN vinto_master.user_profile up ON up.user_id = u.id
  JOIN vinto_master.profile p ON p.id = up.profile_id AND p.active
 WHERE u.active AND p.code IN ('OPERACION', 'CALIDAD')
   AND NOT EXISTS (SELECT 1 FROM vinto_master.user_machine_form_grant g WHERE g.user_id = u.id AND g.revoked_at IS NULL)
 ORDER BY p.code, u.display_name;

-- 3. Machines that hold several active assignments today (legitimate only with the gate ON; with it OFF the backend answers 409 MULTIPLE_ACTIVE_ASSIGNMENTS).
SELECT m.code AS machine, count(*) AS active_assignments, count(DISTINCT v.work_order_id) AS work_orders
  FROM vinto_txn.assignment a
  JOIN vinto_master.machine m ON m.id = a.machine_id
  JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
  JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
 WHERE a.status = 'active'
 GROUP BY m.code HAVING count(*) > 1 ORDER BY m.code;

-- 4. Impossible states that must be investigated BEFORE anything else (0010/0011 should prevent them): a line without machine; a line active twice;
--    a machine with active assignments of two different work orders.
SELECT 'line_without_machine' AS problem, count(*) AS n FROM vinto_txn.work_order_line WHERE machine_id IS NULL HAVING count(*) > 0
UNION ALL
SELECT 'line_active_twice', count(*) FROM (SELECT work_order_line_id FROM vinto_txn.assignment WHERE status = 'active' GROUP BY work_order_line_id HAVING count(*) > 1) x HAVING count(*) > 0
UNION ALL
SELECT 'machine_with_two_work_orders', count(*) FROM (
  SELECT a.machine_id FROM vinto_txn.assignment a JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
   WHERE a.status = 'active' GROUP BY a.machine_id HAVING count(DISTINCT v.work_order_id) > 1) y HAVING count(*) > 0;

-- 5. Active assignments from another shift or operating date (informational: Supervisión must re-activate them before Operación can capture).
SELECT m.code AS machine, a.operating_date, count(*) AS active_assignments
  FROM vinto_txn.assignment a JOIN vinto_master.machine m ON m.id = a.machine_id
 WHERE a.status = 'active' AND a.operating_date <> (now() AT TIME ZONE 'America/La_Paz')::date
 GROUP BY m.code, a.operating_date ORDER BY m.code;
