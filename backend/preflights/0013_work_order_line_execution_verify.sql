-- E1-02 POST-MIGRATION verification (read-only). Expected: index unique/partial,
-- 4 enabled triggers, no row backfill, no DELETE privilege for vinto_app.
SELECT idx.indexname, idx.indexdef FROM pg_indexes idx
WHERE idx.schemaname = 'vinto_txn' AND idx.tablename = 'work_order_line_execution'
ORDER BY idx.indexname;
SELECT tgname,tgenabled FROM pg_trigger
WHERE tgrelid='vinto_txn.work_order_line_execution'::regclass AND NOT tgisinternal
ORDER BY tgname;
SELECT count(*) AS execution_rows_after_migration FROM vinto_txn.work_order_line_execution;
SELECT rolname,
       has_table_privilege(rolname,'vinto_txn.work_order_line_execution','SELECT') AS can_read,
       has_table_privilege(rolname,'vinto_txn.work_order_line_execution','INSERT') AS can_insert,
       has_table_privilege(rolname,'vinto_txn.work_order_line_execution','UPDATE') AS can_update,
       has_table_privilege(rolname,'vinto_txn.work_order_line_execution','DELETE') AS can_delete
FROM pg_roles WHERE rolname = 'vinto_app';
