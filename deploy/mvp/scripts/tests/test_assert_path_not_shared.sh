#!/usr/bin/env bash
# VINTO MVP WEB — pruebas focalizadas de assert_path_not_shared_with_other_containers()
# (CLOUD-DEP-02B.2-G.6-R1).
#
# A diferencia de verify_local.sh (que crea contenedores Docker EFÍMEROS reales), este archivo
# NUNCA toca Docker de verdad: sustituye el comando "docker" por una función de shell ("Docker
# simulado") que devuelve datos sintéticos fijados por cada prueba. Esto permite ejercer, de forma
# determinista y sin efectos secundarios, rutas que serían difíciles o arriesgadas de forzar con
# contenedores reales (errores de "docker ps"/"docker inspect", condiciones de carrera, etc.).
#
# Uso: bash deploy/mvp/scripts/tests/test_assert_path_not_shared.sh
# Requiere únicamente: bash. NUNCA requiere ni usa un "docker" real (seguro de ejecutar en
# cualquier máquina, incluso sin Docker instalado).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SCRIPT_DIR

PASS=0
FAILED=0
report() {
  if [ "$2" -eq 0 ]; then
    printf 'PASS  %s\n' "$1"; PASS=$((PASS + 1))
  else
    printf 'FAIL  %s\n' "$1"; FAILED=$((FAILED + 1))
  fi
}

# Ejecuta assert_path_not_shared_with_other_containers en un proceso bash COMPLETAMENTE NUEVO
# (nunca un simple "( ... )" subshell del runner), con:
#   - lib_common.sh recién cargado (variables TVC_*/MVP_POSTGRES_CONTAINER en su valor real),
#   - un "docker()" simulado definido a partir de MOCK_PS_OUTPUT / MOCK_PS_FAIL /
#     MOCK_INSPECT_FAIL_FOR / MOCK_MOUNTS_<nombre saneado> (variables de entorno, ya exportadas
#     por el prefijo "VAR=valor run_assert ..." con el que cada prueba llama a esta función),
#   - "set -euo pipefail" activo, exactamente como en deploy.sh real (prueba #9).
#
# Un proceso bash NUEVO (vía "bash -c", nunca "( ... )") es deliberado: reproduce fielmente cómo
# corre deploy.sh de verdad (invocado una vez, de cero, nunca anidado dentro de otro bash ya en
# marcha) y evita un falso negativo observado durante el desarrollo de esta prueba: bajo Git
# Bash/Cygwin, un "( ... )" anidado DENTRO del proceso bash ya en ejecución de este mismo archivo
# de pruebas no siempre propaga el abort de "set -e" de la misma forma que un proceso bash
# iniciado de cero -- un detalle del entorno de pruebas local, no del código bajo prueba. "bash -c"
# elimina esa ambigüedad y coincide con el comportamiento ya confirmado manualmente en el VPS real
# (Linux) durante G.6.
run_assert() {
  bash -c '
    set -euo pipefail
    # shellcheck source=../lib_common.sh
    source "$SCRIPT_DIR/../lib_common.sh"

    docker() {
      case "$1" in
        ps)
          [ "${MOCK_PS_FAIL:-0}" = "1" ] && return 7
          printf "%s" "${MOCK_PS_OUTPUT:-}"
          return 0
          ;;
        inspect)
          target="$2"
          if [ "${MOCK_INSPECT_FAIL_FOR:-}" = "$target" ] || [ "${MOCK_INSPECT_FAIL_FOR:-}" = "*" ]; then
            return 9
          fi
          var_name="MOCK_MOUNTS_$(printf "%s" "$target" | tr -c "A-Za-z0-9_" "_")"
          printf "%s" "${!var_name:-}"
          return 0
          ;;
        *)
          echo "mock docker: subcomando no soportado en esta prueba: $*" >&2
          return 99
          ;;
      esac
    }

    assert_path_not_shared_with_other_containers "$1"
  ' bash "$1"
}

# --- 1. Sin contenedores: PASS ------------------------------------------------------------------
test_sin_contenedores() {
  local rc=0
  MOCK_PS_OUTPUT="" run_assert "/home/vinto-mvp/pgdata" >/tmp/t1.out 2>&1 || rc=$?
  [ "$rc" -eq 0 ]
}

# --- 2. Contenedores existentes sin coincidencias: PASS -----------------------------------------
test_sin_coincidencias() {
  local rc=0
  MOCK_PS_OUTPUT=$'vinto-monday-qa\nvinto-monday-rollback-qa\npostgres-vinto\n' \
  MOCK_MOUNTS_vinto_monday_qa=$'/home/ubuntu/vinto-monday-qa-data\n' \
  MOCK_MOUNTS_vinto_monday_rollback_qa=$'/home/ubuntu/vinto-monday-rollback-qa-data\n' \
  MOCK_MOUNTS_postgres_vinto=$'/home/ubuntu/vinto/pgdata\n' \
  run_assert "/home/vinto-mvp/pgdata" >/tmp/t2.out 2>&1 || rc=$?
  [ "$rc" -eq 0 ]
}

# --- 3. Contenedor ajeno que monta EXACTAMENTE PGDATA: FAIL seguro ------------------------------
test_coincidencia_exacta() {
  local rc=0
  MOCK_PS_OUTPUT=$'postgres-vinto\nvinto-monday-qa\n' \
  MOCK_MOUNTS_postgres_vinto=$'/home/ubuntu/vinto/pgdata\n' \
  MOCK_MOUNTS_vinto_monday_qa=$'/home/vinto-mvp/pgdata\n' \
  run_assert "/home/vinto-mvp/pgdata" >/tmp/t3.out 2>&1 || rc=$?
  [ "$rc" -eq 1 ] && grep -q "ya está montada en el contenedor ajeno 'vinto-monday-qa'" /tmp/t3.out
}

# --- 4. Ruta parecida pero no idéntica: NO debe dar falso positivo ------------------------------
test_ruta_parecida_no_identica() {
  local rc=0
  MOCK_PS_OUTPUT=$'vinto-monday-qa\n' \
  MOCK_MOUNTS_vinto_monday_qa=$'/home/vinto-mvp/pgdata-old\n/home/vinto-mvp/pgdata2\n' \
  run_assert "/home/vinto-mvp/pgdata" >/tmp/t4.out 2>&1 || rc=$?
  [ "$rc" -eq 0 ]
}

# --- 5. Error en "docker ps": FAIL seguro (nunca "sin conflicto") -------------------------------
test_error_docker_ps() {
  local rc=0
  MOCK_PS_FAIL=1 run_assert "/home/vinto-mvp/pgdata" >/tmp/t5.out 2>&1 || rc=$?
  [ "$rc" -eq 1 ] && grep -q "no se pudo listar los contenedores Docker existentes" /tmp/t5.out
}

# --- 6. Error en "docker inspect": FAIL seguro (nunca "sin conflicto") --------------------------
test_error_docker_inspect() {
  local rc=0
  MOCK_PS_OUTPUT=$'vinto-monday-qa\n' \
  MOCK_INSPECT_FAIL_FOR="vinto-monday-qa" \
  run_assert "/home/vinto-mvp/pgdata" >/tmp/t6.out 2>&1 || rc=$?
  [ "$rc" -eq 1 ] && grep -q "no se pudo inspeccionar el contenedor 'vinto-monday-qa'" /tmp/t6.out
}

# --- 7. Ruta dentro de TVC/ETL: FAIL seguro, sin siquiera consultar Docker ----------------------
test_ruta_protegida_tvc() {
  local rc=0
  # Si esto llegara a invocar "docker", el mock devolvería 99 (subcomando no soportado) en vez de
  # la FALLA esperada por ruta protegida -- distingue "se rechazó por TVC" de "se rechazó por
  # otra razón" sin depender de parsear el mensaje.
  MOCK_PS_OUTPUT="" run_assert "/opt/vinto-web/algo" >/tmp/t7.out 2>&1 || rc=$?
  [ "$rc" -eq 1 ] && grep -q "está dentro de un directorio de TVC/ETL" /tmp/t7.out
}

# --- 8. El contenedor MVP se identifica correctamente y se excluye SOLO a él, nunca a otro ------
test_contenedor_mvp_no_se_confunde() {
  local rc_mvp=0 rc_otro=0
  # 8a: el propio contenedor MVP (vinto-mvp-postgres) ya monta la ruta -- debe EXCLUIRSE (PASS).
  MOCK_PS_OUTPUT=$'vinto-mvp-postgres\n' \
  MOCK_MOUNTS_vinto_mvp_postgres=$'/home/vinto-mvp/pgdata\n' \
  run_assert "/home/vinto-mvp/pgdata" >/tmp/t8a.out 2>&1 || rc_mvp=$?
  # 8b: un contenedor de OTRO proyecto con nombre parecido (no exacto) NO debe excluirse -- debe
  # detectarse como conflicto real (FAIL).
  MOCK_PS_OUTPUT=$'vinto-mvp-postgres-old\n' \
  MOCK_MOUNTS_vinto_mvp_postgres_old=$'/home/vinto-mvp/pgdata\n' \
  run_assert "/home/vinto-mvp/pgdata" >/tmp/t8b.out 2>&1 || rc_otro=$?
  [ "$rc_mvp" -eq 0 ] && [ "$rc_otro" -eq 1 ]
}

# --- 9. Bajo set -euo pipefail, la AUSENCIA de coincidencias NO aborta (regresión de G.6) -------
test_no_abort_bajo_pipefail_sin_coincidencias() {
  local rc=0
  # Varios contenedores, ninguno coincide -- este es exactamente el escenario que en G.6 abortaba
  # silenciosamente con exit code 1 pese a no haber ningún conflicto real.
  MOCK_PS_OUTPUT=$'vinto-monday-rollback-qa-20261015\nvinto-monday-prod-rehearsal\nvinto-monday-qa-20261014\npostgres-vinto\n' \
  MOCK_MOUNTS_vinto_monday_rollback_qa_20261015=$'/home/ubuntu/vinto-monday-rollback-qa-data\n' \
  MOCK_MOUNTS_vinto_monday_prod_rehearsal=$'/home/ubuntu/vinto-monday-prod-rehearsal-data\n' \
  MOCK_MOUNTS_vinto_monday_qa_20261014=$'/home/ubuntu/vinto-monday-qa-data\n' \
  MOCK_MOUNTS_postgres_vinto=$'/home/ubuntu/vinto/pgdata\n' \
  run_assert "/home/vinto-mvp/pgdata" >/tmp/t9.out 2>&1 || rc=$?
  [ "$rc" -eq 0 ]
}

# --- 10. Ninguna prueba de este archivo toca recursos Docker reales -----------------------------
# Verificado por construcción: "docker" es una función de shell definida DENTRO del proceso bash
# nuevo que lanza run_assert, nunca el binario real. Aquí se confirma, además, que el mock sí fue
# invocado (si no lo hubiera sido, las pruebas 1-9 no estarían probando nada) y que, con el PATH
# vaciado en ese proceso, un "docker" real -- si por error se llamara -- ni siquiera podría
# encontrarse (fallaría con "command not found", nunca con un resultado simulado). El registro de
# invocaciones se escribe a un ARCHIVO (nunca a una variable de ese proceso, que se perdería al
# terminar).
test_no_toca_docker_real() {
  local rc=0
  local calls
  rm -f /tmp/t10_calls.log
  bash -c '
    set -euo pipefail
    # shellcheck source=../lib_common.sh
    source "$SCRIPT_DIR/../lib_common.sh"
    PATH=""
    docker() {
      echo "$*" >>/tmp/t10_calls.log
      case "$1" in
        ps) printf "%s" "vinto-monday-qa"; return 0 ;;
        inspect) printf "%s" "/home/ubuntu/vinto-monday-qa-data"; return 0 ;;
        *) return 99 ;;
      esac
    }
    assert_path_not_shared_with_other_containers "/home/vinto-mvp/pgdata"
  ' bash >/tmp/t10.out 2>&1 || rc=$?
  calls="$([ -f /tmp/t10_calls.log ] && wc -l </tmp/t10_calls.log || echo 0)"
  [ "$rc" -eq 0 ] && [ "${calls:-0}" -ge 2 ]
}

t() { local name="$1" fn="$2"; local rc=0; "$fn" || rc=$?; report "$name" "$rc"; }

t "1  sin contenedores -> PASS"                                    test_sin_contenedores
t "2  contenedores existentes sin coincidencias -> PASS"           test_sin_coincidencias
t "3  coincidencia exacta de montaje -> FAIL seguro"                test_coincidencia_exacta
t "4  ruta parecida pero no identica -> sin falso positivo"         test_ruta_parecida_no_identica
t "5  error en docker ps -> FAIL seguro"                            test_error_docker_ps
t "6  error en docker inspect -> FAIL seguro"                       test_error_docker_inspect
t "7  ruta protegida TVC/ETL -> FAIL seguro"                        test_ruta_protegida_tvc
t "8  contenedor MVP identificado sin confundirse con otro"         test_contenedor_mvp_no_se_confunde
t "9  set -euo pipefail: sin coincidencias no aborta (regresion G.6)" test_no_abort_bajo_pipefail_sin_coincidencias
t "10 ninguna prueba toca Docker real"                              test_no_toca_docker_real

echo
echo "Resumen: $PASS PASS, $FAILED FAIL."
[ "$FAILED" -eq 0 ]
