#!/usr/bin/env bash
# VINTO MVP WEB — pruebas aisladas de la guarda MF-13-01D.3B.1 / D.3B.4 de deploy.sh::phase_postgres_grants.
#
# Qué se demuestra:
#   - Con D.3B.1 y D.3B.4 NO aplicados, la fase se comporta exactamente como antes: mismos cinco scripts, mismo orden, mismas llamadas.
#   - Con D.3B.1 o D.3B.4 aplicados (total o parcialmente), o si no se puede determinar, la fase FALLA CERRADO antes de ejecutar
#     CUALQUIER archivo SQL (ningún GRANT), con un mensaje que indica el procedimiento, y sin filtrar la contraseña.
#   - La única consulta que hace la guarda es de solo lectura, y deploy.sh nunca ejecuta 03b, 03d ni los rollbacks.
# (La semántica de la consulta contra PostgreSQL REAL —incluido el primer aprovisionamiento, donde vinto_app aún no tiene ningún
#  privilegio— se prueba en backend/tests/test_d3b1_privilege_hardening.py y test_d3b3_two_role_gate.py.)
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
#   MOCK_D3B1_OUTPUT   salida de la consulta de la guarda: "<d3b1> <d3b4>" (por defecto "0 0")
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
      printf "%s\n" "${MOCK_D3B1_OUTPUT-0 0}"
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

# ---- 1. nada aplicado: comportamiento heredado intacto ---------------------------------------------------------------------------------
test_legacy_state_runs_the_five_scripts_in_the_same_order() {
  local rc=0
  CONFIRM=yes MOCK_D3B1_OUTPUT="0 0" run_phase || rc=$?
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

test_legacy_state_never_runs_the_hardening_scripts_or_the_rollbacks() {
  CONFIRM=yes MOCK_D3B1_OUTPUT="0 0" run_phase || return 1
  ! calls | grep -qiE '03b|03c|03d|rollback|d3b1|d3b2|d3b4'
}

# ---- 2. alguna fase aplicada o indeterminado: falla cerrado ANTES de cualquier GRANT --------------------------------------------------
assert_closed_failure() {
  local rc=0
  run_phase || rc=$?
  [ "$rc" -eq 1 ] || return 1
  [ "$(file_calls)" = "0" ] || return 1            # ningún archivo SQL (ningún GRANT) se ejecutó
  [ "$(calls | head -n1)" = "MIGRATED_CHECK" ]      # sí se respetó el orden: primero el esquema migrado, luego la guarda
  grep -q "FALLA CERRADA" "$LOGDIR/err.txt"
  ! grep -q "$SECRET" "$LOGDIR/err.txt" "$LOGDIR/out.txt"   # la contraseña nunca se imprime
}

test_d3b1_applied_blocks_and_names_the_procedure() {
  CONFIRM=yes MOCK_D3B1_OUTPUT="3 0" assert_closed_failure || return 1
  grep -q "D.3B.1: 3 de 3 tablas" "$LOGDIR/err.txt" && grep -q "03b_d3b1_restrict_catalog_writes.sql" "$LOGDIR/err.txt" \
    && grep -q "ROLLBACK_D3B1.sql" "$LOGDIR/err.txt" && grep -q "07_verification_queries.sql" "$LOGDIR/err.txt" \
    && grep -q "NO aplica ni revierte ninguna fase por su cuenta" "$LOGDIR/err.txt"
}

test_d3b4_applied_blocks_and_names_the_cut_procedure() {
  CONFIRM=yes MOCK_D3B1_OUTPUT="0 6" assert_closed_failure || return 1
  grep -q "D.3B.4: 6 de 6 tablas" "$LOGDIR/err.txt" && grep -q "03d_d3b4_cut_identity_dml.sql" "$LOGDIR/err.txt" \
    && grep -q "ROLLBACK_D3B4.sql" "$LOGDIR/err.txt" && grep -q "ANTES de quitar IDENTITY_DATABASE_URL" "$LOGDIR/err.txt"
}

test_both_phases_applied_block() {
  CONFIRM=yes MOCK_D3B1_OUTPUT="3 6" assert_closed_failure && grep -q "D.3B.1: 3 de 3" "$LOGDIR/err.txt" && grep -q "D.3B.4: 6 de 6" "$LOGDIR/err.txt"
}

test_partially_applied_also_blocks() {
  CONFIRM=yes MOCK_D3B1_OUTPUT="1 0" assert_closed_failure && CONFIRM=yes MOCK_D3B1_OUTPUT="0 1" assert_closed_failure
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

test_the_previous_single_number_format_is_not_trusted() {
  CONFIRM=yes MOCK_D3B1_OUTPUT="0" assert_closed_failure && grep -q "respuesta inesperada" "$LOGDIR/err.txt"
}

# ---- 3. orden y alcance ---------------------------------------------------------------------------------------------------------------------
test_confirm_is_still_required_first_and_nothing_runs_without_it() {
  local rc=0
  run_phase || rc=$?   # sin CONFIRM=yes
  [ "$rc" -eq 1 ] && [ ! -s "$LOGDIR/calls.log" ]
}

test_the_guard_query_is_read_only_and_scoped_to_vinto_app_and_the_known_tables() {
  CONFIRM=yes MOCK_D3B1_OUTPUT="0 0" run_phase || return 1
  local sql; sql="$(cat "$LOGDIR/inline_sql.txt")"
  printf '%s' "$sql" | grep -qE '^SELECT ' && ! printf '%s' "$sql" | grep -qiE 'GRANT|REVOKE|INSERT INTO|UPDATE vinto|DELETE|DROP|ALTER|CREATE' \
    && printf '%s' "$sql" | grep -q "vinto_master.profile" && printf '%s' "$sql" | grep -q "vinto_master.machine" && printf '%s' "$sql" | grep -q "vinto_master.sector" \
    && printf '%s' "$sql" | grep -q "vinto_auth.session" && printf '%s' "$sql" | grep -q "vinto_auth.credential" && printf '%s' "$sql" | grep -q "'vinto_app'" \
    && printf '%s' "$sql" | grep -q "'SELECT'" && ! printf '%s' "$sql" | grep -q "$SECRET"
}

test_the_guard_is_wired_before_the_grant_loop_and_the_script_list_is_unchanged() {
  local body
  body="$(awk '/^phase_postgres_grants\(\)/,/^}/' "$SCRIPT_DIR/deploy.sh")"
  local guard_line loop_line
  guard_line="$(printf '%s\n' "$body" | grep -n 'assert_identity_hardening_not_reverted_by_03' | head -n1 | cut -d: -f1)"
  loop_line="$(printf '%s\n' "$body" | grep -n 'for step in' | head -n1 | cut -d: -f1)"
  [ -n "$guard_line" ] && [ -n "$loop_line" ] && [ "$guard_line" -lt "$loop_line" ] \
    && printf '%s\n' "$body" | grep -q 'for step in 02_schema_grants 03_table_grants 04_function_grants 05_no_default_privileges 06_public_and_meta_protection; do'
}

test_deploy_sh_never_executes_the_hardening_scripts_the_rollbacks_or_the_proposals() {
  # solo líneas de código (no comentarios ni el texto del mensaje de ayuda): ningún pg_run_sql_* apunta a 03b / 03c / 03d / rollback / proposals
  ! grep -vE '^\s*#' "$SCRIPT_DIR/deploy.sh" | grep -E 'pg_run_sql_(file|inline)|for step in' | grep -qiE '03b|03c|03d|00c|rollback|proposals|ROLLBACK_D3B'
}

# ---- ejecución ------------------------------------------------------------------------------------------------------------------------------
run_case() {
  local rc=0
  "$2" || rc=$?
  report "$1" "$rc"
}

run_case "1  nada aplicado: mismos 5 scripts, mismo orden (02,03,04,05,06) y mismo mensaje final"                  test_legacy_state_runs_the_five_scripts_in_the_same_order
run_case "2  nada aplicado: jamás se ejecuta 03b/03c/03d ni un rollback"                                         test_legacy_state_never_runs_the_hardening_scripts_or_the_rollbacks
run_case "3  D.3B.1 aplicado en las 3 tablas: falla cerrado, 0 archivos SQL ejecutados, indica el procedimiento" test_d3b1_applied_blocks_and_names_the_procedure
run_case "4  D.3B.4 aplicado: falla cerrado, 0 SQL, indica 03d y ROLLBACK_D3B4 antes de quitar la variable"       test_d3b4_applied_blocks_and_names_the_cut_procedure
run_case "5  ambas fases aplicadas: el mensaje nombra las dos"                                                   test_both_phases_applied_block
run_case "6  aplicado parcialmente (1 tabla de D.3B.1 o de D.3B.4): también falla cerrado"                       test_partially_applied_also_blocks
run_case "7  la consulta de la guarda falla: falla cerrado (nunca se asume 'no aplicado')"                       test_undeterminable_state_blocks_when_the_query_fails
run_case "8  respuesta inesperada de la guarda: falla cerrado"                                                   test_unexpected_output_blocks
run_case "9  respuesta vacía de la guarda: falla cerrado"                                                        test_empty_output_blocks
run_case "10 el formato antiguo de un solo número no se acepta"                                                  test_the_previous_single_number_format_is_not_trusted
run_case "11 sin CONFIRM=yes no se ejecuta nada (ni siquiera la guarda)"                                         test_confirm_is_still_required_first_and_nothing_runs_without_it
run_case "12 la consulta de la guarda es de solo lectura, acotada a vinto_app y a las tablas conocidas"          test_the_guard_query_is_read_only_and_scoped_to_vinto_app_and_the_known_tables
run_case "13 la guarda está cableada ANTES del bucle de GRANT y la lista de scripts no cambió"                   test_the_guard_is_wired_before_the_grant_loop_and_the_script_list_is_unchanged
run_case "14 deploy.sh nunca ejecuta 03b/03c/03d, 00c, los rollbacks ni las propuestas"                          test_deploy_sh_never_executes_the_hardening_scripts_the_rollbacks_or_the_proposals

printf '\n%d PASS, %d FAIL\n' "$PASS" "$FAILED"
[ "$FAILED" -eq 0 ]
