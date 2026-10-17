#!/usr/bin/env bash
# VINTO MVP WEB — backup y restauración verificable de PostgreSQL MVP (CLOUD-DEP-02B.2-D.2,
# corregido tras la auditoría del PR #62, DEP62-01 a 05).
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
#     preserva el último backup válido ante cualquier fallo (escribe primero a archivos
#     ".partial", solo los promueve al nombre final, TODOS JUNTOS, tras completarse con éxito).
#   - Un backup recién creado queda "sin verificar" hasta que "verify" complete una restauración
#     de prueba real y compare el contenido restaurado contra un MANIFIESTO (DEP62-01) capturado
#     en el momento de "create" -- un archivo ".verified" (con metadatos de auditoría, escrito de
#     forma atómica) es la única marca de que un backup es confiable. Una (re)verificación que
#     falla INVALIDA cualquier marca ".verified" anterior (DEP62-02): nunca queda un marcador
#     desactualizado afirmando algo que ya no es cierto.
#   - "prune" (DEP62-05) distingue explícitamente "últimos N archivos verificados" de "N DÍAS
#     calendario con backup verificado" -- implementa la segunda (la política real documentada),
#     nunca borra sin mostrar antes los candidatos ("prune" es un dry-run; "prune-apply" aplica).
#
# Uso:
#   CONFIRM=yes bash backup.sh create
#   CONFIRM=yes bash backup.sh verify <ruta-del-.dump>
#   CONFIRM=yes bash backup.sh create-and-verify
#   bash backup.sh prune          # dry-run: solo muestra candidatos, no borra nada
#   CONFIRM=yes bash backup.sh prune-apply
#   bash backup.sh list

set -euo pipefail

# DEP62-03: umask ANTES de crear ningún archivo -- todo lo que este script cree (.partial, .dump,
# .sha256, .manifest, .verified, cualquier archivo de control) nace con 600 desde el PRIMER
# syscall de creación, nunca con un permiso más amplio ni por un instante. Los "chmod 600"
# explícitos que siguen abajo son defensa en profundidad (p. ej. por si algo se ejecutara alguna
# vez bajo un umask distinto heredado del entorno), nunca el único mecanismo.
umask 077

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

# --- Estado de confianza, UN SOLO lugar que lo decide (DEP62-02, punto 2: coherencia entre
# list/verify/prune) ------------------------------------------------------------------------

# backup_state <ruta-del-.dump> -- imprime "verified", "corrupt", "inconsistent" (ambos
# marcadores presentes a la vez; nunca debería ocurrir por construcción, pero se reporta en vez
# de asumir uno de los dos en silencio) o "unverified".
backup_state() {
  local f="$1"
  local has_verified=0 has_corrupt=0
  [ -f "$f.verified" ] && has_verified=1
  [ -f "$f.CORRUPT" ] && has_corrupt=1
  if [ "$has_verified" -eq 1 ] && [ "$has_corrupt" -eq 1 ]; then
    echo "inconsistent"
  elif [ "$has_corrupt" -eq 1 ]; then
    echo "corrupt"
  elif [ "$has_verified" -eq 1 ]; then
    echo "verified"
  else
    echo "unverified"
  fi
}

# --- Manifiesto de contenido (DEP62-01) ------------------------------------------------------
#
# Capturado en "create", a partir de la fuente VIVA, en el mismo momento que "pg_dump" (nunca
# más tarde, y "verify" NUNCA vuelve a consultar la fuente viva -- compara siempre contra este
# manifiesto ya congelado, para no depender de una base productiva que puede haber cambiado para
# cuando alguien ejecute "verify", posiblemente mucho después de "create").
#
# Formato: una línea "esquema.tabla<TAB>filas" por tabla de usuario (ninguna línea para una base
# legítimamente vacía -- 0 tablas es un manifiesto válido, no un error).
#
# Nota de arquitectura (evaluada, no implementada en este incremento): la forma PERFECTAMENTE
# consistente de capturar esto sería compartir el snapshot MVCC exacto de "pg_dump" vía
# "pg_export_snapshot()" + "pg_dump --snapshot=<id>" + "SET TRANSACTION SNAPSHOT '<id>'" en la
# conexión que cuenta filas, manteniendo una transacción separada abierta mientras dura todo el
# volcado. Se evaluó y se decidió NO implementarlo en este incremento: exige orquestar una sesión
# "psql" de larga duración con escritura/lectura intercalada a través de "docker exec" (un
# coproceso), con sincronización explícita por cada instrucción -- una pieza de infraestructura
# nueva y de fragilidad no trivial de probar de forma fiable, para un piloto de bajo volumen de
# escritura donde la ventana real entre "capturar el manifiesto" e "iniciar pg_dump" es del orden
# de milisegundos. Mecanismo equivalente adoptado: capturar el manifiesto INMEDIATAMENTE ANTES de
# invocar "pg_dump", en la misma llamada a "create", nunca comparado contra la fuente de nuevo
# después. Riesgo residual documentado en el README.

# _manifest_capture <container> <role> <password> <db> <ruta_salida>
_manifest_capture() {
  local container="$1" role="$2" password="$3" db="$4" output_path="$5"
  local qualified_list
  if ! qualified_list="$(pg_run_sql_inline_in "$container" "$role" "$password" "$db" \
      "SELECT quote_ident(table_schema) || '.' || quote_ident(table_name) FROM information_schema.tables WHERE table_schema NOT IN ('pg_catalog','information_schema') ORDER BY 1;")"; then
    echo "_manifest_capture: no se pudo enumerar las tablas de origen." >&2
    return 1
  fi
  : > "$output_path"
  local qualified cnt
  while IFS= read -r qualified; do
    [ -z "$qualified" ] && continue
    if ! cnt="$(pg_run_sql_inline_in "$container" "$role" "$password" "$db" "SELECT count(*) FROM $qualified;")"; then
      echo "_manifest_capture: no se pudo contar filas de $qualified en el origen." >&2
      return 1
    fi
    printf '%s\t%s\n' "$qualified" "$cnt" >> "$output_path"
  done <<< "$qualified_list"
  return 0
}

# _manifest_verify <container> <role> <password> <db> <ruta_manifiesto> -- compara el contenido
# YA RESTAURADO contra el manifiesto congelado, tabla por tabla, EXACTO (nunca "al menos una
# tabla"). Una tabla legítimamente vacía (0 filas en el manifiesto) se compara igual que
# cualquier otra -- 0 == 0 pasa. Una tabla del manifiesto AUSENTE tras la restauración (consulta
# que falla por "relation does not exist") se trata como fallo explícito, distinto de un simple
# desajuste de conteo. Nunca marca nada por su cuenta -- solo informa (imprime en stdout un
# resumen) y retorna 0/1; "phase_verify" decide qué hacer con el resultado.
_manifest_verify() {
  local container="$1" role="$2" password="$3" db="$4" manifest_path="$5"
  local qualified expected actual
  local mismatch=0 checked=0
  while IFS=$'\t' read -r qualified expected; do
    [ -z "$qualified" ] && continue
    checked=$((checked + 1))
    if ! actual="$(pg_run_sql_inline_in "$container" "$role" "$password" "$db" "SELECT count(*) FROM $qualified;" 2>&1)"; then
      echo "FALLA: $qualified del manifiesto no se pudo consultar tras restaurar (¿tabla ausente?): $actual" >&2
      mismatch=1
      continue
    fi
    if [ "$actual" != "$expected" ]; then
      echo "FALLA: $qualified tiene $actual fila(s) tras restaurar, el manifiesto esperaba $expected." >&2
      mismatch=1
    fi
  done < "$manifest_path"
  echo "Manifiesto comparado: $checked tabla(s) revisada(s)."
  return "$mismatch"
}

# Crea el backup (Fase B): manifiesto + pg_dump -Fc + checksums, bajo un nombre único por marca
# de tiempo, en un directorio privado (700) propio del operador que ejecuta este script. Nunca
# sobrescribe nada; nunca toca un backup anterior. Todo se escribe primero con sufijo ".partial"
# y se promueve al nombre final SOLO si TODO (manifiesto + dump + ambos checksums) se completó
# con éxito -- atomicidad de "todo o nada" (DEP62-02, punto 4, aplicada también aquí).
LAST_CREATED_DUMP_PATH=""
phase_create() {
  LAST_CREATED_DUMP_PATH=""
  require_confirm
  local compose_dir="$SCRIPT_DIR/../docker"
  assert_docker_env_contract "$compose_dir/.env"
  require_mvp_container
  assert_private_dir "$BACKUP_DIR"
  assert_enough_free_space "$BACKUP_DIR" "$MIN_FREE_MB"

  local bootstrap_user bootstrap_password
  bootstrap_user="$(env_value "$compose_dir/.env" POSTGRES_BOOTSTRAP_USER)"
  bootstrap_password="$(env_value "$compose_dir/.env" POSTGRES_BOOTSTRAP_PASSWORD)"

  local stamp final_path staging_path final_manifest staging_manifest
  stamp="$(date -u +%Y%m%d-%H%M%S)-$$"
  final_path="$BACKUP_DIR/vinto-mvp-${BACKUP_DB}-$stamp.dump"
  staging_path="$final_path.partial"
  final_manifest="$final_path.manifest"
  staging_manifest="$staging_path.manifest"
  # Requisito 8 (Fase B): nunca sobrescribir -- cualquier archivo final o de staging con este
  # nombre ya presente detiene la fase ANTES de intentar nada (la marca de tiempo tiene
  # resolución de segundo + PID, así que una colisión real sería prácticamente imposible, pero
  # nunca se asume).
  if [ -e "$final_path" ] || [ -e "$staging_path" ] || [ -e "$final_manifest" ] || [ -e "$staging_manifest" ]; then
    echo "FALLA: $final_path (o alguno de sus archivos .partial/.manifest) ya existe. No se sobrescribe; reintentar." >&2
    exit 1
  fi

  echo "Capturando manifiesto de contenido (DEP62-01) de $BACKUP_DB antes de volcar..."
  if ! _manifest_capture "$MVP_POSTGRES_CONTAINER_ID" "$bootstrap_user" "$bootstrap_password" "$BACKUP_DB" "$staging_manifest"; then
    echo "FALLA: no se pudo capturar el manifiesto de contenido. El último backup válido anterior (si existe) NO se tocó." >&2
    rm -f "$staging_manifest"
    exit 1
  fi

  echo "Volcando $BACKUP_DB (contenedor confirmado: $MVP_POSTGRES_CONTAINER_ID) a $staging_path..."
  if ! pg_dump_custom "$MVP_POSTGRES_CONTAINER_ID" "$bootstrap_user" "$bootstrap_password" "$BACKUP_DB" "$staging_path"; then
    echo "FALLA: pg_dump falló. El último backup válido anterior (si existe) NO se tocó." >&2
    rm -f "$staging_path" "$staging_manifest"
    exit 1
  fi
  if [ ! -s "$staging_path" ]; then
    echo "FALLA: pg_dump terminó sin error pero el archivo resultante está vacío. Se descarta; el último backup válido anterior NO se tocó." >&2
    rm -f "$staging_path" "$staging_manifest"
    exit 1
  fi

  # Promoción del dump y el manifiesto PRIMERO (nunca sus checksums todavía): un checksum
  # calculado sobre el nombre ".partial" referenciaría ese nombre dentro de su propio contenido
  # (formato "<hash>  <nombre-archivo>" de sha256sum) -- renombrar el .dump DESPUÉS dejaría ese
  # checksum apuntando a un nombre que ya no existe (confirmado: "sha256sum -c" fallaba con "No
  # such file or directory" en la primera versión de esta corrección). Calculando el checksum
  # DESPUÉS de renombrar, sobre el nombre final, se evita el problema de raíz. La ventana entre
  # el "mv" y la escritura del checksum es del orden de milisegundos (un solo proceso, sin
  # concurrencia); mientras tanto, "verify" exige AMBOS archivos (dump y checksum) para
  # continuar, así que nunca puede confundir un dump recién movido pero aún sin checksum con uno
  # verificable.
  if [ ! -s "$staging_path" ] || [ ! -s "$staging_manifest" ]; then
    echo "FALLA: el volcado o el manifiesto quedaron vacíos antes de promoverlos. El último backup válido anterior NO se tocó." >&2
    rm -f "$staging_path" "$staging_manifest"
    exit 1
  fi
  mv "$staging_path" "$final_path"
  mv "$staging_manifest" "$final_manifest"
  if ! ( cd "$BACKUP_DIR" && sha256sum "$(basename "$final_path")" > "$(basename "$final_path").sha256" ); then
    echo "FALLA: no se pudo calcular el checksum del volcado ya promovido ($final_path). Revisar a mano -- el dump existe pero sin checksum todavía; 'verify' lo rechazará hasta que se regenere." >&2
    exit 1
  fi
  if ! ( cd "$BACKUP_DIR" && sha256sum "$(basename "$final_manifest")" > "$(basename "$final_manifest").sha256" ); then
    echo "FALLA: no se pudo calcular el checksum del manifiesto ya promovido ($final_manifest). Revisar a mano -- 'verify' lo rechazará hasta que se regenere." >&2
    exit 1
  fi
  chmod 600 "$final_path" "$final_path.sha256" "$final_manifest" "$final_manifest.sha256"
  LAST_CREATED_DUMP_PATH="$final_path"
  echo "Backup creado: $final_path (checksum: $final_path.sha256; manifiesto: $final_manifest)."
  echo "Estado: SIN VERIFICAR -- ejecutar 'backup.sh verify $final_path' para confirmar que es restaurable antes de confiar en él."
}

# Verifica un backup (Fase C): checksums (dump + manifiesto), luego una restauración REAL a un
# contenedor Postgres EFÍMERO y AISLADO (--network none: ni siquiera puede alcanzar la red de
# TVC ni la del propio MVP), con recursos limitados, y una comparación EXACTA de contenido
# (DEP62-01) contra el manifiesto congelado -- nunca contra la fuente viva. Solo si TODO lo
# anterior tiene éxito se crea el marcador "<dump>.verified", de forma atómica (DEP62-02).
# Cualquier fallo INVALIDA un ".verified" anterior (nunca queda un marcador desactualizado).
phase_verify() {
  require_confirm
  local dump_path="${1:?Uso: backup.sh verify <ruta-del-.dump>}"
  local manifest_path="$dump_path.manifest"

  # DEP62-02, punto 1/3: esta (re)verificación decide el estado desde cero -- cualquier fallo de
  # aquí en adelante invalida explícitamente un ".verified" que pudiera existir de una ejecución
  # anterior. Nunca se asume que un marcador viejo sigue siendo cierto.
  invalidate_verified() { rm -f "$dump_path.verified"; }

  if [ ! -f "$dump_path" ]; then
    echo "FALLA: $dump_path no existe." >&2
    exit 1
  fi
  if [ ! -f "$dump_path.sha256" ] || [ ! -f "$manifest_path" ] || [ ! -f "$manifest_path.sha256" ]; then
    echo "FALLA: faltan uno o más archivos de control ($dump_path.sha256 / $manifest_path / $manifest_path.sha256). Nunca se verifica un backup sin todos sus acompañantes." >&2
    invalidate_verified
    exit 1
  fi

  echo "Comprobando checksums de $dump_path y su manifiesto..."
  if ! ( cd "$(dirname "$dump_path")" && sha256sum -c "$(basename "$dump_path").sha256" >/dev/null ); then
    echo "FALLA: el checksum de $dump_path no coincide -- el archivo está dañado o fue alterado. No se intenta restaurar. Se marca como corrupto (nunca como verificado)." >&2
    : > "$dump_path.CORRUPT"
    invalidate_verified
    exit 1
  fi
  if ! ( cd "$(dirname "$manifest_path")" && sha256sum -c "$(basename "$manifest_path").sha256" >/dev/null ); then
    echo "FALLA: el checksum del manifiesto de $dump_path no coincide -- el manifiesto fue alterado o está dañado. No se intenta restaurar. Se marca como corrupto (nunca como verificado)." >&2
    : > "$dump_path.CORRUPT"
    invalidate_verified
    exit 1
  fi
  echo "Checksums OK."
  # Un checksum válido en ESTA ejecución invalida cualquier marca ".CORRUPT" de una ejecución
  # anterior (el archivo ya no está dañado) -- los dos estados son mutuamente excluyentes.
  rm -f "$dump_path.CORRUPT"

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
  if ! ephemeral_cid="$(docker run -d --name "$ephemeral_name" \
      --network none --cpus 1 --memory 512m \
      -e POSTGRES_DB="$ephemeral_db" -e POSTGRES_USER="$ephemeral_user" -e POSTGRES_PASSWORD="$ephemeral_password" \
      "$POSTGRES_IMAGE")"; then
    echo "FALLA: no se pudo crear el contenedor efímero de verificación." >&2
    invalidate_verified
    exit 1
  fi
  # Confirmado por su ID real (igual criterio que el resto de este archivo): toda limpieza
  # posterior actúa sobre $ephemeral_cid, nunca sobre el nombre vuelto a buscar.
  #
  # DEP62-04: NUNCA se confía solo en reinstalar "trap ... EXIT" tras cada llamada a
  # pg_restore_custom/pg_run_sql_inline_in -- esas funciones desarman ("trap - EXIT INT TERM") el
  # trap del PROCESO al terminar, y como los traps nunca se "apilan" entre funciones, un simple
  # "volver a poner el trap después" deja una VENTANA real sin protección si algo falla ANTES de
  # llegar a esa línea de reinstalación. La solución estructural: toda llamada a esas funciones
  # mientras este trap esté activo se envuelve en un SUBSHELL "( ... )" -- el "trap"/"trap -" que
  # hagan DENTRO del subshell nunca toca la tabla de traps del proceso PADRE, así que el trap de
  # "cleanup_ephemeral" de aquí permanece intacto sin importar qué hagan por dentro.
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
    invalidate_verified
    cleanup_ephemeral
    trap - EXIT INT TERM
    exit 1
  fi
  # "pg_isready" confirma que el proceso acepta conexiones, pero bajo carga del host puede haber
  # un breve margen hasta que esté listo para una operación más pesada como "pg_restore" --
  # margen de asentamiento defensivo, nunca un sustituto de la comprobación real de arriba.
  sleep 2

  echo "Restaurando $dump_path en el contenedor efímero..."
  if ! ( pg_restore_custom "$ephemeral_cid" "$ephemeral_user" "$ephemeral_password" "$ephemeral_db" "$dump_path" ); then
    echo "FALLA: pg_restore falló. Backup NO verificado; el archivo original (y su checksum) se conservan sin cambios." >&2
    invalidate_verified
    cleanup_ephemeral
    trap - EXIT INT TERM
    exit 1
  fi
  # El trap de este proceso NUNCA se tocó (la llamada de arriba corrió en un subshell) -- sigue
  # intacto sin necesidad de reinstalarlo.

  echo "Comparando contenido restaurado contra el manifiesto congelado (DEP62-01)..."
  if ! ( _manifest_verify "$ephemeral_cid" "$ephemeral_user" "$ephemeral_password" "$ephemeral_db" "$manifest_path" ); then
    echo "FALLA: el contenido restaurado no coincide con el manifiesto. Backup NO verificado." >&2
    invalidate_verified
    cleanup_ephemeral
    trap - EXIT INT TERM
    exit 1
  fi

  # Marcador ATÓMICO (DEP62-02, punto 4): se escribe primero bajo un nombre de staging propio y
  # se renombra al nombre final -- nunca una escritura directa sobre el nombre que "list"/"prune"
  # ya podrían estar observando. Lleva metadatos de auditoría (nunca solo un archivo vacío),
  # aunque lo único que "list"/"prune" comprueban es su EXISTENCIA.
  local verified_staging
  verified_staging="$dump_path.verified.partial-$$"
  {
    printf 'verified_at=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'manifest=%s\n' "$(basename "$manifest_path")"
  } > "$verified_staging"
  chmod 600 "$verified_staging"
  mv "$verified_staging" "$dump_path.verified"
  echo "Backup VERIFICADO: $dump_path (marcador: $dump_path.verified, contenido comparado exactamente contra el manifiesto)."
  cleanup_ephemeral
  trap - EXIT INT TERM
}

phase_create_and_verify() {
  # No "require_confirm" propio aquí: cada sub-fase ya lo exige por su cuenta, y queremos que el
  # mensaje de error (si CONFIRM no está puesto) sea exactamente el mismo que el de "create".
  phase_create
  if [ -z "$LAST_CREATED_DUMP_PATH" ]; then
    echo "FALLA: 'create' no reportó la ruta del backup recién creado; no se puede verificar." >&2
    exit 1
  fi
  phase_verify "$LAST_CREATED_DUMP_PATH"
}

# --- Retención (Fase D / DEP62-05) -----------------------------------------------------------
#
# Distinción explícita (lo que ChatGPT pidió revisar): "últimos N respaldos VERIFICADOS" (basado
# en CONTAR ARCHIVOS) no es lo mismo que "N DÍAS calendario con respaldo verificado" (basado en
# FECHAS). La política documentada y la única que implementa este script es la segunda: se
# agrupa por fecha UTC (incrustada en el nombre del archivo), se conservan TODOS los backups
# verificados de los $RETENTION_DAILY días calendario más recientes que tengan al menos uno
# (nunca se colapsan los duplicados del mismo día: es más seguro conservarlos que arriesgar que
# desplacen la cobertura de otro día dentro del mismo presupuesto), más UNA copia "semanal" (el
# backup verificado más antiguo que quede fuera de esos días). El backup verificado MÁS RECIENTE
# en términos absolutos SIEMPRE se conserva, sin excepción, incluso en casos límite
# ($RETENTION_DAILY=0, un solo backup, etc.).
#
# "prune" (sin argumentos) es un DRY-RUN: calcula y muestra los candidatos a eliminar, nunca
# borra nada. "prune-apply" aplica la poda, revalidando el estado de cada candidato EN ESE
# INSTANTE (nunca confiando en un cálculo anterior) y exigiendo CONFIRM=yes explícito. Ninguno de
# los dos se programa en cron desde este repositorio.

# _prune_plan: deja el resultado en los arrays globales PRUNE_KEEP/PRUNE_DELETE. Nunca borra
# nada por sí misma.
PRUNE_KEEP=()
PRUNE_DELETE=()
_prune_plan() {
  PRUNE_KEEP=()
  PRUNE_DELETE=()
  local f state
  local verified_files=()
  for f in "$BACKUP_DIR"/*.dump; do
    [ -f "$f" ] || continue
    state="$(backup_state "$f")"
    [ "$state" = "verified" ] && verified_files+=("$f")
  done
  if [ "${#verified_files[@]}" -eq 0 ]; then
    return 0
  fi
  # Orden descendente por nombre -- el nombre embebe la marca de tiempo UTC, así que el orden
  # lexicográfico coincide con el cronológico.
  local sorted=()
  mapfile -t sorted < <(printf '%s\n' "${verified_files[@]}" | sort -r)

  local newest="${sorted[0]}"
  local days_seen_keys="" kept_days_count=0
  local date_part
  for f in "${sorted[@]}"; do
    date_part="$(basename "$f" | grep -oE '[0-9]{8}-[0-9]{6}' | head -n1 | cut -d- -f1)"
    case " $days_seen_keys " in
      *" $date_part "*) : ;;
      *)
        days_seen_keys="$days_seen_keys $date_part"
        kept_days_count=$((kept_days_count + 1))
        ;;
    esac
    if [ "$kept_days_count" -le "$RETENTION_DAILY" ]; then
      PRUNE_KEEP+=("$f")
    fi
  done

  # La copia "semanal": el más antiguo de los que NO quedaron ya conservados arriba.
  local f_oldest="${sorted[-1]}"
  local already_kept=0 k
  for k in "${PRUNE_KEEP[@]}"; do
    [ "$k" = "$f_oldest" ] && already_kept=1 && break
  done
  [ "$already_kept" -eq 0 ] && PRUNE_KEEP+=("$f_oldest")

  # Salvaguarda explícita (requisito: "preservar el último respaldo confiable"): el más reciente
  # SIEMPRE se conserva, sin importar lo que diga el cálculo de arriba (nunca debería hacer falta
  # con RETENTION_DAILY>=1, pero cubre explícitamente $RETENTION_DAILY=0 u otro caso límite).
  already_kept=0
  for k in "${PRUNE_KEEP[@]}"; do
    [ "$k" = "$newest" ] && already_kept=1 && break
  done
  [ "$already_kept" -eq 0 ] && PRUNE_KEEP+=("$newest")

  for f in "${sorted[@]}"; do
    local keep_this=0
    for k in "${PRUNE_KEEP[@]}"; do
      [ "$f" = "$k" ] && keep_this=1 && break
    done
    [ "$keep_this" -eq 0 ] && PRUNE_DELETE+=("$f")
  done
  # "return 0" EXPLÍCITO: sin él, si el ÚLTIMO archivo de "sorted" resulta "conservado" (el caso
  # común), la comprobación "[ \"\$keep_this\" -eq 0 ]" de arriba es FALSA, y como es la última
  # instrucción de la función, su código de salida (1, por ser falsa) se convertiría en el código
  # de salida de ESTA FUNCIÓN -- bajo "set -e" en el script que la invoca sin envolverla en un
  # "if"/"||", eso mataría el script entero en silencio (confirmado: así fallaba "phase_prune" en
  # la primera versión de esta corrección, con cualquier combinación donde el último archivo
  # ordenado terminara conservado). Mismo tipo de trampa que ya se corrigió para
  # "resolve_confirmed_mvp_postgres_id" (DEP61-03) y para la asignación de "table_count" en
  # "phase_verify" -- una función cuyo ÚLTIMO comando puede evaluar a falso en el camino normal
  # necesita un "return 0" explícito si se la va a invocar como una instrucción suelta.
  return 0
}

phase_prune() {
  assert_private_dir "$BACKUP_DIR"
  _prune_plan
  if [ "${#PRUNE_KEEP[@]}" -eq 0 ] && [ "${#PRUNE_DELETE[@]}" -eq 0 ]; then
    echo "No hay backups verificados en $BACKUP_DIR; nada que podar."
    return 0
  fi
  echo "=== DRY-RUN (ningún archivo se modifica) ==="
  echo "Política: $RETENTION_DAILY día(s) calendario + 1 copia semanal; el backup verificado más reciente siempre se conserva."
  echo "Se conservarían ${#PRUNE_KEEP[@]} backup(s):"
  local f
  for f in "${PRUNE_KEEP[@]}"; do echo "  conservar: $f"; done
  if [ "${#PRUNE_DELETE[@]}" -eq 0 ]; then
    echo "Nada que eliminar: todos los backups verificados están dentro de la retención."
  else
    echo "Se eliminarían ${#PRUNE_DELETE[@]} backup(s):"
    for f in "${PRUNE_DELETE[@]}"; do echo "  ELIMINAR: $f (.dump, .sha256, .manifest, .manifest.sha256, .verified)"; done
    echo "Para aplicar de verdad: CONFIRM=yes bash backup.sh prune-apply"
  fi
}

phase_prune_apply() {
  require_confirm
  assert_private_dir "$BACKUP_DIR"
  _prune_plan
  if [ "${#PRUNE_DELETE[@]}" -eq 0 ]; then
    echo "Nada que podar: ${#PRUNE_KEEP[@]} backup(s) verificado(s), todos dentro de la retención."
    return 0
  fi
  echo "Conservando ${#PRUNE_KEEP[@]} backup(s) verificado(s); eliminando ${#PRUNE_DELETE[@]}."
  local f state
  for f in "${PRUNE_DELETE[@]}"; do
    # Revalida el estado EN ESTE INSTANTE (nunca confía en el cálculo de _prune_plan, que pudo
    # haberse hecho un momento antes) -- requisito "validar su estado" antes de eliminar.
    state="$(backup_state "$f")"
    if [ "$state" != "verified" ]; then
      echo "  OMITIENDO $f: su estado cambió a '$state' desde que se planificó esta poda; no se elimina sin revalidar." >&2
      continue
    fi
    echo "  eliminando $f (.dump, .sha256, .manifest, .manifest.sha256, .verified)"
    rm -f "$f" "$f.sha256" "$f.manifest" "$f.manifest.sha256" "$f.verified"
  done
}

phase_list() {
  assert_private_dir "$BACKUP_DIR"
  local f
  for f in "$BACKUP_DIR"/*.dump; do
    [ -f "$f" ] || continue
    printf '%s\t%s\n' "$(backup_state "$f")" "$f"
  done
}

case "${1:-}" in
  create) phase_create ;;
  verify) phase_verify "${2:-}" ;;
  create-and-verify) phase_create_and_verify ;;
  prune) phase_prune ;;
  prune-apply) phase_prune_apply ;;
  list) phase_list ;;
  *)
    echo "Uso: backup.sh {create|verify <ruta-del-.dump>|create-and-verify|prune|prune-apply|list}" >&2
    exit 1
    ;;
esac
