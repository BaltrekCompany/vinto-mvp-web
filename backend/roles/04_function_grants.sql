-- CLOUD-01B-2: EXECUTE sobre funciones. Ejecuta este archivo vinto_migrator (propietario).
--
-- De las ~19 funciones de 0001-0005, UNA SOLA es invocada directamente por backend/app con SELECT:
-- vinto_txn.management_start_year(date), en backend/app/bobbins/service.py:174
-- ("SELECT vinto_txn.management_start_year(%s)"). Esa es la única que necesita EXECUTE explícito.
--
-- Las demás (touch_row, record_change, reject_mutation, guard_published_version, guard_form_child,
-- guard_recipe_child, guard_order_version, guard_order_line, validate_assignment, validate_capture,
-- guard_capture_child, validate_detail_group, validate_completed_capture, guard_bobbin_sequence,
-- validate_bobbin, require_quality_release, guard_capture_bobbin, guard_credential_identity,
-- guard_session_update) se ejecutan EXCLUSIVAMENTE como cuerpo de un TRIGGER y devuelven el
-- pseudotipo "trigger": PostgreSQL las rechaza si se llaman directamente ("ERROR: trigger functions
-- can only be called as triggers"), sin importar quién las invoque ni qué EXECUTE tenga — verificado
-- empíricamente. Por eso no necesitan ningún GRANT/REVOKE de EXECUTE aquí: el riesgo que correspondería
-- cubrir no existe para ellas. management_start_year() es distinta: devuelve integer y SÍ puede
-- invocarse directamente con SELECT, así que es la única donde el privilegio por defecto de PostgreSQL
-- importa de verdad.
--
-- PG54-FINAL (verificación final de ChatGPT sobre PR #54): CREATE FUNCTION concede EXECUTE a PUBLIC
-- por defecto. "ALTER DEFAULT PRIVILEGES ... IN SCHEMA x REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC" NO lo
-- evita (verificado: no registra nada en pg_default_acl para un REVOKE con IN SCHEMA), pero
-- "ALTER DEFAULT PRIVILEGES FOR ROLE vinto_migrator REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC" (SIN
-- "IN SCHEMA", alcance global por rol creador — ver https://www.postgresql.org/docs/17/
-- sql-alterdefaultprivileges.html) SÍ funciona y ya se aplica en 05_no_default_privileges.sql para
-- TODA función que vinto_migrator cree desde ahora en cualquier esquema.
--
-- Eso NO protege retroactivamente a management_start_year, creada por la migración 0004 ANTES de que
-- existiera ese default (verificado: proacl seguía NULL y PUBLIC con EXECUTE=true después de aplicar
-- el default global). Por eso el REVOKE explícito de abajo, sobre el objeto ya existente, sigue siendo
-- necesario — es la única vía fiable para un objeto creado antes del default, y además funciona siempre
-- (a diferencia del REVOKE con IN SCHEMA, que no registra nada).

\set ON_ERROR_STOP on

-- management_start_year ya existe desde 0004_bobbin_production.sql (no se reescribe esa migración:
-- esto es un GRANT/REVOKE de infraestructura, no un cambio de esquema). PUBLIC tenía EXECUTE por el
-- defecto de PostgreSQL desde que se creó; se revoca aquí explícitamente, de forma fiable, sobre el
-- objeto ya existente.
REVOKE EXECUTE ON FUNCTION vinto_txn.management_start_year(date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION vinto_txn.management_start_year(date) TO vinto_app;

-- vinto_reference no llama a esta función (no procesa capturas F3): sin GRANT (y, tras el REVOKE de
-- arriba, tampoco la hereda de PUBLIC).
