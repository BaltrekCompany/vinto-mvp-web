#!/usr/bin/env bash
# OFF-03D.7C: read-only baseline QA fixture metadata; no secret, row or identifier output.
# AFTER 31 D6C2 migrations. Do not re-run D6B2 or D6C1 gates.
set -Eeuo pipefail
set +x
export LC_ALL=C
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
die() { echo "OFF03D7C_BLOCKED: $1" >&2; exit 1; }
[ "$#" -eq 1 ] || { echo 'usage: sudo -n bash script inspect' >&2; exit 2; }
case "$1" in
  help|-h|--help) echo 'sudo -n bash scripts/off-03d7c-qa-fixture-preflight.sh inspect'; exit 0 ;;
  inspect) ;;
  *) die 'only_read_only_inspect_supported' ;;
esac
[ "$(id -u)" -eq 0 ] || die 'sudo_required'
for c in docker systemctl; do command -v "$c" >/dev/null || die "tool_missing_$c"; done
QA=vinto-qa-postgres
DB=vinto_qa_offline
[ "$(docker inspect -f '{{.Config.Image}}' "$QA" 2>/dev/null || true)" = postgres:17 ] ||
  die 'unexpected_QA_image'
[ "$(docker inspect -f '{{.State.Running}}' "$QA" 2>/dev/null || true)" = true ] ||
  die 'QA_not_running'
[ "$(docker inspect -f '{{.State.Health.Status}}' "$QA" 2>/dev/null || true)" = healthy ] ||
  die 'QA_not_healthy'
[ "$(docker inspect -f '{{index .Config.Labels "org.baltrek.environment"}}' "$QA" 2>/dev/null || true)" = qa ] ||
  die 'unexpected_QA_label'
[ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$QA" 2>/dev/null || true)" = vinto-qa-internal ] ||
  die 'unexpected_QA_network'
[ "$(docker inspect -f '{{range (index .HostConfig.PortBindings "5432/tcp")}}{{.HostIp}}:{{.HostPort}}{{end}}' "$QA" 2>/dev/null || true)" = '127.0.0.1:6554' ] ||
  die 'unexpected_QA_port'
for svc in vinto-mvp-backend vinto-mvp-frontend vinto-web; do
  systemctl is-active --quiet "$svc" || die 'existing_service_not_active'
done
for ct in vinto-mvp-postgres postgres-vinto; do
  [ "$(docker inspect -f '{{.State.Running}}' "$ct" 2>/dev/null || true)" = true ] ||
    die 'pilot_TVC_not_running'
done
echo 'OFF03D7C_QA_AND_PILOT_ISOLATION=PASS'

# Aggregate facts only. Does not export usernames, hashes, UUIDs, passwords or values.
# No SELECT of users beyond COUNT; flags remain off and none are changed here.
sql="$(cat <<'SQL'
WITH counts AS (
 SELECT
   (SELECT count(*) FROM vinto_master."user") AS users,
   (SELECT count(*) FROM vinto_master.user_machine_form_grant) AS grants,
   (SELECT count(*) FROM vinto_master.profile) AS profiles,
   (SELECT count(*) FROM vinto_master.sector) AS sectors,
   (SELECT count(*) FROM vinto_config.form) AS forms,
   (SELECT count(*) FROM vinto_config.form_version
    WHERE status='published') AS published,
   (SELECT count(*) FROM vinto_audit.import_batch) AS import_batches,
   (SELECT count(*) FROM vinto_meta.schema_migration) AS migrations
)
SELECT CASE WHEN
  current_database() = 'vinto_qa_offline'
  AND current_user = 'vinto_qa_bootstrap'
  AND counts.migrations = 31
  THEN CASE WHEN counts.users = 0 AND counts.grants = 0
    AND counts.profiles = 0 AND counts.sectors = 0 AND counts.forms = 0
    AND counts.published = 0 AND counts.import_batches = 0
    THEN 'EMPTY_REFERENCE_BASELINE'
    ELSE 'EXISTING_REFERENCE_OR_USERS_REVIEW_REQUIRED' END
  ELSE 'BLOCKED_DATABASE_IDENTITY_OR_SCHEMA' END
FROM counts;
SQL
)"
result="$(docker exec \
  -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=10000' \
  "$QA" psql -X -qAt -v ON_ERROR_STOP=1 -U vinto_qa_bootstrap \
  -d "$DB" -c "$sql" 2>/dev/null)" ||
  die 'QA_read_only_baseline_query_failed'
case "$result" in
  EMPTY_REFERENCE_BASELINE)
    echo 'OFF03D7C_REFERENCE_BASELINE=EMPTY_QA_ONLY'
    echo 'OFF03D7C_QA_USER=NOT_CREATED'
    echo 'OFF03D7C_QA_FORM_PUBLISH=NOT_STARTED'
    ;;
  EXISTING_REFERENCE_OR_USERS_REVIEW_REQUIRED)
    echo 'OFF03D7C_REFERENCE_BASELINE=REVIEW_REQUIRED'
    echo 'OFF03D7C_PREFLIGHT=BLOCKED_EXISTING_DATA'
    exit 1
    ;;
  *) die 'unexpected_QA_state' ;;
esac
echo 'OFF03D7C_SEED_AND_SIGNER=NOT_APPLIED'
echo 'OFF03D7C_PREFLIGHT=PASS_READ_ONLY'
echo 'NO_DATABASE_WRITES=PASS'
