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

echo 'OFF03D7C2_REAL_VPS_TOUCHED=NO'
echo 'OFF03D7C2_CI=PASS_EPHEMERAL_ONLY'
