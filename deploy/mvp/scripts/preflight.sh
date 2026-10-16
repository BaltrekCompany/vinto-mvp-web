#!/usr/bin/env bash
# VINTO MVP WEB — preflight de solo lectura (CLOUD-DEP-02A / se ejecuta en DEP-02B).
# Corregido en CLOUD-DEP-02A.2 (DEP55-03) y en CLOUD-DEP-02A.2-R2 (DEP55-R2-02) tras las
# auditorías del PR #55.
#
# No modifica nada. Verifica que los supuestos de este despliegue siguen siendo ciertos en el VPS
# ANTES de cada grupo de fases de deploy.sh. Seguro de ejecutar repetidamente. Pensado para
# correrse EN EL VPS (no localmente) — aquí solo se valida con `bash -n`/ShellCheck (ver
# deploy/mvp/scripts/tests).
#
# DEP55-R2-02: antes había una sola pasada que mezclaba infraestructura, dependencias de build y
# arranque — una dependencia de compilación ausente (p. ej. Node) bloqueaba un chequeo de
# infraestructura que no la necesita para nada. Ahora son 3 etapas independientes:
#   infra        — puertos, rutas, identidad de recursos, TVC, Docker, backup. NO depende de
#                  node/python/git/corepack: estos NUNCA aparecen en esta etapa.
#   build-deps   — SOLO las dependencias necesarias para compilar/migrar (node, corepack, git,
#                  curl, python3.12), y que la ruta real de node/corepack para el usuario de
#                  servicio coincide con la que los units de systemd asumen.
#   startup      — justo antes de activar/arrancar: puertos todavía libres, el release a activar
#                  está completo, el contenedor de PostgreSQL (si se requiere) está saludable.
# Sin argumento, ejecuta las 3 en orden (equivalente a antes, para una revisión rápida manual).
#
# Uso: bash preflight.sh {infra|build-deps|startup|all}

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib_common.sh
source "$SCRIPT_DIR/lib_common.sh"

FAIL=0
ok()   { printf 'OK    %s\n' "$1"; }
warn() { printf 'AVISO %s  -- %s\n' "$1" "$2"; }
fail() { printf 'FALLA %s  -- %s\n' "$1" "$2"; FAIL=1; }

stage_infra() {
echo "=== VINTO MVP WEB — preflight: infraestructura y coexistencia (solo lectura) ==="

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

# 7. Evidencia de backup de TVC antes de autorizar las fases de riesgo (las que crean/arrancan
#    PostgreSQL, aplican roles o migran). Este script NO puede verificar un backup por sí mismo
#    (no tiene acceso a dónde se guarda); exige una atestación explícita del operador vía variable
#    de entorno, igual de explícita que CONFIRM=yes en deploy.sh.
if [ "${TVC_BACKUP_CONFIRMED:-}" = "yes" ]; then
  ok "TVC_BACKUP_CONFIRMED=yes — el operador atestigua que existe un backup verificado de postgres-vinto (TVC) antes de iniciar fases de riesgo"
else
  warn "backup de TVC" "TVC_BACKUP_CONFIRMED no es 'yes' — confirmar con quien administra TVC que el backup existe y está verificado ANTES de autorizar deploy.sh postgres-up/postgres-roles/migrate (no bloquea este preflight de solo lectura, pero deploy.sh exigirá esta misma variable en esas fases)"
fi

# 8. Primera instalación vs actualización: clasificación informativa, no bloqueante por sí sola
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
}

stage_build_deps() {
echo "=== VINTO MVP WEB — preflight: dependencias de build/migración (solo lectura) ==="
echo "Esta etapa es independiente de 'infra': una dependencia ausente aquí nunca debe impedir un"
echo "chequeo de infraestructura que no la necesita (DEP55-R2-02)."

for bin in git curl node; do
  if command -v "$bin" >/dev/null 2>&1; then
    ok "dependencia '$bin' disponible ($(command -v "$bin"))"
  else
    fail "dependencia '$bin'" "no está instalada; requerida antes de 'checkout'/'frontend-build'"
  fi
done
if command -v python3.12 >/dev/null 2>&1; then
  ok "dependencia 'python3.12' disponible ($(command -v python3.12))"
else
  fail "dependencia 'python3.12'" "no está instalada; requerida para el venv del backend"
fi
if command -v corepack >/dev/null 2>&1; then
  ok "dependencia 'corepack' (pnpm) disponible ($(command -v corepack))"
else
  fail "dependencia 'corepack'" "no está instalada; requerida para compilar el frontend"
fi

# Las rutas reales de node/corepack para el USUARIO DE SERVICIO pueden diferir de las del usuario
# que ejecuta este preflight (p. ej. node instalado vía nvm en el home de "ubuntu", invisible para
# un usuario de sistema sin ese PATH) — DEP55-R2-02: "confirmar las rutas reales de Node/Corepack
# que utilizará el usuario de servicio". Solo se puede comprobar una vez que ese usuario existe.
if id "$MVP_SERVICE_USER" >/dev/null 2>&1; then
  service_node="$(sudo -u "$MVP_SERVICE_USER" sh -c 'command -v node' 2>/dev/null || true)"
  if [ -z "$service_node" ]; then
    fail "node para $MVP_SERVICE_USER" "no se encuentra node en el PATH de $MVP_SERVICE_USER (aunque exista para otro usuario). El unit de systemd usa /usr/bin/node explícitamente: instalar node donde $MVP_SERVICE_USER pueda ejecutarlo, o actualizar ExecStart si la ruta real es otra."
  elif [ "$service_node" != "/usr/bin/node" ]; then
    warn "node para $MVP_SERVICE_USER" "resuelve a '$service_node', no a '/usr/bin/node' (la ruta que usa deploy/mvp/systemd/vinto-mvp-frontend.service). Actualizar el ExecStart del unit a la ruta real antes de 'systemd-install', o instalar node en /usr/bin."
  else
    ok "node para $MVP_SERVICE_USER resuelve a /usr/bin/node, igual que ExecStart del unit del frontend"
  fi
  service_corepack="$(sudo -u "$MVP_SERVICE_USER" sh -c 'command -v corepack' 2>/dev/null || true)"
  if [ -z "$service_corepack" ]; then
    fail "corepack para $MVP_SERVICE_USER" "no se encuentra en el PATH de $MVP_SERVICE_USER; requerido por deploy.sh frontend-build (se ejecuta como ese usuario)."
  else
    ok "corepack para $MVP_SERVICE_USER disponible ($service_corepack)"
  fi
else
  warn "rutas de node/corepack para $MVP_SERVICE_USER" "el usuario todavía no existe (se crea en 'user-and-dirs'); repetir esta etapa después de crearlo y antes de 'frontend-build'."
fi

echo "--- Instalación recomendada de Node/Corepack (solo documentación; no se instala nada aquí) ---"
echo "Fijar una versión concreta de Node (p. ej. paquete NodeSource para la versión LTS que exige"
echo "package.json: \"engines\": { \"node\": \">=22.18.0\" }), nunca 'apt install nodejs' genérico sin"
echo "anclar versión. Corepack ya viene con Node >=16.9; 'corepack enable' una sola vez. pnpm queda"
echo "fijado por 'packageManager' en package.json (pnpm@11.25.0) — corepack lo resuelve solo, sin"
echo "instalar pnpm manualmente. Alternativa sin red en el VPS: compilar el frontend en CI/local y"
echo "desplegar dist/standalone/ ya construido (artefacto), saltando 'frontend-build' en el VPS."
}

stage_startup() {
echo "=== VINTO MVP WEB — preflight: arranque y disponibilidad (solo lectura) ==="
echo "Repite los puertos (pueden haber cambiado desde 'infra') y confirma que lo que se va a"
echo "activar/arrancar está realmente completo, justo antes de hacerlo."

for port in 3100 8100 6544; do
  if ss -ltn "( sport = :$port )" 2>/dev/null | grep -q LISTEN; then
    warn "puerto $port" "en uso ahora mismo — si es el propio servicio del MVP en un reinicio, es esperado; si es otra cosa, revisar antes de 'activate'/'systemd-install'"
  else
    ok "puerto $port libre"
  fi
done

if [ -L "$MVP_APP_DIR/current" ]; then
  release_dir="$(readlink -f "$MVP_APP_DIR/current")"
  if [ -x "$release_dir/backend/.venv/bin/uvicorn" ] && [ -f "$release_dir/dist/standalone/server.js" ]; then
    ok "'current' -> $release_dir está completo (venv + build del frontend)"
  else
    fail "'current'" "apunta a $release_dir pero falta el venv o el build del frontend; no arrancar los servicios todavía"
  fi
else
  warn "'current'" "todavía no existe (esperado antes de la primera 'activate')"
fi

if docker ps --format '{{.Names}}' | grep -qx "$MVP_POSTGRES_CONTAINER"; then
  if docker exec "$MVP_POSTGRES_CONTAINER" sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1; then
    ok "$MVP_POSTGRES_CONTAINER está arriba y acepta conexiones (pg_isready)"
  else
    fail "$MVP_POSTGRES_CONTAINER" "está arriba pero no responde a pg_isready; no continuar con migrate/arranque del backend"
  fi
else
  warn "$MVP_POSTGRES_CONTAINER" "no está corriendo todavía (esperado si aún no se ejecutó 'postgres-up')"
fi
}

case "${1:-all}" in
  infra) stage_infra ;;
  build-deps) stage_build_deps ;;
  startup) stage_startup ;;
  all) stage_infra; stage_build_deps; stage_startup ;;
  *)
    echo "Uso: preflight.sh {infra|build-deps|startup|all}" >&2
    exit 1
    ;;
esac

echo "=== Resultado: $([ "$FAIL" -eq 0 ] && echo 'SIN FALLAS BLOQUEANTES' || echo 'HAY FALLAS — NO CONTINUAR CON deploy.sh') ==="
exit "$FAIL"
