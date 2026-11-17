#!/usr/bin/env bash
# OFF-03D.6A: inspect-only readiness for isolated QA checkout, venv and backup.
# No checkout, pip install, Docker mutations, SQL DDL or file creation.
set -Eeuo pipefail
set +x
export LC_ALL=C

die() { echo "OFF03D6A_BLOCKED: $*" >&2; exit 1; }
usage() { echo 'sudo bash scripts/off-03d6a-qa-staging-preflight.sh inspect'; }
case "$#" in 1) ;; *) usage >&2; exit 2 ;; esac
case "$1" in
  -h|--help|help) usage; exit 0 ;;
  inspect) ;;
  *) usage >&2; die 'solo inspect; escritura no disponible' ;;
esac

[ "$(id -u)" -eq 0 ] || die 'requiere sudo'
for c in docker git bash df awk python3 stat; do
  command -v "$c" >/dev/null 2>&1 || die "falta $c"
done

# Reuse the previously audited and verified D.5 gate. Fail closed if absent/changed.
D5=/tmp/vinto-off03d5-qa-migration-preflight.sh
D5_BLOB=f296b71930a8820abea8666fb1aac01a16ede9e6
[ -f "$D5" ] && [ ! -L "$D5" ] || die 'script D5 exacto ausente'
[ "$(git hash-object "$D5")" = "$D5_BLOB" ] || die 'script D5 alterado'
bash "$D5" inspect || die 'OFF-03D.5 ya no cumple'
echo 'OFF03D6A_D5_GATE=PASS'

# Fixed paths; they are not derived from environment variables.
QA_ROOT=/srv/vinto-qa-offline
QA_CHECKOUT=/srv/vinto-qa-offline/source
QA_VENV=/srv/vinto-qa-offline/venv
QA_BACKUPS=/srv/vinto-qa-offline/backups
# These must be free for a later controlled creation; never overwrite any existing tree.
for path in "$QA_ROOT" "$QA_CHECKOUT" "$QA_VENV" "$QA_BACKUPS"; do
  [ ! -e "$path" ] && [ ! -L "$path" ] ||
    die 'ruta reservada ya existe; inspeccionar manualmente antes de continuar'
done
[ -d /srv ] && [ ! -L /srv ] || die '/srv no es directorio normal'
echo 'OFF03D6A_PATHS_AVAILABLE=PASS'
echo 'OFF03D6A_PILOT_PATHS_UNTOUCHED=PASS'

python3 -m venv --help >/dev/null 2>&1 || die 'python3-venv no disponible'
echo 'OFF03D6A_PYTHON_VENV_CAPABLE=PASS'

QA=vinto-qa-postgres
[ "$(docker inspect -f '{{.Config.Image}}' "$QA" 2>/dev/null || true)" = postgres:17 ] ||
  die 'imagen PostgreSQL QA distinta'
[ "$(docker inspect -f '{{.State.Running}}' "$QA")" = true ] ||
  die 'contenedor QA detenido'
for tool in pg_dump pg_dumpall pg_restore; do
  docker exec "$QA" "$tool" --version >/dev/null ||
    die "falta $tool en contenedor QA"
done
echo 'OFF03D6A_BACKUP_TOOLS=PASS'

# Metadata only: schema still empty, and size estimate for planning; no business rows.
QA_BYTES="$(docker exec \
  -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=5000' \
  "$QA" psql -X -qAt -v ON_ERROR_STOP=1 \
  -U vinto_qa_bootstrap -d vinto_qa_offline \
  -c 'SELECT pg_database_size(current_database())')" ||
  die 'no se puede estimar el volumen QA'
case "$QA_BYTES" in *[!0-9]*|'') die 'tamano QA no numerico' ;; esac
echo "OFF03D6A_QA_DB_SIZE_BYTES=$QA_BYTES"

FREE_KB="$(df -Pk /srv | awk 'NR==2 {print $4}')"
case "$FREE_KB" in *[!0-9]*|'') die 'capacidad /srv no numerica' ;; esac
[ "$FREE_KB" -ge 2097152 ] || die 'menos de 2 GiB disponibles en /srv'
echo 'OFF03D6A_FREE_DISK_2GIB=PASS'
echo 'OFF03D6A_CHECKOUT=NOT_CREATED'
echo 'OFF03D6A_VENV=NOT_CREATED'
echo 'OFF03D6A_BACKUP=NOT_CREATED'
echo 'OFF03D6A_MIGRATIONS=NOT_STARTED'
echo 'OFF03D6A_PREFLIGHT=PASS_READ_ONLY'
echo 'NO_DATABASE_WRITES=PASS'
