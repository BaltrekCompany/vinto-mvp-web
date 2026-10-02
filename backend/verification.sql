-- Read-only verification. Run inside psql connected to vinto.
SELECT version, filename, checksum, applied_at
FROM vinto_meta.schema_migration ORDER BY version;

SELECT table_schema, count(*) AS tables
FROM information_schema.tables
WHERE table_schema IN ('vinto_master','vinto_config','vinto_txn','vinto_audit','vinto_meta')
  AND table_type = 'BASE TABLE'
GROUP BY table_schema ORDER BY table_schema;

SELECT table_schema, table_name
FROM information_schema.tables
WHERE table_schema IN ('vinto_master','vinto_config','vinto_txn','vinto_audit')
  AND table_type = 'BASE TABLE'
ORDER BY table_schema, table_name;

SELECT n.nspname AS schema, c.relname AS table_name, con.contype AS type,
       con.conname AS constraint_name, pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
JOIN pg_class c ON c.oid = con.conrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname IN ('vinto_master','vinto_config','vinto_txn','vinto_audit')
ORDER BY 1,2,3,4;

SELECT schemaname, tablename, indexname, indexdef
FROM pg_indexes
WHERE schemaname IN ('vinto_master','vinto_config','vinto_txn','vinto_audit')
ORDER BY 1,2,3;

SELECT event_object_schema, event_object_table, trigger_name
FROM information_schema.triggers
WHERE event_object_schema IN ('vinto_master','vinto_config','vinto_txn','vinto_audit')
ORDER BY 1,2,3;

SELECT 'capturas' AS entity, count(*) AS rows FROM vinto_txn.capture
UNION ALL SELECT 'usuarios', count(*) FROM vinto_master."user"
UNION ALL SELECT 'articulos', count(*) FROM vinto_master.article
UNION ALL SELECT 'auditoria', count(*) FROM vinto_audit.audit_event;
