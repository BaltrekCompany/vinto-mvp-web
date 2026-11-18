#!/usr/bin/env bash
# VINTO OFF-03D.7C3: POST-DDL backup readiness, READ ONLY.
# NO dump, RESTORE, files, DML, migrations or service modifications are authorized.
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
die() { echo "OFF03D7C3_BLOCKED: $1" >&2; exit 1; }
usage() { echo 'sudo -n bash scripts/off-03d7c3-qa-postddl-backup-preflight.sh inspect'; }
[ "$#" -eq 1 ] || { usage >&2; exit 2; }
case "$1" in
  --help|-h|help) usage; exit 0 ;;
  inspect) ;;
  *) usage >&2; die 'only_read_only_inspect_permitted' ;;
esac
[ "$(id -u)" -eq 0 ] || die 'sudo_required'
for cmd in bash docker git stat df awk find grep sha256sum; do
  command -v "$cmd" >/dev/null || die "missing_$cmd"
done
C3=/tmp/vinto-off03d6c3-qa-postmigration-audit.sh
C3_BLOB=ebb773f88ba6740ddf4fef53f1b76de541346a85
BACKUPS=/srv/vinto-qa-offline/backups
QA=vinto-qa-postgres
DB=vinto_qa_offline

[ -f "$C3" ] && [ ! -L "$C3" ] || die 'prior_C3_audit_missing'
[ "$(git hash-object "$C3")" = "$C3_BLOB" ] ||
  die 'prior_C3_audit_integrity_mismatch'
bash -n "$C3" || die 'prior_C3_syntax'
c3_result="$(bash "$C3" audit)" || die 'prior_postmigration_audit_failed'
printf '%s\n' "$c3_result" | grep -Fxq 'OFF03D6C3_AUDIT=PASS_READ_ONLY' ||
  die 'prior_C3_report_missing'
printf '%s\n' "$c3_result" | grep -Fxq 'OFF03D6C3_MIGRATION_HISTORY_31=PASS' ||
  die 'prior_C3_history_missing'
echo 'OFF03D7C3_POSTMIGRATION_AUDIT=PASS'
echo 'OFF03D7C3_MIGRATIONS_31=PASS'

[ -d "$BACKUPS" ] && [ ! -L "$BACKUPS" ] &&
  [ "$(stat -c '%U:%a' "$BACKUPS")" = root:700 ] ||
  die 'QA_backup_directory_insecure'
prior_count="$(find "$BACKUPS" -mindepth 1 -maxdepth 1 -type d \
  -name 'off03d6b2-*' | awk 'END {print NR+0}')"
[ "$prior_count" = 1 ] || die 'pre_DDL_backup_not_unique'
new_count="$(find "$BACKUPS" -mindepth 1 -maxdepth 1 \
  -name 'off03d7c3-*' | awk 'END {print NR+0}')"
[ "$new_count" = 0 ] || die 'post_DDL_backup_already_present_review_required'
echo 'OFF03D7C3_PRE_DDL_BACKUP_PRESERVED=PASS'
echo 'OFF03D7C3_POST_DDL_BACKUP=NOT_CREATED'

# Do not create a backup; require correct PostgreSQL 17 utilities in QA.
for program in pg_dump pg_dumpall pg_restore; do
  version="$(docker exec "$QA" "$program" --version 2>/dev/null)" ||
    die "missing_$program"
  case "$version" in *"PostgreSQL) 17."*) ;; *) die "wrong_backup_utility_major_version" ;; esac
done
docker image inspect postgres:17 >/dev/null 2>&1 ||
  die 'PG17_restore_image_not_cached'
echo 'OFF03D7C3_PG17_BACKUP_RESTORE_TOOLS=PASS'

free_bytes="$(df -P -B1 "$BACKUPS" | awk 'NR==2 {print $4}')"
case "$free_bytes" in
  ''|*[!0-9]*) die 'disk_measurement_failed' ;;
esac
[ "$free_bytes" -ge 2147483648 ] || die 'free_disk_below_2GiB'
echo 'OFF03D7C3_FREE_DISK_2GIB=PASS'

result="$(docker exec \
  -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=10000' \
  "$QA" psql -X -qAt -v ON_ERROR_STOP=1 -U vinto_qa_bootstrap \
  -d "$DB" -c "
SELECT CASE WHEN
  current_database()='vinto_qa_offline'
  AND current_user='vinto_qa_bootstrap'
  AND (SELECT count(*) FROM vinto_meta.schema_migration)=31
  AND (SELECT count(*) FROM vinto_master.\"user\")=0
  AND (SELECT count(*) FROM vinto_master.user_machine_form_grant)=0
  AND (SELECT count(*) FROM vinto_config.form_version)=0
  AND (SELECT count(*) FROM vinto_audit.import_batch)=0
THEN 'PASS_EMPTY_POST_DDL' ELSE 'REVIEW_REQUIRED' END;" 2>/dev/null)" ||
  die 'QA_baseline_metadata_read_failed'
[ "$result" = PASS_EMPTY_POST_DDL ] ||
  die 'QA_nonempty_or_changed_since_D7C'
echo 'OFF03D7C3_POST_DDL_SOURCE=EMPTY_QA_31_MIGRATIONS'
echo 'OFF03D7C3_BACKUP_RESTORE=NOT_AUTHORIZED'
echo 'OFF03D7C3_PREFLIGHT=PASS_READ_ONLY'
echo 'NO_DATABASE_WRITES=PASS'
