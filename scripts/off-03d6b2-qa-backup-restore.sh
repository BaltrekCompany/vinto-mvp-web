#!/usr/bin/env bash
# OFF-03D.6B2: backup only QA and rehearse restore in networkless PG17.
# No DDL on real QA, no migrations, no pilot/TVC changes.
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
die() { echo "OFF03D6B2_BLOCKED: $*" >&2; exit 1; }
usage() {
  echo 'sudo bash scripts/off-03d6b2-qa-backup-restore.sh inspect'
  echo 'sudo env CONFIRM_QA_BACKUP_RESTORE=YES bash scripts/off-03d6b2-qa-backup-restore.sh backup-restore'
  echo 'sudo bash scripts/off-03d6b2-qa-backup-restore.sh verify'
}
[ "$#" -eq 1 ] || { usage >&2; exit 2; }
case "$1" in
  --help|-h|help) usage; exit 0 ;;
  inspect|backup-restore|verify) OP="$1" ;;
  *) usage >&2; die 'operacion no soportada' ;;
esac
[ "$(id -u)" -eq 0 ] || die 'se requiere sudo'
for cmd in bash docker git sha256sum stat mktemp cmp find awk grep; do
  command -v "$cmd" >/dev/null 2>&1 || die "falta $cmd"
done

QA=vinto-qa-postgres
DB=vinto_qa_offline
BOOT=vinto_qa_bootstrap
ROOT=/srv/vinto-qa-offline
BACKUPS=/srv/vinto-qa-offline/backups
B1=/tmp/vinto-off03d6b1-qa-checkout-venv.sh
B1_BLOB=d398cedb367c151b3bb0a916c1d59f610a441703

# Stable read-only signature of required roles, DB ACL and absence of app schemas.
# Does not extract password hashes, user rows, or business contents.
SQL="$(cat <<'SQLTEXT'
SELECT jsonb_build_object(
 'db',current_database(),
 'owner',(SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()),
 'roles',(SELECT jsonb_agg(jsonb_build_object(
    'name',rolname,'login',rolcanlogin,'superuser',rolsuper,
    'createdb',rolcreatedb,'createrole',rolcreaterole,
    'bypassrls',rolbypassrls,'inherit',rolinherit,'config',rolconfig
 ) ORDER BY rolname) FROM pg_roles WHERE rolname IN
 ('vinto_qa_bootstrap','vinto_app','vinto_migrator','vinto_reference')),
 'acl',jsonb_build_object(
  'public_connect',has_database_privilege('public',current_database(),'CONNECT'),
  'app_connect',has_database_privilege('vinto_app',current_database(),'CONNECT'),
  'migrator_connect',has_database_privilege('vinto_migrator',current_database(),'CONNECT'),
  'reference_connect',has_database_privilege('vinto_reference',current_database(),'CONNECT'),
  'migrator_create',has_database_privilege('vinto_migrator',current_database(),'CREATE'),
  'app_create',has_database_privilege('vinto_app',current_database(),'CREATE'),
  'reference_create',has_database_privilege('vinto_reference',current_database(),'CREATE')
 ),
 'vinto_schemas',(SELECT count(*) FROM pg_namespace WHERE nspname IN
  ('vinto_master','vinto_config','vinto_txn','vinto_audit','vinto_auth','vinto_meta')),
 'migration_history',to_regclass('vinto_meta.schema_migration') IS NOT NULL
)::text;
SQLTEXT
)"
fingerprint() {
  docker exec -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=10000' \
    "$1" psql -X -qAt -v ON_ERROR_STOP=1 -U "$2" -d "$DB" -c "$SQL"
}
check_b1() {
  [ -f "$B1" ] && [ ! -L "$B1" ] || die 'script B1 ausente'
  [ "$(git hash-object "$B1")" = "$B1_BLOB" ] || die 'script B1 alterado'
  bash "$B1" verify || die 'gate B1 bloqueado'
}
check_origin() {
  [ -d "$ROOT" ] && [ ! -L "$ROOT" ] && [ "$(stat -c '%U:%a' "$ROOT")" = root:700 ] ||
    die 'raiz QA insegura'
  [ -d "$BACKUPS" ] && [ ! -L "$BACKUPS" ] &&
    [ "$(stat -c '%U:%a' "$BACKUPS")" = root:700 ] || die 'backups QA inseguros'
  [ "$(docker inspect -f '{{.Config.Image}}' "$QA" 2>/dev/null || true)" = postgres:17 ] ||
    die 'imagen origen inesperada'
  [ "$(docker inspect -f '{{.State.Running}}' "$QA")" = true ] ||
    die 'origen QA detenido'
  [ "$(docker inspect -f '{{index .Config.Labels "org.baltrek.environment"}}' "$QA")" = qa ] ||
    die 'label QA incorrecta'
  [ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$QA")" = vinto-qa-internal ] ||
    die 'red QA incorrecta'
  local binding
  binding="$(docker inspect -f '{{range (index .HostConfig.PortBindings "5432/tcp")}}{{.HostIp}}:{{.HostPort}}{{end}}' "$QA")"
  [ "$binding" = 127.0.0.1:6554 ] || die 'puerto QA incorrecto'
}
count_backup() {
  find "$BACKUPS" -mindepth 1 -maxdepth 1 -name 'off03d6b2-*' -print | awk 'END {print NR+0}'
}
inspect() {
  check_b1
  check_origin
  [ "$(count_backup)" = 0 ] || die 'backup D6B2 previo; detener y revisar'
  for program in pg_dump pg_dumpall pg_restore; do
    docker exec "$QA" "$program" --version >/dev/null ||
      die "falta $program en QA"
  done
  echo 'OFF03D6B2_ORIGIN_QA=PASS'
  echo 'OFF03D6B2_BACKUP_DIR_EMPTY=PASS'
  echo 'OFF03D6B2_PREFLIGHT=PASS_READ_ONLY'
  echo 'NO_DATABASE_WRITES=PASS'
}
select_backup() {
  [ "$(count_backup)" = 1 ] || die 'se requiere exactamente un backup D6B2'
  BACKUP="$(find "$BACKUPS" -mindepth 1 -maxdepth 1 -type d -name 'off03d6b2-*' -print)"
  [ -d "$BACKUP" ] && [ ! -L "$BACKUP" ] &&
    [ "$(stat -c '%U:%a' "$BACKUP")" = root:700 ] ||
    die 'directorio backup inseguro'
}
verify() {
  check_b1
  check_origin
  select_backup
  [ -f "$BACKUP/RESTORE_VERIFIED" ] &&
    [ "$(cat "$BACKUP/RESTORE_VERIFIED")" = OFF03D6B2_RESTORE_PASS ] ||
    die 'falta evidencia de restauracion'
  ( cd "$BACKUP" && sha256sum -c SHA256SUMS >/dev/null ) ||
    die 'checksums del respaldo no coinciden'
  cmp -s "$BACKUP/origin.json" "$BACKUP/restored.json" ||
    die 'deriva de roles/esquemas/ACL en restauracion'
  [ "$(fingerprint "$QA" "$BOOT")" = "$(cat "$BACKUP/origin.json")" ] ||
    die 'QA original derivo desde respaldo'
  echo 'OFF03D6B2_BACKUP_INTEGRITY=PASS'
  echo 'OFF03D6B2_RESTORE_ACL=PASS'
  echo 'OFF03D6B2_SOURCE_QA_UNCHANGED=PASS'
  echo 'OFF03D6B2_MIGRATIONS=NOT_STARTED'
  echo 'OFF03D6B2_VERIFY=PASS_NO_QA_DDL'
}
RESTORE=''
CREATED=0
cleanup() {
  if [ "$CREATED" = 1 ] && [ -n "$RESTORE" ]; then
    local label
    label="$(docker inspect -f '{{index .Config.Labels "org.baltrek.environment"}}' "$RESTORE" 2>/dev/null || true)"
    [ "$label" != qa-offline-restore ] || docker rm -f "$RESTORE" >/dev/null 2>&1 || true
  fi
}
backup_restore() {
  [ "$(printenv CONFIRM_QA_BACKUP_RESTORE 2>/dev/null || true)" = YES ] ||
    die 'requiere CONFIRM_QA_BACKUP_RESTORE=YES'
  inspect
  BACKUP="$(mktemp -d "$BACKUPS/off03d6b2-XXXXXXXX")" ||
    die 'no se pudo reservar carpeta backup'
  [ "$(stat -c '%U:%a' "$BACKUP")" = root:700 ] || die 'permisos backup inseguro'
  fingerprint "$QA" "$BOOT" > "$BACKUP/origin.json" ||
    die 'fallo metadata QA'
  docker exec -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=60000' \
    "$QA" pg_dumpall --globals-only --no-role-passwords -U "$BOOT" -l "$DB" \
    > "$BACKUP/globals-no-passwords.sql" ||
    die 'fallo respaldo de roles'
  grep -Eq '^[[:space:]]*CREATE[[:space:]]+TABLESPACE' "$BACKUP/globals-no-passwords.sql" &&
    die 'tablespaces no soportados para restauracion aislada'
  docker exec -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=60000' \
    "$QA" pg_dump -U "$BOOT" -d "$DB" --format=custom --create \
    > "$BACKUP/vinto_qa_offline.dump" ||
    die 'fallo dump QA'
  [ -s "$BACKUP/globals-no-passwords.sql" ] &&
    [ -s "$BACKUP/vinto_qa_offline.dump" ] || die 'backup vacio'

  RESTORE="vinto-qa-restore-$$"
  [ -z "$(docker ps -aq --filter "name=^/$RESTORE$")" ] ||
    die 'nombre restauracion ocupado'
  trap cleanup EXIT
  docker run -d --rm --pull=never --name "$RESTORE" \
    --network none --label org.baltrek.environment=qa-offline-restore \
    --tmpfs /var/lib/postgresql/data:rw,nosuid,size=536870912 \
    -e POSTGRES_USER=postgres -e POSTGRES_DB=postgres \
    -e POSTGRES_HOST_AUTH_METHOD=trust postgres:17 >/dev/null ||
    die 'fallo levantar PG17 efimero'
  CREATED=1
  [ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$RESTORE")" = none ] ||
    die 'restauracion tiene red'
  [ "$(docker inspect -f '{{json .NetworkSettings.Ports}}' "$RESTORE" | grep -c HostPort || true)" = 0 ] ||
    die 'restauracion tiene puerto expuesto'
  for n in $(seq 1 60); do
    if docker exec "$RESTORE" pg_isready -q -U postgres -d postgres >/dev/null 2>&1; then break; fi
    sleep 1
  done
  docker exec "$RESTORE" pg_isready -q -U postgres -d postgres ||
    die 'PG17 efimero no inicia'
  docker exec -i "$RESTORE" psql -X -q -v ON_ERROR_STOP=1 -U postgres -d postgres \
    < "$BACKUP/globals-no-passwords.sql" ||
    die 'restauracion globals fallo'
  docker exec -i "$RESTORE" pg_restore --exit-on-error --create \
    -U postgres -d postgres < "$BACKUP/vinto_qa_offline.dump" ||
    die 'restauracion QA custom dump fallo'
  fingerprint "$RESTORE" postgres > "$BACKUP/restored.json" ||
    die 'auditoria restaurada fallo'
  cmp -s "$BACKUP/origin.json" "$BACKUP/restored.json" ||
    die 'ACL/roles/esquema de restore difieren'
  ( cd "$BACKUP" &&
    sha256sum origin.json restored.json globals-no-passwords.sql \
      vinto_qa_offline.dump > SHA256SUMS ) ||
    die 'no se pudo registrar SHA256'
  printf 'OFF03D6B2_RESTORE_PASS\n' > "$BACKUP/RESTORE_VERIFIED"
  echo 'OFF03D6B2_RESTORE_TEST=PASS_NETWORKLESS'
  echo 'OFF03D6B2_ROLE_PASSWORDS_EXCLUDED=PASS'
  cleanup
  CREATED=0
  RESTORE=''
  verify
  echo 'OFF03D6B2_BACKUP_RESTORE=PASS'
  echo 'NO_QA_DATABASE_WRITES=PASS'
}
case "$OP" in
  inspect) inspect ;;
  backup-restore) backup_restore ;;
  verify) verify ;;
esac
