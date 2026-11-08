#!/usr/bin/env bash
# QA aislado del healthcheck manual: no red, PostgreSQL, VPS ni systemd.
# Simula backend caido, base no disponible, frontend caido y arranque tardio.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="$(mktemp -d)"
trap 'rm -rf "$ROOT"' EXIT

cat > "$ROOT/curl" <<'MOCK'
#!/usr/bin/env bash
set -euo pipefail
url=""
for item in "$@"; do url="$item"; done
printf '%s\n' "$url" >> "$MOCK_CALLS"
if [ "$url" = "${MOCK_FAIL_URL:-}" ]; then exit 7; fi
if [ "$url" = "${MOCK_FAIL_ONCE_URL:-}" ] && [ ! -e "$MOCK_ONCE_MARK" ]; then
  : > "$MOCK_ONCE_MARK"
  exit 7
fi
MOCK
cat > "$ROOT/sleep" <<'MOCK'
#!/usr/bin/env bash
# No demorar las regresiones; contar los reintentos mediante las llamadas curl.
exit 0
MOCK
chmod 700 "$ROOT/curl" "$ROOT/sleep"
export PATH="$ROOT:$PATH"
export MOCK_CALLS="$ROOT/calls" MOCK_ONCE_MARK="$ROOT/once"

check_calls() {
  local expected="$1"
  test "$(wc -l < "$MOCK_CALLS")" -eq "$expected"
}

assert_failure() {
  local label="$1" url="$2" calls="$3"
  : > "$MOCK_CALLS"
  rm -f "$MOCK_ONCE_MARK"
  export MOCK_FAIL_URL="$url" MOCK_FAIL_ONCE_URL=""
  if bash "$SCRIPT_DIR/deploy.sh" healthcheck > "$ROOT/out" 2>&1; then
    echo "FAIL $label: falso PASS" >&2
    exit 1
  fi
  grep -Fq "FALLA: healthcheck MVP incompleto" "$ROOT/out"
  if grep -Fq "frontend OK" "$ROOT/out"; then
    echo "FAIL $label: exito anunciado sin salud completa" >&2
    exit 1
  fi
  check_calls "$calls"
  echo "PASS $label"
}

assert_failure "backend health caido, frontend sano" "http://127.0.0.1:8100/health" 6
assert_failure "API database health caido, frontend sano" "http://127.0.0.1:8100/api/health" 12
assert_failure "frontend caido, backend sano" "http://127.0.0.1:3100/" 18

: > "$MOCK_CALLS"
rm -f "$MOCK_ONCE_MARK"
export MOCK_FAIL_URL="" MOCK_FAIL_ONCE_URL=""
bash "$SCRIPT_DIR/deploy.sh" healthcheck > "$ROOT/out" 2>&1
check_calls 3
grep -Fq "backend /health: OK" "$ROOT/out"
grep -Fq "backend /api/health (database): OK" "$ROOT/out"
grep -Fq "frontend OK (127.0.0.1:3100)" "$ROOT/out"
echo "PASS backend, database y frontend sanos"

: > "$MOCK_CALLS"
rm -f "$MOCK_ONCE_MARK"
export MOCK_FAIL_ONCE_URL="http://127.0.0.1:8100/health"
bash "$SCRIPT_DIR/deploy.sh" healthcheck > "$ROOT/out" 2>&1
check_calls 4
grep -Fq "frontend OK (127.0.0.1:3100)" "$ROOT/out"
echo "PASS backend demora un intento en arrancar"

echo "MVP_HEALTHCHECK_FAIL_CLOSED_TESTS=5 PASS"
