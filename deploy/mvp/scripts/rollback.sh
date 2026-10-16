#!/usr/bin/env bash
# VINTO MVP WEB — rollback (CLOUD-DEP-02A: preparado aquí; se ejecuta en DEP-02B si hace falta).
# Corregido en CLOUD-DEP-02A.2 (DEP55-01) tras la auditoría del PR #55.
#
# Reversible y acotado al MVP: nunca nombra ni toca postgres-vinto, vinto-web.service,
# /opt/vinto-web, vinto_default ni /etc/nginx/sites-available/vinto-tvc.
#
# Qué cambió en DEP55-01 respecto de la versión anterior:
#   1. Este script YA NO PUEDE destruir datos de PostgreSQL, en ningún subcomando, bajo ninguna
#      variable de entorno. "postgres" y "all" solo detienen el contenedor; el bind-mount de datos
#      nunca se borra desde aquí. Una destrucción deliberada de datos (p. ej. para reinstalar desde
#      cero) es un procedimiento APARTE, fuera del alcance de este PR — ver
#      "Destrucción deliberada de datos" en deploy/mvp/README.md. No existe ningún atajo aquí para
#      saltarse esa separación.
#   2. Ya no se hace `source` de ningún .env: los valores de configuración se leen como texto
#      (ver lib_common.sh::env_value), nunca se ejecutan como código de shell.
#   3. Antes de detener o eliminar cualquier unidad systemd o contenedor, se comprueba que
#      realmente pertenece al MVP (lib_common.sh::assert_unit_is_ours / assert_container_is_ours).
#      Si algo con el mismo nombre existe pero no es del MVP, el script se detiene sin tocarlo.
#   4. Se añade el subcomando "version", separado de "systemd"/"postgres"/"nginx": revierte el
#      código (symlink `current`) a una versión anterior ya desplegada, sin usar git en absoluto
#      (no hay checkout, reset ni clean en rollback — ver deploy.sh para cómo se preparan las
#      versiones separadas en "releases/").
#
# Corregido en CLOUD-DEP-02A.2-R2 (punto 2 de la auditoría): "version" reiniciaba los servicios
# pero no comprobaba su salud — ahora ejecuta el mismo healthcheck que deploy.sh (lib_common.sh::
# mvp_healthcheck) tras reiniciar y, si no responde, lo dice explícitamente y sale con error en
# vez de afirmar que la recuperación fue exitosa sin haberlo comprobado.
#
# Uso: CONFIRM=yes bash rollback.sh {systemd|postgres|nginx|version <sha-anterior>|all}

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib_common.sh
source "$SCRIPT_DIR/lib_common.sh"

rollback_systemd() {
  require_confirm
  for unit in vinto-mvp-backend.service vinto-mvp-frontend.service; do
    assert_unit_is_ours "$unit"
  done
  sudo systemctl stop vinto-mvp-backend.service vinto-mvp-frontend.service 2>/dev/null || true
  sudo systemctl disable vinto-mvp-backend.service vinto-mvp-frontend.service 2>/dev/null || true
  for unit in vinto-mvp-backend.service vinto-mvp-frontend.service; do
    # Revalidar justo antes de borrar el archivo: defensivo frente a una sustitución entre el
    # chequeo anterior y este punto (TOCTOU), aunque de alcance local y de bajo riesgo real aquí.
    assert_unit_is_ours "$unit"
    sudo rm -f "/etc/systemd/system/$unit"
  done
  sudo systemctl daemon-reload
  echo "Unidades systemd del MVP detenidas y eliminadas. vinto-web.service (TVC) no se tocó."
  echo "Los datos de PostgreSQL y el código en $MVP_APP_DIR/releases no se modificaron."
}

# Revierte el CÓDIGO a una versión anterior ya desplegada (releases/<sha-anterior>), sin tocar
# PostgreSQL ni ejecutar ninguna operación de git. Requiere que esa versión ya exista en disco
# (deploy.sh checkout la crea en cada despliegue nuevo; nunca borra versiones anteriores por sí
# solo — ver deploy.sh::phase_checkout). Reinicia los servicios para que tomen el cambio.
rollback_version() {
  require_confirm
  local sha="${1:?Uso: rollback.sh version <sha-anterior-de-40-caracteres>}"
  if ! [[ "$sha" =~ ^[0-9a-f]{40}$ ]]; then
    echo "FALLA: '$sha' no es un SHA completo de 40 caracteres hexadecimales. No se acepta una rama ni una referencia parcial (podría moverse). Abortando." >&2
    exit 1
  fi
  local release_dir="$MVP_APP_DIR/releases/$sha"
  if [ ! -d "$release_dir" ]; then
    echo "FALLA: $release_dir no existe. Solo se puede revertir a una versión que ya fue desplegada con deploy.sh checkout. Abortando sin modificar 'current'." >&2
    exit 1
  fi
  if [ ! -x "$release_dir/backend/.venv/bin/uvicorn" ] || [ ! -f "$release_dir/dist/standalone/server.js" ]; then
    echo "FALLA: $release_dir existe pero no parece una versión completamente desplegada (falta venv o build del frontend). Abortando sin modificar 'current'." >&2
    exit 1
  fi
  local previous_target
  previous_target="$(readlink -f "$MVP_APP_DIR/current" 2>/dev/null || true)"
  echo "Revirtiendo 'current' de '${previous_target:-?}' a '$release_dir'."
  ln -sfn "$release_dir" "$MVP_APP_DIR/current.tmp"
  mv -T "$MVP_APP_DIR/current.tmp" "$MVP_APP_DIR/current"
  for unit in vinto-mvp-backend.service vinto-mvp-frontend.service; do
    assert_unit_is_ours "$unit"
  done
  sudo systemctl restart vinto-mvp-backend.service vinto-mvp-frontend.service
  echo "'current' ahora apunta a $sha. Servicios reiniciados. Ningún dato de PostgreSQL se tocó."
  # CLOUD-DEP-02A.2-R2-2, punto 2: reiniciar no es lo mismo que recuperarse. Comprobar la salud
  # real tras el reinicio y salir con código de error si no responde, en vez de afirmar un éxito
  # que no se comprobó. Un archivo temporal único por ejecución (punto 3), nunca un nombre fijo.
  sleep 2
  local hc_log
  hc_log="$(mktemp)"
  if mvp_healthcheck >"$hc_log" 2>&1; then
    rm -f "$hc_log"
    echo "Healthcheck OK tras revertir a $sha: la recuperación se confirma exitosa."
  else
    echo "AVISO: 'current' apunta a $sha y los servicios se reiniciaron, pero el healthcheck NO responde correctamente. No se afirma que la recuperación haya sido exitosa — revisar de inmediato (journalctl -u vinto-mvp-backend/-frontend):" >&2
    cat "$hc_log" >&2
    rm -f "$hc_log"
    exit 1
  fi
}

# Detiene el contenedor de PostgreSQL del MVP. NUNCA borra el bind-mount de datos: eso es
# deliberadamente imposible desde este script (DEP55-01 punto 1 y 6) — ver la nota al principio
# del archivo. docker compose down, por diseño, no borra bind-mounts (son del host, no volúmenes
# gestionados por Docker), así que esta función es segura incluso sin ninguna lógica adicional.
rollback_postgres() {
  require_confirm
  local compose_dir="$SCRIPT_DIR/../docker"
  assert_container_is_ours "$MVP_POSTGRES_CONTAINER"
  if [ ! -f "$compose_dir/.env" ]; then
    echo "AVISO: no existe $compose_dir/.env; se intenta 'down' igualmente por nombre de proyecto (vinto-mvp)." >&2
    docker compose -f "$compose_dir/docker-compose.postgres.yml" -p "$MVP_COMPOSE_PROJECT" down
  else
    docker compose -f "$compose_dir/docker-compose.postgres.yml" --env-file "$compose_dir/.env" down
  fi
  echo "Contenedor $MVP_POSTGRES_CONTAINER detenido. El bind-mount de datos NO se tocó (este script no tiene ninguna opción para borrarlo)."
  echo "postgres-vinto (TVC) no se tocó."
}

rollback_nginx() {
  require_confirm
  local link=/etc/nginx/sites-enabled/vinto-mvp
  if [ -L "$link" ]; then
    local target
    target="$(readlink -f "$link")"
    if [ -f "$target" ] && ! grep -q "EXCLUSIVO del MVP" "$target" 2>/dev/null; then
      echo "FALLA DE IDENTIDAD: $link no parece apuntar al bloque nginx del MVP (no contiene la marca esperada). Abortando SIN eliminarlo." >&2
      exit 1
    fi
  fi
  sudo rm -f "$link"
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
  version) rollback_version "${2:-}" ;;
  all) rollback_systemd; rollback_postgres; rollback_nginx ;;
  *)
    echo "Uso: rollback.sh {systemd|postgres|nginx|version <sha-anterior>|all}" >&2
    echo "Ningún subcomando de este script puede borrar datos de PostgreSQL (ver DEP55-01)." >&2
    exit 1
    ;;
esac
