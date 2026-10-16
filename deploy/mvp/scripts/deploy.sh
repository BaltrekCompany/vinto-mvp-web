#!/usr/bin/env bash
# VINTO MVP WEB — despliegue controlado (CLOUD-DEP-02A: preparado aquí; SE EJECUTA EN DEP-02B,
# tras autorización explícita de quien administra el VPS; NUNCA en este incremento).
#
# Principios de este script:
#   - Nunca toca nginx (eso es un paso separado y posterior — ver deploy/mvp/nginx/README más abajo
#     y Fase 5 de CLOUD-DEP-02A).
#   - Nunca toca TVC: ningún comando aquí nombra postgres-vinto, vinto-web.service, /opt/vinto-web
#     ni vinto_default.
#   - Nunca genera ni imprime contraseñas: exige que el operador ya haya creado
#     backend/.env y deploy/mvp/docker/.env a partir de las plantillas .example, con las
#     contraseñas reales puestas a mano. El script solo verifica que existen y tienen permisos
#     correctos; si no existen, se detiene con un mensaje y no continúa.
#   - Cada fase se confirma por separado (variable CONFIRM=yes) para que un operador pueda
#     ejecutarlo fase por fase, revisando el resultado de cada una antes de seguir.
#   - No crea el rol vinto_test_admin en ningún momento (no se ejecuta backend/roles/00b_*.sql).
#
# Uso previsto (en el VPS, por fases):
#   CONFIRM=yes bash deploy.sh preflight
#   CONFIRM=yes bash deploy.sh user-and-dirs
#   CONFIRM=yes bash deploy.sh checkout <commit-sha>
#   CONFIRM=yes bash deploy.sh python-venv
#   CONFIRM=yes bash deploy.sh frontend-build
#   CONFIRM=yes bash deploy.sh postgres-up
#   CONFIRM=yes bash deploy.sh postgres-roles
#   CONFIRM=yes bash deploy.sh migrate
#   CONFIRM=yes bash deploy.sh systemd-install
#   CONFIRM=yes bash deploy.sh healthcheck

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/BaltrekCompany/vinto-mvp-web.git}"
APP_DIR=/opt/vinto-mvp-web
SERVICE_USER=vinto-mvp
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

require_confirm() {
  if [ "${CONFIRM:-}" != "yes" ]; then
    echo "Esta fase requiere CONFIRM=yes de forma explícita. No se ejecuta nada." >&2
    exit 1
  fi
}

phase_preflight() {
  bash "$SCRIPT_DIR/preflight.sh"
}

phase_user_and_dirs() {
  require_confirm
  if id "$SERVICE_USER" >/dev/null 2>&1; then
    echo "El usuario $SERVICE_USER ya existe; no se recrea." >&2
  else
    sudo useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
    echo "Usuario de servicio $SERVICE_USER creado (sin login, sin home, aislado de 'ubuntu')."
  fi
  sudo mkdir -p "$APP_DIR"
  sudo chown "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
  sudo chmod 750 "$APP_DIR"
}

phase_checkout() {
  require_confirm
  local commit="${1:?Uso: deploy.sh checkout <commit-sha>}"
  if [ -d "$APP_DIR/.git" ]; then
    echo "Ya existe un checkout en $APP_DIR; se actualiza con fetch+checkout, nunca con reset --hard sin confirmar manualmente." >&2
    sudo -u "$SERVICE_USER" git -C "$APP_DIR" fetch origin
  else
    sudo -u "$SERVICE_USER" git clone "$REPO_URL" "$APP_DIR"
  fi
  sudo -u "$SERVICE_USER" git -C "$APP_DIR" checkout "$commit"
  echo "Checkout en $commit confirmado:"
  sudo -u "$SERVICE_USER" git -C "$APP_DIR" rev-parse HEAD
}

phase_python_venv() {
  require_confirm
  if [ ! -f "$APP_DIR/backend/.env" ]; then
    echo "FALTA $APP_DIR/backend/.env (copiar de deploy/mvp/env/backend.env.example y completar a mano). No se continúa." >&2
    exit 1
  fi
  perms="$(stat -c '%a' "$APP_DIR/backend/.env")"
  if [ "$perms" != "600" ]; then
    echo "$APP_DIR/backend/.env tiene permisos $perms, deben ser 600. Corregir a mano y reintentar." >&2
    exit 1
  fi
  sudo -u "$SERVICE_USER" python3.12 -m venv "$APP_DIR/backend/.venv"
  sudo -u "$SERVICE_USER" "$APP_DIR/backend/.venv/bin/pip" install --no-cache-dir -r "$APP_DIR/backend/requirements.txt"
}

phase_frontend_build() {
  require_confirm
  local domain="${VINTO_MVP_DOMAIN:?Definir VINTO_MVP_DOMAIN (p. ej. vinto-mvp.baltrekservices.com) antes de compilar}"
  cd "$APP_DIR"
  sudo -u "$SERVICE_USER" corepack pnpm install --frozen-lockfile
  # NEXT_PUBLIC_API_URL se incrusta en el bundle del cliente EN TIEMPO DE BUILD (confirmado en
  # CLOUD-01B-1): debe fijarse aquí, no en el systemd unit del frontend.
  sudo -u "$SERVICE_USER" env NEXT_PUBLIC_API_URL="https://$domain" pnpm run build
  if [ ! -f "$APP_DIR/dist/standalone/server.js" ]; then
    echo "El build no generó dist/standalone/server.js — revisar next.config.ts (output: \"standalone\") y .sites-runtime/execution-profile.json (debe estar AUSENTE para el perfil 'portable')." >&2
    exit 1
  fi
}

phase_postgres_up() {
  require_confirm
  local compose_dir="$SCRIPT_DIR/../docker"
  if [ ! -f "$compose_dir/.env" ]; then
    echo "FALTA $compose_dir/.env (copiar de deploy/mvp/env/postgres.env.example y completar a mano). No se continúa." >&2
    exit 1
  fi
  # shellcheck disable=SC1091
  source "$compose_dir/.env"
  sudo mkdir -p "${VINTO_MVP_PGDATA_DIR:?}"
  sudo chown 999:999 "${VINTO_MVP_PGDATA_DIR}"  # UID/GID del rol postgres dentro de la imagen oficial
  docker compose -f "$compose_dir/docker-compose.postgres.yml" --env-file "$compose_dir/.env" up -d
  docker compose -f "$compose_dir/docker-compose.postgres.yml" --env-file "$compose_dir/.env" ps
}

phase_postgres_roles() {
  require_confirm
  echo "Ejecutar a mano, consultando backend/roles/README.md, EXACTAMENTE en este orden:"
  echo "  1. 00_create_roles.sql   (como el rol de arranque POSTGRES_BOOTSTRAP_USER)"
  echo "  2. 01_database_grants.sql"
  echo "  3. migrate.py --target dev   (conectando como vinto_migrator -> fase siguiente)"
  echo "  4. 02_schema_grants.sql .. 06_public_and_meta_protection.sql   (como vinto_migrator)"
  echo "DELIBERADAMENTE NO se incluye 00b_create_test_admin_role.sql: vinto_test_admin NUNCA se crea"
  echo "en esta instancia (CLOUD-DEP-02A, Fase 3)."
  echo "Este script no las ejecuta automáticamente: cada GRANT debe revisarse en el momento, no"
  echo "en un one-shot sin supervisión sobre una base que podrá llegar a tener datos reales."
}

phase_migrate() {
  require_confirm
  cd "$APP_DIR/backend"
  # migrate.py lee backend/.env directamente (pydantic-settings, env_file=BACKEND_DIR/".env"):
  # no hace falta exportar sus variables a mano (evita el problema de división de palabras de
  # intentar parsear el .env con env/xargs, que rompería con valores que contengan espacios).
  sudo -u "$SERVICE_USER" "$APP_DIR/backend/.venv/bin/python" migrate.py --check
  echo "Si el --check anterior muestra pendientes, ejecutar 'migrate.py' (sin --check) solo tras revisar la salida."
}

phase_systemd_install() {
  require_confirm
  sudo cp "$SCRIPT_DIR/../systemd/vinto-mvp-backend.service" /etc/systemd/system/vinto-mvp-backend.service
  sudo cp "$SCRIPT_DIR/../systemd/vinto-mvp-frontend.service" /etc/systemd/system/vinto-mvp-frontend.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now vinto-mvp-backend.service vinto-mvp-frontend.service
  sudo systemctl status --no-pager vinto-mvp-backend.service vinto-mvp-frontend.service
}

phase_healthcheck() {
  curl -fsS http://127.0.0.1:8100/health && echo
  curl -fsS http://127.0.0.1:8100/api/health && echo
  curl -fsS http://127.0.0.1:3100/ >/dev/null && echo "frontend OK (127.0.0.1:3100)"
}

case "${1:-}" in
  preflight) phase_preflight ;;
  user-and-dirs) phase_user_and_dirs ;;
  checkout) phase_checkout "${2:-}" ;;
  python-venv) phase_python_venv ;;
  frontend-build) phase_frontend_build ;;
  postgres-up) phase_postgres_up ;;
  postgres-roles) phase_postgres_roles ;;
  migrate) phase_migrate ;;
  systemd-install) phase_systemd_install ;;
  healthcheck) phase_healthcheck ;;
  *)
    echo "Uso: deploy.sh {preflight|user-and-dirs|checkout <sha>|python-venv|frontend-build|postgres-up|postgres-roles|migrate|systemd-install|healthcheck}" >&2
    exit 1
    ;;
esac
