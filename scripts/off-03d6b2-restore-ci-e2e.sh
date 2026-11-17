#!/usr/bin/env bash
# CI-only disposable PostgreSQL 17: validate dump globals and --create restore semantics.
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
[ "$(printenv GITHUB_ACTIONS 2>/dev/null || true)" = true ] || {
  echo 'OFF03D6B2_CI_ONLY=BLOCKED' >&2
  exit 2
}
for c in docker mktemp sha256sum cmp; do command -v "$c" >/dev/null 2>&1 || exit 2; done
TMP="$(mktemp -d)"
SRC="off03d6b2-ci-src-$(printenv GITHUB_RUN_ID)"
DEST="off03d6b2-ci-dest-$(printenv GITHUB_RUN_ID)"
cleanup() {
  docker rm -f "$SRC" "$DEST" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT
start() {
  docker run -d --rm --name "$1" --network none \
    --label org.baltrek.environment=ci-qa-restore \
    --tmpfs /var/lib/postgresql/data:rw,nosuid,size=536870912 \
    -e "POSTGRES_USER=$2" -e "POSTGRES_DB=$3" \
    -e POSTGRES_HOST_AUTH_METHOD=trust postgres:17 >/dev/null
  for i in $(seq 1 60); do
    if docker exec "$1" pg_isready -q -U "$2" -d "$3"; then return; fi
    sleep 1
  done
  return 1
}
start "$SRC" vinto_qa_bootstrap vinto_qa_offline
docker exec "$SRC" psql -X -q -v ON_ERROR_STOP=1 \
  -U vinto_qa_bootstrap -d vinto_qa_offline -c "
CREATE ROLE vinto_app LOGIN NOINHERIT;
CREATE ROLE vinto_migrator LOGIN NOINHERIT;
CREATE ROLE vinto_reference LOGIN NOINHERIT;
ALTER ROLE vinto_app SET search_path = '';
REVOKE CONNECT, TEMPORARY ON DATABASE vinto_qa_offline FROM PUBLIC;
GRANT CONNECT ON DATABASE vinto_qa_offline TO vinto_app,vinto_migrator,vinto_reference;
GRANT CREATE ON DATABASE vinto_qa_offline TO vinto_migrator;
"
docker exec -e PGOPTIONS='-c default_transaction_read_only=on' "$SRC" \
  pg_dumpall --globals-only --no-role-passwords -U vinto_qa_bootstrap -l vinto_qa_offline \
  > "$TMP/globals.sql"
docker exec -e PGOPTIONS='-c default_transaction_read_only=on' "$SRC" \
  pg_dump -U vinto_qa_bootstrap -d vinto_qa_offline --format=custom --create \
  > "$TMP/database.dump"
test -s "$TMP/globals.sql"
test -s "$TMP/database.dump"
(
  cd "$TMP"
  sha256sum globals.sql database.dump > SHA256SUMS
  sha256sum -c SHA256SUMS >/dev/null
)
start "$DEST" postgres postgres
test "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$DEST")" = none
docker exec -i "$DEST" psql -X -q -v ON_ERROR_STOP=1 \
  -U postgres -d postgres < "$TMP/globals.sql"
docker exec -i "$DEST" pg_restore --exit-on-error --create \
  -U postgres -d postgres < "$TMP/database.dump"
query="SELECT CASE WHEN current_database()='vinto_qa_offline'
 AND (SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database())='vinto_qa_bootstrap'
 AND (SELECT count(*) FROM pg_roles WHERE rolname IN ('vinto_app','vinto_migrator','vinto_reference'))=3
 AND NOT has_database_privilege('public',current_database(),'CONNECT')
 AND has_database_privilege('vinto_migrator',current_database(),'CREATE')
 AND NOT has_database_privilege('vinto_app',current_database(),'CREATE')
 AND NOT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname LIKE 'vinto_%')
 THEN 'PASS' ELSE 'BLOCKED' END;"
result="$(docker exec "$DEST" psql -X -qAt -v ON_ERROR_STOP=1 \
  -U postgres -d vinto_qa_offline -c "$query")"
test "$result" = PASS
echo 'OFF03D6B2_CI_GLOBALS_RESTORE=PASS'
echo 'OFF03D6B2_CI_DB_ACL_RESTORE=PASS'
echo 'OFF03D6B2_CI_NETWORKLESS_RESTORE=PASS'
echo 'OFF03D6B2_REAL_VPS_TOUCHED=NO'
