-- OFF-04.5B-03 PROPOSED post-apply verification (READ ONLY: SELECT only). Every row must have ok = true. Run as the schema owner or a superuser.
SELECT 'schema_exists' AS check_name, EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = 'vinto_offline') AS ok
UNION ALL SELECT 'tables_exist', (SELECT count(*) FROM pg_tables WHERE schemaname = 'vinto_offline' AND tablename IN ('capture_receipt', 'capture_event')) = 2
UNION ALL SELECT 'owner_is_not_app_role', NOT pg_has_role('vinto_app', (SELECT nspowner FROM pg_namespace WHERE nspname = 'vinto_offline'), 'MEMBER')
UNION ALL SELECT 'app_usage_only_on_schema', has_schema_privilege('vinto_app', 'vinto_offline', 'USAGE') AND NOT has_schema_privilege('vinto_app', 'vinto_offline', 'CREATE')
UNION ALL SELECT 'app_receipt_select_insert_update',
    has_table_privilege('vinto_app', 'vinto_offline.capture_receipt', 'SELECT') AND has_table_privilege('vinto_app', 'vinto_offline.capture_receipt', 'INSERT')
    AND has_table_privilege('vinto_app', 'vinto_offline.capture_receipt', 'UPDATE')
UNION ALL SELECT 'app_event_select_insert_only',
    has_table_privilege('vinto_app', 'vinto_offline.capture_event', 'SELECT') AND has_table_privilege('vinto_app', 'vinto_offline.capture_event', 'INSERT')
    AND NOT has_table_privilege('vinto_app', 'vinto_offline.capture_event', 'UPDATE')
UNION ALL SELECT 'app_no_delete_truncate_references_trigger', NOT (
    has_table_privilege('vinto_app', 'vinto_offline.capture_receipt', 'DELETE') OR has_table_privilege('vinto_app', 'vinto_offline.capture_receipt', 'TRUNCATE')
    OR has_table_privilege('vinto_app', 'vinto_offline.capture_receipt', 'REFERENCES') OR has_table_privilege('vinto_app', 'vinto_offline.capture_receipt', 'TRIGGER')
    OR has_table_privilege('vinto_app', 'vinto_offline.capture_event', 'DELETE') OR has_table_privilege('vinto_app', 'vinto_offline.capture_event', 'TRUNCATE')
    OR has_table_privilege('vinto_app', 'vinto_offline.capture_event', 'REFERENCES') OR has_table_privilege('vinto_app', 'vinto_offline.capture_event', 'TRIGGER'))
UNION ALL SELECT 'public_has_nothing', NOT (has_schema_privilege('public', 'vinto_offline', 'USAGE') OR has_table_privilege('public', 'vinto_offline.capture_receipt', 'SELECT')
    OR has_table_privilege('public', 'vinto_offline.capture_event', 'SELECT'))
UNION ALL SELECT 'guard_triggers_present', (SELECT count(*) FROM pg_trigger WHERE tgname IN ('capture_receipt_guard', 'capture_event_guard') AND NOT tgisinternal) = 2;
