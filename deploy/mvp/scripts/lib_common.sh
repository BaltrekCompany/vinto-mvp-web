# VINTO MVP WEB — funciones compartidas por deploy.sh / rollback.sh / preflight.sh (CLOUD-DEP-02A.2).
#
# Se cargan con `source`, nunca se ejecutan solas. Objetivo de este archivo (DEP55-01/02/03/04):
#   - Un único lugar que decide "¿este recurso es realmente del MVP?" antes de detenerlo, borrarlo o
#     modificarlo, para no repetir (y arriesgar que diverja) la misma lógica de seguridad en 3 scripts.
#   - Leer valores de un .env SIN "source"-arlo nunca: un valor de configuración es texto, nunca
#     código de shell que se ejecuta (DEP55-01 punto 2 y 3).
#
# Este archivo no se ejecuta en este incremento (CLOUD-DEP-02A.2 es de preparación; ver DEP-02B).

# Usadas por deploy.sh/rollback.sh/preflight.sh, no directamente por este archivo: ShellCheck no
# lo ve si este archivo se analiza solo (de ahí los "disable" puntuales de abajo); confirmado sin
# ningún aviso con `shellcheck -x deploy.sh rollback.sh preflight.sh`, que sí sigue el `source`.
#
# ":=" en vez de "=": permite que deploy/mvp/scripts/tests/verify_local.sh inyecte, vía variables
# de entorno YA EXPORTADAS antes de este "source", un contenedor/nombre de prueba efímero distinto
# del real — sin esto, el "source" de este archivo sobrescribiría cualquier valor exportado por la
# prueba. En deploy.sh/rollback.sh/preflight.sh (que nunca exportan estas variables) el efecto es
# idéntico a una asignación normal: siempre toman el valor real de abajo.
: "${MVP_APP_DIR:=/opt/vinto-mvp-web}"
# shellcheck disable=SC2034
: "${MVP_SERVICE_USER:=vinto-mvp}"
: "${MVP_COMPOSE_PROJECT:=vinto-mvp}"
: "${MVP_POSTGRES_CONTAINER:=vinto-mvp-postgres}"
# shellcheck disable=SC2034
: "${MVP_NETWORK:=vinto-mvp-internal}"
TVC_APP_DIR="/opt/vinto-web"
TVC_ETL_DIR="/opt/vinto-etl"
TVC_PGDATA_DIR="/home/ubuntu/vinto/pgdata"

require_confirm() {
  if [ "${CONFIRM:-}" != "yes" ]; then
    echo "Esta fase requiere CONFIRM=yes de forma explícita. No se ejecuta nada." >&2
    exit 1
  fi
}

# Lee el valor de UNA clave de un archivo .env como texto literal. Nunca ejecuta el archivo:
# a diferencia de `source archivo.env`, un valor como FOO=$(comando) o FOO=`comando` se devuelve
# tal cual, como cadena, sin interpretarse jamás como código de shell (DEP55-01 punto 2 y 3).
# Uso: valor="$(env_value /ruta/al/.env NOMBRE_CLAVE)"
env_value() {
  local file="$1" key="$2"
  if [ ! -f "$file" ]; then
    echo "env_value: no existe $file" >&2
    return 1
  fi
  local line
  line="$(grep -E "^${key}=" "$file" | tail -n1)" || true
  if [ -z "$line" ]; then
    echo "env_value: no se encontró la clave $key en $file" >&2
    return 1
  fi
  line="${line#"${key}"=}"
  # Quita comillas envolventes si las hay (p. ej. CORS_ORIGINS='["https://x"]'); no interpreta nada más.
  line="${line%\"}"; line="${line#\"}"
  line="${line%\'}"; line="${line#\'}"
  printf '%s' "$line"
}

# Extrae la contraseña de una URL postgresql://usuario:contraseña@host:puerto/base, como texto
# literal (regex, no shell eval). Usado para reaprovisionar roles con la MISMA contraseña que ya
# está en backend/.env, sin pedir el secreto una segunda vez ni volver a imprimirlo.
password_from_pg_url() {
  local url="$1"
  if [[ "$url" =~ ^postgresql://[^:]+:([^@]+)@ ]]; then
    printf '%s' "${BASH_REMATCH[1]}"
  else
    echo "password_from_pg_url: no se reconoce el formato de la URL" >&2
    return 1
  fi
}

# Verifica que un contenedor Docker con ese nombre es realmente del MVP (proyecto de
# docker-compose = vinto-mvp) antes de que cualquier script lo detenga, elimine o le ejecute SQL
# administrativo encima. Si el contenedor no existe, no es un error (nada que verificar). Si existe
# pero no es nuestro, aborta sin tocarlo (DEP55-01 punto 5: comprobar identidad antes de modificar).
assert_container_is_ours() {
  local name="$1"
  if ! docker inspect "$name" >/dev/null 2>&1; then
    return 0
  fi
  local project
  project="$(docker inspect "$name" --format '{{ index .Config.Labels "com.docker.compose.project" }}' 2>/dev/null || true)"
  if [ "$project" != "$MVP_COMPOSE_PROJECT" ]; then
    echo "FALLA DE IDENTIDAD: el contenedor '$name' existe pero su etiqueta com.docker.compose.project es '${project:-ninguna}', no '$MVP_COMPOSE_PROJECT'. No es del MVP (quizá es de TVC/ETL u otro proyecto). Abortando SIN tocarlo." >&2
    exit 1
  fi
}

# Verifica que una red Docker con ese nombre es realmente la del MVP antes de reutilizarla o
# recrearla (DEP55-03: "red Docker ajena al MVP").
assert_network_is_ours() {
  local name="$1"
  if ! docker network inspect "$name" >/dev/null 2>&1; then
    return 0
  fi
  local project
  project="$(docker network inspect "$name" --format '{{ index .Labels "com.docker.compose.project" }}' 2>/dev/null || true)"
  if [ "$project" != "$MVP_COMPOSE_PROJECT" ]; then
    echo "FALLA DE IDENTIDAD: la red Docker '$name' existe pero no está etiquetada como del MVP (etiqueta: '${project:-ninguna}'). Abortando SIN tocarla." >&2
    exit 1
  fi
}

# Verifica que una unidad systemd instalada en el host es la que ESTE despliegue instaló
# (WorkingDirectory dentro de /opt/vinto-mvp-web) antes de detenerla/deshabilitarla/borrarla
# (DEP55-01 punto 5). Si el archivo de unidad no existe, no es un error.
assert_unit_is_ours() {
  local unit="$1"
  local unit_file="/etc/systemd/system/$unit"
  if [ ! -f "$unit_file" ]; then
    return 0
  fi
  if ! grep -q "WorkingDirectory=$MVP_APP_DIR" "$unit_file" 2>/dev/null \
     && ! grep -qE "^ExecStart=.*$MVP_APP_DIR" "$unit_file" 2>/dev/null; then
    echo "FALLA DE IDENTIDAD: $unit_file existe pero no referencia $MVP_APP_DIR. Podría ser una unidad de otro proyecto con el mismo nombre. Abortando SIN tocarla." >&2
    exit 1
  fi
}

# Verifica que el usuario de servicio, si ya existe, tiene la forma esperada (sin home, sin login)
# antes de reutilizarlo (DEP55-03: "usuario de servicio existente no verificado").
assert_service_user_is_ours() {
  local user="$1"
  if ! id "$user" >/dev/null 2>&1; then
    return 0
  fi
  local shell home
  shell="$(getent passwd "$user" | cut -d: -f7)"
  home="$(getent passwd "$user" | cut -d: -f6)"
  case "$shell" in
    */nologin|/bin/false) : ;;
    *)
      echo "FALLA DE IDENTIDAD: el usuario '$user' ya existe con shell '$shell' (se esperaba nologin). Podría ser un usuario preexistente no relacionado con este despliegue. Abortando SIN reutilizarlo." >&2
      exit 1
      ;;
  esac
  if [ -d "$home" ] && [ "$home" != "/nonexistent" ] && [ "$home" != "/" ]; then
    if [ "$(stat -c '%U' "$home" 2>/dev/null)" != "$user" ]; then
      echo "FALLA DE IDENTIDAD: el home de '$user' ($home) no pertenece a ese usuario. Abortando SIN reutilizarlo." >&2
      exit 1
    fi
  fi
}

# Verifica que una ruta de datos (bind-mount) propuesta no está ya en uso como mount de OTRO
# contenedor (TVC/ETL u otro), y que no está dentro de los directorios de TVC (DEP55-03:
# "volumen o bind-mount potencialmente compartido").
assert_path_not_shared_with_other_containers() {
  local path="$1"
  case "$path" in
    "$TVC_APP_DIR"|"$TVC_APP_DIR"/*|"$TVC_ETL_DIR"|"$TVC_ETL_DIR"/*|"$TVC_PGDATA_DIR"|"$TVC_PGDATA_DIR"/*)
      echo "FALLA: la ruta de datos '$path' está dentro de un directorio de TVC/ETL. Elegir otra ruta. Abortando." >&2
      exit 1
      ;;
  esac
  if command -v docker >/dev/null 2>&1; then
    local conflict
    conflict="$(docker ps -a --format '{{.Names}}' | while read -r name; do
      [ "$name" = "$MVP_POSTGRES_CONTAINER" ] && continue
      docker inspect "$name" --format '{{range .Mounts}}{{.Source}}{{"\n"}}{{end}}' 2>/dev/null | grep -Fx "$path" && echo "$name"
    done | tail -n1)"
    if [ -n "$conflict" ]; then
      echo "FALLA: la ruta '$path' ya está montada en el contenedor ajeno '$conflict'. Abortando." >&2
      exit 1
    fi
  fi
}

# --- Ejecución de SQL contra el PostgreSQL del MVP sin exponer contraseñas (PG54-03) ----------
#
# Ninguna contraseña se pasa como argumento de línea de comandos ni como "docker exec -e" (eso
# SÍ sería visible brevemente en la lista de procesos del host mientras el comando corre): la
# contraseña de CONEXIÓN se escribe en un .pgpass temporal (600) dentro del contenedor, vía stdin,
# y se borra al terminar; las contraseñas que un .sql necesite leer con \getenv (p. ej. para un
# CREATE ROLE) se pasan en un archivo --env-file de 600 en el HOST (nunca como -e literal), que
# también se borra al terminar.

# Traduce una ruta de archivo del HOST a la forma que el propio binario de docker necesita para
# encontrarla como argumento de "--env-file" (p. ej. "docker exec --env-file"): en Linux (el VPS
# real) es un no-op; en Windows/Git Bash, usa cygpath si está disponible. No afecta a ninguna ruta
# DENTRO de un contenedor (esas nunca pasan por aquí).
_docker_host_path() {
  local path="$1"
  if command -v cygpath >/dev/null 2>&1; then
    cygpath -w "$path"
  else
    printf '%s' "$path"
  fi
}

_pg_write_pgpass() {
  local role="$1" password="$2" db="$3"
  printf '127.0.0.1:5432:%s:%s:%s\n' "$db" "$role" "$password" \
    | docker exec -i "$MVP_POSTGRES_CONTAINER" sh -c 'umask 077; cat > /tmp/.deploy-pgpass'
}

_pg_cleanup() {
  local extra_remote="${1:-}"
  docker exec "$MVP_POSTGRES_CONTAINER" rm -f /tmp/.deploy-pgpass ${extra_remote:+"$extra_remote"}
}

# pg_run_sql_inline <role> <password> <db> <sentencia-sql>
pg_run_sql_inline() {
  local role="$1" password="$2" db="$3" sql="$4"
  assert_container_is_ours "$MVP_POSTGRES_CONTAINER"
  _pg_write_pgpass "$role" "$password" "$db"
  local status=0
  docker exec -e PGPASSFILE=/tmp/.deploy-pgpass "$MVP_POSTGRES_CONTAINER" \
    psql -h 127.0.0.1 -U "$role" -d "$db" -v ON_ERROR_STOP=1 -tAc "$sql" || status=$?
  _pg_cleanup
  return "$status"
}

# pg_run_sql_file <role> <password> <db> <archivo-sql-local> [NOMBRE=valor ...]
# Los pares NOMBRE=valor finales se exponen al proceso psql (y por tanto a \getenv dentro del
# .sql) vía --env-file, nunca vía -e. El contenido del archivo se envía por stdin ("psql -f -"):
# nunca se usa "docker cp" con la ruta del host como argumento de línea de comandos (ese argumento
# puede ser reescrito de formas distintas por distintos shells/entornos; leerlo con la
# redirección "< archivo" de bash, en cambio, no depende de cómo el shell reescriba argumentos).
pg_run_sql_file() {
  local role="$1" password="$2" db="$3" sql_file="$4"; shift 4
  assert_container_is_ours "$MVP_POSTGRES_CONTAINER"
  _pg_write_pgpass "$role" "$password" "$db"
  local envfile="" docker_env_args=()
  if [ "$#" -gt 0 ]; then
    envfile="$(mktemp)"
    chmod 600 "$envfile"
    printf '%s\n' "$@" > "$envfile"
    docker_env_args=(--env-file "$(_docker_host_path "$envfile")")
  fi
  local status=0
  docker exec -i -e PGPASSFILE=/tmp/.deploy-pgpass "${docker_env_args[@]}" "$MVP_POSTGRES_CONTAINER" \
    psql -h 127.0.0.1 -U "$role" -d "$db" -v ON_ERROR_STOP=1 -f - < "$sql_file" || status=$?
  [ -n "$envfile" ] && rm -f "$envfile"
  _pg_cleanup
  return "$status"
}
