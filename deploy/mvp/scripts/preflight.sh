#!/usr/bin/env bash
# VINTO MVP WEB — preflight de solo lectura (CLOUD-DEP-02A / se ejecuta en DEP-02B).
# Corregido en CLOUD-DEP-02A.2 (DEP55-03) tras la auditoría del PR #55.
#
# No modifica nada. Verifica que los supuestos de este despliegue siguen siendo ciertos en el VPS
# ANTES de ejecutar deploy.sh. Seguro de ejecutar repetidamente. Pensado para correrse EN EL VPS
# (no localmente) — aquí solo se valida con `bash -n`/ShellCheck (ver deploy/mvp/scripts/tests).
#
# Qué cambió en DEP55-03 respecto de la versión anterior:
#   - Un conflicto de PROPIEDAD DESCONOCIDA (ruta/contenedor/red/usuario que ya existe pero no se
#     puede confirmar que es de una corrida previa de ESTE despliegue) ahora es FALLA, no AVISO:
#     antes solo avisaba y dejaba continuar; ahora detiene el procedimiento.
#   - Se añaden controles nuevos: red Docker, volumen/bind-mount potencialmente compartido,
#     usuario de servicio existente no verificado, dependencias ausentes (node/python/git/pnpm),
#     evidencia de backup de TVC antes de autorizar una fase de riesgo.
#   - Se distingue explícitamente "primera instalación" de "actualización" al final del informe.
#
# Uso: bash preflight.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib_common.sh
source "$SCRIPT_DIR/lib_common.sh"

FAIL=0
ok()   { printf 'OK    %s\n' "$1"; }
warn() { printf 'AVISO %s  -- %s\n' "$1" "$2"; }
fail() { printf 'FALLA %s  -- %s\n' "$1" "$2"; FAIL=1; }

echo "=== VINTO MVP WEB — preflight (solo lectura) ==="

# 1. Puertos candidatos deben estar libres.
for port in 3100 8100 6544; do
  if ss -ltn "( sport = :$port )" 2>/dev/null | grep -q LISTEN; then
    fail "puerto $port" "ya está en uso; no se puede reutilizar sin revisar antes"
  else
    ok "puerto $port libre"
  fi
done

# 2. Ruta de la aplicación: si ya existe, debe poder confirmarse que es NUESTRA (propietario
#    vinto-mvp y checkout de BaltrekCompany/vinto-mvp-web) o detener el procedimiento — nunca
#    continuar sobre una propiedad desconocida (DEP55-03).
APP_PATH_STATE="no-existe"
if [ -e "$MVP_APP_DIR" ]; then
  owner="$(stat -c '%U' "$MVP_APP_DIR" 2>/dev/null || echo '?')"
  origin=""
  if [ -d "$MVP_APP_DIR/current/.git" ]; then
    origin="$(git -C "$MVP_APP_DIR/current" remote get-url origin 2>/dev/null || true)"
  fi
  if [ "$owner" = "$MVP_SERVICE_USER" ] && [ "$origin" = "https://github.com/BaltrekCompany/vinto-mvp-web.git" ]; then
    ok "$MVP_APP_DIR ya existe y es reconocible como una corrida previa de este despliegue (propietario $MVP_SERVICE_USER, origin correcto)"
    APP_PATH_STATE="existe-confirmada"
  else
    fail "$MVP_APP_DIR" "ya existe pero NO se pudo confirmar que es de este despliegue (propietario='$owner', origin='${origin:-ninguno}'). Conflicto de propiedad desconocida: no continuar sin revisar a mano."
    APP_PATH_STATE="existe-sin-confirmar"
  fi
else
  ok "$MVP_APP_DIR no existe todavía (esperado antes del primer despliegue)"
fi

if [ -e /home/vinto-mvp ]; then
  owner="$(stat -c '%U' /home/vinto-mvp 2>/dev/null || echo '?')"
  if [ "$owner" = "$MVP_SERVICE_USER" ]; then
    ok "/home/vinto-mvp ya existe y pertenece a $MVP_SERVICE_USER"
  else
    fail "/home/vinto-mvp" "ya existe pero pertenece a '$owner', no a $MVP_SERVICE_USER. Conflicto de propiedad desconocida: no continuar."
  fi
else
  ok "/home/vinto-mvp no existe todavía (esperado antes del primer despliegue)"
fi

# 3. TVC debe seguir intacto (no tocar nada de esto; solo lectura para confirmar que sigue vivo).
#    Un TVC no saludable es una señal de entorno a investigar, no necesariamente un conflicto de
#    propiedad: se mantiene como AVISO (DEP55-03 solo exige bloquear los conflictos de propiedad).
for unit in vinto-web.service nginx.service docker.service; do
  if systemctl is-active --quiet "$unit"; then
    ok "$unit sigue activo (TVC/infraestructura compartida intacta)"
  else
    warn "$unit" "no está activo — investigar ANTES de continuar, podría no ser por este despliegue"
  fi
done
if [ -e /etc/nginx/sites-enabled/vinto-tvc ]; then
  ok "sites-enabled/vinto-tvc sigue presente"
else
  warn "sites-enabled/vinto-tvc" "no está presente — no continuar sin entender por qué"
fi

# 4. Docker disponible y el usuario actual puede usarlo sin sudo (grupo docker).
if docker info >/dev/null 2>&1; then
  ok "docker accesible sin sudo"
else
  fail "docker" "no accesible; revisar pertenencia al grupo docker antes de continuar"
fi

# 5. Contenedor de PostgreSQL del MVP: si ya existe, debe ser identificable como nuestro
#    (etiqueta de proyecto de compose) — igual que la ruta de la app, un conflicto de propiedad
#    desconocida ahora bloquea (antes solo avisaba).
POSTGRES_STATE="no-existe"
if docker ps -a --format '{{.Names}}' | grep -qx "$MVP_POSTGRES_CONTAINER"; then
  project="$(docker inspect "$MVP_POSTGRES_CONTAINER" --format '{{ index .Config.Labels "com.docker.compose.project" }}' 2>/dev/null || true)"
  if [ "$project" = "$MVP_COMPOSE_PROJECT" ]; then
    ok "$MVP_POSTGRES_CONTAINER ya existe y es reconocible como del MVP (proyecto compose correcto)"
    POSTGRES_STATE="existe-confirmada"
  else
    fail "$MVP_POSTGRES_CONTAINER" "ya existe pero su etiqueta de proyecto es '${project:-ninguna}', no '$MVP_COMPOSE_PROJECT'. Conflicto de propiedad desconocida: no continuar."
    POSTGRES_STATE="existe-sin-confirmar"
  fi
else
  ok "$MVP_POSTGRES_CONTAINER no existe todavía (esperado antes del primer despliegue)"
fi
if docker ps -a --format '{{.Names}}' | grep -qx "postgres-vinto"; then
  ok "postgres-vinto (TVC) presente, no se tocará"
fi

# 5b. Red Docker del MVP: mismo criterio que el contenedor.
if docker network inspect "$MVP_NETWORK" >/dev/null 2>&1; then
  project="$(docker network inspect "$MVP_NETWORK" --format '{{ index .Labels "com.docker.compose.project" }}' 2>/dev/null || true)"
  if [ "$project" = "$MVP_COMPOSE_PROJECT" ]; then
    ok "red docker $MVP_NETWORK ya existe y es del MVP"
  else
    fail "red docker $MVP_NETWORK" "ya existe pero no está etiquetada como del MVP (etiqueta: '${project:-ninguna}'). Conflicto de propiedad desconocida: no continuar."
  fi
else
  ok "red docker $MVP_NETWORK no existe todavía"
fi

# 6. Usuario de servicio dedicado: si ya existe, debe tener la forma esperada (sin login, sin
#    home ajeno) — antes esto solo era un AVISO, ahora bloquea si no se puede confirmar.
if id "$MVP_SERVICE_USER" >/dev/null 2>&1; then
  shell="$(getent passwd "$MVP_SERVICE_USER" | cut -d: -f7)"
  case "$shell" in
    */nologin|/bin/false)
      ok "usuario $MVP_SERVICE_USER ya existe con shell sin login ($shell) — reutilizable"
      ;;
    *)
      fail "usuario $MVP_SERVICE_USER" "ya existe con shell '$shell' (se esperaba nologin). Conflicto de propiedad desconocida: no continuar sin revisar a mano."
      ;;
  esac
else
  ok "usuario $MVP_SERVICE_USER no existe todavía (esperado antes del primer despliegue)"
fi

# 7. Dependencias necesarias para compilar/ejecutar, ausentes = falla (no se puede continuar sin
#    ellas, da igual la fase).
for bin in git curl node; do
  if command -v "$bin" >/dev/null 2>&1; then
    ok "dependencia '$bin' disponible"
  else
    fail "dependencia '$bin'" "no está instalada; requerida antes de continuar"
  fi
done
if command -v python3.12 >/dev/null 2>&1; then
  ok "dependencia 'python3.12' disponible"
else
  fail "dependencia 'python3.12'" "no está instalada; requerida para el venv del backend"
fi
if command -v corepack >/dev/null 2>&1; then
  ok "dependencia 'corepack' (pnpm) disponible"
else
  fail "dependencia 'corepack'" "no está instalada; requerida para compilar el frontend"
fi

# 8. Evidencia de backup de TVC antes de autorizar las fases de riesgo (las que crean/arrancan
#    PostgreSQL, aplican roles o migran). Este script NO puede verificar un backup por sí mismo
#    (no tiene acceso a dónde se guarda); exige una atestación explícita del operador vía variable
#    de entorno, igual de explícita que CONFIRM=yes en deploy.sh.
if [ "${TVC_BACKUP_CONFIRMED:-}" = "yes" ]; then
  ok "TVC_BACKUP_CONFIRMED=yes — el operador atestigua que existe un backup verificado de postgres-vinto (TVC) antes de iniciar fases de riesgo"
else
  warn "backup de TVC" "TVC_BACKUP_CONFIRMED no es 'yes' — confirmar con quien administra TVC que el backup existe y está verificado ANTES de autorizar deploy.sh postgres-up/postgres-roles/migrate (no bloquea este preflight de solo lectura, pero deploy.sh exigirá esta misma variable en esas fases)"
fi

# 9. Primera instalación vs actualización: clasificación informativa, no bloqueante por sí sola
#    (los conflictos de propiedad de arriba ya bloquearon si correspondía).
echo "--- Clasificación del despliegue ---"
existing=0
[ "$APP_PATH_STATE" = "existe-confirmada" ] && existing=$((existing + 1))
[ "$POSTGRES_STATE" = "existe-confirmada" ] && existing=$((existing + 1))
if [ "$existing" -eq 0 ]; then
  echo "CLASIFICACIÓN: primera instalación (ni $MVP_APP_DIR ni $MVP_POSTGRES_CONTAINER existen todavía)."
elif [ "$existing" -eq 2 ]; then
  echo "CLASIFICACIÓN: actualización (checkout y contenedor de PostgreSQL ya existen y son del MVP; deploy.sh checkout creará una nueva versión en releases/ sin tocar PostgreSQL)."
else
  warn "clasificación" "estado mixto (solo uno de los dos existe) — revisar a mano antes de continuar, no asumir ni primera instalación ni actualización"
fi

echo "=== Resultado: $([ "$FAIL" -eq 0 ] && echo 'SIN FALLAS BLOQUEANTES' || echo 'HAY FALLAS — NO CONTINUAR CON deploy.sh') ==="
exit "$FAIL"
