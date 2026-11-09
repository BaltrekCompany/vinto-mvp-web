#!/usr/bin/env bash
# RG-MP3-01. Pre-activación: importación aditiva del catálogo en una transacción.
# check: solo lectura. apply: respaldo verificado + confirmación de SHA + gate.
# NO conmuta current, NO reinicia servicios, NO concede permisos a usuarios.
set -euo pipefail

ACTION="${1:-}"
SHA="${2:-}"
APP_DIR="/opt/vinto-mvp-web"
SERVICE_USER="vinto-mvp"
BACKUP_DIR="/home/ubuntu/vinto-mvp-backups"
FORM="VINTO-MP3-01"

case "$ACTION" in check|apply) ;; *) echo "Uso: $0 {check|apply} <SHA40>" >&2; exit 2 ;; esac
if ! [[ "$SHA" =~ ^[a-f0-9]{40}$ ]]; then
  echo "MP3_RG01_STOP=INVALID_SHA" >&2; exit 2
fi

RELEASE="$APP_DIR/releases/$SHA"
if [ ! -d "$RELEASE/backend/seed_data" ] || [ ! -f "$RELEASE/backend/seed_data/forms/$FORM.json" ]; then
  echo "MP3_RG01_STOP=RELEASE_NOT_PREPARED" >&2; exit 2
fi
if [ ! -x "$RELEASE/backend/.venv/bin/python" ] || [ ! -e "$RELEASE/backend/.env" ]; then
  echo "MP3_RG01_STOP=BACKEND_RUNTIME_NOT_PREPARED" >&2; exit 2
fi
CURRENT="$(readlink -f "$APP_DIR/current" || true)"
if [ -z "$CURRENT" ]; then
  echo "MP3_RG01_STOP=NO_CURRENT_RELEASE" >&2; exit 2
fi
if [ "$CURRENT" = "$RELEASE" ]; then
  echo "MP3_RG01_STOP=REQUIRES_PREACTIVATION" >&2; exit 2
fi

run_gate() {
  local arg="${1:-}"
  sudo -u "$SERVICE_USER" bash -c '
    set -euo pipefail
    cd "$1"
    shift
    exec .venv/bin/python mp3_rg01_import_gate.py "$@"
  ' -- "$RELEASE/backend" ${arg:+"$arg"}
}

if [ "$ACTION" = check ]; then
  echo "MP3_RG01_CURRENT=$CURRENT"
  echo "MP3_RG01_CANDIDATE=$RELEASE"
  run_gate
  exit $?
fi

if [ "${CONFIRM:-}" != "yes" ] || [ "${AUTHORIZED_COMMIT:-}" != "$SHA" ]; then
  echo "MP3_RG01_STOP=EXPLICIT_AUTHORIZATION_REQUIRED" >&2; exit 2
fi

# El backup debe pertenecer a la carpeta de backups oficial.
BACKUP="${BACKUP_FILE:-}"
case "$BACKUP" in
  "$BACKUP_DIR"/vinto-mvp-vinto_piloto-*.dump) ;;
  *) echo "MP3_RG01_STOP=INVALID_BACKUP_PATH" >&2; exit 2 ;;
esac
if [ ! -s "$BACKUP" ] || [ ! -s "$BACKUP.sha256" ] || [ ! -f "$BACKUP.verified" ]; then
  echo "MP3_RG01_STOP=BACKUP_NOT_VERIFIED" >&2; exit 2
fi
sha256sum -c "$BACKUP.sha256"

# Esta fase comparte el lock operacional con activate/rollback para no
# importar mientras otro proceso cambia de versión.
# IMPORTANTE: lock del operador instalado en OPS, NO el lock del release
# candidato; activate/rollback usan /home/ubuntu/vinto-mvp-ops/scripts.
SCRIPT_DIR="/home/ubuntu/vinto-mvp-ops/scripts"
if [ ! -f "$SCRIPT_DIR/lib_common.sh" ]; then
  echo "MP3_RG01_STOP=OPS_LOCK_LIBRARY_MISSING" >&2; exit 2
fi
# shellcheck source=./lib_common.sh
source "$SCRIPT_DIR/lib_common.sh"
acquire_activate_lock

if [ "$(readlink -f "$APP_DIR/current")" != "$CURRENT" ]; then
  echo "MP3_RG01_STOP=CURRENT_CHANGED" >&2; exit 2
fi

echo "=== RG01 PLAN FINAL (READ ONLY) ==="
run_gate

echo "=== RG01 APPLY TRANSACTIONAL ==="
run_gate --apply

echo "=== RG01 POSTCHECK (READ ONLY) ==="
run_gate

if [ "$(readlink -f "$APP_DIR/current")" != "$CURRENT" ]; then
  echo "MP3_RG01_STOP=UNEXPECTED_RELEASE_CHANGE" >&2; exit 2
fi
echo "MP3_RG01_PREACTIVATION_IMPORT=PASS"
