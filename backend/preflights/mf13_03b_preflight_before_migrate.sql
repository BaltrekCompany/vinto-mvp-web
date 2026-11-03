-- MF13-03.B · PREFLIGHT BEFORE migrating (read only; nothing is written). It works on the EXISTING schema, including a database that has NOT applied migrations 0010-0012 yet:
-- it only reads objects that exist since 0009 (assignment, work_order_line without machine_id, grants, vinto_meta.schema_migration, pg_catalog). It never references anything the migrations create.
--   psql -v ON_ERROR_STOP=1 -f mf13_03b_preflight_before_migrate.sql
-- Sections 3, 4 and 5 return rows ONLY when a person has to decide before migrating. After migrating, run mf13_03b_verify_after_migrate.sql.

-- 1. Where the database is: last applied migration and how many are applied (the release's own `deploy.sh check-release <sha>` states what is PENDING for that release).
--    legacy_unique_machine_index = true means 0011 has not run yet (the one-active-per-machine unique index still exists).
SELECT (SELECT max(version) FROM vinto_meta.schema_migration) AS last_applied_version,
       (SELECT count(*) FROM vinto_meta.schema_migration) AS applied,
       EXISTS (SELECT 1 FROM pg_indexes WHERE schemaname = 'vinto_txn' AND indexname = 'assignment_one_active_machine') AS legacy_unique_machine_index;

-- 2. The migration and application roles exist (informational: expected vinto_migrator and vinto_app in a hardened environment).
SELECT rolname FROM pg_roles WHERE rolname IN ('vinto_migrator', 'vinto_app') ORDER BY rolname;

-- 3. Preconditions that migration 0011 itself checks and would ABORT on (it rolls back, but it is better to know first): a line with more than one active assignment, or a machine
--    with active assignments of two different work orders. Both should be impossible under the legacy unique index.
SELECT 'line_active_twice' AS problem, count(*) AS n
  FROM (SELECT work_order_line_id FROM vinto_txn.assignment WHERE status = 'active' GROUP BY work_order_line_id HAVING count(*) > 1) x HAVING count(*) > 0
UNION ALL
SELECT 'machine_with_two_work_orders', count(*) FROM (
  SELECT a.machine_id FROM vinto_txn.assignment a JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
   WHERE a.status = 'active' GROUP BY a.machine_id HAVING count(DISTINCT v.work_order_id) > 1) y HAVING count(*) > 0;

-- 4. Operators / Quality users with NO active machine-form grant (PR5 prerequisite for turning the multi-machine gate ON, not for migrating): with the gate ON they would see no machine.
SELECT u.id AS user_id, u.display_name, p.code AS profile
  FROM vinto_master."user" u
  JOIN vinto_master.user_profile up ON up.user_id = u.id
  JOIN vinto_master.profile p ON p.id = up.profile_id AND p.active
 WHERE u.active AND p.code IN ('OPERACION', 'CALIDAD')
   AND NOT EXISTS (SELECT 1 FROM vinto_master.user_machine_form_grant g WHERE g.user_id = u.id AND g.revoked_at IS NULL)
 ORDER BY p.code, u.display_name;

-- 5. Active assignments from another shift or operating date (informational: Supervisión must re-activate them before Operación can capture).
SELECT m.code AS machine, a.operating_date, count(*) AS active_assignments
  FROM vinto_txn.assignment a JOIN vinto_master.machine m ON m.id = a.machine_id
 WHERE a.status = 'active' AND a.operating_date <> (now() AT TIME ZONE 'America/La_Paz')::date
 GROUP BY m.code, a.operating_date ORDER BY m.code;
