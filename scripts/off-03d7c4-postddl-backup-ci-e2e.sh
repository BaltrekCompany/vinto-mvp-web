#!/usr/bin/env bash
# OFF-03D.7C4 - Ephemeral PostgreSQL 17 post-DDL backup/restore integration.
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
NAME="off03d7c4-ci-$(printenv GITHUB_RUN_ID)"
RESTORE="off03d7c4-restore-ci-$(printenv GITHUB_RUN_ID)"
PORT="$(python3 -c 'import socket;s=socket.socket();s.bind(("127.0.0.1",0));print(s.getsockname()[1]);s.close()')"

cleanup() {
  docker rm -f "$RESTORE" >/dev/null 2>&1 || true
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


# D7C4: Consistent read-only backup on disposable CI PostgreSQL17.
# Reuse identical metadata fingerprint SQL embedded by the production runner.
fingerprint_sql="$(awk '/^FINGERPRINT_SQL=/{active=1;next} /^SQL$/{if(active){exit}} active{print}' \
  "$ROOT/scripts/off-03d7c4-qa-postddl-backup-restore.sh")"
[ -n "$fingerprint_sql" ] || { echo 'OFF03D7C4_CI_FINGERPRINT_EXTRACTION=BLOCKED'; exit 1; }
fingerprint() {
  docker exec -e PGOPTIONS='-c default_transaction_read_only=on' "$1" \
    psql -X -qAt -v ON_ERROR_STOP=1 -U "$2" -d vinto_qa_offline -c "$fingerprint_sql"
}
fingerprint "$NAME" vinto_qa_bootstrap > "$TMP/origin.json"
docker exec -e PGOPTIONS='-c default_transaction_read_only=on' "$NAME" \
  pg_dumpall --globals-only --no-role-passwords -U vinto_qa_bootstrap \
  -l vinto_qa_offline > "$TMP/globals-no-passwords.sql"
docker exec -e PGOPTIONS='-c default_transaction_read_only=on' "$NAME" \
  pg_dump -U vinto_qa_bootstrap -d vinto_qa_offline --format=custom --create \
  > "$TMP/vinto_qa_offline.dump"
[ -s "$TMP/origin.json" ] && [ -s "$TMP/globals-no-passwords.sql" ] &&
  [ -s "$TMP/vinto_qa_offline.dump" ] || {
    echo 'OFF03D7C4_CI_POSTDDL_DUMP=BLOCKED'; exit 1;
  }
fingerprint "$NAME" vinto_qa_bootstrap > "$TMP/after-dump.json"
cmp "$TMP/origin.json" "$TMP/after-dump.json" >/dev/null ||
  { echo 'OFF03D7C4_CI_QA_DRIFT=BLOCKED'; exit 1; }
echo 'OFF03D7C4_CI_POSTDDL_DUMP=PASS'

docker run -d --rm --pull=never --name "$RESTORE" --network none \
  --label org.baltrek.environment=qa-postddl-restore-d7c4 \
  --tmpfs /var/lib/postgresql/data:rw,nosuid,size=536870912 \
  -e POSTGRES_USER=postgres -e POSTGRES_DB=postgres \
  -e POSTGRES_HOST_AUTH_METHOD=trust postgres:17 >/dev/null
[ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$RESTORE")" = none ] || exit 1
[ -z "$(docker port "$RESTORE" 2>/dev/null || true)" ] || exit 1
for n in $(seq 1 70); do
  if docker exec "$RESTORE" pg_isready -q -U postgres -d postgres >/dev/null 2>&1; then break; fi
  sleep 1
done
docker exec "$RESTORE" pg_isready -q -U postgres -d postgres
docker exec -i "$RESTORE" psql -X -q -v ON_ERROR_STOP=1 -U postgres \
  -d postgres < "$TMP/globals-no-passwords.sql"
docker exec -i "$RESTORE" pg_restore --exit-on-error --create -U postgres \
  -d postgres < "$TMP/vinto_qa_offline.dump"
fingerprint "$RESTORE" postgres > "$TMP/restored.json"
cmp -s "$TMP/origin.json" "$TMP/restored.json" ||
  { echo 'OFF03D7C4_CI_RESTORED_METADATA=BLOCKED'; exit 1; }
(
  cd "$TMP"
  sha256sum origin.json after-dump.json restored.json \
    globals-no-passwords.sql vinto_qa_offline.dump > SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
)
echo 'OFF03D7C4_CI_RESTORED_SCHEMA_OWNERS_ACL_HISTORY=PASS'
echo 'OFF03D7C4_CI_CHECKSUMS=PASS'
echo 'OFF03D7C4_CI_RESTORE_NETWORKLESS=PASS'
echo 'OFF03D7C4_CI_REAL_VPS_TOUCHED=NO'
echo 'OFF03D7C4_CI_E2E=PASS_EPHEMERAL_ONLY'
