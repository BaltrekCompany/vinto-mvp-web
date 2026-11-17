#!/usr/bin/env bash
# OFF-03D.6C1: inspect only; NEVER apply migrations or write to any DB.
set -Eeuo pipefail
set +x
export LC_ALL=C
die() { echo "OFF03D6C1_BLOCKED: $*" >&2; exit 1; }
usage() { echo 'sudo bash scripts/off-03d6c1-qa-migrator-preflight.sh inspect'; }
[ "$#" -eq 1 ] || { usage >&2; exit 2; }
case "$1" in
  --help|-h|help) usage; exit 0 ;;
  inspect) ;;
  *) usage >&2; die 'solo inspect' ;;
esac
[ "$(id -u)" -eq 0 ] || die 'requiere sudo'
for c in bash docker git stat find awk sed seq basename; do
  command -v "$c" >/dev/null 2>&1 || die "falta $c"
done
B2=/tmp/vinto-off03d6b2-qa-backup-restore.sh
B2_BLOB=8d7193acfe59acc243bff47c65048705f2847c1d
ROOT=/srv/vinto-qa-offline
SOURCE=/srv/vinto-qa-offline/source
VENV=/srv/vinto-qa-offline/venv
PYTHON=/srv/vinto-qa-offline/venv/bin/python
SECRET=/etc/vinto-qa/role-migrator.password
PIN=7b9eb8c82a290d06e719ee4990c2020076bbd11b
QA=vinto-qa-postgres
DB=vinto_qa_offline
[ -f "$B2" ] && [ ! -L "$B2" ] || die 'gate B2 ausente'
[ "$(git hash-object "$B2")" = "$B2_BLOB" ] || die 'gate B2 alterado'
# B2 verify passes only BEFORE DDL. Do not call B2 inspect after a backup exists.
bash "$B2" verify || die 'backup B2 no restaurable o QA cambio'
echo 'OFF03D6C1_BACKUP_RESTORE_GATE=PASS'
[ -d "$ROOT" ] && [ ! -L "$ROOT" ] &&
  [ "$(stat -c '%U:%a' "$ROOT")" = root:700 ] || die 'raiz QA insegura'
# Python venv commonly symlinks bin/python to its base interpreter.
# Reject a symlinked VENV directory, not its valid executable.
[ -d "$VENV" ] && [ ! -L "$VENV" ] && [ -x "$PYTHON" ] ||
  die 'venv QA ausente o no ejecutable'
"$PYTHON" - <<'PY_VENV'
import sys
from pathlib import Path
venv = Path('/srv/vinto-qa-offline/venv').resolve(strict=True)
assert Path(sys.prefix).resolve(strict=True) == venv, 'wrong_venv_prefix'
assert sys.prefix != sys.base_prefix, 'not_isolated_venv'
import psycopg
import pydantic_settings
print('OFF03D6C1_VENV_IDENTITY=PASS')
PY_VENV
[ "$(git -C "$SOURCE" rev-parse HEAD)" = "$PIN" ] ||
  die 'checkout QA en SHA inesperado'
[ -z "$(git -C "$SOURCE" status --porcelain --untracked-files=all)" ] ||
  die 'checkout QA con cambios'
[ "$(git -C "$SOURCE" symbolic-ref --quiet HEAD 2>/dev/null || true)" = '' ] ||
  die 'checkout QA no detached'
for dot in "$SOURCE/.env" "$SOURCE/backend/.env"; do
  [ ! -e "$dot" ] && [ ! -L "$dot" ] ||
    die 'archivo .env no esperado en checkout QA'
done
[ -d "$SOURCE/backend/migrations" ] || die 'carpeta migraciones ausente'
count="$(git -C "$SOURCE" ls-files 'backend/migrations/*.sql' | awk 'END{print NR+0}')"
[ "$count" = 31 ] || die 'Git no contiene 31 migraciones'
found="$(find "$SOURCE/backend/migrations" -maxdepth 1 -type f -name '*.sql' | awk 'END{print NR+0}')"
[ "$found" = 31 ] || die 'archivos SQL extra o ausentes'
i=1
while [ "$i" -le 31 ]; do
  file="$(git -C "$SOURCE" ls-files 'backend/migrations/*.sql' | sed -n "$i"'p')"
  name="$(basename "$file")"
  prefix="$(printf '%04d_' "$i")"
  case "$name" in "$prefix"*.sql) ;; *) die 'secuencia migraciones incorrecta' ;; esac
  [ -f "$SOURCE/$file" ] && [ ! -L "$SOURCE/$file" ] ||
    die 'migracion ausente o symlink'
  [ "$(git hash-object "$SOURCE/$file")" = "$(git -C "$SOURCE" rev-parse "HEAD:$file")" ] ||
    die 'contenido migracion difiere del SHA pin'
  i=$((i + 1))
done
echo 'OFF03D6C1_CHECKOUT_MIGRATIONS_31=PASS'
echo 'OFF03D6C1_CHECKOUT_SHA=7b9eb8c82a290d06e719ee4990c2020076bbd11b'
[ "$(stat -c '%U:%a' "$SECRET")" = root:600 ] ||
  die 'secreto migrador QA sin permisos root 0600'
QA_START="$(docker exec \
  -e PGOPTIONS='-c default_transaction_read_only=on -c statement_timeout=5000' \
  "$QA" psql -X -qAt -v ON_ERROR_STOP=1 -U vinto_qa_bootstrap -d "$DB" \
  -c 'SELECT extract(epoch FROM pg_postmaster_start_time())::bigint')" ||
  die 'postmaster QA inaccesible'
case "$QA_START" in *[!0-9]*|'') die 'firma postmaster no numerica' ;; esac

# Fixed host/port/db/user; only protected QA secret, no arbitrary DSN.
QA_START="$QA_START" "$PYTHON" - <<'PY'
import os
import re
from pathlib import Path
try:
    import psycopg
    secret = Path('/etc/vinto-qa/role-migrator.password').read_text(encoding='ascii').strip()
    assert re.fullmatch(r'[a-f0-9]{64}', secret), 'password_shape'
    with psycopg.connect(
        host='127.0.0.1', port=6554, dbname='vinto_qa_offline',
        user='vinto_migrator', password=secret, connect_timeout=5,
        options='-c default_transaction_read_only=on -c statement_timeout=5000',
        autocommit=True,
    ) as conn:
        row = conn.execute("""
            SELECT current_database(),current_user,inet_server_port(),
                   current_setting('default_transaction_read_only'),
                   pg_is_in_recovery(),
                   extract(epoch FROM pg_postmaster_start_time())::bigint,
                   (SELECT count(*) FROM pg_namespace WHERE nspname IN
                     ('vinto_master','vinto_config','vinto_txn',
                      'vinto_audit','vinto_auth','vinto_meta')),
                   to_regclass('vinto_meta.schema_migration') IS NULL,
                   has_database_privilege('vinto_migrator',current_database(),'CREATE'),
                   NOT has_database_privilege('public',current_database(),'CONNECT')
        """).fetchone()
        assert row == (
            'vinto_qa_offline','vinto_migrator',5432,'on',False,
            int(os.environ['QA_START']),0,True,True,True
        ), 'wrong_origin_or_state'
    print('OFF03D6C1_HOST_TO_QA_DB_IDENTITY=PASS')
    print('OFF03D6C1_REAL_ROLE_MIGRATOR=PASS')
    print('OFF03D6C1_MIGRATION_HISTORY=EMPTY')
except BaseException:
    print('OFF03D6C1_BLOCKED: host-to-QA identity/ACL/read-only test failed')
    raise SystemExit(1)
PY
echo 'OFF03D6C1_PREFLIGHT=PASS_READ_ONLY'
echo 'OFF03D6C1_MIGRATIONS=NOT_STARTED'
echo 'NO_DATABASE_WRITES=PASS'
