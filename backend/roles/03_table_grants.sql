-- CLOUD-01B-2: privilegios DML por tabla. Ejecuta este archivo vinto_migrator (propietario).
--
-- Matriz exacta derivada de CLOUD-01B-2 / CLOUD-01B-2A (evidencia: grep de backend/app por tabla,
-- citada en los comentarios). Ningún rol de aplicación recibe DELETE salvo donde el código realmente
-- lo usa (una sola tabla en todo el backend: vinto_master.user_sector). Ningún rol de aplicación
-- recibe CREATE/ALTER/DROP/TRUNCATE sobre ninguna tabla (principio 1, 5, 6).

\set ON_ERROR_STOP on

-- ===== vinto_app =====================================================================================

-- vinto_master: SELECT+INSERT+UPDATE en las 13 tablas de identidad/catálogo que la API usa (todas
-- salvo user_sector, que tiene su propia regla abajo). Evidencia: backend/app/{admin,assignments,auth,
-- bobbins,capture_service,quality/*,work_orders,seed/reference}.py.
GRANT SELECT, INSERT, UPDATE ON
  vinto_master."user", vinto_master.profile, vinto_master.user_profile, vinto_master.sector,
  vinto_master.machine, vinto_master.machine_alias, vinto_master.device, vinto_master.unit,
  vinto_master.material_class, vinto_master.article, vinto_master.article_version,
  vinto_master.article_machine, vinto_master.article_version_spec
TO vinto_app;
-- MF-13-01D.3B.1: este GRANT sigue siendo la línea base amplia. Para profile, machine y sector se estrecha DESPUÉS con 03b_d3b1_restrict_catalog_writes.sql
-- (procedimiento de aprovisionamiento = 03 + 03b, siempre juntos y en ese orden: re-ejecutar 03 sola restaura INSERT/UPDATE de tabla).

-- vinto_master.user_sector: única tabla con DELETE real (backend/app/auth/grants.py:57). Nunca UPDATE
-- (el modelo es alta/baja de filas, no edición).
GRANT SELECT, INSERT, DELETE ON vinto_master.user_sector TO vinto_app;

-- vinto_config: solo SELECT. La única escritura sobre este esquema es el importador de referencias
-- (vinto_reference, ver más abajo), nunca el tráfico HTTP normal.
GRANT SELECT ON
  vinto_config.shift, vinto_config.shift_schedule, vinto_config.workflow_definition, vinto_config.form,
  vinto_config.form_version, vinto_config.form_version_machine, vinto_config.field_group,
  vinto_config.field_definition, vinto_config.field_option, vinto_config.field_option_dependency,
  vinto_config.workflow_step, vinto_config.recipe_version, vinto_config.recipe_component,
  vinto_config.report_definition
TO vinto_app;

-- vinto_txn: SELECT+INSERT+UPDATE en las 11 tablas transaccionales. Nunca DELETE: además de no haber
-- ningún "DELETE FROM vinto_txn.*" en backend/app, varias de estas tablas ya lo bloquean por trigger
-- (prevent_capture_delete, reject_mutation) — pero el GRANT tampoco lo concede, por defensa en
-- profundidad y para que la denegación ocurra por permiso (42501) y no solo por trigger (23514).
GRANT SELECT, INSERT, UPDATE ON
  vinto_txn.work_order, vinto_txn.work_order_version, vinto_txn.work_order_line, vinto_txn.assignment,
  vinto_txn.capture, vinto_txn.capture_group_row, vinto_txn.capture_detail, vinto_txn.bobbin,
  vinto_txn.bobbin_relation, vinto_txn.quality_release, vinto_txn.bobbin_sequence
TO vinto_app;

-- vinto_audit.audit_event: INSERT únicamente. Necesario aunque backend/app nunca lo referencie
-- directamente: lo inserta vinto_audit.record_change(), un trigger SECURITY INVOKER (se ejecuta con
-- los privilegios del rol que dispara el INSERT/UPDATE/DELETE auditado, nunca con privilegios propios).
-- Nunca UPDATE/DELETE/TRUNCATE: el trigger immutable_event los rechaza en cualquier caso (23514), y aquí
-- tampoco se conceden (42501) para que la denegación sea doble, no solo por trigger.
GRANT INSERT ON vinto_audit.audit_event TO vinto_app;

-- vinto_auth: credential/session necesitan UPDATE (bloqueo de intentos, revocación de sesión vía
-- revoked_at); auth_event es append-only (solo INSERT). Ninguna de las tres admite DELETE.
GRANT SELECT, INSERT, UPDATE ON vinto_auth.credential, vinto_auth.session TO vinto_app;
GRANT INSERT ON vinto_auth.auth_event TO vinto_app;

-- vinto_meta: SIN GRANT para vinto_app. No ejecutar nada aquí a propósito (ver 02_schema_grants.sql).

-- ===== vinto_reference ===============================================================================

-- vinto_master: solo las tablas que app/seed/reference.py escribe (backend/app/seed/reference.py:142-356).
-- El resto de vinto_master (user, user_profile, device, machine_alias) es gestión de usuarios/dispositivos,
-- ajena al importador: no recibe ningún privilegio aquí.
GRANT SELECT, INSERT, UPDATE ON
  vinto_master.unit, vinto_master.material_class, vinto_master.sector, vinto_master.machine,
  vinto_master.profile, vinto_master.article, vinto_master.article_version,
  vinto_master.article_version_spec, vinto_master.article_machine
TO vinto_reference;

-- vinto_config: las 9 tablas que el importador escribe (backend/app/seed/reference.py:234-356).
-- G.12-C5-DEPLOY: field_group faltaba aquí -- reference.py ya la escribe desde G.12-C4-FINAL25
-- (grupos repetibles de P1-11/P1-29), pero este archivo nunca se actualizó; el import-reference
-- real contra vinto_piloto falló con InsufficientPrivilege (42501) hasta corregirlo.
GRANT SELECT, INSERT, UPDATE ON
  vinto_config.shift, vinto_config.shift_schedule, vinto_config.workflow_definition, vinto_config.form,
  vinto_config.form_version, vinto_config.form_version_machine, vinto_config.field_group,
  vinto_config.field_definition, vinto_config.field_option
TO vinto_reference;

-- vinto_audit: import_batch necesita UPDATE (cierre de batch, backend/app/seed/reference.py:376-447);
-- import_record solo INSERT (append-only); audit_event solo INSERT (misma razón que para vinto_app:
-- record_change() corre con los privilegios de quien dispara el trigger).
GRANT SELECT, INSERT, UPDATE ON vinto_audit.import_batch TO vinto_reference;
GRANT INSERT ON vinto_audit.import_record, vinto_audit.audit_event TO vinto_reference;

-- vinto_txn, vinto_auth, vinto_meta: SIN GRANT para vinto_reference (no tiene USAGE sobre esos
-- esquemas desde 02_schema_grants.sql; esto es además una segunda barrera por si USAGE se concediera
-- por error en el futuro).
