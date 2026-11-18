#!/usr/bin/env bash
# VINTO OFF-03D.7B — launch compiled Vinext standalone on CI loopback only.
# Never run this script against the VPS or a production service.
set -Eeuo pipefail
set +x
export LC_ALL=C
[ "$#" -eq 1 ] && [ "$1" = smoke ] || {
  echo 'OFF03D7B_SMOKE_BLOCKED: requires smoke' >&2; exit 2;
}
[ "$(printenv GITHUB_ACTIONS 2>/dev/null || true)" = true ] &&
[ "$(printenv RUNNER_OS 2>/dev/null || true)" = Linux ] ||
  { echo 'OFF03D7B_SMOKE_BLOCKED: ephemeral GitHub Actions runner required' >&2; exit 1; }
for x in node curl mktemp grep cmp seq; do command -v "$x" >/dev/null 2>&1 ||
  { echo "OFF03D7B_SMOKE_BLOCKED: missing $x" >&2; exit 1; }; done
[ -s dist/standalone/server.js ] && [ -s dist/standalone/public/sw.js ] ||
  { echo 'OFF03D7B_SMOKE_BLOCKED: standalone output absent' >&2; exit 1; }
[ "$(printenv NEXT_PUBLIC_API_URL 2>/dev/null || true)" = 'https://qa-vinto-mvp.baltrekservices.com' ] ||
  { echo 'OFF03D7B_SMOKE_BLOCKED: wrong QA same-origin API URL' >&2; exit 1; }
node -e 'let [a,b,c]=process.versions.node.split(".").map(Number);process.exit(a>22||(a===22&&(b>18||(b===18&&c>=0)))?0:1)' ||
  { echo 'OFF03D7B_SMOKE_BLOCKED: Node below 22.18.0' >&2; exit 1; }
[ "$(node --input-type=module -e 'import p from "./package.json" with {type:"json"}; console.log(p.packageManager)')" = 'pnpm@11.25.0' ] ||
  { echo 'OFF03D7B_SMOKE_BLOCKED: pnpm pin drift' >&2; exit 1; }
cmp -s public/offline-boot.js dist/standalone/public/offline-boot.js ||
  { echo 'OFF03D7B_SMOKE_BLOCKED: offline boot artifact drift' >&2; exit 1; }

# CI runner is disposable. Ensure no leftover listener is mistaken for ours.
PORT=33200
HOSTNAME=127.0.0.1
BASE='http://127.0.0.1:33200'
if curl --noproxy '*' --silent --connect-timeout 1 --max-time 2 \
  "$BASE/" >/dev/null 2>&1; then
  echo 'OFF03D7B_SMOKE_BLOCKED: preexisting listener' >&2; exit 1
fi
LOG="$(mktemp)"
PID=''
cleanup() {
  if [ -n "$PID" ]; then
    kill "$PID" 2>/dev/null || true
    wait "$PID" 2>/dev/null || true
  fi
  rm -f -- "$LOG"
}
trap cleanup EXIT
# No database or cookie configuration is injected. No QA VPS connection.
PORT="$PORT" HOSTNAME="$HOSTNAME" NODE_ENV=production \
  node dist/standalone/server.js >"$LOG" 2>&1 &
PID="$!"

probe(){
  local path="$1" expected="$2" code=''
  code="$(curl --noproxy '*' --silent --show-error \
    --connect-timeout 1 --max-time 4 --max-redirs 0 \
    --output /dev/null --write-out '%{http_code}' "$BASE$path" 2>/dev/null)" || return 1
  [ "$code" = "$expected" ]
}
for _ in $(seq 1 45); do
  kill -0 "$PID" 2>/dev/null || {
    echo 'OFF03D7B_SMOKE_BLOCKED: standalone process exited' >&2; exit 1;
  }
  if probe '/' 200; then break; fi
  sleep 1
done
probe '/' 200 || { echo 'OFF03D7B_SMOKE_BLOCKED: root route not 200' >&2; exit 1; }
probe '/offline-preparacion' 200 || {
  echo 'OFF03D7B_SMOKE_BLOCKED: offline preparation route unavailable' >&2; exit 1;
}
for asset in /offline.html /sw.js /offline-device-qa.js \
  /offline-boot.js /offline-probe.js /manifest.webmanifest /favicon.svg; do
  probe "$asset" 200 || {
    echo "OFF03D7B_SMOKE_BLOCKED: public asset missing $asset" >&2; exit 1;
  }
done
code="$(curl --noproxy '*' --silent --show-error --connect-timeout 2 \
  --max-time 5 --max-redirs 0 --output /dev/null --write-out '%{http_code}' \
  "$BASE/api/auth/me")" || {
  echo 'OFF03D7B_SMOKE_BLOCKED: no local API response' >&2; exit 1;
}
# No auth backend is bound on CI loopback: do not accept a successful session.
[ "$code" != 200 ] || {
  echo 'OFF03D7B_SMOKE_BLOCKED: unauthenticated API unexpectedly returned 200' >&2; exit 1;
}
echo 'OFF03D7B_NODE_STANDALONE_START=PASS_LOOPBACK_CI'
echo 'OFF03D7B_PUBLIC_OFFLINE_ASSETS=PASS'
echo 'OFF03D7B_SAME_ORIGIN_QA_BUILD=PASS_CONTRACT'
echo 'OFF03D7B_REMOTE_VPS=UNTOUCHED'
echo 'OFF03D7B_SMOKE=PASS_EPHEMERAL_ONLY'
