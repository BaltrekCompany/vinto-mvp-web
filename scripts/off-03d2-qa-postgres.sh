#!/usr/bin/env bash
# VINTO OFF-03D.2: isolated QA Postgres. No actions touch pilot or TVC.
set -Eeuo pipefail
export LC_ALL=C
umask 077
DOMAIN=qa-vinto-mvp.baltrekservices.com
IP=51.79.65.225
NAME=vinto-qa-postgres
NET=vinto-qa-internal
VOL=vinto-qa-offline-pgdata
IMG=postgres:17
PORT=6554
DB=vinto_qa_offline
USER=vinto_qa_bootstrap
SECRET_DIR=/etc/vinto-qa
SECRET=/etc/vinto-qa/postgres-bootstrap.password

die(){ echo "OFF03D2_BLOCKED: $*" >&2; exit 1; }
need(){ command -v "$1" >/dev/null 2>&1 || die "falta $1"; }
root(){ [ "$(id -u)" -eq 0 ] || die 'requiere sudo'; }
usage(){
  echo 'sudo bash scripts/off-03d2-qa-postgres.sh preflight'
  echo 'sudo env CONFIRM_QA_DB_CREATE=YES bash scripts/off-03d2-qa-postgres.sh install'
  echo 'sudo bash scripts/off-03d2-qa-postgres.sh verify'
}
preflight(){
  root
  for x in docker curl getent awk sort grep ss openssl systemctl; do need "$x"; done
  docker info >/dev/null 2>&1 || die 'Docker no disponible'
  addr="$(getent ahostsv4 "$DOMAIN" | awk '{print $1}' | sort -u)"
  [ "$addr" = "$IP" ] || die 'DNS QA diferente'
  ready="$(curl --silent --show-error --fail --noproxy '*' --proto '=https' \
    --connect-timeout 5 --max-time 15 "https://$DOMAIN/qa-ready")" || die 'HTTPS QA inaccesible'
  [ "$ready" = VINTO_QA_HTTPS_READY ] || die 'HTTPS QA incorrecto'
  echo 'QA_HTTPS=PASS'
  for svc in vinto-mvp-frontend vinto-mvp-backend vinto-web; do
    systemctl is-active --quiet "$svc" || die "servicio existente inactivo: $svc"
  done
  for c in vinto-mvp-postgres postgres-vinto; do
    [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null || true)" = true ] \
      || die "contenedor existente inactivo: $c"
  done
  echo 'PILOT_TVC_RUNNING=PASS'
  if ss -H -ltn "( sport = :$PORT )" | grep -q .; then die 'puerto QA ocupado'; fi
  echo 'QA_PORT_6554=AVAILABLE'
  ! docker container inspect "$NAME" >/dev/null 2>&1 || die 'contenedor QA ya existe'
  ! docker network inspect "$NET" >/dev/null 2>&1 || die 'red QA ya existe'
  ! docker volume inspect "$VOL" >/dev/null 2>&1 || die 'volumen QA ya existe'
  [ ! -e "$SECRET_DIR" ] || die 'secretos QA ya existen'
  echo 'QA_NAMES_COLLISION=NONE'
  docker image inspect "$IMG" >/dev/null 2>&1 || die 'falta imagen local postgres:17; no descargar implicitamente'
  echo 'POSTGRES17_IMAGE_LOCAL=PASS'
  echo 'OFF03D2_PREFLIGHT=PASS'
  echo 'CHANGES_MADE=NONE'
}
verify(){
  root; need docker
  [ "$(docker inspect -f '{{.Config.Image}}' "$NAME" 2>/dev/null || true)" = "$IMG" ] || die 'imagen QA incorrecta'
  [ "$(docker inspect -f '{{index .Config.Labels "org.baltrek.environment"}}' "$NAME")" = qa ] || die 'etiqueta QA incorrecta'
  [ "$(docker inspect -f '{{.State.Running}}' "$NAME")" = true ] || die 'contenedor detenido'
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$NAME")" = healthy ] || die 'contenedor no saludable'
  [ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$NAME")" = "$NET" ] || die 'red incorrecta'
  bind="$(docker inspect -f '{{range (index .HostConfig.PortBindings "5432/tcp")}}{{.HostIp}}:{{.HostPort}}{{end}}' "$NAME")"
  [ "$bind" = "127.0.0.1:$PORT" ] || die 'puerto no aislado en loopback'
  mount="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Type}}:{{.Name}}{{end}}{{end}}' "$NAME")"
  [ "$mount" = "volume:$VOL" ] || die 'volumen incorrecto'
  result="$(docker exec -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=5000' \
    "$NAME" psql -X -qAt -v ON_ERROR_STOP=1 -U "$USER" -d "$DB" \
    -c "SELECT CASE WHEN current_database()='vinto_qa_offline' AND current_user='vinto_qa_bootstrap' THEN 'PASS' ELSE 'BLOCKED' END; SELECT CASE WHEN NOT EXISTS(SELECT 1 FROM pg_database WHERE datname='vinto_piloto') THEN 'PASS' ELSE 'BLOCKED' END;")" \
    || die 'consulta DB QA fallida'
  [ "$result" = "$(printf 'PASS\nPASS')" ] || die 'identidad de cluster QA incorrecta'
  echo 'QA_DB_ISOLATION=PASS'
  echo 'QA_DB_PORT=127.0.0.1:6554'
  echo 'QA_DB_NAME=vinto_qa_offline'
  echo 'QA_DB_APP_ROLES=NOT_CONFIGURED'
  echo 'QA_DB_MIGRATIONS=NOT_APPLIED'
  echo 'OFF03D2_VERIFY=PASS_BOOTSTRAP_ONLY'
}
install_qa(){
  [ "${CONFIRM_QA_DB_CREATE:-}" = YES ] || die 'requiere CONFIRM_QA_DB_CREATE=YES'
  preflight
  install -d -m 0700 "$SECRET_DIR"
  openssl rand -hex 32 > "$SECRET"
  chmod 0600 "$SECRET"
  docker network create --driver bridge --label org.baltrek.environment=qa "$NET" >/dev/null
  docker volume create --label org.baltrek.environment=qa "$VOL" >/dev/null
  docker run -d --name "$NAME" --label org.baltrek.environment=qa \
    --restart unless-stopped --network "$NET" \
    --publish "127.0.0.1:$PORT:5432" \
    --mount "type=volume,src=$VOL,dst=/var/lib/postgresql/data" \
    --mount "type=bind,src=$SECRET,dst=/run/secrets/postgres_password,readonly" \
    --env "POSTGRES_USER=$USER" --env "POSTGRES_DB=$DB" \
    --env POSTGRES_PASSWORD_FILE=/run/secrets/postgres_password \
    --memory 1g --cpus 2 --pids-limit 256 \
    --health-cmd 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
    --health-interval 10s --health-timeout 5s --health-retries 12 "$IMG" >/dev/null
  for n in $(seq 1 40); do
    state="$(docker inspect -f '{{.State.Health.Status}}' "$NAME")"
    [ "$state" != unhealthy ] || die 'QA unhealthy: conservar recursos para diagnostico'
    [ "$state" != healthy ] || break
    sleep 2
  done
  verify
  echo 'OFF03D2_INSTALL=PASS_BOOTSTRAP_ONLY'
  echo 'PILOT_TVC_MODIFICATIONS=NONE_BY_THIS_SCRIPT'
}
case "${1:-help}" in
  -h|--help|help) usage ;;
  preflight) preflight ;;
  verify) verify ;;
  install) install_qa ;;
  *) usage >&2; die 'accion desconocida' ;;
esac
