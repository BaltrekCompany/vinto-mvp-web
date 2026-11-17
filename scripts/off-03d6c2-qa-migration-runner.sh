#!/usr/bin/env bash
# VINTO OFF-03D.6C2: strict QA-only one-shot migration and ACL runner.
# Inspect is read-only. Apply is intentionally blocked without two explicit gates.
# NEVER use this runner against pilot/TVC or through a caller-provided DSN.
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
# Never execute a caller-supplied binary via an untrusted PATH in root context.
export PATH=/usr/sbin:/usr/bin:/sbin:/bin

die() { echo "OFF03D6C2_BLOCKED: $*" >&2; exit 1; }
usage() {
  echo 'sudo bash scripts/off-03d6c2-qa-migration-runner.sh inspect'
  echo 'sudo env CONFIRM_QA_MIGRATIONS=YES CONFIRM_QA_TARGET=vinto_qa_offline_6554 bash scripts/off-03d6c2-qa-migration-runner.sh apply'
}
[ "$#" -eq 1 ] || { usage >&2; exit 2; }
case "$1" in
  -h|--help|help) usage; exit 0 ;;
  inspect|apply) MODE="$1" ;;
  *) usage >&2; die 'modo no soportado' ;;
esac
[ "$(id -u)" -eq 0 ] || die 'se requiere sudo'
for cmd in git bash docker stat; do
  command -v "$cmd" >/dev/null 2>&1 || die "falta $cmd"
done
if [ "$MODE" = apply ]; then
  [ "$(printenv CONFIRM_QA_MIGRATIONS 2>/dev/null || true)" = YES ] ||
    die 'CONFIRM_QA_MIGRATIONS=YES obligatorio'
  [ "$(printenv CONFIRM_QA_TARGET 2>/dev/null || true)" = vinto_qa_offline_6554 ] ||
    die 'CONFIRM_QA_TARGET=vinto_qa_offline_6554 obligatorio'
fi

C1=/tmp/vinto-off03d6c1-qa-migrator-preflight.sh
C1_BLOB=376bad3820642ac0efa038222f171bd5f2d97607
SOURCE=/srv/vinto-qa-offline/source
PYTHON=/srv/vinto-qa-offline/venv/bin/python
PIN=7b9eb8c82a290d06e719ee4990c2020076bbd11b

[ -f "$C1" ] && [ ! -L "$C1" ] || die 'script C1 exacto ausente'
[ "$(git hash-object "$C1")" = "$C1_BLOB" ] || die 'script C1 alterado'
# This runs before any write, while B2's pre-DDL fingerprint must still match.
bash "$C1" inspect || die 'OFF-03D.6C1 no cumple'
[ "$(git -C "$SOURCE" rev-parse HEAD)" = "$PIN" ] || die 'checkout SHA inesperado'
[ -x "$PYTHON" ] || die 'Python QA no ejecutable'

# Both modes use the isolated QA venv, fixed host/port/database/user, and
# a fresh environment. Password never appears in CLI args, SQL, or log output.
MODE="$MODE" "$PYTHON" -I -B - <<'PY'
import os
import re
import subprocess
import sys
from pathlib import Path

def die(code):
    print("OFF03D6C2_BLOCKED: " + code)
    raise SystemExit(1)

try:
    import psycopg
    mode = os.environ.get("MODE", "")
    if mode not in ("inspect", "apply"):
        die("invalid_mode")
    root = Path("/srv/vinto-qa-offline/source")
    backend = root / "backend"
    sql_dir = backend / "roles"
    script = backend / "migrate.py"
    python = Path("/srv/vinto-qa-offline/venv/bin/python")
    secret_path = Path("/etc/vinto-qa/role-migrator.password")
    password = secret_path.read_text(encoding="ascii").strip()
    if not re.fullmatch(r"[a-f0-9]{64}", password):
        die("invalid_QA_secret")

    # All SQL/DDL file contents must be exactly those of the pinned checkout.
    role_files = (
        "02_schema_grants.sql",
        "03_table_grants.sql",
        "03b_d3b1_restrict_catalog_writes.sql",
        "04_function_grants.sql",
        "05_no_default_privileges.sql",
        "06_public_and_meta_protection.sql",
        "07_verification_queries.sql",
        "08_release_preflight.sql",
    )
    if not script.is_file():
        die("missing_pinned_migrator")
    for file in ("backend/migrate.py",) + tuple("backend/roles/" + n for n in role_files):
        path = root / file
        if not path.is_file() or path.is_symlink():
            die("missing_or_symlinked_SQL")
        expected = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD:" + file],
            check=True, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        actual = subprocess.run(
            ["git", "hash-object", str(path)],
            check=True, capture_output=True, text=True, timeout=10,
        ).stdout.strip()
        if actual != expected:
            die("migrator_or_ACL_hash_mismatch")
    print("OFF03D6C2_PINNED_MIGRATOR_ACL=PASS")

    # Check host-to-container instance identity again immediately before DDL.
    qa = "vinto-qa-postgres"
    result = subprocess.run([
        "docker", "exec", "-e",
        "PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=5000",
        qa, "psql", "-X", "-qAt", "-v", "ON_ERROR_STOP=1",
        "-U", "vinto_qa_bootstrap", "-d", "vinto_qa_offline",
        "-c", "SELECT extract(epoch FROM pg_postmaster_start_time())::bigint",
    ], check=True, capture_output=True, text=True, timeout=15)
    start = int(result.stdout.strip())
    fixed = dict(
        host="127.0.0.1", port=6554, dbname="vinto_qa_offline",
        user="vinto_migrator", password=password, connect_timeout=5,
        autocommit=True,
        options="-c default_transaction_read_only=on -c statement_timeout=5000",
    )
    with psycopg.connect(**fixed) as conn:
        row = conn.execute("""
            SELECT current_database(),current_user,inet_server_port(),
                   extract(epoch FROM pg_postmaster_start_time())::bigint,
                   to_regclass('vinto_meta.schema_migration') IS NULL,
                   (SELECT count(*) FROM pg_namespace WHERE nspname IN
                     ('vinto_master','vinto_config','vinto_txn',
                      'vinto_audit','vinto_auth','vinto_meta')),
                   NOT has_database_privilege('public',current_database(),'CONNECT'),
                   has_database_privilege('vinto_migrator',current_database(),'CREATE')
        """).fetchone()
        if row != ("vinto_qa_offline", "vinto_migrator", 5432,
                   start, True, 0, True, True):
            die("QA_identity_history_or_privileges_changed")
    print("OFF03D6C2_EFFECTIVE_TARGET=PASS")
    print("OFF03D6C2_HISTORY_BEFORE=EMPTY")

    # The isolated child environment cannot inherit DATABASE_URL, PGHOST, or
    # pilot/TVC env settings. The exact URL contains NO password.
    clean_env = {
        "PATH": "/usr/bin:/bin",
        "HOME": "/srv/vinto-qa-offline",
        "APP_ENV": "qa",
        "PG_PRIVILEGE_MODE": "hardened",
        "MIGRATOR_DATABASE_URL":
            "postgresql://vinto_migrator@127.0.0.1:6554/vinto_qa_offline",
        "PGPASSWORD": password,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
    }
    # --status is read-only by design. C1 has already confirmed empty history.
    status = subprocess.run(
        [str(python), "-E", "-s", "-B", str(script), "--target", "dev", "--status"],
        cwd=str(backend), env=clean_env, capture_output=True, text=True, timeout=60,
    )
    if status.returncode != 0 or status.stdout.count(": pendiente") != 31:
        die("migrator_status_not_31_pending")
    print("OFF03D6C2_MIGRATOR_STATUS=31_PENDING")

    if mode == "inspect":
        print("OFF03D6C2_PREFLIGHT=PASS_READ_ONLY")
        print("OFF03D6C2_MIGRATIONS=NOT_STARTED")
        print("NO_DATABASE_WRITES=PASS")
        raise SystemExit(0)

    # The explicit shell gates are checked above; repeat here independently.
    if (os.environ.get("CONFIRM_QA_MIGRATIONS") != "YES" or
        os.environ.get("CONFIRM_QA_TARGET") != "vinto_qa_offline_6554"):
        die("apply_not_authorized")
    # All remaining actions are real DDL on QA ONLY. No retries or partial cleanup.
    applied = subprocess.run(
        [str(python), "-E", "-s", "-B", str(script), "--target", "dev"],
        cwd=str(backend), env=clean_env, capture_output=True, text=True, timeout=900,
    )
    if applied.returncode != 0:
        die("migration_failed_no_retry_" + str(applied.returncode))
    print("OFF03D6C2_MIGRATIONS_APPLIED=31")

    checked = subprocess.run(
        [str(python), "-E", "-s", "-B", str(script), "--target", "dev", "--check"],
        cwd=str(backend), env=clean_env, capture_output=True, text=True, timeout=90,
    )
    if checked.returncode != 0 or checked.stdout.count(": aplicada") != 31:
        die("migration_checksum_check_failed")
    print("OFF03D6C2_MIGRATION_CHECKSUMS=PASS")

    # Psql meta-commands in role scripts require psql, not psycopg direct SQL.
    # Password and SQL are fed only through docker stdin, never argv or logs.
    command = (
        "IFS= read -r PGPASSWORD; export PGPASSWORD; "
        "exec psql -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 "
        "-U vinto_migrator -d vinto_qa_offline -f -"
    )
    for name in role_files:
        sql = (sql_dir / name).read_text(encoding="utf-8")
        result = subprocess.run(
            ["docker", "exec", "-i", qa, "sh", "-ceu", command],
            input=password + "\n" + sql,
            text=True, capture_output=True, timeout=90,
        )
        if result.returncode != 0:
            die("ACL_step_failed_no_retry_" + name)
        print("OFF03D6C2_ACL_STEP_PASS=" + name)

    with psycopg.connect(**fixed) as conn:
        ok = conn.execute("""
        SELECT
          (SELECT count(*) FROM vinto_meta.schema_migration)=31
          AND (SELECT min(version) FROM vinto_meta.schema_migration)=1
          AND (SELECT max(version) FROM vinto_meta.schema_migration)=31
          AND (SELECT count(*) FROM pg_namespace WHERE nspname IN
             ('vinto_master','vinto_config','vinto_txn','vinto_audit',
              'vinto_auth','vinto_meta'))=6
          AND NOT has_schema_privilege('vinto_app','vinto_meta','USAGE')
          AND NOT has_table_privilege('vinto_app','vinto_master.profile','INSERT')
          AND NOT has_table_privilege('vinto_app','vinto_master.machine','INSERT')
          AND NOT has_table_privilege('vinto_app','vinto_master.sector','INSERT')
          AND NOT has_database_privilege('public',current_database(),'CONNECT')
        """).fetchone()[0]
        if not ok:
            die("final_QA_ACL_or_history_failed")
    print("OFF03D6C2_POSTMIGRATION_ACL=PASS")
    print("OFF03D6C2_APPLY=PASS_QA_ONLY")
except SystemExit:
    raise
except BaseException as exc:
    # Keep the public log free of passwords, DSN and possible business rows.
    die("unexpected_" + type(exc).__name__)
PY
