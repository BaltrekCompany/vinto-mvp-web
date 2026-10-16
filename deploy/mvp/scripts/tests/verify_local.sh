#!/usr/bin/env bash
# VINTO MVP WEB — pruebas locales obligatorias de CLOUD-DEP-02A.2 (auditoría del PR #55).
#
# Corre ENTERAMENTE en local (Windows/Git Bash o Linux), sin acceder al VPS. Todo lo que necesita
# PostgreSQL usa un contenedor EFÍMERO, creado y destruido por este mismo script — nunca una base
# existente ni el PostgreSQL de TVC. No requiere sudo/systemd/useradd (eso es exclusivo del VPS real
# y está fuera del alcance de lo que se puede probar aquí); en su lugar ejercita directamente las
# funciones puras de lib_common.sh y la lógica de las fases de PostgreSQL de deploy.sh.
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

echo "=== 1/10: bash -n (sintaxis) ==="
for f in deploy.sh rollback.sh preflight.sh lib_common.sh; do
  bash -n "$SCRIPT_DIR/../$f"
  report "bash -n $f" "$?"
done

echo "=== 2/10: ShellCheck (dockerizado) ==="
# MSYS_NO_PATHCONV se activa SOLO para estas dos llamadas (en una subshell): si quedara exportada
# para el resto del script, rompería la conversión de ruta que necesitan los pasos 3/4 más abajo.
if ( export MSYS_NO_PATHCONV=1; docker run --rm -v "$SCRIPT_DIR/..:/mnt" koalaman/shellcheck:stable --shell=bash -x \
    /mnt/deploy.sh /mnt/rollback.sh /mnt/preflight.sh ) >/tmp/shellcheck-entrypoints.log 2>&1; then
  report "shellcheck deploy.sh/rollback.sh/preflight.sh (-x, sigue lib_common.sh)" 0
else
  cat /tmp/shellcheck-entrypoints.log
  report "shellcheck deploy.sh/rollback.sh/preflight.sh (-x, sigue lib_common.sh)" 1
fi
if ( export MSYS_NO_PATHCONV=1; docker run --rm -v "$SCRIPT_DIR/..:/mnt" koalaman/shellcheck:stable --shell=bash /mnt/lib_common.sh ) \
    >/tmp/shellcheck-lib.log 2>&1; then
  report "shellcheck lib_common.sh (solo)" 0
else
  cat /tmp/shellcheck-lib.log
  report "shellcheck lib_common.sh (solo)" 1
fi

echo "=== 3/10: docker compose config ==="
# El archivo de entorno se escribe JUNTO al compose (no en /tmp): --env-file necesita una ruta
# válida para el binario de Docker (en Windows, vía Docker Desktop, no para el path POSIX de
# Git Bash), y esta ubicación ya se confirmó funcional.
TMP_COMPOSE_ENV="$MVP_DIR/docker/.env.verify-tmp"
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

echo "=== 4/10: nginx -t (plantilla sola + junto a un bloque TVC reconstruido) ==="
NGINX_TEST_DIR="$(mktemp -d)"
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

echo "=== 5/10: rollback.sh — pruebas negativas (DEP55-01) ==="
if ! grep -qE 'rm -rf.*PGDATA|DESTROY_DATA' "$SCRIPT_DIR/../rollback.sh"; then
  report "rollback.sh no contiene ningún rm -rf de datos ni DESTROY_DATA" 0
else
  report "rollback.sh no contiene ningún rm -rf de datos ni DESTROY_DATA" 1
fi
# "source lib_common.sh" (nuestra propia librería de confianza) es intencional y seguro; lo que
# NUNCA debe aparecer es código real que haga "source" de un .env operativo (el patrón original
# del hallazgo) — se excluyen las líneas de comentario (que documentan, en texto, que ya no se hace).
if ! grep -vE '^\s*#' "$SCRIPT_DIR/../rollback.sh" "$SCRIPT_DIR/../deploy.sh" | grep -nE 'source\s+"[^"]*\.env'; then
  report "rollback.sh/deploy.sh no hacen 'source' de ningún .env operativo" 0
else
  report "rollback.sh/deploy.sh no hacen 'source' de ningún .env operativo" 1
fi
# assert_unit_is_ours debe rechazar (exit !=0) una unidad con el mismo nombre que no es nuestra.
FAKE_UNIT_DIR="$(mktemp -d)"
cat > "$FAKE_UNIT_DIR/fake.service" <<'EOF'
[Service]
ExecStart=/usr/bin/true
EOF
set +e
(
  set -e
  # shellcheck disable=SC2034
  _test_unit_file() { cat "$FAKE_UNIT_DIR/fake.service"; }
  grep -q "WorkingDirectory=$MVP_APP_DIR" "$FAKE_UNIT_DIR/fake.service" 2>/dev/null \
    || grep -qE "^ExecStart=.*$MVP_APP_DIR" "$FAKE_UNIT_DIR/fake.service" 2>/dev/null
)
unit_matches=$?
set -e
if [ "$unit_matches" -ne 0 ]; then
  report "una unidad ajena (sin referencia a $MVP_APP_DIR) NO pasaría assert_unit_is_ours" 0
else
  report "una unidad ajena (sin referencia a $MVP_APP_DIR) NO pasaría assert_unit_is_ours" 1
fi
rm -rf "$FAKE_UNIT_DIR"

echo "=== 6/10: pruebas de colisión de recursos (contenedor ajeno con el mismo nombre) ==="
# assert_container_is_ours hace "exit 1" a propósito (debe detener deploy.sh/rollback.sh de
# inmediato en producción): para probarla sin matar este runner, se invoca en un subproceso.
docker rm -f vinto-mvp-postgres-test-foreign >/dev/null 2>&1 || true
docker run -d --rm --name vinto-mvp-postgres-test-foreign alpine:3 sleep 60 >/dev/null
set +e
bash -c "source '$SCRIPT_DIR/../lib_common.sh'; assert_container_is_ours vinto-mvp-postgres-test-foreign" \
  >/tmp/assert-container.log 2>&1
foreign_result=$?
set -e
docker rm -f vinto-mvp-postgres-test-foreign >/dev/null 2>&1 || true
if [ "$foreign_result" -ne 0 ]; then
  report "assert_container_is_ours rechaza un contenedor sin etiqueta de proyecto vinto-mvp" 0
else
  cat /tmp/assert-container.log
  report "assert_container_is_ours rechaza un contenedor sin etiqueta de proyecto vinto-mvp" 1
fi
# env_value nunca ejecuta código: un valor con sustitución de comandos se devuelve como texto.
INJECTION_ENV="$(mktemp)"
MARKER_FILE="$(mktemp -u)"
printf 'MALICIOUS=$(touch %s)\n' "$MARKER_FILE" > "$INJECTION_ENV"
value="$(env_value "$INJECTION_ENV" MALICIOUS)"
if [ ! -e "$MARKER_FILE" ] && [ "$value" = '$(touch '"$MARKER_FILE"')' ]; then
  report "env_value nunca ejecuta el contenido de un .env (sin source)" 0
else
  rm -f "$MARKER_FILE"
  report "env_value nunca ejecuta el contenido de un .env (sin source)" 1
fi
rm -f "$INJECTION_ENV"

echo "=== 7/10: orden de aprovisionamiento contra PostgreSQL EFÍMERO (DEP55-02) ==="
EPHEMERAL_NAME="vinto-mvp-verify-$(date +%s)"
BOOTSTRAP_USER=verify_root
BOOTSTRAP_PASSWORD="$(head -c18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
APP_PW="$(head -c18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
MIGRATOR_PW="$(head -c18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
REFERENCE_PW="$(head -c18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')"
# MSYS_NO_PATHCONV evita que Git Bash reescriba "/var/lib/postgresql/data" (una ruta DENTRO del
# contenedor, nunca del host) como si fuera una ruta de Windows.
( export MSYS_NO_PATHCONV=1; docker run -d --rm --name "$EPHEMERAL_NAME" \
  --label com.docker.compose.project=vinto-mvp \
  --tmpfs /var/lib/postgresql/data \
  -e POSTGRES_DB=vinto_mvp_bootstrap -e POSTGRES_USER="$BOOTSTRAP_USER" -e POSTGRES_PASSWORD="$BOOTSTRAP_PASSWORD" \
  postgres:17 >/dev/null )
for _ in $(seq 1 30); do
  docker exec "$EPHEMERAL_NAME" pg_isready -U "$BOOTSTRAP_USER" -d vinto_mvp_bootstrap >/dev/null 2>&1 && break
  sleep 1
done
# El cuerpo de la prueba vive en un script temporal propio, ejecutado como SUBPROCESO: las
# funciones de lib_common.sh (assert_container_is_ours dentro de pg_run_sql_inline/pg_run_sql_file)
# hacen "exit 1" a propósito si algo no coincide, y eso debe terminar solo ese subproceso, nunca
# este runner. Los valores se pasan por variables de entorno exportadas, nunca interpolados en
# texto de shell (evita cualquier problema de escapado de comillas).
PROVISION_SCRIPT="$(mktemp)"
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
# MSYS_NO_PATHCONV: todos los argumentos de docker en este flujo son rutas DENTRO del contenedor
# (/tmp/.deploy-pgpass, etc.) o nombres de variable, nunca una ruta del host (pg_run_sql_file ya
# no usa "docker cp"; el archivo .sql se lee con la redirección "< archivo" de bash, resuelta por
# bash mismo, no por docker.exe).
LIB_COMMON_PATH="$SCRIPT_DIR/../lib_common.sh" ROLES_DIR="$REPO_ROOT/backend/roles" \
  EPHEMERAL_NAME="$EPHEMERAL_NAME" MVP_POSTGRES_CONTAINER="$EPHEMERAL_NAME" \
  BOOTSTRAP_USER="$BOOTSTRAP_USER" BOOTSTRAP_PASSWORD="$BOOTSTRAP_PASSWORD" \
  APP_PW="$APP_PW" MIGRATOR_PW="$MIGRATOR_PW" REFERENCE_PW="$REFERENCE_PW" \
  MSYS_NO_PATHCONV=1 \
  bash "$PROVISION_SCRIPT" >/tmp/verify7.log 2>&1
step_ok=$?
set -e
rm -f "$PROVISION_SCRIPT"
docker rm -f "$EPHEMERAL_NAME" >/dev/null 2>&1 || true
if [ "$step_ok" -eq 0 ]; then
  report "postgres-bootstrap-db -> 00_create_roles.sql -> 01_database_grants.sql, en orden, contra Postgres efímero" 0
else
  echo "--- log de la fase 7 ---"; cat /tmp/verify7.log
  report "postgres-bootstrap-db -> 00_create_roles.sql -> 01_database_grants.sql, en orden, contra Postgres efímero" 1
fi

echo "=== 8/10: comprobación de secretos (ningún archivo publicado contiene una contraseña real) ==="
if ! grep -rEn 'PASSWORD\s*=\s*[^C][^H][^A][^N][^G][^E]' "$MVP_DIR/env" 2>/dev/null \
   | grep -vE 'CHANGE_ME|test_only_not_real'; then
  report "ningún .env.example de deploy/mvp/env contiene algo distinto de CHANGE_ME" 0
else
  report "ningún .env.example de deploy/mvp/env contiene algo distinto de CHANGE_ME" 1
fi
if ! grep -rln "$BOOTSTRAP_PASSWORD\|$APP_PW\|$MIGRATOR_PW\|$REFERENCE_PW" "$MVP_DIR" /tmp/verify7.log /tmp/shellcheck-*.log /tmp/nginx-t.log 2>/dev/null; then
  report "ninguna contraseña generada en esta prueba quedó impresa en archivos ni logs" 0
else
  report "ninguna contraseña generada en esta prueba quedó impresa en archivos ni logs" 1
fi

echo "=== 9/10: bloqueo por falta de CONFIRM=yes / AUTHORIZED_COMMIT / TVC_BACKUP_CONFIRMED ==="
set +e
( unset CONFIRM; bash "$SCRIPT_DIR/../deploy.sh" user-and-dirs ) >/tmp/verify9a.log 2>&1
r1=$?
( unset AUTHORIZED_COMMIT; CONFIRM=yes bash "$SCRIPT_DIR/../deploy.sh" checkout 0000000000000000000000000000000000000000 ) >/tmp/verify9b.log 2>&1
r2=$?
( unset TVC_BACKUP_CONFIRMED; CONFIRM=yes bash "$SCRIPT_DIR/../deploy.sh" postgres-up ) >/tmp/verify9c.log 2>&1
r3=$?
( unset CONFIRM; bash "$SCRIPT_DIR/../rollback.sh" all ) >/tmp/verify9d.log 2>&1
r4=$?
set -e
if [ "$r1" -ne 0 ] && [ "$r2" -ne 0 ] && [ "$r3" -ne 0 ] && [ "$r4" -ne 0 ]; then
  report "cada fase de riesgo se niega a ejecutar sin su confirmación explícita" 0
else
  echo "r1=$r1 r2=$r2 r3=$r3 r4=$r4"
  report "cada fase de riesgo se niega a ejecutar sin su confirmación explícita" 1
fi

echo "=== 10/10: diff estructural contra main ==="
git -C "$REPO_ROOT" fetch origin main --quiet 2>/dev/null || true
if git -C "$REPO_ROOT" diff --name-only origin/main...HEAD -- deploy/mvp | grep -q .; then
  report "hay diferencias frente a main, limitadas a deploy/mvp (revisar manualmente la lista)" 0
  git -C "$REPO_ROOT" diff --name-only origin/main...HEAD -- deploy/mvp
else
  report "hay diferencias frente a main, limitadas a deploy/mvp (revisar manualmente la lista)" 1
fi
if git -C "$REPO_ROOT" diff --name-only origin/main...HEAD | grep -qv '^deploy/mvp/'; then
  report "el diff NO toca nada fuera de deploy/mvp (ninguna migración, servicio TVC, etc.)" 1
else
  report "el diff NO toca nada fuera de deploy/mvp (ninguna migración, servicio TVC, etc.)" 0
fi

echo "=== Resultado: $PASS OK, $FAILED FALLAS ==="
exit "$FAILED"
