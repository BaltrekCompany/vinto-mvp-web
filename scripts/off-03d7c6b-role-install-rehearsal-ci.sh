#!/usr/bin/env bash
# OFF-03D.7C2 - Ephemeral PG17 migrations, ACL and full official-reference import rehearsal.
# CI ONLY: cannot be used as VPS provisioning script.
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
[ "$(printenv GITHUB_ACTIONS 2>/dev/null || true)" = true ] || {
  echo 'OFF03D5_CI_ONLY=BLOCKED' >&2
  exit 2
}
for c in docker openssl python3; do command -v "$c" >/dev/null 2>&1 || exit 2; done
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
NAME="off03d7c2-ci-$(printenv GITHUB_RUN_ID)"
PORT="$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')"

cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT

openssl rand -hex 32 > "$TMP/root"
openssl rand -hex 32 > "$TMP/app"
openssl rand -hex 32 > "$TMP/migrator"
openssl rand -hex 32 > "$TMP/reference"

docker run -d --rm --name "$NAME" --publish "127.0.0.1:$PORT:5432" \
  -e POSTGRES_USER=vinto_qa_bootstrap -e POSTGRES_DB=vinto_qa_offline \
  -e "POSTGRES_PASSWORD=$(cat "$TMP/root")" postgres:17 >/dev/null

for n in $(seq 1 70); do
  if docker exec "$NAME" pg_isready -q -U vinto_qa_bootstrap -d vinto_qa_offline >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec "$NAME" pg_isready -q -U vinto_qa_bootstrap -d vinto_qa_offline

{
  cat "$TMP/app"
  cat "$TMP/migrator"
  cat "$TMP/reference"
  cat "$ROOT/backend/roles/00_create_roles.sql"
} | docker exec -i "$NAME" sh -ceu '
  IFS= read -r APP_PASSWORD
  IFS= read -r MIGRATOR_PASSWORD
  IFS= read -r REFERENCE_PASSWORD
  export APP_PASSWORD MIGRATOR_PASSWORD REFERENCE_PASSWORD
  exec psql -X -q -v ON_ERROR_STOP=1 -U vinto_qa_bootstrap -d vinto_qa_offline -f -
'
docker exec -i -e DBNAME=vinto_qa_offline "$NAME" \
  psql -X -q -v ON_ERROR_STOP=1 -U vinto_qa_bootstrap -d vinto_qa_offline \
  -f - < "$ROOT/backend/roles/01_database_grants.sql"
echo 'OFF03D5_CI_BASE_ROLES=PASS'

python3 -m venv "$TMP/venv"
"$TMP/venv/bin/pip" -q install -r "$ROOT/backend/requirements.txt"

export CI_QA_PORT="$PORT"
export APP_ENV=qa
export PG_PRIVILEGE_MODE=hardened
export MIGRATOR_DATABASE_URL="postgresql://vinto_migrator:$(cat "$TMP/migrator")@127.0.0.1:$PORT/vinto_qa_offline"

(
  cd "$ROOT/backend"
  "$TMP/venv/bin/python" - <<'PY'
from urllib.parse import urlparse
import os
import psycopg
from migrate import read_migrations
p = urlparse(os.environ['MIGRATOR_DATABASE_URL'])
assert p.scheme == 'postgresql'
assert (p.hostname, p.port, p.username, p.path) == (
    '127.0.0.1', int(os.environ['CI_QA_PORT']), 'vinto_migrator', '/vinto_qa_offline')
migrations = read_migrations()
assert len(migrations) == 31
assert [m.version for m in migrations] == list(range(1, 32))
with psycopg.connect(os.environ['MIGRATOR_DATABASE_URL']) as conn:
    database, user = conn.execute("SELECT current_database(), current_user").fetchone()
    assert (database, user) == ('vinto_qa_offline', 'vinto_migrator')
    assert conn.execute("SELECT to_regclass('vinto_meta.schema_migration')").fetchone()[0] is None
print('OFF03D5_CI_DB_IDENTITY=PASS')
print('OFF03D5_CI_MIGRATIONS_MANIFEST=31')
PY
  "$TMP/venv/bin/python" migrate.py --target dev --status > "$TMP/before.txt"
  "$TMP/venv/bin/python" migrate.py --target dev > "$TMP/apply.txt"
  "$TMP/venv/bin/python" migrate.py --target dev --check > "$TMP/check.txt"
)
echo 'OFF03D5_CI_MIGRATIONS_APPLIED=PASS'
echo 'OFF03D5_CI_MIGRATIONS_CHECK=PASS'

run_acl() {
  local file="$1"
  {
    cat "$TMP/migrator"
    cat "$ROOT/backend/roles/$file"
  } | docker exec -i "$NAME" sh -ceu '
    IFS= read -r PGPASSWORD
    export PGPASSWORD
    exec psql -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 \
      -U vinto_migrator -d vinto_qa_offline -f -
  '
}
run_acl 02_schema_grants.sql
run_acl 03_table_grants.sql
run_acl 03b_d3b1_restrict_catalog_writes.sql
run_acl 04_function_grants.sql
run_acl 05_no_default_privileges.sql
run_acl 06_public_and_meta_protection.sql
run_acl 07_verification_queries.sql > "$TMP/verify-07.txt"
run_acl 08_release_preflight.sql > "$TMP/verify-08.txt"

# Verify final state through metadata as bootstrap, NO business data.
result="$(docker exec "$NAME" psql -X -qAt -v ON_ERROR_STOP=1 \
  -U vinto_qa_bootstrap -d vinto_qa_offline -c "
SELECT CASE WHEN
 (SELECT COUNT(*) FROM vinto_meta.schema_migration)=31
 AND (SELECT MIN(version) FROM vinto_meta.schema_migration)=1
 AND (SELECT MAX(version) FROM vinto_meta.schema_migration)=31
 AND (SELECT count(*) FROM pg_namespace WHERE nspname IN
    ('vinto_master','vinto_config','vinto_txn','vinto_audit','vinto_auth','vinto_meta'))=6
 AND NOT has_schema_privilege('vinto_app','vinto_meta','USAGE')
 AND NOT has_table_privilege('vinto_app','vinto_master.profile','INSERT')
 AND NOT has_table_privilege('vinto_app','vinto_master.machine','INSERT')
 AND NOT has_table_privilege('vinto_app','vinto_master.sector','INSERT')
 AND has_database_privilege('vinto_migrator','vinto_qa_offline','CREATE')
 AND NOT has_database_privilege('public','vinto_qa_offline','CONNECT')
 THEN 'PASS' ELSE 'BLOCKED' END;
")"
[ "$result" = PASS ] || { echo 'OFF03D5_CI_FINAL_ACL=BLOCKED' >&2; exit 1; }
echo 'OFF03D5_CI_FINAL_ACL=PASS'
echo 'OFF03D5_CI_EPHEMERAL_PASS=PASS'


# OFF-03D.7C2 extension: official bundle dry-run and full import into the
# disposal-only PostgreSQL container. NEVER against VPS or production.
export REFERENCE_DATABASE_URL="postgresql://vinto_reference:$(cat "$TMP/reference")@127.0.0.1:$PORT/vinto_qa_offline"
unset DATABASE_URL || true
(
  cd "$ROOT/backend"
  "$TMP/venv/bin/python" -B - <<'PY'
from app.qa_offline_fixture_contract import validate_repo_qa_fixture_contract
info = validate_repo_qa_fixture_contract()
assert len(info.form_versions) == 4
assert info.form_versions == (
    ("VINTO-P1-18", 2), ("VINTO-P1-22", 2),
    ("VINTO-P1-26", 3), ("VINTO-P1-27", 2)
)
print("OFF03D7C2_CANONICAL_BUNDLE=PASS")
PY
  "$TMP/venv/bin/python" -B import_reference.py --target dev > "$TMP/reference-plan.txt"
  grep -q 'Base de destino: vinto_qa_offline (target=dev, modo=dry-run)' "$TMP/reference-plan.txt"
  grep -q 'Plan (dry-run, 0 filas escritas):' "$TMP/reference-plan.txt"
  grep -q 'Pendiente:' "$TMP/reference-plan.txt"
  ! grep -q 'CONFLICT / DRIFT' "$TMP/reference-plan.txt"
  echo 'OFF03D7C2_REFERENCE_DRY_RUN=PASS_READ_ONLY'

  # This apply is authorized ONLY within CI ephemeral container, not on VPS.
  "$TMP/venv/bin/python" -B import_reference.py --target dev --apply > "$TMP/reference-applied.txt"
  grep -q 'Base de destino: vinto_qa_offline (target=dev, modo=apply)' "$TMP/reference-applied.txt"
  grep -q 'Importación completada' "$TMP/reference-applied.txt"
  echo 'OFF03D7C2_CI_REFERENCE_IMPORT=PASS_EPHEMERAL'

  "$TMP/venv/bin/python" -B import_reference.py --target dev > "$TMP/reference-repeat.txt"
  grep -Eq 'NO-OP:|CONSISTENT / NO CHANGES:' "$TMP/reference-repeat.txt"
  ! grep -q 'CONFLICT / DRIFT' "$TMP/reference-repeat.txt"
  echo 'OFF03D7C2_IDEMPOTENT_RERUN=PASS_READ_ONLY'
)

# Diagnostic is aggregate metadata from the disposable CI database only.
# It is safe to print if a contract assertion fails; never include row values.
metadata="$(docker exec -e PGOPTIONS='-c default_transaction_read_only=on' "$NAME" \
 psql -X -qAt -v ON_ERROR_STOP=1 -U vinto_qa_bootstrap -d vinto_qa_offline -c "
WITH expected(code, version) AS (
 VALUES ('VINTO-P1-18',2), ('VINTO-P1-22',2),('VINTO-P1-26',3),('VINTO-P1-27',2)
), selected AS (
 SELECT fv.id, fv.status, fv.area FROM expected e
 JOIN vinto_config.form f ON f.code=e.code
 JOIN vinto_config.form_version fv ON fv.form_id=f.id AND fv.version_number=e.version
)
SELECT concat(
  'migration_count:', (SELECT count(*) FROM vinto_meta.schema_migration),
  ',versions:', (SELECT count(*) FROM selected),
  ',draft_quality:', (SELECT count(*) FROM selected WHERE status='draft' AND area='quality'),
  ',published_quality:', (SELECT count(*) FROM selected WHERE status='published' AND area='quality'),
  ',machine_links:', (SELECT count(*) FROM vinto_config.form_version_machine m JOIN selected s ON s.id=m.form_version_id),
  ',users:', (SELECT count(*) FROM vinto_master.\"user\"),
  ',grants:', (SELECT count(*) FROM vinto_master.user_machine_form_grant),
  ',completed_batches:', (SELECT count(*) FROM vinto_audit.import_batch WHERE status='completed'),
  ',all_batches:', (SELECT count(*) FROM vinto_audit.import_batch)
);
" 2>/dev/null)" || { echo 'OFF03D7C2_CI_METADATA_DIAGNOSTIC=BLOCKED' >&2; exit 1; }
echo "OFF03D7C2_CI_METADATA_DIAGNOSTIC=$metadata"

result="$(docker exec -e PGOPTIONS='-c default_transaction_read_only=on' "$NAME" \
 psql -X -qAt -v ON_ERROR_STOP=1 -U vinto_qa_bootstrap -d vinto_qa_offline -c "
WITH expected(code, version) AS (
 VALUES ('VINTO-P1-18',2), ('VINTO-P1-22',2),
        ('VINTO-P1-26',3), ('VINTO-P1-27',2)
), selected AS (
 SELECT fv.id, fv.status, fv.area FROM expected e
 JOIN vinto_config.form f ON f.code=e.code
 JOIN vinto_config.form_version fv ON fv.form_id=f.id AND fv.version_number=e.version
)
SELECT CASE WHEN
   current_database()='vinto_qa_offline'
   AND (SELECT count(*) FROM vinto_meta.schema_migration)=31
   AND (SELECT count(*) FROM selected)=4
   AND (SELECT count(*) FROM selected WHERE status='published' AND area='quality')=4
   AND (SELECT count(*) FROM vinto_config.form_version_machine m
        JOIN selected s ON m.form_version_id=s.id)=8
   AND (SELECT count(*) FROM vinto_master.\"user\")=0
   AND (SELECT count(*) FROM vinto_master.user_machine_form_grant)=0
   AND (SELECT count(*) FROM vinto_audit.import_batch WHERE status='completed')=1
 THEN 'PASS' ELSE 'BLOCKED' END;
" 2>/dev/null)" || { echo 'OFF03D7C2_CI_METADATA_QUERY=BLOCKED' >&2; exit 1; }
[ "$result" = PASS ] || { echo 'OFF03D7C2_CI_POSTIMPORT_CONTRACT=BLOCKED' >&2; exit 1; }
echo 'OFF03D7C2_CI_FOUR_QUALITY_VERSIONS=PUBLISHED_BY_IMPORT'
echo 'OFF03D7C2_CI_MACHINE_LINKS=8'
echo 'OFF03D7C2_CI_NO_ADDITIONAL_PUBLICATION_STEP=PASS'
echo 'OFF03D7C2_CI_TEST_USER_AND_GRANTS=NOT_CREATED'
echo 'OFF03D7C2_CI_POSTIMPORT_CONTRACT=PASS'

# D7C6A -- same identity/ACL read-only SQL as the VPS auditor, on disposable PG17.
sql="$(python3 - "$ROOT/scripts/off-03d7c6a-qa-identity-readiness.sh" <<'PY'
from pathlib import Path
import sys
src=Path(sys.argv[1]).read_text(encoding="utf-8")
start="read -r -d '' SQL <<'SQL' || true\n"
end="\nSQL\n"
begin=src.index(start)+len(start)
finish=src.index(end,begin)
query=src[begin:finish]
assert "current_database() = 'vinto_qa_offline'" in query
assert "ROLE_ABSENT_APP_IDENTITY_DML_PRESENT" in query
print(query)
PY
)" || { echo 'OFF03D7C6A_CI_SQL_EXTRACT=BLOCKED' >&2; exit 1; }
[ -n "$sql" ] || { echo 'OFF03D7C6A_CI_SQL_EXTRACT=BLOCKED' >&2; exit 1; }
result="$(docker exec \
  -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=15000' \
  "$NAME" psql -X -qAt -v ON_ERROR_STOP=1 \
  -U vinto_qa_bootstrap -d vinto_qa_offline -c "$sql" 2>/dev/null)" ||
  { echo 'OFF03D7C6A_CI_IDENTITY_BASELINE=BLOCKED' >&2; exit 1; }
[ "$result" = ROLE_ABSENT_APP_IDENTITY_DML_PRESENT ] ||
  { echo 'OFF03D7C6A_CI_IDENTITY_BASELINE=BLOCKED' >&2; exit 1; }
echo 'OFF03D7C6A_CI_IDENTITY_ROLE=ABSENT'
echo 'OFF03D7C6A_CI_APP_IDENTITY_DML=EXPOSED_LEGACY'
echo 'OFF03D7C6A_CI_IDENTITY_BASELINE=PASS_READ_ONLY'
echo 'OFF03D7C6A_CI_REAL_VPS_TOUCHED=NO'


# OFF-03D.7C6B: evaluate the exact fixed read-only SQL that will be
# used in real QA, on this isolated/disposable PG17 before role creation.
preflight_sql="$(python3 - "$ROOT/scripts/off-03d7c6b-qa-identity-role-preflight.sh" <<'PY'
from pathlib import Path
import sys
src=Path(sys.argv[1]).read_text(encoding="utf-8")
start="SQL=\"$(cat <<'SQL'\n"
end="\nSQL\n)\""
begin=src.index(start)+len(start)
finish=src.index(end,begin)
q=src[begin:finish]
assert "current_database() = 'vinto_qa_offline'" in q
assert "PASS_PRE_ROLE_CREATION" in q
print(q)
PY
)" || { echo 'OFF03D7C6B_CI_SQL_EXTRACT=BLOCKED' >&2; exit 1; }
[ -n "$preflight_sql" ] || { echo 'OFF03D7C6B_CI_SQL_EXTRACT=BLOCKED' >&2; exit 1; }
preflight="$(docker exec \
 -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=15000' \
 "$NAME" psql -X -qAt -v ON_ERROR_STOP=1 \
 -U vinto_qa_bootstrap -d vinto_qa_offline -c "$preflight_sql" 2>/dev/null)" ||
 { echo 'OFF03D7C6B_CI_ROLE_PREFLIGHT=BLOCKED' >&2; exit 1; }
[ "$preflight" = PASS_PRE_ROLE_CREATION ] ||
 { echo 'OFF03D7C6B_CI_ROLE_PREFLIGHT=BLOCKED' >&2; exit 1; }
echo 'OFF03D7C6B_CI_QA_ROLE_GLOBAL_ISOLATION=PASS'
echo 'OFF03D7C6B_CI_ROLE_PREFLIGHT=PASS_READ_ONLY'
echo 'OFF03D7C6B_CI_REAL_VPS_TOUCHED=NO'

echo 'OFF03D7C2_REAL_VPS_TOUCHED=NO'
echo 'OFF03D7C2_CI=PASS_EPHEMERAL_ONLY'


# OFF03D.7C6B: CI-only rehearsal of the unchanged official 00c + 03c SQL
# after all 31 migrations, D3B1 and canonical reference catalog.
# This is NOT an installer and MUST NOT be run on the persistent VPS.
role_root="$ROOT/backend/roles"
check_blob() {
  [ "$(git hash-object "$role_root/$1")" = "$2" ] ||
    { echo 'OFF03D7C6B_CI_SQL_BLOB_DRIFT=BLOCKED' >&2; exit 1; }
}
check_blob '00c_create_identity_role.sql' '04bc90dfeaf225d2c139587899fa46ce54913fe5'
check_blob '03c_d3b2_identity_role_grants.sql' '6df9ac8c96d6cf85a00aecccc6631f8eddc7450b'
check_blob 'rollback/ROLLBACK_D3B2.sql' '0039f4c530b611873f4b60710bf42aec54edd2c7'
echo 'OFF03D7C6B_CI_ROLE_SQL_BLOBS=PASS'

# The role password is only in disposable runner memory/file (umask 077),
# transferred via STDIN. Never exposed as docker argv, psql -v, SQL logs or Git.
openssl rand -hex 32 > "$TMP/identity"
(
  printf '%s\n' "$(cat "$TMP/identity")"
  cat "$role_root/00c_create_identity_role.sql"
) | docker exec -i "$NAME" bash -c \
  'IFS= read -r IDENTITY_PASSWORD; export IDENTITY_PASSWORD; exec psql -X -q -v ON_ERROR_STOP=1 -U vinto_qa_bootstrap -d vinto_qa_offline -f -' \
  >/dev/null || { echo 'OFF03D7C6B_CI_CREATE_ROLE=BLOCKED' >&2; exit 1; }

identity_created="$(docker exec -e PGOPTIONS='-c default_transaction_read_only=on' "$NAME" \
  psql -X -qAt -v ON_ERROR_STOP=1 -U vinto_qa_bootstrap -d vinto_qa_offline -c "
SELECT CASE WHEN
 (SELECT count(*) FROM pg_roles WHERE rolname='vinto_identity'
  AND rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
  AND NOT rolinherit AND array_to_string(rolconfig,',') LIKE 'search_path=%')=1
 AND NOT has_database_privilege('vinto_identity',current_database(),'CONNECT')
 AND NOT has_table_privilege('vinto_identity','vinto_master.\"user\"','INSERT')
THEN 'PASS' ELSE 'BLOCKED' END;
" 2>/dev/null)" ||
 { echo 'OFF03D7C6B_CI_ROLE_SHAPE=BLOCKED' >&2; exit 1; }
[ "$identity_created" = PASS ] ||
 { echo 'OFF03D7C6B_CI_ROLE_SHAPE=BLOCKED' >&2; exit 1; }
echo 'OFF03D7C6B_CI_CREATE_ROLE=PASS_UNPRIVILEGED_LOGIN'

# Database CONNECT is owned by QA bootstrap, NOT vinto_migrator.
# The official 03c GRANT CONNECT clause may report "no privileges granted"
# when executed by migrator. Explicitly grant CONNECT as DB owner beforehand.
docker exec "$NAME" psql -X -q -v ON_ERROR_STOP=1 \
  -U vinto_qa_bootstrap -d vinto_qa_offline \
  -c 'GRANT CONNECT ON DATABASE vinto_qa_offline TO vinto_identity;' >/dev/null ||
  { echo 'OFF03D7C6B_CI_DB_OWNER_CONNECT=BLOCKED' >&2; exit 1; }
connect="$(docker exec -e PGOPTIONS='-c default_transaction_read_only=on' "$NAME" \
  psql -X -qAt -v ON_ERROR_STOP=1 \
  -U vinto_qa_bootstrap -d vinto_qa_offline -c "
SELECT CASE WHEN has_database_privilege('vinto_identity',current_database(),'CONNECT')
 AND NOT has_database_privilege('public',current_database(),'CONNECT')
 THEN 'PASS' ELSE 'BLOCKED' END;" 2>/dev/null)" ||
  { echo 'OFF03D7C6B_CI_DB_OWNER_CONNECT=BLOCKED' >&2; exit 1; }
[ "$connect" = PASS ] ||
  { echo 'OFF03D7C6B_CI_DB_OWNER_CONNECT=BLOCKED' >&2; exit 1; }
echo 'OFF03D7C6B_CI_DB_OWNER_CONNECT=PASS_SEPARATE_ADMIN_GRANT'

# 03c runs as vinto_migrator, the documented table owner, NOT bootstrap.
docker exec -i "$NAME" psql -X -q -v ON_ERROR_STOP=1 \
  -U vinto_migrator -d vinto_qa_offline \
  < "$role_root/03c_d3b2_identity_role_grants.sql" >/dev/null ||
  { echo 'OFF03D7C6B_CI_ROLE_GRANTS=BLOCKED' >&2; exit 1; }

grants="$(docker exec -e PGOPTIONS='-c default_transaction_read_only=on' "$NAME" \
 psql -X -qAt -v ON_ERROR_STOP=1 -U vinto_qa_bootstrap -d vinto_qa_offline -c "
SELECT CASE WHEN
 has_database_privilege('vinto_identity',current_database(),'CONNECT')
 AND has_schema_privilege('vinto_identity','vinto_auth','USAGE')
 AND has_table_privilege('vinto_identity','vinto_master.\"user\"','INSERT')
 AND has_table_privilege('vinto_identity','vinto_master.user_machine_form_grant','INSERT')
 AND has_table_privilege('vinto_identity','vinto_auth.credential','INSERT')
 AND has_table_privilege('vinto_identity','vinto_auth.session','INSERT')
 AND has_table_privilege('vinto_app','vinto_master.\"user\"','INSERT')
 AND has_table_privilege('vinto_app','vinto_auth.credential','INSERT')
 AND NOT has_table_privilege('vinto_identity','vinto_master.user_machine_form_grant','DELETE')
 AND NOT has_database_privilege('vinto_identity',current_database(),'CREATE')
 AND NOT has_table_privilege('vinto_identity','vinto_master.machine','INSERT')
 AND (SELECT count(*) FROM vinto_master.\"user\")=0
 AND (SELECT count(*) FROM vinto_master.user_machine_form_grant)=0
 AND (SELECT count(*) FROM vinto_meta.schema_migration)=31
THEN 'PASS' ELSE 'BLOCKED' END;
" 2>/dev/null)" ||
 { echo 'OFF03D7C6B_CI_ROLE_GRANTS=BLOCKED' >&2; exit 1; }
[ "$grants" = PASS ] ||
 { echo 'OFF03D7C6B_CI_ROLE_GRANTS=BLOCKED' >&2; exit 1; }
echo 'OFF03D7C6B_CI_ROLE_GRANTS=PASS_ADDITIVE_ONLY'

# Only disposable CI executes this ROLLBACK, to prove actual contract.
# The rollback REVOKES privileges but intentionally leaves the role present.
docker exec -i "$NAME" psql -X -q -v ON_ERROR_STOP=1 \
 -U vinto_migrator -d vinto_qa_offline \
 < "$role_root/rollback/ROLLBACK_D3B2.sql" >/dev/null ||
 { echo 'OFF03D7C6B_CI_ROLLBACK_D3B2=BLOCKED' >&2; exit 1; }

# ROLLBACK_D3B2 is run as migrator. It cannot revoke a CONNECT grant
# owned by bootstrap. Before owner cleanup, schema/table grants are gone but
# the role may still have CONNECT. Explicit admin REVOKE is therefore required.
docker exec "$NAME" psql -X -q -v ON_ERROR_STOP=1 \
  -U vinto_qa_bootstrap -d vinto_qa_offline \
  -c 'REVOKE CONNECT ON DATABASE vinto_qa_offline FROM vinto_identity;' >/dev/null ||
  { echo 'OFF03D7C6B_CI_DB_OWNER_REVOKE=BLOCKED' >&2; exit 1; }
echo 'OFF03D7C6B_CI_DB_OWNER_REVOKE=PASS_SEPARATE_ADMIN_REVOKE'

revoked="$(docker exec -e PGOPTIONS='-c default_transaction_read_only=on' "$NAME" \
 psql -X -qAt -v ON_ERROR_STOP=1 -U vinto_qa_bootstrap -d vinto_qa_offline -c "
SELECT CASE WHEN
 EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vinto_identity')
 AND NOT has_database_privilege('vinto_identity',current_database(),'CONNECT')
 AND NOT has_schema_privilege('vinto_identity','vinto_auth','USAGE')
 AND NOT has_table_privilege('vinto_identity','vinto_auth.credential','SELECT')
 AND NOT has_table_privilege('vinto_identity','vinto_master.\"user\"','INSERT')
 AND has_table_privilege('vinto_app','vinto_master.\"user\"','INSERT')
 AND has_table_privilege('vinto_app','vinto_auth.credential','INSERT')
 AND (SELECT count(*) FROM vinto_master.\"user\")=0
 AND (SELECT count(*) FROM vinto_master.user_machine_form_grant)=0
 AND (SELECT count(*) FROM vinto_meta.schema_migration)=31
THEN 'PASS' ELSE 'BLOCKED' END;
" 2>/dev/null)" ||
 { echo 'OFF03D7C6B_CI_ROLLBACK_D3B2=BLOCKED' >&2; exit 1; }
[ "$revoked" = PASS ] ||
 { echo 'OFF03D7C6B_CI_ROLLBACK_D3B2=BLOCKED' >&2; exit 1; }
echo 'OFF03D7C6B_CI_ROLLBACK_D3B2=PASS_REVOKES_ONLY'
echo 'OFF03D7C6B_CI_IDENTITY_ROLE_REMOVAL=NOT_TESTED_NOT_PART_OF_D3B2'
echo 'OFF03D7C6B_CI_IDENTITY_DML_CUT=NOT_EXECUTED'
echo 'OFF03D7C6B_CI_PILOT_TVC=NOT_TOUCHED'
echo 'OFF03D7C6B_CI_FULL_REHEARSAL=PASS_EPHEMERAL_ONLY'
