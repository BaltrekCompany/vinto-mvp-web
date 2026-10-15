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
-- guard_session_update) se ejecutan EXCLUSIVAMENTE como cuerpo de un TRIGGER. PostgreSQL dispara una
-- función de trigger sin exigir EXECUTE al rol que ejecuta el INSERT/UPDATE/DELETE que lo activa; ese
-- rol solo necesita los privilegios de tabla que el cuerpo de la función usa (ya cubiertos en
-- 03_table_grants.sql). NO se concede EXECUTE sobre ninguna de ellas: no es necesario, y concederlo
-- sin necesidad sería la misma "concesión indiscriminada" que OBS-PG-01 pidió evitar para tablas.

\set ON_ERROR_STOP on

GRANT EXECUTE ON FUNCTION vinto_txn.management_start_year(date) TO vinto_app;

-- vinto_reference no llama a esta función (no procesa capturas F3): sin GRANT.
