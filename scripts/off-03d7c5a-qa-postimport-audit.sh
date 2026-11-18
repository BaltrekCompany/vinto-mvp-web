#!/usr/bin/env bash
# VINTO OFF-03D.7C5A - independent post-import QA audit, strictly READ ONLY.
# Not the pre-import D7C5 inspect: a populated catalog is REQUIRED.
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH=/usr/sbin:/usr/bin:/sbin:/bin
deny(){ echo "OFF03D7C5A_BLOCKED: $1" >&2; exit 1; }
usage(){ echo 'sudo -n bash scripts/off-03d7c5a-qa-postimport-audit.sh audit'; }
[ "$#" -eq 1 ] || { usage >&2; exit 2; }
case "$1" in
  -h|--help|help) usage; exit 0 ;;
  audit) ;;
  *) usage >&2; deny 'only_read_only_audit_permitted' ;;
esac
[ "$(id -u)" -eq 0 ] || deny 'sudo_required'
for cmd in bash docker git grep stat systemctl; do
  command -v "$cmd" >/dev/null 2>&1 || deny "tool_missing_$cmd"
done

C3=/tmp/vinto-off03d6c3-qa-postmigration-audit.sh
C3_BLOB=ebb773f88ba6740ddf4fef53f1b76de541346a85
BACKUP=/tmp/vinto-off03d7c4-qa-postddl-backup-restore.sh
BACKUP_BLOB=6f772a25a9b552d792d7d2215cc5676cca56b5fe
SOURCE=/srv/vinto-qa-offline/source
PIN=7b9eb8c82a290d06e719ee4990c2020076bbd11b
PYTHON=/srv/vinto-qa-offline/venv/bin/python
SECRET=/etc/vinto-qa/role-reference.password
QA=vinto-qa-postgres
DB=vinto_qa_offline

script_ok(){
  [ -f "$1" ] && [ ! -L "$1" ] &&
  [ "$(git hash-object "$1")" = "$2" ] && bash -n "$1" ||
  deny 'dependency_script_missing_or_changed'
}
script_ok "$C3" "$C3_BLOB"
script_ok "$BACKUP" "$BACKUP_BLOB"

# These are valid AFTER reference import; neither presupposes an empty data baseline.
c3_result="$(bash "$C3" audit)" || deny 'postmigration_audit_failed'
for expected in \
  OFF03D6C3_AUDIT=PASS_READ_ONLY \
  OFF03D6C3_MIGRATION_HISTORY_31=PASS \
  OFF03D6C3_MIGRATION_CHECKSUMS=PASS \
  OFF03D6C3_POSTMIGRATION_ACL=PASS \
  OFF03D6C3_PILOT_TVC_RUNNING=PASS; do
  printf '%s\n' "$c3_result" | grep -Fxq "$expected" ||
    deny 'postmigration_history_ACL_or_pilot_not_pass'
done
echo 'OFF03D7C5A_MIGRATIONS_31_CHECKSUMS_ACL=PASS'
echo 'OFF03D7C5A_PILOT_TVC_STATUS=PASS_AT_AUDIT'

backup_result="$(bash "$BACKUP" verify)" || deny 'postDDL_backup_verify_failed'
for expected in \
  OFF03D7C4_BACKUP_INTEGRITY=PASS \
  OFF03D7C4_RESTORE_METADATA=PASS \
  OFF03D7C4_VERIFY=PASS_FILE_INTEGRITY; do
  printf '%s\n' "$backup_result" | grep -Fxq "$expected" ||
    deny 'postDDL_backup_hash_or_restore_proof_not_pass'
done
echo 'OFF03D7C5A_POST_DDL_BACKUP=PASS_FILE_INTEGRITY'

# C3 above also pins the protected checkout SHA and verifies unmodified migrations.
[ -d "$SOURCE/.git" ] && [ ! -L "$SOURCE" ] &&
[ "$(git -C "$SOURCE" rev-parse HEAD)" = "$PIN" ] &&
[ -z "$(git -C "$SOURCE" status --porcelain --untracked-files=all)" ] ||
  deny 'QA_checkout_dirty_or_changed'
# D6C3 has already executed this interpreter and verified sys.prefix == QA venv.
# Python venv/bin/python is often a valid symlink; rejecting it is incorrect.
VENV=/srv/vinto-qa-offline/venv
[ -d "$VENV" ] && [ ! -L "$VENV" ] && [ -x "$PYTHON" ] ||
  deny 'QA_python_venv_invalid'
for row in \
  'backend/import_reference.py:26ef9a3b3ce74f9a1df9a47b411758d8ceb1dc24' \
  'backend/app/seed/reference.py:622dadfe7dbd0b77cde36654733cb4eeda97f415' \
  'backend/app/seed/bundle.py:e50d9842a7e071b754144c04037dc66a39c04bdc' \
  'backend/seed_data/manifest.json:892cabe2acc80e60abf0c52aaf6ff616b84a5bae'; do
  IFS=: read -r path expected <<< "$row"
  [ -f "$SOURCE/$path" ] && [ ! -L "$SOURCE/$path" ] &&
  [ "$(git hash-object "$SOURCE/$path")" = "$expected" ] &&
  [ "$(git -C "$SOURCE" rev-parse "HEAD:$path")" = "$expected" ] ||
  deny 'importer_or_manifest_changed'
done
[ -f "$SECRET" ] && [ ! -L "$SECRET" ] &&
[ "$(stat -c '%U:%a' "$SECRET")" = root:600 ] &&
[ "$(stat -c '%U:%a' /etc/vinto-qa)" = root:700 ] ||
  deny 'QA_secret_permissions_changed'

[ "$(docker inspect -f '{{.Config.Image}}' "$QA" 2>/dev/null || true)" = postgres:17 ] &&
[ "$(docker inspect -f '{{.State.Health.Status}}' "$QA" 2>/dev/null || true)" = healthy ] &&
[ "$(docker inspect -f '{{index .Config.Labels "org.baltrek.environment"}}' "$QA" 2>/dev/null || true)" = qa ] &&
[ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$QA" 2>/dev/null || true)" = vinto-qa-internal ] &&
[ "$(docker inspect -f '{{range (index .HostConfig.PortBindings "5432/tcp")}}{{.HostIp}}:{{.HostPort}}{{end}}' "$QA" 2>/dev/null || true)" = 127.0.0.1:6554 ] ||
  deny 'QA_container_identity_changed'
echo 'OFF03D7C5A_QA_ISOLATION=PASS'

# Full bundle integrity plus its source checksum, without printing its content.
# -E suppresses user-provided Python environment; cwd is the fixed, Git-pinned backend.
CHECKSUM="$(cd "$SOURCE/backend" &&
  "$PYTHON" -E -s -B -c 'from app.seed.bundle import load_bundle; print(load_bundle().source_checksum)')" ||
  deny 'approved_bundle_validation_failed'
[[ "$CHECKSUM" =~ ^[0-9a-f]{64}$ ]] || deny 'bundle_checksum_invalid'
echo 'OFF03D7C5A_CANONICAL_BUNDLE=PASS'

# Aggregate metadata only: four exact forms, eight exact machine associations,
# 26 versions published, one complete import batch matching the canonical SHA.
# No user names, hashes, UUIDs or captured values are selected.
SQL="$(cat <<SQL
WITH wanted(code, version_number) AS (
  VALUES ('VINTO-P1-18',2),('VINTO-P1-22',2),
         ('VINTO-P1-26',3),('VINTO-P1-27',2)
), versions AS (
  SELECT f.code, fv.id, fv.status, fv.area
  FROM wanted w
  JOIN vinto_config.form f ON f.code=w.code
  JOIN vinto_config.form_version fv
    ON fv.form_id=f.id AND fv.version_number=w.version_number
), pairs AS (
  SELECT v.code AS form_code, m.code AS machine_code
  FROM versions v
  JOIN vinto_config.form_version_machine fvm ON fvm.form_version_id=v.id
  JOIN vinto_master.machine m ON m.id=fvm.machine_id
), exact_pairs AS (
  SELECT f.code AS form_code, m.code AS machine_code
  FROM (VALUES ('VINTO-P1-18'),('VINTO-P1-22'),
               ('VINTO-P1-26'),('VINTO-P1-27')) f(code)
  CROSS JOIN (VALUES ('MP1'),('MP3')) m(code)
)
SELECT CASE WHEN
 current_database()='vinto_qa_offline'
 AND current_user='vinto_qa_bootstrap'
 AND (SELECT count(*) FROM vinto_meta.schema_migration)=31
 AND (SELECT count(*) FROM vinto_master.sector)=3
 AND (SELECT count(*) FROM vinto_master.profile)=5
 AND (SELECT count(*) FROM vinto_master.machine)=18
 AND (SELECT count(*) FROM vinto_master.article)=315
 AND (SELECT count(*) FROM vinto_master.article_machine)=340
 AND (SELECT count(*) FROM vinto_config.form)=26
 AND (SELECT count(*) FROM vinto_config.form_version)=26
 AND (SELECT count(*) FROM vinto_config.form_version WHERE status='published')=26
 AND (SELECT count(*) FROM vinto_audit.import_batch)=1
 AND (SELECT count(*) FROM vinto_audit.import_batch
       WHERE status='completed'
       AND source='vinto-reference-bobinas'
       AND source_checksum='$CHECKSUM')=1
 AND (SELECT count(*) FROM versions)=4
 AND (SELECT count(*) FROM versions WHERE status='published' AND area='quality')=4
 AND (SELECT count(*) FROM pairs)=8
 AND NOT EXISTS (
   SELECT 1 FROM exact_pairs p WHERE NOT EXISTS (
     SELECT 1 FROM pairs actual
     WHERE actual.form_code=p.form_code AND actual.machine_code=p.machine_code))
 AND (SELECT count(*) FROM vinto_master."user")=0
 AND (SELECT count(*) FROM vinto_master.user_machine_form_grant)=0
 THEN 'PASS' ELSE 'BLOCKED' END;
SQL
)"
metadata="$(docker exec \
  -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=15000' \
  "$QA" psql -X -qAt -v ON_ERROR_STOP=1 \
    -U vinto_qa_bootstrap -d "$DB" -c "$SQL" 2>/dev/null)" ||
  deny 'QA_metadata_read_failed'
[ "$metadata" = PASS ] || deny 'postimport_catalog_batch_or_machines_mismatch'
echo 'OFF03D7C5A_FULL_REFERENCE_CATALOG=PASS_COUNTS'
echo 'OFF03D7C5A_IMPORT_BATCH=PASS_CHECKSUM_COMPLETE'
echo 'OFF03D7C5A_QUALITY_PUBLISHED=PASS_FOUR_VERSIONS'
echo 'OFF03D7C5A_MP1_MP3=PASS_EIGHT_EXACT_PAIRS'
echo 'OFF03D7C5A_USER_AND_GRANTS=ZERO'

# Independent second dry-run, with READ ONLY enforced by libpq for *every*
# session. This does not perform any INSERT/UPDATE and does not call --apply.
MODE=audit "$PYTHON" -I -B - <<'PY'
import os
import re
import subprocess
from pathlib import Path

def block(reason):
    print("OFF03D7C5A_BLOCKED: "+reason)
    raise SystemExit(1)

try:
    password=Path("/etc/vinto-qa/role-reference.password").read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[a-f0-9]{64}",password):
        block("reference_password_format")
    env={
        "PATH":"/usr/bin:/bin",
        "HOME":"/srv/vinto-qa-offline",
        "LC_ALL":"C",
        "APP_ENV":"qa",
        "PG_PRIVILEGE_MODE":"hardened",
        "REFERENCE_DATABASE_URL":
           "postgresql://vinto_reference@127.0.0.1:6554/vinto_qa_offline",
        "PGPASSWORD":password,
        "PGOPTIONS":"-c default_transaction_read_only=on -c statement_timeout=120000",
        "PYTHONNOUSERSITE":"1",
        "PYTHONDONTWRITEBYTECODE":"1",
    }
    backend="/srv/vinto-qa-offline/source/backend"
    p=subprocess.run([
        "/srv/vinto-qa-offline/venv/bin/python",
        "-E","-s","-B",backend+"/import_reference.py","--target","dev",
    ], cwd=backend,env=env, capture_output=True,text=True,timeout=130)
    if p.returncode != 0:
        block("postimport_dry_run_failed")
    out=p.stdout
    if ("Base de destino: vinto_qa_offline (target=dev, modo=dry-run)" not in out
        or ("CONSISTENT / NO CHANGES" not in out and "NO-OP:" not in out)
        or "CONFLICT / DRIFT" in out):
        block("postimport_drift_or_nonidempotence")
    print("OFF03D7C5A_IDEMPOTENCE=PASS_READ_ONLY")
    print("OFF03D7C5A_AUDIT=PASS_READ_ONLY")
    print("NO_DATABASE_WRITES=PASS")
except SystemExit:
    raise
except BaseException as ex:
    block("unexpected_"+type(ex).__name__)
PY
