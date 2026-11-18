#!/usr/bin/env bash
# CI-only PostgreSQL17 rehearsal. Never run against a persistent host DB.
set -Eeuo pipefail
set +x
export LC_ALL=C
[ "${GITHUB_ACTIONS:-}" = true ] ||
  { echo 'SEC_HOST_A02_CI_ONLY=BLOCKED' >&2; exit 2; }
command -v docker >/dev/null || exit 2
command -v python3 >/dev/null || exit 2

NAME="sec-a02-pg17-${GITHUB_RUN_ID:-ci}"
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT
# No published ports or networking: fixture accessible only via docker exec.
docker run -d --network none --name "$NAME" \
  -e POSTGRES_HOST_AUTH_METHOD=trust postgres:17 >/dev/null

ready=0
for n in $(seq 1 60); do
  if docker exec "$NAME" pg_isready -U postgres -d postgres >/dev/null 2>&1; then
    ready=1; break
  fi
  sleep 1
done
[ "$ready" -eq 1 ] ||
  { echo 'SEC_HOST_A02_CI_PG17_READY=BLOCKED' >&2; exit 1; }
cid="$(docker inspect -f '{{.Id}}' "$NAME")"
[ "${#cid}" -eq 64 ] || exit 1

psql_ci() {
 docker exec "$NAME" psql -X -qAt -v ON_ERROR_STOP=1 \
   -U postgres -d postgres -c "$1"
}
[ "$(psql_ci 'SHOW log_connections;')" = off ] ||
  { echo 'SEC_HOST_A02_CI_INITIAL_OFF=BLOCKED' >&2; exit 1; }
psql_ci 'ALTER SYSTEM SET log_connections = on;' >/dev/null
[ "$(psql_ci 'SELECT pg_reload_conf();')" = t ] || exit 1
[ "$(psql_ci 'SHOW log_connections;')" = on ] ||
  { echo 'SEC_HOST_A02_CI_ON_SIMULATION=BLOCKED' >&2; exit 1; }
echo 'SEC_HOST_A02_CI_ON_SIMULATION=PASS_DISPOSABLE_ONLY'

# Call the actual stop-only controller, not the systemd unit. This
# rehearses RESET + reload + new session read in disposable PostgreSQL.
python3 - "$cid" <<'PY'
import importlib.util
from pathlib import Path
import sys
module_path=Path("scripts/sec-host-01-a02-stop-watchdog.py").resolve()
spec=importlib.util.spec_from_file_location("sec_a02_fixture", module_path)
module=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=module
spec.loader.exec_module(module)
obs=module.Observation.from_mapping(dict(
 container_id=sys.argv[1],
 db="postgres",
 role="postgres",
 baseline_source="default",
 baseline_verified=True,
 armed_epoch=1_800_000_000,
 deadline_epoch=1_800_000_360,
 log_bytes_at_arm=0,
 max_log_growth_bytes=500000,
 min_free_bytes=10000000,
 phase="stopping"
))
result=module.PgController(obs).restore()
if result!="RESTORED":
 raise SystemExit("SEC_HOST_A02_CI_PG_RESTORE=BLOCKED")
print("SEC_HOST_A02_CI_PG_RESTORE=PASS_ACTUAL_RESET_RELOAD_VERIFY")
PY
[ "$(psql_ci 'SHOW log_connections;')" = off ] ||
  { echo 'SEC_HOST_A02_CI_FINAL_OFF=BLOCKED' >&2; exit 1; }
[ "$(psql_ci "SELECT source FROM pg_settings WHERE name='log_connections';")" = default ] ||
  { echo 'SEC_HOST_A02_CI_FINAL_SOURCE=BLOCKED' >&2; exit 1; }
echo 'SEC_HOST_A02_CI_FINAL_STATE=PASS_ORIGINAL_DEFAULT'
echo 'SEC_HOST_A02_CI_PERSISTENT_SERVER_TOUCHED=NO'
