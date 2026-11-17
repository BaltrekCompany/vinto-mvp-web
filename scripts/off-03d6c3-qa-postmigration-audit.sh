#!/usr/bin/env bash
# VINTO OFF-03D.6C3: independent QA post-migration audit, READ ONLY.
# Intended ONLY after authorized D6C2 apply. Do not rerun D5/C1/B2 verify after DDL.
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
die() { echo "OFF03D6C3_BLOCKED: $*" >&2; exit 1; }
usage() { echo 'sudo bash scripts/off-03d6c3-qa-postmigration-audit.sh audit'; }
[ "$#" -eq 1 ] || { usage >&2; exit 2; }
case "$1" in
  -h|--help|help) usage; exit 0 ;;
  audit) ;;
  *) usage >&2; die 'solo audit, sin operaciones de escritura' ;;
esac
[ "$(id -u)" -eq 0 ] || die 'requiere sudo'
for c in bash docker git stat sha256sum systemctl python3; do
  command -v "$c" >/dev/null 2>&1 || die "falta $c"
done
for svc in vinto-mvp-frontend vinto-mvp-backend vinto-web; do
  systemctl is-active --quiet "$svc" || die "servicio fuera de QA inactivo: $svc"
done
for c in vinto-mvp-postgres postgres-vinto; do
  [ "$(docker inspect -f '{{.State.Running}}' "$c" 2>/dev/null || true)" = true ] ||
    die "contenedor ajeno a QA detenido: $c"
done
echo 'OFF03D6C3_PILOT_TVC_RUNNING=PASS'

VENV=/srv/vinto-qa-offline/venv
PYTHON=/srv/vinto-qa-offline/venv/bin/python
[ -d "$VENV" ] && [ ! -L "$VENV" ] && [ -x "$PYTHON" ] ||
  die 'venv QA ausente o inseguro'
"$PYTHON" -I -B - <<'PY'
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

def block(code):
    print('OFF03D6C3_BLOCKED: ' + code)
    raise SystemExit(1)

# Explicitly strip caller-controlled PG/DOCKER/PYTHON env from each command.
CLEAN = {'PATH': '/usr/bin:/bin', 'HOME': '/srv/vinto-qa-offline',
         'LC_ALL': 'C'}
def run(args, *, cwd=None, timeout=20):
    result = subprocess.run(args, cwd=cwd, env=CLEAN, text=True,
                            capture_output=True, timeout=timeout)
    if result.returncode != 0:
        block('read_only_command_failed')
    return result.stdout.strip()

def docker_sql(query):
    return run([
        '/usr/bin/docker', 'exec', '-e',
        'PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=10000',
        'vinto-qa-postgres', 'psql', '-X', '-qAt',
        '-v', 'ON_ERROR_STOP=1', '-U', 'vinto_qa_bootstrap',
        '-d', 'vinto_qa_offline', '-c', query,
    ], timeout=30)

try:
    root = Path('/srv/vinto-qa-offline')
    source = root / 'source'
    backups = root / 'backups'
    expected_pin = '7b9eb8c82a290d06e719ee4990c2020076bbd11b'
    expected_remote = 'https://github.com/BaltrekCompany/vinto-mvp-web.git'
    if root.is_symlink() or not root.is_dir() or source.is_symlink():
        block('qa_root_or_source_invalid')
    if root.stat().st_uid != 0 or (root.stat().st_mode & 0o777) != 0o700:
        block('qa_root_permissions')
    if source.resolve(strict=True) != root / 'source':
        block('source_path_changed')
    if run(['git','-C',str(source),'rev-parse','HEAD']) != expected_pin:
        block('checkout_sha')
    if run(['git','-C',str(source),'remote','get-url','origin']) != expected_remote:
        block('checkout_remote')
    if run(['git','-C',str(source),'status','--porcelain','--untracked-files=all']):
        block('checkout_dirty')
    detached = subprocess.run(
        ['git','-C',str(source),'symbolic-ref','--quiet','HEAD'],
        env=CLEAN,capture_output=True,text=True,timeout=10
    )
    if detached.returncode != 1:
        block('checkout_not_detached')
    if (source / 'backend' / '.env').exists() or (source / '.env').exists():
        block('unexpected_env_file')
    if sys.prefix == sys.base_prefix or (
        Path(sys.prefix).resolve(strict=True) != (root / 'venv').resolve(strict=True)
    ):
        block('python_venv_identity')
    print('OFF03D6C3_CHECKOUT_VENV=PASS')

    # Preserve a verifiably restored PRE-DDL recovery point. Its source fingerprint
    # must NOT be compared with the legitimately changed post-DDL QA database.
    if backups.is_symlink() or not backups.is_dir() or (
        backups.stat().st_uid != 0 or (backups.stat().st_mode & 0o777) != 0o700
    ):
        block('backup_directory_permissions')
    entries = list(backups.glob('off03d6b2-*'))
    if len(entries) != 1 or not entries[0].is_dir() or entries[0].is_symlink():
        block('pre_migration_backup_count')
    backup = entries[0]
    if backup.stat().st_uid != 0 or (backup.stat().st_mode & 0o777) != 0o700:
        block('pre_migration_backup_permissions')
    if (backup / 'RESTORE_VERIFIED').read_text().strip() != 'OFF03D6B2_RESTORE_PASS':
        block('restore_proof_missing')
    run(['sha256sum','-c','SHA256SUMS'],cwd=str(backup),timeout=30)
    if (backup / 'origin.json').read_bytes() != (backup / 'restored.json').read_bytes():
        block('pre_migration_restore_acl_difference')
    print('OFF03D6C3_PRE_DDL_BACKUP_INTEGRITY=PASS')

    qa='vinto-qa-postgres'
    def inspect(fmt):
        return run(['/usr/bin/docker','inspect','-f',fmt,qa])
    checks={
       '{{.Config.Image}}': 'postgres:17',
       '{{.State.Running}}': 'true',
       '{{.State.Health.Status}}': 'healthy',
       '{{index .Config.Labels "org.baltrek.environment"}}': 'qa',
       '{{.HostConfig.NetworkMode}}': 'vinto-qa-internal',
       '{{range (index .HostConfig.PortBindings "5432/tcp")}}{{.HostIp}}:{{.HostPort}}{{end}}': '127.0.0.1:6554',
       '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Type}}:{{.Name}}{{end}}{{end}}': 'volume:vinto-qa-offline-pgdata',
    }
    for fmt,expected in checks.items():
        if inspect(fmt) != expected:
            block('QA_container_identity')
    print('OFF03D6C3_QA_DB_ISOLATION=PASS')

    sql_dir = source / 'backend' / 'migrations'
    sql_files = sorted(sql_dir.glob('*.sql'))
    if len(sql_files)!=31:
        block('migration_count_local')
    recorded = []
    for idx,p in enumerate(sql_files,1):
        if p.is_symlink() or not p.is_file():
            block('migration_symlink_or_missing')
        if re.fullmatch(r'[0-9]{4}_[a-z0-9_]+[.]sql',p.name) is None:
            block('migration_bad_filename')
        if int(p.name[:4]) != idx:
            block('migration_nonconsecutive')
        relative = str(p.relative_to(source))
        if run(['git','-C',str(source),'rev-parse','HEAD:'+relative]) != run(
            ['git','hash-object',str(p)]):
            block('migration_blob_drift')
        sql = p.read_text(encoding='utf-8').replace('\r\n','\n')
        recorded.append({'version':idx,'filename':p.name,
                         'checksum':hashlib.sha256(sql.encode('utf-8')).hexdigest()})
    print('OFF03D6C3_LOCAL_MIGRATIONS_31=PASS')

    history_query = """SELECT COALESCE(
      json_agg(json_build_object('version',version,'filename',filename,
      'checksum',checksum) ORDER BY version),'[]'::json)::text
      FROM vinto_meta.schema_migration;"""
    actual = json.loads(docker_sql(history_query))
    if actual != recorded:
        block('history_version_filename_or_checksum_drift')
    print('OFF03D6C3_MIGRATION_HISTORY_31=PASS')
    print('OFF03D6C3_MIGRATION_CHECKSUMS=PASS')

    # Expected baseline QA model: no identity cut and no test administrator.
    metadata_query = """SELECT CASE WHEN
      current_database()='vinto_qa_offline'
      AND current_user='vinto_qa_bootstrap'
      AND (SELECT count(*) FROM pg_namespace WHERE nspname IN
        ('vinto_master','vinto_config','vinto_txn','vinto_audit','vinto_auth','vinto_meta'))=6
      AND (SELECT count(*) FROM pg_namespace WHERE nspname LIKE 'vinto_%')=6
      AND NOT EXISTS (
         SELECT 1 FROM pg_namespace
         WHERE nspname IN ('vinto_master','vinto_config','vinto_txn','vinto_audit','vinto_auth','vinto_meta')
           AND pg_get_userbyid(nspowner)<>'vinto_migrator'
      )
      AND NOT EXISTS (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('vinto_master','vinto_config','vinto_txn','vinto_audit','vinto_auth','vinto_meta')
          AND c.relkind IN ('r','p','v','m','S','f')
          AND pg_get_userbyid(c.relowner)<>'vinto_migrator'
      )
      AND (SELECT count(*) FROM pg_roles WHERE rolname IN
           ('vinto_app','vinto_migrator','vinto_reference'))=3
      AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN
           ('vinto_identity','vinto_test_admin'))
      AND NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname IN
           ('vinto_app','vinto_migrator','vinto_reference')
           AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls OR rolinherit))
      AND NOT has_database_privilege('public',current_database(),'CONNECT')
      AND has_database_privilege('vinto_migrator',current_database(),'CREATE')
      AND NOT has_database_privilege('vinto_app',current_database(),'CREATE')
      AND NOT has_database_privilege('vinto_reference',current_database(),'CREATE')
      AND NOT has_schema_privilege('vinto_app','vinto_meta','USAGE')
      AND NOT has_schema_privilege('vinto_reference','vinto_meta','USAGE')
      AND NOT has_schema_privilege('public','vinto_meta','USAGE')
      AND NOT has_table_privilege('vinto_app','vinto_master.profile','INSERT')
      AND NOT has_table_privilege('vinto_app','vinto_master.machine','INSERT')
      AND NOT has_table_privilege('vinto_app','vinto_master.sector','INSERT')
      AND has_table_privilege('vinto_reference','vinto_master.profile','INSERT')
      AND has_table_privilege('vinto_reference','vinto_master.machine','INSERT')
      AND has_table_privilege('vinto_reference','vinto_master.sector','INSERT')
      AND has_table_privilege('vinto_app','vinto_master.user','INSERT')
      AND NOT has_table_privilege('public','vinto_master.user','SELECT')
      THEN 'PASS' ELSE 'BLOCKED' END;"""
    if docker_sql(metadata_query) != 'PASS':
        block('QA_schema_ownership_ACL_or_identity_model')
    print('OFF03D6C3_SCHEMAS_6_OWNERSHIP=PASS')
    print('OFF03D6C3_POSTMIGRATION_ACL=PASS')
    print('OFF03D6C3_NO_IDENTITY_CUT=PASS')
    print('OFF03D6C3_PILOT_TVC_UNTOUCHED_BY_AUDIT=PASS')
    print('OFF03D6C3_AUDIT=PASS_READ_ONLY')
    print('NO_DATABASE_WRITES=PASS')
except SystemExit:
    raise
except BaseException as e:
    # Never display DSNs, passwords, or data from unexpected exceptions.
    block('unexpected_'+type(e).__name__)
PY
