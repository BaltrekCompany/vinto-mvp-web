#!/usr/bin/env bash
# VINTO OFF-03D.3 — READ ONLY gate before QA schema provisioning.
# Never reads bootstrap password or environment values. Does NOT create roles or migrate.
set -Eeuo pipefail
export LC_ALL=C

usage() {
  echo 'Uso: sudo bash scripts/off-03d3-qa-schema-preflight.sh inspect'
  echo 'Solo lectura. No hay comandos de instalacion o migracion en este archivo.'
}
die() { echo "OFF03D3_BLOCKED: $*" >&2; exit 1; }

if [ "$#" -ne 1 ]; then usage; exit 2; fi
case "$1" in
  -h|--help|help) usage; exit 0 ;;
  inspect) ;;
  *) usage >&2; die 'operacion no soportada';;
esac

[ "$(id -u)" -eq 0 ] || die 'requiere sudo para inspeccion'
for c in docker curl getent awk sort grep ss stat systemctl; do
  command -v "$c" >/dev/null 2>&1 || die "falta herramienta $c"
done
docker info >/dev/null 2>&1 || die 'Docker no disponible'

QA_DOMAIN=qa-vinto-mvp.baltrekservices.com
QA_IP=51.79.65.225
QA_NAME=vinto-qa-postgres
QA_NET=vinto-qa-internal
QA_VOL=vinto-qa-offline-pgdata
QA_DB=vinto_qa_offline
QA_USER=vinto_qa_bootstrap
QA_PORT=6554
QA_SECRET=/etc/vinto-qa/postgres-bootstrap.password

echo '=== 1. DOMINIO HTTPS QA ==='
addr="$(getent ahostsv4 "$QA_DOMAIN" | awk '{print $1}' | sort -u)"
[ "$addr" = "$QA_IP" ] || die 'DNS QA distinto al esperado'
ready="$(curl --silent --show-error --fail --noproxy '*' --proto '=https' \
  --connect-timeout 5 --max-time 15 "https://$QA_DOMAIN/qa-ready")" || die 'HTTPS QA sin respuesta'
[ "$ready" = VINTO_QA_HTTPS_READY ] || die 'marcador HTTPS QA inesperado'
echo 'QA_HTTPS=PASS'

echo '=== 2. CONTENEDOR / RED / VOLUMEN / PUERTO ==='
[ "$(docker inspect -f '{{.Config.Image}}' "$QA_NAME" 2>/dev/null || true)" = postgres:17 ] || die 'imagen QA incorrecta'
[ "$(docker inspect -f '{{.State.Running}}' "$QA_NAME")" = true ] || die 'contenedor QA no activo'
[ "$(docker inspect -f '{{.State.Health.Status}}' "$QA_NAME")" = healthy ] || die 'contenedor QA no saludable'
[ "$(docker inspect -f '{{index .Config.Labels "org.baltrek.environment"}}' "$QA_NAME")" = qa ] || die 'etiqueta QA no coincide'
[ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$QA_NAME")" = "$QA_NET" ] || die 'red QA diferente'
bind="$(docker inspect -f '{{range (index .HostConfig.PortBindings "5432/tcp")}}{{.HostIp}}:{{.HostPort}}{{end}}' "$QA_NAME")"
[ "$bind" = "127.0.0.1:$QA_PORT" ] || die 'QA PostgreSQL no ligado solo a loopback'
volume="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Type}}:{{.Name}}{{end}}{{end}}' "$QA_NAME")"
[ "$volume" = "volume:$QA_VOL" ] || die 'volumen QA distinto'
echo 'QA_CONTAINER_ISOLATION=PASS'

echo '=== 3. ARCHIVO SECRETO (SOLO METADATOS) ==='
[ -f "$QA_SECRET" ] || die 'archivo secreto QA no existe'
[ "$(stat -c '%U:%a' "$QA_SECRET")" = root:600 ] || die 'archivo secreto QA sin proteccion root 600'
echo 'QA_SECRET_PERMISSIONS=PASS'

echo '=== 4. SERVICIOS PREEXISTENTES ==='
for svc in vinto-mvp-frontend vinto-mvp-backend vinto-web; do
  systemctl is-active --quiet "$svc" || die "servicio existente inactivo: $svc"
done
for container in vinto-mvp-postgres postgres-vinto; do
  [ "$(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null || true)" = true ] || die "contenedor existente inactivo: $container"
done
echo 'PILOT_TVC_RUNNING=PASS'

echo '=== 5. ESTADO DEL ESQUEMA QA (READ ONLY SQL) ==='
# PostgreSQL peer access is via Unix socket INSIDE the isolated container.
# PGOPTIONS enforces read-only transactions and timeouts; no secret is printed.
result="$(docker exec \
  -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=5000' \
  "$QA_NAME" psql -X -qAt -v ON_ERROR_STOP=1 -U "$QA_USER" -d "$QA_DB" \
  -c "
SELECT CASE WHEN
 current_database() = 'vinto_qa_offline'
 AND current_user = 'vinto_qa_bootstrap'
 AND NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'vinto_piloto')
 AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN
   ('vinto_app','vinto_migrator','vinto_reference','vinto_identity','vinto_test_admin'))
 AND NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname IN
   ('vinto_meta','vinto_master','vinto_auth','vinto_txn','vinto_config','vinto_audit'))
 AND to_regclass('vinto_meta.schema_migration') IS NULL
THEN 'PASS_EMPTY_QA' ELSE 'BLOCKED_NOT_EMPTY' END;
")" || die 'inspeccion SQL de QA fallida'
[ "$result" = PASS_EMPTY_QA ] || die "el esquema/roles QA no estan vacios: $result"
echo 'QA_SCHEMA_EMPTY=PASS'
echo 'QA_APPLICATION_ROLES_ABSENT=PASS'
echo 'QA_MIGRATION_HISTORY_ABSENT=PASS'

echo '=== RESULTADO ==='
echo 'OFF03D3_PREFLIGHT=PASS_READ_ONLY'
echo 'DB_ROLES_MIGRATION=NOT_AUTHORIZED'
echo 'QA_BACKEND_FRONTEND=NOT_DEPLOYED'
echo 'NO_DATABASE_WRITES=PASS'
