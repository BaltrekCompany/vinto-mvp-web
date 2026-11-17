#!/usr/bin/env bash
# CI-only integration of immutable SQL00+SQL01 against ephemeral Postgres 17.
# Strictly prevents use on the live VPS.
set -Eeuo pipefail
set +x
export LC_ALL=C
umask 077
[ "$(printenv GITHUB_ACTIONS 2>/dev/null || true)" = true ] || {
  echo 'CI_ONLY: refuse to run outside GitHub Actions' >&2
  exit 2
}
command -v docker >/dev/null 2>&1
command -v openssl >/dev/null 2>&1
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TMP="$(mktemp -d)"
NAME="off03d4-ci-$(printenv GITHUB_RUN_ID)"
cleanup() {
  docker rm -f "$NAME" >/dev/null 2>&1 || true
  rm -rf "$TMP"
}
trap cleanup EXIT
printf 'POSTGRES_USER=vinto_qa_bootstrap\nPOSTGRES_DB=vinto_qa_offline\n' > "$TMP/pg.env"
printf 'POSTGRES_PASSWORD=%s\n' "$(openssl rand -hex 32)" >> "$TMP/pg.env"
openssl rand -hex 32 > "$TMP/app"
openssl rand -hex 32 > "$TMP/migrator"
openssl rand -hex 32 > "$TMP/reference"
docker run --detach --rm --name "$NAME" --env-file "$TMP/pg.env" postgres:17 >/dev/null

for n in $(seq 1 60); do
  if docker exec "$NAME" pg_isready -q -U vinto_qa_bootstrap -d vinto_qa_offline >/dev/null 2>&1; then
    break
  fi
  sleep 2
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

result="$(docker exec "$NAME" psql -X -qAt -v ON_ERROR_STOP=1 -U vinto_qa_bootstrap -d vinto_qa_offline -c "
SELECT CASE WHEN
 (SELECT count(*) FROM pg_roles WHERE rolname IN ('vinto_app','vinto_migrator','vinto_reference'))=3
 AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN ('vinto_app','vinto_migrator','vinto_reference')
   AND (NOT rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole OR rolinherit OR rolbypassrls))
 AND NOT has_database_privilege('public','vinto_qa_offline','CONNECT')
 AND has_database_privilege('vinto_app','vinto_qa_offline','CONNECT')
 AND has_database_privilege('vinto_migrator','vinto_qa_offline','CONNECT')
 AND has_database_privilege('vinto_reference','vinto_qa_offline','CONNECT')
 AND has_database_privilege('vinto_migrator','vinto_qa_offline','CREATE')
 AND NOT has_database_privilege('vinto_app','vinto_qa_offline','CREATE')
 THEN 'PASS' ELSE 'BLOCKED' END;
")"
[ "$result" = PASS ]

for role in vinto_app vinto_migrator vinto_reference; do
  case "$role" in
    vinto_app) file="$TMP/app" ;;
    vinto_migrator) file="$TMP/migrator" ;;
    vinto_reference) file="$TMP/reference" ;;
  esac
  actual="$(cat "$file" | docker exec -i "$NAME" sh -ceu '
    IFS= read -r PGPASSWORD
    export PGPASSWORD
    exec psql -X -qAt -v ON_ERROR_STOP=1 -h 127.0.0.1 \
      -U "$1" -d vinto_qa_offline -c "SELECT current_user"
  ' _ "$role")"
  [ "$actual" = "$role" ]
done

echo 'OFF03D4_EPHEMERAL_SQL00_SQL01=PASS'
echo 'OFF03D4_EPHEMERAL_AUTH=PASS'
echo 'OFF03D4_REAL_VPS_TOUCHED=NO'
