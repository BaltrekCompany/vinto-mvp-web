#!/usr/bin/env bash
# VINTO OFF-03D.4: QA-only PostgreSQL roles. No migrations, no frontend/backend.
# All calls target container vinto-qa-postgres, never host DB port 6544/6543.
set -Eeuo pipefail
set +x
export LC_ALL=C
umask 077

CONTAINER=vinto-qa-postgres
DB=vinto_qa_offline
BOOTSTRAP=vinto_qa_bootstrap
NET=vinto-qa-internal
VOL=vinto-qa-offline-pgdata
SECRET_DIR=/etc/vinto-qa
APP_PASS=/etc/vinto-qa/role-app.password
MIG_PASS=/etc/vinto-qa/role-migrator.password
REF_PASS=/etc/vinto-qa/role-reference.password
DOMAIN=qa-vinto-mvp.baltrekservices.com
SOURCE_COMMIT=0e68f40396ab1b506e52897c7aa17f2890aab77c
SQL00_BLOB=28a1ddbfa24297f730bf68092aa477d827e8fcdb
SQL01_BLOB=306c452381b12b2a194ee0173346372179c290d6

die() { echo "OFF03D4_BLOCKED: $*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "falta $1"; }
root() { [ "$(id -u)" -eq 0 ] || die 'se requiere root/sudo'; }
usage() {
  echo 'sudo bash scripts/off-03d4-qa-roles.sh preflight'
  echo 'sudo env CONFIRM_QA_ROLE_CREATE=YES bash scripts/off-03d4-qa-roles.sh install'
  echo 'sudo bash scripts/off-03d4-qa-roles.sh verify'
}
common() {
  root
  for x in docker curl getent awk sort grep git stat systemctl; do need "$x"; done
  docker info >/dev/null 2>&1 || die 'Docker no disponible'
  addr="$(getent ahostsv4 "$DOMAIN" | awk '{print $1}' | sort -u)"
  [ "$addr" = 51.79.65.225 ] || die 'DNS QA inesperado'
  marker="$(curl -fsS --noproxy '*' --proto '=https' --connect-timeout 5 \
    --max-time 15 "https://$DOMAIN/qa-ready")" || die 'HTTPS QA inaccesible'
  [ "$marker" = VINTO_QA_HTTPS_READY ] || die 'HTTPS QA no coincide'
  [ "$(docker inspect -f '{{.Config.Image}}' "$CONTAINER" 2>/dev/null || true)" = postgres:17 ] || die 'imagen QA inesperada'
  [ "$(docker inspect -f '{{.State.Running}}' "$CONTAINER")" = true ] || die 'QA detenido'
  [ "$(docker inspect -f '{{.State.Health.Status}}' "$CONTAINER")" = healthy ] || die 'QA unhealthy'
  [ "$(docker inspect -f '{{index .Config.Labels "org.baltrek.environment"}}' "$CONTAINER")" = qa ] || die 'label QA ausente'
  [ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$CONTAINER")" = "$NET" ] || die 'red QA incorrecta'
  bind="$(docker inspect -f '{{range (index .HostConfig.PortBindings "5432/tcp")}}{{.HostIp}}:{{.HostPort}}{{end}}' "$CONTAINER")"
  [ "$bind" = 127.0.0.1:6554 ] || die 'binding QA distinto'
  mount="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Type}}:{{.Name}}{{end}}{{end}}' "$CONTAINER")"
  [ "$mount" = "volume:$VOL" ] || die 'volumen QA distinto'
  [ "$(stat -c '%U:%a' "$SECRET_DIR")" = root:700 ] || die 'directorio secreto QA sin 0700'
  [ "$(stat -c '%U:%a' "$SECRET_DIR/postgres-bootstrap.password")" = root:600 ] || die 'bootstrap secreto sin 0600'
  for svc in vinto-mvp-frontend vinto-mvp-backend vinto-web; do
    systemctl is-active --quiet "$svc" || die "servicio existente inactivo: $svc"
  done
  for c in vinto-mvp-postgres postgres-vinto; do
    [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null || true)" = true ] || die "contenedor existente inactivo: $c"
  done
  echo 'QA_ORIGIN_DB_PILOT_TVC=PASS'
}
sql_query() {
  docker exec -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=5000' \
    "$CONTAINER" psql -X -qAt -v ON_ERROR_STOP=1 -U "$BOOTSTRAP" -d "$DB" -c "$1"
}
preflight() {
  common
  for file in "$APP_PASS" "$MIG_PASS" "$REF_PASS"; do
    [ ! -e "$file" ] || die 'secretos de roles QA ya existen; detener, no sobrescribir'
  done
  result="$(sql_query "
    SELECT CASE WHEN
      current_database() = 'vinto_qa_offline'
      AND current_user = 'vinto_qa_bootstrap'
      AND NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'vinto_piloto')
      AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN
        ('vinto_app','vinto_migrator','vinto_reference','vinto_identity','vinto_test_admin'))
      AND NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname IN
        ('vinto_master','vinto_config','vinto_txn','vinto_audit','vinto_auth','vinto_meta'))
    THEN 'PASS' ELSE 'BLOCKED' END;
  ")" || die 'query de preflight fallida'
  [ "$result" = PASS ] || die 'roles/esquemas previos detectados; no reintentar'
  echo 'QA_ROLES_ABSENT=PASS'
  echo 'QA_SCHEMA_EMPTY=PASS'
  echo 'OFF03D4_PREFLIGHT=PASS_READ_ONLY'
}
get_sql() {
  local temp="$1" name="$2" expected="$3"
  curl -fsSL --proto '=https' --max-redirs 3 --connect-timeout 5 --max-time 30 \
    "https://raw.githubusercontent.com/BaltrekCompany/vinto-mvp-web/$SOURCE_COMMIT/backend/roles/$name" \
    -o "$temp" || die "no se pudo obtener $name"
  [ "$(git hash-object "$temp")" = "$expected" ] || die "hash incorrecto de $name"
}
install_qa() {
  [ "$(printenv CONFIRM_QA_ROLE_CREATE 2>/dev/null || true)" = YES ] || die 'requiere CONFIRM_QA_ROLE_CREATE=YES'
  preflight
  need mktemp
  need openssl
  work="$(mktemp -d /root/vinto-qa-roles.XXXXXXXX)"
  trap 'rm -rf -- "$work"' EXIT
  get_sql "$work/00.sql" 00_create_roles.sql "$SQL00_BLOB"
  get_sql "$work/01.sql" 01_database_grants.sql "$SQL01_BLOB"
  echo 'QA_SQL_BLOBS=PASS'

  # New independent 256-bit secrets, not printed or passed in docker CLI args.
  openssl rand -hex 32 > "$APP_PASS"
  openssl rand -hex 32 > "$MIG_PASS"
  openssl rand -hex 32 > "$REF_PASS"
  chmod 0600 "$APP_PASS" "$MIG_PASS" "$REF_PASS"

  echo '=== CREANDO SOLO ROLES QA ==='
  {
    cat "$APP_PASS"
    cat "$MIG_PASS"
    cat "$REF_PASS"
    cat "$work/00.sql"
  } | docker exec -i "$CONTAINER" sh -ceu '
    IFS= read -r APP_PASSWORD
    IFS= read -r MIGRATOR_PASSWORD
    IFS= read -r REFERENCE_PASSWORD
    export APP_PASSWORD MIGRATOR_PASSWORD REFERENCE_PASSWORD
    exec psql -X -q -v ON_ERROR_STOP=1 -U vinto_qa_bootstrap -d vinto_qa_offline -f -
  ' || die 'fallo SQL00; conservar secretos/roles para diagnostico, NO reintentar'

  echo '=== CONCEDIENDO ACCESO SOLO A BASE QA ==='
  docker exec -i -e DBNAME="$DB" "$CONTAINER" \
    psql -X -q -v ON_ERROR_STOP=1 -U "$BOOTSTRAP" -d "$DB" -f - \
    < "$work/01.sql" || die 'fallo SQL01; NO reintentar automaticamente'

  verify
  echo 'OFF03D4_INSTALL=PASS_ROLES_ONLY'
  echo 'QA_MIGRATIONS=NOT_APPLIED'
}
verify() {
  common
  for file in "$APP_PASS" "$MIG_PASS" "$REF_PASS"; do
    [ "$(stat -c '%U:%a' "$file")" = root:600 ] || die 'secretos de roles no protegidos'
  done
  result="$(sql_query "
    SELECT CASE WHEN
      current_database() = 'vinto_qa_offline'
      AND (SELECT count(*) FROM pg_roles WHERE rolname IN
        ('vinto_app','vinto_migrator','vinto_reference')) = 3
      AND NOT EXISTS (SELECT 1 FROM pg_roles
        WHERE rolname IN ('vinto_app','vinto_migrator','vinto_reference')
          AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls OR rolinherit))
      AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ('vinto_test_admin','vinto_identity'))
      AND NOT has_database_privilege('public', 'vinto_qa_offline', 'CONNECT')
      AND has_database_privilege('vinto_app', 'vinto_qa_offline', 'CONNECT')
      AND has_database_privilege('vinto_migrator', 'vinto_qa_offline', 'CONNECT')
      AND has_database_privilege('vinto_reference', 'vinto_qa_offline', 'CONNECT')
      AND has_database_privilege('vinto_migrator', 'vinto_qa_offline', 'CREATE')
      AND NOT has_database_privilege('vinto_app', 'vinto_qa_offline', 'CREATE')
      AND NOT has_database_privilege('vinto_reference', 'vinto_qa_offline', 'CREATE')
      AND to_regclass('vinto_meta.schema_migration') IS NULL
    THEN 'PASS' ELSE 'BLOCKED' END;
  ")" || die 'consulta de validacion fallida'
  [ "$result" = PASS ] || die 'roles o privilegios QA no cumplen'
  echo 'QA_ROLE_PRIVILEGES=PASS'
  # Confirm real password login over localhost INSIDE QA container only.
  for role in vinto_app vinto_migrator vinto_reference; do
    case "$role" in
      vinto_app) file="$APP_PASS" ;;
      vinto_migrator) file="$MIG_PASS" ;;
      vinto_reference) file="$REF_PASS" ;;
    esac
    actual="$(cat "$file" | docker exec -i "$CONTAINER" sh -ceu '
      IFS= read -r PGPASSWORD
      export PGPASSWORD
      exec psql -X -qAt -v ON_ERROR_STOP=1 -h 127.0.0.1 \
        -U "$1" -d vinto_qa_offline -c "SELECT current_user"
    ' _ "$role")" || die "login QA no verificado: $role"
    [ "$actual" = "$role" ] || die "identidad login QA incorrecta: $role"
  done
  echo 'QA_ROLE_AUTH=PASS'
  echo 'QA_MIGRATION_HISTORY=EMPTY'
  echo 'OFF03D4_VERIFY=PASS_ROLES_ONLY'
}
case "$#" in 1) ;; *) usage >&2; exit 2 ;; esac
case "$1" in
  help|-h|--help) usage ;;
  preflight) preflight ;;
  install) install_qa ;;
  verify) verify ;;
  *) usage >&2; die 'operacion no soportada' ;;
esac
