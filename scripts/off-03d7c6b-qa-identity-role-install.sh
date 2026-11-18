#!/usr/bin/env bash
# VINTO OFF-03D.7C6B INSTALL - isolated QA role only.
# inspect: read only (PRE-ROLE). verify: read only (POST-ROLE).
# apply: creates one QA role, grants QA database CONNECT and official D3B2.
# No backups: operator waived a fresh postimport snapshot; D7C4 stays historic.
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

die(){ echo "OFF03D7C6B_INSTALL_BLOCKED: $1" >&2; exit 1; }
usage(){
  echo 'sudo -n bash scripts/off-03d7c6b-qa-identity-role-install.sh inspect'
  echo 'sudo -n bash scripts/off-03d7c6b-qa-identity-role-install.sh verify'
  echo 'sudo -n env CONFIRM_QA_IDENTITY_ROLE_INSTALL=YES CONFIRM_QA_TARGET=vinto_qa_offline_6554 ACK_NO_NEW_BACKUP=YES bash scripts/off-03d7c6b-qa-identity-role-install.sh apply'
}
[ "$#" -eq 1 ] || { usage >&2; exit 2; }
case "$1" in
 -h|--help|help) usage; exit 0 ;;
 inspect|verify|apply) OP="$1" ;;
 *) usage >&2; die 'unsupported_operation' ;;
esac
[ "$(id -u)" -eq 0 ] || die 'sudo_required'
for tool in docker git bash stat grep; do
 command -v "$tool" >/dev/null 2>&1 || die "tool_missing_$tool"
done

QA=vinto-qa-postgres
DB=vinto_qa_offline
SOURCE=/srv/vinto-qa-offline/source
PIN=7b9eb8c82a290d06e719ee4990c2020076bbd11b
PRE=/tmp/vinto-off03d7c6b-qa-identity-role-preflight.sh
PRE_BLOB=abfb2e15e99cd207693a309c5d8d7314ae71f467
ROOT=/etc/vinto-qa
IDENTITY_SECRET=$ROOT/role-identity.password
MIGRATOR_SECRET=$ROOT/role-migrator.password
PYTHON=/srv/vinto-qa-offline/venv/bin/python
ROLE_SQL=$SOURCE/backend/roles/00c_create_identity_role.sql
GRANTS_SQL=$SOURCE/backend/roles/03c_d3b2_identity_role_grants.sql

check_qa(){
 [ "$(docker inspect -f '{{.Config.Image}}' "$QA" 2>/dev/null || true)" = postgres:17 ] ||
   die 'not_expected_PG17_image'
 [ "$(docker inspect -f '{{.State.Running}}' "$QA" 2>/dev/null || true)" = true ] ||
   die 'QA_not_running'
 [ "$(docker inspect -f '{{index .Config.Labels "org.baltrek.environment"}}' "$QA" 2>/dev/null || true)" = qa ] ||
   die 'QA_label_mismatch'
 [ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$QA" 2>/dev/null || true)" = vinto-qa-internal ] ||
   die 'QA_network_mismatch'
 [ "$(docker inspect -f '{{range (index .HostConfig.PortBindings "5432/tcp")}}{{.HostIp}}:{{.HostPort}}{{end}}' "$QA" 2>/dev/null || true)" = 127.0.0.1:6554 ] ||
   die 'QA_binding_mismatch'
 [ -d "$SOURCE/.git" ] && [ ! -L "$SOURCE" ] &&
 [ "$(git -C "$SOURCE" rev-parse HEAD)" = "$PIN" ] &&
 [ -z "$(git -C "$SOURCE" status --porcelain --untracked-files=all)" ] ||
   die 'QA_source_changed'
 for row in \
  'backend/roles/00c_create_identity_role.sql:04bc90dfeaf225d2c139587899fa46ce54913fe5' \
  'backend/roles/03c_d3b2_identity_role_grants.sql:6df9ac8c96d6cf85a00aecccc6631f8eddc7450b' \
  'backend/roles/rollback/ROLLBACK_D3B2.sql:0039f4c530b611873f4b60710bf42aec54edd2c7'; do
  IFS=: read -r path expected <<< "$row"
  [ -f "$SOURCE/$path" ] && [ ! -L "$SOURCE/$path" ] &&
  [ "$(git hash-object "$SOURCE/$path")" = "$expected" ] &&
  [ "$(git -C "$SOURCE" rev-parse "HEAD:$path")" = "$expected" ] ||
    die 'pinned_role_SQL_changed'
 done
 [ -d "$ROOT" ] && [ ! -L "$ROOT" ] &&
 [ "$(stat -c '%U:%a' "$ROOT")" = root:700 ] &&
 [ -x "$PYTHON" ] || die 'protected_QA_environment_invalid'
}
check_pre(){
 [ -f "$PRE" ] && [ ! -L "$PRE" ] &&
 [ "$(git hash-object "$PRE")" = "$PRE_BLOB" ] &&
 bash -n "$PRE" || die 'pinned_D7C6B_PRE_missing_or_changed'
 local pre
 pre="$(bash "$PRE" inspect)" || die 'D7C6B_PRE_not_PASS'
 for expected in \
   OFF03D7C6B_IMPORTED_QA_CATALOG_AND_BACKUP=PASS \
   OFF03D7C6B_PILOT_TVC=PASS_AT_AUDIT \
   OFF03D7C6B_IDENTITY_SQL_AND_ROLLBACK=PASS_PINNED \
   OFF03D7C6B_IDENTITY_ROLE=ABSENT_READY_FOR_SEPARATE_APPROVAL \
   OFF03D7C6B_QA_CLUSTER_ROLE_ISOLATION=PASS_READ_ONLY \
   OFF03D7C6B_QA_USERS_GRANTS=ZERO \
   OFF03D7C6B_ROLE_CREATE_GRANTS=NOT_AUTHORIZED \
   OFF03D7C6B_PREFLIGHT=PASS_READ_ONLY \
   NO_DATABASE_WRITES=PASS; do
    printf '%s\n' "$pre" | grep -Fxq "$expected" ||
      die 'D7C6B_PRE_gate_missing'
 done
 echo 'OFF03D7C6B_INSTALL_PREFLIGHT=PASS_READ_ONLY'
 echo 'OFF03D7C6B_BACKUP_WAIVER=ACKNOWLEDGED_NO_NEW_BACKUP'
}
query_admin(){
  docker exec \
   -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=15000' \
   "$QA" psql -X -qAt -v ON_ERROR_STOP=1 \
     -U vinto_qa_bootstrap -d "$DB" -c "$1" 2>/dev/null ||
    die 'QA_admin_metadata_failed'
}
check_secret(){
 local path="$1"
 [ -f "$path" ] && [ ! -L "$path" ] &&
 [ "$(stat -c '%U:%a' "$path")" = root:600 ] ||
    die 'QA_secret_missing_or_unprotected'
 local secret
 secret="$(cat "$path")"
 [[ "$secret" =~ ^[0-9a-f]{64}$ ]] ||
    die 'QA_secret_invalid_format'
 unset secret
}
role_metadata_sql="$(cat <<'SQL'
SELECT CASE WHEN
 current_database() = 'vinto_qa_offline'
 AND current_user = 'vinto_qa_bootstrap'
 AND (SELECT count(*) FROM vinto_meta.schema_migration)=31
 AND (SELECT count(*) FROM vinto_master."user")=0
 AND (SELECT count(*) FROM vinto_master.user_machine_form_grant)=0
 AND (SELECT count(*) FROM vinto_master.article)=315
 AND (SELECT count(*) FROM vinto_config.form)=26
 AND (SELECT count(*) FROM vinto_config.form_version WHERE status='published')=26
 AND (SELECT count(*) FROM pg_roles WHERE rolname='vinto_identity'
    AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
    AND NOT rolbypassrls AND NOT rolreplication AND NOT rolinherit
    AND array_to_string(rolconfig,',') LIKE 'search_path=%')=1
 AND NOT EXISTS (SELECT 1 FROM pg_auth_members
                 WHERE member='vinto_identity'::regrole
                    OR roleid='vinto_identity'::regrole)
 AND has_database_privilege('vinto_identity',current_database(),'CONNECT')
 AND NOT has_database_privilege('vinto_identity',current_database(),'CREATE')
 AND NOT has_database_privilege('public',current_database(),'CONNECT')
 AND has_schema_privilege('vinto_identity','vinto_auth','USAGE')
 AND has_table_privilege('vinto_identity','vinto_master."user"','SELECT,INSERT,UPDATE')
 AND has_table_privilege('vinto_identity','vinto_master.user_machine_form_grant','SELECT,INSERT,UPDATE')
 AND has_table_privilege('vinto_identity','vinto_auth.credential','SELECT,INSERT,UPDATE')
 AND has_table_privilege('vinto_identity','vinto_auth.session','SELECT,INSERT,UPDATE')
 AND has_table_privilege('vinto_identity','vinto_auth.auth_event','SELECT,INSERT')
 AND NOT has_table_privilege('vinto_identity','vinto_master.user_machine_form_grant','DELETE')
 AND NOT has_table_privilege('vinto_identity','vinto_master.machine','INSERT')
 AND NOT has_table_privilege('vinto_identity','vinto_master.sector','INSERT')
 AND NOT has_table_privilege('vinto_identity','vinto_audit.audit_event','UPDATE')
 AND has_table_privilege('vinto_app','vinto_master."user"','INSERT')
 AND has_table_privilege('vinto_app','vinto_auth.credential','INSERT')
 AND (SELECT count(*) FROM vinto_auth.credential)=0
 AND (SELECT count(*) FROM vinto_auth.session)=0
THEN 'PASS_ROLE_IDENTITY_ADDITIVE_ONLY'
ELSE 'REVIEW_REQUIRED' END;
SQL
)"
verify_role(){
 check_qa
 check_secret "$IDENTITY_SECRET"
 local state
 state="$(query_admin "$role_metadata_sql")" || die 'postrole_metadata_unavailable'
 [ "$state" = PASS_ROLE_IDENTITY_ADDITIVE_ONLY ] ||
    die 'postrole_acl_or_catalog_mismatch'
 echo 'OFF03D7C6B_ROLE_FLAGS=PASS_UNPRIVILEGED_LOGIN'
 echo 'OFF03D7C6B_ROLE_CONNECT=PASS_QA_DB_OWNER'
 echo 'OFF03D7C6B_ROLE_GRANTS=PASS_D3B2_ADDITIVE_ONLY'
 echo 'OFF03D7C6B_APP_IDENTITY_DML=LEGACY_PRESERVED_D3B4_NOT_APPLIED'
 echo 'OFF03D7C6B_QA_CATALOG_AND_MIGRATIONS=PASS_UNCHANGED'
 echo 'OFF03D7C6B_QA_USERS_AND_GRANTS=ZERO'

 # Independently authenticate as the new identity via QA HOST LOOPBACK.
 # Never reveal password, DB URL or raw query results. Enforce READ ONLY.
 env -i PATH=/usr/sbin:/usr/bin:/sbin:/bin \
 "$PYTHON" -I -B - <<'PY'
import re
from pathlib import Path
import psycopg
secret=Path("/etc/vinto-qa/role-identity.password").read_text(encoding="ascii").strip()
if not re.fullmatch(r"[0-9a-f]{64}",secret):
    raise SystemExit("OFF03D7C6B_INSTALL_BLOCKED: secret_shape")
try:
    with psycopg.connect(
        host="127.0.0.1",port=6554,dbname="vinto_qa_offline",
        user="vinto_identity",password=secret,connect_timeout=6,
        options="-c default_transaction_read_only=on -c statement_timeout=10000",
        autocommit=True,
    ) as conn:
        row=conn.execute(
            "SELECT current_database(),current_user,inet_server_port(),"
            "current_setting('default_transaction_read_only'),"
            "has_table_privilege(current_user,'vinto_auth.credential','INSERT'),"
            "has_table_privilege(current_user,'vinto_master.machine','INSERT')"
        ).fetchone()
        if row != ("vinto_qa_offline","vinto_identity",5432,"on",True,False):
            raise ValueError("qa_identity_role_target_or_acl")
    print("OFF03D7C6B_ROLE_AUTH=PASS_READ_ONLY_QA_LOOPBACK")
except Exception:
    raise SystemExit("OFF03D7C6B_INSTALL_BLOCKED: identity_connection_or_effective_acl")
PY
 echo 'OFF03D7C6B_POSTVERIFY=PASS_ROLE_AND_GRANTS_QA_ONLY'
 echo 'OFF03D7C6B_NEW_USERS=NOT_CREATED'
 echo 'OFF03D7C6B_DML_CUT=NOT_APPLIED'
 echo 'OFF03D7C6B_GRANTS_AND_SIGNING=NOT_AUTHORIZED'
}

inspect(){
 check_qa
 check_pre
 [ ! -e "$IDENTITY_SECRET" ] && [ ! -L "$IDENTITY_SECRET" ] ||
    die 'preexisting_QA_identity_secret'
 echo 'OFF03D7C6B_INSTALL=NOT_AUTHORIZED'
 echo 'OFF03D7C6B_INSPECT=PASS_READ_ONLY'
 echo 'NO_DATABASE_WRITES=PASS'
}

apply(){
 [ "$(printenv CONFIRM_QA_IDENTITY_ROLE_INSTALL 2>/dev/null || true)" = YES ] ||
    die 'missing_specific_CREATE_ROLE_and_GRANT_approval'
 [ "$(printenv CONFIRM_QA_TARGET 2>/dev/null || true)" = vinto_qa_offline_6554 ] ||
    die 'wrong_QA_target_confirmation'
 [ "$(printenv ACK_NO_NEW_BACKUP 2>/dev/null || true)" = YES ] ||
    die 'explicit_no_new_backup_ack_missing'
 command -v flock >/dev/null 2>&1 || die 'flock_unavailable'
 exec 9>/run/lock/vinto-off03d7c6b-identity-role.lock
 flock -n 9 || die 'concurrent_role_install'
 inspect
 check_secret "$MIGRATOR_SECRET"
 echo 'OFF03D7C6B_NO_NEW_BACKUP=EXPLICITLY_WAIVED'
 echo 'OFF03D7C6B_OLD_POSTDDL_BACKUP=HISTORICAL_ONLY'

 # New password is generated only in the authorized APPLY path.
 # O_EXCL / O_NOFOLLOW prohibits overwrite and symlink substitution.
 "$PYTHON" -I -B - <<'PY'
import os
import secrets
from pathlib import Path
path="/etc/vinto-qa/role-identity.password"
flags=os.O_WRONLY|os.O_CREAT|os.O_EXCL|getattr(os,"O_NOFOLLOW",0)
fd=os.open(path,flags,0o600)
try:
    os.fchmod(fd,0o600)
    os.write(fd,(secrets.token_hex(32)+"\n").encode("ascii"))
finally:
    os.close(fd)
PY
 check_secret "$IDENTITY_SECRET"
 echo 'OFF03D7C6B_QA_IDENTITY_SECRET=CREATED_ROOT_600_NO_VALUE'

 # 00c official, as the QA cluster administrator; password via STDIN,
 # only the psql process inside QA receives IDENTITY_PASSWORD in env.
 { cat "$IDENTITY_SECRET"; cat "$ROLE_SQL"; } |
   docker exec -i "$QA" /bin/sh -c \
     'IFS= read -r IDENTITY_PASSWORD; export IDENTITY_PASSWORD; exec psql -X -q -v ON_ERROR_STOP=1 -U vinto_qa_bootstrap -d vinto_qa_offline -f -' \
     >/dev/null 2>/dev/null ||
      die 'official_00c_role_create_failed_no_automatic_rollback'

 local bare
 bare="$(query_admin "SELECT CASE WHEN
 (SELECT count(*) FROM pg_roles WHERE rolname='vinto_identity'
   AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb
   AND NOT rolcreaterole AND NOT rolinherit)=1
 AND NOT has_database_privilege('vinto_identity',current_database(),'CONNECT')
 AND NOT has_table_privilege('vinto_identity','vinto_master.\"user\"','INSERT')
 THEN 'PASS' ELSE 'BLOCKED' END;")" ||
   die 'role_creation_metadata_failed_no_retry'
 [ "$bare" = PASS ] || die 'role_creation_postcheck_failed_no_retry'
 echo 'OFF03D7C6B_ROLE_CREATE=PASS_QA_CLUSTER_ONLY'

 # Separate DB OWNER GRANT; official 03c's database GRANT from migrator
 # warns "no privileges granted", so actual CONNECT must be set here.
 docker exec "$QA" psql -X -q -v ON_ERROR_STOP=1 \
   -U vinto_qa_bootstrap -d "$DB" \
   -c 'GRANT CONNECT ON DATABASE vinto_qa_offline TO vinto_identity;' \
   >/dev/null 2>/dev/null ||
   die 'QA_owner_CONNECT_GRANT_failed_no_retry'
 [ "$(query_admin "SELECT CASE WHEN
   has_database_privilege('vinto_identity',current_database(),'CONNECT')
   AND NOT has_database_privilege('public',current_database(),'CONNECT')
   THEN 'PASS' ELSE 'BLOCKED' END;")" = PASS ] ||
   die 'QA_owner_CONNECT_postcheck_failed_no_retry'
 echo 'OFF03D7C6B_QA_DB_CONNECT=PASS_BOOTSTRAP_OWNER'

 # 03c official as the actual schema owner/migrator; TCP inside QA,
 # migrator password via STDIN (never Docker CLI args or GitHub).
 { cat "$MIGRATOR_SECRET"; cat "$GRANTS_SQL"; } |
   docker exec -i "$QA" /bin/sh -c \
     'IFS= read -r PGPASSWORD; export PGPASSWORD; exec psql -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -p 5432 -U vinto_migrator -d vinto_qa_offline -f -' \
     >/dev/null 2>/dev/null ||
      die 'official_03c_role_grants_failed_no_automatic_rollback'
 echo 'OFF03D7C6B_D3B2_GRANTS=EXECUTED_QA_ONLY'
 verify_role
 echo 'OFF03D7C6B_INSTALL=PASS_ROLE_AND_ADDITIVE_GRANTS_QA_ONLY'
 echo 'OFF03D7C6B_D3B4_CUT=NOT_EXECUTED'
 echo 'OFF03D7C6B_PILOT_TVC=NOT_TOUCHED_BY_RUNNER'
}

case "$OP" in
 inspect) inspect ;;
 verify) verify_role; echo 'NO_DATABASE_WRITES=PASS' ;;
 apply) apply ;;
esac
