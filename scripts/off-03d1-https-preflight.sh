#!/usr/bin/env bash
# VINTO OFF-03D.1: remote HTTPS QA origin preflight, READ ONLY.
# Usage: bash scripts/off-03d1-https-preflight.sh https://qa.example.invalid
# No credentials, cookies, access tokens, database queries, commits or changes.
# ALWAYS run from the mobile's permitted network/VPN before planning device QA.
set -euo pipefail
export LC_ALL=C

origin="${1:-}"
if [[ ! "$origin" =~ ^https://[A-Za-z0-9][A-Za-z0-9.-]*(:[0-9]{2,5})?$ ]]; then
  printf 'USO: bash %s https://dominio-qa (solo origen HTTPS, sin rutas/credenciales)\n' "$0" >&2
  exit 2
fi
command -v curl >/dev/null 2>&1 || { echo 'BLOQUEADO: falta curl' >&2; exit 2; }
command -v mktemp >/dev/null 2>&1 || { echo 'BLOQUEADO: falta mktemp' >&2; exit 2; }

tmpdir="$(mktemp -d)"
trap 'rm -rf -- "$tmpdir"' EXIT
pass=0
fail=0
results=()
http_status=''
body_file="$tmpdir/body"
headers_file="$tmpdir/headers"

ok() { results+=("PASS $1"); pass=$((pass+1)); }
blocked() { results+=("BLOCKED $1"); fail=$((fail+1)); }

probe() {
  local method="$1" path="$2" code rc
  : > "$body_file"
  : > "$headers_file"
  # Do NOT follow HTTP redirects: they may switch origin or expose cookies.
  # There are NO cookies and no authentication headers in these checks.
  if [[ "$method" == POST ]]; then
    code="$(curl --silent --show-error --connect-timeout 6 --max-time 18 \
      --proto '=https' --max-redirs 0 --request POST \
      --header 'Content-Type: application/json' \
      --data '{"device_key":"00000000-0000-4000-8000-000000000000","machine_codes":["MP1"]}' \
      --dump-header "$headers_file" --output "$body_file" \
      --write-out '%{http_code}' "$origin$path")" || rc=$?
  else
    code="$(curl --silent --show-error --connect-timeout 6 --max-time 18 \
      --proto '=https' --max-redirs 0 --request GET \
      --dump-header "$headers_file" --output "$body_file" \
      --write-out '%{http_code}' "$origin$path")" || rc=$?
  fi
  if [[ -n "${rc:-}" ]]; then http_status='000'; return 1; fi
  http_status="$code"
}

public_file() {
  local path="$1" marker="$2" name="$3"
  if ! probe GET "$path"; then blocked "$name (conexión/TLS)"; return; fi
  if [[ "$http_status" != 200 ]]; then
    blocked "$name (HTTP $http_status)"; return
  fi
  if [[ -n "$marker" ]] && ! grep -Fq -- "$marker" "$body_file"; then
    blocked "$name (versión/artefacto no coincide)"; return
  fi
  ok "$name (HTTPS 200)"
}

echo 'VINTO_OFF03D1_REMOTE_PREFLIGHT_READ_ONLY'
echo 'IMPORTANTE: no prueba aislamiento de BD ni reinicio físico; no habilita captura.'
public_file '/' '' 'Frontend QA'
public_file '/offline-preparacion' '' 'Preparación online'
public_file '/offline.html' '/offline-device-qa.js' 'Pantalla offline OFF-03C.3'
public_file '/sw.js' 'vinto-off03c3-static-v1' 'Service Worker versionado'
public_file '/offline-device-qa.js' 'vinto-off03c3-static-v1' 'Diagnóstico móvil público'
public_file '/offline-boot.js' '' 'Verificador offline compilado'
public_file '/offline-probe.js' '' 'Prueba pública almacenamiento'
public_file '/manifest.webmanifest' '' 'Manifest PWA'
public_file '/favicon.svg' '' 'Ícono estático'

# No credentials are attached. The auth API MUST refuse the anonymous user.
if ! probe GET '/api/auth/me'; then
  blocked 'GET /api/auth/me (red/TLS)'
elif [[ "$http_status" == 401 ]]; then
  ok 'GET /api/auth/me niega acceso anónimo (401)'
else
  blocked "GET /api/auth/me devolvió HTTP $http_status (esperado 401)"
fi

# FastAPI evaluates authentication first: an anonymous POST must return 401.
# This cannot verify that the QA feature flags are enabled for real users.
if ! probe POST '/api/offline/scope'; then
  blocked 'POST /api/offline/scope (red/TLS)'
elif [[ "$http_status" == 401 ]]; then
  ok 'POST /api/offline/scope requiere autenticación (401)'
else
  blocked "POST /api/offline/scope devolvió HTTP $http_status (esperado 401)"
fi

if ! probe POST '/api/offline/quality-package'; then
  blocked 'POST /api/offline/quality-package (red/TLS)'
elif [[ "$http_status" == 401 ]]; then
  ok 'POST /api/offline/quality-package requiere autenticación (401)'
else
  blocked "POST /api/offline/quality-package devolvió HTTP $http_status (esperado 401)"
fi

printf '%s\n' "${results[@]}"
printf 'CHECKS_PASS=%d CHECKS_BLOCKED=%d\n' "$pass" "$fail"
echo 'DATABASE_ISOLATION=NOT_VERIFIED'
echo 'DEPLOYED_SHA=NOT_VERIFIED'
echo 'AUTHENTICATED_SIGNING=NOT_VERIFIED'
echo 'MOBILE_HARD_RESTART=NOT_RUN'
if [[ "$fail" != 0 ]]; then echo 'OFF03D1_REMOTE_GATE=BLOCKED'; exit 1; fi
echo 'OFF03D1_REMOTE_GATE=PASS_NETWORK_ONLY'
