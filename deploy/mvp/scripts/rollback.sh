#!/usr/bin/env bash
# VINTO MVP WEB — rollback (CLOUD-DEP-02A: preparado aquí; se ejecuta en DEP-02B si hace falta).
#
# Reversible y acotado al MVP: nunca nombra ni toca postgres-vinto, vinto-web.service,
# /opt/vinto-web, vinto_default ni /etc/nginx/sites-available/vinto-tvc. Cada fase es independiente
# para poder revertir solo lo que se necesite (p. ej. solo el frontend, sin tocar la base de datos).
#
# Uso: CONFIRM=yes bash rollback.sh {systemd|postgres|nginx|all}
# "postgres" NUNCA borra el bind-mount de datos por defecto (solo detiene el contenedor): para
# destruir datos hay que pasar además DESTROY_DATA=yes, una confirmación separada y explícita.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

require_confirm() {
  if [ "${CONFIRM:-}" != "yes" ]; then
    echo "Esta fase requiere CONFIRM=yes de forma explícita. No se ejecuta nada." >&2
    exit 1
  fi
}

rollback_systemd() {
  require_confirm
  sudo systemctl stop vinto-mvp-backend.service vinto-mvp-frontend.service 2>/dev/null || true
  sudo systemctl disable vinto-mvp-backend.service vinto-mvp-frontend.service 2>/dev/null || true
  sudo rm -f /etc/systemd/system/vinto-mvp-backend.service /etc/systemd/system/vinto-mvp-frontend.service
  sudo systemctl daemon-reload
  echo "Unidades systemd del MVP detenidas y eliminadas. vinto-web.service (TVC) no se tocó."
}

rollback_postgres() {
  require_confirm
  local compose_dir="$SCRIPT_DIR/../docker"
  docker compose -f "$compose_dir/docker-compose.postgres.yml" --env-file "$compose_dir/.env" down
  if [ "${DESTROY_DATA:-}" = "yes" ]; then
    # shellcheck disable=SC1091
    source "$compose_dir/.env"
    echo "DESTROY_DATA=yes: eliminando ${VINTO_MVP_PGDATA_DIR:?} (irreversible). Confirmar que hay backup."
    sudo rm -rf "${VINTO_MVP_PGDATA_DIR:?}"
  else
    echo "Contenedor detenido; el bind-mount de datos se conserva (pasar DESTROY_DATA=yes para borrarlo)."
  fi
  echo "postgres-vinto (TVC) no se tocó."
}

rollback_nginx() {
  require_confirm
  sudo rm -f /etc/nginx/sites-enabled/vinto-mvp
  if sudo nginx -t; then
    sudo systemctl reload nginx
    echo "Bloque nginx del MVP retirado y nginx recargado. sites-available/vinto-tvc no se tocó."
  else
    echo "nginx -t falló tras retirar el enlace — revisar antes de recargar; TVC sigue sirviendo con la configuración anterior." >&2
    exit 1
  fi
}

case "${1:-}" in
  systemd) rollback_systemd ;;
  postgres) rollback_postgres ;;
  nginx) rollback_nginx ;;
  all) rollback_systemd; rollback_postgres; rollback_nginx ;;
  *)
    echo "Uso: rollback.sh {systemd|postgres|nginx|all}" >&2
    exit 1
    ;;
esac
