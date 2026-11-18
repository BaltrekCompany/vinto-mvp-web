#!/usr/bin/env bash
# VINTO OFF-03D.7C6A -- Identity/authorization baseline after QA reference import.
# Strictly READ ONLY. Never provision role, user, grant, password, or API service.
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

deny() { echo "OFF03D7C6A_BLOCKED: $1" >&2; exit 1; }
usage() { echo 'sudo -n bash scripts/off-03d7c6a-qa-identity-readiness.sh audit'; }
[ "$#" -eq 1 ] || { usage >&2; exit 2; }
case "$1" in
  -h|--help|help) usage; exit 0 ;;
  audit) ;;
  *) usage >&2; deny 'only_read_only_audit_permitted' ;;
esac

[ "$(id -u)" -eq 0 ] || deny 'sudo_required'
for cmd in bash docker git grep; do
  command -v "$cmd" >/dev/null 2>&1 || deny "missing_$cmd"
done

# The prior independent postimport auditor validates the official 26-form
# reference catalog, batch checksum, exactly eight P1/MP1/MP3 associations,
# 31 migrations, effective ACL, pilot/TVC and POST-DDL recovery integrity.
PREVIOUS=/tmp/vinto-off03d7c5a-qa-postimport-audit.sh
PREVIOUS_BLOB=34c560bc0e1b77381820d0e9d5b57caf1de4c67a
[ -f "$PREVIOUS" ] && [ ! -L "$PREVIOUS" ] &&
[ "$(git hash-object "$PREVIOUS")" = "$PREVIOUS_BLOB" ] &&
bash -n "$PREVIOUS" || deny 'prior_postimport_auditor_missing_or_modified'

report="$(bash "$PREVIOUS" audit)" || deny 'prior_postimport_audit_failed'
for expected in \
  OFF03D7C5A_MIGRATIONS_31_CHECKSUMS_ACL=PASS \
  OFF03D7C5A_PILOT_TVC_STATUS=PASS_AT_AUDIT \
  OFF03D7C5A_POST_DDL_BACKUP=PASS_FILE_INTEGRITY \
  OFF03D7C5A_QA_ISOLATION=PASS \
  OFF03D7C5A_FULL_REFERENCE_CATALOG=PASS_COUNTS \
  OFF03D7C5A_IMPORT_BATCH=PASS_CHECKSUM_COMPLETE \
  OFF03D7C5A_QUALITY_PUBLISHED=PASS_FOUR_VERSIONS \
  OFF03D7C5A_MP1_MP3=PASS_EIGHT_EXACT_PAIRS \
  OFF03D7C5A_USER_AND_GRANTS=ZERO \
  OFF03D7C5A_IDEMPOTENCE=PASS_READ_ONLY \
  OFF03D7C5A_AUDIT=PASS_READ_ONLY \
  NO_DATABASE_WRITES=PASS; do
  printf '%s\n' "$report" | grep -Fxq "$expected" ||
    deny 'prior_postimport_gate_not_pass'
done
echo 'OFF03D7C6A_POSTIMPORT_CATALOG=PASS_READ_ONLY'
echo 'OFF03D7C6A_PILOT_TVC=PASS_AT_AUDIT'
echo 'OFF03D7C6A_POST_DDL_BACKUP=PASS_FILE_INTEGRITY'

# No role password or any user record is selected. The existing QA bootstrap
# is used ONLY for this fixed, aggregate/read-only SQL metadata query.
# Do not inspect/change role secrets; creating vinto_identity requires
# an independent, explicitly authorized phase.
read -r -d '' SQL <<'SQL' || true
SELECT CASE WHEN
  current_database() = 'vinto_qa_offline'
  AND current_user = 'vinto_qa_bootstrap'
  AND (SELECT count(*) FROM vinto_meta.schema_migration) = 31
  AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_identity')
  AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_test_admin')
  AND (SELECT count(*) FROM vinto_master."user") = 0
  AND (SELECT count(*) FROM vinto_master.user_profile) = 0
  AND (SELECT count(*) FROM vinto_master.user_sector) = 0
  AND (SELECT count(*) FROM vinto_master.user_machine_form_grant) = 0
  AND (SELECT count(*) FROM vinto_auth.credential) = 0
  AND (SELECT count(*) FROM vinto_auth.session) = 0
  AND (SELECT count(*) FROM vinto_master.profile) = 5
  AND (SELECT count(*) FROM vinto_master.sector) = 3
  AND has_table_privilege('vinto_app', 'vinto_master."user"', 'INSERT')
  AND has_table_privilege('vinto_app', 'vinto_master.user_profile', 'INSERT')
  AND has_table_privilege('vinto_app', 'vinto_master.user_sector', 'INSERT')
  AND has_table_privilege('vinto_app', 'vinto_master.user_machine_form_grant', 'INSERT')
  AND has_table_privilege('vinto_app', 'vinto_auth.credential', 'INSERT')
  AND has_table_privilege('vinto_app', 'vinto_auth.session', 'INSERT')
  AND has_column_privilege('vinto_app', 'vinto_auth.credential', 'password_hash', 'SELECT')
  AND NOT has_table_privilege('vinto_app', 'vinto_master.profile', 'INSERT')
  AND NOT has_table_privilege('vinto_app', 'vinto_master.machine', 'INSERT')
  AND NOT has_table_privilege('vinto_app', 'vinto_master.sector', 'INSERT')
  AND NOT has_database_privilege('public', current_database(), 'CONNECT')
THEN 'ROLE_ABSENT_APP_IDENTITY_DML_PRESENT'
ELSE 'REVIEW_REQUIRED' END;
SQL

state="$(docker exec \
  -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=15000' \
  vinto-qa-postgres psql -X -qAt -v ON_ERROR_STOP=1 \
  -U vinto_qa_bootstrap -d vinto_qa_offline -c "$SQL" 2>/dev/null)" ||
  deny 'identity_ACL_metadata_query_failed'
[ "$state" = ROLE_ABSENT_APP_IDENTITY_DML_PRESENT ] ||
  deny 'identity_role_or_existing_ACL_changed'

# Evidence of CURRENT baseline, not approval to retain these broad rights.
echo 'OFF03D7C6A_QA_USERS_AND_GRANTS=ZERO'
echo 'OFF03D7C6A_IDENTITY_ROLE=ABSENT_NOT_PROVISIONED'
echo 'OFF03D7C6A_APP_IDENTITY_DML=EXPOSED_LEGACY_BASELINE'
echo 'OFF03D7C6A_CATALOG_WRITE_RESTRICTION_D3B1=PASS'
echo 'OFF03D7C6A_IDENTITY_ROLE_CUT_D3B4=NOT_APPLIED'
echo 'OFF03D7C6A_TEST_ACCOUNT_CREATE=BLOCKED_PENDING_ROLE_AND_APPROVAL'
echo 'OFF03D7C6A_GRANTS_AND_SIGNING=NOT_AUTHORIZED'
echo 'OFF03D7C6A_QA_WEB_WRITE_GUARD=NOT_VERIFIED_ON_DEPLOYED_API'
echo 'OFF03D7C6A_AUDIT=PASS_READ_ONLY_WITH_IDENTITY_GATES_OPEN'
echo 'NO_DATABASE_WRITES=PASS'
