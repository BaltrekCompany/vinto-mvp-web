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
set -e
if [ "$r1" -ne 0 ] && [ "$r2" -ne 0 ] && [ "$r3" -ne 0 ] && [ "$r4" -ne 0 ] && [ "$r5" -ne 0 ]; then
  report "cada fase de riesgo (incluida rollback.sh version) se niega a ejecutar sin confirmación explícita" 0
else
  echo "r1=$r1 r2=$r2 r3=$r3 r4=$r4 r5=$r5"
  report "cada fase de riesgo (incluida rollback.sh version) se niega a ejecutar sin confirmación explícita" 1
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

echo "=== Resultado: $PASS OK, $FAILED FALLAS ==="
exit "$FAILED"
