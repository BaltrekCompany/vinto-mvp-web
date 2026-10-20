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
  assert_can_read_mvp_private_paths
  local sha="${1:?Uso: rollback.sh version <sha-anterior-de-40-caracteres>}"
  if ! [[ "$sha" =~ ^[0-9a-f]{40}$ ]]; then
    echo "FALLA: '$sha' no es un SHA completo de 40 caracteres hexadecimales. No se acepta una rama ni una referencia parcial (podría moverse). Abortando." >&2
    exit 1
  fi
  local release_dir="$MVP_APP_DIR/releases/$sha"
  if ! mvp_test -d "$release_dir"; then
    echo "FALLA: $release_dir no existe. Solo se puede revertir a una versión que ya fue desplegada con deploy.sh checkout. Abortando sin modificar 'current'." >&2
    exit 1
  fi
  if ! mvp_test -x "$release_dir/backend/.venv/bin/uvicorn" || ! mvp_test -f "$release_dir/dist/standalone/server.js"; then
    echo "FALLA: $release_dir existe pero no parece una versión completamente desplegada (falta venv o build del frontend). Abortando sin modificar 'current'." >&2
    exit 1
  fi
  # CLOUD-DEP-02B.2-G.12-B4-P3-H1: la identidad de las unidades (assert_unit_is_ours) se verifica
  # ANTES de tocar 'current' — antes corría DESPUÉS de conmutar el symlink, el mismo defecto de
  # orden encontrado y corregido en deploy.sh::phase_activate (ver ese archivo para el incidente
  # real que lo motivó). Reordenado así, un fallo de identidad aquí nunca llega a modificar
  # 'current'. assert_unit_is_ours en sí (lib_common.sh) también se corrigió por separado: antes
  # un "grep" sin privilegios contra un unit root:root 600 fallaba siempre por permisos, nunca por
  # una discrepancia real — un rollback manual legítimo habría fallado igual que la activación.
  for unit in vinto-mvp-backend.service vinto-mvp-frontend.service; do
    assert_unit_is_ours "$unit"
  done

  local previous_target
  previous_target="$(mvp_readlink_f "$MVP_APP_DIR/current" 2>/dev/null || true)"
  echo "Revirtiendo 'current' de '${previous_target:-?}' a '$release_dir'."
  # CLOUD-DEP-02B.1-E.6-A.1: faltaba "sudo -u $MVP_SERVICE_USER" aquí — "ln"/"mv" directos, como
  # el invocador (ubuntu), fallarían con "Permission denied" al intentar escribir dentro de
  # $MVP_APP_DIR (750, exclusivo de $MVP_SERVICE_USER). A diferencia de las comprobaciones de
  # lectura de más arriba (que fallaban en silencio, "no existe"), esta era una mutación que
  # habría fallado de forma RUIDOSA y visible — pero fallado igual, sin revertir nunca 'current'.
  sudo -u "$MVP_SERVICE_USER" ln -sfn "$release_dir" "$MVP_APP_DIR/current.tmp"
  sudo -u "$MVP_SERVICE_USER" mv -T "$MVP_APP_DIR/current.tmp" "$MVP_APP_DIR/current"
  # CLOUD-DEP-02B.2-G.12-B4-P3-H1, punto 9/15 (mismo tratamiento que phase_activate): el código de
  # salida de "systemctl restart" ya no se ignora en silencio, aunque el healthcheck de abajo
  # sigue siendo quien decide si hace falta intervención — esto solo evita que un fallo aquí quede
  # oculto detrás de un healthcheck que, coincidentemente, pudiera pasar de todos modos.
  local restart_rc=0
  sudo systemctl restart vinto-mvp-backend.service vinto-mvp-frontend.service || restart_rc=$?
  if [ "$restart_rc" -ne 0 ]; then
    echo "AVISO: 'systemctl restart' devolvió el código $restart_rc al revertir a $sha; continuando hacia el healthcheck." >&2
  fi
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
# del archivo. "docker compose down", por diseño, no borra bind-mounts (son del host, no
# volúmenes gestionados por Docker), así que el camino normal es seguro incluso sin ninguna
# lógica adicional.
#
# DEP61-01 (auditoría del PR #61): el camino degradado anterior (cuando docker/.env falta o es
# inseguro) invocaba "docker compose ... -p proyecto down" SIN --env-file — pero
# docker-compose.postgres.yml exige "${VAR:?mensaje}" para las 4 claves de entorno/volumen, así
# que Compose fallaba al RESOLVER el archivo YAML antes de intentar detener nada: la
# "recuperación" no recuperaba nada en absoluto (confirmado: Compose aborta en la fase de
# interpolación, nunca llega a ejecutar "down"). Corregido de raíz: el camino degradado ya NUNCA
# pasa por Compose. Resuelve primero la identidad ESTRICTA del contenedor
# (lib_common.sh::resolve_confirmed_mvp_postgres_id — nombre + etiqueta de proyecto + imagen,
# nunca solo el nombre) y, si docker/.env no es válido (o si, siendo válido, "compose down"
# fallara igual por cualquier otro motivo — p. ej. un archivo con permisos/propietario correctos
# pero CONTENIDO corrupto, que el contrato de seguridad del archivo no puede detectar porque
# nunca inspecciona claves ni valores), usa "docker stop" DIRECTAMENTE sobre el ID ya confirmado
# — nunca lee ni una sola variable de docker/.env, nunca fabrica credenciales falsas para
# completar el YAML. Deliberadamente CONSERVADOR: solo detiene, nunca elimina el contenedor ni
# toca la red "vinto-mvp-internal" (a diferencia de "compose down", que sí los elimina) — deja
# esos dos recursos Docker creados a propósito; eliminarlos, si se desea, es una decisión aparte
# del operador (p. ej. una vez restaurado docker/.env, repetir "rollback.sh postgres" con el
# archivo ya válido).
#
# DEP61-02 (auditoría del PR #61): "lib_common.sh::detect_compose_cmd" termina el proceso entero
# con "exit 1" si ni "docker compose" ni "docker-compose" están instalados — correcto para las
# fases MUTADORAS normales de deploy.sh (que de verdad necesitan Compose), pero aquí mataría la
# recuperación entera incluso cuando Docker Engine sigue perfectamente accesible y "docker stop"
# directo funcionaría sin problema. Se invoca dentro de un SUBSHELL "( ... )": si no hay ningún
# comando Compose disponible, el "exit 1" de "detect_compose_cmd" termina SOLO ese subshell, no
# el proceso de rollback.sh — el script sigue y degrada igual a la detención directa. Nunca se
# cambia el comportamiento de "detect_compose_cmd" en sí (seguiría terminando el proceso para
# cualquier llamador que lo invoque fuera de un subshell, como ya hace deploy.sh).
rollback_postgres() {
  require_confirm
  local compose_dir="$SCRIPT_DIR/../docker"
  resolve_confirmed_mvp_postgres_id "$MVP_POSTGRES_CONTAINER" "postgres:17"
  if [ -z "$MVP_POSTGRES_CONTAINER_ID" ]; then
    echo "$MVP_POSTGRES_CONTAINER no existe; nada que detener (idempotente)."
    echo "postgres-vinto (TVC) no se tocó."
    return 0
  fi

  local degraded=0
  if docker_env_contract_check "$compose_dir/.env"; then
    local down_status=0
    # Subshell deliberado (DEP61-02): si "detect_compose_cmd" no encuentra ningún comando Compose,
    # su "exit 1" termina SOLO este subshell -- nunca el proceso de rollback.sh completo.
    ( detect_compose_cmd && "${COMPOSE_CMD[@]}" -f "$compose_dir/docker-compose.postgres.yml" --env-file "$compose_dir/.env" down ) \
      || down_status=$?
    if [ "$down_status" -ne 0 ]; then
      echo "AVISO: 'docker compose down' con docker/.env falló, o ningún comando Docker Compose está disponible en este host (código $down_status) — posible contenido corrupto del archivo (no detectado por su contrato de seguridad, que nunca inspecciona claves/valores) o ausencia de la herramienta Compose. Se degrada a detención directa del contenedor ya identificado; Docker Engine en sí no hace falta que tenga Compose instalado para esto." >&2
      degraded=1
    fi
  else
    echo "AVISO: $DOCKER_ENV_CONTRACT_REASON Se degrada a detención directa del contenedor ya identificado (ID confirmado), sin leer docker/.env ni depender de sus variables." >&2
    degraded=1
  fi

  if [ "$degraded" -eq 1 ]; then
    docker stop "$MVP_POSTGRES_CONTAINER_ID" >/dev/null
    echo "Contenedor $MVP_POSTGRES_CONTAINER detenido directamente (ID confirmado: $MVP_POSTGRES_CONTAINER_ID), sin usar docker/.env ni Docker Compose. A diferencia del camino normal, el contenedor queda DETENIDO pero NO eliminado y la red 'vinto-mvp-internal' no se toca — recursos Docker que quedan creados a propósito (recuperación conservadora, nunca destructiva por defecto)."
  fi
  echo "El bind-mount de datos NO se tocó (este script no tiene ninguna opción para borrarlo)."
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
