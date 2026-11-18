#!/usr/bin/env bash
# VINTO OFF-03D.7C6C-PRE -- identity DML cut read-only readiness.
# Post-role phase. Does NOT run 03d/ROLLBACK or touch API/Nginx.
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

deny(){ echo "OFF03D7C6C_BLOCKED: $1" >&2; exit 1; }
usage(){ echo 'sudo -n bash scripts/off-03d7c6c-qa-precut-readonly.sh audit'; }
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
SOURCE=/srv/vinto-qa-offline/source
PIN=7b9eb8c82a290d06e719ee4990c2020076bbd11b
QA=vinto-qa-postgres
DB=vinto_qa_offline
POSTROLE=/tmp/vinto-off03d7c6b-qa-identity-role-install.sh
POSTROLE_BLOB=93a222224a99b7c0e1eaa3bcd2575681efb26af0

[ -f "$POSTROLE" ] && [ ! -L "$POSTROLE" ] &&
[ "$(git hash-object "$POSTROLE")" = "$POSTROLE_BLOB" ] &&
bash -n "$POSTROLE" || deny 'pinned_postrole_verifier_unavailable'

# After creating vinto_identity, NEVER run PRE-ROLE D7C6A/B inspect.
# The D7C6B verify path does not require the role to be absent.
post="$(bash "$POSTROLE" verify)" ||
 deny 'D7C6B_postrole_verify_not_pass'
for expected in \
  OFF03D7C6B_ROLE_FLAGS=PASS_UNPRIVILEGED_LOGIN \
  OFF03D7C6B_ROLE_CONNECT=PASS_QA_DB_OWNER \
  OFF03D7C6B_ROLE_GRANTS=PASS_D3B2_ADDITIVE_ONLY \
  OFF03D7C6B_ROLE_AUTH=PASS_READ_ONLY_QA_LOOPBACK \
  OFF03D7C6B_QA_CATALOG_AND_MIGRATIONS=PASS_UNCHANGED \
  OFF03D7C6B_QA_USERS_AND_GRANTS=ZERO \
  OFF03D7C6B_POSTVERIFY=PASS_ROLE_AND_GRANTS_QA_ONLY \
  OFF03D7C6B_DML_CUT=NOT_APPLIED \
  NO_DATABASE_WRITES=PASS; do
 printf '%s\n' "$post" | grep -Fxq "$expected" ||
   deny 'D7C6B_postrole_marker_missing'
done
echo 'OFF03D7C6C_POSTROLE=PASS_READ_ONLY'
echo 'OFF03D7C6C_ROLE_AND_CATALOG=PASS_READ_ONLY'

[ -d "$SOURCE/.git" ] && [ ! -L "$SOURCE" ] &&
[ "$(git -C "$SOURCE" rev-parse HEAD)" = "$PIN" ] &&
[ -z "$(git -C "$SOURCE" status --porcelain --untracked-files=all)" ] ||
 deny 'QA_protected_checkout_changed'

for row in \
 'backend/roles/03d_d3b4_cut_identity_dml.sql:bc76423ed56506d55bff1fc0e4d9b82ea96f872b' \
 'backend/roles/rollback/ROLLBACK_D3B4.sql:97041aa0c90b738d4f9be7fa71185b11f2240a9e'; do
 IFS=: read -r path expected <<< "$row"
 [ -f "$SOURCE/$path" ] && [ ! -L "$SOURCE/$path" ] &&
 [ "$(git hash-object "$SOURCE/$path")" = "$expected" ] &&
 [ "$(git -C "$SOURCE" rev-parse "HEAD:$path")" = "$expected" ] ||
  deny 'official_cut_or_rollback_changed'
done
echo 'OFF03D7C6C_CUT_AND_ROLLBACK=PASS_PINNED'

# Fixed, aggregate ACL inspection. No actor data, credential hashes, rows,
# secrets or URLs are retrieved. Neither the cut nor its rollback is applied.
SQL="$(cat <<'SQL'
SELECT CASE WHEN
 current_database() = 'vinto_qa_offline'
 AND current_user = 'vinto_qa_bootstrap'
 AND (SELECT count(*) FROM vinto_meta.schema_migration)=31
 AND (SELECT count(*) FROM vinto_master."user")=0
 AND (SELECT count(*) FROM vinto_master.user_profile)=0
 AND (SELECT count(*) FROM vinto_master.user_sector)=0
 AND (SELECT count(*) FROM vinto_master.user_machine_form_grant)=0
 AND (SELECT count(*) FROM vinto_auth.credential)=0
 AND (SELECT count(*) FROM vinto_auth.session)=0
 AND (SELECT count(*) FROM vinto_master.article)=315
 AND (SELECT count(*) FROM vinto_config.form)=26
 AND (SELECT count(*) FROM vinto_config.form_version WHERE status='published')=26
 AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vinto_app'
   AND rolcanlogin AND NOT rolsuper AND NOT rolcreaterole AND NOT rolcreatedb
   AND NOT rolbypassrls AND NOT rolreplication)
 AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vinto_identity'
   AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
   AND NOT rolbypassrls AND NOT rolreplication)
 AND NOT EXISTS (SELECT 1 FROM pg_auth_members
   WHERE member IN ('vinto_app'::regrole,'vinto_identity'::regrole))
 AND NOT has_database_privilege('public',current_database(),'CONNECT')
 AND has_database_privilege('vinto_identity',current_database(),'CONNECT')
 AND NOT has_database_privilege('vinto_identity',current_database(),'CREATE')
 AND has_table_privilege('vinto_identity','vinto_master."user"','INSERT')
 AND has_table_privilege('vinto_identity','vinto_master.user_profile','INSERT')
 AND has_table_privilege('vinto_identity','vinto_master.user_sector','DELETE')
 AND has_table_privilege('vinto_identity','vinto_master.user_machine_form_grant','UPDATE')
 AND has_table_privilege('vinto_identity','vinto_auth.credential','SELECT')
 AND has_table_privilege('vinto_identity','vinto_auth.credential','INSERT')
 AND has_table_privilege('vinto_identity','vinto_auth.session','UPDATE')
 AND has_table_privilege('vinto_identity','vinto_auth.auth_event','INSERT')
 AND has_table_privilege('vinto_identity','vinto_audit.audit_event','INSERT')
 AND has_column_privilege('vinto_identity','vinto_master.profile','active','UPDATE')
 AND has_table_privilege('vinto_app','vinto_master."user"','INSERT')
 AND has_table_privilege('vinto_app','vinto_master.user_profile','INSERT')
 AND has_table_privilege('vinto_app','vinto_auth.credential','INSERT')
 AND has_table_privilege('vinto_app','vinto_auth.credential','SELECT')
 AND has_column_privilege('vinto_app','vinto_auth.credential','password_hash','SELECT')
 AND has_table_privilege('vinto_app','vinto_auth.session','UPDATE')
 AND has_table_privilege('vinto_app','vinto_audit.audit_event','INSERT')
 AND NOT has_table_privilege('vinto_app','vinto_master.profile','INSERT')
 AND NOT has_table_privilege('vinto_app','vinto_master.machine','INSERT')
 AND NOT has_table_privilege('vinto_app','vinto_master.sector','INSERT')
THEN 'PASS_PRECUT_DB_ROLES_READY'
ELSE 'REVIEW_REQUIRED' END;
SQL
)"
status="$(docker exec \
 -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=15000' \
 "$QA" psql -X -qAt -v ON_ERROR_STOP=1 \
  -U vinto_qa_bootstrap -d "$DB" -c "$SQL" 2>/dev/null)" ||
 deny 'QA_precut_metadata_unavailable'
[ "$status" = PASS_PRECUT_DB_ROLES_READY ] ||
 deny 'QA_precut_DML_or_role_baseline_changed'

echo 'OFF03D7C6C_TWO_ROLES_DB_ACL=PASS_PRECUT_READ_ONLY'
echo 'OFF03D7C6C_APP_IDENTITY_DML=LEGACY_PRESENT_NOT_YET_CUT'
echo 'OFF03D7C6C_ACTIVE_API_IDENTITY_DATABASE_URL=NOT_VERIFIED'
echo 'OFF03D7C6C_ACTIVE_API_PG_PRIVILEGE_MODE=NOT_VERIFIED'
echo 'OFF03D7C6C_ACTIVE_API_QA_WRITE_GUARD=NOT_VERIFIED'
echo 'OFF03D7C6C_D3B3_TWO_ROLE_FUNCTIONAL_GATE=NOT_EXECUTED_ON_QA'
echo 'OFF03D7C6C_D3B4_SQL_CUT=NOT_AUTHORIZED'
echo 'OFF03D7C6C_USER_AND_MACHINE_GRANTS=ZERO'
echo 'OFF03D7C6C_AUDIT=PASS_READ_ONLY_WITH_FUNCTIONAL_GATES_OPEN'
echo 'NO_DATABASE_WRITES=PASS'
