#!/usr/bin/env bash
# VINTO OFF-03D.7C6B-PRE -- QA identity-role candidate inspection.
# READ ONLY: no CREATE ROLE, GRANT, REVOKE, role passwords or file writes.
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
die() { echo "OFF03D7C6B_BLOCKED: $1" >&2; exit 1; }
usage(){ echo 'sudo -n bash scripts/off-03d7c6b-qa-identity-role-preflight.sh inspect'; }
[ "$#" -eq 1 ] || { usage >&2; exit 2; }
case "$1" in
  -h|--help|help) usage; exit 0 ;;
  inspect) ;;
  *) usage >&2; die 'read_only_inspect_only' ;;
esac
[ "$(id -u)" -eq 0 ] || die 'sudo_required'
for tool in bash docker git grep stat; do
  command -v "$tool" >/dev/null 2>&1 || die "missing_tool_$tool"
done

SOURCE=/srv/vinto-qa-offline/source
QA_SHA=7b9eb8c82a290d06e719ee4990c2020076bbd11b
D7C6A=/tmp/vinto-off03d7c6a-qa-identity-readiness.sh
D7C6A_BLOB=2433b96bf9bc9b0f4a46569e6f993b8299ec9e07
[ -f "$D7C6A" ] && [ ! -L "$D7C6A" ] &&
[ "$(git hash-object "$D7C6A")" = "$D7C6A_BLOB" ] &&
bash -n "$D7C6A" || die 'previous_auditor_missing_or_modified'

# This previous phase-valid audit checks the imported full catalog and
# immutable backup, SQL ACLs, the still-absent identity role, and pilot/TVC.
baseline="$(bash "$D7C6A" audit)" || die 'prior_identity_audit_failed'
for marker in \
  OFF03D7C6A_POSTIMPORT_CATALOG=PASS_READ_ONLY \
  OFF03D7C6A_PILOT_TVC=PASS_AT_AUDIT \
  OFF03D7C6A_POST_DDL_BACKUP=PASS_FILE_INTEGRITY \
  OFF03D7C6A_QA_USERS_AND_GRANTS=ZERO \
  OFF03D7C6A_IDENTITY_ROLE=ABSENT_NOT_PROVISIONED \
  OFF03D7C6A_APP_IDENTITY_DML=EXPOSED_LEGACY_BASELINE \
  OFF03D7C6A_CATALOG_WRITE_RESTRICTION_D3B1=PASS \
  OFF03D7C6A_IDENTITY_ROLE_CUT_D3B4=NOT_APPLIED \
  OFF03D7C6A_AUDIT=PASS_READ_ONLY_WITH_IDENTITY_GATES_OPEN \
  NO_DATABASE_WRITES=PASS; do
  printf '%s\n' "$baseline" | grep -Fxq "$marker" ||
    die 'prior_identity_gate_changed'
done
echo 'OFF03D7C6B_IMPORTED_QA_CATALOG_AND_BACKUP=PASS'
echo 'OFF03D7C6B_PILOT_TVC=PASS_AT_AUDIT'

# All four role lifecycle scripts are identical to vetted GitHub objects at
# protected checkout SHA, including the rollback that REVOKES but NOT DROPs.
[ -d "$SOURCE/.git" ] && [ ! -L "$SOURCE" ] &&
[ "$(git -C "$SOURCE" rev-parse HEAD)" = "$QA_SHA" ] &&
[ -z "$(git -C "$SOURCE" status --porcelain --untracked-files=all)" ] ||
  die 'protected_QA_checkout_changed'

for row in \
  'backend/roles/00c_create_identity_role.sql:04bc90dfeaf225d2c139587899fa46ce54913fe5' \
  'backend/roles/03c_d3b2_identity_role_grants.sql:6df9ac8c96d6cf85a00aecccc6631f8eddc7450b' \
  'backend/roles/rollback/ROLLBACK_D3B2.sql:0039f4c530b611873f4b60710bf42aec54edd2c7' \
  'backend/roles/03d_d3b4_cut_identity_dml.sql:bc76423ed56506d55bff1fc0e4d9b82ea96f872b'; do
  IFS=: read -r file blob <<< "$row"
  [ -f "$SOURCE/$file" ] && [ ! -L "$SOURCE/$file" ] &&
  [ "$(git hash-object "$SOURCE/$file")" = "$blob" ] &&
  [ "$(git -C "$SOURCE" rev-parse "HEAD:$file")" = "$blob" ] ||
    die 'role_procedure_or_rollback_SHA_mismatch'
done
echo 'OFF03D7C6B_IDENTITY_SQL_AND_ROLLBACK=PASS_PINNED'

# In this QA-only PostgreSQL 17 container roles are GLOBAL to that container.
# Query no user records, password hashes, tokens, role passwords, identifiers,
# grants for individuals, or operational rows.
SQL="$(cat <<'SQL'
SELECT CASE WHEN
 current_database() = 'vinto_qa_offline'
 AND current_user = 'vinto_qa_bootstrap'
 AND (SELECT count(*) FROM vinto_meta.schema_migration)=31
 AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vinto_qa_bootstrap' AND rolsuper)
 AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vinto_migrator'
              AND rolcanlogin AND NOT rolsuper AND NOT rolcreaterole)
 AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vinto_app'
              AND rolcanlogin AND NOT rolsuper AND NOT rolcreaterole)
 AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vinto_reference'
              AND rolcanlogin AND NOT rolsuper AND NOT rolcreaterole)
 AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vinto_identity')
 AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vinto_test_admin')
 AND NOT pg_has_role('vinto_app','vinto_migrator','MEMBER')
 AND NOT pg_has_role('vinto_app','vinto_reference','MEMBER')
 AND NOT pg_has_role('vinto_reference','vinto_migrator','MEMBER')
 AND (SELECT count(*) FROM vinto_master."user")=0
 AND (SELECT count(*) FROM vinto_master.user_profile)=0
 AND (SELECT count(*) FROM vinto_master.user_sector)=0
 AND (SELECT count(*) FROM vinto_master.user_machine_form_grant)=0
 AND (SELECT count(*) FROM vinto_auth.credential)=0
 AND (SELECT count(*) FROM vinto_auth.session)=0
 AND has_table_privilege('vinto_app', 'vinto_master."user"', 'INSERT')
 AND has_table_privilege('vinto_app', 'vinto_auth.credential', 'INSERT')
 AND NOT has_table_privilege('vinto_app','vinto_master.profile','INSERT')
 AND NOT has_database_privilege('public',current_database(),'CONNECT')
THEN 'PASS_PRE_ROLE_CREATION'
ELSE 'REVIEW_REQUIRED' END;
SQL
)"
state="$(docker exec -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=15000' \
  vinto-qa-postgres psql -X -qAt -v ON_ERROR_STOP=1 \
  -U vinto_qa_bootstrap -d vinto_qa_offline -c "$SQL" 2>/dev/null)" ||
  die 'pre_role_cluster_metadata_failed'
[ "$state" = PASS_PRE_ROLE_CREATION ] ||
  die 'identity_pre_role_baseline_drift'
echo 'OFF03D7C6B_IDENTITY_ROLE=ABSENT_READY_FOR_SEPARATE_APPROVAL'
echo 'OFF03D7C6B_QA_CLUSTER_ROLE_ISOLATION=PASS_READ_ONLY'
echo 'OFF03D7C6B_QA_USERS_GRANTS=ZERO'
echo 'OFF03D7C6B_ROLLBACK_D3B2=REVOKES_ONLY_ROLE_REMOVAL_OUT_OF_SCOPE'
echo 'OFF03D7C6B_IDENTITY_DML_CUT=NOT_APPLIED'
echo 'OFF03D7C6B_ROLE_CREATE_GRANTS=NOT_AUTHORIZED'
echo 'OFF03D7C6B_PREFLIGHT=PASS_READ_ONLY'
echo 'NO_DATABASE_WRITES=PASS'
