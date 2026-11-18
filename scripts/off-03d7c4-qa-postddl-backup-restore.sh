#!/usr/bin/env bash
# VINTO OFF-03D.7C4 — QA POST-DDL backup + networkless PG17 restore.
# No SQL DML/DDL on real QA. Only confirmed mode creates files and
# a temporary PostgreSQL17 container with network=none; NO pilot/TVC changes.
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

die() { echo "OFF03D7C4_BLOCKED: $1" >&2; exit 1; }
usage() {
  echo 'sudo -n bash scripts/off-03d7c4-qa-postddl-backup-restore.sh inspect'
  echo 'sudo -n env CONFIRM_QA_POSTDDL_BACKUP=YES CONFIRM_QA_TARGET=vinto_qa_offline_6554 bash scripts/off-03d7c4-qa-postddl-backup-restore.sh backup-restore'
  echo 'sudo -n bash scripts/off-03d7c4-qa-postddl-backup-restore.sh verify'
}
[ "$#" -eq 1 ] || { usage >&2; exit 2; }
case "$1" in
  help|-h|--help) usage; exit 0 ;;
  inspect|backup-restore|verify) OP="$1" ;;
  *) usage >&2; die 'unsupported_operation' ;;
esac

[ "$(id -u)" -eq 0 ] || die 'sudo_required'
for c in bash docker git stat sha256sum awk cmp find grep mktemp df seq; do
  command -v "$c" >/dev/null 2>&1 || die "missing_prerequisite_$c"
done

QA=vinto-qa-postgres
DB=vinto_qa_offline
BOOT=vinto_qa_bootstrap
BACKUPS=/srv/vinto-qa-offline/backups
C3=/tmp/vinto-off03d7c3-qa-postddl-backup-preflight.sh
C3_BLOB=8baff8f5db57d0c0f7d460cf47c2b5884cb03f84
RESTORE=''
CREATED=0

# Only metadata: no credentials, business data, password hashes or row values.
FINGERPRINT_SQL="$(cat <<'SQL'
WITH roles AS (
 SELECT COALESCE(jsonb_agg(jsonb_build_object('name',rolname,'login',rolcanlogin,
 'super',rolsuper,'createdb',rolcreatedb,'createrole',rolcreaterole,
 'bypassrls',rolbypassrls,'inherit',rolinherit) ORDER BY rolname),'[]'::jsonb) AS value
 FROM pg_roles WHERE rolname IN
 ('vinto_qa_bootstrap','vinto_app','vinto_migrator','vinto_reference')
), schemas AS (
 SELECT COALESCE(jsonb_agg(jsonb_build_object('name',nspname,
 'owner',pg_get_userbyid(nspowner),
 'app_usage',has_schema_privilege('vinto_app',oid,'USAGE'),
 'reference_usage',has_schema_privilege('vinto_reference',oid,'USAGE'))
 ORDER BY nspname),'[]'::jsonb) AS value
 FROM pg_namespace WHERE nspname IN
 ('vinto_master','vinto_config','vinto_txn','vinto_audit','vinto_auth','vinto_meta')
), objects AS (
 SELECT COALESCE(jsonb_agg(jsonb_build_object('schema',n.nspname,
 'name',c.relname,'kind',c.relkind,'owner',pg_get_userbyid(c.relowner))
 ORDER BY n.nspname,c.relname,c.relkind),'[]'::jsonb) AS value
 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
 WHERE n.nspname IN
 ('vinto_master','vinto_config','vinto_txn','vinto_audit','vinto_auth','vinto_meta')
), functions AS (
 SELECT COALESCE(jsonb_agg(jsonb_build_object('schema',n.nspname,
 'name',p.proname,'args',pg_get_function_identity_arguments(p.oid),
 'owner',pg_get_userbyid(p.proowner)) ORDER BY n.nspname,p.proname,
 pg_get_function_identity_arguments(p.oid)),'[]'::jsonb) AS value
 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
 WHERE n.nspname IN
 ('vinto_master','vinto_config','vinto_txn','vinto_audit','vinto_auth','vinto_meta')
), migrations AS (
 SELECT COALESCE(jsonb_agg(jsonb_build_object('version',version,
 'filename',filename,'checksum',checksum) ORDER BY version),'[]'::jsonb) AS value
 FROM vinto_meta.schema_migration
)
SELECT jsonb_build_object(
 'database',current_database(),
 'owner',(SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database()),
 'acl',jsonb_build_object(
  'public_connect',has_database_privilege('public',current_database(),'CONNECT'),
  'app_connect',has_database_privilege('vinto_app',current_database(),'CONNECT'),
  'app_create',has_database_privilege('vinto_app',current_database(),'CREATE'),
  'migrator_create',has_database_privilege('vinto_migrator',current_database(),'CREATE'),
  'reference_create',has_database_privilege('vinto_reference',current_database(),'CREATE'),
  'app_profile_insert',has_table_privilege('vinto_app','vinto_master.profile','INSERT'),
  'app_machine_insert',has_table_privilege('vinto_app','vinto_master.machine','INSERT'),
  'app_sector_insert',has_table_privilege('vinto_app','vinto_master.sector','INSERT'),
  'reference_profile_insert',has_table_privilege('vinto_reference','vinto_master.profile','INSERT'),
  'app_auth_user_select',has_table_privilege('vinto_app','vinto_master.user','SELECT')),
 'roles',(SELECT value FROM roles),
 'schemas',(SELECT value FROM schemas),
 'objects',(SELECT value FROM objects),
 'functions',(SELECT value FROM functions),
 'migration_history',(SELECT value FROM migrations),
 'counts',jsonb_build_object(
  'migrations',(SELECT count(*) FROM vinto_meta.schema_migration),
  'users',(SELECT count(*) FROM vinto_master."user"),
  'grants',(SELECT count(*) FROM vinto_master.user_machine_form_grant),
  'forms',(SELECT count(*) FROM vinto_config.form),
  'versions',(SELECT count(*) FROM vinto_config.form_version),
  'batches',(SELECT count(*) FROM vinto_audit.import_batch)))::text;
SQL
)"

fingerprint() {
  local container="$1" user="$2"
  docker exec \
    -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=15000' \
    "$container" psql -X -qAt -v ON_ERROR_STOP=1 \
      -U "$user" -d "$DB" -c "$FINGERPRINT_SQL"
}
check_backup_root() {
  [ -d "$BACKUPS" ] && [ ! -L "$BACKUPS" ] &&
    [ "$(stat -c '%U:%a' "$BACKUPS")" = root:700 ] ||
    die 'backup_root_permissions'
}
count_backup() {
  find "$BACKUPS" -mindepth 1 -maxdepth 1 -name 'off03d7c4-*' |
    awk 'END {print NR+0}'
}
check_prerequisites() {
  check_backup_root
  [ -f "$C3" ] && [ ! -L "$C3" ] && [ "$(git hash-object "$C3")" = "$C3_BLOB" ] ||
    die 'D7C3_preflight_missing_or_modified'
  bash -n "$C3" || die 'D7C3_preflight_bad_syntax'
  local output
  output="$(bash "$C3" inspect)" || die 'D7C3_inspection_failed'
  printf '%s\n' "$output" | grep -Fxq 'OFF03D7C3_PREFLIGHT=PASS_READ_ONLY' ||
    die 'D7C3_inspection_not_pass'
  printf '%s\n' "$output" | grep -Fxq 'OFF03D7C3_POST_DDL_SOURCE=EMPTY_QA_31_MIGRATIONS' ||
    die 'D7C3_source_not_empty_postddl'
  [ "$(count_backup)" = 0 ] || die 'D7C4_backup_already_exists'
  [ "$(docker inspect -f '{{.State.Running}}' "$QA" 2>/dev/null || true)" = true ] ||
    die 'QA_not_running'
  local original
  original="$(fingerprint "$QA" "$BOOT")" || die 'QA_fingerprint_failed'
  [ -n "$original" ] || die 'QA_fingerprint_empty'
  echo 'OFF03D7C4_QA_SOURCE=PASS_POSTDDL_EMPTY'
  echo 'OFF03D7C4_D7C3_GATE=PASS_READ_ONLY'
  echo 'OFF03D7C4_NEW_BACKUP=NOT_CREATED'
}
select_backup() {
  check_backup_root
  [ "$(count_backup)" = 1 ] || die 'expected_exactly_one_D7C4_backup'
  BACKUP="$(find "$BACKUPS" -mindepth 1 -maxdepth 1 -type d -name 'off03d7c4-*' -print)"
  [ -d "$BACKUP" ] && [ ! -L "$BACKUP" ] &&
    [ "$(stat -c '%U:%a' "$BACKUP")" = root:700 ] ||
    die 'backup_subdir_permissions'
  for file in origin.json restored.json globals-no-passwords.sql vinto_qa_offline.dump SHA256SUMS RESTORE_VERIFIED; do
    [ -f "$BACKUP/$file" ] && [ ! -L "$BACKUP/$file" ] &&
      [ "$(stat -c '%U:%a' "$BACKUP/$file")" = root:600 ] ||
      die 'backup_file_missing_or_insecure'
  done
}
verify() {
  select_backup
  [ "$(cat "$BACKUP/RESTORE_VERIFIED")" = OFF03D7C4_RESTORE_PASS ] ||
    die 'restore_proof_missing'
  (cd "$BACKUP" && sha256sum -c SHA256SUMS >/dev/null) ||
    die 'backup_digest_mismatch'
  cmp -s "$BACKUP/origin.json" "$BACKUP/restored.json" ||
    die 'restored_metadata_mismatch'
  [ -s "$BACKUP/vinto_qa_offline.dump" ] &&
    [ -s "$BACKUP/globals-no-passwords.sql" ] || die 'dump_missing_or_empty'
  echo 'OFF03D7C4_BACKUP_INTEGRITY=PASS'
  echo 'OFF03D7C4_RESTORE_METADATA=PASS'
  echo 'OFF03D7C4_VERIFY=PASS_FILE_INTEGRITY'
}
cleanup() {
  if [ "$CREATED" = 1 ] && [ -n "$RESTORE" ]; then
    local label
    label="$(docker inspect -f '{{index .Config.Labels "org.baltrek.environment"}}' "$RESTORE" 2>/dev/null || true)"
    if [ "$label" = qa-postddl-restore-d7c4 ]; then
      docker rm -f "$RESTORE" >/dev/null 2>&1 || true
    fi
  fi
}
backup_restore() {
  [ "$(printenv CONFIRM_QA_POSTDDL_BACKUP 2>/dev/null || true)" = YES ] ||
    die 'CONFIRM_QA_POSTDDL_BACKUP_required'
  [ "$(printenv CONFIRM_QA_TARGET 2>/dev/null || true)" = vinto_qa_offline_6554 ] ||
    die 'CONFIRM_QA_TARGET_required'
  check_prerequisites

  BACKUP="$(mktemp -d "$BACKUPS/off03d7c4-XXXXXXXX")" ||
    die 'cannot_create_backup_directory'
  [ "$(stat -c '%U:%a' "$BACKUP")" = root:700 ] || die 'backup_subdir_insecure'
  fingerprint "$QA" "$BOOT" > "$BACKUP/origin.json" ||
    die 'QA_source_fingerprint_failed'

  docker exec \
    -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=120000' \
    "$QA" pg_dumpall --globals-only --no-role-passwords -U "$BOOT" -l "$DB" \
    > "$BACKUP/globals-no-passwords.sql" || die 'globals_dump_failed'
  docker exec \
    -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=120000' \
    "$QA" pg_dump -U "$BOOT" -d "$DB" --format=custom --create \
    > "$BACKUP/vinto_qa_offline.dump" || die 'QA_custom_dump_failed'
  [ -s "$BACKUP/globals-no-passwords.sql" ] &&
    [ -s "$BACKUP/vinto_qa_offline.dump" ] || die 'empty_backup'
  if grep -Eq '^[[:space:]]*CREATE[[:space:]]+TABLESPACE' "$BACKUP/globals-no-passwords.sql"; then
    die 'unsupported_tablespace'
  fi
  # Require no source drift during both dumps (QA not intentionally being written).
  fingerprint "$QA" "$BOOT" > "$BACKUP/after-dump.json" ||
    die 'QA_postdump_fingerprint_failed'
  cmp -s "$BACKUP/origin.json" "$BACKUP/after-dump.json" ||
    die 'QA_source_changed_during_backup'

  RESTORE="vinto-qa-postddl-restore-$$"
  [ -z "$(docker ps -aq --filter "name=^/$RESTORE$")" ] ||
    die 'restore_container_name_taken'
  trap cleanup EXIT
  docker run -d --rm --pull=never --name "$RESTORE" \
    --network none --label org.baltrek.environment=qa-postddl-restore-d7c4 \
    --tmpfs /var/lib/postgresql/data:rw,nosuid,size=536870912 \
    -e POSTGRES_USER=postgres -e POSTGRES_DB=postgres \
    -e POSTGRES_HOST_AUTH_METHOD=trust postgres:17 >/dev/null ||
    die 'networkless_postgres_start_failed'
  CREATED=1
  [ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$RESTORE")" = none ] ||
    die 'restore_network_mismatch'
  [ -z "$(docker port "$RESTORE" 2>/dev/null || true)" ] ||
    die 'restore_port_must_not_be_exposed'
  for n in $(seq 1 70); do
    if docker exec "$RESTORE" pg_isready -q -U postgres -d postgres >/dev/null 2>&1; then break; fi
    sleep 1
  done
  docker exec "$RESTORE" pg_isready -q -U postgres -d postgres ||
    die 'ephemeral_postgres_not_ready'
  docker exec -i "$RESTORE" psql -X -q -v ON_ERROR_STOP=1 \
    -U postgres -d postgres < "$BACKUP/globals-no-passwords.sql" ||
    die 'restore_globals_failed'
  docker exec -i "$RESTORE" pg_restore --exit-on-error --create \
    -U postgres -d postgres < "$BACKUP/vinto_qa_offline.dump" ||
    die 'restore_database_failed'
  fingerprint "$RESTORE" postgres > "$BACKUP/restored.json" ||
    die 'restored_metadata_query_failed'
  cmp -s "$BACKUP/origin.json" "$BACKUP/restored.json" ||
    die 'RESTORE_SCHEMA_ACL_HISTORY_MISMATCH'
  (cd "$BACKUP" && sha256sum origin.json after-dump.json restored.json \
    globals-no-passwords.sql vinto_qa_offline.dump > SHA256SUMS) ||
    die 'checksum_manifest_failed'
  printf 'OFF03D7C4_RESTORE_PASS\n' > "$BACKUP/RESTORE_VERIFIED"

  cleanup
  CREATED=0
  RESTORE=''
  verify
  echo 'OFF03D7C4_RESTORE_TEST=PASS_NETWORKLESS'
  echo 'OFF03D7C4_MIGRATIONS_31=PASS'
  echo 'OFF03D7C4_ROLE_PASSWORDS_EXCLUDED=PASS'
  echo 'OFF03D7C4_SOURCE_QA_UNCHANGED=PASS'
  echo 'OFF03D7C4_BACKUP_RESTORE=PASS_POSTDDL_QA_ONLY'
  echo 'NO_QA_DATABASE_WRITES=PASS'
}
case "$OP" in
  inspect)
    check_prerequisites
    echo 'OFF03D7C4_PREFLIGHT=PASS_READ_ONLY'
    echo 'NO_DATABASE_WRITES=PASS'
    ;;
  backup-restore) backup_restore ;;
  verify) verify ;;
esac
