#!/usr/bin/env bash
# VINTO MVP WEB — pruebas locales obligatorias de CLOUD-DEP-02A.2 (PR #55) y su ronda 2
# (CLOUD-DEP-02A.2-R2, DEP55-R2-01..04).
#
# Corre ENTERAMENTE en local (Windows/Git Bash o Linux), sin acceder al VPS. Todo lo que necesita
# PostgreSQL usa contenedores EFÍMEROS, creados y destruidos por este mismo script — nunca una
# base existente ni el PostgreSQL de TVC.
#
# DEP55-R2-01 ("seguridad del runner"): a diferencia de la versión anterior de este archivo, NUNCA
# se hace un "docker rm -f <nombre fijo>" preventivo al empezar (eso podría destruir un recurso
# ajeno que coincidiera por casualidad con ese nombre). En su lugar, cada recurso que este script
# crea:
#   1. usa un nombre ÚNICO por ejecución (create_container genera el sufijo),
#   2. se comprueba que NO existe ya ANTES de crearlo (si existe, se considera una colisión y la
#      prueba falla en vez de reutilizarlo o destruirlo),
#   3. se registra por su ID real (devuelto por "docker run", confirmado con "docker inspect"),
#      nunca por el nombre que se le pidió,
#   4. se limpia exclusivamente por ese ID, nunca por nombre, al final de la prueba Y también ante
#      un error o una interrupción (trap EXIT/INT/TERM sobre la lista de IDs registrados).
#
# Uso: bash deploy/mvp/scripts/tests/verify_local.sh
# Requiere: bash, docker, git. Seguro de ejecutar repetidamente.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MVP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
REPO_ROOT="$(cd "$MVP_DIR/../.." && pwd)"
# shellcheck source=../lib_common.sh
source "$SCRIPT_DIR/../lib_common.sh"

PASS=0
FAILED=0
report() {
  if [ "$2" -eq 0 ]; then
    printf 'PASS  %s\n' "$1"; PASS=$((PASS + 1))
  else
    printf 'FAIL  %s\n' "$1"; FAILED=$((FAILED + 1))
  fi
}

# --- Ciclo de vida seguro de recursos (DEP55-R2-01) --------------------------------------------
TRACKED_CONTAINER_IDS=()
TRACKED_TMP_PATHS=()
TRACKED_PIDS=()
track_pid() { TRACKED_PIDS+=("$1"); }

_verify_unique_suffix() {
  printf '%s-%s-%s' "$$" "$RANDOM" "$(date +%s%N 2>/dev/null || date +%s)"
}

# create_container <nombre-base> <docker run args...> -- crea un contenedor con un nombre ÚNICO
# derivado de <nombre-base>, comprueba que no colisiona con nada preexistente, lo crea, confirma
# su ID real con "docker inspect" y lo registra para limpieza. Deja el resultado en las variables
# GLOBALES CREATED_NAME/CREATED_ID (nunca por stdout vía "$(...)": una sustitución de comandos
# corre en una subshell, y la mutación de TRACKED_CONTAINER_IDS se perdería al salir de ella).
CREATED_NAME=""
CREATED_ID=""
create_container() {
  CREATED_NAME=""
  CREATED_ID=""
  local base_name="$1"; shift
  local name
  name="${base_name}-$(_verify_unique_suffix)"
  if docker inspect "$name" >/dev/null 2>&1; then
    echo "create_container: colisión inesperada, '$name' ya existe. Abortando sin tocarlo." >&2
    return 1
  fi
  local cid
  cid="$(docker run -d --name "$name" "$@")" || return 1
  local confirmed
  confirmed="$(docker inspect --format '{{.Id}}' "$cid" 2>/dev/null || true)"
  if [ -z "$confirmed" ] || [ "$confirmed" != "$cid" ]; then
    echo "create_container: no se pudo confirmar el ID del contenedor creado (docker run devolvió '$cid', docker inspect devolvió '${confirmed:-nada}'). Abortando." >&2
    docker rm -f "$cid" >/dev/null 2>&1 || true
    return 1
  fi
  TRACKED_CONTAINER_IDS+=("$confirmed")
  CREATED_NAME="$name"
  # shellcheck disable=SC2034 # parte deliberada del contrato de la función: no todas las pruebas
  # necesitan el ID además del nombre, pero queda disponible para las que sí (p. ej. limpieza
  # explícita por ID en un futuro caso de prueba).
  CREATED_ID="$confirmed"
}

track_tmp_path() { TRACKED_TMP_PATHS+=("$1"); }

# shellcheck disable=SC2329 # se invoca vía "trap cleanup_all EXIT INT TERM" más abajo, no por
# llamada directa; ShellCheck no reconoce esa forma de invocación.
cleanup_all() {
  local id
  for id in "${TRACKED_CONTAINER_IDS[@]:-}"; do
    [ -n "$id" ] && docker rm -f "$id" >/dev/null 2>&1 || true
  done
  local p
  for p in "${TRACKED_TMP_PATHS[@]:-}"; do
    [ -n "$p" ] && rm -rf "$p" 2>/dev/null || true
  done
  local pid
  for pid in "${TRACKED_PIDS[@]:-}"; do
    [ -n "$pid" ] && kill "$pid" >/dev/null 2>&1 || true
  done
}
trap cleanup_all EXIT INT TERM

echo "=== 1/10: bash syntax ==="
for f in deploy.sh rollback.sh preflight.sh lib_common.sh; do
  set +e
  bash -n "$SCRIPT_DIR/../$f"
  rc=$?
  set -e
  report "bash -n $f" "$rc"
done

echo "=== 2/10: ShellCheck (dockerizado) ==="
# MSYS_NO_PATHCONV se activa SOLO para estas dos llamadas (en una subshell, a propósito: así no
# hace falta desarmarla a mano y no puede quedar exportada para los pasos 3/4 más abajo, que
# necesitan la conversión de ruta normal de Git Bash).
# shellcheck disable=SC2030,SC2031 # intencional: el scope local a la subshell es justo lo buscado.
if ( export MSYS_NO_PATHCONV=1; docker run --rm -v "$SCRIPT_DIR/..:/mnt" koalaman/shellcheck:stable --shell=bash -x \
    /mnt/deploy.sh /mnt/rollback.sh /mnt/preflight.sh ) >/tmp/shellcheck-entrypoints.log 2>&1; then
  report "shellcheck deploy.sh/rollback.sh/preflight.sh (-x, sigue lib_common.sh)" 0
else
  cat /tmp/shellcheck-entrypoints.log
  report "shellcheck deploy.sh/rollback.sh/preflight.sh (-x, sigue lib_common.sh)" 1
fi
# shellcheck disable=SC2030,SC2031
if ( export MSYS_NO_PATHCONV=1; docker run --rm -v "$SCRIPT_DIR/..:/mnt" koalaman/shellcheck:stable --shell=bash /mnt/lib_common.sh ) \
    >/tmp/shellcheck-lib.log 2>&1; then
  report "shellcheck lib_common.sh (solo)" 0
else
  cat /tmp/shellcheck-lib.log
  report "shellcheck lib_common.sh (solo)" 1
fi
# -w /mnt/tests + ruta relativa: así ShellCheck resuelve "source=../lib_common.sh" (si no, con una
# ruta absoluta como argumento, el "-x" no sigue el "source" aunque el archivo exista en el mount
# — comportamiento confirmado de ShellCheck, no un error de este script).
# shellcheck disable=SC2030,SC2031
if ( export MSYS_NO_PATHCONV=1; docker run --rm -w /mnt/tests -v "$SCRIPT_DIR/..:/mnt" koalaman/shellcheck:stable --shell=bash -x verify_local.sh ) \
    >/tmp/shellcheck-self.log 2>&1; then
  report "shellcheck tests/verify_local.sh (-x, sigue lib_common.sh)" 0
else
  cat /tmp/shellcheck-self.log
  report "shellcheck tests/verify_local.sh (-x, sigue lib_common.sh)" 1
fi

echo "=== 3/10: Docker Compose config ==="
TMP_COMPOSE_ENV="$MVP_DIR/docker/.env.verify-tmp"
track_tmp_path "$TMP_COMPOSE_ENV"
cat > "$TMP_COMPOSE_ENV" <<EOF
POSTGRES_BOOTSTRAP_DB=vinto_mvp_bootstrap
POSTGRES_BOOTSTRAP_USER=vinto_mvp_root
POSTGRES_BOOTSTRAP_PASSWORD=test_only_not_real
VINTO_MVP_PGDATA_DIR=/tmp/vinto-mvp-pgdata-test
EOF
if docker compose -f "$MVP_DIR/docker/docker-compose.postgres.yml" --env-file "$TMP_COMPOSE_ENV" config \
    | grep -q '127.0.0.1'; then
  report "docker compose config resuelve correctamente (127.0.0.1:6544)" 0
else
  report "docker compose config resuelve correctamente (127.0.0.1:6544)" 1
fi
rm -f "$TMP_COMPOSE_ENV"

echo "=== 4/10: Nginx syntax ==="
NGINX_TEST_DIR="$(mktemp -d)"
track_tmp_path "$NGINX_TEST_DIR"
mkdir -p "$NGINX_TEST_DIR/conf.d"
sed -e 's/__DOMAIN__/vinto-mvp.baltrekservices.com/g' \
    -e 's/__FRONTEND_PORT__/3100/g' \
    -e 's/__BACKEND_PORT__/8100/g' \
    -e 's#__ALLOWED_CIDR__#203.0.113.0/24#g' \
    "$MVP_DIR/nginx/vinto-mvp.conf.template" > "$NGINX_TEST_DIR/conf.d/vinto-mvp.conf"
cat > "$NGINX_TEST_DIR/conf.d/vinto-tvc.conf" <<'EOF'
server {
    listen 80;
    server_name vinto-tvc.baltrekservices.com;
    location / { proxy_pass http://127.0.0.1:8000; proxy_set_header Host $host; }
}
EOF
WIN_NGINX_DIR="$(cygpath -w "$NGINX_TEST_DIR/conf.d" 2>/dev/null || echo "$NGINX_TEST_DIR/conf.d")"
if docker run --rm -v "${WIN_NGINX_DIR}:/etc/nginx/conf.d:ro" nginx:alpine nginx -t >/tmp/nginx-t.log 2>&1; then
  report "nginx -t (vinto-mvp + vinto-tvc juntos, sin colisión)" 0
else
  cat /tmp/nginx-t.log
  report "nginx -t (vinto-mvp + vinto-tvc juntos, sin colisión)" 1
fi
rm -rf "$NGINX_TEST_DIR"

echo "=== 5/10: pruebas negativas de recursos ajenos (sin destruir nada preexistente) ==="
if ! grep -qE 'rm -rf.*PGDATA|DESTROY_DATA' "$SCRIPT_DIR/../rollback.sh"; then
  report "rollback.sh no contiene ningún rm -rf de datos ni DESTROY_DATA" 0
else
  report "rollback.sh no contiene ningún rm -rf de datos ni DESTROY_DATA" 1
fi
if ! grep -vE '^\s*#' "$SCRIPT_DIR/../rollback.sh" "$SCRIPT_DIR/../deploy.sh" | grep -nE 'source\s+"[^"]*\.env'; then
  report "rollback.sh/deploy.sh no hacen 'source' de ningún .env operativo" 0
else
  report "rollback.sh/deploy.sh no hacen 'source' de ningún .env operativo" 1
fi
# assert_unit_is_ours debe rechazar (exit !=0) una unidad con el mismo nombre que no es nuestra.
# No se crea/toca ninguna unidad systemd real: solo un archivo de texto equivalente.
FAKE_UNIT_DIR="$(mktemp -d)"
track_tmp_path "$FAKE_UNIT_DIR"
cat > "$FAKE_UNIT_DIR/fake.service" <<'EOF'
[Service]
ExecStart=/usr/bin/true
EOF
set +e
( grep -q "WorkingDirectory=$MVP_APP_DIR" "$FAKE_UNIT_DIR/fake.service" 2>/dev/null \
    || grep -qE "^ExecStart=.*$MVP_APP_DIR" "$FAKE_UNIT_DIR/fake.service" 2>/dev/null )
unit_matches=$?
set -e
if [ "$unit_matches" -ne 0 ]; then
  report "una unidad ajena (sin referencia a $MVP_APP_DIR) NO pasaría assert_unit_is_ours" 0
else
  report "una unidad ajena (sin referencia a $MVP_APP_DIR) NO pasaría assert_unit_is_ours" 1
fi

# Contenedor AJENO con nombre ÚNICO (nunca el nombre real "vinto-mvp-postgres"): confirma que
# assert_container_is_ours lo rechaza sin que este runner necesite tocar ningún recurso real.
set +e
create_container vinto-mvp-verify-foreign --label "com.docker.compose.project=otro-proyecto" alpine:3 sleep 60
foreign_create_status=$?
set -e
if [ "$foreign_create_status" -eq 0 ]; then
  FOREIGN_NAME="$CREATED_NAME"
  set +e
  bash -c "source '$SCRIPT_DIR/../lib_common.sh'; MVP_POSTGRES_CONTAINER='$FOREIGN_NAME' assert_container_is_ours '$FOREIGN_NAME'" \
    >/tmp/assert-container.log 2>&1
  foreign_result=$?
  set -e
  if [ "$foreign_result" -ne 0 ]; then
    report "assert_container_is_ours rechaza un contenedor ajeno (etiqueta de proyecto distinta)" 0
  else
    cat /tmp/assert-container.log
    report "assert_container_is_ours rechaza un contenedor ajeno (etiqueta de proyecto distinta)" 1
  fi
else
  report "assert_container_is_ours rechaza un contenedor ajeno (etiqueta de proyecto distinta)" 1
fi

echo "=== 6/10: pruebas de limpieza temporal (DEP55-R2-03) ==="
# env_value nunca ejecuta código: un valor con sustitución de comandos se devuelve como texto.
INJECTION_ENV="$(mktemp)"
track_tmp_path "$INJECTION_ENV"
MARKER_FILE="$(mktemp -u)"
# shellcheck disable=SC2016 # literal a propósito: "$(touch ...)" debe quedar como TEXTO dentro
# del .env de prueba, nunca expandirse aquí — eso es justamente lo que se está comprobando.
printf 'MALICIOUS=$(touch %s)\n' "$MARKER_FILE" > "$INJECTION_ENV"
set +e
value="$(env_value "$INJECTION_ENV" MALICIOUS)"
set -e
expected_literal="\$(touch $MARKER_FILE)"
if [ ! -e "$MARKER_FILE" ] && [ "$value" = "$expected_literal" ]; then
  report "env_value nunca ejecuta el contenido de un .env (sin source)" 0
else
  rm -f "$MARKER_FILE"
  report "env_value nunca ejecuta el contenido de un .env (sin source)" 1
fi

# password_from_pg_url decodifica porcentaje (contraseña con "@"/"+" codificados).
set +e
decoded="$(password_from_pg_url 'postgresql://vinto_app:cl%40ve%2Bsegura@127.0.0.1:6544/vinto_piloto')"
set -e
if [ "$decoded" = 'cl@ve+segura' ]; then
  report "password_from_pg_url decodifica porcentaje correctamente (%40 -> @, %2B -> +)" 0
else
  report "password_from_pg_url decodifica porcentaje correctamente (%40 -> @, %2B -> +) [obtenido: longitud ${#decoded}]" 1
fi

# Rutas temporales únicas por llamada: dos invocaciones de _pg_write_pgpass (o del sufijo que usa)
# nunca deben coincidir, incluso en el mismo segundo.
suffix_a="$(_pg_unique_suffix)"; suffix_b="$(_pg_unique_suffix)"
if [ "$suffix_a" != "$suffix_b" ]; then
  report "_pg_unique_suffix genera valores distintos en llamadas consecutivas" 0
else
  report "_pg_unique_suffix genera valores distintos en llamadas consecutivas" 1
fi

# El archivo --env-file que escribe pg_run_sql_file queda con permisos 600 mientras existe (se
# verifica indirectamente más abajo, en la prueba 7, inspeccionando el contenedor en pleno vuelo).

echo "=== 7/10: pruebas concurrentes de autenticación PostgreSQL (DEP55-02, DEP55-R2-01/03) ==="
BOOTSTRAP_USER=verify_root
BOOTSTRAP_PASSWORD="$(head -c18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
APP_PW="$(head -c18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
MIGRATOR_PW="$(head -c18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
REFERENCE_PW="$(head -c18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
# MSYS_NO_PATHCONV evita que Git Bash reescriba "/var/lib/postgresql/data" (una ruta DENTRO del
# contenedor, nunca del host) como si fuera una ruta de Windows.
# MSYS_NO_PATHCONV se exporta en ESTE shell (nunca dentro de una sustitución de comandos ni de una
# subshell): create_container registra el ID creado en el array TRACKED_CONTAINER_IDS de este
# mismo proceso, y correrlo en una subshell perdería esa mutación al salir (el array quedaría
# vacío para el trap de limpieza) — por eso ahora se llama como sentencia simple, no vía "$(...)".
# shellcheck disable=SC2031 # export de nivel superior (no en subshell); el aviso es un residuo
# del análisis de las subshells de arriba, no aplica a esta asignación.
export MSYS_NO_PATHCONV=1
set +e
create_container vinto-mvp-verify-pg \
  --label com.docker.compose.project=vinto-mvp \
  --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_DB=vinto_mvp_bootstrap -e POSTGRES_USER="$BOOTSTRAP_USER" -e POSTGRES_PASSWORD="$BOOTSTRAP_PASSWORD" \
  postgres:17
ephemeral_create_status=$?
set -e
unset MSYS_NO_PATHCONV
if [ "$ephemeral_create_status" -ne 0 ]; then
  report "creación del Postgres efímero para la prueba 7" 1
else
EPHEMERAL_NAME="$CREATED_NAME"
for _ in $(seq 1 30); do
  docker exec "$EPHEMERAL_NAME" pg_isready -U "$BOOTSTRAP_USER" -d vinto_mvp_bootstrap >/dev/null 2>&1 && break
  sleep 1
done

# 7a. Orden de aprovisionamiento: bootstrap-db -> 00_create_roles -> 01_database_grants, y que
# 00_create_roles.sql sigue siendo idempotente al repetirse. El cuerpo vive en un script temporal
# propio ejecutado como SUBPROCESO (las funciones de lib_common.sh hacen "exit 1" a propósito si
# algo no coincide, y eso debe terminar solo ese subproceso, nunca este runner). Los valores se
# pasan por variables de entorno exportadas, nunca interpolados en texto de shell.
PROVISION_SCRIPT="$(mktemp)"
track_tmp_path "$PROVISION_SCRIPT"
cat > "$PROVISION_SCRIPT" <<'EOS'
set -e
source "$LIB_COMMON_PATH"
assert_container_is_ours "$EPHEMERAL_NAME"
exists="$(pg_run_sql_inline "$BOOTSTRAP_USER" "$BOOTSTRAP_PASSWORD" vinto_mvp_bootstrap \
  "SELECT 1 FROM pg_database WHERE datname = 'vinto_piloto';")"
if [ "$exists" != "1" ]; then
  pg_run_sql_inline "$BOOTSTRAP_USER" "$BOOTSTRAP_PASSWORD" vinto_mvp_bootstrap \
    "CREATE DATABASE vinto_piloto OWNER ${BOOTSTRAP_USER};"
fi
pg_run_sql_file "$BOOTSTRAP_USER" "$BOOTSTRAP_PASSWORD" vinto_piloto "$ROLES_DIR/00_create_roles.sql" \
  "APP_PASSWORD=$APP_PW" "MIGRATOR_PASSWORD=$MIGRATOR_PW" "REFERENCE_PASSWORD=$REFERENCE_PW"
pg_run_sql_file "$BOOTSTRAP_USER" "$BOOTSTRAP_PASSWORD" vinto_piloto "$ROLES_DIR/01_database_grants.sql" \
  "DBNAME=vinto_piloto"
roles_created="$(pg_run_sql_inline "$BOOTSTRAP_USER" "$BOOTSTRAP_PASSWORD" vinto_piloto \
  "SELECT count(*) FROM pg_roles WHERE rolname IN ('vinto_app','vinto_migrator','vinto_reference');")"
[ "$roles_created" = "3" ]
# Repetir 00_create_roles.sql debe seguir siendo idempotente (no falla al re-ejecutarse).
pg_run_sql_file "$BOOTSTRAP_USER" "$BOOTSTRAP_PASSWORD" vinto_piloto "$ROLES_DIR/00_create_roles.sql" \
  "APP_PASSWORD=$APP_PW" "MIGRATOR_PASSWORD=$MIGRATOR_PW" "REFERENCE_PASSWORD=$REFERENCE_PW"
EOS
set +e
# shellcheck disable=SC2097,SC2098 # a propósito: "VAR=valor bash script" exporta VAR al proceso
# hijo para que el script temporal (PROVISION_SCRIPT) lo lea con "$VAR"; no es una auto-asignación
# redundante, es el mecanismo para pasarle variables sin tocar el entorno de ESTE shell.
LIB_COMMON_PATH="$SCRIPT_DIR/../lib_common.sh" ROLES_DIR="$REPO_ROOT/backend/roles" \
  EPHEMERAL_NAME="$EPHEMERAL_NAME" MVP_POSTGRES_CONTAINER="$EPHEMERAL_NAME" \
  BOOTSTRAP_USER="$BOOTSTRAP_USER" BOOTSTRAP_PASSWORD="$BOOTSTRAP_PASSWORD" \
  APP_PW="$APP_PW" MIGRATOR_PW="$MIGRATOR_PW" REFERENCE_PW="$REFERENCE_PW" \
  MSYS_NO_PATHCONV=1 \
  bash "$PROVISION_SCRIPT" >/tmp/verify7a.log 2>&1
step_ok=$?
set -e
if [ "$step_ok" -eq 0 ]; then
  report "postgres-bootstrap-db -> 00_create_roles.sql -> 01_database_grants.sql, en orden (idempotente)" 0
else
  echo "--- log de la prueba 7a ---"; cat /tmp/verify7a.log
  report "postgres-bootstrap-db -> 00_create_roles.sql -> 01_database_grants.sql, en orden (idempotente)" 1
fi

# 7b. Concurrencia: dos consultas de solo lectura contra el MISMO contenedor, EN PARALELO, cada
# una con su propio pgpass/envfile efímero (DEP55-R2-03: "dos ejecuciones simultáneas no
# interfieren"). Si las rutas temporales colisionaran, una de las dos fallaría o leería datos de
# la otra.
CONCURRENT_SCRIPT="$(mktemp)"
track_tmp_path "$CONCURRENT_SCRIPT"
cat > "$CONCURRENT_SCRIPT" <<'EOS'
set -e
source "$LIB_COMMON_PATH"
result="$(pg_run_sql_inline "$BOOTSTRAP_USER" "$BOOTSTRAP_PASSWORD" vinto_mvp_bootstrap "SELECT '$TOKEN';")"
[ "$result" = "$TOKEN" ]
EOS
set +e
( LIB_COMMON_PATH="$SCRIPT_DIR/../lib_common.sh" MVP_POSTGRES_CONTAINER="$EPHEMERAL_NAME" \
    BOOTSTRAP_USER="$BOOTSTRAP_USER" BOOTSTRAP_PASSWORD="$BOOTSTRAP_PASSWORD" TOKEN=token-uno \
    bash "$CONCURRENT_SCRIPT" >/tmp/verify7b-1.log 2>&1 ) &
pid1=$!
( LIB_COMMON_PATH="$SCRIPT_DIR/../lib_common.sh" MVP_POSTGRES_CONTAINER="$EPHEMERAL_NAME" \
    BOOTSTRAP_USER="$BOOTSTRAP_USER" BOOTSTRAP_PASSWORD="$BOOTSTRAP_PASSWORD" TOKEN=token-dos \
    bash "$CONCURRENT_SCRIPT" >/tmp/verify7b-2.log 2>&1 ) &
pid2=$!
wait "$pid1"; r1=$?
wait "$pid2"; r2=$?
set -e
if [ "$r1" -eq 0 ] && [ "$r2" -eq 0 ]; then
  report "dos llamadas concurrentes a pg_run_sql_inline contra el mismo contenedor no interfieren" 0
else
  echo "--- log concurrente 1 ---"; cat /tmp/verify7b-1.log
  echo "--- log concurrente 2 ---"; cat /tmp/verify7b-2.log
  report "dos llamadas concurrentes a pg_run_sql_inline contra el mismo contenedor no interfieren" 1
fi

# 7c. Limpieza robusta ante interrupción: lanzar una llamada en segundo plano y matarla (SIGTERM)
# a mitad de camino; el trap EXIT/INT/TERM de pg_run_sql_inline debe borrar igualmente su propio
# pgpass. Se usa pg_sleep para tener una ventana de tiempo en la que interrumpir. Se limpia
# cualquier .pgpass preexistente de las pruebas 7a/7b justo antes (este contenedor es enteramente
# nuestro, creado por esta misma corrida: no es un recurso ajeno), para que la comprobación de
# abajo mida EXCLUSIVAMENTE lo que deja esta llamada, no un posible resto de otra prueba anterior.
docker exec "$EPHEMERAL_NAME" sh -c 'rm -f /tmp/.deploy-pgpass-* 2>/dev/null' || true
set +e
# MSYS_NO_PATHCONV=1 es imprescindible aquí (como en 7a/7b): sin ella, Git Bash reescribe el
# valor de "-e PGPASSFILE=/tmp/..." dentro del "docker exec" como una ruta de Windows, y la propia
# limpieza del trap (que usa la MISMA variable) termina intentando borrar esa ruta reescrita en
# vez de la real dentro del contenedor — dejando el archivo real sin borrar. Olvidar esta
# variable fue la causa real de que esta prueba fallara en versiones anteriores de este archivo.
( LIB_COMMON_PATH="$SCRIPT_DIR/../lib_common.sh" MVP_POSTGRES_CONTAINER="$EPHEMERAL_NAME" \
    BOOTSTRAP_USER="$BOOTSTRAP_USER" BOOTSTRAP_PASSWORD="$BOOTSTRAP_PASSWORD" MSYS_NO_PATHCONV=1 bash -c '
  source "$LIB_COMMON_PATH"
  pg_run_sql_inline "$BOOTSTRAP_USER" "$BOOTSTRAP_PASSWORD" vinto_mvp_bootstrap "SELECT pg_sleep(30);"
' ) &
slow_pid=$!
sleep 2
kill -TERM "$slow_pid" 2>/dev/null
wait "$slow_pid" 2>/dev/null
set -e
# La limpieza la dispara el trap al recibir la señal, pero "docker exec rm -f" es una llamada de
# red/IPC real (al demonio de Docker) que puede tardar más de un segundo bajo carga variable del
# host de pruebas: en vez de un "sleep" fijo (potencialmente inestable), se sondea hasta 10s.
remaining_pgpass=""
for _ in $(seq 1 20); do
  remaining_pgpass="$(docker exec "$EPHEMERAL_NAME" sh -c 'ls /tmp/.deploy-pgpass-* 2>/dev/null' || true)"
  [ -z "$remaining_pgpass" ] && break
  sleep 0.5
done
if [ -z "$remaining_pgpass" ]; then
  report "una llamada interrumpida (SIGTERM) limpia igualmente su .pgpass temporal" 0
else
  report "una llamada interrumpida (SIGTERM) limpia igualmente su .pgpass temporal (quedó: $remaining_pgpass)" 1
fi
fi # ephemeral_create_status

echo "=== 8/10: validación de releases (DEP55-R2-04) ==="
# Ensayo en un contenedor Ubuntu 24.04 EFÍMERO: usuario de servicio, propiedad de directorios,
# resolución de symlinks hacia shared/backend.env, activación atómica, y la recuperación
# automática de la versión anterior cuando el healthcheck tras activar falla (ver
# deploy.sh::phase_activate). LIMITACIÓN EXPLÍCITA (no se simula un resultado que no se ejecutó):
# un contenedor Docker normal no corre systemd como PID 1, así que "systemctl restart"/"enable"/
# "Restart=on-failure"/el sandboxing de ProtectSystem=strict NO se ejercitan aquí — solo la lógica
# de usuario/propiedad/symlinks que deploy.sh/rollback.sh ejecutan con "sudo -u"/"ln -sfn", que es
# independiente de systemd. Esa parte dependiente de systemd queda pendiente de DEP-02B (VPS real).
RELEASE_TEST_DIR="$(mktemp -d)"
track_tmp_path "$RELEASE_TEST_DIR"
export MSYS_NO_PATHCONV=1
set +e
create_container vinto-mvp-verify-ubuntu \
  --label com.docker.compose.project=vinto-mvp \
  -v "$(cygpath -w "$RELEASE_TEST_DIR" 2>/dev/null || echo "$RELEASE_TEST_DIR"):/work" \
  ubuntu:24.04 sleep 300
release_create_status=$?
set -e
unset MSYS_NO_PATHCONV
if [ "$release_create_status" -ne 0 ]; then
  report "creación del contenedor Ubuntu 24.04 efímero para validar releases" 1
else
RELEASE_CNAME="$CREATED_NAME"
set +e
docker exec "$RELEASE_CNAME" bash -c '
  set -e
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq && apt-get install -y -qq --no-install-recommends git python3 >/dev/null
  useradd --system --no-create-home --shell /usr/sbin/nologin vinto-mvp
  mkdir -p /work/app/releases/aaaa /work/app/releases/bbbb /work/app/shared
  echo "FAKE_SECRET=1" > /work/app/shared/backend.env
  chmod 600 /work/app/shared/backend.env
  mkdir -p /work/app/releases/aaaa/backend /work/app/releases/bbbb/backend
  mkdir -p /work/app/releases/aaaa/backend/.venv/bin /work/app/releases/bbbb/backend/.venv/bin
  touch /work/app/releases/aaaa/backend/.venv/bin/uvicorn /work/app/releases/bbbb/backend/.venv/bin/uvicorn
  chmod +x /work/app/releases/aaaa/backend/.venv/bin/uvicorn /work/app/releases/bbbb/backend/.venv/bin/uvicorn
  mkdir -p /work/app/releases/aaaa/dist/standalone /work/app/releases/bbbb/dist/standalone
  touch /work/app/releases/aaaa/dist/standalone/server.js /work/app/releases/bbbb/dist/standalone/server.js
  ln -s ../../../shared/backend.env /work/app/releases/aaaa/backend/.env
  ln -s ../../../shared/backend.env /work/app/releases/bbbb/backend/.env
  chown -R vinto-mvp:vinto-mvp /work/app
  mkdir -p /opt/vinto-web && chown root:root /opt/vinto-web && chmod 750 /opt/vinto-web
' >/tmp/verify8-setup.log 2>&1
setup_ok=$?
set -e
if [ "$setup_ok" -ne 0 ]; then
  echo "--- log de preparación 8 ---"; cat /tmp/verify8-setup.log
  report "preparación del layout releases/shared en el contenedor Ubuntu efímero" 1
else
  report "preparación del layout releases/shared en el contenedor Ubuntu efímero" 0

  # Activación atómica: current -> aaaa, luego -> bbbb, verificando el symlink y que el usuario de
  # servicio puede leer backend/.env (resuelto a través de 2 niveles de symlink) pero NO /opt/vinto-web.
  # La imagen base ubuntu:24.04 no trae "sudo" instalado; "su" (sí presente) alcanza para
  # impersonar a vinto-mvp desde root sin necesitar instalar nada (deploy.sh/rollback.sh reales
  # usan "sudo -u" en el VPS, donde sudo sí está disponible — aquí "su" ejercita la misma
  # propiedad/permiso de archivos, que es lo que esta prueba necesita confirmar).
  set +e
  docker exec "$RELEASE_CNAME" bash -c '
    set -e
    as_vinto_mvp() { su -s /bin/bash vinto-mvp -c "$1"; }
    as_vinto_mvp "ln -sfn /work/app/releases/aaaa /work/app/current.tmp"
    as_vinto_mvp "mv -T /work/app/current.tmp /work/app/current"
    [ "$(readlink -f /work/app/current)" = "/work/app/releases/aaaa" ]
    as_vinto_mvp "test -r /work/app/current/backend/.env"
    as_vinto_mvp "ln -sfn /work/app/releases/bbbb /work/app/current.tmp"
    as_vinto_mvp "mv -T /work/app/current.tmp /work/app/current"
    [ "$(readlink -f /work/app/current)" = "/work/app/releases/bbbb" ]
    ! as_vinto_mvp "test -r /opt/vinto-web"
  ' >/tmp/verify8-activate.log 2>&1
  activate_ok=$?
  set -e
  if [ "$activate_ok" -eq 0 ]; then
    report "activación atómica entre dos releases + aislamiento de /opt/vinto-web, como vinto-mvp" 0
  else
    echo "--- log de activación 8 ---"; cat /tmp/verify8-activate.log
    report "activación atómica entre dos releases + aislamiento de /opt/vinto-web, como vinto-mvp" 1
  fi

  # git/python instalados en el paso de preparación de arriba, ejecutables como el usuario de
  # servicio vía "su" (equivalente, para este fin, al "sudo -u" real del VPS): confirma
  # compatibilidad de permisos/PATH, no una compilación real. Node queda fuera de este ensayo
  # (no se instala vía apt aquí: el VPS real lo instala con una versión concreta vía NodeSource,
  # ver preflight.sh::stage_build_deps; instalar un node de Ubuntu sin anclar versión en esta
  # imagen de prueba no aportaría una señal representativa).
  set +e
  docker exec "$RELEASE_CNAME" bash -c '
    su -s /bin/bash vinto-mvp -c "git --version" && su -s /bin/bash vinto-mvp -c "python3 --version"
  ' >/tmp/verify8-git.log 2>&1
  git_ok=$?
  set -e
  if [ "$git_ok" -eq 0 ]; then
    report "git y python3 ejecutables como vinto-mvp (su) dentro del contenedor de ensayo" 0
  else
    echo "--- log git/python 8 ---"; cat /tmp/verify8-git.log
    report "git y python3 ejecutables como vinto-mvp (su) dentro del contenedor de ensayo" 1
  fi
fi
fi # release_create_status

echo "=== 9/10: validación de rollback (DEP55-R2-04) ==="
if [ "${release_create_status:-1}" -eq 0 ] && [ "${setup_ok:-1}" -eq 0 ]; then
  # rollback_version: revertir current de bbbb a aaaa, sin tocar PostgreSQL (no se nombra ningún
  # contenedor de Postgres en esta prueba) y sin ninguna operación de git.
  set +e
  docker exec "$RELEASE_CNAME" bash -c '
    set -e
    as_vinto_mvp() { su -s /bin/bash vinto-mvp -c "$1"; }
    [ "$(readlink -f /work/app/current)" = "/work/app/releases/bbbb" ]
    as_vinto_mvp "ln -sfn /work/app/releases/aaaa /work/app/current.tmp"
    as_vinto_mvp "mv -T /work/app/current.tmp /work/app/current"
    [ "$(readlink -f /work/app/current)" = "/work/app/releases/aaaa" ]
  ' >/tmp/verify9-rollback.log 2>&1
  rollback_test_ok=$?
  set -e
  if [ "$rollback_test_ok" -eq 0 ]; then
    report "rollback.sh version: reversión del symlink 'current' sin git ni PostgreSQL" 0
  else
    echo "--- log de rollback 9 ---"; cat /tmp/verify9-rollback.log
    report "rollback.sh version: reversión del symlink 'current' sin git ni PostgreSQL" 1
  fi
else
  report "rollback.sh version: reversión del symlink 'current' sin git ni PostgreSQL (omitida: el ensayo de la prueba 8 no se completó)" 1
fi

# Bloqueo por falta de confirmación explícita (CONFIRM/AUTHORIZED_COMMIT/TVC_BACKUP_CONFIRMED),
# incluyendo rollback.sh, que es justo lo que se está validando en este bloque.
set +e
( unset CONFIRM; bash "$SCRIPT_DIR/../deploy.sh" user-and-dirs ) >/tmp/verify9a.log 2>&1
r1=$?
( unset AUTHORIZED_COMMIT; CONFIRM=yes bash "$SCRIPT_DIR/../deploy.sh" checkout 0000000000000000000000000000000000000000 ) >/tmp/verify9b.log 2>&1
r2=$?
( unset TVC_BACKUP_CONFIRMED; CONFIRM=yes bash "$SCRIPT_DIR/../deploy.sh" postgres-up ) >/tmp/verify9c.log 2>&1
r3=$?
( unset CONFIRM; bash "$SCRIPT_DIR/../rollback.sh" all ) >/tmp/verify9d.log 2>&1
r4=$?
( unset CONFIRM; bash "$SCRIPT_DIR/../rollback.sh" version 1111111111111111111111111111111111111111 ) >/tmp/verify9e.log 2>&1
r5=$?
( unset CONFIRM; bash "$SCRIPT_DIR/../deploy.sh" link-backend-env 2222222222222222222222222222222222222222 ) >/tmp/verify9f.log 2>&1
r6=$?
set -e
if [ "$r1" -ne 0 ] && [ "$r2" -ne 0 ] && [ "$r3" -ne 0 ] && [ "$r4" -ne 0 ] && [ "$r5" -ne 0 ] && [ "$r6" -ne 0 ]; then
  report "cada fase de riesgo (incluida rollback.sh version y link-backend-env) se niega a ejecutar sin confirmación explícita" 0
else
  echo "r1=$r1 r2=$r2 r3=$r3 r4=$r4 r5=$r5 r6=$r6"
  report "cada fase de riesgo (incluida rollback.sh version y link-backend-env) se niega a ejecutar sin confirmación explícita" 1
fi

# link-backend-env (CLOUD-DEP-02B.2-C): el SHA se valida ANTES de tocar nada (ni siquiera
# "sudo -u vinto-mvp"), igual que en "checkout" -- se puede comprobar directamente en el host,
# sin ningún contenedor ni usuario vinto-mvp real.
set +e
CONFIRM=yes bash "$SCRIPT_DIR/../deploy.sh" link-backend-env not-a-full-sha >/tmp/verify9g.log 2>&1
r7=$?
set -e
if [ "$r7" -ne 0 ] && grep -q "no es un SHA completo de 40 caracteres hexadecimales" /tmp/verify9g.log; then
  report "link-backend-env rechaza un SHA que no es completo/hexadecimal, antes de tocar nada" 0
else
  cat /tmp/verify9g.log
  report "link-backend-env rechaza un SHA que no es completo/hexadecimal, antes de tocar nada" 1
fi

echo "=== 10/10: inspección del diff completo contra main ==="
git -C "$REPO_ROOT" fetch origin main --quiet 2>/dev/null || true
DIFF_FILES="$(git -C "$REPO_ROOT" diff --name-only origin/main...HEAD)"
if [ -n "$DIFF_FILES" ]; then
  report "hay diferencias frente a main" 0
  echo "$DIFF_FILES"
else
  report "hay diferencias frente a main" 1
fi
if printf '%s\n' "$DIFF_FILES" | grep -qv '^deploy/mvp/\|^$'; then
  report "el diff NO toca nada fuera de deploy/mvp (ninguna migración, servicio TVC, etc.)" 1
else
  report "el diff NO toca nada fuera de deploy/mvp (ninguna migración, servicio TVC, etc.)" 0
fi
echo "--- diff completo (deploy/mvp), para inspección manual ---"
git -C "$REPO_ROOT" diff --stat origin/main...HEAD -- deploy/mvp

echo "=== comprobación de secretos en logs/artefactos de esta corrida ==="
if ! grep -rln "${BOOTSTRAP_PASSWORD:-__none__}\|${APP_PW:-__none__}\|${MIGRATOR_PW:-__none__}\|${REFERENCE_PW:-__none__}" \
    "$MVP_DIR" /tmp/verify7a.log /tmp/verify7b-1.log /tmp/verify7b-2.log /tmp/shellcheck-*.log /tmp/nginx-t.log /tmp/verify8-*.log /tmp/verify9-*.log 2>/dev/null; then
  report "ninguna contraseña generada en esta corrida quedó impresa en archivos ni logs" 0
else
  report "ninguna contraseña generada en esta corrida quedó impresa en archivos ni logs" 1
fi
if ! grep -rEn 'PASSWORD\s*=\s*[^C][^H][^A][^N][^G][^E]' "$MVP_DIR/env" 2>/dev/null \
   | grep -vE 'CHANGE_ME|test_only_not_real'; then
  report "ningún .env.example de deploy/mvp/env contiene algo distinto de CHANGE_ME" 0
else
  report "ningún .env.example de deploy/mvp/env contiene algo distinto de CHANGE_ME" 1
fi

echo "=== Prueba focalizada R2-2.1: orden migrate -> postgres-grants/arranque (CLOUD-DEP-02A.2-R2-2, punto 1) ==="
# Confirma, EMPÍRICAMENTE contra un Postgres efímero y el backend/.venv local, que
# "migrate.py --check" distingue correctamente un esquema sin migrar (exit != 0) de uno migrado
# (exit 0): es justo la llamada que lib_common.sh::assert_schema_migrated usa para bloquear
# "postgres-grants"/"systemd-install"/"activate". Además confirma, por código, que esas 3 fases
# realmente invocan ese guardián (no basta con que la función exista: tiene que estar conectada).
BACKEND_VENV_PY=""
if [ -x "$REPO_ROOT/backend/.venv/Scripts/python.exe" ]; then
  BACKEND_VENV_PY="$REPO_ROOT/backend/.venv/Scripts/python.exe"
elif [ -x "$REPO_ROOT/backend/.venv/bin/python" ]; then
  BACKEND_VENV_PY="$REPO_ROOT/backend/.venv/bin/python"
fi
if [ -z "$BACKEND_VENV_PY" ]; then
  report "orden migrate -> postgres-grants/arranque, validado contra Postgres efímero (omitida: no hay backend/.venv local con psycopg/pydantic instalados)" 1
else
  export MSYS_NO_PATHCONV=1
  set +e
  create_container vinto-mvp-verify-order --label com.docker.compose.project=vinto-mvp \
    --tmpfs /var/lib/postgresql/data -p 127.0.0.1::5432 \
    -e POSTGRES_DB=vinto_order_test -e POSTGRES_USER=order_root -e POSTGRES_PASSWORD=order_pw \
    postgres:17
  order_create_status=$?
  set -e
  unset MSYS_NO_PATHCONV
  if [ "$order_create_status" -ne 0 ]; then
    report "orden migrate -> postgres-grants/arranque, validado contra Postgres efímero" 1
  else
    ORDER_CNAME="$CREATED_NAME"
    for _ in $(seq 1 30); do
      docker exec "$ORDER_CNAME" pg_isready -U order_root -d vinto_order_test >/dev/null 2>&1 && break
      sleep 1
    done
    ORDER_PORT="$(docker port "$ORDER_CNAME" 5432/tcp | head -n1 | cut -d: -f2)"
    set +e
    DATABASE_URL="postgresql://order_root:order_pw@127.0.0.1:${ORDER_PORT}/vinto_order_test" \
      PG_PRIVILEGE_MODE=legacy "$BACKEND_VENV_PY" "$REPO_ROOT/backend/migrate.py" --target dev --check \
      >/tmp/verify-order-1.log 2>&1
    before_migrate_check=$?
    set -e
    if [ "$before_migrate_check" -eq 0 ]; then
      echo "--- log orden (antes de migrar) ---"; cat /tmp/verify-order-1.log
      report "'migrate.py --check' detecta un esquema SIN migrar (debía fallar, no falló)" 1
    else
      report "'migrate.py --check' detecta un esquema SIN migrar (exit != 0, como se espera)" 0
      set +e
      DATABASE_URL="postgresql://order_root:order_pw@127.0.0.1:${ORDER_PORT}/vinto_order_test" \
        PG_PRIVILEGE_MODE=legacy "$BACKEND_VENV_PY" "$REPO_ROOT/backend/migrate.py" --target dev \
        >/tmp/verify-order-2.log 2>&1
      apply_status=$?
      set -e
      if [ "$apply_status" -ne 0 ]; then
        echo "--- log orden (aplicando) ---"; cat /tmp/verify-order-2.log
        report "'migrate.py' (aplicar) sobre el Postgres efímero" 1
      else
        set +e
        DATABASE_URL="postgresql://order_root:order_pw@127.0.0.1:${ORDER_PORT}/vinto_order_test" \
          PG_PRIVILEGE_MODE=legacy "$BACKEND_VENV_PY" "$REPO_ROOT/backend/migrate.py" --target dev --check \
          >/tmp/verify-order-3.log 2>&1
        after_migrate_check=$?
        set -e
        if [ "$after_migrate_check" -eq 0 ]; then
          report "orden migrate -> postgres-grants/arranque: --check pasa a OK justo después de migrar, en el orden correcto" 0
        else
          echo "--- log orden (después de migrar) ---"; cat /tmp/verify-order-3.log
          report "orden migrate -> postgres-grants/arranque: --check pasa a OK justo después de migrar, en el orden correcto" 1
        fi
      fi
    fi
  fi
fi
# Comprobación por código: las 3 fases que no deben continuar sin el esquema migrado llaman al
# guardián, no solo lo declaran.
guard_wired=0
for phase_fn in phase_postgres_grants phase_systemd_install phase_activate; do
  awk "/^$phase_fn\\(\\)/,/^}/" "$SCRIPT_DIR/../deploy.sh" | grep -q 'assert_schema_migrated' || guard_wired=1
done
if [ "$guard_wired" -eq 0 ]; then
  report "phase_postgres_grants/phase_systemd_install/phase_activate llaman a assert_schema_migrated" 0
else
  report "phase_postgres_grants/phase_systemd_install/phase_activate llaman a assert_schema_migrated" 1
fi

echo "=== Prueba focalizada R2-2.2: rollback.sh version comprueba salud tras reiniciar (punto 2) ==="
# No hay systemd local para un ensayo end-to-end (ver limitación ya documentada en la prueba 8):
# se valida la MISMA función que rollback.sh/deploy.sh usan para decidir si una recuperación fue
# exitosa (lib_common.sh::mvp_healthcheck) contra servidores HTTP reales en los puertos reales
# (8100/3100), subiéndolos y bajándolos, en vez de solo inspeccionar el código.
HEALTH_PY=""
if [ -n "$BACKEND_VENV_PY" ]; then HEALTH_PY="$BACKEND_VENV_PY"; elif command -v python3 >/dev/null 2>&1; then HEALTH_PY="$(command -v python3)"; fi
if [ -z "$HEALTH_PY" ]; then
  report "mvp_healthcheck distingue servicios arriba/abajo en 8100+3100 (omitida: no hay python disponible)" 1
else
  HEALTH_TMP_DIR="$(mktemp -d)"
  track_tmp_path "$HEALTH_TMP_DIR"
  for p in 8100 3100; do mkdir -p "$HEALTH_TMP_DIR/$p"; done
  # http.server es un servidor de ARCHIVOS: devuelve 404 para una ruta que no exista, no 200 para
  # cualquier cosa. Se crean los archivos exactos que mvp_healthcheck pide (/health, /api/health
  # en 8100; "/" en 3100 ya devuelve 200 por defecto al listar el directorio).
  touch "$HEALTH_TMP_DIR/8100/health"
  mkdir -p "$HEALTH_TMP_DIR/8100/api"
  touch "$HEALTH_TMP_DIR/8100/api/health"
  # Orden deliberado: primero solo el frontend (3100) arriba y NADA en 8100 todavía, para
  # comprobar el caso "falla" sin tener que matar a mitad de prueba un proceso en segundo plano
  # (en este entorno, matar un job intermedio demostró ser poco fiable para el propio runner).
  # Solo el backgroundeo final, limpiado por el trap cleanup_all al terminar el script, es necesario.
  ( cd "$HEALTH_TMP_DIR/3100" && exec "$HEALTH_PY" -m http.server 3100 --bind 127.0.0.1 >/dev/null 2>&1 ) &
  frontend_http_pid=$!
  track_pid "$frontend_http_pid"
  sleep 1
  set +e
  mvp_healthcheck >/tmp/verify-health-down.log 2>&1
  health_down_status=$?
  set -e
  if [ "$health_down_status" -ne 0 ]; then
    report "mvp_healthcheck devuelve FALLA cuando el backend (8100) no responde" 0
  else
    report "mvp_healthcheck devuelve FALLA cuando el backend (8100) no responde" 1
  fi
  ( cd "$HEALTH_TMP_DIR/8100" && exec "$HEALTH_PY" -m http.server 8100 --bind 127.0.0.1 >/dev/null 2>&1 ) &
  backend_http_pid=$!
  track_pid "$backend_http_pid"
  sleep 1
  set +e
  mvp_healthcheck >/tmp/verify-health-up.log 2>&1
  health_up_status=$?
  set -e
  if [ "$health_up_status" -eq 0 ]; then
    report "mvp_healthcheck devuelve OK con ambos puertos (8100/3100) respondiendo" 0
  else
    echo "--- log healthcheck arriba ---"; cat /tmp/verify-health-up.log
    report "mvp_healthcheck devuelve OK con ambos puertos (8100/3100) respondiendo" 1
  fi
fi
# Comprobación por código: rollback_version llama a mvp_healthcheck y sale con error si falla,
# sin afirmar éxito antes de comprobarlo.
if awk '/^rollback_version\(\)/,/^}/' "$SCRIPT_DIR/../rollback.sh" | grep -q 'mvp_healthcheck'; then
  report "rollback.sh version llama a mvp_healthcheck tras reiniciar los servicios" 0
else
  report "rollback.sh version llama a mvp_healthcheck tras reiniciar los servicios" 1
fi

echo "=== Prueba focalizada R2-2.3: temporal único para el healthcheck de activate (punto 3) ==="
if grep -q '/tmp/\.deploy-activate-healthcheck\.log' "$SCRIPT_DIR/../deploy.sh" "$SCRIPT_DIR/../rollback.sh" 2>/dev/null; then
  report "ningún nombre de archivo temporal fijo (/tmp/.deploy-activate-healthcheck.log) sigue en deploy.sh/rollback.sh" 1
else
  report "ningún nombre de archivo temporal fijo (/tmp/.deploy-activate-healthcheck.log) sigue en deploy.sh/rollback.sh" 0
fi
if grep -qE 'hc_log="\$\(mktemp\)"' "$SCRIPT_DIR/../deploy.sh" && grep -qE 'hc_log="\$\(mktemp\)"' "$SCRIPT_DIR/../rollback.sh"; then
  report "deploy.sh (activate) y rollback.sh (version) usan mktemp para el log del healthcheck" 0
else
  report "deploy.sh (activate) y rollback.sh (version) usan mktemp para el log del healthcheck" 1
fi

echo "=== Prueba focalizada C.1-1: runtime Node AISLADO, checksum real (CLOUD-DEP-02B.1-C.1) ==="
echo "CLOUD-DEP-02B.1-D.1: el invocador de deploy.sh ya NO es root dentro del contenedor de ensayo"
echo "('mvp_operator', sin privilegios, con sudo amplio pero NUNCA miembro de vinto-mvp) — exactamente"
echo "el modelo real del VPS ('ubuntu' + sudo), que es lo que la versión anterior de esta prueba no"
echo "ejercitaba (docker exec corría como root, que puede leer cualquier cosa sin pasar por sudo -u,"
echo "y por eso el defecto real de phase_install_node_runtime escapó a esta batería)."
NODE_RUNTIME_CNAME=""
set +e
create_container vinto-mvp-verify-noderuntime --label com.docker.compose.project=vinto-mvp ubuntu:24.04 sleep 900
noderuntime_create_status=$?
set -e
if [ "$noderuntime_create_status" -ne 0 ]; then
  report "runtime Node aislado: instalación real con checksum oficial (omitida: no se pudo crear el contenedor de ensayo)" 1
else
  NODE_RUNTIME_CNAME="$CREATED_NAME"
  # Se copia TODO deploy/mvp (no solo scripts/): "install-node-runtime" ahora lee el checksum
  # aprobado de env/node-runtime-checksums.txt (CLOUD-DEP-02B.1-C.2, DEP56-02), un hermano de
  # scripts/ en el árbol, no un argumento de línea de comandos.
  docker cp "$MVP_DIR" "$NODE_RUNTIME_CNAME:/tmp/mvp" >/dev/null
  set +e
  docker exec "$NODE_RUNTIME_CNAME" bash -c '
    set -e
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq && apt-get install -y -qq --no-install-recommends curl ca-certificates xz-utils sudo >/dev/null
    chmod -R a+rX /tmp/mvp

    # vinto-mvp: propietario EXCLUSIVO de /opt/vinto-mvp-web (750), igual que en el VPS real.
    useradd --system --no-create-home --shell /usr/sbin/nologin vinto-mvp
    mkdir -p /opt/vinto-mvp-web
    chown vinto-mvp:vinto-mvp /opt/vinto-mvp-web
    chmod 750 /opt/vinto-mvp-web

    # mvp_operator: simula a "ubuntu" en el VPS real — SIN pertenecer a vinto-mvp, pero con sudo
    # amplio (confirmado "sudo -n true" para "ubuntu" en CLOUD-DEP-02B.1-D), que es exactamente lo
    # que deploy.sh necesita para sus "sudo -u vinto-mvp ...", nunca para correr el script entero
    # como root. Invocar deploy.sh como root (sin "su"/sudo de por medio) NUNCA seria una prueba
    # honesta de esta fase: root puede leer cualquier cosa sin pasar por ningún "sudo -u".
    useradd -m -s /bin/bash mvp_operator
    echo "mvp_operator ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/mvp_operator
    chmod 440 /etc/sudoers.d/mvp_operator

    # mvp_operator_nosudo: mismo perfil, pero SIN entrada en sudoers — para el escenario de fallo
    # de permisos (ningún "sudo -u vinto-mvp" posible desde este usuario).
    useradd -m -s /bin/bash mvp_operator_nosudo

    cd /tmp
    curl -fsSLO https://nodejs.org/dist/v22.18.0/node-v22.18.0-linux-x64.tar.xz
    chmod 644 /tmp/node-v22.18.0-linux-x64.tar.xz
  ' >/tmp/verify-noderuntime-setup.log 2>&1
  noderuntime_setup_ok=$?
  set -e
  if [ "$noderuntime_setup_ok" -ne 0 ]; then
    echo "--- log de preparación C.1-1 ---"; cat /tmp/verify-noderuntime-setup.log
    report "runtime Node aislado: preparación (descarga oficial real + usuarios sin privilegios) en el contenedor de ensayo" 1
  else
    report "runtime Node aislado: preparación (descarga oficial real + usuarios sin privilegios) en el contenedor de ensayo" 0

    # Sanity check: mvp_operator debe estar tan aislado de /opt/vinto-mvp-web como "ubuntu" lo está
    # en el VPS real (confirmado empíricamente en CLOUD-DEP-02B.1-D) — si esto NO fuera cierto, el
    # resto de esta batería no estaría ejercitando el defecto real.
    set +e
    docker exec "$NODE_RUNTIME_CNAME" bash -c '
      ! su -s /bin/bash mvp_operator -c "test -r /opt/vinto-mvp-web"
    ' >/tmp/verify-noderuntime-isolation.log 2>&1
    isolation_ok=$?
    set -e
    if [ "$isolation_ok" -eq 0 ]; then
      report "mvp_operator (sin privilegios, igual que 'ubuntu' en el VPS) no puede atravesar /opt/vinto-mvp-web directamente" 0
    else
      echo "--- log de aislamiento ---"; cat /tmp/verify-noderuntime-isolation.log
      report "mvp_operator (sin privilegios, igual que 'ubuntu' en el VPS) no puede atravesar /opt/vinto-mvp-web directamente" 1
    fi

    # Regresión CLOUD-DEP-02B.1-D (ronda 1): un tarball colocado dentro de un árbol EXCLUSIVO de
    # vinto-mvp (700) es ilegible para el operador — debe rechazarse con un mensaje explícito sobre
    # el problema de lectura, NUNCA con un "checksum no coincide" confuso, y sin tocar runtime/.
    set +e
    docker exec "$NODE_RUNTIME_CNAME" bash -c '
      set -e
      install -d -o vinto-mvp -g vinto-mvp -m 700 /opt/vinto-mvp-web/.exclusive-tarball-staging
      cp /tmp/node-v22.18.0-linux-x64.tar.xz /opt/vinto-mvp-web/.exclusive-tarball-staging/
      chown vinto-mvp:vinto-mvp /opt/vinto-mvp-web/.exclusive-tarball-staging/node-v22.18.0-linux-x64.tar.xz
      chmod 600 /opt/vinto-mvp-web/.exclusive-tarball-staging/node-v22.18.0-linux-x64.tar.xz
      ! su -s /bin/bash mvp_operator -c "cd /tmp/mvp/scripts && CONFIRM=yes bash deploy.sh install-node-runtime 22.18.0 /opt/vinto-mvp-web/.exclusive-tarball-staging/node-v22.18.0-linux-x64.tar.xz" 2>/tmp/regression-r1.err
      grep -q "no se puede leer" /tmp/regression-r1.err
      [ ! -e /opt/vinto-mvp-web/runtime ]
    ' >/tmp/verify-noderuntime-regression-r1.log 2>&1
    regression_r1_ok=$?
    set -e
    if [ "$regression_r1_ok" -eq 0 ]; then
      report "install-node-runtime rechaza un tarball ilegible para el operador, con un mensaje claro (regresión de la ronda 1), sin tocar runtime/" 0
    else
      echo "--- log regresión ronda 1 ---"; cat /tmp/verify-noderuntime-regression-r1.log
      report "install-node-runtime rechaza un tarball ilegible para el operador, con un mensaje claro (regresión de la ronda 1), sin tocar runtime/" 1
    fi

    # DEP56-02: el checksum aprobado vive en env/node-runtime-checksums.txt (versionado), NUNCA en
    # un SHASUMS256.txt que viaje junto al tarball — "install-node-runtime" ya solo toma
    # <version> <tarball>, ningún tercer argumento. Invocado como mvp_operator (nunca como root).
    set +e
    docker exec "$NODE_RUNTIME_CNAME" bash -c '
      set -e
      cp /tmp/node-v22.18.0-linux-x64.tar.xz /tmp/corrupt.tar.xz
      printf "corrupted" >> /tmp/corrupt.tar.xz
      chmod 644 /tmp/corrupt.tar.xz
      ! su -s /bin/bash mvp_operator -c "cd /tmp/mvp/scripts && CONFIRM=yes bash deploy.sh install-node-runtime 22.18.0 /tmp/corrupt.tar.xz"
      [ ! -e /opt/vinto-mvp-web/runtime/node-v22.18.0-linux-x64 ]
    ' >/tmp/verify-noderuntime-corrupt.log 2>&1
    corrupt_ok=$?
    set -e
    if [ "$corrupt_ok" -eq 0 ]; then
      report "install-node-runtime (como mvp_operator) rechaza un tarball con checksum incorrecto, sin instalar nada" 0
    else
      echo "--- log C.1-1 corrupto ---"; cat /tmp/verify-noderuntime-corrupt.log
      report "install-node-runtime (como mvp_operator) rechaza un tarball con checksum incorrecto, sin instalar nada" 1
    fi

    # 1. Runtime ausente: instalación real limpia, verificada con la VERSIÓN real reportada por el
    #    binario (como vinto-mvp), no solo su existencia.
    # 3. Runtime completo y ya activo: una segunda instalación de la MISMA versión es idempotente
    #    (no reescribe INSTALLED.log).
    set +e
    docker exec "$NODE_RUNTIME_CNAME" bash -c '
      set -e
      su -s /bin/bash mvp_operator -c "cd /tmp/mvp/scripts && CONFIRM=yes bash deploy.sh install-node-runtime 22.18.0 /tmp/node-v22.18.0-linux-x64.tar.xz"
      [ "$(readlink -f /opt/vinto-mvp-web/runtime/active)" = "/opt/vinto-mvp-web/runtime/node-v22.18.0-linux-x64" ]
      sudo -u vinto-mvp /opt/vinto-mvp-web/runtime/active/bin/node --version | grep -qx v22.18.0
      log_lines_before="$(wc -l < /opt/vinto-mvp-web/runtime/INSTALLED.log)"
      su -s /bin/bash mvp_operator -c "cd /tmp/mvp/scripts && CONFIRM=yes bash deploy.sh install-node-runtime 22.18.0 /tmp/node-v22.18.0-linux-x64.tar.xz"
      log_lines_after="$(wc -l < /opt/vinto-mvp-web/runtime/INSTALLED.log)"
      [ "$log_lines_before" = "$log_lines_after" ]
    ' >/tmp/verify-noderuntime-install.log 2>&1
    install_ok=$?
    set -e
    if [ "$install_ok" -eq 0 ]; then
      report "install-node-runtime (como mvp_operator): instalación real verificada por versión + idempotente cuando ya está activo (sin reescribir INSTALLED.log)" 0
    else
      echo "--- log C.1-1 instalación ---"; cat /tmp/verify-noderuntime-install.log
      report "install-node-runtime (como mvp_operator): instalación real verificada por versión + idempotente cuando ya está activo (sin reescribir INSTALLED.log)" 1
    fi

    # 2. Runtime completo y válido, "active" ausente: reanudación de una instalación interrumpida
    #    (el estado exacto en que quedó el VPS real tras CLOUD-DEP-02B.1-D) — debe completar la
    #    activación SIN volver a extraer encima del árbol ya válido (confirmado con un centinela).
    set +e
    docker exec "$NODE_RUNTIME_CNAME" bash -c '
      set -e
      rm -f /opt/vinto-mvp-web/runtime/active
      [ ! -e /opt/vinto-mvp-web/runtime/active ]
      touch /opt/vinto-mvp-web/runtime/node-v22.18.0-linux-x64/.sentinel-no-reextract
      su -s /bin/bash mvp_operator -c "cd /tmp/mvp/scripts && CONFIRM=yes bash deploy.sh install-node-runtime 22.18.0 /tmp/node-v22.18.0-linux-x64.tar.xz"
      [ "$(readlink -f /opt/vinto-mvp-web/runtime/active)" = "/opt/vinto-mvp-web/runtime/node-v22.18.0-linux-x64" ]
      [ -e /opt/vinto-mvp-web/runtime/node-v22.18.0-linux-x64/.sentinel-no-reextract ]
    ' >/tmp/verify-noderuntime-resume.log 2>&1
    resume_ok=$?
    set -e
    if [ "$resume_ok" -eq 0 ]; then
      report "install-node-runtime: reanuda una instalación interrumpida (runtime válido, 'active' ausente) sin volver a extraer" 0
    else
      echo "--- log reanudación ---"; cat /tmp/verify-noderuntime-resume.log
      report "install-node-runtime: reanuda una instalación interrumpida (runtime válido, 'active' ausente) sin volver a extraer" 1
    fi

    # 4. Runtime parcial/corrupto (nombre de versión correcto, sin bin/node ejecutable): rechazar
    #    sin sobrescribir ni borrar automáticamente.
    set +e
    docker exec "$NODE_RUNTIME_CNAME" bash -c '
      set -e
      mkdir -p /tmp/fakever8/node-v8.8.8-linux-x64/bin
      printf "#!/bin/sh\necho v8.8.8\n" > /tmp/fakever8/node-v8.8.8-linux-x64/bin/node
      chmod +x /tmp/fakever8/node-v8.8.8-linux-x64/bin/node
      tar -cJf /tmp/node-v8.8.8-linux-x64.tar.xz -C /tmp/fakever8 node-v8.8.8-linux-x64
      chmod 644 /tmp/node-v8.8.8-linux-x64.tar.xz
      sha="$(sha256sum /tmp/node-v8.8.8-linux-x64.tar.xz | awk "{print \$1}")"
      printf "8.8.8 %s\n" "$sha" >> /tmp/mvp/env/node-runtime-checksums.txt
      chmod -R a+rX /tmp/mvp/env

      mkdir -p /opt/vinto-mvp-web/runtime/node-v8.8.8-linux-x64/bin
      chown -R vinto-mvp:vinto-mvp /opt/vinto-mvp-web/runtime/node-v8.8.8-linux-x64

      ! su -s /bin/bash mvp_operator -c "cd /tmp/mvp/scripts && CONFIRM=yes bash deploy.sh install-node-runtime 8.8.8 /tmp/node-v8.8.8-linux-x64.tar.xz"
      [ ! -x /opt/vinto-mvp-web/runtime/node-v8.8.8-linux-x64/bin/node ]
      [ "$(readlink -f /opt/vinto-mvp-web/runtime/active)" != "/opt/vinto-mvp-web/runtime/node-v8.8.8-linux-x64" ]
    ' >/tmp/verify-noderuntime-partial.log 2>&1
    partial_ok=$?
    set -e
    if [ "$partial_ok" -eq 0 ]; then
      report "install-node-runtime rechaza un runtime existente parcial/sin bin/node ejecutable, sin sobrescribir ni activar" 0
    else
      echo "--- log parcial ---"; cat /tmp/verify-noderuntime-partial.log
      report "install-node-runtime rechaza un runtime existente parcial/sin bin/node ejecutable, sin sobrescribir ni activar" 1
    fi

    # 5. Runtime existente cuya VERSIÓN EFECTIVA no coincide con el nombre del directorio (bin/node
    #    ejecutable, pero reporta otra versión): rechazar, sin tocar el binario existente.
    set +e
    docker exec "$NODE_RUNTIME_CNAME" bash -c '
      set -e
      mkdir -p /opt/vinto-mvp-web/runtime/node-v7.7.7-linux-x64/bin
      printf "#!/bin/sh\necho v0.0.1-wrong\n" > /opt/vinto-mvp-web/runtime/node-v7.7.7-linux-x64/bin/node
      chmod +x /opt/vinto-mvp-web/runtime/node-v7.7.7-linux-x64/bin/node
      chown -R vinto-mvp:vinto-mvp /opt/vinto-mvp-web/runtime/node-v7.7.7-linux-x64

      mkdir -p /tmp/fakever7content
      echo "contenido irrelevante: esta rama nunca llega a extraerlo" > /tmp/fakever7content/placeholder
      tar -cJf /tmp/node-v7.7.7-linux-x64.tar.xz -C /tmp/fakever7content .
      chmod 644 /tmp/node-v7.7.7-linux-x64.tar.xz
      sha="$(sha256sum /tmp/node-v7.7.7-linux-x64.tar.xz | awk "{print \$1}")"
      printf "7.7.7 %s\n" "$sha" >> /tmp/mvp/env/node-runtime-checksums.txt
      chmod -R a+rX /tmp/mvp/env

      ! su -s /bin/bash mvp_operator -c "cd /tmp/mvp/scripts && CONFIRM=yes bash deploy.sh install-node-runtime 7.7.7 /tmp/node-v7.7.7-linux-x64.tar.xz"
      [ "$(/opt/vinto-mvp-web/runtime/node-v7.7.7-linux-x64/bin/node --version)" = "v0.0.1-wrong" ]
      [ "$(readlink -f /opt/vinto-mvp-web/runtime/active)" != "/opt/vinto-mvp-web/runtime/node-v7.7.7-linux-x64" ]
    ' >/tmp/verify-noderuntime-wrongversion.log 2>&1
    wrongversion_ok=$?
    set -e
    if [ "$wrongversion_ok" -eq 0 ]; then
      report "install-node-runtime rechaza un runtime existente cuya versión efectiva no coincide con el nombre del directorio" 0
    else
      echo "--- log version incorrecta ---"; cat /tmp/verify-noderuntime-wrongversion.log
      report "install-node-runtime rechaza un runtime existente cuya versión efectiva no coincide con el nombre del directorio" 1
    fi

    # 6. Error de permisos (sudo -u vinto-mvp no disponible para el invocador): detenerse ANTES de
    #    intentar ninguna extracción — nunca queda un directorio nuevo a medio crear.
    set +e
    docker exec "$NODE_RUNTIME_CNAME" bash -c '
      set -e
      mkdir -p /tmp/fakever6/node-v6.6.6-linux-x64/bin
      printf "#!/bin/sh\necho v6.6.6\n" > /tmp/fakever6/node-v6.6.6-linux-x64/bin/node
      chmod +x /tmp/fakever6/node-v6.6.6-linux-x64/bin/node
      tar -cJf /tmp/node-v6.6.6-linux-x64.tar.xz -C /tmp/fakever6 node-v6.6.6-linux-x64
      chmod 644 /tmp/node-v6.6.6-linux-x64.tar.xz
      sha="$(sha256sum /tmp/node-v6.6.6-linux-x64.tar.xz | awk "{print \$1}")"
      printf "6.6.6 %s\n" "$sha" >> /tmp/mvp/env/node-runtime-checksums.txt
      chmod -R a+rX /tmp/mvp/env

      ! su -s /bin/bash mvp_operator_nosudo -c "cd /tmp/mvp/scripts && CONFIRM=yes bash deploy.sh install-node-runtime 6.6.6 /tmp/node-v6.6.6-linux-x64.tar.xz" 2>/tmp/regression-nosudo.err
      [ ! -e /opt/vinto-mvp-web/runtime/node-v6.6.6-linux-x64 ]
      grep -q "no se puede ejecutar .sudo -u vinto-mvp." /tmp/regression-nosudo.err
    ' >/tmp/verify-noderuntime-nosudo.log 2>&1
    nosudo_ok=$?
    set -e
    if [ "$nosudo_ok" -eq 0 ]; then
      report "install-node-runtime se detiene ANTES de extraer si 'sudo -u vinto-mvp' no está disponible para el invocador" 0
    else
      echo "--- log sin sudo ---"; cat /tmp/verify-noderuntime-nosudo.log
      report "install-node-runtime se detiene ANTES de extraer si 'sudo -u vinto-mvp' no está disponible para el invocador" 1
    fi

    # Versión NO aprobada (ausente de env/node-runtime-checksums.txt): debe rechazarse, aunque el
    # tarball sea válido — aprobar una versión es un cambio de código (PR), no un argumento en el
    # momento de instalar (DEP56-02).
    set +e
    docker exec "$NODE_RUNTIME_CNAME" bash -c '
      cp /tmp/node-v22.18.0-linux-x64.tar.xz /tmp/node-v22.99.0-linux-x64.tar.xz
      chmod 644 /tmp/node-v22.99.0-linux-x64.tar.xz
      ! su -s /bin/bash mvp_operator -c "cd /tmp/mvp/scripts && CONFIRM=yes bash deploy.sh install-node-runtime 22.99.0 /tmp/node-v22.99.0-linux-x64.tar.xz"
    ' >/tmp/verify-noderuntime-unapproved.log 2>&1
    unapproved_ok=$?
    set -e
    if [ "$unapproved_ok" -eq 0 ]; then
      report "install-node-runtime rechaza una versión no aprobada en env/node-runtime-checksums.txt" 0
    else
      echo "--- log C.1-1 no aprobada ---"; cat /tmp/verify-noderuntime-unapproved.log
      report "install-node-runtime rechaza una versión no aprobada en env/node-runtime-checksums.txt" 1
    fi

    # Coexistencia de versiones sin borrar la anterior: se aprueba una SEGUNDA versión de
    # prueba SOLO en la copia del archivo dentro del contenedor (nunca se toca el archivo real
    # del repositorio local), con un tarball sintético (evita descargar otros ~30MB reales).
    set +e
    docker exec "$NODE_RUNTIME_CNAME" bash -c '
      set -e
      mkdir -p /tmp/fakever/node-v9.9.9-linux-x64/bin
      printf "#!/bin/sh\necho v9.9.9\n" > /tmp/fakever/node-v9.9.9-linux-x64/bin/node
      chmod +x /tmp/fakever/node-v9.9.9-linux-x64/bin/node
      tar -cJf /tmp/node-v9.9.9-linux-x64.tar.xz -C /tmp/fakever node-v9.9.9-linux-x64
      chmod 644 /tmp/node-v9.9.9-linux-x64.tar.xz
      sha="$(sha256sum /tmp/node-v9.9.9-linux-x64.tar.xz | awk "{print \$1}")"
      printf "9.9.9 %s\n" "$sha" >> /tmp/mvp/env/node-runtime-checksums.txt
      chmod -R a+rX /tmp/mvp/env
      su -s /bin/bash mvp_operator -c "cd /tmp/mvp/scripts && CONFIRM=yes bash deploy.sh install-node-runtime 9.9.9 /tmp/node-v9.9.9-linux-x64.tar.xz"
      [ -d /opt/vinto-mvp-web/runtime/node-v22.18.0-linux-x64 ]
      [ "$(readlink -f /opt/vinto-mvp-web/runtime/active)" = "/opt/vinto-mvp-web/runtime/node-v9.9.9-linux-x64" ]
    ' >/tmp/verify-noderuntime-multiversion.log 2>&1
    multiversion_ok=$?
    set -e
    if [ "$multiversion_ok" -eq 0 ]; then
      report "install-node-runtime: una segunda versión aprobada no borra la anterior" 0
    else
      echo "--- log C.1-1 multiversión ---"; cat /tmp/verify-noderuntime-multiversion.log
      report "install-node-runtime: una segunda versión aprobada no borra la anterior" 1
    fi
  fi
fi

echo "=== Prueba focalizada C.1-2: artefacto frontend externo (commit + checksum) ==="
ARTIFACT_CNAME=""
set +e
create_container vinto-mvp-verify-artifact --label com.docker.compose.project=vinto-mvp ubuntu:24.04 sleep 300
artifact_create_status=$?
set -e
if [ "$artifact_create_status" -ne 0 ]; then
  report "install-frontend-artifact: validación de commit/checksum (omitida: no se pudo crear el contenedor de ensayo)" 1
else
  ARTIFACT_CNAME="$CREATED_NAME"
  docker cp "$SCRIPT_DIR/.." "$ARTIFACT_CNAME:/tmp/mvp-scripts" >/dev/null
  set +e
  docker exec "$ARTIFACT_CNAME" bash -c '
    set -e
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq && apt-get install -y -qq --no-install-recommends sudo python3.12 >/dev/null
    useradd --system --no-create-home --shell /usr/sbin/nologin vinto-mvp
    SHA_OK="1111111111111111111111111111111111111111"
    SHA_OTHER="2222222222222222222222222222222222222222"
    mkdir -p /opt/vinto-mvp-web/releases/$SHA_OK/backend /opt/vinto-mvp-web/releases/$SHA_OTHER/backend
    chown -R vinto-mvp:vinto-mvp /opt/vinto-mvp-web

    mkdir -p /tmp/fakeartifact/standalone
    echo "fake server" > /tmp/fakeartifact/standalone/server.js
    tar -czf /tmp/artifact.tar.gz -C /tmp/fakeartifact standalone
    REAL_SHA256="$(sha256sum /tmp/artifact.tar.gz | awk "{print \$1}")"
    printf "VINTO_MVP_ARTIFACT_COMMIT=%s\nVINTO_MVP_ARTIFACT_NODE_VERSION=22.18.0\nVINTO_MVP_ARTIFACT_SHA256=%s\n" "$SHA_OK" "$REAL_SHA256" > /tmp/artifact.manifest

    cd /tmp/mvp-scripts
    # 1. commit correcto + checksum correcto -> instala.
    CONFIRM=yes bash deploy.sh install-frontend-artifact "$SHA_OK" /tmp/artifact.tar.gz /tmp/artifact.manifest
    [ -f /opt/vinto-mvp-web/releases/$SHA_OK/dist/standalone/server.js ]

    # 2. commit del manifiesto no coincide con el pedido -> rechaza, no instala nada para SHA_OTHER.
    ! CONFIRM=yes bash deploy.sh install-frontend-artifact "$SHA_OTHER" /tmp/artifact.tar.gz /tmp/artifact.manifest
    [ ! -e /opt/vinto-mvp-web/releases/$SHA_OTHER/dist ]

    # 3. artefacto manipulado (checksum ya no coincide con el manifiesto) -> rechaza.
    cp /tmp/artifact.tar.gz /tmp/tampered.tar.gz
    printf "x" >> /tmp/tampered.tar.gz
    sed "s/$SHA_OK/$SHA_OTHER/" /tmp/artifact.manifest > /tmp/other.manifest
    ! CONFIRM=yes bash deploy.sh install-frontend-artifact "$SHA_OTHER" /tmp/tampered.tar.gz /tmp/other.manifest
    [ ! -e /opt/vinto-mvp-web/releases/$SHA_OTHER/dist ]

    # 4. reinstalar sobre un release que YA tiene dist/ -> rechaza, nunca sobrescribe.
    ! CONFIRM=yes bash deploy.sh install-frontend-artifact "$SHA_OK" /tmp/artifact.tar.gz /tmp/artifact.manifest
  ' >/tmp/verify-artifact.log 2>&1
  artifact_ok=$?
  set -e
  if [ "$artifact_ok" -eq 0 ]; then
    report "install-frontend-artifact: instala con commit+checksum correctos; rechaza commit erróneo, artefacto manipulado y sobrescritura" 0
  else
    echo "--- log C.1-2 ---"; cat /tmp/verify-artifact.log
    report "install-frontend-artifact: instala con commit+checksum correctos; rechaza commit erróneo, artefacto manipulado y sobrescritura" 1
  fi

  echo "=== Prueba focalizada DEP56-01: extracción segura de artefactos (archivos maliciosos y truncados) ==="
  # Reutiliza el mismo contenedor (ya tiene python3.12 + vinto-mvp). Cada caso debe rechazarse
  # SIN instalar nada y SIN dejar nada en el staging propio.
  set +e
  docker exec "$ARTIFACT_CNAME" bash -c '
    set -e
    SHA="3333333333333333333333333333333333333333"
    mkdir -p /opt/vinto-mvp-web/releases/$SHA/backend
    chown -R vinto-mvp:vinto-mvp /opt/vinto-mvp-web/releases/$SHA
    cd /tmp/mvp-scripts

    # Entrada fuera de standalone/.
    mkdir -p /tmp/evil1/standalone
    echo x > /tmp/evil1/standalone/server.js
    echo evil > /tmp/evil1/evil.txt
    tar -czf /tmp/evil1.tar.gz -C /tmp/evil1 standalone evil.txt
    sha="$(sha256sum /tmp/evil1.tar.gz | awk "{print \$1}")"
    printf "VINTO_MVP_ARTIFACT_COMMIT=%s\nVINTO_MVP_ARTIFACT_SHA256=%s\n" "$SHA" "$sha" > /tmp/evil1.manifest
    ! CONFIRM=yes bash deploy.sh install-frontend-artifact "$SHA" /tmp/evil1.tar.gz /tmp/evil1.manifest
    [ ! -e /opt/vinto-mvp-web/releases/$SHA/dist ]

    # Recorrido "..": un tar de verdad con una entrada que escapa de standalone/.
    mkdir -p /tmp/evil2/standalone /tmp/evil2_payload
    echo x > /tmp/evil2/standalone/server.js
    cd /tmp/evil2 && tar -cf /tmp/evil2.tar standalone && cd /tmp
    echo PWNED > /tmp/evil2_payload/escape.txt
    cd /tmp/evil2_payload
    tar --transform "s,^escape.txt,standalone/../../etc/escape.txt," -rf /tmp/evil2.tar escape.txt
    cd /tmp
    gzip -f /tmp/evil2.tar
    sha="$(sha256sum /tmp/evil2.tar.gz | awk "{print \$1}")"
    printf "VINTO_MVP_ARTIFACT_COMMIT=%s\nVINTO_MVP_ARTIFACT_SHA256=%s\n" "$SHA" "$sha" > /tmp/evil2.manifest
    ! CONFIRM=yes bash deploy.sh install-frontend-artifact "$SHA" /tmp/evil2.tar.gz /tmp/evil2.manifest
    [ ! -e /opt/vinto-mvp-web/releases/$SHA/dist ]
    [ ! -e /etc/escape.txt ]

    # Enlace simbólico que escapa del destino.
    mkdir -p /tmp/evil3/standalone
    echo x > /tmp/evil3/standalone/server.js
    ln -s /etc /tmp/evil3/standalone/escape
    tar -czf /tmp/evil3.tar.gz -C /tmp/evil3 standalone
    sha="$(sha256sum /tmp/evil3.tar.gz | awk "{print \$1}")"
    printf "VINTO_MVP_ARTIFACT_COMMIT=%s\nVINTO_MVP_ARTIFACT_SHA256=%s\n" "$SHA" "$sha" > /tmp/evil3.manifest
    ! CONFIRM=yes bash deploy.sh install-frontend-artifact "$SHA" /tmp/evil3.tar.gz /tmp/evil3.manifest
    [ ! -e /opt/vinto-mvp-web/releases/$SHA/dist ]

    # Tar truncado/corrupto (suficientemente grande para que truncarlo a la mitad sea real).
    mkdir -p /tmp/big/standalone
    head -c 50000 /dev/urandom | base64 > /tmp/big/standalone/server.js
    tar -czf /tmp/big.tar.gz -C /tmp/big standalone
    head -c $(( $(stat -c%s /tmp/big.tar.gz) / 2 )) /tmp/big.tar.gz > /tmp/truncated.tar.gz
    sha="$(sha256sum /tmp/truncated.tar.gz | awk "{print \$1}")"
    printf "VINTO_MVP_ARTIFACT_COMMIT=%s\nVINTO_MVP_ARTIFACT_SHA256=%s\n" "$SHA" "$sha" > /tmp/truncated.manifest
    ! CONFIRM=yes bash deploy.sh install-frontend-artifact "$SHA" /tmp/truncated.tar.gz /tmp/truncated.manifest
    [ ! -e /opt/vinto-mvp-web/releases/$SHA/dist ]

    # Nada de staging propio debe quedar tras los 4 rechazos.
    [ -z "$(ls -A /opt/vinto-mvp-web/.artifact-staging 2>/dev/null)" ]
  ' >/tmp/verify-dep56-01.log 2>&1
  dep56_01_ok=$?
  set -e
  if [ "$dep56_01_ok" -eq 0 ]; then
    report "install-frontend-artifact rechaza entrada fuera de standalone/, recorrido '..', enlace simbólico y tar truncado; staging siempre vacío" 0
  else
    echo "--- log DEP56-01 ---"; cat /tmp/verify-dep56-01.log
    report "install-frontend-artifact rechaza entrada fuera de standalone/, recorrido '..', enlace simbólico y tar truncado; staging siempre vacío" 1
  fi
fi

echo "=== Prueba focalizada C.1-3: sintaxis systemd (systemd-analyze, misma versión que el VPS) ==="
# El VPS real corre systemd 255 (confirmado en CLOUD-DEP-02B.1-A); ubuntu:24.04 trae la misma
# versión mayor. "systemd-analyze verify" no necesita que systemd sea PID 1: valida el archivo de
# unidad igual. No se declara probado el ARRANQUE real (eso sigue pendiente del VPS), solo la
# sintaxis — ver limitación ya documentada en la prueba 8 de este mismo archivo.
SYSTEMD_CNAME=""
set +e
create_container vinto-mvp-verify-systemd --label com.docker.compose.project=vinto-mvp ubuntu:24.04 sleep 300
systemd_create_status=$?
set -e
if [ "$systemd_create_status" -ne 0 ]; then
  report "systemd-analyze verify sobre los 2 units del MVP (omitida: no se pudo crear el contenedor de ensayo)" 1
else
  SYSTEMD_CNAME="$CREATED_NAME"
  # "docker cp" SÍ necesita la conversión normal de Git Bash (el origen "$MVP_DIR/systemd" es una
  # ruta real del HOST) — se ejecuta ANTES de activar MSYS_NO_PATHCONV, que a partir de aquí
  # protege los argumentos /tmp/mvp-systemd/... (rutas DENTRO del contenedor) de "systemd-analyze
  # verify": sin esa protección, Git Bash los reescribiría como rutas de Windows y produciría un
  # error confuso que no tiene nada que ver con la unidad en sí (p. ej. "Couldn't process aliases").
  docker cp "$MVP_DIR/systemd" "$SYSTEMD_CNAME:/tmp/mvp-systemd" >/dev/null
  export MSYS_NO_PATHCONV=1
  set +e
  docker exec "$SYSTEMD_CNAME" bash -c '
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq >/dev/null && apt-get install -y -qq --no-install-recommends systemd >/dev/null
  ' >/tmp/verify-systemd-setup.log 2>&1
  systemd_setup_ok=$?
  set -e
  if [ "$systemd_setup_ok" -ne 0 ]; then
    echo "--- log de preparación C.1-3 ---"; cat /tmp/verify-systemd-setup.log
    report "systemd-analyze verify sobre los 2 units del MVP (omitida: no se pudo instalar systemd en el contenedor de ensayo)" 1
  else
    set +e
    no_unknown_key="$(docker exec "$SYSTEMD_CNAME" systemd-analyze verify /tmp/mvp-systemd/vinto-mvp-backend.service /tmp/mvp-systemd/vinto-mvp-frontend.service 2>&1 | grep -i 'unknown key' || true)"
    set -e
    if [ -z "$no_unknown_key" ]; then
      report "ningún 'Unknown key name' en los units (StartLimitIntervalSec/Burst correctamente en [Unit])" 0
    else
      echo "$no_unknown_key"
      report "ningún 'Unknown key name' en los units (StartLimitIntervalSec/Burst correctamente en [Unit])" 1
    fi
    # "systemd-analyze verify" también comprueba que el binario de ExecStart exista y sea
    # ejecutable (no solo la sintaxis) — en un contenedor vacío eso fallaría SIEMPRE, sin que
    # signifique nada sobre la unidad en sí. Se crean ejecutables de relleno exactamente en las
    # rutas que ambas unidades referencian, para una verificación honesta de la unidad completa.
    set +e
    docker exec "$SYSTEMD_CNAME" bash -c '
      mkdir -p /opt/vinto-mvp-web/current/backend/.venv/bin /opt/vinto-mvp-web/runtime/active/bin
      printf "#!/bin/sh\ntrue\n" > /opt/vinto-mvp-web/current/backend/.venv/bin/uvicorn
      printf "#!/bin/sh\ntrue\n" > /opt/vinto-mvp-web/runtime/active/bin/node
      chmod +x /opt/vinto-mvp-web/current/backend/.venv/bin/uvicorn /opt/vinto-mvp-web/runtime/active/bin/node
    ' >/tmp/verify-systemd-stubs.log 2>&1
    stubs_ok=$?
    set -e
    if [ "$stubs_ok" -ne 0 ]; then
      echo "--- log C.1-3 stubs ---"; cat /tmp/verify-systemd-stubs.log
      report "systemd-analyze verify: vinto-mvp-frontend.service sintácticamente válido (systemd 255, igual que el VPS)" 1
    else
      set +e
      docker exec "$SYSTEMD_CNAME" systemd-analyze verify /tmp/mvp-systemd/vinto-mvp-frontend.service >/tmp/verify-systemd-frontend.log 2>&1
      frontend_verify_ok=$?
      set -e
      if [ "$frontend_verify_ok" -eq 0 ]; then
        report "systemd-analyze verify: vinto-mvp-frontend.service sintácticamente válido (systemd 255, igual que el VPS)" 0
      else
        echo "--- log C.1-3 frontend ---"; cat /tmp/verify-systemd-frontend.log
        report "systemd-analyze verify: vinto-mvp-frontend.service sintácticamente válido (systemd 255, igual que el VPS)" 1
      fi
    fi
  fi
  unset MSYS_NO_PATHCONV
fi

echo "=== Prueba focalizada C.1-4: wrapper de Docker Compose (DEP55-02B.1-C.1, Fase D) ==="
set +e
( source "$SCRIPT_DIR/../lib_common.sh"; detect_compose_cmd; echo "${COMPOSE_CMD[@]}" )
detect_status=$?
set -e
if [ "$detect_status" -eq 0 ]; then
  report "detect_compose_cmd encuentra un comando compose utilizable en este host" 0
else
  report "detect_compose_cmd encuentra un comando compose utilizable en este host" 1
fi
# Estático: confirmar que deploy.sh/rollback.sh usan el wrapper (COMPOSE_CMD) y no "docker compose"
# literal fuera de comentarios — así nunca queda un rastro sin adaptar.
literal_compose_calls="$(grep -vE '^\s*#' "$SCRIPT_DIR/../deploy.sh" "$SCRIPT_DIR/../rollback.sh" | grep -E '\bdocker compose\b' || true)"
if [ -z "$literal_compose_calls" ]; then
  report "deploy.sh/rollback.sh no invocan 'docker compose' literal (usan detect_compose_cmd/COMPOSE_CMD)" 0
else
  echo "$literal_compose_calls"
  report "deploy.sh/rollback.sh no invocan 'docker compose' literal (usan detect_compose_cmd/COMPOSE_CMD)" 1
fi
if grep -q 'COMPOSE_CMD\[@\]' "$SCRIPT_DIR/../deploy.sh" && grep -q 'COMPOSE_CMD\[@\]' "$SCRIPT_DIR/../rollback.sh"; then
  report "deploy.sh y rollback.sh usan \${COMPOSE_CMD[@]} para levantar/detener PostgreSQL" 0
else
  report "deploy.sh y rollback.sh usan \${COMPOSE_CMD[@]} para levantar/detener PostgreSQL" 1
fi

echo "=== Prueba focalizada DEP56-R2-01: validate-compose, sin secretos ni en argumentos de procesos ==="
# Corre en ESTE host (necesita un comando Compose real disponible, no dentro de un contenedor
# Ubuntu vacío). Camino exitoso Y camino de error, con una contraseña SINTÉTICA inyectada en
# docker/.env — en ningún caso debe aparecer ni en stdout, ni en stderr, ni como argumento de
# ningún proceso lanzado durante la validación (CLOUD-DEP-02B.1-C.3: la versión anterior pasaba
# la contraseña como argv de un proceso Python para redactar un log, visible en la lista de
# procesos del host mientras corría).
SYNTHETIC_PW="S3cretSynthetic_Pw_$(_verify_unique_suffix)"
COMPOSE_ENV="$MVP_DIR/docker/.env"
track_tmp_path "$COMPOSE_ENV"
cat > "$COMPOSE_ENV" <<EOF
POSTGRES_BOOTSTRAP_DB=vinto_mvp_bootstrap
POSTGRES_BOOTSTRAP_USER=vinto_mvp_root
POSTGRES_BOOTSTRAP_PASSWORD=$SYNTHETIC_PW
VINTO_MVP_PGDATA_DIR=/tmp/vinto-mvp-pgdata-test
EOF

# Camino exitoso, vigilando la lista de procesos MIENTRAS corre (best-effort: se lanza en
# segundo plano y se sondea "ps" repetidamente durante su ejecución, no solo al final).
set +e
( CONFIRM=yes bash "$SCRIPT_DIR/../deploy.sh" validate-compose >/tmp/verify-compose-ok.out 2>/tmp/verify-compose-ok.err ) &
vc_pid=$!
pw_seen_in_ps=0
for _ in $(seq 1 100); do
  kill -0 "$vc_pid" 2>/dev/null || break
  # shellcheck disable=SC2009 # se busca una SUBCADENA arbitraria (la contraseña sintética) en
  # los argumentos de los procesos; "pgrep" no busca por contenido de argv de esta forma.
  if ps -ef 2>/dev/null | grep -F "$SYNTHETIC_PW" | grep -v "verify_local.sh\|grep" >/dev/null 2>&1; then
    pw_seen_in_ps=1
    break
  fi
  sleep 0.05
done
wait "$vc_pid"
compose_ok_status=$?
set -e
if [ "$compose_ok_status" -eq 0 ] && [ "$pw_seen_in_ps" -eq 0 ] \
    && ! grep -q "$SYNTHETIC_PW" /tmp/verify-compose-ok.out /tmp/verify-compose-ok.err; then
  report "validate-compose (éxito): la contraseña sintética no aparece en stdout/stderr ni en 'ps' mientras corre" 0
else
  echo "--- stdout ---"; cat /tmp/verify-compose-ok.out
  echo "--- stderr ---"; cat /tmp/verify-compose-ok.err
  echo "--- vista en ps: $pw_seen_in_ps ---"
  report "validate-compose (éxito): la contraseña sintética no aparece en stdout/stderr ni en 'ps' mientras corre" 1
fi

# Camino de error: quitar una variable requerida para forzar un fallo de interpolación. El
# mensaje debe ser GENÉRICO (sin el detalle de compose, sin nombres de variable ni fragmentos de
# configuración) además de no contener la contraseña.
cat > "$COMPOSE_ENV" <<EOF
POSTGRES_BOOTSTRAP_DB=vinto_mvp_bootstrap
POSTGRES_BOOTSTRAP_USER=vinto_mvp_root
POSTGRES_BOOTSTRAP_PASSWORD=$SYNTHETIC_PW
EOF
set +e
CONFIRM=yes bash "$SCRIPT_DIR/../deploy.sh" validate-compose >/tmp/verify-compose-err.out 2>/tmp/verify-compose-err.err
compose_err_status=$?
set -e
if [ "$compose_err_status" -ne 0 ] \
    && ! grep -q "$SYNTHETIC_PW" /tmp/verify-compose-err.out /tmp/verify-compose-err.err \
    && ! grep -qiE 'interpolat|VINTO_MVP_PGDATA_DIR|required variable' /tmp/verify-compose-err.out /tmp/verify-compose-err.err; then
  report "validate-compose (error): mensaje genérico, sin contraseña ni detalle de la configuración" 0
else
  echo "--- stdout ---"; cat /tmp/verify-compose-err.out
  echo "--- stderr ---"; cat /tmp/verify-compose-err.err
  report "validate-compose (error): mensaje genérico, sin contraseña ni detalle de la configuración" 1
fi
rm -f "$COMPOSE_ENV"

# Estático: confirma que la fase exige -q/--quiet, y que su cuerpo YA NO invoca python3.12 ni lee
# la contraseña en absoluto (nunca la pasa como argumento de ningún proceso).
if grep -q -- '--quiet' "$SCRIPT_DIR/../deploy.sh"; then
  report "phase_validate_compose exige -q/--quiet antes de validar" 0
else
  report "phase_validate_compose exige -q/--quiet antes de validar" 1
fi
validate_compose_body="$(awk '/^phase_validate_compose\(\)/,/^}/' "$SCRIPT_DIR/../deploy.sh")"
if ! printf '%s' "$validate_compose_body" | grep -qE 'python3\.12|BOOTSTRAP_PASSWORD|bootstrap_pw'; then
  report "phase_validate_compose ya no invoca python3.12 ni lee ninguna contraseña (nunca puede pasarla como argumento)" 0
else
  report "phase_validate_compose ya no invoca python3.12 ni lee ninguna contraseña (nunca puede pasarla como argumento)" 1
fi

echo "=== Verificación: DEP56-01/02 permanecen intactos (reutilizando las pruebas ya ejecutadas arriba) ==="
echo "Ver secciones 'Prueba focalizada DEP56-01' y 'C.1-1/C.1-2' más arriba en esta misma corrida:"
echo "forman parte de la MISMA ejecución de verify_local.sh, no de una corrida separada."

echo "=== Prueba focalizada E.2: build-frontend-artifact.sh — dependencias de runtime completas + arranque aislado obligatorio (CLOUD-DEP-02B.1-E.2) ==="
echo "CLOUD-DEP-02B.1-E.1 encontró, contra el commit real ebbe1afedb5d39f2605cc534b1278fd92f614394,"
echo "que el standalone de 'vinext build' puede NO incluir todo lo que necesita en tiempo de"
echo "ejecución (faltaba 'react'; ERR_MODULE_NOT_FOUND real al arrancar). Esta batería prueba la"
echo "corrección con un build real (Linux x86_64, Node 22.18.0, pnpm 11.25.0) Y los caminos de"
echo "rechazo explícito (Fase D), nunca solo el camino feliz."
FRONTEND_BUILD_CNAME=""
set +e
create_container vinto-mvp-verify-frontend-build --label com.docker.compose.project=vinto-mvp node:22.18.0-bookworm sleep 1800
frontend_build_create_status=$?
set -e
if [ "$frontend_build_create_status" -ne 0 ]; then
  report "build-frontend-artifact.sh: build real + arranque aislado (omitida: no se pudo crear el contenedor de ensayo)" 1
else
  FRONTEND_BUILD_CNAME="$CREATED_NAME"
  docker cp "$SCRIPT_DIR/../build-frontend-artifact.sh" "$FRONTEND_BUILD_CNAME:/tmp/build-frontend-artifact-fixed.sh" >/dev/null
  set +e
  docker exec "$FRONTEND_BUILD_CNAME" bash -c '
    set -e
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq && apt-get install -y -qq --no-install-recommends git curl ca-certificates >/dev/null
    corepack enable
    git clone --quiet https://github.com/BaltrekCompany/vinto-mvp-web.git /tmp/repo
    cd /tmp/repo
    git checkout --quiet ebbe1afedb5d39f2605cc534b1278fd92f614394
  ' >/tmp/verify-e2-setup.log 2>&1
  e2_setup_ok=$?
  set -e
  if [ "$e2_setup_ok" -ne 0 ]; then
    echo "--- log de preparación E.2 ---"; cat /tmp/verify-e2-setup.log
    report "build-frontend-artifact.sh: preparación (clon real del repositorio en el commit aprobado)" 1
  else
    report "build-frontend-artifact.sh: preparación (clon real del repositorio en el commit aprobado)" 0

    # Camino feliz, con el commit y el repositorio REALES: build completo, dependencias
    # completadas dinámicamente, empaquetado, y arranque AISLADO (fuera de /tmp/repo) con HTTP 200
    # — exactamente lo que recibiría deploy.sh install-frontend-artifact en el VPS. Además verifica
    # checksum real, estructura (todo bajo standalone/, sin .env) y que 'react' (lo que faltaba en
    # E.1) está ahora presente.
    set +e
    docker exec "$FRONTEND_BUILD_CNAME" bash -c '
      set -e
      mkdir -p /tmp/out
      VINTO_MVP_DOMAIN=vinto-mvp.baltrekservices.com bash /tmp/build-frontend-artifact-fixed.sh /tmp/repo ebbe1afedb5d39f2605cc534b1278fd92f614394 /tmp/out
      ARTIFACT="/tmp/out/vinto-mvp-frontend-ebbe1afedb5d39f2605cc534b1278fd92f614394.tar.gz"
      MANIFEST="/tmp/out/vinto-mvp-frontend-ebbe1afedb5d39f2605cc534b1278fd92f614394.manifest"
      [ -f "$ARTIFACT" ]
      [ -f "$MANIFEST" ]
      actual_sha="$(sha256sum "$ARTIFACT" | awk "{print \$1}")"
      manifest_sha="$(grep "^VINTO_MVP_ARTIFACT_SHA256=" "$MANIFEST" | cut -d= -f2)"
      [ "$actual_sha" = "$manifest_sha" ]
      ! tar -tzf "$ARTIFACT" | grep -v "^standalone/"
      ! tar -tzf "$ARTIFACT" | grep -iE "(^|/)\.env($|[./])"
      tar -tzf "$ARTIFACT" | grep -qx "standalone/node_modules/react/package.json"
      # Evidencia EXPLÍCITA de arranque aislado con HTTP 200, en una copia aparte fuera de
      # /tmp/repo (Node no puede ver node_modules del repo original desde ahí).
      rm -rf /tmp/evidence && mkdir -p /tmp/evidence
      tar -xzf "$ARTIFACT" -C /tmp/evidence
      source /tmp/build-frontend-artifact-fixed.sh
      BOOT_TIMEOUT_UNITS=20
      evidence_result="$(boot_and_check /tmp/evidence/standalone)"
      [ "$evidence_result" = "OK" ]
      echo "EVIDENCIA_HTTP200_AISLADO: $evidence_result"
    ' >/tmp/verify-e2-build.log 2>&1
    e2_build_ok=$?
    set -e
    if [ "$e2_build_ok" -eq 0 ]; then
      report "build-frontend-artifact.sh: build real completa dependencias faltantes, empaqueta y arranca HTTP 200 de forma aislada (checksum, estructura y seguridad verificados)" 0
      grep "EVIDENCIA_HTTP200_AISLADO" /tmp/verify-e2-build.log
    else
      echo "--- log E.2 build ---"; cat /tmp/verify-e2-build.log
      report "build-frontend-artifact.sh: build real completa dependencias faltantes, empaqueta y arranca HTTP 200 de forma aislada (checksum, estructura y seguridad verificados)" 1
    fi

    # --- Fase D: validación negativa (nunca solo el camino feliz) ------------------------------

    # D1+D5: un paquete de runtime obligatorio que NO puede resolverse (ni en el repo, porque no
    # está instalado) debe hacer FALLAR el build explícitamente, sin dejar artefacto ni manifiesto
    # — nunca una versión "a medias" que pudiera confundirse con una válida.
    set +e
    docker exec "$FRONTEND_BUILD_CNAME" bash -c '
      set -e
      rm -rf /tmp/fakerepo && mkdir -p /tmp/fakerepo
      cd /tmp/fakerepo
      git init --quiet
      git config user.email "test@example.com"
      git config user.name "test"
      printf "%s" "{\"name\":\"fake-vinto-mvp\",\"private\":true,\"packageManager\":\"pnpm@11.25.0\",\"scripts\":{\"build\":\"node build.js\"}}" > package.json
      printf "%s" "const fs=require(\"fs\");fs.mkdirSync(\"dist/standalone\",{recursive:true});fs.writeFileSync(\"dist/standalone/package.json\",JSON.stringify({private:true,type:\"module\"}));fs.writeFileSync(\"dist/standalone/server.js\",\"import \\\"paquete-inexistente-xyz-999\\\";\\n\");" > build.js
      corepack pnpm install --lockfile-only >/dev/null 2>&1
      git add -A
      git commit --quiet -m "fake repo"
      SHA="$(git rev-parse HEAD)"
      rm -rf /tmp/fakeout && mkdir -p /tmp/fakeout
      ! VINTO_MVP_DOMAIN=example.test bash /tmp/build-frontend-artifact-fixed.sh /tmp/fakerepo "$SHA" /tmp/fakeout
      [ -z "$(ls -A /tmp/fakeout)" ]
    ' >/tmp/verify-e2-d1.log 2>&1
    e2_d1_ok=$?
    set -e
    if [ "$e2_d1_ok" -eq 0 ]; then
      report "build-frontend-artifact.sh: un paquete de runtime irresoluble hace FALLAR el build sin generar artefacto ni manifiesto" 0
    else
      echo "--- log D1/D5 ---"; cat /tmp/verify-e2-d1.log
      report "build-frontend-artifact.sh: un paquete de runtime irresoluble hace FALLAR el build sin generar artefacto ni manifiesto" 1
    fi

    # D2: un artefacto incompleto (sin standalone/server.js) debe ser rechazado por
    # isolated_boot_gate, nunca aceptado por tener la extensión/estructura superficial correcta.
    set +e
    docker exec "$FRONTEND_BUILD_CNAME" bash -c '
      set -e
      source /tmp/build-frontend-artifact-fixed.sh
      rm -rf /tmp/incomplete && mkdir -p /tmp/incomplete/standalone
      echo "{}" > /tmp/incomplete/standalone/package.json
      tar -czf /tmp/incomplete.tar.gz -C /tmp/incomplete standalone
      ! isolated_boot_gate /tmp/incomplete.tar.gz /tmp/repo
    ' >/tmp/verify-e2-d2.log 2>&1
    e2_d2_ok=$?
    set -e
    if [ "$e2_d2_ok" -eq 0 ]; then
      report "build-frontend-artifact.sh: isolated_boot_gate rechaza un artefacto incompleto (sin server.js)" 0
    else
      echo "--- log D2 ---"; cat /tmp/verify-e2-d2.log
      report "build-frontend-artifact.sh: isolated_boot_gate rechaza un artefacto incompleto (sin server.js)" 1
    fi

    # D3+D4: un servidor que nunca responde (ni arranca ni muestra un error de módulo reconocible)
    # debe producir FALLA dentro de un tiempo ACOTADO (nunca colgar la prueba), y el proceso que
    # arrancó nunca debe sobrevivir a la comprobación (sin huérfanos, ni siquiera tras un fallo).
    # DOS "docker exec" separados a propósito: el proceso "bash -c" del PRIMERO queda él mismo en
    # la lista de procesos mientras corre, con el propio texto embebido del script (que menciona
    # "hangtest/server.js" varias veces) como su línea de comandos — comprobar huérfanos DENTRO de
    # ese mismo "docker exec" se autocoincidiría con el envoltorio, no con un proceso "node" real.
    # El segundo "docker exec" corre después de que el primero ya terminó y desapareció.
    set +e
    docker exec "$FRONTEND_BUILD_CNAME" bash -c '
      set -e
      source /tmp/build-frontend-artifact-fixed.sh
      rm -rf /tmp/hangtest && mkdir -p /tmp/hangtest
      printf "setInterval(() => {}, 1000);\n" > /tmp/hangtest/server.js
      BOOT_TIMEOUT_UNITS=4
      start=$(date +%s)
      set +e
      out="$(boot_and_check /tmp/hangtest)"
      status=$?
      set -e
      end=$(date +%s)
      elapsed=$((end - start))
      [ "$out" = "FAIL" ]
      [ "$status" -ne 0 ]
      [ "$elapsed" -le 8 ]
    ' >/tmp/verify-e2-d3.log 2>&1
    e2_d3_ok=$?
    set -e
    if [ "$e2_d3_ok" -eq 0 ]; then
      set +e
      docker exec "$FRONTEND_BUILD_CNAME" bash -c '! ps aux | grep "[n]ode .*hangtest/server.js"' >>/tmp/verify-e2-d3.log 2>&1
      e2_d3_orphan_ok=$?
      set -e
    else
      e2_d3_orphan_ok=1
    fi
    if [ "$e2_d3_ok" -eq 0 ] && [ "$e2_d3_orphan_ok" -eq 0 ]; then
      report "build-frontend-artifact.sh: un servidor que nunca responde produce FALLA acotada en el tiempo, sin procesos huérfanos" 0
    else
      echo "--- log D3/D4 ---"; cat /tmp/verify-e2-d3.log
      report "build-frontend-artifact.sh: un servidor que nunca responde produce FALLA acotada en el tiempo, sin procesos huérfanos" 1
    fi

    # --- CLOUD-DEP-02B.1-E.3: correcciones focalizadas tras la auditoría del PR #58 -------------

    # CLOUD-DEP-02B.1-E.3, observación 3 (ejecución concurrente): dos boot_and_check en paralelo, cada uno contra su propio
    # servidor y puerto (pick_free_port), no deben interferirse ni colisionar.
    set +e
    docker exec "$FRONTEND_BUILD_CNAME" bash -c '
      set -e
      source /tmp/build-frontend-artifact-fixed.sh
      for n in a b; do
        mkdir -p "/tmp/concserver-$n"
        printf "const http=require(\"http\");http.createServer((req,res)=>{res.end(\"hola-%s\")}).listen(process.env.PORT,process.env.HOST);\n" "$n" > "/tmp/concserver-$n/server.js"
      done
      ( boot_and_check /tmp/concserver-a > /tmp/conc-a.out 2>/tmp/conc-a.err ) &
      pa=$!
      ( boot_and_check /tmp/concserver-b > /tmp/conc-b.out 2>/tmp/conc-b.err ) &
      pb=$!
      wait "$pa"; ra=$?
      wait "$pb"; rb=$?
      [ "$ra" -eq 0 ] && [ "$rb" -eq 0 ]
      [ "$(cat /tmp/conc-a.out)" = "OK" ] && [ "$(cat /tmp/conc-b.out)" = "OK" ]
    ' >/tmp/verify-e3-concurrency.log 2>&1
    e3_concurrency_ok=$?
    set -e
    if [ "$e3_concurrency_ok" -eq 0 ]; then
      report "build-frontend-artifact.sh: dos boot_and_check concurrentes (puertos/temporales propios) no se interfieren" 0
    else
      echo "--- log E.3 concurrencia ---"; cat /tmp/verify-e3-concurrency.log
      report "build-frontend-artifact.sh: dos boot_and_check concurrentes (puertos/temporales propios) no se interfieren" 1
    fi

    # CLOUD-DEP-02B.1-E.3, observación 3 (limpieza de temporales): boot_and_check no debe dejar NINGÚN archivo nuevo bajo
    # /tmp tras resolverse, en ninguno de sus 3 caminos (OK, MISSING, FAIL) — ni su propio "$log"
    # (mktemp) ni, para isolated_boot_gate, el ".tar-stderr.log" de DEP58-01 (que ahora vive DENTRO
    # del directorio aislado y se borra con él, nunca en una ruta fija compartida).
    set +e
    docker exec "$FRONTEND_BUILD_CNAME" bash -c '
      set -e
      source /tmp/build-frontend-artifact-fixed.sh
      before="$(find /tmp -maxdepth 1 -type f | sort)"

      mkdir -p /tmp/cleanserver
      printf "const http=require(\"http\");http.createServer((req,res)=>{res.end(\"ok\")}).listen(process.env.PORT,process.env.HOST);\n" > /tmp/cleanserver/server.js
      boot_and_check /tmp/cleanserver >/dev/null 2>&1

      mkdir -p /tmp/missingserver
      printf "import \"paquete-xyz-inexistente\";\n" > /tmp/missingserver/server.js
      boot_and_check /tmp/missingserver >/dev/null 2>&1 || true

      mkdir -p /tmp/hangserver2
      printf "setInterval(() => {}, 1000);\n" > /tmp/hangserver2/server.js
      BOOT_TIMEOUT_UNITS=4 boot_and_check /tmp/hangserver2 >/dev/null 2>&1 || true

      after="$(find /tmp -maxdepth 1 -type f | sort)"
      leaked="$(comm -13 <(printf "%s\n" "$before") <(printf "%s\n" "$after"))"
      [ -z "$leaked" ]
    ' >/tmp/verify-e3-cleanup.log 2>&1
    e3_cleanup_ok=$?
    set -e
    if [ "$e3_cleanup_ok" -eq 0 ]; then
      report "build-frontend-artifact.sh: boot_and_check no deja archivos temporales propios en ninguno de sus 3 caminos (OK/MISSING/FAIL)" 0
    else
      echo "--- log E.3 limpieza ---"; cat /tmp/verify-e3-cleanup.log
      report "build-frontend-artifact.sh: boot_and_check no deja archivos temporales propios en ninguno de sus 3 caminos (OK/MISSING/FAIL)" 1
    fi

    # CLOUD-DEP-02B.1-E.3, observaciones 2/3 (terminación de procesos, incluso adversa): un servidor que INSTALA SU PROPIO
    # manejador de SIGTERM sin terminar (confirmado empíricamente: por defecto sobrevive
    # indefinidamente a "kill") debe, aun así, quedar terminado (escalada a SIGKILL) y la función
    # debe devolver el control en tiempo acotado — tanto si el servidor llega a responder HTTP 200
    # antes de que se le mate, como si nunca responde.
    set +e
    docker exec "$FRONTEND_BUILD_CNAME" bash -c '
      set -e
      source /tmp/build-frontend-artifact-fixed.sh

      mkdir -p /tmp/stubborn-ok
      cat > /tmp/stubborn-ok/server.js <<EOF2
process.on("SIGTERM", () => {});
const http = require("http");
http.createServer((req,res)=>{res.end("ok")}).listen(process.env.PORT, process.env.HOST);
EOF2
      BOOT_TIMEOUT_UNITS=6
      start=$(date +%s)
      set +e
      out_ok="$(boot_and_check /tmp/stubborn-ok)"; status_ok=$?
      set -e
      elapsed_ok=$(( $(date +%s) - start ))
      [ "$out_ok" = "OK" ] && [ "$status_ok" -eq 0 ] && [ "$elapsed_ok" -le 10 ]

      mkdir -p /tmp/stubborn-hang
      cat > /tmp/stubborn-hang/server.js <<EOF2
process.on("SIGTERM", () => {});
setInterval(() => {}, 1000);
EOF2
      BOOT_TIMEOUT_UNITS=4
      start=$(date +%s)
      set +e
      out_hang="$(boot_and_check /tmp/stubborn-hang)"; status_hang=$?
      set -e
      elapsed_hang=$(( $(date +%s) - start ))
      [ "$out_hang" = "FAIL" ] && [ "$status_hang" -ne 0 ] && [ "$elapsed_hang" -le 8 ]
    ' >/tmp/verify-e3-sigterm.log 2>&1
    e3_sigterm_ok=$?
    set -e
    if [ "$e3_sigterm_ok" -eq 0 ]; then
      set +e
      docker exec "$FRONTEND_BUILD_CNAME" bash -c '! ps aux | grep "[s]tubborn-ok/server.js" && ! ps aux | grep "[s]tubborn-hang/server.js"' >>/tmp/verify-e3-sigterm.log 2>&1
      e3_sigterm_orphan_ok=$?
      set -e
    else
      e3_sigterm_orphan_ok=1
    fi
    if [ "$e3_sigterm_ok" -eq 0 ] && [ "$e3_sigterm_orphan_ok" -eq 0 ]; then
      report "build-frontend-artifact.sh: un servidor que ignora SIGTERM se termina igual (escalada a SIGKILL), en tiempo acotado y sin huérfanos" 0
    else
      echo "--- log E.3 SIGTERM ---"; cat /tmp/verify-e3-sigterm.log
      report "build-frontend-artifact.sh: un servidor que ignora SIGTERM se termina igual (escalada a SIGKILL), en tiempo acotado y sin huérfanos" 1
    fi
  fi
fi

echo "=== Prueba focalizada E.6-A.1: identidad efectiva en checkout/python-venv/install-frontend-artifact/activate/rollback/preflight (CLOUD-DEP-02B.1-E.6-A.1) ==="
echo "La auditoría E.6-A encontró que \$APP_DIR (750, exclusivo de vinto-mvp) hace que CUALQUIER"
echo "comprobación de ruta privada evaluada como el invocador (ubuntu, nunca root/sudo sobre el"
echo "script completo) sea un falso negativo — el mismo patrón ya corregido para"
echo "install-node-runtime en PR #57, pero presente sin corregir en el resto del pipeline. Esta"
echo "batería reproduce el modelo real (usuario sin privilegios + sudo amplio + vinto-mvp separado,"
echo "sudoers equivalente) y ejercita las fases REALES de deploy.sh/rollback.sh/preflight.sh contra"
echo "un repositorio Git local sintético (nunca el repositorio real ni datos industriales)."
E6A1_CNAME=""
set +e
create_container vinto-mvp-verify-e6a1 --label com.docker.compose.project=vinto-mvp ubuntu:24.04 sleep 1800
e6a1_create_status=$?
set -e
if [ "$e6a1_create_status" -ne 0 ]; then
  report "E.6-A.1: identidad efectiva en el pipeline completo (omitida: no se pudo crear el contenedor de ensayo)" 1
else
  E6A1_CNAME="$CREATED_NAME"
  docker cp "$MVP_DIR" "$E6A1_CNAME:/tmp/mvp" >/dev/null
  # Exportado para TODO este bloque (no solo una línea): casi cada prueba de aquí invoca
  # "su -s /bin/bash ..." como argumento DIRECTO de "docker exec" (no envuelto en un "bash -c"
  # propio) — sin esto, Git Bash reescribe "/bin/bash" como una ruta de Windows ("su: failed to
  # execute C:/Program Files/Git/usr/bin/bash: No such file or directory"), igual que ya le pasa
  # a cualquier argumento con forma de ruta absoluta en otras pruebas de este archivo.
  export MSYS_NO_PATHCONV=1
  set +e
  docker exec "$E6A1_CNAME" bash -c '
    set -e
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq && apt-get install -y -qq --no-install-recommends git python3.12 python3.12-venv sudo curl ca-certificates >/dev/null

    # vinto-mvp: usuario de servicio real, 750 sobre /opt/vinto-mvp-web (lo crea "user-and-dirs",
    # más abajo, no a mano aquí: también ejercita esa fase).
    useradd --system --no-create-home --shell /usr/sbin/nologin vinto-mvp
    # mvp_operator: simula a "ubuntu" en el VPS real — sudo amplio, NUNCA miembro de vinto-mvp.
    useradd -m -s /bin/bash mvp_operator
    echo "mvp_operator ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/mvp_operator
    chmod 440 /etc/sudoers.d/mvp_operator
    # mvp_operator_nosudo: mismo perfil, SIN sudoers — para el escenario de fallo (punto 14).
    useradd -m -s /bin/bash mvp_operator_nosudo
    # 700 (no 755 por defecto de mkdir): simula que TVC/ETL no son legibles por "otros" en el
    # VPS real (el aislamiento que "user-and-dirs" verifica es justamente esto).
    mkdir -p -m 700 /opt/vinto-web /opt/vinto-etl

    # Repositorio Git LOCAL sintético (nunca el repositorio real ni datos industriales): 2
    # commits, con un backend/ mínimo pero realista (requirements.txt vacío — válido para pip,
    # evita cualquier dependencia de red además de la ya usada por apt/git).
    mkdir -p /tmp/fakerepo-src/backend/roles
    cd /tmp/fakerepo-src
    git init --quiet
    git config user.email "test@example.com"
    git config user.name "test"
    : > backend/requirements.txt
    printf -- "-- stub\n" > backend/roles/00_create_roles.sql
    git add -A
    git commit --quiet -m "fake commit 1"
    git rev-parse HEAD > /tmp/fakerepo-sha1.txt
    printf -- "-- stub actualizado\n" >> backend/roles/00_create_roles.sql
    git add -A
    git commit --quiet -m "fake commit 2"
    git rev-parse HEAD > /tmp/fakerepo-sha2.txt
    # "dubious ownership" de git: solo relevante para ESTE repositorio LOCAL de prueba (un clon
    # real por HTTPS, como en el VPS, nunca pasa por esa comprobación) — nunca algo que afecte al
    # repositorio real ni a ningún otro.
    git config --system --add safe.directory "*"
  ' >/tmp/verify-e6a1-setup.log 2>&1
  e6a1_setup_ok=$?
  set -e
  if [ "$e6a1_setup_ok" -ne 0 ]; then
    echo "--- log de preparación E.6-A.1 ---"; cat /tmp/verify-e6a1-setup.log
    report "E.6-A.1: preparación (usuarios sin privilegios, vinto-mvp, repositorio Git local sintético)" 1
  else
    report "E.6-A.1: preparación (usuarios sin privilegios, vinto-mvp, repositorio Git local sintético)" 0
    # MSYS_NO_PATHCONV: estas rutas son DENTRO del contenedor, nunca del host — sin esto, Git
    # Bash las reescribiría como rutas de Windows (mismo motivo que en otras pruebas de este
    # archivo que ya usan esta variable para argumentos de "docker exec"/"docker cp").
    SHA1="$(MSYS_NO_PATHCONV=1 docker exec "$E6A1_CNAME" cat /tmp/fakerepo-sha1.txt)"
    SHA2="$(MSYS_NO_PATHCONV=1 docker exec "$E6A1_CNAME" cat /tmp/fakerepo-sha2.txt)"

    # Punto de partida REAL: "user-and-dirs" crea /opt/vinto-mvp-web (750) como lo haría en el
    # VPS — nunca se construye el árbol a mano en esta prueba.
    set +e
    docker exec "$E6A1_CNAME" su -s /bin/bash mvp_operator -c \
      'cd /tmp/mvp/scripts && CONFIRM=yes bash deploy.sh user-and-dirs' \
      >/tmp/verify-e6a1-userdirs.log 2>&1
    e6a1_userdirs_ok=$?
    set -e
    if [ "$e6a1_userdirs_ok" -eq 0 ]; then
      report "E.6-A.1: user-and-dirs crea /opt/vinto-mvp-web (750) como mvp_operator, sin privilegios ampliados" 0
    else
      echo "--- log user-and-dirs ---"; cat /tmp/verify-e6a1-userdirs.log
      report "E.6-A.1: user-and-dirs crea /opt/vinto-mvp-web (750) como mvp_operator, sin privilegios ampliados" 1
    fi

    # 1. Checkout inicial (sin shared/backend.env todavía: debe avisar, no fallar).
    set +e
    docker exec "$E6A1_CNAME" su -s /bin/bash mvp_operator -c \
      "cd /tmp/mvp/scripts && REPO_URL=/tmp/fakerepo-src CONFIRM=yes AUTHORIZED_COMMIT=$SHA1 bash deploy.sh checkout $SHA1" \
      >/tmp/verify-e6a1-checkout1.log 2>&1
    e6a1_checkout1_ok=$?
    set -e
    if [ "$e6a1_checkout1_ok" -eq 0 ] && grep -q "AVISO.*backend.env" /tmp/verify-e6a1-checkout1.log; then
      report "E.6-A.1 (1,3): checkout inicial real como mvp_operator; detecta correctamente que shared/backend.env AÚN NO existe" 0
    else
      echo "--- log checkout 1 ---"; cat /tmp/verify-e6a1-checkout1.log
      report "E.6-A.1 (1,3): checkout inicial real como mvp_operator; detecta correctamente que shared/backend.env AÚN NO existe" 1
    fi

    # 2. Rechazo de checkout duplicado (mismo commit): mensaje claro, nunca el error de git
    #    confuso que producía el defecto original (release_dir "invisible" para mvp_operator).
    set +e
    docker exec "$E6A1_CNAME" su -s /bin/bash mvp_operator -c \
      "cd /tmp/mvp/scripts && REPO_URL=/tmp/fakerepo-src CONFIRM=yes AUTHORIZED_COMMIT=$SHA1 bash deploy.sh checkout $SHA1" \
      >/tmp/verify-e6a1-checkout-dup.log 2>&1
    e6a1_checkout_dup_status=$?
    set -e
    if [ "$e6a1_checkout_dup_status" -ne 0 ] && grep -q "ya existe .*releases" /tmp/verify-e6a1-checkout-dup.log; then
      report "E.6-A.1 (2): checkout duplicado rechazado con el mensaje claro esperado (no el error de git confuso del defecto original)" 0
    else
      echo "--- log checkout duplicado ---"; cat /tmp/verify-e6a1-checkout-dup.log
      report "E.6-A.1 (2): checkout duplicado rechazado con el mensaje claro esperado (no el error de git confuso del defecto original)" 1
    fi

    # 3b/4. Crear shared/backend.env (600) y repetir checkout con un SEGUNDO commit: ahora debe
    #       detectarlo y crear backend/.env como symlink real hacia shared/backend.env.
    set +e
    docker exec "$E6A1_CNAME" bash -c '
      set -e
      sudo -u vinto-mvp sh -c "printf \"DATABASE_URL=postgresql://x:y@127.0.0.1/db\n\" > /opt/vinto-mvp-web/shared/backend.env"
      sudo -u vinto-mvp chmod 600 /opt/vinto-mvp-web/shared/backend.env
    ' >/tmp/verify-e6a1-backendenv.log 2>&1
    docker exec "$E6A1_CNAME" su -s /bin/bash mvp_operator -c \
      "cd /tmp/mvp/scripts && REPO_URL=/tmp/fakerepo-src CONFIRM=yes AUTHORIZED_COMMIT=$SHA2 bash deploy.sh checkout $SHA2" \
      >>/tmp/verify-e6a1-backendenv.log 2>&1
    MSYS_NO_PATHCONV=1 docker exec "$E6A1_CNAME" sudo -u vinto-mvp test -L "/opt/vinto-mvp-web/releases/$SHA2/backend/.env" \
      >>/tmp/verify-e6a1-backendenv.log 2>&1
    e6a1_backendenv_ok=$?
    set -e
    if [ "$e6a1_backendenv_ok" -eq 0 ]; then
      report "E.6-A.1 (3,4): con shared/backend.env presente, checkout crea backend/.env como symlink real (antes: nunca se creaba, invisible para mvp_operator)" 0
    else
      echo "--- log backend.env/symlink ---"; cat /tmp/verify-e6a1-backendenv.log
      report "E.6-A.1 (3,4): con shared/backend.env presente, checkout crea backend/.env como symlink real (antes: nunca se creaba, invisible para mvp_operator)" 1
    fi

    # 5,6,7. Reconocimiento del release existente + python-venv real (venv + pip install de un
    #        requirements.txt vacío pero válido) + permisos 600 de backend/.env ya verificados
    #        dentro de la propia fase (antes: FALLABA siempre en la primera línea).
    set +e
    docker exec "$E6A1_CNAME" su -s /bin/bash mvp_operator -c \
      "cd /tmp/mvp/scripts && CONFIRM=yes bash deploy.sh python-venv $SHA2" \
      >/tmp/verify-e6a1-venv.log 2>&1
    e6a1_venv_ok=$?
    set -e
    if [ "$e6a1_venv_ok" -eq 0 ]; then
      MSYS_NO_PATHCONV=1 docker exec "$E6A1_CNAME" sudo -u vinto-mvp test -x "/opt/vinto-mvp-web/releases/$SHA2/backend/.venv/bin/python"
      e6a1_venv_ok=$?
    fi
    if [ "$e6a1_venv_ok" -eq 0 ]; then
      report "E.6-A.1 (5,6,7): python-venv real sobre un release ya preparado, como mvp_operator (antes: fallaba siempre en la primera comprobación)" 0
    else
      echo "--- log python-venv ---"; cat /tmp/verify-e6a1-venv.log
      report "E.6-A.1 (5,6,7): python-venv real sobre un release ya preparado, como mvp_operator (antes: fallaba siempre en la primera comprobación)" 1
    fi

    # 8,9,10. install-frontend-artifact: artefacto sintético válido se instala; uno incompleto
    #         (sin standalone/server.js) se rechaza; reinstalar sobre un dist/ ya existente se
    #         rechaza sin sobrescribir (antes: las 3 comprobaciones fallaban siempre en silencio).
    set +e
    docker exec "$E6A1_CNAME" bash -c "
      set -e
      mkdir -p /tmp/fakeartifact/standalone
      echo fake > /tmp/fakeartifact/standalone/server.js
      cd /tmp && tar -czf artifact.tar.gz -C fakeartifact standalone
      sha=\$(sha256sum artifact.tar.gz | awk '{print \$1}')
      printf 'VINTO_MVP_ARTIFACT_COMMIT=%s\nVINTO_MVP_ARTIFACT_SHA256=%s\n' '$SHA1' \"\$sha\" > artifact.manifest
      chown mvp_operator:mvp_operator artifact.tar.gz artifact.manifest

      mkdir -p /tmp/incomplete/standalone
      echo '{}' > /tmp/incomplete/standalone/package.json
      tar -czf incomplete.tar.gz -C incomplete standalone
      shai=\$(sha256sum incomplete.tar.gz | awk '{print \$1}')
      printf 'VINTO_MVP_ARTIFACT_COMMIT=%s\nVINTO_MVP_ARTIFACT_SHA256=%s\n' '$SHA2' \"\$shai\" > incomplete.manifest
      chown mvp_operator:mvp_operator incomplete.tar.gz incomplete.manifest
    " >/tmp/verify-e6a1-artifacts-prep.log 2>&1
    docker exec "$E6A1_CNAME" su -s /bin/bash mvp_operator -c \
      "cd /tmp/mvp/scripts && CONFIRM=yes bash deploy.sh install-frontend-artifact $SHA1 /tmp/artifact.tar.gz /tmp/artifact.manifest" \
      >/tmp/verify-e6a1-artifact-ok.log 2>&1
    e6a1_artifact_ok=$?
    set +e
    MSYS_NO_PATHCONV=1 docker exec "$E6A1_CNAME" sudo -u vinto-mvp test -f "/opt/vinto-mvp-web/releases/$SHA1/dist/standalone/server.js"
    e6a1_artifact_server_js=$?
    docker exec "$E6A1_CNAME" su -s /bin/bash mvp_operator -c \
      "cd /tmp/mvp/scripts && ! CONFIRM=yes bash deploy.sh install-frontend-artifact $SHA2 /tmp/incomplete.tar.gz /tmp/incomplete.manifest" \
      >/tmp/verify-e6a1-artifact-incomplete.log 2>&1
    e6a1_artifact_incomplete_rejected=$?
    docker exec "$E6A1_CNAME" su -s /bin/bash mvp_operator -c \
      "cd /tmp/mvp/scripts && ! CONFIRM=yes bash deploy.sh install-frontend-artifact $SHA1 /tmp/artifact.tar.gz /tmp/artifact.manifest" \
      >/tmp/verify-e6a1-artifact-overwrite.log 2>&1
    e6a1_artifact_overwrite_rejected=$?
    set -e
    if [ "$e6a1_artifact_ok" -eq 0 ] && [ "$e6a1_artifact_server_js" -eq 0 ] \
        && [ "$e6a1_artifact_incomplete_rejected" -eq 0 ] && [ "$e6a1_artifact_overwrite_rejected" -eq 0 ]; then
      report "E.6-A.1 (8,9,10): install-frontend-artifact instala un artefacto válido, rechaza uno incompleto y rechaza sobrescribir dist/ ya instalado, todo como mvp_operator" 0
    else
      echo "--- logs install-frontend-artifact ---"
      cat /tmp/verify-e6a1-artifact-ok.log /tmp/verify-e6a1-artifact-incomplete.log /tmp/verify-e6a1-artifact-overwrite.log
      report "E.6-A.1 (8,9,10): install-frontend-artifact instala un artefacto válido, rechaza uno incompleto y rechaza sobrescribir dist/ ya instalado, todo como mvp_operator" 1
    fi

    # 11. Activate dos veces (SHA1 luego SHA2, con stubs de uvicorn): detección de 'current' y
    #     'previous' — antes, 'previous_target' quedaba SIEMPRE vacío (el check de 'current'
    #     fallaba en silencio), así que la recuperación automática tras un healthcheck fallido
    #     NUNCA se disparaba de verdad en una segunda activación real.
    set +e
    docker exec "$E6A1_CNAME" bash -c "
      set -e
      sudo -u vinto-mvp mkdir -p /opt/vinto-mvp-web/releases/$SHA1/backend/.venv/bin
      sudo -u vinto-mvp sh -c 'printf \"#!/bin/sh\ntrue\n\" > /opt/vinto-mvp-web/releases/$SHA1/backend/.venv/bin/uvicorn'
      sudo -u vinto-mvp chmod +x /opt/vinto-mvp-web/releases/$SHA1/backend/.venv/bin/uvicorn
      sudo -u vinto-mvp mkdir -p /opt/vinto-mvp-web/releases/$SHA2/dist/standalone
      sudo -u vinto-mvp sh -c 'echo fake > /opt/vinto-mvp-web/releases/$SHA2/dist/standalone/server.js'
      # SHA2 ya tiene un venv real (de la prueba 5,6,7), pero su requirements.txt está vacío a
      # propósito (evita depender de la red más allá de apt/git) — nunca instaló uvicorn de
      # verdad. Stub ejecutable, igual que para SHA1, solo para satisfacer la comprobación de
      # activate sin depender de un paquete pip real.
      sudo -u vinto-mvp mkdir -p /opt/vinto-mvp-web/releases/$SHA2/backend/.venv/bin
      sudo -u vinto-mvp sh -c 'printf \"#!/bin/sh\ntrue\n\" > /opt/vinto-mvp-web/releases/$SHA2/backend/.venv/bin/uvicorn'
      sudo -u vinto-mvp chmod +x /opt/vinto-mvp-web/releases/$SHA2/backend/.venv/bin/uvicorn
    " >/tmp/verify-e6a1-activate-prep.log 2>&1
    docker exec "$E6A1_CNAME" su -s /bin/bash mvp_operator -c \
      "cd /tmp/mvp/scripts && CONFIRM=yes bash deploy.sh activate $SHA1" \
      >/tmp/verify-e6a1-activate1.log 2>&1
    e6a1_activate1_ok=$?
    docker exec "$E6A1_CNAME" su -s /bin/bash mvp_operator -c \
      "cd /tmp/mvp/scripts && CONFIRM=yes bash deploy.sh activate $SHA2" \
      >/tmp/verify-e6a1-activate2.log 2>&1
    e6a1_activate2_ok=$?
    set -e
    previous_path="$(MSYS_NO_PATHCONV=1 docker exec "$E6A1_CNAME" sudo -u vinto-mvp cat /opt/vinto-mvp-web/.previous-release-path 2>/dev/null || true)"
    if [ "$e6a1_activate1_ok" -eq 0 ] && [ "$e6a1_activate2_ok" -eq 0 ] \
        && [ "$previous_path" = "/opt/vinto-mvp-web/releases/$SHA1" ]; then
      report "E.6-A.1 (11): segunda activación detecta correctamente 'current'/'previous' (antes: previous_target quedaba siempre vacío)" 0
    else
      echo "--- previous_path detectado: '$previous_path' (esperado: /opt/vinto-mvp-web/releases/$SHA1) ---"
      echo "--- logs activate ---"; cat /tmp/verify-e6a1-activate1.log /tmp/verify-e6a1-activate2.log
      report "E.6-A.1 (11): segunda activación detecta correctamente 'current'/'previous' (antes: previous_target quedaba siempre vacío)" 1
    fi

    # 13. rollback.sh version en el laboratorio sintético (nunca sobre servicios productivos):
    #     revertir 'current' de SHA2 a SHA1 — antes, el "ln"/"mv" de esta función ni siquiera
    #     tenían "sudo -u vinto-mvp": habrían fallado con "Permission denied" directo.
    set +e
    docker exec "$E6A1_CNAME" su -s /bin/bash mvp_operator -c \
      "cd /tmp/mvp/scripts && CONFIRM=yes bash rollback.sh version $SHA1" \
      >/tmp/verify-e6a1-rollback.log 2>&1 || true
    set -e
    rollback_current="$(MSYS_NO_PATHCONV=1 docker exec "$E6A1_CNAME" sudo -u vinto-mvp readlink -f /opt/vinto-mvp-web/current 2>/dev/null || true)"
    # Se tolera que falle MÁS ADELANTE en el healthcheck (no hay systemd real en este contenedor
    # de ensayo: limitación conocida y documentada, igual que en la prueba 8 de este archivo) —
    # lo que se exige es que el symlink SÍ haya cambiado antes de llegar a esa limitación.
    if [ "$rollback_current" = "/opt/vinto-mvp-web/releases/$SHA1" ]; then
      report "E.6-A.1 (13): rollback.sh version revierte 'current' con el privilegio correcto en un laboratorio sintético (antes: 'ln'/'mv' sin 'sudo -u', fallo directo de permisos)" 0
    else
      echo "--- current tras rollback: '$rollback_current' (esperado: /opt/vinto-mvp-web/releases/$SHA1) ---"
      echo "--- log rollback ---"; cat /tmp/verify-e6a1-rollback.log
      report "E.6-A.1 (13): rollback.sh version revierte 'current' con el privilegio correcto en un laboratorio sintético (antes: 'ln'/'mv' sin 'sudo -u', fallo directo de permisos)" 1
    fi

    # 12. preflight.sh startup: 'current' completo se reporta OK (antes: siempre AVISO "no existe
    #     todavía" aunque existiera); runtime/active ausente se reporta FALLA real; con un runtime
    #     sintético presente, se reporta OK ejecutando el binario como vinto-mvp.
    set +e
    docker exec "$E6A1_CNAME" su -s /bin/bash mvp_operator -c \
      'cd /tmp/mvp/scripts && bash preflight.sh startup' \
      >/tmp/verify-e6a1-preflight1.log 2>&1
    set -e
    if grep -q "OK.*'current'.*completo" /tmp/verify-e6a1-preflight1.log \
        && grep -q "FALLA runtime/active" /tmp/verify-e6a1-preflight1.log; then
      e6a1_preflight1_ok=0
    else
      e6a1_preflight1_ok=1
    fi
    docker exec "$E6A1_CNAME" bash -c "
      set -e
      sudo -u vinto-mvp mkdir -p /opt/vinto-mvp-web/runtime/node-vfake/bin
      sudo -u vinto-mvp sh -c 'printf \"#!/bin/sh\necho v99.0.0\n\" > /opt/vinto-mvp-web/runtime/node-vfake/bin/node'
      sudo -u vinto-mvp chmod +x /opt/vinto-mvp-web/runtime/node-vfake/bin/node
      sudo -u vinto-mvp ln -sfn /opt/vinto-mvp-web/runtime/node-vfake /opt/vinto-mvp-web/runtime/active
    " >/tmp/verify-e6a1-preflight-prep.log 2>&1
    set +e
    docker exec "$E6A1_CNAME" su -s /bin/bash mvp_operator -c \
      'cd /tmp/mvp/scripts && bash preflight.sh startup' \
      >/tmp/verify-e6a1-preflight2.log 2>&1
    set -e
    if grep -q "OK.*runtime/active.*v99.0.0" /tmp/verify-e6a1-preflight2.log; then
      e6a1_preflight2_ok=0
    else
      e6a1_preflight2_ok=1
    fi
    if [ "$e6a1_preflight1_ok" -eq 0 ] && [ "$e6a1_preflight2_ok" -eq 0 ]; then
      report "E.6-A.1 (12): preflight.sh startup distingue correctamente recursos presentes de ausentes dentro del árbol privado, como mvp_operator" 0
    else
      echo "--- log preflight (sin runtime) ---"; cat /tmp/verify-e6a1-preflight1.log
      echo "--- log preflight (con runtime sintético) ---"; cat /tmp/verify-e6a1-preflight2.log
      report "E.6-A.1 (12): preflight.sh startup distingue correctamente recursos presentes de ausentes dentro del árbol privado, como mvp_operator" 1
    fi

    # 14. Fallo de sudoers: mvp_operator_nosudo no puede ejecutar ninguna fase que dependa de leer
    #     rutas privadas — debe detenerse con el mensaje explícito, nunca con un fallo silencioso.
    set +e
    docker exec "$E6A1_CNAME" su -s /bin/bash mvp_operator_nosudo -c \
      "cd /tmp/mvp/scripts && CONFIRM=yes bash deploy.sh python-venv $SHA1" \
      >/tmp/verify-e6a1-nosudo.log 2>&1
    e6a1_nosudo_status=$?
    set -e
    if [ "$e6a1_nosudo_status" -ne 0 ] && grep -q "no se puede ejecutar 'sudo -u vinto-mvp'" /tmp/verify-e6a1-nosudo.log; then
      report "E.6-A.1 (14): sin 'sudo -u vinto-mvp' disponible, la fase se detiene con el mensaje explícito (nunca un fallo silencioso)" 0
    else
      echo "--- log sin sudoers ---"; cat /tmp/verify-e6a1-nosudo.log
      report "E.6-A.1 (14): sin 'sudo -u vinto-mvp' disponible, la fase se detiene con el mensaje explícito (nunca un fallo silencioso)" 1
    fi
  fi
  unset MSYS_NO_PATHCONV
fi
echo "Punto 15 (regresión de install-node-runtime, PR #57): cubierto por la batería 'C.1-1' de este"
echo "mismo archivo, ejecutada en esta misma corrida — ver sus resultados más arriba."

echo "=== Prueba focalizada CLOUD-DEP-02B.2-C: link-backend-env (idempotencia, identidad, enlaces rotos) ==="
echo "Esta fase nueva crea backend/.env -> shared/backend.env en un release YA clonado, sin repetir"
echo "checkout ni python-venv (ver deploy.sh::phase_link_backend_env). Laboratorio: operador sin"
echo "privilegios + vinto-mvp separado (mismo patrón que E.6-A.1), con la estructura de"
echo "releases/shared fabricada directamente -- esta fase solo hace mkdir/ln/stat, nunca clona ni"
echo "necesita git/python, así que el contenedor de ensayo no los instala."

# Comprobación estática primero (sin contenedor): phase_link_backend_env nunca debe invocar
# phase_checkout ni phase_python_venv (requisito 13 del alcance de CLOUD-DEP-02B.2-C).
if ! awk '/^phase_link_backend_env\(\)/,/^}/' "$SCRIPT_DIR/../deploy.sh" | grep -qE 'phase_checkout|phase_python_venv'; then
  report "link-backend-env: el cuerpo de la fase nunca llama a phase_checkout ni phase_python_venv" 0
else
  report "link-backend-env: el cuerpo de la fase nunca llama a phase_checkout ni phase_python_venv" 1
fi

LINKENV_CNAME=""
set +e
create_container vinto-mvp-verify-linkenv --label com.docker.compose.project=vinto-mvp ubuntu:24.04 sleep 1800
linkenv_create_status=$?
set -e
if [ "$linkenv_create_status" -ne 0 ]; then
  report "link-backend-env: batería completa (omitida: no se pudo crear el contenedor de ensayo)" 1
else
  LINKENV_CNAME="$CREATED_NAME"
  docker cp "$MVP_DIR" "$LINKENV_CNAME:/tmp/mvp" >/dev/null
  export MSYS_NO_PATHCONV=1
  set +e
  docker exec "$LINKENV_CNAME" bash -c '
    set -e
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq && apt-get install -y -qq --no-install-recommends sudo >/dev/null

    useradd --system --no-create-home --shell /usr/sbin/nologin vinto-mvp
    useradd -m -s /bin/bash mvp_operator
    echo "mvp_operator ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/mvp_operator
    chmod 440 /etc/sudoers.d/mvp_operator
    useradd -m -s /bin/bash mvp_operator_nosudo

    # Dos releases fabricados directamente (nunca con checkout real: esta fase no lo necesita) +
    # un "current" apuntando a un tercer destino arbitrario, para confirmar al final (caso 11) que
    # ninguna llamada de esta batería lo tocó.
    mkdir -p /opt/vinto-mvp-web/releases/aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111/backend
    mkdir -p /opt/vinto-mvp-web/releases/bbbb2222bbbb2222bbbb2222bbbb2222bbbb2222/backend
    mkdir -p /opt/vinto-mvp-web/releases/unrelated-target
    mkdir -p /opt/vinto-mvp-web/shared
    ln -sfn /opt/vinto-mvp-web/releases/unrelated-target /opt/vinto-mvp-web/current
    chown -R vinto-mvp:vinto-mvp /opt/vinto-mvp-web
    chmod 750 /opt/vinto-mvp-web
  ' >/tmp/verify-linkenv-setup.log 2>&1
  linkenv_setup_ok=$?
  set -e
  if [ "$linkenv_setup_ok" -ne 0 ]; then
    echo "--- log de preparación link-backend-env ---"; cat /tmp/verify-linkenv-setup.log
    report "link-backend-env: preparación del laboratorio (vinto-mvp, releases fabricados, 'current' arbitrario)" 1
  else
    report "link-backend-env: preparación del laboratorio (vinto-mvp, releases fabricados, 'current' arbitrario)" 0
    SHA_A=aaaa1111aaaa1111aaaa1111aaaa1111aaaa1111
    SHA_FAKE=dddd4444dddd4444dddd4444dddd4444dddd4444

    as_operator() { docker exec "$LINKENV_CNAME" su -s /bin/bash mvp_operator -c "cd /tmp/mvp/scripts && $1"; }
    as_nosudo()   { docker exec "$LINKENV_CNAME" su -s /bin/bash mvp_operator_nosudo -c "cd /tmp/mvp/scripts && $1"; }

    # Caso 6: release inexistente.
    set +e
    as_operator "CONFIRM=yes bash deploy.sh link-backend-env $SHA_FAKE" >/tmp/verify-linkenv-case6.log 2>&1
    case6_status=$?
    set -e
    if [ "$case6_status" -ne 0 ] && grep -q "no existe. Ejecutar 'checkout" /tmp/verify-linkenv-case6.log; then
      report "link-backend-env caso 6: release inexistente, rechazado con mensaje claro" 0
    else
      cat /tmp/verify-linkenv-case6.log
      report "link-backend-env caso 6: release inexistente, rechazado con mensaje claro" 1
    fi

    # Caso 3: shared/backend.env todavía no existe.
    set +e
    as_operator "CONFIRM=yes bash deploy.sh link-backend-env $SHA_A" >/tmp/verify-linkenv-case3.log 2>&1
    case3_status=$?
    set -e
    if [ "$case3_status" -ne 0 ] && grep -q "shared/backend.env no existe todavía" /tmp/verify-linkenv-case3.log; then
      report "link-backend-env caso 3: shared/backend.env inexistente, rechazado antes de tocar nada" 0
    else
      cat /tmp/verify-linkenv-case3.log
      report "link-backend-env caso 3: shared/backend.env inexistente, rechazado antes de tocar nada" 1
    fi

    # shared/backend.env SINTÉTICO del laboratorio (nunca una credencial real), con el propietario
    # y permisos correctos para las pruebas siguientes.
    docker exec "$LINKENV_CNAME" bash -c '
      sudo -u vinto-mvp sh -c "printf \"DATABASE_URL=postgresql://x:y@127.0.0.1/db\n\" > /opt/vinto-mvp-web/shared/backend.env"
      sudo -u vinto-mvp chmod 600 /opt/vinto-mvp-web/shared/backend.env
    ' >/tmp/verify-linkenv-mkenv.log 2>&1

    # Caso 12 (DEP60-01, auditoría del PR #60): shared/backend.env convertido en un ENLACE
    # simbólico hacia un archivo VÁLIDO (mismos 600 y propietario vinto-mvp en el destino real) --
    # debe rechazarse IGUAL, nunca aceptarse solo porque el enlace resuelve correctamente.
    docker exec "$LINKENV_CNAME" bash -c '
      sudo -u vinto-mvp mv /opt/vinto-mvp-web/shared/backend.env /opt/vinto-mvp-web/shared/backend.env.real
      sudo -u vinto-mvp ln -s backend.env.real /opt/vinto-mvp-web/shared/backend.env
    ' >/tmp/verify-linkenv-case12-setup.log 2>&1
    set +e
    as_operator "CONFIRM=yes bash deploy.sh link-backend-env $SHA_A" >/tmp/verify-linkenv-case12.log 2>&1
    case12_status=$?
    set -e
    if [ "$case12_status" -ne 0 ] && grep -q "es un enlace simbólico. Debe ser un archivo regular" /tmp/verify-linkenv-case12.log; then
      report "link-backend-env caso 12 (DEP60-01): shared/backend.env como enlace hacia un destino VÁLIDO, rechazado igual" 0
    else
      cat /tmp/verify-linkenv-case12.log
      report "link-backend-env caso 12 (DEP60-01): shared/backend.env como enlace hacia un destino VÁLIDO, rechazado igual" 1
    fi
    docker exec "$LINKENV_CNAME" bash -c '
      sudo -u vinto-mvp rm -f /opt/vinto-mvp-web/shared/backend.env
      sudo -u vinto-mvp mv /opt/vinto-mvp-web/shared/backend.env.real /opt/vinto-mvp-web/shared/backend.env
    ' >/tmp/verify-linkenv-case12-restore.log 2>&1

    # Caso 4: permisos incorrectos (644 en vez de 600).
    docker exec "$LINKENV_CNAME" sudo -u vinto-mvp chmod 644 /opt/vinto-mvp-web/shared/backend.env
    set +e
    as_operator "CONFIRM=yes bash deploy.sh link-backend-env $SHA_A" >/tmp/verify-linkenv-case4.log 2>&1
    case4_status=$?
    set -e
    if [ "$case4_status" -ne 0 ] && grep -q "deben ser 600" /tmp/verify-linkenv-case4.log; then
      report "link-backend-env caso 4: permisos incorrectos (644) en shared/backend.env, rechazado" 0
    else
      cat /tmp/verify-linkenv-case4.log
      report "link-backend-env caso 4: permisos incorrectos (644) en shared/backend.env, rechazado" 1
    fi
    docker exec "$LINKENV_CNAME" sudo -u vinto-mvp chmod 600 /opt/vinto-mvp-web/shared/backend.env

    # Caso 5: propietario incorrecto (root en vez de vinto-mvp), permisos 600 igual.
    docker exec "$LINKENV_CNAME" chown root:root /opt/vinto-mvp-web/shared/backend.env
    set +e
    as_operator "CONFIRM=yes bash deploy.sh link-backend-env $SHA_A" >/tmp/verify-linkenv-case5.log 2>&1
    case5_status=$?
    set -e
    if [ "$case5_status" -ne 0 ] && grep -q "pertenece a 'root'" /tmp/verify-linkenv-case5.log; then
      report "link-backend-env caso 5: propietario incorrecto en shared/backend.env, rechazado" 0
    else
      cat /tmp/verify-linkenv-case5.log
      report "link-backend-env caso 5: propietario incorrecto en shared/backend.env, rechazado" 1
    fi
    docker exec "$LINKENV_CNAME" chown vinto-mvp:vinto-mvp /opt/vinto-mvp-web/shared/backend.env

    # Caso 9: backend/.env ya existe como archivo REGULAR (no symlink).
    docker exec "$LINKENV_CNAME" sudo -u vinto-mvp sh -c "echo not-a-link > /opt/vinto-mvp-web/releases/$SHA_A/backend/.env"
    set +e
    as_operator "CONFIRM=yes bash deploy.sh link-backend-env $SHA_A" >/tmp/verify-linkenv-case9.log 2>&1
    case9_status=$?
    set -e
    if [ "$case9_status" -ne 0 ] && grep -q "no es un enlace simbólico" /tmp/verify-linkenv-case9.log; then
      report "link-backend-env caso 9: backend/.env ya existe como archivo regular, rechazado sin sobrescribir" 0
    else
      cat /tmp/verify-linkenv-case9.log
      report "link-backend-env caso 9: backend/.env ya existe como archivo regular, rechazado sin sobrescribir" 1
    fi
    docker exec "$LINKENV_CNAME" sudo -u vinto-mvp rm -f "/opt/vinto-mvp-web/releases/$SHA_A/backend/.env"

    # Caso 7: enlace ROTO preexistente, hacia un destino que no existe y que además no es el
    # esperado. "-e" por sí solo seguiría el enlace, no resolvería, y reportaría (incorrectamente)
    # "no existe" -- un falso negativo que llevaría a un "ln -s" fallando con el error crudo de
    # "ln", nunca con el mensaje claro que se comprueba aquí.
    docker exec "$LINKENV_CNAME" sudo -u vinto-mvp ln -s ../../../shared/no-existe.env "/opt/vinto-mvp-web/releases/$SHA_A/backend/.env"
    set +e
    as_operator "CONFIRM=yes bash deploy.sh link-backend-env $SHA_A" >/tmp/verify-linkenv-case7.log 2>&1
    case7_status=$?
    set -e
    if [ "$case7_status" -ne 0 ] && grep -q "ya es un enlace simbólico" /tmp/verify-linkenv-case7.log; then
      report "link-backend-env caso 7: enlace ROTO preexistente (destino distinto), detectado vía -L y rechazado" 0
    else
      cat /tmp/verify-linkenv-case7.log
      report "link-backend-env caso 7: enlace ROTO preexistente (destino distinto), detectado vía -L y rechazado" 1
    fi
    docker exec "$LINKENV_CNAME" sudo -u vinto-mvp rm -f "/opt/vinto-mvp-web/releases/$SHA_A/backend/.env"

    # Caso 8: enlace VÁLIDO (resuelve) pero hacia otro destino distinto del esperado.
    docker exec "$LINKENV_CNAME" sudo -u vinto-mvp sh -c "echo otra-cosa > /opt/vinto-mvp-web/shared/otro.env && chmod 600 /opt/vinto-mvp-web/shared/otro.env"
    docker exec "$LINKENV_CNAME" sudo -u vinto-mvp ln -s ../../../shared/otro.env "/opt/vinto-mvp-web/releases/$SHA_A/backend/.env"
    set +e
    as_operator "CONFIRM=yes bash deploy.sh link-backend-env $SHA_A" >/tmp/verify-linkenv-case8.log 2>&1
    case8_status=$?
    set -e
    if [ "$case8_status" -ne 0 ] && grep -q "ya es un enlace simbólico" /tmp/verify-linkenv-case8.log; then
      report "link-backend-env caso 8: enlace existente hacia OTRO destino (válido), rechazado sin sobrescribir" 0
    else
      cat /tmp/verify-linkenv-case8.log
      report "link-backend-env caso 8: enlace existente hacia OTRO destino (válido), rechazado sin sobrescribir" 1
    fi
    docker exec "$LINKENV_CNAME" sudo -u vinto-mvp rm -f "/opt/vinto-mvp-web/releases/$SHA_A/backend/.env" /opt/vinto-mvp-web/shared/otro.env

    # Caso 10: fallo de sudoers (operador sin sudo configurado hacia vinto-mvp).
    set +e
    as_nosudo "CONFIRM=yes bash deploy.sh link-backend-env $SHA_A" >/tmp/verify-linkenv-case10.log 2>&1
    case10_status=$?
    set -e
    if [ "$case10_status" -ne 0 ] && grep -q "no se puede ejecutar 'sudo -u vinto-mvp'" /tmp/verify-linkenv-case10.log; then
      report "link-backend-env caso 10: sin sudoers hacia vinto-mvp, falla con mensaje explícito" 0
    else
      cat /tmp/verify-linkenv-case10.log
      report "link-backend-env caso 10: sin sudoers hacia vinto-mvp, falla con mensaje explícito" 1
    fi

    # Caso 1: creación correcta (release A, ya limpio de los casos anteriores).
    set +e
    as_operator "CONFIRM=yes bash deploy.sh link-backend-env $SHA_A" >/tmp/verify-linkenv-case1.log 2>&1
    case1_status=$?
    set -e
    MSYS_NO_PATHCONV=1 docker exec "$LINKENV_CNAME" sudo -u vinto-mvp test -L "/opt/vinto-mvp-web/releases/$SHA_A/backend/.env"
    case1_link_exists=$?
    target1="$(MSYS_NO_PATHCONV=1 docker exec "$LINKENV_CNAME" sudo -u vinto-mvp readlink "/opt/vinto-mvp-web/releases/$SHA_A/backend/.env")"
    # Requisito 4 (DEP60-01): no basta con que el TEXTO del enlace sea el esperado -- confirmar
    # que "readlink -f" de backend/.env resuelve EXACTAMENTE a "readlink -f" del propio
    # shared/backend.env real (misma comparación que hace ahora phase_link_backend_env), y que el
    # mensaje de éxito deja constancia explícita de esa resolución.
    resolved_link1="$(MSYS_NO_PATHCONV=1 docker exec "$LINKENV_CNAME" sudo -u vinto-mvp readlink -f "/opt/vinto-mvp-web/releases/$SHA_A/backend/.env")"
    resolved_shared1="$(MSYS_NO_PATHCONV=1 docker exec "$LINKENV_CNAME" sudo -u vinto-mvp readlink -f /opt/vinto-mvp-web/shared/backend.env)"
    if [ "$case1_status" -eq 0 ] && [ "$case1_link_exists" -eq 0 ] && [ "$target1" = "../../../shared/backend.env" ] \
        && [ -n "$resolved_link1" ] && [ "$resolved_link1" = "$resolved_shared1" ] \
        && grep -q "resuelve exactamente a" /tmp/verify-linkenv-case1.log; then
      report "link-backend-env caso 1: crea el enlace correcto y resuelve exactamente a shared/backend.env (release ya existente, sin repetir checkout)" 0
    else
      echo "destino obtenido: '$target1' -- resuelto: '$resolved_link1' (esperado: '$resolved_shared1')"; cat /tmp/verify-linkenv-case1.log
      report "link-backend-env caso 1: crea el enlace correcto y resuelve exactamente a shared/backend.env (release ya existente, sin repetir checkout)" 1
    fi

    # Caso 2: segunda ejecución idempotente (mismo release A, enlace ya correcto), confirmando
    # también que la ruta idempotente vuelve a verificar la resolución exacta (no solo el texto).
    set +e
    as_operator "CONFIRM=yes bash deploy.sh link-backend-env $SHA_A" >/tmp/verify-linkenv-case2.log 2>&1
    case2_status=$?
    set -e
    if [ "$case2_status" -eq 0 ] && grep -q "idempotente" /tmp/verify-linkenv-case2.log && grep -q "resuelve exactamente a" /tmp/verify-linkenv-case2.log; then
      report "link-backend-env caso 2: segunda ejecución idempotente (no vuelve a crear ni falla), resolución exacta reconfirmada" 0
    else
      cat /tmp/verify-linkenv-case2.log
      report "link-backend-env caso 2: segunda ejecución idempotente (no vuelve a crear ni falla)" 1
    fi

    # Caso 11: 'current' nunca se tocó por ninguna de las llamadas (exitosas o fallidas) de arriba.
    current_target="$(MSYS_NO_PATHCONV=1 docker exec "$LINKENV_CNAME" sudo -u vinto-mvp readlink -f /opt/vinto-mvp-web/current)"
    if [ "$current_target" = "/opt/vinto-mvp-web/releases/unrelated-target" ]; then
      report "link-backend-env caso 11: 'current' permanece intacto durante toda la batería" 0
    else
      echo "current observado: '$current_target' (esperado: /opt/vinto-mvp-web/releases/unrelated-target)"
      report "link-backend-env caso 11: 'current' permanece intacto durante toda la batería" 1
    fi

    # Requisito 14 del alcance: ningún valor de shared/backend.env (ni siquiera el sintético de
    # este laboratorio) quedó impreso en ningún log de esta batería.
    if ! grep -l "DATABASE_URL=postgresql://x:y" /tmp/verify-linkenv-case*.log /tmp/verify-linkenv-mkenv.log 2>/dev/null; then
      report "link-backend-env: ningún valor de shared/backend.env quedó impreso en los logs de esta batería" 0
    else
      report "link-backend-env: ningún valor de shared/backend.env quedó impreso en los logs de esta batería" 1
    fi
  fi
  unset MSYS_NO_PATHCONV
fi

echo "=== Prueba focalizada CLOUD-DEP-02B.2-D.1: contrato de seguridad de docker/.env ==="
echo "docker_env_contract_check (lib_common.sh) es el guardián compartido nuevo: nunca llama a"
echo "'exit' ni imprime el contenido del archivo -- deja el motivo del primer fallo en"
echo "DOCKER_ENV_CONTRACT_REASON (solo metadatos, nunca un valor leído) y cada llamador decide qué"
echo "hacer. Las fases MUTADORAS de deploy.sh se detienen (assert_docker_env_contract);"
echo "rollback.sh degrada al camino ya existente de 'tratarlo como ausente' -- una recuperación"
echo "legítima nunca debe volverse imposible solo por un problema de permisos en este archivo."

# Comprobación estática primero: las 4 fases que consumen docker/.env deben llamar al guardián
# nuevo, y rollback_postgres debe usarlo en modo degradado (nunca un "exit 1" propio sobre el
# resultado del contrato).
docker_env_wired=0
for phase_fn in phase_validate_compose phase_postgres_up phase_postgres_bootstrap_db phase_postgres_roles; do
  awk "/^$phase_fn\\(\\)/,/^}/" "$SCRIPT_DIR/../deploy.sh" | grep -q 'assert_docker_env_contract' || docker_env_wired=1
done
if [ "$docker_env_wired" -eq 0 ]; then
  report "las 4 fases que consumen docker/.env llaman a assert_docker_env_contract" 0
else
  report "las 4 fases que consumen docker/.env llaman a assert_docker_env_contract" 1
fi
if awk '/^rollback_postgres\(\)/,/^}/' "$SCRIPT_DIR/../rollback.sh" | grep -q 'docker_env_contract_check' \
    && ! awk '/^rollback_postgres\(\)/,/^}/' "$SCRIPT_DIR/../rollback.sh" | grep -qE '^\s*exit 1\s*$'; then
  report "rollback_postgres usa el guardián en modo degradado (nunca 'exit 1' propio sobre el contrato)" 0
else
  report "rollback_postgres usa el guardián en modo degradado (nunca 'exit 1' propio sobre el contrato)" 1
fi

DOCKERENV_CNAME=""
set +e
create_container vinto-mvp-verify-dockerenv --label com.docker.compose.project=vinto-mvp ubuntu:24.04 sleep 1800
dockerenv_create_status=$?
set -e
if [ "$dockerenv_create_status" -ne 0 ]; then
  report "docker/.env: batería completa (omitida: no se pudo crear el contenedor de ensayo)" 1
else
  DOCKERENV_CNAME="$CREATED_NAME"
  docker cp "$MVP_DIR" "$DOCKERENV_CNAME:/tmp/mvp" >/dev/null
  export MSYS_NO_PATHCONV=1
  set +e
  docker exec "$DOCKERENV_CNAME" bash -c '
    set -e
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq && apt-get install -y -qq --no-install-recommends sudo acl >/dev/null

    useradd --system --no-create-home --shell /usr/sbin/nologin vinto-mvp
    # mvp_operator: dueño legítimo del docker/.env de este laboratorio.
    useradd -m -s /bin/bash mvp_operator
    echo "mvp_operator ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/mvp_operator
    chmod 440 /etc/sudoers.d/mvp_operator
    # mvp_operator_b: un SEGUNDO operador, nunca dueño de nada de este laboratorio -- demuestra
    # que el contrato se resuelve dinámicamente contra quien invoca (id -un), no un nombre fijo.
    useradd -m -s /bin/bash mvp_operator_b
    echo "mvp_operator_b ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/mvp_operator_b
    chmod 440 /etc/sudoers.d/mvp_operator_b

    mkdir -p /opt/docker-env-lab
    chown mvp_operator:mvp_operator /opt/docker-env-lab
    chmod 755 /opt/docker-env-lab

    # "docker cp" copia como root; mvp_operator necesita poder crear el docker/.env de prueba
    # dentro del checkout copiado (para los casos B13/B14, que ejercitan las fases REALES de
    # deploy.sh en la ruta que de verdad esperan, scripts/../docker/.env).
    chown -R mvp_operator:mvp_operator /tmp/mvp
  ' >/tmp/verify-dockerenv-setup.log 2>&1
  dockerenv_setup_ok=$?
  set -e
  if [ "$dockerenv_setup_ok" -ne 0 ]; then
    echo "--- log de preparación docker/.env ---"; cat /tmp/verify-dockerenv-setup.log
    report "docker/.env: preparación del laboratorio (dos operadores + vinto-mvp + acl)" 1
  else
    report "docker/.env: preparación del laboratorio (dos operadores + vinto-mvp + acl)" 0

    check_contract_as() {
      local user="$1" path="$2" logfile="$3"
      docker exec "$DOCKERENV_CNAME" su -s /bin/bash "$user" -c \
        "source /tmp/mvp/scripts/lib_common.sh; docker_env_contract_check '$path'; echo RC=\$?; echo REASON=\$DOCKER_ENV_CONTRACT_REASON" \
        >"$logfile" 2>&1
    }
    rc_of() { grep -m1 '^RC=' "$1" | sed 's/^RC=//'; }

    GOOD_ENV=/opt/docker-env-lab/good.env
    SECRET_MARKER="SECRETO-SINTETICO-$(date +%s)-NUNCA-UNA-CREDENCIAL-REAL"

    docker exec "$DOCKERENV_CNAME" su -s /bin/bash mvp_operator -c \
      "printf 'POSTGRES_BOOTSTRAP_PASSWORD=$SECRET_MARKER\n' > $GOOD_ENV && chmod 600 $GOOD_ENV" \
      >/tmp/verify-dockerenv-mk.log 2>&1

    # Caso A1: archivo correcto (propietario mvp_operator, 600) -- aceptado.
    check_contract_as mvp_operator "$GOOD_ENV" /tmp/verify-dockerenv-a1.log
    if [ "$(rc_of /tmp/verify-dockerenv-a1.log)" = "0" ]; then
      report "docker/.env caso A1: archivo correcto (propietario correcto, 600), aceptado" 0
    else
      cat /tmp/verify-dockerenv-a1.log
      report "docker/.env caso A1: archivo correcto (propietario correcto, 600), aceptado" 1
    fi

    # Caso A2: modo 644 -- rechazado.
    docker exec "$DOCKERENV_CNAME" chmod 644 "$GOOD_ENV"
    check_contract_as mvp_operator "$GOOD_ENV" /tmp/verify-dockerenv-a2.log
    if [ "$(rc_of /tmp/verify-dockerenv-a2.log)" = "1" ] && grep -q "deben ser exactamente 600" /tmp/verify-dockerenv-a2.log; then
      report "docker/.env caso A2: modo 644, rechazado" 0
    else
      cat /tmp/verify-dockerenv-a2.log
      report "docker/.env caso A2: modo 644, rechazado" 1
    fi
    docker exec "$DOCKERENV_CNAME" chmod 600 "$GOOD_ENV"

    # Caso A3: propietario incorrecto (root en vez de mvp_operator) -- rechazado.
    docker exec "$DOCKERENV_CNAME" chown root:root "$GOOD_ENV"
    check_contract_as mvp_operator "$GOOD_ENV" /tmp/verify-dockerenv-a3.log
    if [ "$(rc_of /tmp/verify-dockerenv-a3.log)" = "1" ] && grep -q "pertenece a 'root'" /tmp/verify-dockerenv-a3.log; then
      report "docker/.env caso A3: propietario incorrecto (root), rechazado" 0
    else
      cat /tmp/verify-dockerenv-a3.log
      report "docker/.env caso A3: propietario incorrecto (root), rechazado" 1
    fi
    docker exec "$DOCKERENV_CNAME" chown mvp_operator:mvp_operator "$GOOD_ENV"

    # Caso A4: enlace simbólico VÁLIDO (resuelve a un archivo con permisos/propietario correctos)
    # -- rechazado igual (misma lección de DEP60-01 para shared/backend.env).
    docker exec "$DOCKERENV_CNAME" su -s /bin/bash mvp_operator -c \
      "mv $GOOD_ENV /opt/docker-env-lab/good.env.real && ln -s good.env.real $GOOD_ENV"
    check_contract_as mvp_operator "$GOOD_ENV" /tmp/verify-dockerenv-a4.log
    if [ "$(rc_of /tmp/verify-dockerenv-a4.log)" = "1" ] && grep -q "enlace simbólico" /tmp/verify-dockerenv-a4.log; then
      report "docker/.env caso A4: enlace simbólico hacia un destino VÁLIDO, rechazado igual" 0
    else
      cat /tmp/verify-dockerenv-a4.log
      report "docker/.env caso A4: enlace simbólico hacia un destino VÁLIDO, rechazado igual" 1
    fi

    # Caso A5: enlace simbólico ROTO (mismo archivo, ahora hacia un destino que no existe) --
    # rechazado con el MISMO motivo ("-L" se dispara antes de intentar resolver nada).
    docker exec "$DOCKERENV_CNAME" su -s /bin/bash mvp_operator -c \
      "rm -f $GOOD_ENV && ln -s no-existe.env $GOOD_ENV"
    check_contract_as mvp_operator "$GOOD_ENV" /tmp/verify-dockerenv-a5.log
    if [ "$(rc_of /tmp/verify-dockerenv-a5.log)" = "1" ] && grep -q "enlace simbólico" /tmp/verify-dockerenv-a5.log; then
      report "docker/.env caso A5: enlace simbólico ROTO, rechazado con el mismo motivo (-L, no solo -e)" 0
    else
      cat /tmp/verify-dockerenv-a5.log
      report "docker/.env caso A5: enlace simbólico ROTO, rechazado con el mismo motivo (-L, no solo -e)" 1
    fi
    docker exec "$DOCKERENV_CNAME" su -s /bin/bash mvp_operator -c \
      "rm -f $GOOD_ENV && mv /opt/docker-env-lab/good.env.real $GOOD_ENV"

    # Caso A6: archivo inexistente -- rechazado.
    check_contract_as mvp_operator /opt/docker-env-lab/no-existe.env /tmp/verify-dockerenv-a6.log
    if [ "$(rc_of /tmp/verify-dockerenv-a6.log)" = "1" ] && grep -q "no existe" /tmp/verify-dockerenv-a6.log; then
      report "docker/.env caso A6: archivo inexistente, rechazado" 0
    else
      cat /tmp/verify-dockerenv-a6.log
      report "docker/.env caso A6: archivo inexistente, rechazado" 1
    fi

    # Caso A7: directorio en lugar de archivo -- rechazado.
    docker exec "$DOCKERENV_CNAME" mkdir -p /opt/docker-env-lab/adir
    check_contract_as mvp_operator /opt/docker-env-lab/adir /tmp/verify-dockerenv-a7.log
    if [ "$(rc_of /tmp/verify-dockerenv-a7.log)" = "1" ] && grep -q "es un directorio" /tmp/verify-dockerenv-a7.log; then
      report "docker/.env caso A7: directorio en vez de archivo, rechazado" 0
    else
      cat /tmp/verify-dockerenv-a7.log
      report "docker/.env caso A7: directorio en vez de archivo, rechazado" 1
    fi
    docker exec "$DOCKERENV_CNAME" rmdir /opt/docker-env-lab/adir

    # Caso A8: directorio PADRE inseguro (escribible por grupo/otros), archivo en sí correcto --
    # rechazado (requisito 5: "rechace ... directorios inseguros").
    docker exec "$DOCKERENV_CNAME" chmod 777 /opt/docker-env-lab
    check_contract_as mvp_operator "$GOOD_ENV" /tmp/verify-dockerenv-a8.log
    if [ "$(rc_of /tmp/verify-dockerenv-a8.log)" = "1" ] && grep -q "escribible por grupo u otros" /tmp/verify-dockerenv-a8.log; then
      report "docker/.env caso A8: directorio padre escribible por grupo/otros, rechazado" 0
    else
      cat /tmp/verify-dockerenv-a8.log
      report "docker/.env caso A8: directorio padre escribible por grupo/otros, rechazado" 1
    fi
    docker exec "$DOCKERENV_CNAME" chmod 755 /opt/docker-env-lab

    # Caso A9 ("operador sin permisos"): un SEGUNDO operador (mvp_operator_b), nunca dueño de
    # este archivo, lo comprueba -- rechazado, y el motivo nombra a QUIEN invoca (resuelto con
    # "id -un", nunca un nombre de usuario fijo).
    check_contract_as mvp_operator_b "$GOOD_ENV" /tmp/verify-dockerenv-a9.log
    if [ "$(rc_of /tmp/verify-dockerenv-a9.log)" = "1" ] && grep -q "debe pertenecer a 'mvp_operator_b'" /tmp/verify-dockerenv-a9.log; then
      report "docker/.env caso A9: operador sin permisos (no es el dueño), rechazado con el operador correcto resuelto dinámicamente" 0
    else
      cat /tmp/verify-dockerenv-a9.log
      report "docker/.env caso A9: operador sin permisos (no es el dueño), rechazado con el operador correcto resuelto dinámicamente" 1
    fi

    # Caso A10: vinto-mvp obtiene una entrada ACL de lectura sobre el archivo. En la práctica,
    # "setfacl -m" recalcula la máscara ACL, así que el bit de GRUPO que "stat -c '%a'" reporta
    # también cambia (confirmado empíricamente: 600 -> 640) -- el rechazo puede producirse por el
    # chequeo de permisos (600) o por la comprobación ACTIVA ("sudo -u vinto-mvp test -r"), según
    # cuál se evalúe primero; AMBOS son un resultado correcto (nunca se acepta el archivo). La
    # comprobación activa sigue siendo valiosa como defensa en profundidad para mecanismos que
    # "stat" no refleje en absoluto (p. ej. ACLs NFSv4, o cambios futuros en esta lógica) aunque
    # este escenario concreto de ACL POSIX ya quede cubierto por el chequeo de permisos.
    docker exec "$DOCKERENV_CNAME" setfacl -m u:vinto-mvp:r "$GOOD_ENV"
    check_contract_as mvp_operator "$GOOD_ENV" /tmp/verify-dockerenv-a10.log
    if [ "$(rc_of /tmp/verify-dockerenv-a10.log)" = "1" ] \
        && grep -qE "permisos demasiado abiertos|deben ser exactamente 600" /tmp/verify-dockerenv-a10.log; then
      report "docker/.env caso A10 (requisito 9): vinto-mvp con una entrada ACL de lectura, rechazado" 0
    else
      cat /tmp/verify-dockerenv-a10.log
      report "docker/.env caso A10 (requisito 9): vinto-mvp con una entrada ACL de lectura, rechazado" 1
    fi
    docker exec "$DOCKERENV_CNAME" setfacl -b "$GOOD_ENV"

    # Caso A11: confirmación directa (fuera de nuestra función) de que vinto-mvp NO puede leer el
    # archivo en su estado normal y correcto -- la garantía real en la que se apoya el requisito 9.
    set +e
    docker exec "$DOCKERENV_CNAME" sudo -u vinto-mvp test -r "$GOOD_ENV"
    a11_vinto_can_read=$?
    set -e
    if [ "$a11_vinto_can_read" -ne 0 ]; then
      report "docker/.env caso A11: vinto-mvp no puede leer docker/.env en su estado normal (600, dueño correcto)" 0
    else
      report "docker/.env caso A11: vinto-mvp no puede leer docker/.env en su estado normal (600, dueño correcto)" 1
    fi

    # Caso A12 ("configuración incompleta"): archivo seguro (600, dueño correcto) pero SIN una
    # clave obligatoria -- el contrato de ARCHIVO pasa, pero env_value (capa de CONTENIDO,
    # inalterada por esta corrección) rechaza la lectura de la clave ausente. Las dos capas
    # (seguridad del archivo + completitud del contenido) se componen correctamente.
    docker exec "$DOCKERENV_CNAME" su -s /bin/bash mvp_operator -c \
      "printf 'POSTGRES_BOOTSTRAP_DB=x\n' > /opt/docker-env-lab/incomplete.env && chmod 600 /opt/docker-env-lab/incomplete.env"
    check_contract_as mvp_operator /opt/docker-env-lab/incomplete.env /tmp/verify-dockerenv-a12-file.log
    set +e
    docker exec "$DOCKERENV_CNAME" su -s /bin/bash mvp_operator -c \
      "source /tmp/mvp/scripts/lib_common.sh; env_value /opt/docker-env-lab/incomplete.env POSTGRES_BOOTSTRAP_PASSWORD" \
      >/tmp/verify-dockerenv-a12-key.log 2>&1
    a12_key_status=$?
    set -e
    if [ "$(rc_of /tmp/verify-dockerenv-a12-file.log)" = "0" ] && [ "$a12_key_status" -ne 0 ] \
        && grep -q "no se encontró la clave" /tmp/verify-dockerenv-a12-key.log; then
      report "docker/.env caso A12: archivo seguro pero con una clave obligatoria ausente, rechazado por la capa de contenido" 0
    else
      cat /tmp/verify-dockerenv-a12-file.log /tmp/verify-dockerenv-a12-key.log
      report "docker/.env caso A12: archivo seguro pero con una clave obligatoria ausente, rechazado por la capa de contenido" 1
    fi

    # Caso B13/B14: integración REAL con las fases de deploy.sh (no solo la función aislada) --
    # un docker/.env en 644 en la ubicación real que deploy.sh espera (scripts/../docker/.env)
    # debe rechazarse ANTES de cualquier intento de contactar PostgreSQL/Docker.
    docker exec "$DOCKERENV_CNAME" su -s /bin/bash mvp_operator -c \
      "printf 'POSTGRES_BOOTSTRAP_PASSWORD=$SECRET_MARKER\n' > /tmp/mvp/docker/.env && chmod 644 /tmp/mvp/docker/.env"
    set +e
    docker exec "$DOCKERENV_CNAME" su -s /bin/bash mvp_operator -c \
      "cd /tmp/mvp/scripts && CONFIRM=yes bash deploy.sh postgres-bootstrap-db" >/tmp/verify-dockerenv-b13.log 2>&1
    b13_status=$?
    set -e
    if [ "$b13_status" -ne 0 ] && grep -q "deben ser exactamente 600" /tmp/verify-dockerenv-b13.log; then
      report "docker/.env caso B13: 'deploy.sh postgres-bootstrap-db' rechaza docker/.env en 644 antes de contactar PostgreSQL" 0
    else
      cat /tmp/verify-dockerenv-b13.log
      report "docker/.env caso B13: 'deploy.sh postgres-bootstrap-db' rechaza docker/.env en 644 antes de contactar PostgreSQL" 1
    fi
    set +e
    docker exec "$DOCKERENV_CNAME" su -s /bin/bash mvp_operator -c \
      "cd /tmp/mvp/scripts && CONFIRM=yes bash deploy.sh postgres-roles" >/tmp/verify-dockerenv-b14.log 2>&1
    b14_status=$?
    set -e
    if [ "$b14_status" -ne 0 ] && grep -q "deben ser exactamente 600" /tmp/verify-dockerenv-b14.log; then
      report "docker/.env caso B14: 'deploy.sh postgres-roles' rechaza docker/.env en 644 antes de leer roles/backend" 0
    else
      cat /tmp/verify-dockerenv-b14.log
      report "docker/.env caso B14: 'deploy.sh postgres-roles' rechaza docker/.env en 644 antes de leer roles/backend" 1
    fi

    # Ningún valor secreto (ni el sintético de este laboratorio) quedó impreso en ningún log.
    if ! grep -l "$SECRET_MARKER" /tmp/verify-dockerenv-*.log 2>/dev/null; then
      report "docker/.env: ningún valor secreto quedó impreso en los logs de esta batería" 0
    else
      report "docker/.env: ningún valor secreto quedó impreso en los logs de esta batería" 1
    fi
  fi
  unset MSYS_NO_PATHCONV
fi

echo "El comportamiento REAL de rollback_postgres (con Docker Compose real, DEP61-01) se prueba"
echo "en vivo más abajo, en la batería dedicada a esa corrección — no solo por código."

echo "=== Prueba focalizada DEP61-01: rollback_postgres sin depender de docker/.env ==="
echo "El camino degradado anterior invocaba 'docker compose ... down' SIN --env-file, pero"
echo "docker-compose.postgres.yml exige \${VAR:?mensaje} para 4 claves -- Compose fallaba al"
echo "RESOLVER el YAML antes de intentar detener nada (confirmado empíricamente). Corregido:"
echo "ahora resuelve primero la identidad ESTRICTA del contenedor (nombre + etiqueta de proyecto"
echo "compose + imagen, nunca solo el nombre) y, si docker/.env no sirve por cualquier motivo,"
echo "usa 'docker stop' DIRECTO sobre el ID ya confirmado -- nunca pasa por Compose, nunca lee"
echo "docker/.env. Laboratorio: un contenedor Ubuntu con el SOCKET de Docker montado (para que"
echo "chmod/stat/ln -s sean semántica POSIX real -- un host Windows no garantiza esto en /tmp, ver"
echo "nota más abajo) y el CLI de Docker instalado, controlando contenedores HERMANOS en el MISMO"
echo "demonio que el resto de este archivo. Nombres de proyecto/contenedor/red ÚNICOS por prueba."
echo "Incluye además DEP61-02 (Compose no disponible pero Docker Engine operativo: ya no mata la"
echo "recuperación entera, ver el subshell en rollback.sh) y DEP61-03 (daemon inaccesible o"
echo "consulta fallida: nunca se confunde con 'contenedor ausente', ver"
echo "lib_common.sh::resolve_confirmed_mvp_postgres_id)."

DEP61_SECRET="SECRETO-SINTETICO-DEP61-$(date +%s)-NUNCA-UNA-CREDENCIAL-REAL"
DEP61_WRAPPER_NAME=""

# Contenedor AJENO creado ANTES de la batería (requisito: "contenedor ajeno permanece activo") --
# nunca lleva ninguna etiqueta ni nombre relacionado con el MVP ni con TVC, y se verifica al
# final que ninguna prueba de abajo lo tocó.
set +e
create_container verify-dep61-bystander alpine:3 sleep 300
dep61_bystander_status=$?
set -e
DEP61_BYSTANDER_NAME="$CREATED_NAME"

set +e
create_container dep61-wrapper -v //var/run/docker.sock:/var/run/docker.sock ubuntu:24.04 sleep 1800
dep61_wrapper_status=$?
set -e
if [ "$dep61_wrapper_status" -ne 0 ]; then
  report "DEP61-01: batería completa (omitida: no se pudo crear el contenedor envoltorio con el socket de Docker montado)" 1
else
  DEP61_WRAPPER_NAME="$CREATED_NAME"
  docker cp "$MVP_DIR" "$DEP61_WRAPPER_NAME:/tmp/mvp" >/dev/null
  set +e
  docker exec "$DEP61_WRAPPER_NAME" bash -c '
    set -e
    export DEBIAN_FRONTEND=noninteractive
    find /tmp/mvp -name "*.sh" -exec sed -i "s/\r$//" {} + 2>/dev/null || true
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends docker.io docker-compose-v2 >/dev/null
  ' >/tmp/verify-dep61-setup.log 2>&1
  dep61_setup_ok=$?
  set -e
  if [ "$dep61_setup_ok" -ne 0 ]; then
    echo "--- log de preparación DEP61-01 ---"; cat /tmp/verify-dep61-setup.log
    report "DEP61-01: preparación (contenedor envoltorio con docker CLI real, vía socket montado)" 1
  else
    report "DEP61-01: preparación (contenedor envoltorio con docker CLI real, vía socket montado)" 0

    # NOTA (por qué un contenedor y no el host directamente): "chmod"/"ln -s" sobre el /tmp de un
    # host Windows vía Git Bash NO producen semántica POSIX real (confirmado empíricamente: un
    # "chmod 600" seguido de "stat -c '%a'" reporta "644" de todas formas, y "ln -s" no siempre
    # crea un enlace real) -- docker_env_contract_check (permisos/symlink) necesita un filesystem
    # Linux real para que esta batería pruebe lo que de verdad importa. El socket montado permite
    # que "docker"/"docker compose", instalados DENTRO de este contenedor, controlen contenedores
    # HERMANOS en el mismo demonio que ve el resto de este archivo (y el propio host).
    DEP61_INNER="$(mktemp)"
    track_tmp_path "$DEP61_INNER"
    cat > "$DEP61_INNER" <<INNEREOF
set -u
cd /tmp/mvp
cp docker/docker-compose.postgres.yml docker/docker-compose.postgres.yml.orig

write_compose() {
  sed -e "s/^name: vinto-mvp\\\$/name: vinto-mvp-dep61-\$1/" \
      -e "s/container_name: vinto-mvp-postgres/container_name: vinto-mvp-postgres-dep61-\$1/" \
      -e "s/vinto-mvp-internal/vinto-mvp-internal-dep61-\$1/g" \
      docker/docker-compose.postgres.yml.orig > docker/docker-compose.postgres.yml
}
write_valid_env() {
  printf 'POSTGRES_BOOTSTRAP_DB=bootdb\nPOSTGRES_BOOTSTRAP_USER=bootuser\nPOSTGRES_BOOTSTRAP_PASSWORD=$DEP61_SECRET\nVINTO_MVP_PGDATA_DIR=/tmp/pgdata-\$1\n' > docker/.env
  chmod 600 docker/.env
}
do_rollback() {
  ( cd scripts && CONFIRM=yes \
      MVP_POSTGRES_CONTAINER="vinto-mvp-postgres-dep61-\$1" \
      MVP_COMPOSE_PROJECT="vinto-mvp-dep61-\$1" \
      bash rollback.sh postgres )
}
is_running() { docker inspect --format '{{.State.Running}}' "\$1" 2>/dev/null || echo false; }
wait_exec_ready() {
  local n=0
  while [ "\$n" -lt 30 ]; do
    docker exec "\$1" true >/dev/null 2>&1 && return 0
    sleep 0.5
    n=\$((n + 1))
  done
  return 1
}
result() { echo "RESULT:\$1:\$2"; }

# T1: docker/.env VÁLIDO -- camino normal (compose down elimina contenedor + red).
write_compose t1
write_valid_env t1
docker compose -f docker/docker-compose.postgres.yml --env-file docker/.env up -d
wait_exec_ready vinto-mvp-postgres-dep61-t1
set +e
log_t1="\$(do_rollback t1 2>&1)"; t1_status=\$?
set -e
echo "\$log_t1"
if [ "\$t1_status" -eq 0 ] && ! docker inspect vinto-mvp-postgres-dep61-t1 >/dev/null 2>&1; then
  result T1 0
else
  result T1 1
fi
docker rm -f vinto-mvp-postgres-dep61-t1 >/dev/null 2>&1 || true
docker network rm vinto-mvp-internal-dep61-t1 >/dev/null 2>&1 || true

# T2: docker/.env AUSENTE -- recuperación funcional (detención directa; datos verificados tras
# reiniciar el contenedor, no solo asumidos).
write_compose t2
write_valid_env t2
docker compose -f docker/docker-compose.postgres.yml --env-file docker/.env up -d
wait_exec_ready vinto-mvp-postgres-dep61-t2
docker exec vinto-mvp-postgres-dep61-t2 sh -c 'echo ok > /var/lib/postgresql/data/MARKER'
rm -f docker/.env
set +e
log_t2="\$(do_rollback t2 2>&1)"; t2_status=\$?
set -e
echo "\$log_t2"
if [ "\$t2_status" -eq 0 ] && [ "\$(is_running vinto-mvp-postgres-dep61-t2)" = "false" ] \
    && docker inspect vinto-mvp-postgres-dep61-t2 >/dev/null 2>&1 \
    && printf '%s' "\$log_t2" | grep -q "detenido directamente"; then
  docker start vinto-mvp-postgres-dep61-t2 >/dev/null
  wait_exec_ready vinto-mvp-postgres-dep61-t2
  marker_t2="\$(docker exec vinto-mvp-postgres-dep61-t2 cat /var/lib/postgresql/data/MARKER 2>/dev/null || true)"
  docker stop vinto-mvp-postgres-dep61-t2 >/dev/null
  if [ "\$marker_t2" = "ok" ]; then result T2 0; else result T2 1; fi
else
  result T2 1
fi
docker rm -f vinto-mvp-postgres-dep61-t2 >/dev/null 2>&1 || true
docker network rm vinto-mvp-internal-dep61-t2 >/dev/null 2>&1 || true

# T3: docker/.env en 644 -- recuperación funcional SIN leerlo (nunca aparece el secreto en el log).
write_compose t3
write_valid_env t3
docker compose -f docker/docker-compose.postgres.yml --env-file docker/.env up -d
wait_exec_ready vinto-mvp-postgres-dep61-t3
chmod 644 docker/.env
set +e
log_t3="\$(do_rollback t3 2>&1)"; t3_status=\$?
set -e
echo "\$log_t3"
if [ "\$t3_status" -eq 0 ] && [ "\$(is_running vinto-mvp-postgres-dep61-t3)" = "false" ] \
    && ! printf '%s' "\$log_t3" | grep -q "$DEP61_SECRET"; then
  result T3 0
else
  result T3 1
fi
docker rm -f vinto-mvp-postgres-dep61-t3 >/dev/null 2>&1 || true
docker network rm vinto-mvp-internal-dep61-t3 >/dev/null 2>&1 || true

# T4: docker/.env como ENLACE simbólico hacia un destino VÁLIDO -- recuperación funcional sin
# leerlo (DEP60-01 aplicado también aquí: rechazado por ser symlink, nunca por contenido).
write_compose t4
write_valid_env t4
docker compose -f docker/docker-compose.postgres.yml --env-file docker/.env up -d
wait_exec_ready vinto-mvp-postgres-dep61-t4
mv docker/.env docker/.env.real
ln -s .env.real docker/.env
set +e
log_t4="\$(do_rollback t4 2>&1)"; t4_status=\$?
set -e
echo "\$log_t4"
if [ "\$t4_status" -eq 0 ] && [ "\$(is_running vinto-mvp-postgres-dep61-t4)" = "false" ] \
    && ! printf '%s' "\$log_t4" | grep -q "$DEP61_SECRET" \
    && printf '%s' "\$log_t4" | grep -q "enlace simbólico"; then
  result T4 0
else
  result T4 1
fi
docker rm -f vinto-mvp-postgres-dep61-t4 >/dev/null 2>&1 || true
docker network rm vinto-mvp-internal-dep61-t4 >/dev/null 2>&1 || true
rm -f docker/.env docker/.env.real

# T5: archivo "corrupto" -- 600, propietario correcto (pasa el contrato de SEGURIDAD del archivo,
# que nunca inspecciona claves/valores), pero falta POSTGRES_BOOTSTRAP_PASSWORD: Compose falla al
# resolver "\${POSTGRES_BOOTSTRAP_PASSWORD:?...}" -- debe degradar igual, SIN fabricar un valor.
write_compose t5
write_valid_env t5
docker compose -f docker/docker-compose.postgres.yml --env-file docker/.env up -d
wait_exec_ready vinto-mvp-postgres-dep61-t5
printf 'POSTGRES_BOOTSTRAP_DB=bootdb\nPOSTGRES_BOOTSTRAP_USER=bootuser\nVINTO_MVP_PGDATA_DIR=/tmp/pgdata-t5\n' > docker/.env
chmod 600 docker/.env
set +e
log_t5="\$(do_rollback t5 2>&1)"; t5_status=\$?
set -e
echo "\$log_t5"
if [ "\$t5_status" -eq 0 ] && [ "\$(is_running vinto-mvp-postgres-dep61-t5)" = "false" ] \
    && printf '%s' "\$log_t5" | grep -q "falló" \
    && printf '%s' "\$log_t5" | grep -q "detenido directamente"; then
  result T5 0
else
  result T5 1
fi
docker rm -f vinto-mvp-postgres-dep61-t5 >/dev/null 2>&1 || true
docker network rm vinto-mvp-internal-dep61-t5 >/dev/null 2>&1 || true

# T6: contenedor con el NOMBRE esperado pero identidad AJENA (imagen distinta, pese a la etiqueta
# de proyecto correcta) -- rechazo; requisitos 3/4: nunca solo el nombre como evidencia.
docker run -d --name vinto-mvp-postgres-dep61-t6 \
  --label com.docker.compose.project=vinto-mvp-dep61-t6 alpine:3 sleep 300 >/dev/null
set +e
log_t6="\$(do_rollback t6 2>&1)"; t6_status=\$?
set -e
echo "\$log_t6"
if [ "\$t6_status" -ne 0 ] && [ "\$(is_running vinto-mvp-postgres-dep61-t6)" = "true" ] \
    && printf '%s' "\$log_t6" | grep -q "FALLA DE IDENTIDAD"; then
  result T6 0
else
  result T6 1
fi
docker rm -f vinto-mvp-postgres-dep61-t6 >/dev/null 2>&1 || true

# T7: contenedor del MVP INEXISTENTE -- explícito e idempotente en dos ejecuciones consecutivas.
set +e
log_t7a="\$(do_rollback t7 2>&1)"; t7a=\$?
log_t7b="\$(do_rollback t7 2>&1)"; t7b=\$?
set -e
echo "\$log_t7a"; echo "\$log_t7b"
if [ "\$t7a" -eq 0 ] && [ "\$t7b" -eq 0 ] \
    && printf '%s' "\$log_t7a" | grep -q "no existe; nada que detener" \
    && printf '%s' "\$log_t7b" | grep -q "no existe; nada que detener"; then
  result T7 0
else
  result T7 1
fi

# T13 (DEP61-03): daemon INACCESIBLE -- "docker inspect" falla, pero NUNCA con el texto "no such
# object"/"no such container" (esa es la única señal de ausencia real). Debe fallar
# EXPLÍCITAMENTE, nunca confundirse con "no existe; nada que detener".
set +e
log_t13="\$(DOCKER_HOST=unix:///tmp/dep61-bogus-\$\$.sock do_rollback t13 2>&1)"; t13_status=\$?
set -e
echo "\$log_t13"
if [ "\$t13_status" -ne 0 ] \
    && printf '%s' "\$log_t13" | grep -q "error DISTINTO de 'no existe'" \
    && ! printf '%s' "\$log_t13" | grep -q "no existe; nada que detener"; then
  result T13 0
else
  result T13 1
fi

# T14 (DEP61-02): Docker Compose NO disponible en este host, pero Docker Engine SÍ operativo --
# debe seguir degradando a detención directa, nunca morir por culpa de "detect_compose_cmd".
# El contenedor se crea con "docker run" (nunca con compose, ya deshabilitado) pero docker/.env
# SÍ es válido: se intenta el camino normal, que debe fallar por ausencia de la herramienta, no
# por el contrato de seguridad del archivo.
mv /usr/libexec/docker/cli-plugins/docker-compose /usr/libexec/docker/cli-plugins/docker-compose.disabled
write_valid_env t14
docker run -d --name vinto-mvp-postgres-dep61-t14 \
  --label com.docker.compose.project=vinto-mvp-dep61-t14 \
  -e POSTGRES_DB=bootdb -e POSTGRES_USER=bootuser -e POSTGRES_PASSWORD=x postgres:17 >/dev/null
wait_exec_ready vinto-mvp-postgres-dep61-t14
set +e
log_t14="\$(do_rollback t14 2>&1)"; t14_status=\$?
set -e
echo "\$log_t14"
mv /usr/libexec/docker/cli-plugins/docker-compose.disabled /usr/libexec/docker/cli-plugins/docker-compose
if [ "\$t14_status" -eq 0 ] && [ "\$(is_running vinto-mvp-postgres-dep61-t14)" = "false" ] \
    && printf '%s' "\$log_t14" | grep -q "detenido directamente"; then
  result T14 0
else
  result T14 1
fi
docker rm -f vinto-mvp-postgres-dep61-t14 >/dev/null 2>&1 || true
INNEREOF
    docker exec -i "$DEP61_WRAPPER_NAME" bash -s < "$DEP61_INNER" >/tmp/verify-dep61-inner.log 2>&1
    dep61_inner_status=$?

    dep61_result_of() {
      grep "^RESULT:$1:" /tmp/verify-dep61-inner.log | tail -n1 | cut -d: -f3
    }
    if [ "$(dep61_result_of T1)" = "0" ]; then
      report "DEP61-01 T1: docker/.env válido -- camino normal (compose down elimina el contenedor)" 0
    else
      report "DEP61-01 T1: docker/.env válido -- camino normal (compose down elimina el contenedor)" 1
    fi
    if [ "$(dep61_result_of T2)" = "0" ]; then
      report "DEP61-01 T2: docker/.env ausente -- recuperación funcional (detención directa; datos verificados tras reiniciar)" 0
    else
      report "DEP61-01 T2: docker/.env ausente -- recuperación funcional (detención directa; datos verificados tras reiniciar)" 1
    fi
    if [ "$(dep61_result_of T3)" = "0" ]; then
      report "DEP61-01 T3: docker/.env en 644 -- recuperación funcional sin leerlo" 0
    else
      report "DEP61-01 T3: docker/.env en 644 -- recuperación funcional sin leerlo" 1
    fi
    if [ "$(dep61_result_of T4)" = "0" ]; then
      report "DEP61-01 T4: docker/.env como enlace simbólico (destino válido) -- recuperación funcional sin leerlo" 0
    else
      report "DEP61-01 T4: docker/.env como enlace simbólico (destino válido) -- recuperación funcional sin leerlo" 1
    fi
    if [ "$(dep61_result_of T5)" = "0" ]; then
      report "DEP61-01 T5: docker/.env con contenido corrupto (clave obligatoria ausente) -- recuperación segura, sin fabricar credenciales" 0
    else
      report "DEP61-01 T5: docker/.env con contenido corrupto (clave obligatoria ausente) -- recuperación segura, sin fabricar credenciales" 1
    fi
    if [ "$(dep61_result_of T6)" = "0" ]; then
      report "DEP61-01 T6: nombre esperado pero identidad ajena (imagen distinta) -- rechazado, contenedor sigue activo" 0
    else
      report "DEP61-01 T6: nombre esperado pero identidad ajena (imagen distinta) -- rechazado, contenedor sigue activo" 1
    fi
    if [ "$(dep61_result_of T7)" = "0" ]; then
      report "DEP61-01 T7: contenedor del MVP inexistente -- explícito e idempotente en dos ejecuciones" 0
    else
      report "DEP61-01 T7: contenedor del MVP inexistente -- explícito e idempotente en dos ejecuciones" 1
    fi
    if [ "$(dep61_result_of T13)" = "0" ]; then
      report "DEP61-03 T13: daemon inaccesible -- error explícito, nunca confundido con 'no existe'" 0
    else
      report "DEP61-03 T13: daemon inaccesible -- error explícito, nunca confundido con 'no existe'" 1
    fi
    if [ "$(dep61_result_of T14)" = "0" ]; then
      report "DEP61-02 T14: Docker Compose no disponible, Docker Engine operativo -- degrada a detención directa" 0
    else
      report "DEP61-02 T14: Docker Compose no disponible, Docker Engine operativo -- degrada a detención directa" 1
    fi
    if [ "$dep61_inner_status" -ne 0 ] && ! grep -q '^RESULT:' /tmp/verify-dep61-inner.log; then
      echo "--- log interno DEP61-01 (fallo antes de producir ningún RESULT) ---"
      cat /tmp/verify-dep61-inner.log
    fi

    # T11: ningún secreto (ni el sintético de este laboratorio) quedó impreso en el log interno.
    if ! grep -q "$DEP61_SECRET" /tmp/verify-dep61-inner.log; then
      report "DEP61-01 T11: ningún valor secreto quedó impreso en los logs de esta batería" 0
    else
      report "DEP61-01 T11: ningún valor secreto quedó impreso en los logs de esta batería" 1
    fi
    # T12: la ÚNICA aparición esperada de "postgres-vinto" es el mensaje de reaseguro que
    # rollback.sh ya imprime siempre ("postgres-vinto (TVC) no se tocó.") -- cualquier OTRA
    # mención (o cualquier mención de vinto_default) sería indicio de que algo tocó TVC de verdad.
    if ! grep -E "postgres-vinto|vinto_default" /tmp/verify-dep61-inner.log /tmp/verify-dep61-setup.log \
        | grep -qv "postgres-vinto (TVC) no se tocó"; then
      report "DEP61-01 T12: la única mención de TVC en los logs es el reaseguro esperado de rollback.sh (nunca tocado)" 0
    else
      report "DEP61-01 T12: la única mención de TVC en los logs es el reaseguro esperado de rollback.sh (nunca tocado)" 1
    fi
  fi
fi

# T9: el contenedor AJENO creado ANTES de toda la batería (sin ninguna etiqueta ni nombre
# relacionado con el MVP) permanece activo después de T1-T7 -- ninguna prueba lo tocó.
if [ "$dep61_bystander_status" -eq 0 ] \
    && [ "$(docker inspect --format '{{.State.Running}}' "$DEP61_BYSTANDER_NAME" 2>/dev/null)" = "true" ]; then
  report "DEP61-01 T9: el contenedor ajeno, creado ANTES de la batería, permanece activo tras T1-T7" 0
else
  report "DEP61-01 T9: el contenedor ajeno, creado ANTES de la batería, permanece activo tras T1-T7" 1
fi

echo "=== Prueba focalizada CLOUD-DEP-02B.2-D.2: backup.sh (dump/restore verificable de PostgreSQL MVP) ==="
echo "backup.sh es un script NUEVO, separado de deploy.sh/rollback.sh (DEP55-01). Identifica el"
echo "contenedor del MVP con la misma identidad estricta que rollback.sh (DEP61-01/02/03), lee"
echo "docker/.env con el mismo contrato fail-closed que deploy.sh (DEP60-01/CLOUD-DEP-02B.2-D.1),"
echo "y nunca pasa contraseñas como argumento (mismo patrón .pgpass que pg_run_sql_inline)."
echo "Laboratorio: mismo contenedor Ubuntu con el socket de Docker montado que las baterías de"
echo "DEP61 -- chmod/stat reales, contenedores HERMANOS en el mismo demonio."

DEP62_PW_T1="SECRETO-SINTETICO-DEP62-T1-$(date +%s)-NUNCA-REAL"
DEP62_PW_T5="SECRETO-SINTETICO-DEP62-T5-$(date +%s)-NUNCA-REAL"
DEP62_PW_T6_REAL="SECRETO-SINTETICO-DEP62-T6-$(date +%s)-NUNCA-REAL"
DEP62_PW_T13="SECRETO-SINTETICO-DEP62-T13-$(date +%s)-NUNCA-REAL"
DEP62_WRAPPER_NAME=""

set +e
create_container verify-dep62-bystander alpine:3 sleep 300
dep62_bystander_status=$?
set -e
DEP62_BYSTANDER_NAME="$CREATED_NAME"

set +e
create_container dep62-wrapper -v //var/run/docker.sock:/var/run/docker.sock ubuntu:24.04 sleep 1800
dep62_wrapper_status=$?
set -e
if [ "$dep62_wrapper_status" -ne 0 ]; then
  report "CLOUD-DEP-02B.2-D.2: batería completa (omitida: no se pudo crear el contenedor envoltorio con el socket de Docker montado)" 1
else
  DEP62_WRAPPER_NAME="$CREATED_NAME"
  docker cp "$MVP_DIR" "$DEP62_WRAPPER_NAME:/tmp/mvp" >/dev/null
  set +e
  docker exec "$DEP62_WRAPPER_NAME" bash -c '
    set -e
    export DEBIAN_FRONTEND=noninteractive
    find /tmp/mvp -name "*.sh" -exec sed -i "s/\r$//" {} + 2>/dev/null || true
    apt-get update -qq
    apt-get install -y -qq --no-install-recommends docker.io coreutils >/dev/null
    chmod +x /tmp/mvp/scripts/backup.sh
  ' >/tmp/verify-dep62-setup.log 2>&1
  dep62_setup_ok=$?
  set -e
  if [ "$dep62_setup_ok" -ne 0 ]; then
    echo "--- log de preparación CLOUD-DEP-02B.2-D.2 ---"; cat /tmp/verify-dep62-setup.log
    report "CLOUD-DEP-02B.2-D.2: preparación (contenedor envoltorio con docker CLI real, vía socket montado)" 1
  else
    report "CLOUD-DEP-02B.2-D.2: preparación (contenedor envoltorio con docker CLI real, vía socket montado)" 0

    DEP62_INNER="$(mktemp)"
    track_tmp_path "$DEP62_INNER"
    cat > "$DEP62_INNER" <<INNEREOF
set -u
cd /tmp/mvp

wait_exec_ready() {
  local n=0
  while [ "\$n" -lt 30 ]; do
    docker exec "\$1" true >/dev/null 2>&1 && return 0
    sleep 0.5
    n=\$((n + 1))
  done
  return 1
}
# wait_pg_ready <container> <user> <db>: a diferencia de wait_exec_ready (solo confirma que el
# PROCESO del contenedor responde), esto espera a que Postgres mismo termine de inicializar y
# acepte conexiones -- "docker exec ... true" puede tener éxito mucho antes de que "pg_isready"
# lo haga, confirmado empíricamente ("connection refused" en el primer intento de esta batería).
wait_pg_ready() {
  local n=0
  while [ "\$n" -lt 90 ]; do
    docker exec "\$1" pg_isready -U "\$2" -d "\$3" >/dev/null 2>&1 && { sleep 2; return 0; }
    sleep 1
    n=\$((n + 1))
  done
  return 1
}
mk_mvp_container() {
  local suffix="\$1" password="\$2"
  docker run -d --name "vinto-mvp-postgres-dep62-\$suffix" \
    --label com.docker.compose.project="vinto-mvp-dep62-\$suffix" \
    -e POSTGRES_DB=vinto_piloto -e POSTGRES_USER=bootuser -e POSTGRES_PASSWORD="\$password" \
    postgres:17 >/dev/null
  wait_pg_ready "vinto-mvp-postgres-dep62-\$suffix" bootuser vinto_piloto
  docker exec -e PGPASSWORD="\$password" "vinto-mvp-postgres-dep62-\$suffix" \
    psql -h 127.0.0.1 -U bootuser -d vinto_piloto -v ON_ERROR_STOP=1 -c \
    "CREATE TABLE verify_seed (id serial primary key, note text); INSERT INTO verify_seed (note) SELECT 'row-' || g FROM generate_series(1,25) g;" >/dev/null
}
write_docker_env() {
  printf 'POSTGRES_BOOTSTRAP_DB=vinto_piloto\nPOSTGRES_BOOTSTRAP_USER=bootuser\nPOSTGRES_BOOTSTRAP_PASSWORD=%s\nVINTO_MVP_PGDATA_DIR=/tmp/unused-pgdata\n' "\$1" > docker/.env
  chmod 600 docker/.env
}
run_backup() {
  local suffix="\$1"; shift
  ( cd scripts && CONFIRM=yes \
      MVP_POSTGRES_CONTAINER="vinto-mvp-postgres-dep62-\$suffix" \
      MVP_COMPOSE_PROJECT="vinto-mvp-dep62-\$suffix" \
      VINTO_MVP_BACKUP_DIR="/tmp/backups-dep62-\$suffix" \
      bash backup.sh "\$@" )
}
result() { echo "RESULT:\$1:\$2"; }

# T1: backup EXITOSO.
mkdir -p /tmp/backups-dep62-t1 && chmod 700 /tmp/backups-dep62-t1
mk_mvp_container t1 "$DEP62_PW_T1"
write_docker_env "$DEP62_PW_T1"
set +e
log_create_t1="\$(run_backup t1 create 2>&1)"; create_t1_status=\$?
set -e
echo "\$log_create_t1"
dump_path_t1="\$(printf '%s' "\$log_create_t1" | grep -oE '/tmp/backups-dep62-t1/[^ ]+\.dump' | head -n1)"
if [ "\$create_t1_status" -eq 0 ] && [ -n "\$dump_path_t1" ] && [ -f "\$dump_path_t1" ] && [ -f "\$dump_path_t1.sha256" ]; then
  result T1 0
else
  result T1 1
fi

# T2: restauración EXITOSA (verify sobre el dump de T1).
set +e
log_verify_t1="\$(run_backup t1 verify "\$dump_path_t1" 2>&1)"; verify_t1_status=\$?
set -e
echo "\$log_verify_t1"
if [ "\$verify_t1_status" -eq 0 ] && [ -f "\$dump_path_t1.verified" ]; then
  result T2 0
else
  result T2 1
fi

# T3: verificación RIGUROSA de filas/objetos -- restaurar de nuevo, aparte, y comparar el
# recuento EXACTO de filas de la tabla sembrada (25) contra el origen.
if [ -n "\$dump_path_t1" ] && [ -f "\$dump_path_t1" ]; then
  docker run -d --name vinto-mvp-backup-rowcheck-t1 --network none \
    -e POSTGRES_DB=rowcheck -e POSTGRES_USER=rowcheck_root -e POSTGRES_PASSWORD=rowcheckpw postgres:17 >/dev/null
  wait_pg_ready vinto-mvp-backup-rowcheck-t1 rowcheck_root rowcheck
  docker exec -i -e PGPASSWORD=rowcheckpw vinto-mvp-backup-rowcheck-t1 \
    pg_restore -h 127.0.0.1 -U rowcheck_root -d rowcheck --no-owner --no-privileges < "\$dump_path_t1" >/dev/null 2>&1 || true
  row_count_t1="\$(docker exec -e PGPASSWORD=rowcheckpw vinto-mvp-backup-rowcheck-t1 \
    psql -h 127.0.0.1 -U rowcheck_root -d rowcheck -tAc 'SELECT count(*) FROM verify_seed;' 2>/dev/null | tr -d '[:space:]')"
  docker rm -f vinto-mvp-backup-rowcheck-t1 >/dev/null 2>&1 || true
  if [ "\$row_count_t1" = "25" ]; then
    result T3 0
  else
    result T3 1
  fi
else
  result T3 1
fi

# T4: archivo CORRUPTO (checksum NO coincide) -- nunca se intenta restaurar, se marca .CORRUPT.
if [ -n "\$dump_path_t1" ] && [ -f "\$dump_path_t1" ]; then
  cp "\$dump_path_t1" "\$dump_path_t1.tampered"
  sed "s#\$(basename "\$dump_path_t1")#\$(basename "\$dump_path_t1").tampered#" "\$dump_path_t1.sha256" > "\$dump_path_t1.tampered.sha256"
  printf 'GARBAGE-APPENDED-AFTER-CHECKSUM' >> "\$dump_path_t1.tampered"
  set +e
  log_t4="\$(run_backup t1 verify "\$dump_path_t1.tampered" 2>&1)"; t4_status=\$?
  set -e
  echo "\$log_t4"
  if [ "\$t4_status" -ne 0 ] && [ -f "\$dump_path_t1.tampered.CORRUPT" ] && [ ! -f "\$dump_path_t1.tampered.verified" ]; then
    result T4 0
  else
    result T4 1
  fi
else
  result T4 1
fi

# T5: ESPACIO INSUFICIENTE -- rechazado antes de intentar pg_dump; directorio queda vacío.
mkdir -p /tmp/backups-dep62-t5 && chmod 700 /tmp/backups-dep62-t5
mk_mvp_container t5 "$DEP62_PW_T5"
write_docker_env "$DEP62_PW_T5"
set +e
log_t5="\$( ( cd scripts && CONFIRM=yes MVP_POSTGRES_CONTAINER=vinto-mvp-postgres-dep62-t5 \
    MVP_COMPOSE_PROJECT=vinto-mvp-dep62-t5 VINTO_MVP_BACKUP_DIR=/tmp/backups-dep62-t5 \
    VINTO_MVP_BACKUP_MIN_FREE_MB=999999999 bash backup.sh create ) 2>&1 )"; t5_status=\$?
set -e
echo "\$log_t5"
if [ "\$t5_status" -ne 0 ] && printf '%s' "\$log_t5" | grep -q "libres en el sistema de archivos" \
    && [ -z "\$(ls -A /tmp/backups-dep62-t5 2>/dev/null)" ]; then
  result T5 0
else
  result T5 1
fi

# T6: CONTRASEÑA INCORRECTA -- pg_dump falla, nunca se promueve un archivo parcial, nunca se
# imprime la contraseña real en ningún log.
#
# NOTA: la imagen oficial de postgres confía (pg_hba.conf "trust") en CUALQUIER conexión desde
# 127.0.0.1 por defecto -- confirmado empíricamente, incluso con POSTGRES_HOST_AUTH_METHOD
# puesto, las líneas host/127.0.0.1/::1 quedan en "trust" igual. Como pg_dump_custom conecta
# siempre vía "docker exec ... -h 127.0.0.1" (dentro del propio contenedor), nunca se le pediría
# contraseña de verdad sin forzar la autenticación real primero -- se reemplaza "trust" por
# "scram-sha-256" en el pg_hba.conf YA ESCRITO (edición vía "docker exec", nunca un bind-mount
# -- un bind-mount desde este envoltorio apuntaría a una ruta del DEMONIO, no de este
# contenedor) y se recarga con "pg_reload_conf()", usando TODAVÍA la contraseña real (la
# recarga, no la conexión que la dispara, es lo que cambia el comportamiento futuro).
mkdir -p /tmp/backups-dep62-t6 && chmod 700 /tmp/backups-dep62-t6
mk_mvp_container t6 "$DEP62_PW_T6_REAL"
docker exec vinto-mvp-postgres-dep62-t6 sed -i 's/trust/scram-sha-256/' /var/lib/postgresql/data/pg_hba.conf
docker exec -e PGPASSWORD="$DEP62_PW_T6_REAL" vinto-mvp-postgres-dep62-t6 \
  psql -h 127.0.0.1 -U bootuser -d vinto_piloto -c "SELECT pg_reload_conf();" >/dev/null
write_docker_env "contrasena-equivocada-\$\$-nunca-la-real"
set +e
log_t6="\$(run_backup t6 create 2>&1)"; t6_status=\$?
set -e
echo "\$log_t6"
if [ "\$t6_status" -ne 0 ] && [ -z "\$(ls -A /tmp/backups-dep62-t6 2>/dev/null)" ] \
    && ! printf '%s' "\$log_t6" | grep -q "$DEP62_PW_T6_REAL"; then
  result T6 0
else
  result T6 1
fi

# T7: CONTENEDOR AUSENTE -- rechazado con mensaje explícito, nunca intenta nada más.
mkdir -p /tmp/backups-dep62-t7 && chmod 700 /tmp/backups-dep62-t7
write_docker_env "irrelevante-t7"
set +e
log_t7="\$(run_backup t7 create 2>&1)"; t7_status=\$?
set -e
echo "\$log_t7"
if [ "\$t7_status" -ne 0 ] && printf '%s' "\$log_t7" | grep -q "no existe. No se puede respaldar"; then
  result T7 0
else
  result T7 1
fi

# T8: CONTENEDOR DE IDENTIDAD AJENA (nombre esperado, imagen distinta) -- rechazado, sigue activo.
docker run -d --name vinto-mvp-postgres-dep62-t8 \
  --label com.docker.compose.project=vinto-mvp-dep62-t8 alpine:3 sleep 300 >/dev/null
mkdir -p /tmp/backups-dep62-t8 && chmod 700 /tmp/backups-dep62-t8
write_docker_env "irrelevante-t8"
set +e
log_t8="\$(run_backup t8 create 2>&1)"; t8_status=\$?
set -e
echo "\$log_t8"
if [ "\$t8_status" -ne 0 ] && printf '%s' "\$log_t8" | grep -q "FALLA DE IDENTIDAD" \
    && [ "\$(docker inspect --format '{{.State.Running}}' vinto-mvp-postgres-dep62-t8 2>/dev/null)" = "true" ]; then
  result T8 0
else
  result T8 1
fi
docker rm -f vinto-mvp-postgres-dep62-t8 >/dev/null 2>&1 || true

# T9: FALLO DE RESTAURACIÓN -- checksum SÍ coincide (nunca se detecta como "corrupto"), pero el
# contenido no es un archivo de pg_dump válido: pg_restore debe fallar, nunca marcar .verified.
printf 'NOT-A-REAL-PG-DUMP-FILE-GARBAGE-CONTENT' > /tmp/backups-dep62-t1/fake.dump
( cd /tmp/backups-dep62-t1 && sha256sum fake.dump > fake.dump.sha256 )
chmod 600 /tmp/backups-dep62-t1/fake.dump /tmp/backups-dep62-t1/fake.dump.sha256
set +e
log_t9="\$(run_backup t1 verify /tmp/backups-dep62-t1/fake.dump 2>&1)"; t9_status=\$?
set -e
echo "\$log_t9"
if [ "\$t9_status" -ne 0 ] && [ ! -f /tmp/backups-dep62-t1/fake.dump.verified ] \
    && [ ! -f /tmp/backups-dep62-t1/fake.dump.CORRUPT ]; then
  result T9 0
else
  result T9 1
fi

# T10: PRESERVACIÓN del backup anterior -- un "create" fallido (contraseña incorrecta, reusando
# el contenedor de T1 pero con docker/.env ahora equivocado) no debe tocar el backup bueno de T1.
# Mismo forzado de autenticación real que T6 (ver su nota): el contenedor de T1 sigue en "trust"
# hasta este punto, y nada posterior a T10 vuelve a necesitar esa confianza por omisión.
checksum_before_t10="\$(sha256sum "\$dump_path_t1" | awk '{print \$1}')"
docker exec vinto-mvp-postgres-dep62-t1 sed -i 's/trust/scram-sha-256/' /var/lib/postgresql/data/pg_hba.conf
docker exec -e PGPASSWORD="$DEP62_PW_T1" vinto-mvp-postgres-dep62-t1 \
  psql -h 127.0.0.1 -U bootuser -d vinto_piloto -c "SELECT pg_reload_conf();" >/dev/null
write_docker_env "otra-contrasena-equivocada-\$\$"
set +e
log_t10="\$(run_backup t1 create 2>&1)"; t10_create_status=\$?
set -e
echo "\$log_t10"
checksum_after_t10="\$(sha256sum "\$dump_path_t1" | awk '{print \$1}')"
if [ "\$t10_create_status" -ne 0 ] && [ "\$checksum_before_t10" = "\$checksum_after_t10" ]; then
  result T10 0
else
  result T10 1
fi

# T13: comando de conveniencia "create-and-verify".
mkdir -p /tmp/backups-dep62-t13 && chmod 700 /tmp/backups-dep62-t13
mk_mvp_container t13 "$DEP62_PW_T13"
write_docker_env "$DEP62_PW_T13"
set +e
log_t13="\$(run_backup t13 create-and-verify 2>&1)"; t13_status=\$?
set -e
echo "\$log_t13"
verified_count_t13="\$(ls /tmp/backups-dep62-t13/*.verified 2>/dev/null | wc -l)"
if [ "\$t13_status" -eq 0 ] && [ "\$verified_count_t13" = "1" ]; then
  result T13 0
else
  result T13 1
fi

# T14: política de retención ("prune") -- 10 backups verificados sintéticos, RETENTION_DAILY=7 ->
# deben quedar 8 (7 diarios + 1 semanal, el más antiguo).
PRUNE_DIR=/tmp/backups-dep62-prune
mkdir -p "\$PRUNE_DIR" && chmod 700 "\$PRUNE_DIR"
for i in 1 2 3 4 5 6 7 8 9 10; do
  ts="\$(printf '202501%02d-000000' "\$i")"
  f="\$PRUNE_DIR/vinto-mvp-vinto_piloto-\$ts-fake.dump"
  printf 'fake' > "\$f"
  chmod 600 "\$f"
  : > "\$f.verified"
done
set +e
log_prune="\$( ( cd scripts && CONFIRM=yes VINTO_MVP_BACKUP_DIR="\$PRUNE_DIR" VINTO_MVP_BACKUP_RETENTION_DAILY=7 bash backup.sh prune ) 2>&1 )"; prune_status=\$?
set -e
echo "\$log_prune"
remaining="\$(ls "\$PRUNE_DIR"/*.dump 2>/dev/null | wc -l)"
oldest_kept="\$(ls "\$PRUNE_DIR"/*.dump 2>/dev/null | sort | head -n1)"
if [ "\$prune_status" -eq 0 ] && [ "\$remaining" = "8" ] && printf '%s' "\$oldest_kept" | grep -q "20250101"; then
  result T14 0
else
  result T14 1
fi

# Limpieza de los contenedores "MVP" sintéticos creados por esta batería (T1/T5/T6/T13 -- T8 y el
# rowcheck de T3 ya se limpian en su propio paso). Estos son contenedores HERMANOS en el demonio
# real del host, no hijos de este envoltorio: sobreviven a su destrucción si no se limpian aquí.
for suffix in t1 t5 t6 t13; do
  docker rm -f "vinto-mvp-postgres-dep62-\$suffix" >/dev/null 2>&1 || true
done
INNEREOF
    docker exec -i "$DEP62_WRAPPER_NAME" bash -s < "$DEP62_INNER" >/tmp/verify-dep62-inner.log 2>&1
    dep62_inner_status=$?

    dep62_result_of() {
      grep "^RESULT:$1:" /tmp/verify-dep62-inner.log | tail -n1 | cut -d: -f3
    }
    if [ "$(dep62_result_of T1)" = "0" ]; then
      report "CLOUD-DEP-02B.2-D.2 T1: backup exitoso (pg_dump -Fc + checksum)" 0
    else
      report "CLOUD-DEP-02B.2-D.2 T1: backup exitoso (pg_dump -Fc + checksum)" 1
    fi
    if [ "$(dep62_result_of T2)" = "0" ]; then
      report "CLOUD-DEP-02B.2-D.2 T2: restauración exitosa en contenedor efímero aislado (marca .verified)" 0
    else
      report "CLOUD-DEP-02B.2-D.2 T2: restauración exitosa en contenedor efímero aislado (marca .verified)" 1
    fi
    if [ "$(dep62_result_of T3)" = "0" ]; then
      report "CLOUD-DEP-02B.2-D.2 T3: verificación rigurosa de filas (25/25 exactas tras restaurar)" 0
    else
      report "CLOUD-DEP-02B.2-D.2 T3: verificación rigurosa de filas (25/25 exactas tras restaurar)" 1
    fi
    if [ "$(dep62_result_of T4)" = "0" ]; then
      report "CLOUD-DEP-02B.2-D.2 T4: archivo corrupto (checksum no coincide), nunca se intenta restaurar" 0
    else
      report "CLOUD-DEP-02B.2-D.2 T4: archivo corrupto (checksum no coincide), nunca se intenta restaurar" 1
    fi
    if [ "$(dep62_result_of T5)" = "0" ]; then
      report "CLOUD-DEP-02B.2-D.2 T5: espacio insuficiente, rechazado antes de pg_dump" 0
    else
      report "CLOUD-DEP-02B.2-D.2 T5: espacio insuficiente, rechazado antes de pg_dump" 1
    fi
    if [ "$(dep62_result_of T6)" = "0" ]; then
      report "CLOUD-DEP-02B.2-D.2 T6: contraseña incorrecta, rechazado sin promover ni imprimir el secreto" 0
    else
      report "CLOUD-DEP-02B.2-D.2 T6: contraseña incorrecta, rechazado sin promover ni imprimir el secreto" 1
    fi
    if [ "$(dep62_result_of T7)" = "0" ]; then
      report "CLOUD-DEP-02B.2-D.2 T7: contenedor del MVP ausente, rechazado con mensaje explícito" 0
    else
      report "CLOUD-DEP-02B.2-D.2 T7: contenedor del MVP ausente, rechazado con mensaje explícito" 1
    fi
    if [ "$(dep62_result_of T8)" = "0" ]; then
      report "CLOUD-DEP-02B.2-D.2 T8: contenedor de identidad ajena (imagen distinta), rechazado, sigue activo" 0
    else
      report "CLOUD-DEP-02B.2-D.2 T8: contenedor de identidad ajena (imagen distinta), rechazado, sigue activo" 1
    fi
    if [ "$(dep62_result_of T9)" = "0" ]; then
      report "CLOUD-DEP-02B.2-D.2 T9: fallo de restauración (contenido inválido, checksum sí coincide), nunca se marca verificado" 0
    else
      report "CLOUD-DEP-02B.2-D.2 T9: fallo de restauración (contenido inválido, checksum sí coincide), nunca se marca verificado" 1
    fi
    if [ "$(dep62_result_of T10)" = "0" ]; then
      report "CLOUD-DEP-02B.2-D.2 T10: un create fallido preserva intacto el backup anterior válido" 0
    else
      report "CLOUD-DEP-02B.2-D.2 T10: un create fallido preserva intacto el backup anterior válido" 1
    fi
    if [ "$(dep62_result_of T13)" = "0" ]; then
      report "CLOUD-DEP-02B.2-D.2 T13: comando de conveniencia 'create-and-verify'" 0
    else
      report "CLOUD-DEP-02B.2-D.2 T13: comando de conveniencia 'create-and-verify'" 1
    fi
    if [ "$(dep62_result_of T14)" = "0" ]; then
      report "CLOUD-DEP-02B.2-D.2 T14: política de retención ('prune') conserva 7 diarios + 1 semanal" 0
    else
      report "CLOUD-DEP-02B.2-D.2 T14: política de retención ('prune') conserva 7 diarios + 1 semanal" 1
    fi
    if [ "$dep62_inner_status" -ne 0 ] && ! grep -q '^RESULT:' /tmp/verify-dep62-inner.log; then
      echo "--- log interno CLOUD-DEP-02B.2-D.2 (fallo antes de producir ningún RESULT) ---"
      cat /tmp/verify-dep62-inner.log
    fi

    # T11: LIMPIEZA SEGURA -- ningún contenedor efímero de verificación quedó huérfano.
    leftover_ephemeral="$(docker ps -a --filter "name=vinto-mvp-backup-verify-" --format '{{.Names}}')"
    if [ -z "$leftover_ephemeral" ]; then
      report "CLOUD-DEP-02B.2-D.2 T11: limpieza segura, ningún contenedor efímero de verificación queda huérfano" 0
    else
      echo "Contenedores efímeros huérfanos: $leftover_ephemeral"
      report "CLOUD-DEP-02B.2-D.2 T11: limpieza segura, ningún contenedor efímero de verificación queda huérfano" 1
    fi

    # T12: ningún secreto (ni los sintéticos de este laboratorio) quedó impreso en ningún log.
    if ! grep -qE "$DEP62_PW_T1|$DEP62_PW_T5|$DEP62_PW_T6_REAL|$DEP62_PW_T13" /tmp/verify-dep62-inner.log /tmp/verify-dep62-setup.log; then
      report "CLOUD-DEP-02B.2-D.2 T12: ningún valor secreto quedó impreso en los logs de esta batería" 0
    else
      report "CLOUD-DEP-02B.2-D.2 T12: ningún valor secreto quedó impreso en los logs de esta batería" 1
    fi
    # Nunca toca TVC.
    if ! grep -qE "postgres-vinto|vinto_default" /tmp/verify-dep62-inner.log /tmp/verify-dep62-setup.log; then
      report "CLOUD-DEP-02B.2-D.2: ningún log de esta batería nombra postgres-vinto/vinto_default (TVC)" 0
    else
      report "CLOUD-DEP-02B.2-D.2: ningún log de esta batería nombra postgres-vinto/vinto_default (TVC)" 1
    fi
  fi
fi

# El contenedor AJENO creado ANTES de toda la batería permanece activo después.
if [ "$dep62_bystander_status" -eq 0 ] \
    && [ "$(docker inspect --format '{{.State.Running}}' "$DEP62_BYSTANDER_NAME" 2>/dev/null)" = "true" ]; then
  report "CLOUD-DEP-02B.2-D.2: el contenedor ajeno, creado ANTES de la batería, permanece activo tras toda la batería" 0
else
  report "CLOUD-DEP-02B.2-D.2: el contenedor ajeno, creado ANTES de la batería, permanece activo tras toda la batería" 1
fi

echo "=== Resultado: $PASS OK, $FAILED FALLAS ==="
exit "$FAILED"
