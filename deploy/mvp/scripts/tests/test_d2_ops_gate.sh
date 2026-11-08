#!/usr/bin/env bash
# E2-D2-B2-OPS: isolated REAL Bash tests for the release-aware gate.
# No database, systemd, root/sudo permissions or VPS access. The gate's
# external database CLI is mocked, not its shell decision/ordering.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT
export MVP_APP_DIR="$ROOT"
export MVP_SERVICE_USER="fake-vinto-service"
source "$SCRIPT_DIR/lib_common.sh"

LEGACY="$ROOT/releases/legacy"
NEW="$ROOT/releases/new"
mkdir -p "$LEGACY/backend/app" "$LEGACY/backend/.venv/bin" \
  "$NEW/backend/app/work_orders" "$NEW/backend/.venv/bin" \
  "$NEW/backend/migrations" "$ROOT/shared"
printf '#!/bin/sh\nexit 0\n' > "$LEGACY/backend/.venv/bin/python"
printf '#!/bin/sh\nexit 0\n' > "$NEW/backend/.venv/bin/python"
chmod 700 "$LEGACY/backend/.venv/bin/python" "$NEW/backend/.venv/bin/python"
: > "$NEW/backend/app/work_orders/handoff_rollout_cli.py"
: > "$NEW/backend/migrations/0019_work_order_line_reprogram_handoff.sql"
ln -s "$LEGACY" "$ROOT/current"
MOCK_RC=0
CALLS="$ROOT/gate-calls"
: > "$CALLS"

# Scope test overrides; shell function under test is never mocked.
assert_can_read_mvp_private_paths() { :; }
mvp_test() { test "$@"; }
mvp_readlink_f() { readlink -f "$1"; }
run_with_lock_fd_closed() {
  printf '%s\n' "$*" >> "$CALLS"
  return "$MOCK_RC"
}
mvp_env_value() {
  grep -E "^${2}=" "$1" | tail -n1 | cut -d= -f2-
}
sudo() {
  [ "$1" = "-u" ] || return 50
  shift 2
  "$@"
}

pass=0
assert_pass() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    pass=$((pass+1))
    printf 'PASS %s\n' "$name"
  else
    echo "FAIL $name" >&2
    exit 1
  fi
}
assert_fail() {
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    echo "FAIL $name (unexpected success)" >&2
    exit 1
  else
    pass=$((pass+1))
    printf 'PASS %s\n' "$name"
  fi
}

assert_pass "legacy-to-legacy probes DB without D2 CLI" d2_ops_gate rollback "$LEGACY"
grep -Fq "$ROOT/current/backend/.venv/bin/python -B -c" "$CALLS"
MOCK_RC=3
assert_fail "legacy DB unavailable fails closed" d2_ops_gate rollback "$LEGACY"
MOCK_RC=0
: > "$CALLS"
assert_fail "enable requires installed B2 runner" d2_ops_gate enable "$LEGACY"
assert_pass "first B2 activation uses prepared new release" d2_ops_gate activate "$NEW"
grep -Fq "$NEW/backend/.venv/bin/python -m app.work_orders.handoff_rollout_cli rollback" "$CALLS"
grep -Fq "PYTHONPATH=$NEW/backend" "$CALLS"

# Once B2 is current, it ALWAYS remains the gate, even when rolling back.
ln -sfn "$NEW" "$ROOT/current"
: > "$CALLS"
MOCK_RC=2
assert_fail "open handoff blocks rollback" d2_ops_gate rollback "$LEGACY"
assert_fail "open handoff blocks automatic activation fallback" d2_ops_gate activate "$LEGACY"
assert_fail "open handoff blocks manual flag disable" d2_ops_gate disable "$NEW"
[ "$(readlink -f "$ROOT/current")" = "$NEW" ] || exit 1
MOCK_RC=0
assert_pass "no handoffs allows preflight" d2_ops_gate disable "$NEW"
assert_pass "new release preflight allows enable" d2_ops_gate enable "$NEW"

# Env parser protection: do not roll back to a release that rejects the
# D2 flag in Pydantic, even when no handoffs exist.
printf 'WORK_ORDER_REPROGRAM_HANDOFF_ENABLED=true\n' > "$ROOT/shared/backend.env"
assert_fail "legacy target cannot parse D2 flag" d2_ops_gate rollback "$LEGACY"
: > "$LEGACY/backend/app/config.py"
assert_fail "legacy still lacks D2 flag field" d2_ops_gate rollback "$LEGACY"
printf 'work_order_reprogram_handoff_enabled: bool = False\n' > "$LEGACY/backend/app/config.py"
assert_pass "compatible legacy target after no-open gate" d2_ops_gate rollback "$LEGACY"

# Rollback to a pre-B2 D2 writer is dangerous with the flag ON even when
# the current B2 preflight says there are no handoffs.
B1="$ROOT/releases/b1"
mkdir -p "$B1/backend/migrations" "$B1/backend/app"
: > "$B1/backend/migrations/0019_work_order_line_reprogram_handoff.sql"
printf 'work_order_reprogram_handoff_enabled: bool = False\n' > "$B1/backend/app/config.py"
assert_fail "flag ON rejects downgrade to B1-only writer" d2_ops_gate rollback "$B1"
printf 'WORK_ORDER_REPROGRAM_HANDOFF_ENABLED=false\n' > "$ROOT/shared/backend.env"
assert_pass "flag OFF and zero handoffs permits B1-only checkout" d2_ops_gate rollback "$B1"

# With migration 0019, missing preflight code must NEVER be mistaken for
# pre-D2 legacy. A DB connection failure must also block.
rm -f "$NEW/backend/app/work_orders/handoff_rollout_cli.py"
assert_fail "D2 writer without runner fails closed" d2_ops_gate enable "$NEW"
ln -sfn "$LEGACY" "$ROOT/current"
assert_fail "D2 writer on target without runner fails closed" d2_ops_gate activate "$NEW"

# Static ordering check: guard appears before every release symlink flip,
# including the automatic reversal on failed healthcheck.
python3 - "$SCRIPT_DIR" <<'PY'
from pathlib import Path
import sys
scripts=Path(sys.argv[1])
d=(scripts/"deploy.sh").read_text()
r=(scripts/"rollback.sh").read_text()
activate=d.split("phase_activate() {",1)[1].split("phase_postgres_up() {",1)[0]
manual=r.split("rollback_version() {",1)[1].split("rollback_postgres() {",1)[0]
assert activate.index("d2_ops_gate activate") < activate.index('ln -sfn "$release_dir"')
assert activate.index('d2_ops_gate rollback "$previous_target"') < activate.index('ln -sfn "$previous_target"')
assert manual.index('d2_ops_gate rollback "$release_dir"') < manual.index('ln -sfn "$release_dir"')
assert "d2-gate) phase_d2_gate" in d
print("PASS gate ordering before all symlink changes")
PY
pass=$((pass+1))
echo "D2_B2OPS_SHELL_TESTS=$pass PASS"
