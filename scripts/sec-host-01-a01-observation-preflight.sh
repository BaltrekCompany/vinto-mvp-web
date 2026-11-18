#!/usr/bin/env bash
# SEC-HOST-01 A0.1 - generic observation readiness audit; READ ONLY.
# Public-source code must not contain target identifiers or log details.
# No START/STOP in this phase. No logging switches, file writes or SQL DDL.
set -Eeuo pipefail
set +x
export LC_ALL=C
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
umask 077

fail() { printf 'SEC_HOST_A01_PREFLIGHT=BLOCKED_%s\n' "$1" >&2; exit 1; }
usage() { echo 'sudo -n env OBS_CONTAINER=... OBS_CONTAINER_ID=... OBS_DB=... OBS_ROLE=... bash sec-host-01-a01-observation-preflight.sh audit'; }
[ "$#" -eq 1 ] || { usage >&2; exit 2; }
case "$1" in
  -h|--help|help) usage; exit 0 ;;
  audit) ;;
  *) fail 'READ_ONLY_AUDIT_ONLY' ;;
esac
[ "$(id -u)" -eq 0 ] || fail 'ROOT_REQUIRED'
command -v docker >/dev/null 2>&1 || fail 'DOCKER_MISSING'
[[ "${OBS_CONTAINER:-}" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$ ]] ||
  fail 'TARGET_IDENTITY_REQUIRED'
[[ "${OBS_CONTAINER_ID:-}" =~ ^[0-9a-f]{64}$ ]] ||
  fail 'PINNED_CONTAINER_ID_REQUIRED'
[[ "${OBS_DB:-}" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]] ||
  fail 'DB_IDENTITY_REQUIRED'
[[ "${OBS_ROLE:-}" =~ ^[A-Za-z_][A-Za-z0-9_]{0,62}$ ]] ||
  fail 'ROLE_IDENTITY_REQUIRED'

# Verify a specific, running container by immutable Docker container ID.
# An ID must be captured independently during the host-only inventory.
actual_id="$(docker inspect -f '{{.Id}}' "$OBS_CONTAINER" 2>/dev/null)" ||
  fail 'CONTAINER_INSPECTION_FAILED'
[ "$actual_id" = "$OBS_CONTAINER_ID" ] ||
  fail 'CONTAINER_ID_CHANGED'
running="$(docker inspect -f '{{.State.Running}}' "$OBS_CONTAINER" 2>/dev/null)" ||
  fail 'RUNNING_STATUS_UNAVAILABLE'
[ "$running" = true ] || fail 'TARGET_NOT_RUNNING'

# Only pg_settings/current_setting; no pg_stat_activity addresses or raw logs.
# Current GUC values/source filenames are intentionally not exposed.
sql="$(cat <<'SQL'
WITH
  lc AS (
    SELECT setting, context, vartype, source, pending_restart
    FROM pg_settings WHERE name = 'log_connections'
  ),
  ld AS (
    SELECT setting FROM pg_settings WHERE name = 'log_destination'
  ),
  coll AS (
    SELECT setting FROM pg_settings WHERE name = 'logging_collector'
  ),
  stmt AS (
    SELECT setting FROM pg_settings WHERE name = 'log_statement'
  ),
  dur AS (
    SELECT setting FROM pg_settings WHERE name = 'log_min_duration_statement'
  )
SELECT
  CASE WHEN current_setting('server_version_num')::int BETWEEN 140000 AND 179999
    AND (SELECT count(*) FROM lc) = 1
    AND (SELECT vartype = 'bool' AND context = 'superuser-backend'
          AND setting = 'off' AND NOT pending_restart
          AND source NOT IN ('command line', 'override') FROM lc)
  THEN 'PASS_GUC_CANDIDATE_DISABLED' ELSE 'REVIEW_GUC_OR_VERSION' END
  || '|'
  || CASE WHEN (SELECT setting = 'stderr' FROM ld)
            AND (SELECT setting = 'off' FROM coll)
     THEN 'PASS_STDERR_DIRECT' ELSE 'REVIEW_LOG_ROUTING' END
  || '|'
  || CASE WHEN (SELECT setting = 'none' FROM stmt)
            AND (SELECT setting = '-1' FROM dur)
     THEN 'PASS_NO_EXISTING_STATEMENT_LOGGING'
     ELSE 'REVIEW_EXISTING_STATEMENT_LOGGING' END;
SQL
)"
result="$(docker exec \
  -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=15000' \
  "$OBS_CONTAINER" psql -X -qAt -v ON_ERROR_STOP=1 \
  -U "$OBS_ROLE" -d "$OBS_DB" -c "$sql" 2>/dev/null)" ||
  fail 'GUC_QUERY_FAILED'
IFS='|' read -r guc sink stmt <<< "$result"
[ "$guc" = PASS_GUC_CANDIDATE_DISABLED ] ||
  fail 'GUC_VERSION_OR_SOURCE_REVIEW_REQUIRED'
echo 'SEC_HOST_A01_PG_GUC=PASS_DISABLED_BOOLEAN_RELOAD_CANDIDATE'
case "$sink" in
  PASS_STDERR_DIRECT) echo 'SEC_HOST_A01_LOG_ROUTE=STDERR_DIRECT_CANDIDATE' ;;
  *) echo 'SEC_HOST_A01_LOG_ROUTE=NOT_VERIFIED_NEEDS_PLAN' ;;
esac
case "$stmt" in
  PASS_NO_EXISTING_STATEMENT_LOGGING) echo 'SEC_HOST_A01_EXISTING_STATEMENT_LOGGING=OFF' ;;
  *) echo 'SEC_HOST_A01_EXISTING_STATEMENT_LOGGING=REVIEW_REQUIRED' ;;
esac
# These are critical gates NOT verifiable by querying pg_settings alone.
echo 'SEC_HOST_A01_LOG_SOURCE_FIDELITY=NOT_VERIFIED'
echo 'SEC_HOST_A01_LOG_RETENTION_AND_ACCESS=NOT_VERIFIED'
echo 'SEC_HOST_A01_AUTO_STOP_AND_RESTORE=NOT_INSTALLED'
echo 'SEC_HOST_A01_EXTERNAL_CLIENT_ORIGIN=NOT_VERIFIED'
echo 'SEC_HOST_A01_START_STOP=NOT_AUTHORIZED'
echo 'SEC_HOST_A01_PREFLIGHT=PASS_READ_ONLY_WITH_OPERATIONAL_GATES_OPEN'
echo 'NO_DATABASE_WRITES=PASS'
