#!/usr/bin/env bash
# OFF-03D.5 - Ephemeral PostgreSQL 17 migration + ACL integration gate.
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
NAME="off03d5-ci-$(printenv GITHUB_RUN_ID)"
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
"$TMP/venv/bin/pip" -q install 'psycopg[binary]==3.3.6' 'pydantic-settings==2.15.0'

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

# D3B1 removes vinto_app catalog writes. Before that tightening, prove the
# dedicated vinto_reference role can run the official bundle dry-run in hardened mode.
(
  cd "$ROOT/backend"
  REFERENCE_DATABASE_URL="postgresql://vinto_reference@127.0.0.1:$PORT/vinto_qa_offline" \
  PGPASSWORD="$(cat "$TMP/reference")" \
    "$TMP/venv/bin/python" -B import_reference.py --target dev \
      > "$TMP/reference-dry-run.txt"
)
grep -q 'Base de destino: vinto_qa_offline (target=dev, modo=dry-run)' "$TMP/reference-dry-run.txt"
grep -q 'Plan (dry-run, 0 filas escritas):' "$TMP/reference-dry-run.txt"
grep -Eq 'Pendiente:|CONSISTENT / NO CHANGES:|NO-OP:' "$TMP/reference-dry-run.txt"
! grep -q 'CONFLICT / DRIFT' "$TMP/reference-dry-run.txt"
echo 'OFF03D5_CI_REFERENCE_IMPORT_DRY_RUN=PASS'

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
echo 'OFF03D5_REAL_VPS_TOUCHED=NO'
