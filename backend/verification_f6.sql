-- Read-only verification of central F6 captures (VINTO-P1-06). Run inside psql connected to vinto. Changes nothing, prints no secrets.
-- 1) Latest F6 captures with status/revision, detail count, OT/line/assignment and the operator.
SELECT c.captured_at, c.status, c.revision, m.code AS machine, sh.code AS shift, c.operating_date,
       wo.number AS work_order, wl.line_code, wl.pv_reference, a.status AS assignment_status,
       (SELECT count(*) FROM vinto_txn.capture_detail d WHERE d.capture_id = c.id) AS details,
       u.display_name AS operator, c.id AS capture_id
FROM vinto_txn.capture c
JOIN vinto_config.form_version fv ON fv.id = c.form_version_id
JOIN vinto_config.form f ON f.id = fv.form_id AND f.code = 'VINTO-P1-06'
JOIN vinto_master.machine m ON m.id = c.machine_id
JOIN vinto_config.shift_schedule ss ON ss.id = c.shift_schedule_id
JOIN vinto_config.shift sh ON sh.id = ss.shift_id
JOIN vinto_txn.assignment a ON a.id = c.assignment_id
JOIN vinto_txn.work_order_line wl ON wl.id = a.work_order_line_id
JOIN vinto_txn.work_order_version wv ON wv.id = wl.work_order_version_id
JOIN vinto_txn.work_order wo ON wo.id = wv.work_order_id
LEFT JOIN vinto_master."user" u ON u.id = c.created_by
ORDER BY c.captured_at DESC LIMIT 20;

-- 2) Typed values of the latest F6 captures (one value column per row).
SELECT d.capture_id, fd.key, d.value_type,
       coalesce(d.value_text, d.value_decimal::text, d.value_integer::text, d.value_boolean::text, d.value_date::text, d.value_time::text) AS value
FROM vinto_txn.capture_detail d
JOIN vinto_config.field_definition fd ON fd.id = d.field_definition_id
WHERE d.capture_id IN (SELECT c.id FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id = c.form_version_id
                       JOIN vinto_config.form f ON f.id = fv.form_id AND f.code = 'VINTO-P1-06' ORDER BY c.captured_at DESC LIMIT 5)
ORDER BY d.capture_id, fd.display_order;

-- 3) Audit trail of those captures (actor, action, reason).
SELECT e.occurred_at, e.entity_table, e.action, e.actor_id, e.reason
FROM vinto_audit.audit_event e
WHERE e.entity_table IN ('capture', 'capture_detail', 'device')
ORDER BY e.id DESC LIMIT 30;

-- 4) Totals (the "Registros centrales" counter counts the capture rows of the front's sector).
SELECT (SELECT count(*) FROM vinto_txn.capture) AS captures, (SELECT count(*) FROM vinto_txn.capture_detail) AS details,
       (SELECT count(*) FROM vinto_master.device) AS devices;
