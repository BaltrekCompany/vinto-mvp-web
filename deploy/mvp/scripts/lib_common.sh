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
: "${MVP_SERVICE_USER:=vinto-mvp}"
: "${MVP_COMPOSE_PROJECT:=vinto-mvp}"
: "${MVP_POSTGRES_CONTAINER:=vinto-mvp-postgres}"
# shellcheck disable=SC2034
: "${MVP_NETWORK:=vinto-mvp-internal}"
TVC_APP_DIR="/opt/vinto-web"
TVC_ETL_DIR="/opt/vinto-etl"
TVC_PGDATA_DIR="/home/ubuntu/vinto/pgdata"

# Comprueba /health, /api/health y la raíz del frontend. Usada por deploy.sh (fase "healthcheck" y
# dentro de "activate") Y por rollback.sh ("version", CLOUD-DEP-02A.2-R2-2: "comprobar salud tras
# reiniciar, nunca afirmar éxito sin comprobarlo"). Un único lugar evita que las dos copias diverjan.
mvp_healthcheck() {
  curl -fsS http://127.0.0.1:8100/health >/dev/null \
    && curl -fsS http://127.0.0.1:8100/api/health >/dev/null \
    && curl -fsS http://127.0.0.1:3100/ >/dev/null
}

# Detecta qué comando Compose está disponible, sin instalar ni preferir uno por encima del otro
# salvo por disponibilidad (CLOUD-DEP-02B.1-C.1, Fase D): el VPS real solo tiene el binario
# standalone "docker-compose" (confirmado v5.3.1, mismo motor que el plugin "docker compose" —
# su propio --help se autodenomina "docker compose"); el entorno local de pruebas normalmente
# tiene el plugin. Nunca instala nada ni reinicia Docker: solo decide con qué invocar. Resultado
# en el array global COMPOSE_CMD (p. ej. ("docker" "compose") o ("docker-compose")), para usarse
# como "${COMPOSE_CMD[@]}" -f archivo.yml ...
COMPOSE_CMD=()
detect_compose_cmd() {
  if [ "${#COMPOSE_CMD[@]}" -gt 0 ]; then
    return 0
  fi
  if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD=(docker compose)
  elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD=(docker-compose)
  else
    echo "FALLA: ni 'docker compose' (plugin) ni 'docker-compose' (binario standalone) están disponibles. No se puede continuar con las fases de PostgreSQL." >&2
    exit 1
  fi
}

# CLOUD-DEP-02B.1-E.6-A.1: $MVP_APP_DIR es 750, propiedad exclusiva de $MVP_SERVICE_USER
# (vinto-mvp) — user-and-dirs lo deja así a propósito (DEP55-04), y así debe permanecer. El
# operador que invoca deploy.sh/rollback.sh/preflight.sh (siempre "ubuntu" en el VPS real, NUNCA
# root/sudo sobre el script completo — confirmado en CLOUD-DEP-02B.1-D) no tiene ni permiso de
# tránsito sobre ese árbol. Evaluar "[ -e/-f/-d/-x/-L ... ]", "stat" o "readlink" sobre una ruta
# DENTRO de $MVP_APP_DIR como ese operador es, en la práctica, un "permission denied" disfrazado
# de "no existe" — confirmado empíricamente primero en "install-node-runtime" (CLOUD-DEP-02B.1-D,
# corregido en PR #57) y de nuevo, de forma mucho más extendida, en la auditoría E.6-A sobre
# "checkout"/"python-venv"/"install-frontend-artifact"/"activate"/"rollback.sh version"/
# "preflight.sh". Toda lectura sobre una ruta privada del MVP debe pasar por estas funciones
# (nunca repetir "sudo -u ... test"/"stat"/"readlink" suelto fuera de aquí, para que una futura
# corrección de este patrón solo tenga que tocar un sitio).
#
# assert_can_read_mvp_private_paths: confirma que "sudo -u $MVP_SERVICE_USER" es viable desde
# este invocador ANTES de usarlo para decidir nada — si no lo es (sudoers mal configurado,
# usuario inexistente), cada mvp_test/mvp_readlink_f/mvp_stat de más abajo fallaría en silencio
# igual que la lectura directa (sudo imprime su propio error a stderr, que normalmente no se
# examina), produciendo el mismo "permission denied disfrazado de no existe" que esto corrige.
# Se llama una vez al principio de cada fase que dependa de estas funciones.
assert_can_read_mvp_private_paths() {
  if ! sudo -u "$MVP_SERVICE_USER" true 2>/dev/null; then
    echo "FALLA: no se puede ejecutar 'sudo -u $MVP_SERVICE_USER' desde este invocador. Sin esto, ninguna comprobación sobre rutas dentro de $MVP_APP_DIR (750, exclusivo de $MVP_SERVICE_USER) puede distinguir 'no existe' de 'sin permiso para verlo'. Revisar la configuración de sudoers antes de reintentar." >&2
    exit 1
  fi
}

# mvp_test <bandera-de-test...> -- equivalente a "[ <bandera> ... ]", evaluado como
# $MVP_SERVICE_USER en vez de como el invocador. Uso: mvp_test -e "$ruta", mvp_test ! -d "$ruta".
mvp_test() {
  sudo -u "$MVP_SERVICE_USER" test "$@"
}

# mvp_readlink_f <ruta> -- "readlink -f <ruta>" como $MVP_SERVICE_USER.
mvp_readlink_f() {
  sudo -u "$MVP_SERVICE_USER" readlink -f "$1"
}

# mvp_stat <formato> <ruta> -- "stat -c <formato> <ruta>" como $MVP_SERVICE_USER (p. ej.
# mvp_stat '%a' "$ruta" para permisos octales, igual que "stat -c '%a'" normal).
mvp_stat() {
  sudo -u "$MVP_SERVICE_USER" stat -c "$1" "$2"
}

# Verifica que el esquema de vinto_piloto está completamente migrado (migrate.py --check, con el
# venv del release activo) ANTES de aplicar privilegios sobre tablas/funciones que todavía podrían
# no existir, o de arrancar un backend que fallaría en tiempo de ejecución contra un esquema
# incompleto (CLOUD-DEP-02A.2-R2-2, punto 1: "impedir que postgres-grants y el arranque continúen
# si el esquema requerido no está migrado"). Mantiene la aprobación explícita para APLICAR
# migraciones intacta: esta función solo verifica (--check), nunca ejecuta migrate.py sin --check.
assert_schema_migrated() {
  assert_can_read_mvp_private_paths
  local release_dir="$MVP_APP_DIR/current"
  if ! mvp_test -d "$release_dir/backend"; then
    echo "FALLA: $release_dir/backend no existe. Ejecutar 'activate <sha>' primero." >&2
    exit 1
  fi
  local log
  log="$(mktemp)"
  # shellcheck disable=SC2024 # la redirección la abre ESTE shell (no el proceso con sudo), sobre
  # un archivo de mktemp ya propio: no hace falta que el usuario con sudo pueda escribirlo.
  if ! sudo -u "$MVP_SERVICE_USER" "$release_dir/backend/.venv/bin/python" "$release_dir/backend/migrate.py" \
      --target dev --check >"$log" 2>&1; then
    echo "FALLA: el esquema de vinto_piloto no está completamente migrado (migrate.py --target dev --check falló):" >&2
    cat "$log" >&2
    rm -f "$log"
    echo "Ejecutar 'deploy.sh migrate' (con autorización explícita, revisando qué queda pendiente antes de aplicar) antes de continuar." >&2
    exit 1
  fi
  rm -f "$log"
}

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

# CLOUD-DEP-02B.1-E.6-A.1: variante de "env_value" para archivos DENTRO de $MVP_APP_DIR (p. ej.
# current/backend/.env) — "env_value" normal, evaluada como el invocador (ubuntu), no puede ni
# comprobar que el archivo existe ni leerlo ahí (750, exclusivo de $MVP_SERVICE_USER). Para
# archivos FUERA del árbol privado (p. ej. docker/.env) sigue usándose "env_value" normal: no
# convertir aquella en privilegiada de forma incondicional sería leer con más privilegio del que
# ese caso necesita. Misma semántica exacta que "env_value", solo cambia el usuario que lee.
mvp_env_value() {
  local file="$1" key="$2"
  if ! mvp_test -f "$file"; then
    echo "mvp_env_value: no existe $file" >&2
    return 1
  fi
  local line
  line="$(sudo -u "$MVP_SERVICE_USER" grep -E "^${key}=" "$file" | tail -n1)" || true
  if [ -z "$line" ]; then
    echo "mvp_env_value: no se encontró la clave $key en $file" >&2
    return 1
  fi
  line="${line#"${key}"=}"
  line="${line%\"}"; line="${line#\"}"
  line="${line%\'}"; line="${line#\'}"
  printf '%s' "$line"
}

# Decodifica porcentaje (RFC 3986) de un texto, p. ej. "%40" -> "@". Las contraseñas dentro de
# una URL postgresql:// que contienen ":"/"@"/"/" deben llevarlo codificado así (DEP55-R2-03:
# "contraseñas codificadas"); sin esto, password_from_pg_url devolvería el texto codificado en
# vez de la contraseña real. Solo texto, nunca se evalúa como shell.
_url_decode() {
  local data="${1//+/ }"
  printf '%b' "${data//%/\\x}"
}

# Extrae la contraseña de una URL postgresql://usuario:contraseña@host:puerto/base, como texto
# literal (regex, no shell eval), ya decodificada de porcentaje. Usado para reaprovisionar roles
# con la MISMA contraseña que ya está en backend/.env, sin pedir el secreto una segunda vez ni
# volver a imprimirlo. El error NUNCA incluye la URL ni la contraseña, solo que el formato no se
# reconoció (DEP55-R2-03: "los errores no filtran credenciales").
password_from_pg_url() {
  local url="$1"
  if [[ "$url" =~ ^postgresql://[^:]+:([^@]+)@ ]]; then
    _url_decode "${BASH_REMATCH[1]}"
  else
    echo "password_from_pg_url: no se reconoce el formato de la URL (longitud recibida: ${#url})" >&2
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

# --- Contrato de seguridad de docker/.env (CLOUD-DEP-02B.2-D.1) --------------------------------
#
# docker/.env contiene POSTGRES_BOOTSTRAP_PASSWORD (el rol de arranque del clúster de Postgres,
# equivalente a un administrador del clúster) en texto plano. A diferencia de
# shared/backend.env — que SÍ debe ser legible por $MVP_SERVICE_USER, porque el proceso de la API
# y las herramientas administrativas corren bajo esa identidad —, docker/.env NUNCA debe ser
# legible por $MVP_SERVICE_USER: solo lo necesita el operador que invoca "docker compose"
# directamente (en el VPS real, "ubuntu"), nunca el proceso del MVP. Si $MVP_SERVICE_USER pudiera
# leerlo, comprometer el backend filtraría también la contraseña de arranque del clúster, hoy
# fuera de su alcance.
#
# docker_env_contract_check <path>: NUNCA llama a "exit" ni imprime el contenido del archivo —
# deja el resultado en el código de retorno (0 = cumple el contrato) y el motivo del primer fallo
# en DOCKER_ENV_CONTRACT_REASON (una frase para el operador, nunca un valor leído del archivo).
# Los llamadores deciden qué hacer con un fallo: las fases MUTADORAS de deploy.sh deben detenerse
# (ver assert_docker_env_contract, más abajo); rollback.sh, en cambio, debe degradar a su camino
# ya existente de "tratarlo como ausente" — una recuperación legítima nunca debe volverse
# imposible solo porque este archivo de configuración tenga un problema de permisos.
#
# El propietario esperado se resuelve con "id -un" (quien invoca ESTE proceso), nunca con un
# nombre de usuario fijo como "ubuntu": el VPS real podría nombrar distinto a ese operador, y
# deploy.sh/rollback.sh nunca se ejecutan completos como root/sudo (ver nota en deploy.sh).
DOCKER_ENV_CONTRACT_REASON=""
docker_env_contract_check() {
  DOCKER_ENV_CONTRACT_REASON=""
  local path="${1:-}"
  if [ -z "$path" ]; then
    DOCKER_ENV_CONTRACT_REASON="ruta vacía."
    return 1
  fi
  case "$path" in
    "$MVP_APP_DIR"|"$MVP_APP_DIR"/*)
      DOCKER_ENV_CONTRACT_REASON="$path está dentro de $MVP_APP_DIR (el árbol privado de $MVP_SERVICE_USER). docker/.env nunca debe vivir ahí: mezclaría su modelo de permisos con el de shared/backend.env."
      return 1
      ;;
  esac
  # "-L" ANTES de cualquier otra comprobación (misma lección de DEP60-01 para shared/backend.env):
  # nunca un enlace simbólico, incluso si resuelve a un archivo válido con permisos/propietario
  # correctos — un enlace añade una segunda ruta de control sobre el contenido real.
  if [ -L "$path" ]; then
    DOCKER_ENV_CONTRACT_REASON="$path es un enlace simbólico. Debe ser un archivo regular, incluso si el enlace resuelve a un archivo válido."
    return 1
  fi
  if [ ! -e "$path" ]; then
    DOCKER_ENV_CONTRACT_REASON="$path no existe."
    return 1
  fi
  if [ -d "$path" ]; then
    DOCKER_ENV_CONTRACT_REASON="$path es un directorio, no un archivo regular."
    return 1
  fi
  if [ ! -f "$path" ]; then
    DOCKER_ENV_CONTRACT_REASON="$path existe pero no es un archivo regular."
    return 1
  fi
  # El directorio que lo contiene no debe ser escribible por grupo ni por otros: cualquiera con
  # ese acceso podría sustituir el archivo por otro bajo el mismo nombre, sin tocar el archivo en
  # sí (y por tanto sin que ninguna comprobación posterior sobre EL ARCHIVO lo detecte).
  local parent_dir perms_dir group_other_bits
  parent_dir="$(dirname "$path")"
  perms_dir="$(stat -c '%a' "$parent_dir" 2>/dev/null || true)"
  if [ -n "$perms_dir" ]; then
    group_other_bits="${perms_dir: -2}"
    case "$group_other_bits" in
      *[2367]*)
        DOCKER_ENV_CONTRACT_REASON="el directorio $parent_dir tiene permisos $perms_dir (escribible por grupo u otros); cualquiera con ese acceso podría sustituir $path. Corregir el directorio antes de continuar."
        return 1
        ;;
    esac
  fi
  local expected_owner actual_owner
  expected_owner="$(id -un)"
  actual_owner="$(stat -c '%U' "$path" 2>/dev/null || true)"
  if [ "$actual_owner" != "$expected_owner" ]; then
    DOCKER_ENV_CONTRACT_REASON="$path pertenece a '$actual_owner', debe pertenecer a '$expected_owner' (quien invoca este script y ejecuta Docker Compose)."
    return 1
  fi
  # Nunca $MVP_SERVICE_USER: ni como propietario ni con acceso de lectura por ningún otro medio
  # (grupo, otros, ACL) -- comprobación explícita y activa, no solo "el propietario no es
  # vinto-mvp" (un permiso de grupo/otros demasiado abierto filtraría el secreto igual).
  if [ "$actual_owner" = "$MVP_SERVICE_USER" ]; then
    DOCKER_ENV_CONTRACT_REASON="$path pertenece a $MVP_SERVICE_USER. Nunca debe pertenecer al usuario de servicio del MVP: contiene el secreto de arranque del clúster de Postgres, que $MVP_SERVICE_USER no necesita y no debe poder leer."
    return 1
  fi
  local perms
  perms="$(stat -c '%a' "$path" 2>/dev/null || true)"
  if [ "$perms" != "600" ]; then
    DOCKER_ENV_CONTRACT_REASON="$path tiene permisos ${perms:-desconocidos}, deben ser exactamente 600."
    return 1
  fi
  # Con propietario y permisos YA confirmados correctos, esta comprobación ACTIVA es la última
  # línea de defensa contra un mecanismo que "stat" no refleja (p. ej. una ACL POSIX que concede
  # lectura a $MVP_SERVICE_USER pese a que los bits clásicos de owner/group/other ya parecen 600)
  # -- nunca el primer motivo de rechazo para un error simple de permisos, que ya se reportó arriba
  # con un mensaje más específico.
  if id "$MVP_SERVICE_USER" >/dev/null 2>&1 && sudo -u "$MVP_SERVICE_USER" test -r "$path" 2>/dev/null; then
    DOCKER_ENV_CONTRACT_REASON="$MVP_SERVICE_USER puede leer $path (permisos demasiado abiertos, probablemente vía ACL: propietario y modo 600 ya son correctos). $MVP_SERVICE_USER nunca debe tener acceso a este archivo."
    return 1
  fi
  # Defensivo frente a otros mecanismos que "stat" no refleja: confirmar que el operador actual
  # puede leerlo de verdad, no solo que propietario/permisos parecen correctos.
  if [ ! -r "$path" ]; then
    DOCKER_ENV_CONTRACT_REASON="$path no es legible por el operador actual ($expected_owner), aunque propietario y permisos parezcan correctos (revisar ACLs)."
    return 1
  fi
  return 0
}

# Variante que detiene la fase (deploy.sh): usarla ANTES de cualquier operación mutadora que
# dependa de docker/.env. Nunca cambia permisos/propietario automáticamente — solo reporta y
# detiene; corregirlo es siempre una acción manual y deliberada del operador.
assert_docker_env_contract() {
  if ! docker_env_contract_check "$1"; then
    echo "FALLA: $DOCKER_ENV_CONTRACT_REASON" >&2
    exit 1
  fi
}

# --- Identidad ESTRICTA del contenedor de Postgres del MVP (DEP61-01) --------------------------
#
# resolve_confirmed_mvp_postgres_id <nombre> <imagen-esperada>: para operaciones de RECUPERACIÓN
# que no pueden confiar en Docker Compose (ver rollback.sh::rollback_postgres) y por tanto no
# pueden dejar que Compose decida, por sí solo, si un contenedor es "nuestro". Nunca basta con el
# nombre: exige ADEMÁS que la etiqueta de proyecto compose y la imagen coincidan EXACTAMENTE con
# lo que docker-compose.postgres.yml declara, y solo entonces resuelve y fija el ID real (hash)
# del contenedor en MVP_POSTGRES_CONTAINER_ID. Toda operación posterior debe actuar sobre ESE ID,
# nunca volver a buscar por nombre (evita una sustitución entre la comprobación y la acción,
# TOCTOU). "No existe" es un estado LEGÍTIMO, nunca un error: deja MVP_POSTGRES_CONTAINER_ID
# vacío y retorna 0, para que el llamador lo trate de forma explícita e idempotente. Si existe
# pero CUALQUIER señal de identidad no coincide, se detiene (exit 1) — mismo criterio fail-closed
# que el resto de las funciones "assert_*" de este archivo, nunca se opera sobre un contenedor
# cuya identidad no se pudo confirmar del todo.
#
# DEP61-03 (auditoría del PR #61): la versión anterior trataba CUALQUIER fallo de "docker inspect"
# como "el contenedor no existe" — pero "docker inspect" también falla (mismo código de salida)
# si el daemon es inaccesible, si el operador no tiene permiso, o ante cualquier otro error de
# consulta. Confundir esos casos con "no existe" es un falso negativo peligroso: un contenedor que
# SÍ existe (y sigue corriendo) se reportaría como "nada que detener", dejando a quien opera con
# una falsa sensación de que la recuperación funcionó. Ahora se distingue por el TEXTO del error
# ("no such object"/"no such container", la señal estable que usa el cliente de Docker para
# "realmente no existe"): solo ESE caso se trata como ausencia legítima; cualquier otro error de
# consulta se reporta explícitamente y detiene la función (exit 1) sin asumir nada y sin tocar
# nada — fail-closed, nunca fail-open disfrazado de idempotencia.
# shellcheck disable=SC2034 # usada por rollback.sh tras "source"; ShellCheck no lo ve si este
# archivo se analiza solo (igual que COMPOSE_CMD más arriba).
MVP_POSTGRES_CONTAINER_ID=""
resolve_confirmed_mvp_postgres_id() {
  MVP_POSTGRES_CONTAINER_ID=""
  local name="$1" expected_image="$2"
  local inspected status
  # "if var=$(cmd); then" (nunca una asignación suelta fuera de un "if"): la condición de un "if"
  # es el único contexto exento de "set -e" que captura CORRECTAMENTE tanto la salida como el
  # código de salida de un comando que puede fallar legítimamente (aquí, "docker inspect" sobre
  # un contenedor que no existe). Una asignación suelta ("inspected=\"\$(...)\""; "status=\$?")
  # habría disparado "set -e" en cuanto "docker inspect" devolviera un código distinto de 0 --
  # matando el script ANTES de poder distinguir "no existe" de cualquier otro error (regresión
  # real detectada en la propia batería de pruebas de esta corrección).
  if inspected="$(docker inspect "$name" --format '{{.Id}}|{{ index .Config.Labels "com.docker.compose.project" }}|{{.Config.Image}}' 2>&1)"; then
    status=0
  else
    status=$?
  fi
  if [ "$status" -ne 0 ]; then
    if printf '%s' "$inspected" | grep -qi "no such object\|no such container"; then
      return 0
    fi
    echo "FALLA: no se pudo consultar '$name' en Docker -- la consulta falló con un error DISTINTO de 'no existe' (posible daemon inaccesible, permisos insuficientes, u otro problema). No se asume que el contenedor no existe ni se toca nada; revisar el daemon/los permisos antes de reintentar. Detalle: $inspected" >&2
    exit 1
  fi
  local cid project image rest
  cid="${inspected%%|*}"
  rest="${inspected#*|}"
  project="${rest%%|*}"
  image="${rest#*|}"
  if [ "$project" != "$MVP_COMPOSE_PROJECT" ]; then
    echo "FALLA DE IDENTIDAD: el contenedor '$name' existe pero su etiqueta com.docker.compose.project es '${project:-ninguna}', no '$MVP_COMPOSE_PROJECT'. Podría ser de TVC/ETL u otro proyecto. Abortando SIN tocarlo." >&2
    exit 1
  fi
  if [ "$image" != "$expected_image" ]; then
    echo "FALLA DE IDENTIDAD: el contenedor '$name' existe y su etiqueta de proyecto es correcta, pero su imagen es '${image:-ninguna}', no '$expected_image' (la que fija docker-compose.postgres.yml). Nunca se opera sobre un contenedor cuya imagen no coincide con la esperada. Abortando SIN tocarlo." >&2
    exit 1
  fi
  if [ -z "$cid" ]; then
    echo "FALLA: no se pudo resolver el ID real de '$name' tras confirmar su identidad (nombre, etiqueta de proyecto e imagen). Abortando SIN tocarlo." >&2
    exit 1
  fi
  # shellcheck disable=SC2034 # usada por rollback.sh tras "source"; ShellCheck no lo ve si este
  # archivo se analiza solo (igual que COMPOSE_CMD, más arriba).
  MVP_POSTGRES_CONTAINER_ID="$cid"
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
#
# Corregido en CLOUD-DEP-02A.2 (DEP55-R2-03) tras la auditoría del PR #55:
#   - Ambos archivos temporales usan una ruta ÚNICA POR LLAMADA (PID + aleatorio + nanosegundos),
#     nunca un nombre fijo: dos invocaciones concurrentes (dos operadores, o deploy.sh y un
#     healthcheck solapados) ya no pueden pisarse ni borrar el archivo activo de la otra.
#   - La limpieza usa "trap ... EXIT INT TERM" con la ruta exacta ya resuelta en el momento de
#     crear el archivo: si el proceso se interrumpe (Ctrl-C, kill, error no controlado) a mitad de
#     una llamada, el archivo en uso en ESE momento se borra igual; al terminar con normalidad, el
#     trap se desarma explícitamente (nunca queda un trap de una llamada anterior activo para la
#     siguiente, porque cada llamada solo vive mientras su propia función está en curso).

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

# Sufijo único por llamada: PID propio + número aleatorio de bash + nanosegundos (o segundos si el
# "date" del sistema no soporta %N). Nunca se reutiliza dentro de la misma ejecución del script.
_pg_unique_suffix() {
  printf '%s-%s-%s' "$$" "$RANDOM" "$(date +%s%N 2>/dev/null || date +%s)"
}

# Escribe un .pgpass temporal DENTRO del contenedor indicado, en una ruta única, y la imprime
# por stdout para que el llamador la capture y la use tanto en PGPASSFILE como en su propia
# limpieza. Variante parametrizada por contenedor (CLOUD-DEP-02B.2-D.2): backup.sh necesita
# escribirlo tanto en el contenedor REAL del MVP (para "pg_dump") como en un contenedor EFÍMERO
# de restauración de prueba (para "pg_restore"), nunca en el mismo -- _pg_write_pgpass sigue
# existiendo tal cual para no tocar a pg_run_sql_inline/pg_run_sql_file, que siguen operando
# siempre sobre $MVP_POSTGRES_CONTAINER.
_pg_write_pgpass_in() {
  local container="$1" role="$2" password="$3" db="$4"
  local remote
  remote="/tmp/.deploy-pgpass-$(_pg_unique_suffix)"
  printf '127.0.0.1:5432:%s:%s:%s\n' "$db" "$role" "$password" \
    | docker exec -i "$container" sh -c "umask 077; cat > '$remote'" || return 1
  printf '%s' "$remote"
}
_pg_write_pgpass() {
  local role="$1" password="$2" db="$3"
  _pg_write_pgpass_in "$MVP_POSTGRES_CONTAINER" "$role" "$password" "$db"
}

# pg_run_sql_inline_in <container> <role> <password> <db> <sentencia-sql>: variante parametrizada
# por contenedor (CLOUD-DEP-02B.2-D.2) -- backup.sh la usa para verificar el contenido restaurado
# en el contenedor EFÍMERO de prueba, nunca en $MVP_POSTGRES_CONTAINER. "pg_run_sql_inline" (sin
# "_in") sigue existiendo igual, siempre sobre $MVP_POSTGRES_CONTAINER, para no tocar a sus
# llamadores existentes.
pg_run_sql_inline_in() {
  local container="$1" role="$2" password="$3" db="$4" sql="$5"
  local pgpass_path
  pgpass_path="$(_pg_write_pgpass_in "$container" "$role" "$password" "$db")" || {
    echo "pg_run_sql_inline_in: no se pudo preparar la autenticación (ver mensaje anterior; no se filtró ninguna contraseña)." >&2
    return 1
  }
  # shellcheck disable=SC2064 # se expande AHORA a propósito: la ruta exacta de ESTA llamada.
  trap "docker exec '$container' rm -f '$pgpass_path' >/dev/null 2>&1" EXIT INT TERM
  # DEP55-R2-03: "docker exec" se lanza en segundo plano y se espera con "wait" (builtin), nunca
  # en primer plano directamente. Bash difiere la ejecución de un trap hasta que el comando en
  # primer plano termina — si psql se quedara colgado (o tardara mucho), una señal recibida
  # mientras tanto no limpiaría nada hasta que terminara por sí solo. "wait" SÍ se interrumpe de
  # inmediato al llegar una señal con trap, permitiendo una limpieza pronta en vez de diferida.
  docker exec -e PGPASSFILE="$pgpass_path" "$container" \
    psql -h 127.0.0.1 -U "$role" -d "$db" -v ON_ERROR_STOP=1 -tAc "$sql" &
  local dpid=$! status=0
  wait "$dpid" || status=$?
  docker exec "$container" rm -f "$pgpass_path" >/dev/null 2>&1
  trap - EXIT INT TERM
  return "$status"
}

# pg_run_sql_inline <role> <password> <db> <sentencia-sql>
pg_run_sql_inline() {
  local role="$1" password="$2" db="$3" sql="$4"
  assert_container_is_ours "$MVP_POSTGRES_CONTAINER"
  pg_run_sql_inline_in "$MVP_POSTGRES_CONTAINER" "$role" "$password" "$db" "$sql"
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
  local pgpass_path
  pgpass_path="$(_pg_write_pgpass "$role" "$password" "$db")" || {
    echo "pg_run_sql_file: no se pudo preparar la autenticación (ver mensaje anterior; no se filtró ninguna contraseña)." >&2
    return 1
  }
  local envfile="" docker_env_args=()
  if [ "$#" -gt 0 ]; then
    envfile="$(mktemp)"  # mktemp ya genera un nombre único por llamada en el host.
    chmod 600 "$envfile"
    printf '%s\n' "$@" > "$envfile"
    docker_env_args=(--env-file "$(_docker_host_path "$envfile")")
  fi
  # shellcheck disable=SC2064 # se expanden AHORA: las rutas exactas de ESTA llamada.
  trap "docker exec '$MVP_POSTGRES_CONTAINER' rm -f '$pgpass_path' >/dev/null 2>&1; rm -f '$envfile' 2>/dev/null" EXIT INT TERM
  # Igual que en pg_run_sql_inline (DEP55-R2-03): en segundo plano + "wait", para que una señal
  # con trap se atienda de inmediato en vez de diferirse hasta que termine el comando en curso.
  docker exec -i -e PGPASSFILE="$pgpass_path" "${docker_env_args[@]}" "$MVP_POSTGRES_CONTAINER" \
    psql -h 127.0.0.1 -U "$role" -d "$db" -v ON_ERROR_STOP=1 -f - < "$sql_file" &
  local dpid=$! status=0
  wait "$dpid" || status=$?
  docker exec "$MVP_POSTGRES_CONTAINER" rm -f "$pgpass_path" >/dev/null 2>&1
  [ -n "$envfile" ] && rm -f "$envfile"
  trap - EXIT INT TERM
  return "$status"
}

# --- Dump/restore de PostgreSQL (CLOUD-DEP-02B.2-D.2, backup.sh) -------------------------------
#
# Mismo patrón de seguridad que pg_run_sql_inline/pg_run_sql_file (PG54-03/DEP55-R2-03): la
# contraseña NUNCA se pasa como argumento de línea de comandos ni como "docker exec -e" literal
# -- se escribe en un .pgpass temporal DENTRO del contenedor correspondiente, vía stdin, en una
# ruta única por llamada, borrada en todos los caminos de salida (trap EXIT INT TERM). A
# diferencia de pg_run_sql_inline/pg_run_sql_file (que siempre operan sobre $MVP_POSTGRES_CONTAINER,
# el contenedor REAL del MVP), estas dos funciones toman el contenedor como parámetro explícito:
# backup.sh necesita volcar ("pg_dump") el contenedor real pero restaurar ("pg_restore") en un
# contenedor EFÍMERO de verificación, nunca el mismo, y nunca deben confundirse por un valor
# global compartido.

# pg_restore_custom <container> <role> <password> <db> <ruta_dump_en_el_host>
# Restaura con "--no-owner --no-privileges": el contenedor EFÍMERO de verificación nunca tiene
# los mismos roles (vinto_app/vinto_migrator/vinto_reference) que el dump original -- intentar
# reproducir propietario/privilegios exactos fallaría contra roles inexistentes. Esta función
# verifica INTEGRIDAD de esquema/datos, nunca el modelo de privilegios (eso ya lo cubre
# backend/roles/ + su propia batería, roles_e2e.py).
pg_restore_custom() {
  local container="$1" role="$2" password="$3" db="$4" dump_path="$5"
  local pgpass_path
  pgpass_path="$(_pg_write_pgpass_in "$container" "$role" "$password" "$db")" || {
    echo "pg_restore_custom: no se pudo preparar la autenticación (ver mensaje anterior; no se filtró ninguna contraseña)." >&2
    return 1
  }
  # shellcheck disable=SC2064
  trap "docker exec '$container' rm -f '$pgpass_path' >/dev/null 2>&1" EXIT INT TERM
  docker exec -i -e PGPASSFILE="$pgpass_path" "$container" \
    pg_restore -h 127.0.0.1 -U "$role" -d "$db" --no-owner --no-privileges < "$dump_path" &
  local dpid=$! status=0
  wait "$dpid" || status=$?
  docker exec "$container" rm -f "$pgpass_path" >/dev/null 2>&1
  trap - EXIT INT TERM
  return "$status"
}

# pg_dump_and_manifest_snapshot_consistent <container> <role> <password> <db> <dump_host_out> <manifest_host_out>
#
# DEP62-08 (auditoría del PR #62, opción A -- implementada, no solo diseñada): "pg_dump" y el
# recuento de filas para el manifiesto de contenido comparten el MISMO snapshot MVCC de
# PostgreSQL, así que ninguno de los dos puede ver una escritura concurrente que el otro no vea
# (consistencia real, no solo "capturados con una ventana de milisegundos entre uno y otro").
#
# Mecanismo (verificado empíricamente antes de implementarlo, ver notas de la PR): UNA sola
# sesión "psql" (una sola invocación de "docker exec -i", nunca un coproceso ni una sesión
# interactiva de larga duración con sincronización manual):
#   1. "BEGIN ISOLATION LEVEL REPEATABLE READ" + "SELECT pg_export_snapshot() AS snap \gset"
#      exporta el snapshot de ESA transacción.
#   2. "\setenv PGSNAP :snap" copia el ID exportado a una variable de ENTORNO real (psql NO
#      interpola variables ":nombre" dentro de "\!" directamente -- confirmado empíricamente;
#      "\setenv" es el puente documentado para que un comando de shell sí pueda leerlo).
#   3. "\! pg_dump --snapshot=\"\$PGSNAP\" ..." -- un PROCESO "pg_dump" SEPARADO, lanzado por
#      psql dentro del MISMO contenedor, importa ESE snapshot exacto. La transacción que lo
#      exportó sigue abierta (no se hace COMMIT todavía), así que el snapshot sigue siendo válido.
#   4. TODAVÍA dentro de la MISMA transacción (sin necesitar importar nada: es la misma sesión),
#      se captura el manifiesto con una sola consulta ("query_to_xml"+"xpath", built-in de
#      PostgreSQL, sin extensiones) que cuenta las filas de CADA tabla de usuario -- ninguna
#      escritura posterior a la apertura de la transacción puede alterar lo que esta consulta ve,
#      por la MISMA razón MVCC que protege a "pg_dump". "\o <ruta>" redirige el resultado a un
#      archivo DENTRO del contenedor (el cliente "psql" corre ahí, nunca en el host) -- una
#      consulta de 0 filas (base sin tablas de usuario, DEP62-06) sigue creando el archivo, vacío
#      pero presente, porque "\o" abre el archivo antes de ejecutar la consulta.
#   5. "COMMIT" cierra la transacción (y por tanto el snapshot) solo al final, tras haber usado
#      ambas cosas.
# El volcado y el manifiesto quedan DENTRO del contenedor (esa es la ruta de "psql"/"\!", no la
# del host que invoca "docker exec") -- se extraen con "docker cp" al terminar la sesión, nunca
# antes de confirmar que "pg_dump" (dentro de "\!") terminó con código 0 (capturado explícitamente
# en el propio script, porque "ON_ERROR_STOP" de psql no aborta la sesión solo porque un "\!"
# devuelva un código de salida distinto de cero).
pg_dump_and_manifest_snapshot_consistent() {
  local container="$1" role="$2" password="$3" db="$4" dump_host_out="$5" manifest_host_out="$6"
  local pgpass_path
  pgpass_path="$(_pg_write_pgpass_in "$container" "$role" "$password" "$db")" || {
    echo "pg_dump_and_manifest_snapshot_consistent: no se pudo preparar la autenticación (ver mensaje anterior; no se filtró ninguna contraseña)." >&2
    return 1
  }
  local suffix in_dump in_manifest in_exitcode script session_log
  suffix="$(_pg_unique_suffix)"
  in_dump="/tmp/.deploy-snapdump-$suffix"
  in_manifest="/tmp/.deploy-snapmanifest-$suffix"
  in_exitcode="/tmp/.deploy-snapexit-$suffix"
  script="$(mktemp)"
  chmod 600 "$script"
  cat > "$script" <<'PSQLEOF'
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT pg_export_snapshot() AS snap \gset
\setenv PGSNAP :snap
\! PGPASSFILE=__PGPASS__ pg_dump -h 127.0.0.1 -U __ROLE__ -d __DB__ --snapshot="$PGSNAP" -Fc -f __DUMPPATH__ ; echo $? > __EXITPATH__
\o __MANIFESTPATH__
SELECT quote_ident(table_schema) || '.' || quote_ident(table_name),
       (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM %I.%I', table_schema, table_name), false, true, '')))[1]::text
FROM information_schema.tables
WHERE table_schema NOT IN ('pg_catalog','information_schema')
ORDER BY 1;
\o
COMMIT;
PSQLEOF
  sed -i \
    -e "s#__PGPASS__#$pgpass_path#g" \
    -e "s#__ROLE__#$role#g" \
    -e "s#__DB__#$db#g" \
    -e "s#__DUMPPATH__#$in_dump#g" \
    -e "s#__EXITPATH__#$in_exitcode#g" \
    -e "s#__MANIFESTPATH__#$in_manifest#g" \
    "$script"
  # shellcheck disable=SC2064 # se expanden AHORA: las rutas exactas de ESTA llamada.
  trap "docker exec '$container' rm -f '$pgpass_path' '$in_dump' '$in_manifest' '$in_exitcode' >/dev/null 2>&1; rm -f '$script'" EXIT INT TERM
  session_log="$(mktemp)"
  if ! docker exec -i -e PGPASSFILE="$pgpass_path" "$container" \
      psql -h 127.0.0.1 -U "$role" -d "$db" -v ON_ERROR_STOP=1 -tA -F $'\t' < "$script" >"$session_log" 2>&1; then
    echo "pg_dump_and_manifest_snapshot_consistent: la sesión de psql (snapshot compartido) falló. Detalle:" >&2
    cat "$session_log" >&2
    rm -f "$session_log"
    trap - EXIT INT TERM
    docker exec "$container" rm -f "$pgpass_path" "$in_dump" "$in_manifest" "$in_exitcode" >/dev/null 2>&1
    rm -f "$script"
    return 1
  fi
  rm -f "$session_log"
  local pgdump_exit
  pgdump_exit="$(docker exec "$container" cat "$in_exitcode" 2>/dev/null || echo "desconocido")"
  if [ "$pgdump_exit" != "0" ]; then
    echo "pg_dump_and_manifest_snapshot_consistent: pg_dump (dentro de la sesión con snapshot compartido) terminó con código $pgdump_exit." >&2
    trap - EXIT INT TERM
    docker exec "$container" rm -f "$pgpass_path" "$in_dump" "$in_manifest" "$in_exitcode" >/dev/null 2>&1
    rm -f "$script"
    return 1
  fi
  if ! docker cp "$container:$in_dump" "$dump_host_out" >/dev/null 2>&1; then
    echo "pg_dump_and_manifest_snapshot_consistent: no se pudo extraer el volcado del contenedor." >&2
    trap - EXIT INT TERM
    docker exec "$container" rm -f "$pgpass_path" "$in_dump" "$in_manifest" "$in_exitcode" >/dev/null 2>&1
    rm -f "$script"
    return 1
  fi
  # DEP62-06: el manifiesto puede ser legítimamente de 0 bytes (base sin tablas de usuario) --
  # "docker cp" de un archivo de 0 bytes funciona igual; nunca se exige tamaño no-cero aquí.
  if ! docker cp "$container:$in_manifest" "$manifest_host_out" >/dev/null 2>&1; then
    echo "pg_dump_and_manifest_snapshot_consistent: no se pudo extraer el manifiesto del contenedor." >&2
    trap - EXIT INT TERM
    docker exec "$container" rm -f "$pgpass_path" "$in_dump" "$in_manifest" "$in_exitcode" >/dev/null 2>&1
    rm -f "$script"
    return 1
  fi
  docker exec "$container" rm -f "$pgpass_path" "$in_dump" "$in_manifest" "$in_exitcode" >/dev/null 2>&1
  trap - EXIT INT TERM
  rm -f "$script"
  return 0
}

# --- Directorio privado de backups (CLOUD-DEP-02B.2-D.2) ---------------------------------------
#
# assert_private_dir <path>: exige que el directorio exista con permisos EXACTAMENTE 700 y
# propietario = quien invoca este proceso (mismo criterio dinámico que
# docker_env_contract_check, "id -un", nunca un nombre fijo). Nunca lo crea ni le cambia permisos
# si ya existe con algo distinto -- igual filosofía fail-closed que el resto de este archivo
# (reportar y detener, nunca "arreglar" silenciosamente algo que un operador pudo haber dejado
# así a propósito o por error). backup.sh sí crea el directorio con 700 la PRIMERA vez que no
# existe en absoluto (eso no es "corregir algo existente", es "establecerlo correctamente desde
# cero").
assert_private_dir() {
  local path="$1"
  if [ ! -e "$path" ]; then
    echo "FALLA: $path no existe. Crearlo (p. ej. 'mkdir -p $path && chmod 700 $path', como el operador que ejecutará los backups) antes de continuar." >&2
    exit 1
  fi
  if [ -L "$path" ]; then
    echo "FALLA: $path es un enlace simbólico. Debe ser un directorio regular." >&2
    exit 1
  fi
  if [ ! -d "$path" ]; then
    echo "FALLA: $path existe pero no es un directorio." >&2
    exit 1
  fi
  local owner perms expected_owner
  expected_owner="$(id -un)"
  owner="$(stat -c '%U' "$path" 2>/dev/null || true)"
  if [ "$owner" != "$expected_owner" ]; then
    echo "FALLA: $path pertenece a '$owner', debe pertenecer a '$expected_owner' (quien ejecuta este script)." >&2
    exit 1
  fi
  perms="$(stat -c '%a' "$path" 2>/dev/null || true)"
  if [ "$perms" != "700" ]; then
    echo "FALLA: $path tiene permisos ${perms:-desconocidos}, deben ser exactamente 700." >&2
    exit 1
  fi
}

# assert_enough_free_space <path> <min_MB>: rechaza continuar si el sistema de archivos que
# contiene <path> tiene menos de <min_MB> megabytes libres. "pg_dump" no permite conocer de
# antemano el tamaño exacto del volcado; este umbral es una red de seguridad mínima, configurable
# por el operador, no una garantía de espacio suficiente para cualquier volumen de datos.
assert_enough_free_space() {
  local path="$1" min_mb="$2"
  local avail_mb
  avail_mb="$(df -Pm "$path" 2>/dev/null | awk 'NR==2 {print $4}')"
  if [ -z "$avail_mb" ]; then
    echo "FALLA: no se pudo determinar el espacio libre en $path. No se continúa sin saberlo." >&2
    exit 1
  fi
  if [ "$avail_mb" -lt "$min_mb" ]; then
    echo "FALLA: solo quedan ${avail_mb}MB libres en el sistema de archivos de $path, se exigen al menos ${min_mb}MB. No se intenta el respaldo." >&2
    exit 1
  fi
}
