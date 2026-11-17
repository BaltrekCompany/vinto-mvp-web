#!/usr/bin/env bash
# VINTO OFF-03D.6B1: QA-only checkout and migrator Python venv (no database writes).
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C

die() { echo "OFF03D6B1_BLOCKED: $*" >&2; exit 1; }
usage() {
  echo 'sudo bash scripts/off-03d6b1-qa-checkout-venv.sh inspect'
  echo 'sudo env CONFIRM_QA_STAGE=YES bash scripts/off-03d6b1-qa-checkout-venv.sh prepare'
  echo 'sudo bash scripts/off-03d6b1-qa-checkout-venv.sh verify'
}
case "$#" in 1) ;; *) usage >&2; exit 2 ;; esac
case "$1" in
  -h|--help|help) usage; exit 0 ;;
  inspect|prepare|verify) OP="$1" ;;
  *) usage >&2; die 'operacion no soportada' ;;
esac

[ "$(id -u)" -eq 0 ] || die 'requiere sudo'
for c in git bash docker python3 stat install; do
  command -v "$c" >/dev/null 2>&1 || die "falta $c"
done

# Fixed, isolated paths and pinned checkout. Never accept a caller-supplied DSN or git ref.
ROOT=/srv/vinto-qa-offline
SOURCE=/srv/vinto-qa-offline/source
VENV=/srv/vinto-qa-offline/venv
BACKUPS=/srv/vinto-qa-offline/backups
PIN=7b9eb8c82a290d06e719ee4990c2020076bbd11b
REMOTE=https://github.com/BaltrekCompany/vinto-mvp-web.git
SOURCE_BRANCH=feat/off-03d6a-qa-staging-preflight

D5=/tmp/vinto-off03d5-qa-migration-preflight.sh
D5_BLOB=f296b71930a8820abea8666fb1aac01a16ede9e6
D6A=/tmp/vinto-off03d6a-qa-staging-preflight.sh
D6A_BLOB=b52d2b2f5b9615b279163a9bfc1519b6331a94c4

check_script() {
  local path="$1" sha="$2"
  [ -f "$path" ] && [ ! -L "$path" ] || die 'gate anterior ausente o symlink'
  [ "$(git hash-object "$path")" = "$sha" ] || die 'gate anterior modificado'
}
check_d5() {
  check_script "$D5" "$D5_BLOB"
  bash "$D5" inspect || die 'OFF-03D.5 no cumple'
}
check_empty() {
  [ -d /srv ] && [ ! -L /srv ] || die '/srv no es un directorio normal'
  for p in "$ROOT" "$SOURCE" "$VENV" "$BACKUPS"; do
    [ ! -e "$p" ] && [ ! -L "$p" ] ||
      die 'ruta QA ya existe; no sobrescribir, revisar antes de reintentar'
  done
}
inspect() {
  check_d5
  check_script "$D6A" "$D6A_BLOB"
  bash "$D6A" inspect || die 'OFF-03D.6A no cumple'
  check_empty
  echo 'OFF03D6B1_PREFLIGHT=PASS_READ_ONLY'
  echo 'OFF03D6B1_FILESYSTEM_WRITES=NONE'
}
verify() {
  check_d5
  [ -d "$ROOT" ] && [ ! -L "$ROOT" ] || die 'directorio QA ausente'
  [ "$(stat -c '%U:%a' "$ROOT")" = root:700 ] || die 'root QA sin proteccion 0700'
  [ -d "$SOURCE/.git" ] && [ ! -L "$SOURCE" ] || die 'checkout QA ausente'
  [ "$(git -C "$SOURCE" remote get-url origin)" = "$REMOTE" ] ||
    die 'remote Git no es el esperado'
  [ "$(git -C "$SOURCE" rev-parse --verify HEAD)" = "$PIN" ] ||
    die 'checkout QA no coincide con commit aprobado'
  [ -z "$(git -C "$SOURCE" status --porcelain --untracked-files=all)" ] ||
    die 'checkout QA no esta limpio'
  [ "$(git -C "$SOURCE" symbolic-ref --quiet HEAD 2>/dev/null || true)" = '' ] ||
    die 'checkout QA no esta detached'
  [ -d "$BACKUPS" ] && [ ! -L "$BACKUPS" ] ||
    die 'carpeta de backup QA ausente'
  [ "$(stat -c '%U:%a' "$BACKUPS")" = root:700 ] ||
    die 'backups QA sin proteccion 0700'
  [ -x "$VENV/bin/python" ] && [ ! -L "$VENV" ] ||
    die 'venv QA no disponible'
  "$VENV/bin/python" -c 'import psycopg, pydantic_settings; print("OFF03D6B1_PYTHON_IMPORTS=PASS")' ||
    die 'dependencias Python QA no verificadas'
  SOURCE="$SOURCE" "$VENV/bin/python" - <<'PY'
import os
import re
from pathlib import Path
migration_dir = Path(os.environ["SOURCE"]) / "backend" / "migrations"
names = sorted(p.name for p in migration_dir.glob("*.sql"))
assert len(names) == 31, "migration_count"
assert all(re.fullmatch(r"[0-9]{4}_[a-z0-9_]+[.]sql", n) for n in names)
assert [int(n[:4]) for n in names] == list(range(1, 32)), "migration_sequence"
print("OFF03D6B1_MIGRATIONS_MANIFEST=31")
PY
  echo "OFF03D6B1_CHECKOUT_SHA=$PIN"
  echo 'OFF03D6B1_CHECKOUT=PASS_DETACHED_CLEAN'
  echo 'OFF03D6B1_VENV=PASS_ISOLATED'
  echo 'OFF03D6B1_BACKUP=NOT_CREATED'
  echo 'OFF03D6B1_MIGRATIONS=NOT_STARTED'
  echo 'OFF03D6B1_VERIFY=PASS_NO_DDL'
}
prepare() {
  [ "$(printenv CONFIRM_QA_STAGE 2>/dev/null || true)" = YES ] ||
    die 'requiere CONFIRM_QA_STAGE=YES'
  inspect
  echo '=== QA: crear solo directorio protegido, checkout y venv ==='
  install -d -m 0700 "$ROOT"
  # Clone without checkout; the tree is populated only at the exact pinned commit.
  git -c init.templateDir=/dev/null clone --no-checkout --single-branch \
    --branch "$SOURCE_BRANCH" -- "$REMOTE" "$SOURCE" ||
    die 'git clone QA fallo; conservar estado para auditoria, NO reintentar a ciegas'
  git -C "$SOURCE" checkout --detach "$PIN" ||
    die 'checkout SHA QA fallido'
  [ "$(git -C "$SOURCE" rev-parse --verify HEAD)" = "$PIN" ] ||
    die 'SHA QA distinto al fijado'
  [ -z "$(git -C "$SOURCE" status --porcelain --untracked-files=all)" ] ||
    die 'checkout QA no esta limpio'
  python3 -m venv "$VENV" ||
    die 'fallo creando venv QA'
  "$VENV/bin/python" -m pip install --no-input --disable-pip-version-check \
    --only-binary=:all: 'psycopg[binary]==3.3.6' 'pydantic-settings==2.15.0' ||
    die 'pip QA fallido; no tocar piloto ni reintentar sin inspeccion'
  install -d -m 0700 "$BACKUPS"
  verify
  echo 'OFF03D6B1_PREPARE=PASS_FILES_ONLY'
  echo 'NO_DATABASE_WRITES=PASS'
}
case "$OP" in
  inspect) inspect ;;
  prepare) prepare ;;
  verify) verify ;;
esac
