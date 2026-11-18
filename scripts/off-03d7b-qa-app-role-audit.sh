#!/usr/bin/env bash
# VINTO OFF-03D.7B: QA app role audit. READ ONLY, no table rows or passwords printed.
# Only run on the approved VPS by the operator; do NOT execute D6C1/B2 pre-DDL gates.
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
die(){ echo "OFF03D7B_BLOCKED: $1" >&2; exit 1; }
usage(){ echo 'sudo -n bash scripts/off-03d7b-qa-app-role-audit.sh audit'; }
[ "$#" -eq 1 ] || { usage >&2; exit 2; }
case "$1" in
  help|-h|--help) usage; exit 0 ;;
  audit) ;;
  *) usage >&2; die 'only audit mode is permitted' ;;
esac
[ "$(id -u)" -eq 0 ] || die 'sudo_required'
for cmd in docker stat cat systemctl; do command -v "$cmd" >/dev/null || die "tool_missing_$cmd"; done

QA=vinto-qa-postgres
DB=vinto_qa_offline
APP_SECRET=/etc/vinto-qa/role-app.password

# Guard environment first; do not touch pilot/TVC or re-run migrations.
[ "$(docker inspect -f '{{.Config.Image}}' "$QA" 2>/dev/null || true)" = postgres:17 ] ||
  die 'QA_image_mismatch'
[ "$(docker inspect -f '{{.State.Running}}' "$QA" 2>/dev/null || true)" = true ] ||
  die 'QA_container_not_running'
[ "$(docker inspect -f '{{.State.Health.Status}}' "$QA" 2>/dev/null || true)" = healthy ] ||
  die 'QA_container_unhealthy'
[ "$(docker inspect -f '{{index .Config.Labels "org.baltrek.environment"}}' "$QA" 2>/dev/null || true)" = qa ] ||
  die 'QA_label_mismatch'
[ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$QA" 2>/dev/null || true)" = vinto-qa-internal ] ||
  die 'QA_network_mismatch'
[ "$(docker inspect -f '{{range (index .HostConfig.PortBindings "5432/tcp")}}{{.HostIp}}:{{.HostPort}}{{end}}' "$QA" 2>/dev/null || true)" = '127.0.0.1:6554' ] ||
  die 'QA_port_mismatch'
for svc in vinto-mvp-frontend vinto-mvp-backend vinto-web; do
  systemctl is-active --quiet "$svc" || die 'pilot_service_not_active'
done
for container in vinto-mvp-postgres postgres-vinto; do
  [ "$(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null || true)" = true ] ||
    die 'pilot_or_tvc_container_not_running'
done
echo 'OFF03D7B_QA_CONTAINER_ISOLATION=PASS'
echo 'OFF03D7B_PILOT_TVC_RUNNING=PASS'

# QA bootstrap only sees catalog metadata; no passwords, no row values, no DML.
admin_sql="$(cat <<'SQL'
SELECT CASE WHEN
 current_database()='vinto_qa_offline'
 AND current_user='vinto_qa_bootstrap'
 AND (SELECT count(*) FROM vinto_meta.schema_migration)=31
 AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname='vinto_app' AND rolcanlogin
     AND NOT (rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls OR rolinherit))
 AND NOT has_database_privilege('public',current_database(),'CONNECT')
 AND has_database_privilege('vinto_app',current_database(),'CONNECT')
 AND NOT has_database_privilege('vinto_app',current_database(),'CREATE')
 AND has_schema_privilege('vinto_app','vinto_master','USAGE')
 AND has_schema_privilege('vinto_app','vinto_config','USAGE')
 AND has_schema_privilege('vinto_app','vinto_auth','USAGE')
 AND NOT has_schema_privilege('vinto_app','vinto_meta','USAGE')
 AND has_table_privilege('vinto_app','vinto_config.form','SELECT')
 AND has_table_privilege('vinto_app','vinto_config.form_version','SELECT')
 AND has_table_privilege('vinto_app','vinto_master.user','SELECT')
 AND has_table_privilege('vinto_app','vinto_auth.session','SELECT')
 AND NOT has_table_privilege('vinto_app','vinto_master.profile','INSERT')
 AND NOT has_table_privilege('vinto_app','vinto_master.machine','INSERT')
 AND NOT has_table_privilege('vinto_app','vinto_master.sector','INSERT')
 THEN 'PASS' ELSE 'BLOCKED' END;
SQL
)"
admin_result="$(docker exec \
  -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=10000' \
  "$QA" psql -X -qAt -v ON_ERROR_STOP=1 -U vinto_qa_bootstrap \
  -d "$DB" -c "$admin_sql" 2>/dev/null)" || die 'QA_catalog_query_failed'
[ "$admin_result" = PASS ] || die 'QA_catalog_privileges_mismatch'
echo 'OFF03D7B_QA_APP_CATALOG_ACL=PASS'

[ -f "$APP_SECRET" ] && [ ! -L "$APP_SECRET" ] &&
  [ "$(stat -c '%U:%a' "$APP_SECRET")" = root:600 ] ||
  die 'QA_app_secret_missing_or_insecure'
[ "$(stat -c '%U:%a' /etc/vinto-qa)" = root:700 ] ||
  die 'QA_secret_directory_insecure'

# Read QA app password only into an unlogged pipe to the isolated QA container.
# No echo, process argv, temporary files, logs, env export on host or SQL writes.
app_sql="$(cat <<'SQL'
SELECT CASE WHEN
 current_database()='vinto_qa_offline'
 AND current_user='vinto_app'
 AND current_setting('default_transaction_read_only')='on'
 AND has_database_privilege(current_user,current_database(),'CONNECT')
 AND NOT has_database_privilege(current_user,current_database(),'CREATE')
 AND has_table_privilege('vinto_config.form','SELECT')
 AND has_table_privilege('vinto_master.user','SELECT')
 AND has_table_privilege('vinto_auth.session','SELECT')
 AND NOT has_table_privilege('vinto_master.profile','INSERT')
 AND NOT has_schema_privilege('vinto_meta','USAGE')
 THEN 'PASS' ELSE 'BLOCKED' END;
SQL
)"
app_result="$(cat "$APP_SECRET" | docker exec -i \
  -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=10000' \
  "$QA" sh -ceu '
    IFS= read -r PGPASSWORD
    export PGPASSWORD
    exec psql -X -qAt -v ON_ERROR_STOP=1 -h 127.0.0.1 -p 5432 \
      -U vinto_app -d vinto_qa_offline -c "$1"
  ' _ "$app_sql" 2>/dev/null)" || die 'QA_app_password_login_failed'
[ "$app_result" = PASS ] || die 'QA_app_effective_privileges_mismatch'
echo 'OFF03D7B_QA_APP_LOGIN=PASS_READ_ONLY'
echo 'OFF03D7B_QA_APP_MIN_PRIVILEGES=PASS'
echo 'OFF03D7B_MIGRATIONS=UNCHANGED_31'
echo 'OFF03D7B_AUDIT=PASS_READ_ONLY'
echo 'NO_DATABASE_WRITES=PASS'
