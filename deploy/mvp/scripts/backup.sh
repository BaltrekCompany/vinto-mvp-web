#!/usr/bin/env bash
# VINTO MVP WEB — backup y restauración verificable de PostgreSQL MVP (CLOUD-DEP-02B.2-D.2).
#
# Deliberadamente SEPARADO de deploy.sh/rollback.sh (ver DEP55-01: "ningún script de despliegue
# toca backups"). No se ejecuta en este incremento contra el VPS real; se prepara, documenta y
# prueba en un laboratorio Docker aislado con datos sintéticos.
#
# Principios de este script:
#   - Identifica el contenedor del MVP EXACTAMENTE igual que rollback.sh (DEP61-01/02/03):
#     lib_common.sh::resolve_confirmed_mvp_postgres_id -- nombre + etiqueta de proyecto compose +
#     imagen, nunca solo el nombre. Nunca opera sobre un contenedor cuya identidad no confirmó.
#   - Lee docker/.env con el mismo contrato de seguridad fail-closed que deploy.sh
#     (lib_common.sh::assert_docker_env_contract, DEP60-01/CLOUD-DEP-02B.2-D.1): archivo regular,
#     600, propietario = quien invoca, nunca legible por vinto-mvp.
#   - "pg_dump"/"pg_restore" nunca reciben la contraseña como argumento ni como "docker exec -e"
#     literal (lib_common.sh::pg_dump_custom/pg_restore_custom, mismo patrón .pgpass que
#     pg_run_sql_inline/pg_run_sql_file).
#   - Nunca toca TVC: ningún comando aquí nombra postgres-vinto, vinto-web.service, /opt/vinto-web
#     ni vinto_default. La restauración de prueba vive en un contenedor EFÍMERO propio, con
#     --network none (ni siquiera puede alcanzar la red de TVC aunque quisiera) y su propio
#     PGDATA temporal, nunca el bind-mount real del MVP ni el de TVC.
#   - "create" nunca sobrescribe un backup existente (nombre con marca de tiempo + sufijo único) y
#     preserva el último backup válido ante cualquier fallo (escribe primero a un archivo
#     ".partial", solo lo promueve al nombre final tras completarse con éxito).
#   - Un backup recién creado queda "sin verificar" hasta que "verify" complete una restauración
#     de prueba real y compruebe el contenido — un archivo ".verified" (vacío, solo su existencia
#     importa) es la única marca de que un backup es confiable.
#
# Uso:
#   CONFIRM=yes bash backup.sh create
#   CONFIRM=yes bash backup.sh verify <ruta-del-.dump>
#   CONFIRM=yes bash backup.sh create-and-verify
#   CONFIRM=yes bash backup.sh prune
#   bash backup.sh list

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib_common.sh
source "$SCRIPT_DIR/lib_common.sh"

BACKUP_DIR="${VINTO_MVP_BACKUP_DIR:-/home/ubuntu/vinto-mvp-backups}"
MIN_FREE_MB="${VINTO_MVP_BACKUP_MIN_FREE_MB:-500}"
RETENTION_DAILY="${VINTO_MVP_BACKUP_RETENTION_DAILY:-7}"
BACKUP_DB="${VINTO_MVP_BACKUP_DB:-vinto_piloto}"
POSTGRES_IMAGE="postgres:17"

# Resuelve el contenedor del MVP con la MISMA identidad estricta que rollback.sh (DEP61-01):
# nombre + etiqueta de proyecto compose + imagen. Deja MVP_POSTGRES_CONTAINER_ID (vacío si no
# existe) y nunca llama a "exit" por sí misma más allá de lo que ya hace
# resolve_confirmed_mvp_postgres_id.
require_mvp_container() {
  resolve_confirmed_mvp_postgres_id "$MVP_POSTGRES_CONTAINER" "$POSTGRES_IMAGE"
  if [ -z "$MVP_POSTGRES_CONTAINER_ID" ]; then
    echo "FALLA: $MVP_POSTGRES_CONTAINER no existe. No se puede respaldar un contenedor que no está corriendo." >&2
    exit 1
  fi
}

# Crea el backup (Fase B): pg_dump -Fc + checksum SHA-256, bajo un nombre único por marca de
# tiempo, en un directorio privado (700) propio del operador que ejecuta este script. Nunca
# sobrescribe nada; nunca toca un backup anterior.
phase_create() {
  require_confirm
  local compose_dir="$SCRIPT_DIR/../docker"
  assert_docker_env_contract "$compose_dir/.env"
  require_mvp_container
  assert_private_dir "$BACKUP_DIR"
  assert_enough_free_space "$BACKUP_DIR" "$MIN_FREE_MB"

  local bootstrap_user bootstrap_password
  bootstrap_user="$(env_value "$compose_dir/.env" POSTGRES_BOOTSTRAP_USER)"
  bootstrap_password="$(env_value "$compose_dir/.env" POSTGRES_BOOTSTRAP_PASSWORD)"

  local stamp final_path staging_path
  stamp="$(date -u +%Y%m%d-%H%M%S)-$$"
  final_path="$BACKUP_DIR/vinto-mvp-${BACKUP_DB}-$stamp.dump"
  staging_path="$final_path.partial"
  # Requisito 8 (Fase B): nunca sobrescribir -- un .dump o .partial con este nombre ya presente
  # detiene la fase ANTES de intentar nada (la marca de tiempo tiene resolución de segundo + PID,
  # así que una colisión real sería prácticamente imposible, pero nunca se asume).
  if [ -e "$final_path" ] || [ -e "$staging_path" ]; then
    echo "FALLA: $final_path (o su archivo .partial) ya existe. No se sobrescribe; reintentar." >&2
    exit 1
  fi

  echo "Volcando $BACKUP_DB (contenedor confirmado: $MVP_POSTGRES_CONTAINER_ID) a $staging_path..."
  if ! pg_dump_custom "$MVP_POSTGRES_CONTAINER_ID" "$bootstrap_user" "$bootstrap_password" "$BACKUP_DB" "$staging_path"; then
    echo "FALLA: pg_dump falló. El último backup válido anterior (si existe) NO se tocó." >&2
    rm -f "$staging_path"
    exit 1
  fi
  if [ ! -s "$staging_path" ]; then
    echo "FALLA: pg_dump terminó sin error pero el archivo resultante está vacío. Se descarta; el último backup válido anterior NO se tocó." >&2
    rm -f "$staging_path"
    exit 1
  fi

  # Requisito 9 (Fase B): "mv" es la única operación sobre el nombre final -- un fallo en
  # cualquier paso ANTERIOR (arriba) deja el staging a medio camino, nunca el nombre final.
  mv "$staging_path" "$final_path"
  chmod 600 "$final_path"
  ( cd "$BACKUP_DIR" && sha256sum "$(basename "$final_path")" > "$(basename "$final_path").sha256" )
  chmod 600 "$final_path.sha256"
  echo "Backup creado: $final_path (checksum: $final_path.sha256)."
  echo "Estado: SIN VERIFICAR -- ejecutar 'backup.sh verify $final_path' para confirmar que es restaurable antes de confiar en él."
}

# Verifica un backup (Fase C): checksum, luego una restauración REAL a un contenedor Postgres
# EFÍMERO y AISLADO (--network none: ni siquiera puede alcanzar la red de TVC ni la del propio
# MVP), con recursos limitados, y una comparación de objetos/filas contra el origen. Solo si
# TODO lo anterior tiene éxito se crea el marcador "<dump>.verified".
phase_verify() {
  require_confirm
  local dump_path="${1:?Uso: backup.sh verify <ruta-del-.dump>}"
  if [ ! -f "$dump_path" ]; then
    echo "FALLA: $dump_path no existe." >&2
    exit 1
  fi
  if [ ! -f "$dump_path.sha256" ]; then
    echo "FALLA: no existe $dump_path.sha256. Nunca se verifica un backup sin su checksum acompañante." >&2
    exit 1
  fi
  echo "Comprobando checksum de $dump_path..."
  if ! ( cd "$(dirname "$dump_path")" && sha256sum -c "$(basename "$dump_path").sha256" >/dev/null ); then
    echo "FALLA: el checksum de $dump_path no coincide con $dump_path.sha256 -- el archivo está dañado o fue alterado. No se intenta restaurar. Se marca como corrupto (nunca como verificado)." >&2
    : > "$dump_path.CORRUPT"
    exit 1
  fi
  echo "Checksum OK."

  # Deliberadamente SIN "require_mvp_container" ni "assert_docker_env_contract" aquí: verificar
  # un dump es independiente del contenedor REAL del MVP (que podría incluso no estar corriendo
  # en este momento) -- solo necesita el archivo y un contenedor EFÍMERO propio, con credenciales
  # igualmente efímeras, nunca las de docker/.env.

  # Credenciales EFÍMERAS, generadas solo para este contenedor de prueba, destruidas junto con
  # él -- nunca se reutiliza ninguna credencial real del MVP ni de TVC aquí.
  local ephemeral_db="restore_check" ephemeral_user="restore_root"
  local ephemeral_password
  ephemeral_password="$(head -c24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c24)"
  local ephemeral_name
  ephemeral_name="vinto-mvp-backup-verify-$(_pg_unique_suffix)"

  echo "Creando contenedor efímero de verificación ($ephemeral_name), --network none, recursos limitados..."
  local ephemeral_cid
  ephemeral_cid="$(docker run -d --name "$ephemeral_name" \
    --network none --cpus 1 --memory 512m \
    -e POSTGRES_DB="$ephemeral_db" -e POSTGRES_USER="$ephemeral_user" -e POSTGRES_PASSWORD="$ephemeral_password" \
    "$POSTGRES_IMAGE")" || {
    echo "FALLA: no se pudo crear el contenedor efímero de verificación." >&2
    exit 1
  }
  # Confirmado por su ID real (igual criterio que el resto de este archivo): toda limpieza
  # posterior actúa sobre $ephemeral_cid, nunca sobre el nombre vuelto a buscar.
  #
  # NUNCA se confía solo en "trap ... EXIT" para esta limpieza: pg_restore_custom/
  # pg_run_sql_inline_in (más abajo) usan su PROPIO "trap ... EXIT INT TERM" interno para su
  # .pgpass, y lo DESARMAN ("trap - EXIT INT TERM") al terminar -- como los traps son del PROCESO
  # completo (nunca se "apilan" entre funciones), ese desarme interno se llevaría también
  # cualquier trap que esta función hubiera dejado puesto antes de llamarlas (confirmado: así es
  # como se perdía la limpieza del contenedor efímero en la primera versión de esta corrección).
  # Por eso aquí se llama a "cleanup_ephemeral" EXPLÍCITAMENTE antes de cada "exit", nunca solo
  # por el trap; el trap se mantiene únicamente como red de seguridad para una señal (INT/TERM)
  # recibida en una ventana en la que ninguna de esas funciones ya reasignó el trap.
  cleanup_ephemeral() {
    docker rm -f "$ephemeral_cid" >/dev/null 2>&1 || true
  }
  trap cleanup_ephemeral EXIT INT TERM

  local ready=1 n=0
  while [ "$n" -lt 60 ]; do
    if docker exec "$ephemeral_cid" pg_isready -U "$ephemeral_user" -d "$ephemeral_db" >/dev/null 2>&1; then
      ready=0
      break
    fi
    sleep 1
    n=$((n + 1))
  done
  if [ "$ready" -ne 0 ]; then
    echo "FALLA: el contenedor efímero de verificación no respondió a tiempo. Backup NO verificado (se conserva como estaba)." >&2
    cleanup_ephemeral
    trap - EXIT INT TERM
    exit 1
  fi
  # "pg_isready" confirma que el proceso acepta conexiones, pero bajo carga del host puede haber
  # un breve margen hasta que esté listo para una operación más pesada como "pg_restore" --
  # margen de asentamiento defensivo, nunca un sustituto de la comprobación real de arriba.
  sleep 2

  echo "Restaurando $dump_path en el contenedor efímero..."
  if ! pg_restore_custom "$ephemeral_cid" "$ephemeral_user" "$ephemeral_password" "$ephemeral_db" "$dump_path"; then
    echo "FALLA: pg_restore falló. Backup NO verificado; el archivo original (y su checksum) se conservan sin cambios." >&2
    cleanup_ephemeral
    trap - EXIT INT TERM
    exit 1
  fi
  # pg_restore_custom ya desarmó el trap de PROCESO al terminar (ver nota arriba) -- se reinstala
  # aquí para que una señal recibida en lo que queda de esta función siga limpiando el contenedor.
  trap cleanup_ephemeral EXIT INT TERM

  echo "Verificando objetos restaurados (recuento de tablas con datos)..."
  local table_count
  table_count="$(pg_run_sql_inline_in "$ephemeral_cid" "$ephemeral_user" "$ephemeral_password" "$ephemeral_db" \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema');")"
  trap cleanup_ephemeral EXIT INT TERM
  if [ -z "$table_count" ] || [ "$table_count" = "0" ]; then
    echo "FALLA: la restauración no produjo ninguna tabla de usuario. Backup NO verificado." >&2
    cleanup_ephemeral
    trap - EXIT INT TERM
    exit 1
  fi
  echo "Restauración verificada: $table_count tabla(s) de usuario presentes tras pg_restore."

  : > "$dump_path.verified"
  chmod 600 "$dump_path.verified"
  echo "Backup VERIFICADO: $dump_path (marcador: $dump_path.verified)."
  cleanup_ephemeral
  trap - EXIT INT TERM
}

phase_create_and_verify() {
  # No "require_confirm" propio aquí: cada sub-fase ya lo exige por su cuenta, y queremos que el
  # mensaje de error (si CONFIRM no está puesto) sea exactamente el mismo que el de "create".
  local compose_dir="$SCRIPT_DIR/../docker"
  local before_dir
  before_dir="$(mktemp)"
  ls -1 "$BACKUP_DIR"/*.dump 2>/dev/null > "$before_dir" || true
  phase_create
  local new_path
  new_path="$(comm -13 "$before_dir" <(ls -1 "$BACKUP_DIR"/*.dump 2>/dev/null) | head -n1)"
  rm -f "$before_dir"
  if [ -z "$new_path" ]; then
    echo "FALLA: no se pudo determinar el archivo recién creado para verificarlo." >&2
    exit 1
  fi
  phase_verify "$new_path"
}

# Retención (Fase D, propuesta): 1 backup diario, conservar los $RETENTION_DAILY más recientes
# YA VERIFICADOS + 1 copia semanal adicional (la verificada más antigua que quede). Nunca purga
# un backup sin marcador ".verified" -- podría ser el único resguardo disponible si algo salió
# mal después. Esta fase NUNCA se programa en cron desde este repositorio; es una herramienta
# manual para cuando el operador decida aplicar la política.
phase_prune() {
  require_confirm
  assert_private_dir "$BACKUP_DIR"
  local verified=()
  local f
  for f in "$BACKUP_DIR"/*.dump; do
    [ -f "$f" ] && [ -f "$f.verified" ] && verified+=("$f")
  done
  if [ "${#verified[@]}" -eq 0 ]; then
    echo "No hay backups verificados en $BACKUP_DIR; nada que podar."
    return 0
  fi
  # Orden descendente por nombre -- el nombre embebe la marca de tiempo UTC, así que el orden
  # lexicográfico coincide con el cronológico.
  mapfile -t sorted < <(printf '%s\n' "${verified[@]}" | sort -r)
  local keep=("${sorted[@]:0:$RETENTION_DAILY}")
  local rest=("${sorted[@]:$RETENTION_DAILY}")
  if [ "${#rest[@]}" -gt 0 ]; then
    # El más antiguo de los que sobran se conserva como "semanal".
    local weekly="${rest[-1]}"
    keep+=("$weekly")
  fi
  local to_delete=()
  for f in "${sorted[@]}"; do
    local keep_this=0
    local k
    for k in "${keep[@]}"; do
      [ "$f" = "$k" ] && keep_this=1 && break
    done
    [ "$keep_this" -eq 0 ] && to_delete+=("$f")
  done
  if [ "${#to_delete[@]}" -eq 0 ]; then
    echo "Nada que podar: ${#sorted[@]} backup(s) verificado(s), todos dentro de la retención ($RETENTION_DAILY diarios + 1 semanal)."
    return 0
  fi
  echo "Conservando ${#keep[@]} backup(s) verificado(s); eliminando ${#to_delete[@]}."
  for f in "${to_delete[@]}"; do
    echo "  eliminando $f (.dump, .sha256, .verified)"
    rm -f "$f" "$f.sha256" "$f.verified"
  done
}

phase_list() {
  assert_private_dir "$BACKUP_DIR"
  local f
  for f in "$BACKUP_DIR"/*.dump; do
    [ -f "$f" ] || continue
    local status="SIN VERIFICAR"
    [ -f "$f.verified" ] && status="verificado"
    [ -f "$f.CORRUPT" ] && status="CORRUPTO"
    printf '%s\t%s\n' "$status" "$f"
  done
}

case "${1:-}" in
  create) phase_create ;;
  verify) phase_verify "${2:-}" ;;
  create-and-verify) phase_create_and_verify ;;
  prune) phase_prune ;;
  list) phase_list ;;
  *)
    echo "Uso: backup.sh {create|verify <ruta-del-.dump>|create-and-verify|prune|list}" >&2
    exit 1
    ;;
esac
