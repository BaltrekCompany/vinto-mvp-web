#!/usr/bin/env bash
# OFF-03D.5: read-only staging gate before schema migration. NEVER applies DDL.
set -Eeuo pipefail
set +x
export LC_ALL=C
die() { echo "OFF03D5_BLOCKED: $*" >&2; exit 1; }
usage() { echo 'sudo bash scripts/off-03d5-qa-migration-preflight.sh inspect'; }
case "$#" in 1) ;; *) usage >&2; exit 2 ;; esac
case "$1" in
  -h|--help|help) usage; exit 0 ;;
  inspect) ;;
  *) usage >&2; die 'operacion no soportada' ;;
esac
[ "$(id -u)" -eq 0 ] || die 'requiere sudo'
for c in docker curl git python3 openssl getent awk sort grep stat systemctl ss; do
  command -v "$c" >/dev/null 2>&1 || die "falta $c"
done

QA=vinto-qa-postgres
DB=vinto_qa_offline
SEC=/etc/vinto-qa/role-migrator.password
DOMAIN=qa-vinto-mvp.baltrekservices.com

dns="$(getent ahostsv4 "$DOMAIN" | awk '{print $1}' | sort -u)"
[ "$dns" = 51.79.65.225 ] || die 'DNS QA inesperado'
marker="$(curl -fsS --noproxy '*' --proto '=https' \
  --connect-timeout 5 --max-time 15 "https://$DOMAIN/qa-ready")" || die 'origen HTTPS QA inaccesible'
[ "$marker" = VINTO_QA_HTTPS_READY ] || die 'marcador HTTPS QA inesperado'
echo 'QA_HTTPS=PASS'

[ "$(docker inspect -f '{{.Config.Image}}' "$QA" 2>/dev/null || true)" = postgres:17 ] || die 'imagen QA incorrecta'
[ "$(docker inspect -f '{{.State.Running}}' "$QA")" = true ] || die 'QA detenido'
[ "$(docker inspect -f '{{.State.Health.Status}}' "$QA")" = healthy ] || die 'QA unhealthy'
[ "$(docker inspect -f '{{index .Config.Labels "org.baltrek.environment"}}' "$QA")" = qa ] || die 'etiqueta QA incorrecta'
[ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$QA")" = vinto-qa-internal ] || die 'red QA incorrecta'
bind="$(docker inspect -f '{{range (index .HostConfig.PortBindings "5432/tcp")}}{{.HostIp}}:{{.HostPort}}{{end}}' "$QA")"
[ "$bind" = 127.0.0.1:6554 ] || die 'QA DB no exclusiva de localhost'
mount="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Type}}:{{.Name}}{{end}}{{end}}' "$QA")"
[ "$mount" = volume:vinto-qa-offline-pgdata ] || die 'volumen QA distinto'
echo 'QA_DB_ISOLATION=PASS'

[ "$(stat -c '%U:%a' "$SEC")" = root:600 ] || die 'credencial migrador no protegida'

for svc in vinto-mvp-frontend vinto-mvp-backend vinto-web; do
  systemctl is-active --quiet "$svc" || die "servicio $svc inactivo"
done
for c in vinto-mvp-postgres postgres-vinto; do
  [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null || true)" = true ] || die "contenedor $c inactivo"
done
echo 'PILOT_TVC_RUNNING=PASS'

read_only_sql="$(docker exec \
  -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=5000' \
  "$QA" psql -X -qAt -v ON_ERROR_STOP=1 \
  -U vinto_qa_bootstrap -d "$DB" \
  -c "SELECT CASE WHEN
   current_database()='vinto_qa_offline'
   AND NOT EXISTS (SELECT 1 FROM pg_database WHERE datname='vinto_piloto')
   AND (SELECT count(*) FROM pg_roles WHERE rolname IN
      ('vinto_app','vinto_migrator','vinto_reference'))=3
   AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN
      ('vinto_identity','vinto_test_admin'))
   AND NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname IN
      ('vinto_master','vinto_config','vinto_txn','vinto_audit','vinto_auth','vinto_meta'))
   AND to_regclass('vinto_meta.schema_migration') IS NULL
   AND NOT has_database_privilege('public','vinto_qa_offline','CONNECT')
   AND has_database_privilege('vinto_migrator','vinto_qa_offline','CREATE')
   THEN 'PASS' ELSE 'BLOCKED' END;")" || die 'consulta metadata fallida'
[ "$read_only_sql" = PASS ] || die 'base/roles/historial no son estado D4 esperado'
echo 'QA_ROLES_READY=PASS'
echo 'QA_SCHEMA_EMPTY=PASS'
echo 'QA_MIGRATION_HISTORY=EMPTY'

actual="$(cat "$SEC" | docker exec -i \
  -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=5000' \
  "$QA" sh -ceu '
    IFS= read -r PGPASSWORD
    export PGPASSWORD
    exec psql -X -qAt -v ON_ERROR_STOP=1 -h 127.0.0.1 \
      -U vinto_migrator -d vinto_qa_offline \
      -c "SELECT current_database() || '|' || current_user"
  ')" || die 'login de migrador QA fallido'
[ "$actual" = vinto_qa_offline\|vinto_migrator ] || die 'identidad migrador incorrecta'
echo 'QA_MIGRATOR_AUTH=PASS'

echo "PYTHON_VERSION=$(python3 -c 'import sys;print(".".join(map(str,sys.version_info[:3])))')"
echo 'PYTHON_VENV_INSTALLATION=NOT_VERIFIED'
echo 'QA_CHECKOUT_SHA=NOT_VERIFIED'
echo 'QA_MIGRATION_DDL=NOT_STARTED'
echo 'OFF03D5_PREFLIGHT=PASS_READ_ONLY'
echo 'NO_DATABASE_WRITES=PASS'
