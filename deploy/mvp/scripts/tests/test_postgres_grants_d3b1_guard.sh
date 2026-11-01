#!/usr/bin/env bash
# VINTO MVP WEB — pruebas aisladas de la guarda MF-13-01D.3B.1 de deploy.sh::phase_postgres_grants.
#
# Qué se demuestra:
#   - Con D.3B.1 NO aplicado, la fase se comporta exactamente como antes: mismos cinco scripts, mismo orden, mismas llamadas.
#   - Con D.3B.1 aplicado (total o parcialmente), o si no se puede determinar, la fase FALLA CERRADA antes de ejecutar
#     CUALQUIER archivo SQL (ningún GRANT), con un mensaje que indica el procedimiento, y sin filtrar la contraseña.
#   - La única consulta que hace la guarda es de solo lectura, y deploy.sh nunca ejecuta 03b ni el rollback.
#
# Igual que test_pg_run_sql_file.sh: ni Docker ni PostgreSQL ni sudo reales. Cada caso lanza un proceso bash NUEVO que sourcea
# lib_common.sh y deploy.sh (con "exit" neutralizado solo durante el source) y sustituye los ayudantes que tocarían la VPS.
# El archivo de registro $LOGDIR/calls.log recibe una línea por cada llamada simulada, en orden.
#
# Uso: bash deploy/mvp/scripts/tests/test_postgres_grants_d3b1_guard.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export SCRIPT_DIR
LOGDIR="$(mktemp -d)"
export LOGDIR
trap 'rm -rf "$LOGDIR"' EXIT

PASS=0
FAILED=0
report() {
  if [ "$2" -eq 0 ]; then
    printf 'PASS  %s\n' "$1"; PASS=$((PASS + 1))
  else
    printf 'FAIL  %s\n' "$1"; FAILED=$((FAILED + 1))
  fi
}

SECRET="pw-sentinel-$$-must-never-appear"
export SECRET

# run_phase: ejecuta phase_postgres_grants en un bash nuevo. Controlan el simulacro:
#   MOCK_D3B1_OUTPUT   salida de la consulta de la guarda (por defecto "0")
#   MOCK_INLINE_EXIT   código de salida de esa consulta (por defecto 0)
#   CONFIRM            "yes" para pasar require_confirm
# Devuelve el código de salida de la fase; stdout/stderr van a $LOGDIR/out.txt y $LOGDIR/err.txt.
run_phase() {
  : > "$LOGDIR/calls.log"
  bash -c '
    set -euo pipefail
    exit() { return 0; }
    source "$SCRIPT_DIR/lib_common.sh"
    source "$SCRIPT_DIR/deploy.sh"
    set +e
    unset -f exit
    APP_DIR="$LOGDIR/app"
    assert_can_read_mvp_private_paths() { :; }
    mvp_test() { return 0; }
    assert_schema_migrated() { echo "MIGRATED_CHECK" >> "$LOGDIR/calls.log"; }
    mvp_env_value() { echo "postgresql://vinto_migrator:${SECRET}@127.0.0.1:5432/vinto_piloto"; }
    password_from_pg_url() { echo "$SECRET"; }
    pg_run_sql_inline() {
      echo "INLINE role=$1 db=$3" >> "$LOGDIR/calls.log"
      printf "%s" "$4" > "$LOGDIR/inline_sql.txt"
      printf "%s\n" "${MOCK_D3B1_OUTPUT-0}"
      return "${MOCK_INLINE_EXIT:-0}"
    }
    pg_run_sql_file() {
      echo "FILE role=$1 db=$3 file=$(basename "$4")" >> "$LOGDIR/calls.log"
    }
    phase_postgres_grants
  ' > "$LOGDIR/out.txt" 2> "$LOGDIR/err.txt"
}

calls() { cat "$LOGDIR/calls.log"; }
file_calls() { grep -c '^FILE ' "$LOGDIR/calls.log" || true; }

# ---- 1. D.3B.1 no aplicado: comportamiento heredado intacto --------------------------------------------------------------------------
test_legacy_state_runs_the_five_scripts_in_the_same_order() {
  local rc=0
  CONFIRM=yes MOCK_D3B1_OUTPUT=0 run_phase || rc=$?
  [ "$rc" -eq 0 ] || return 1
  local expected
  expected="$(printf '%s\n' \
    "MIGRATED_CHECK" \
    "INLINE role=vinto_migrator db=vinto_piloto" \
    "FILE role=vinto_migrator db=vinto_piloto file=02_schema_grants.sql" \
    "FILE role=vinto_migrator db=vinto_piloto file=03_table_grants.sql" \
    "FILE role=vinto_migrator db=vinto_piloto file=04_function_grants.sql" \
    "FILE role=vinto_migrator db=vinto_piloto file=05_no_default_privileges.sql" \
    "FILE role=vinto_migrator db=vinto_piloto file=06_public_and_meta_protection.sql")"
  [ "$(calls)" = "$expected" ] && grep -q "02..06 aplicados" "$LOGDIR/out.txt"
}

test_legacy_state_never_runs_03b_or_the_rollback() {
  CONFIRM=yes MOCK_D3B1_OUTPUT=0 run_phase || return 1
  ! calls | grep -qiE '03b|rollback|d3b1'
}

# ---- 2. D.3B.1 aplicado o indeterminado: falla cerrado ANTES de cualquier GRANT ---------------------------------------------------------
assert_closed_failure() {
  local rc=0
  run_phase || rc=$?
  [ "$rc" -eq 1 ] || return 1
  [ "$(file_calls)" = "0" ] || return 1            # ningún archivo SQL (ningún GRANT) se ejecutó
  [ "$(calls | head -n1)" = "MIGRATED_CHECK" ]      # sí se respetó el orden: primero el esquema migrado, luego la guarda
  grep -q "FALLA CERRADA" "$LOGDIR/err.txt"
  ! grep -q "$SECRET" "$LOGDIR/err.txt" "$LOGDIR/out.txt"   # la contraseña nunca se imprime
}

test_fully_applied_blocks_and_names_the_procedure() {
  CONFIRM=yes MOCK_D3B1_OUTPUT=3 assert_closed_failure || return 1
  grep -q "3 de 3 tablas" "$LOGDIR/err.txt" && grep -q "03b_d3b1_restrict_catalog_writes.sql" "$LOGDIR/err.txt" \
    && grep -q "ROLLBACK_D3B1.sql" "$LOGDIR/err.txt" && grep -q "07_verification_queries.sql" "$LOGDIR/err.txt" \
    && grep -q "NO aplica D.3B.1 por su cuenta" "$LOGDIR/err.txt"
}

test_partially_applied_also_blocks() {
  CONFIRM=yes MOCK_D3B1_OUTPUT=1 assert_closed_failure
}

test_undeterminable_state_blocks_when_the_query_fails() {
  CONFIRM=yes MOCK_D3B1_OUTPUT="" MOCK_INLINE_EXIT=1 assert_closed_failure && grep -q "no se pudo determinar" "$LOGDIR/err.txt"
}

test_unexpected_output_blocks() {
  CONFIRM=yes MOCK_D3B1_OUTPUT="ERROR: algo raro" assert_closed_failure && grep -q "respuesta inesperada" "$LOGDIR/err.txt"
}

test_empty_output_blocks() {
  CONFIRM=yes MOCK_D3B1_OUTPUT="" assert_closed_failure
}

# ---- 3. orden y alcance ---------------------------------------------------------------------------------------------------------------------
test_confirm_is_still_required_first_and_nothing_runs_without_it() {
  local rc=0
  run_phase || rc=$?   # sin CONFIRM=yes
  [ "$rc" -eq 1 ] && [ ! -s "$LOGDIR/calls.log" ]
}

test_the_guard_query_is_read_only_and_scoped_to_vinto_app_and_the_three_tables() {
  CONFIRM=yes MOCK_D3B1_OUTPUT=0 run_phase || return 1
  local sql; sql="$(cat "$LOGDIR/inline_sql.txt")"
  printf '%s' "$sql" | grep -qE '^SELECT ' && ! printf '%s' "$sql" | grep -qiE 'GRANT|REVOKE|INSERT INTO|UPDATE vinto|DELETE|DROP|ALTER|CREATE' \
    && printf '%s' "$sql" | grep -q "vinto_master.profile" && printf '%s' "$sql" | grep -q "vinto_master.machine" && printf '%s' "$sql" | grep -q "vinto_master.sector" \
    && printf '%s' "$sql" | grep -q "'vinto_app'" && ! printf '%s' "$sql" | grep -q "$SECRET"
}

test_the_guard_is_wired_before_the_grant_loop_and_the_script_list_is_unchanged() {
  local body
  body="$(awk '/^phase_postgres_grants\(\)/,/^}/' "$SCRIPT_DIR/deploy.sh")"
  local guard_line loop_line
  guard_line="$(printf '%s\n' "$body" | grep -n 'assert_d3b1_not_silently_reverted_by_03' | head -n1 | cut -d: -f1)"
  loop_line="$(printf '%s\n' "$body" | grep -n 'for step in' | head -n1 | cut -d: -f1)"
  [ -n "$guard_line" ] && [ -n "$loop_line" ] && [ "$guard_line" -lt "$loop_line" ] \
    && printf '%s\n' "$body" | grep -q 'for step in 02_schema_grants 03_table_grants 04_function_grants 05_no_default_privileges 06_public_and_meta_protection; do'
}

test_deploy_sh_never_executes_03b_the_rollback_or_the_proposals() {
  # solo líneas de código (no comentarios ni el texto del mensaje de ayuda): ningún pg_run_sql_file apunta a 03b / rollback / proposals
  ! grep -vE '^\s*#' "$SCRIPT_DIR/deploy.sh" | grep -E 'pg_run_sql_(file|inline)' | grep -qiE '03b|rollback|proposals|ROLLBACK_D3B1'
}

# ---- ejecución ------------------------------------------------------------------------------------------------------------------------------
run_case() {
  local rc=0
  "$2" || rc=$?
  report "$1" "$rc"
}

run_case "1  D.3B.1 no aplicado: mismos 5 scripts, mismo orden (02,03,04,05,06) y mismo mensaje final"          test_legacy_state_runs_the_five_scripts_in_the_same_order
run_case "2  D.3B.1 no aplicado: jamás se ejecuta 03b ni el rollback"                                           test_legacy_state_never_runs_03b_or_the_rollback
run_case "3  D.3B.1 aplicado en las 3 tablas: falla cerrado, 0 archivos SQL ejecutados, indica el procedimiento" test_fully_applied_blocks_and_names_the_procedure
run_case "4  D.3B.1 aplicado parcialmente: también falla cerrado"                                               test_partially_applied_also_blocks
run_case "5  la consulta de la guarda falla: falla cerrado (nunca se asume 'no aplicado')"                      test_undeterminable_state_blocks_when_the_query_fails
run_case "6  respuesta inesperada de la guarda: falla cerrado"                                                  test_unexpected_output_blocks
run_case "7  respuesta vacía de la guarda: falla cerrado"                                                       test_empty_output_blocks
run_case "8  sin CONFIRM=yes no se ejecuta nada (ni siquiera la guarda)"                                        test_confirm_is_still_required_first_and_nothing_runs_without_it
run_case "9  la consulta de la guarda es de solo lectura, acotada a vinto_app y 3 tablas, sin secretos"         test_the_guard_query_is_read_only_and_scoped_to_vinto_app_and_the_three_tables
run_case "10 la guarda está cableada ANTES del bucle de GRANT y la lista de scripts no cambió"                  test_the_guard_is_wired_before_the_grant_loop_and_the_script_list_is_unchanged
run_case "11 deploy.sh nunca ejecuta 03b, el rollback ni las propuestas"                                        test_deploy_sh_never_executes_03b_the_rollback_or_the_proposals

printf '\n%d PASS, %d FAIL\n' "$PASS" "$FAILED"
[ "$FAILED" -eq 0 ]
