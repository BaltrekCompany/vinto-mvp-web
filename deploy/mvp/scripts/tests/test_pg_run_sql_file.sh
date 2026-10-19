#!/usr/bin/env bash
# VINTO MVP WEB — pruebas focalizadas de pg_run_sql_file() (CLOUD-DEP-02B.2-G.8-R1).
#
# G.8 encontró que pg_run_sql_file() abría el .sql con una redirección normal del shell
# invocador (ubuntu), que no puede leer árboles privados del MVP (750, exclusivo de
# $MVP_SERVICE_USER) -- "Permission denied" real contra backend/roles/00_create_roles.sql.
#
# Igual que test_assert_path_not_shared.sh (G.6-R1): "docker" y "sudo" son funciones de shell
# simuladas con datos sintéticos, NUNCA los binarios reales -- esta suite no requiere Docker ni
# PostgreSQL instalados y no escribe nada en ninguna base real. Cada prueba lanza un proceso bash
# COMPLETAMENTE NUEVO (nunca un "( ... )" anidado dentro de este mismo proceso): un "( ... )"
# anidado no siempre propaga el abort de "set -e" de la misma forma que un proceso nuevo bajo
# Git Bash/Cygwin (lección de G.6-R1), y además así se reproduce fielmente cómo deploy.sh corre
# de verdad (invocado una vez, de cero).
#
# Uso: bash deploy/mvp/scripts/tests/test_pg_run_sql_file.sh

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

# Harness común: sourcea lib_common.sh y define "sudo"/"docker" simulados en un proceso bash
# nuevo. Variables de entorno (ya exportadas por el prefijo "VAR=valor run_pg_run_sql_file ...")
# controlan el comportamiento del mock:
#   MOCK_CAT_FAIL=1            -> "sudo -u vinto-mvp cat -- <sql_file>" falla (código 7).
#   MOCK_CAT_PARTIAL_OUTPUT=x  -> esa misma llamada imprime "x" por stdout Y falla (lectura parcial).
#   MOCK_PSQL_EXIT=<n>         -> el "docker exec ... psql ..." simulado termina con código n.
# Archivos de registro (sobreviven al proceso nuevo, a diferencia de una variable):
#   $LOGDIR/sudo_calls.log     -> una línea por invocación de "sudo", con sus argumentos exactos.
#   $LOGDIR/docker_calls.log   -> una línea por invocación de "docker", con sus argumentos exactos.
#   $LOGDIR/psql_stdin.bin     -> bytes exactos recibidos por el "psql" simulado via stdin.
run_pg_run_sql_file() {
  local sql_file="$1" role="$2" password="$3" db="$4"; shift 4
  bash -c '
    set -euo pipefail
    # shellcheck source=../lib_common.sh
    source "$SCRIPT_DIR/../lib_common.sh"

    sudo() {
      printf "%s\n" "$*" >> "$LOGDIR/sudo_calls.log"
      if [ "$1" = "-u" ] && [ "$3" = "cat" ]; then
        local target_path="$5"
        # "--" en la posición 4 ("cat" "--" "<path>"); el path real es el argumento siguiente.
        if [ "${MOCK_CAT_FAIL:-0}" = "1" ]; then
          [ -n "${MOCK_CAT_PARTIAL_OUTPUT:-}" ] && printf "%s" "$MOCK_CAT_PARTIAL_OUTPUT"
          return 7
        fi
        cat -- "$target_path"
        return 0
      fi
      echo "mock sudo: invocación no soportada en esta prueba: $*" >&2
      return 99
    }

    docker() {
      printf "%s\n" "$*" >> "$LOGDIR/docker_calls.log"
      case "$1" in
        inspect)
          printf "%s" "${MVP_COMPOSE_PROJECT}"
          return 0
          ;;
        exec)
          # Distinguir el sub-caso por la presencia de "psql"/"sh"/"rm" entre los argumentos.
          local has_psql=0 has_rm=0
          for a in "$@"; do
            [ "$a" = "psql" ] && has_psql=1
            [ "$a" = "rm" ] && has_rm=1
          done
          if [ "$has_psql" = "1" ]; then
            cat > "$LOGDIR/psql_stdin.bin"
            return "${MOCK_PSQL_EXIT:-0}"
          elif [ "$has_rm" = "1" ]; then
            return 0
          else
            cat >/dev/null  # consume stdin de _pg_write_pgpass (umask 077; cat > remote)
            return 0
          fi
          ;;
        *)
          echo "mock docker: subcomando no soportado en esta prueba: $*" >&2
          return 99
          ;;
      esac
    }

    pg_run_sql_file "$2" "$3" "$4" "$1" "${@:5}"
  ' bash "$sql_file" "$role" "$password" "$db" "$@"
}

LOGDIR=""
setup_logdir() {
  LOGDIR="$(mktemp -d)"
  export LOGDIR
  : > "$LOGDIR/sudo_calls.log"
  : > "$LOGDIR/docker_calls.log"
}
teardown_logdir() {
  rm -rf "$LOGDIR"
}

# --- 1. Lectura bajo la identidad correcta: "sudo -u $MVP_SERVICE_USER cat -- <archivo>", NUNCA
# una redirección directa del invocador. Se verifica el comando REGISTRADO, no solo el resultado:
# un mock que "funcionara por casualidad" con la identidad equivocada no debe pasar esta prueba. ---
test_lectura_identidad_correcta() {
  setup_logdir
  local rc=0
  printf 'SELECT 1;\n' > "$LOGDIR/sample.sql"
  run_pg_run_sql_file "$LOGDIR/sample.sql" app_role app_pw vinto_piloto \
    >"$LOGDIR/out.log" 2>&1 || rc=$?
  local ok=1
  [ "$rc" -eq 0 ] || ok=0
  grep -qF -- "-u vinto-mvp cat -- $LOGDIR/sample.sql" "$LOGDIR/sudo_calls.log" || ok=0
  teardown_logdir
  [ "$ok" -eq 1 ]
}

# --- 2. Transmisión correcta del SQL a psql: el contenido recibido por stdin debe ser EXACTO
# (incluye comillas, $, backticks -- nunca re-evaluado por el shell). ---
test_transmision_correcta() {
  setup_logdir
  local rc=0
  printf '%s\n' \
    "-- comentario con \$VAR, \`backtick\`, comillas \"dobles\" y 'simples'" \
    "SELECT 'texto con espacios y \$1 literal';" \
    > "$LOGDIR/sample.sql"
  run_pg_run_sql_file "$LOGDIR/sample.sql" app_role app_pw vinto_piloto \
    >"$LOGDIR/out.log" 2>&1 || rc=$?
  local ok=1
  [ "$rc" -eq 0 ] || ok=0
  # "$(...)" descarta los saltos de línea finales por igual en ambos lados (comportamiento
  # estándar de la sustitución de comandos de bash, inofensivo para SQL terminado en ";" -- la
  # propia pg_run_sql_file lee el archivo con este mismo mecanismo); el resto del contenido,
  # incluidos "$", comillas y backticks, debe llegar carácter por carácter.
  [ "$(cat -- "$LOGDIR/sample.sql")" = "$(cat -- "$LOGDIR/psql_stdin.bin")" ] || ok=0
  teardown_logdir
  [ "$ok" -eq 1 ]
}

# --- 3. Archivo inexistente/ilegible: FAIL seguro, y psql NUNCA se invoca (un "psql -f -" con
# entrada vacía terminaría con éxito, confundiendo el fallo de lectura con una ejecución OK). ---
test_archivo_ilegible_fail_seguro() {
  setup_logdir
  local rc=0
  printf 'SELECT 1;\n' > "$LOGDIR/sample.sql"
  MOCK_CAT_FAIL=1 run_pg_run_sql_file "$LOGDIR/sample.sql" app_role app_pw vinto_piloto \
    >"$LOGDIR/out.log" 2>&1 || rc=$?
  local ok=1
  [ "$rc" -ne 0 ] || ok=0
  grep -q 'psql' "$LOGDIR/docker_calls.log" 2>/dev/null && ok=0
  teardown_logdir
  [ "$ok" -eq 1 ]
}

# --- 4. Fallo de lectura PARCIAL (el "cat" simulado imprime algo antes de fallar): debe seguir
# tratándose como FAIL seguro -- el código de salida manda, nunca la presencia de output. ---
test_lectura_parcial_fail_seguro() {
  setup_logdir
  local rc=0
  printf 'SELECT 1;\n' > "$LOGDIR/sample.sql"
  MOCK_CAT_FAIL=1 MOCK_CAT_PARTIAL_OUTPUT="-- solo la mitad del archivo" \
  run_pg_run_sql_file "$LOGDIR/sample.sql" app_role app_pw vinto_piloto \
    >"$LOGDIR/out.log" 2>&1 || rc=$?
  local ok=1
  [ "$rc" -ne 0 ] || ok=0
  grep -q 'psql' "$LOGDIR/docker_calls.log" 2>/dev/null && ok=0
  teardown_logdir
  [ "$ok" -eq 1 ]
}

# --- 5. Fallo de psql (ON_ERROR_STOP=1): el código de salida distinto de cero se propaga tal
# cual como resultado de pg_run_sql_file. ---
test_fallo_psql_propagado() {
  setup_logdir
  local rc=0
  printf 'SELECT 1;\n' > "$LOGDIR/sample.sql"
  MOCK_PSQL_EXIT=3 run_pg_run_sql_file "$LOGDIR/sample.sql" app_role app_pw vinto_piloto \
    >"$LOGDIR/out.log" 2>&1 || rc=$?
  local ok=1
  [ "$rc" -eq 3 ] || ok=0
  teardown_logdir
  [ "$ok" -eq 1 ]
}

# --- 6. Limpieza de .pgpass y de archivos temporales tras un error de psql (y, por separado,
# que un fallo de lectura no deja nada que limpiar: nunca se llegó a crear .pgpass). ---
test_limpieza_tras_error() {
  setup_logdir
  local rc=0
  printf 'SELECT 1;\n' > "$LOGDIR/sample.sql"
  MOCK_PSQL_EXIT=1 run_pg_run_sql_file "$LOGDIR/sample.sql" app_role app_pw vinto_piloto \
    >"$LOGDIR/out.log" 2>&1 || rc=$?
  local ok=1
  [ "$rc" -ne 0 ] || ok=0
  grep -q ' rm -f ' "$LOGDIR/docker_calls.log" || ok=0
  teardown_logdir

  # Camino de fallo de lectura: nunca se invoca _pg_write_pgpass (ninguna llamada a "docker" en
  # absoluto más allá de "assert_container_is_ours"), así que no hay nada que limpiar.
  setup_logdir
  local rc2=0
  MOCK_CAT_FAIL=1 run_pg_run_sql_file "$LOGDIR/sample.sql" app_role app_pw vinto_piloto \
    >"$LOGDIR/out2.log" 2>&1 || rc2=$?
  local ok2=1
  [ "$rc2" -ne 0 ] || ok2=0
  grep -q ' rm -f ' "$LOGDIR/docker_calls.log" 2>/dev/null && ok2=0
  teardown_logdir
  [ "$ok" -eq 1 ] && [ "$ok2" -eq 1 ]
}

# --- 7. Sin filtración de contraseñas (ni de rol/BD usados como marcador) en ninguna salida. ---
test_sin_filtracion_de_secretos() {
  setup_logdir
  local rc=0
  printf 'SELECT 1;\n' > "$LOGDIR/sample.sql"
  run_pg_run_sql_file "$LOGDIR/sample.sql" app_role 'S3cr3t_M4rk3r_9f3a' vinto_piloto \
    >"$LOGDIR/out.log" 2>&1 || rc=$?
  local ok=1
  [ "$rc" -eq 0 ] || ok=0
  grep -qF 'S3cr3t_M4rk3r_9f3a' "$LOGDIR/out.log" "$LOGDIR/sudo_calls.log" "$LOGDIR/docker_calls.log" 2>/dev/null && ok=0
  teardown_logdir
  [ "$ok" -eq 1 ]
}

# --- 8. Rutas privadas con espacios y caracteres especiales: deben llegar INTACTAS (un solo
# argumento), nunca divididas por espacios ni expandidas por el shell. ---
test_ruta_con_espacios_y_especiales() {
  setup_logdir
  local rc=0
  local weird_dir="$LOGDIR/dir con espacios y \$pecial's"
  mkdir -p "$weird_dir"
  printf 'SELECT 1;\n' > "$weird_dir/00_create roles.sql"
  run_pg_run_sql_file "$weird_dir/00_create roles.sql" app_role app_pw vinto_piloto \
    >"$LOGDIR/out.log" 2>&1 || rc=$?
  local ok=1
  [ "$rc" -eq 0 ] || ok=0
  grep -qF -- "-u vinto-mvp cat -- $weird_dir/00_create roles.sql" "$LOGDIR/sudo_calls.log" || ok=0
  [ "$(cat -- "$weird_dir/00_create roles.sql")" = "$(cat -- "$LOGDIR/psql_stdin.bin")" ] || ok=0
  teardown_logdir
  [ "$ok" -eq 1 ]
}

# --- 9. Compatibilidad con la forma exacta en que postgres-roles/postgres-grants invocan a esta
# función: pares NOMBRE=valor finales expuestos a psql vía --env-file (nunca -e literal). ---
test_compatibilidad_env_pairs() {
  setup_logdir
  local rc=0
  printf 'SELECT 1;\n' > "$LOGDIR/00_create_roles.sql"
  run_pg_run_sql_file "$LOGDIR/00_create_roles.sql" vinto_mvp_root bootstrap_pw vinto_piloto \
    "APP_PASSWORD=pw_app" "MIGRATOR_PASSWORD=pw_mig" "REFERENCE_PASSWORD=pw_ref" \
    >"$LOGDIR/out.log" 2>&1 || rc=$?
  local ok=1
  [ "$rc" -eq 0 ] || ok=0
  grep -q -- '--env-file' "$LOGDIR/docker_calls.log" || ok=0
  # Los 3 pares NOMBRE=valor deben viajar DENTRO del --env-file, nunca como "-e NOMBRE=valor"
  # literal (eso sí sería visible en la lista de procesos del host mientras el comando corre).
  # "-e PGPASSFILE=..." es un mecanismo aparte y preexistente (ruta de archivo, no un secreto de
  # \getenv) y SÍ debe seguir apareciendo así; no se prohíbe aquí.
  grep -qE -- '-e (APP_PASSWORD|MIGRATOR_PASSWORD|REFERENCE_PASSWORD)=' "$LOGDIR/docker_calls.log" && ok=0
  teardown_logdir
  [ "$ok" -eq 1 ]
}

# --- 10. Ninguna prueba de este archivo escribe en PostgreSQL real: "docker" es siempre la
# función simulada, nunca el binario real. Se confirma de dos formas: (a) bash resuelve "docker"
# a una FUNCIÓN (nunca a un ejecutable del PATH -- "type"/"command -v" ya priorizan funciones
# sobre el PATH, así que esto no es un simple supuesto) y (b) el registro de invocaciones
# efectivamente recibió llamadas (si no, ninguna de las pruebas 1-9 estaría probando nada real). ---
test_sin_escritura_real() {
  setup_logdir
  local rc=0
  printf 'SELECT 1;\n' > "$LOGDIR/sample.sql"
  bash -c '
    set -euo pipefail
    source "$SCRIPT_DIR/../lib_common.sh"
    sudo() {
      if [ "$1" = "-u" ] && [ "$3" = "cat" ]; then cat -- "$5"; return 0; fi
      return 99
    }
    docker() {
      printf "%s\n" "$*" >> "$LOGDIR/docker_calls.log"
      case "$1" in
        inspect) printf "%s" "${MVP_COMPOSE_PROJECT}"; return 0 ;;
        exec)
          for a in "$@"; do [ "$a" = "psql" ] && { cat >/dev/null; return 0; }; done
          cat >/dev/null; return 0 ;;
      esac
    }
    pg_run_sql_file app_role app_pw vinto_piloto "$1"
    type docker
  ' bash "$LOGDIR/sample.sql" >"$LOGDIR/out.log" 2>&1 || rc=$?
  local ok=1
  [ "$rc" -eq 0 ] || ok=0
  [ -s "$LOGDIR/docker_calls.log" ] || ok=0
  grep -qi 'docker is a function' "$LOGDIR/out.log" || ok=0
  teardown_logdir
  [ "$ok" -eq 1 ]
}

t() { local name="$1" fn="$2"; local rc=0; "$fn" || rc=$?; report "$name" "$rc"; }

t "1  lectura con identidad correcta (sudo -u vinto-mvp cat)"        test_lectura_identidad_correcta
t "2  transmision exacta del SQL a psql"                             test_transmision_correcta
t "3  archivo ilegible -> FAIL seguro, psql nunca invocado"           test_archivo_ilegible_fail_seguro
t "4  lectura parcial -> FAIL seguro (codigo manda, no el output)"    test_lectura_parcial_fail_seguro
t "5  fallo de psql -> codigo de salida propagado"                   test_fallo_psql_propagado
t "6  limpieza de pgpass/temporales tras error"                       test_limpieza_tras_error
t "7  sin filtracion de contraseñas en ninguna salida"                test_sin_filtracion_de_secretos
t "8  rutas con espacios y caracteres especiales"                     test_ruta_con_espacios_y_especiales
t "9  compatibilidad con pares NOMBRE=valor (postgres-roles/grants)"  test_compatibilidad_env_pairs
t "10 ninguna prueba escribe en PostgreSQL real"                      test_sin_escritura_real

echo
echo "Resumen: $PASS PASS, $FAILED FAIL."
[ "$FAILED" -eq 0 ]
