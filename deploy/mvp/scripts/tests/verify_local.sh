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

echo "=== Resultado: $PASS OK, $FAILED FALLAS ==="
exit "$FAILED"
