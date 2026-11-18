#!/usr/bin/env bash
# VINTO OFF-03D.7C5 — official QA reference bundle; read-only inspect
# and separately authorized one-shot apply. NO pilot/TVC/main changes.
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

die(){ echo "OFF03D7C5_BLOCKED: $1" >&2; exit 1; }
usage(){
  echo 'sudo -n bash scripts/off-03d7c5-qa-reference-import-gate.sh inspect'
  echo 'sudo -n env CONFIRM_QA_REFERENCE_IMPORT=YES CONFIRM_QA_TARGET=vinto_qa_offline_6554 bash scripts/off-03d7c5-qa-reference-import-gate.sh apply'
}
[ "$#" -eq 1 ] || { usage >&2; exit 2; }
case "$1" in
  --help|-h|help) usage; exit 0 ;;
  inspect|apply) MODE="$1" ;;
  *) usage >&2; die 'unsupported_operation' ;;
esac
[ "$(id -u)" -eq 0 ] || die 'sudo_required'
for c in bash docker git stat systemctl grep; do
 command -v "$c" >/dev/null || die "missing_$c"
done

if [ "$MODE" = apply ]; then
 [ "$(printenv CONFIRM_QA_REFERENCE_IMPORT 2>/dev/null || true)" = YES ] ||
  die 'CONFIRM_QA_REFERENCE_IMPORT_required'
 [ "$(printenv CONFIRM_QA_TARGET 2>/dev/null || true)" = vinto_qa_offline_6554 ] ||
  die 'CONFIRM_QA_TARGET_required'
fi

SOURCE=/srv/vinto-qa-offline/source
PYTHON=/srv/vinto-qa-offline/venv/bin/python
BACKUP_RUNNER=/tmp/vinto-off03d7c4-qa-postddl-backup-restore.sh
BACKUP_BLOB=6f772a25a9b552d792d7d2215cc5676cca56b5fe
AUDITOR=/tmp/vinto-off03d6c3-qa-postmigration-audit.sh
AUDITOR_BLOB=ebb773f88ba6740ddf4fef53f1b76de541346a85
PIN=7b9eb8c82a290d06e719ee4990c2020076bbd11b
QA=vinto-qa-postgres
SECRET=/etc/vinto-qa/role-reference.password

check_script(){
 [ -f "$1" ] && [ ! -L "$1" ] &&
 [ "$(git hash-object "$1")" = "$2" ] && bash -n "$1" ||
 die 'approved_script_missing_or_modified'
}
check_script "$BACKUP_RUNNER" "$BACKUP_BLOB"
check_script "$AUDITOR" "$AUDITOR_BLOB"

# D7C4 verify only checks the historical POST-DDL backup file/proof.
# Do NOT run the D7C4 inspect, B2 verify, or C1 inspect after new data exists.
backup_result="$(bash "$BACKUP_RUNNER" verify)" ||
 die 'post_DDL_backup_restore_proof_failed'
printf '%s\n' "$backup_result" | grep -Fxq 'OFF03D7C4_VERIFY=PASS_FILE_INTEGRITY' ||
 die 'post_DDL_backup_verify_not_pass'
printf '%s\n' "$backup_result" | grep -Fxq 'OFF03D7C4_RESTORE_METADATA=PASS' ||
 die 'post_DDL_backup_metadata_not_pass'
echo 'OFF03D7C5_POST_DDL_RECOVERY_POINT=PASS'

audit_result="$(bash "$AUDITOR" audit)" ||
 die 'postmigration_C3_audit_failed'
printf '%s\n' "$audit_result" | grep -Fxq 'OFF03D6C3_AUDIT=PASS_READ_ONLY' ||
 die 'postmigration_C3_not_pass'
printf '%s\n' "$audit_result" | grep -Fxq 'OFF03D6C3_MIGRATION_CHECKSUMS=PASS' ||
 die 'migration_checksums_not_pass'
echo 'OFF03D7C5_MIGRATIONS_ACL=PASS'

[ -d "$SOURCE/.git" ] && [ ! -L "$SOURCE" ] &&
[ "$(git -C "$SOURCE" rev-parse HEAD)" = "$PIN" ] ||
 die 'QA_source_checkout_SHA_mismatch'
[ -z "$(git -C "$SOURCE" status --porcelain --untracked-files=all)" ] ||
 die 'QA_source_not_clean'
[ -z "$(git -C "$SOURCE" symbolic-ref --quiet HEAD 2>/dev/null || true)" ] ||
 die 'QA_source_not_detached'
[ -x "$PYTHON" ] || die 'QA_venv_missing'
[ -d /etc/vinto-qa ] && [ ! -L /etc/vinto-qa ] &&
[ "$(stat -c '%U:%a' /etc/vinto-qa)" = root:700 ] ||
 die 'QA_secret_dir_insecure'
[ -f "$SECRET" ] && [ ! -L "$SECRET" ] &&
[ "$(stat -c '%U:%a' "$SECRET")" = root:600 ] ||
 die 'QA_reference_secret_missing_or_insecure'
for svc in vinto-mvp-backend vinto-mvp-frontend vinto-web; do
 systemctl is-active --quiet "$svc" || die 'pilot_service_not_running'
done
for container in vinto-mvp-postgres postgres-vinto; do
 [ "$(docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null || true)" = true ] ||
  die 'pilot_TVC_container_not_running'
done
[ "$(docker inspect -f '{{.Config.Image}}' "$QA" 2>/dev/null || true)" = postgres:17 ] ||
 die 'QA_image_changed'
[ "$(docker inspect -f '{{.State.Health.Status}}' "$QA" 2>/dev/null || true)" = healthy ] ||
 die 'QA_container_unhealthy'
[ "$(docker inspect -f '{{index .Config.Labels "org.baltrek.environment"}}' "$QA" 2>/dev/null || true)" = qa ] ||
 die 'QA_label_changed'
[ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$QA" 2>/dev/null || true)" = vinto-qa-internal ] ||
 die 'QA_network_changed'
[ "$(docker inspect -f '{{range (index .HostConfig.PortBindings "5432/tcp")}}{{.HostIp}}:{{.HostPort}}{{end}}' "$QA" 2>/dev/null || true)" = '127.0.0.1:6554' ] ||
 die 'QA_port_changed'
echo 'OFF03D7C5_QA_AND_PILOT_ISOLATION=PASS'

# These blobs match BOTH the protected QA checkout and the reviewed D7C2
# candidate. Bundle loader verifies every member SHA256 against its manifest.
for row in \
 'backend/import_reference.py:26ef9a3b3ce74f9a1df9a47b411758d8ceb1dc24' \
 'backend/app/seed/reference.py:622dadfe7dbd0b77cde36654733cb4eeda97f415' \
 'backend/app/seed/bundle.py:e50d9842a7e071b754144c04037dc66a39c04bdc' \
 'backend/app/db_guard.py:f86f9ef6bc0c3664ed2325beacb06c3c4630b268' \
 'backend/seed_data/manifest.json:892cabe2acc80e60abf0c52aaf6ff616b84a5bae'; do
 IFS=: read -r path expected <<< "$row"
 [ -f "$SOURCE/$path" ] && [ ! -L "$SOURCE/$path" ] &&
 [ "$(git hash-object "$SOURCE/$path")" = "$expected" ] &&
 [ "$(git -C "$SOURCE" rev-parse "HEAD:$path")" = "$expected" ] ||
 die 'official_bundle_or_importer_hash_mismatch'
done
echo 'OFF03D7C5_OFFICIAL_SOURCE=PASS_PINNED'

# This Python process never logs a password/DSN, and invokes the existing
# official importer with a fixed, sanitized environment.
MODE="$MODE" "$PYTHON" -I -B - <<'PY'
import os
import re
import subprocess
from pathlib import Path

def block(reason):
    print("OFF03D7C5_BLOCKED: " + reason)
    raise SystemExit(1)

def run(cmd, *, cwd=None, env=None, timeout=120):
    p=subprocess.run(cmd, cwd=cwd, env=env, text=True,
                     capture_output=True, timeout=timeout)
    if p.returncode:
        block("command_failed_" + str(p.returncode))
    return p.stdout.strip()

try:
    import psycopg
    mode=os.environ.get("MODE","")
    if mode not in ("inspect","apply"):
        block("mode_invalid")
    backend=Path("/srv/vinto-qa-offline/source/backend")
    python="/srv/vinto-qa-offline/venv/bin/python"
    secret=Path("/etc/vinto-qa/role-reference.password")
    password=secret.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[a-f0-9]{64}", password):
        block("reference_secret_format")
    with psycopg.connect(
        host="127.0.0.1",port=6554,dbname="vinto_qa_offline",
        user="vinto_reference",password=password,
        connect_timeout=5,autocommit=True,
        options="-c default_transaction_read_only=on -c statement_timeout=10000"
    ) as c:
        identity=c.execute("""
          SELECT current_database(),current_user,inet_server_port(),
            NOT has_database_privilege('public',current_database(),'CONNECT'),
            NOT has_database_privilege('vinto_reference',current_database(),'CREATE'),
            NOT has_schema_privilege('vinto_reference','vinto_meta','USAGE'),
            has_table_privilege('vinto_reference','vinto_master.profile','INSERT')
        """).fetchone()
        if identity != ("vinto_qa_offline","vinto_reference",5432,True,True,True,True):
            block("effective_QA_role_or_target_changed")
    print("OFF03D7C5_REFERENCE_ROLE_TARGET=PASS")

    clean_env={
      "PATH":"/usr/bin:/bin","HOME":"/srv/vinto-qa-offline",
      "APP_ENV":"qa","PG_PRIVILEGE_MODE":"hardened",
      "REFERENCE_DATABASE_URL":"postgresql://vinto_reference@127.0.0.1:6554/vinto_qa_offline",
      "PGPASSWORD":password,
      "PYTHONDONTWRITEBYTECODE":"1","PYTHONNOUSERSITE":"1",
    }
    # Load and validate complete official bundle independently of database.
    validator=r'''
from app.seed.bundle import load_bundle
b=load_bundle()
expected={"VINTO-P1-18":2,"VINTO-P1-22":2,
 "VINTO-P1-26":3,"VINTO-P1-27":2}
actual={f["code"]:f["version_number"] for f in b.forms if f["code"] in expected}
assert actual==expected
assert {m["code"] for m in b.machines if m["code"] in ("MP1","MP3")}=={"MP1","MP3"}
assert any(p["code"]=="CALIDAD" for p in b.profiles)
assert b.manifest.get("scope",{}).get("candidate") is not True
'''
    run([python,"-E","-s","-B","-c",validator],
        cwd=str(backend),env=clean_env,timeout=45)
    print("OFF03D7C5_CANONICAL_BUNDLE=PASS")

    # Fixed bootstrap read-only metadata; do not expose identities or rows.
    query="""SELECT CASE WHEN
      current_database()='vinto_qa_offline'
      AND current_user='vinto_qa_bootstrap'
      AND (SELECT count(*) FROM vinto_meta.schema_migration)=31
      AND (SELECT count(*) FROM vinto_master."user")=0
      AND (SELECT count(*) FROM vinto_master.user_machine_form_grant)=0
      AND (SELECT count(*) FROM vinto_master.profile)=0
      AND (SELECT count(*) FROM vinto_master.sector)=0
      AND (SELECT count(*) FROM vinto_master.machine)=0
      AND (SELECT count(*) FROM vinto_config.form)=0
      AND (SELECT count(*) FROM vinto_config.form_version)=0
      AND (SELECT count(*) FROM vinto_audit.import_batch)=0
      THEN 'PASS' ELSE 'BLOCKED' END;"""
    def query_qa(sql):
        return run(["/usr/bin/docker","exec",
          "-e","PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=15000",
          "vinto-qa-postgres","psql","-X","-qAt","-v","ON_ERROR_STOP=1",
          "-U","vinto_qa_bootstrap","-d","vinto_qa_offline","-c",sql],
          env={"PATH":"/usr/bin:/bin","LC_ALL":"C"},timeout=45)
    if query_qa(query)!="PASS":
        block("QA_catalog_not_empty_or_changed")
    print("OFF03D7C5_REFERENCE_BASELINE=EMPTY_QA_ONLY")

    importer=str(backend/"import_reference.py")
    dry=run([python,"-E","-s","-B",importer,"--target","dev"],
            cwd=str(backend),env=clean_env)
    if ("Base de destino: vinto_qa_offline (target=dev, modo=dry-run)" not in dry
        or "Plan (dry-run, 0 filas escritas):" not in dry
        or "Pendiente:" not in dry
        or "CONFLICT / DRIFT" in dry):
        block("reference_dry_run_contract")
    print("OFF03D7C5_REFERENCE_DRY_RUN=PASS_READ_ONLY")

    if mode=="inspect":
        print("OFF03D7C5_IMPORT=NOT_AUTHORIZED")
        print("OFF03D7C5_PREFLIGHT=PASS_READ_ONLY")
        print("NO_DATABASE_WRITES=PASS")
        raise SystemExit(0)
    if os.environ.get("CONFIRM_QA_REFERENCE_IMPORT")!="YES" or \
       os.environ.get("CONFIRM_QA_TARGET")!="vinto_qa_offline_6554":
        block("apply_not_authorized")
    result=run([python,"-E","-s","-B",importer,"--target","dev","--apply"],
               cwd=str(backend),env=clean_env,timeout=900)
    if ("Base de destino: vinto_qa_offline (target=dev, modo=apply)" not in result
        or "Importación completada;" not in result):
        block("import_transaction_not_confirmed")
    print("OFF03D7C5_REFERENCE_APPLY=PASS_ONE_QA_TRANSACTION")
    post="""WITH wanted(code,version) AS (VALUES
      ('VINTO-P1-18',2),('VINTO-P1-22',2),
      ('VINTO-P1-26',3),('VINTO-P1-27',2)),
    chosen AS (
      SELECT fv.id,fv.status,fv.area FROM wanted w
      JOIN vinto_config.form f ON f.code=w.code
      JOIN vinto_config.form_version fv
       ON fv.form_id=f.id AND fv.version_number=w.version)
    SELECT CASE WHEN
      current_database()='vinto_qa_offline'
      AND current_user='vinto_qa_bootstrap'
      AND (SELECT count(*) FROM vinto_meta.schema_migration)=31
      AND (SELECT count(*) FROM chosen)=4
      AND (SELECT count(*) FROM chosen WHERE status='published' AND area='quality')=4
      AND (SELECT count(*) FROM vinto_config.form_version_machine m
           JOIN chosen c ON m.form_version_id=c.id)=8
      AND (SELECT count(*) FROM vinto_audit.import_batch WHERE status='completed')=1
      AND (SELECT count(*) FROM vinto_audit.import_batch)=1
      AND (SELECT count(*) FROM vinto_master."user")=0
      AND (SELECT count(*) FROM vinto_master.user_machine_form_grant)=0
      THEN 'PASS' ELSE 'BLOCKED' END;"""
    if query_qa(post)!="PASS":
        block("postimport_metadata_mismatch")
    print("OFF03D7C5_FOUR_QUALITY_VERSIONS=PUBLISHED")
    print("OFF03D7C5_MACHINE_VERSION_LINKS=8")
    print("OFF03D7C5_USER_AND_GRANTS=NOT_CREATED")
    second=run([python,"-E","-s","-B",importer,"--target","dev"],
               cwd=str(backend),env=clean_env)
    if ("CONSISTENT / NO CHANGES" not in second and "NO-OP:" not in second) \
       or "CONFLICT / DRIFT" in second:
        block("postimport_drift_or_nonidempotence")
    print("OFF03D7C5_IMPORT=PASS_QA_ONLY")
except SystemExit:
    raise
except BaseException as e:
    block("unexpected_"+type(e).__name__)
PY
