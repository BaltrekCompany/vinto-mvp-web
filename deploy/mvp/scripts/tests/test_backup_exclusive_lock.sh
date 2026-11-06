#!/usr/bin/env bash
# E1-09 regression: lock must reject concurrent backup/verify/prune-apply
# before credential access, Docker or any dump mutation.
set -euo pipefail

if ! command -v flock >/dev/null 2>&1; then
  echo "FAIL: flock unavailable for test" >&2
  exit 1
fi

source_root="$(cd "$(dirname "$BASH_SOURCE")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

mkdir -p "$tmp/ops" "$tmp/backups"
chmod 700 "$tmp/backups"
cp "$source_root/backup.sh" "$source_root/lib_common.sh" "$tmp/ops/"
chmod 700 "$tmp/ops"
# No docker/.env exists in this fixture. A command that bypasses the lock
# must still fail closed at the environment contract before touching DB.
lock="$tmp/backups/.backup-operations.lock"
output="$tmp/last-output"

invoke() {
  env CONFIRM=yes VINTO_MVP_BACKUP_DIR="$tmp/backups" \
    bash "$tmp/ops/backup.sh" "$@"
}
expect_failure_containing() {
  local expected="$1"
  shift
  if invoke "$@" >"$output" 2>&1; then
    echo "FAIL: command unexpectedly succeeded: $*" >&2
    exit 1
  fi
  if ! grep -Fq "$expected" "$output"; then
    echo "FAIL: missing expected error [$expected] for $*" >&2
    # Fixture has no secrets, but do not print future tool output by default.
    exit 1
  fi
}

# Missing confirmation must abort before even creating a lock file.
if env CONFIRM=no VINTO_MVP_BACKUP_DIR="$tmp/backups" \
  bash "$tmp/ops/backup.sh" create-and-verify >"$output" 2>&1; then
  echo "FAIL: create-and-verify accepted missing confirmation" >&2; exit 1
fi
[ ! -e "$lock" ] || { echo "FAIL: lock created without confirmation" >&2; exit 1; }

# An independently held FD lock blocks *all* mutation entrypoints.
exec 9<>"$lock"
chmod 600 "$lock"  # File under contention must meet the script security contract.
flock -n 9
for mode in create verify create-and-verify prune-apply; do
  if [ "$mode" = verify ]; then
    expect_failure_containing "otra operacion de backup/restore/prune-apply" verify "$tmp/nonexistent.dump"
  else
    expect_failure_containing "otra operacion de backup/restore/prune-apply" "$mode"
  fi
done
exec 9>&-

# Existing symlink and insufficiently private lockfile must fail closed.
rm "$lock"
printf 'untouched\n' >"$tmp/sentinel"
ln -s "$tmp/sentinel" "$lock"
expect_failure_containing "archivo de candado invalido" create-and-verify
[ "$(cat "$tmp/sentinel")" = untouched ] || { echo "FAIL: symlink target modified" >&2; exit 1; }
rm "$lock"
: >"$lock"
chmod 644 "$lock"
expect_failure_containing "modo 600" create-and-verify
rm "$lock"

# With no contention, pass the lock gate but reject the missing .env contract.
# This cannot access Docker, PostgreSQL or credentials.
expect_failure_containing "FALLA:" create-and-verify
[ -f "$lock" ] && [ ! -L "$lock" ] && [ "$(stat -c '%a' "$lock")" = 600 ] \
  || { echo "FAIL: newly-created lock is not regular mode 600" >&2; exit 1; }
if grep -Fq "otra operacion de backup/restore/prune-apply" "$output"; then
  echo "FAIL: lock remained held after the earlier test" >&2; exit 1
fi
# No backup data files or verification markers should have been created.
[ "$(find "$tmp/backups" -maxdepth 1 -type f ! -name '.backup-operations.lock' | wc -l)" -eq 0 ] \
  || { echo "FAIL: unexpected backup artifacts" >&2; exit 1; }

echo "PASS: exclusive lock, fail-closed modes/permissions, no DB/backup operations"
