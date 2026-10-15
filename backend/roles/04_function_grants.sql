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
-- PG54-FINAL: CREATE FUNCTION concede EXECUTE a PUBLIC por defecto — y, a diferencia de las tablas,
-- NINGÚN "ALTER DEFAULT PRIVILEGES ... REVOKE ... ON FUNCTIONS FROM PUBLIC" lo evita para objetos
-- futuros: es una limitación de PostgreSQL documentada desde hace años (PostgreSQL BUG #8685,
-- "alter default privileges cannot revoke default execute privilege on functions", y el hilo más
-- reciente "Removing the default grant of EXECUTE on functions/procedures to PUBLIC" en pgsql-hackers),
-- confirmada aquí de forma empírica: tras "ALTER DEFAULT PRIVILEGES ... REVOKE EXECUTE ON FUNCTIONS
-- FROM PUBLIC", una función nueva seguía teniendo proacl NULL y PUBLIC seguía con EXECUTE=true. La
-- única forma fiable es revocarlo del OBJETO YA CREADO, que sí funciona siempre (verificado). Por eso
-- toda migración futura que cree una función invocable directamente DEBE incluir, en el mismo archivo,
-- su propio "REVOKE EXECUTE ON FUNCTION ... FROM PUBLIC;" (ver backend/migrations/README.md) — no basta
-- con no concederlo explícitamente a nadie, como sí basta para una tabla nueva.

\set ON_ERROR_STOP on

-- management_start_year ya existe desde 0004_bobbin_production.sql (no se reescribe esa migración:
-- esto es un GRANT/REVOKE de infraestructura, no un cambio de esquema). PUBLIC tenía EXECUTE por el
-- defecto de PostgreSQL desde que se creó; se revoca aquí explícitamente, de forma fiable, sobre el
-- objeto ya existente.
REVOKE EXECUTE ON FUNCTION vinto_txn.management_start_year(date) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION vinto_txn.management_start_year(date) TO vinto_app;

-- vinto_reference no llama a esta función (no procesa capturas F3): sin GRANT (y, tras el REVOKE de
-- arriba, tampoco la hereda de PUBLIC).
