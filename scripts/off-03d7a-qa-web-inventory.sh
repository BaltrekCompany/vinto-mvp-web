#!/usr/bin/env bash
# VINTO OFF-03D.7A — QA web inventory, READ ONLY, no secrets or route edits.
set -Eeuo pipefail
set +x
export LC_ALL=C
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

usage() { echo 'bash scripts/off-03d7a-qa-web-inventory.sh inspect'; }
[ "$#" -eq 1 ] || { usage >&2; exit 2; }
case "$1" in
  --help|help|-h) usage; exit 0 ;;
  inspect) ;;
  *) usage >&2; echo 'OFF03D7A_BLOCKED: only inspect permitted' >&2; exit 2 ;;
esac
for tool in curl getent awk sort ss grep systemctl docker; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "OFF03D7A_BLOCKED: missing prerequisite $tool" >&2; exit 1;
  }
done
DOMAIN=qa-vinto-mvp.baltrekservices.com
IP=51.79.65.225
echo 'OFF03D7A_MODE=READ_ONLY'
resolved="$(getent ahostsv4 "$DOMAIN" | awk '{print $1}' | sort -u)"
case "
$resolved
" in *"
$IP
"*) echo 'OFF03D7A_QA_DNS=PASS' ;;
  *) echo 'OFF03D7A_QA_DNS=BLOCKED'; exit 1 ;;
esac
# Validate the trusted HTTPS chain; do not forward credentials or follow redirects.
status="$(curl --silent --show-error --noproxy '*' --proto '=https' \
  --max-redirs 0 --connect-timeout 6 --max-time 15 \
  --output /dev/null --write-out '%{http_code}' \
  "https://$DOMAIN/" )" || {
    echo 'OFF03D7A_QA_TLS_TRUST_CHAIN=BLOCKED'
    exit 1
  }
echo 'OFF03D7A_QA_TLS_TRUST_CHAIN=PASS'
case "$status" in
  200) echo 'OFF03D7A_QA_ROOT_HTTP=200' ;;
  404) echo 'OFF03D7A_QA_ROOT_HTTP=404_NOT_READY' ;;
  *) echo "OFF03D7A_QA_ROOT_HTTP=$status" ;;
esac
# Checking listeners does NOT reserve a port.
listeners="$(ss -H -ltn | awk '{print $4}')"
for port in 3200 8200; do
  if printf '%s\n' "$listeners" | grep -Eq "(^|:)$port$"; then
    printf 'OFF03D7A_PORT_%s=OCCUPIED\n' "$port"
  else
    printf 'OFF03D7A_PORT_%s=FREE_NOT_RESERVED\n' "$port"
  fi
done
for svc in vinto-mvp-frontend vinto-mvp-backend vinto-web; do
  if systemctl is-active --quiet "$svc"; then
    printf 'OFF03D7A_EXISTING_%s=RUNNING\n' "$svc"
  else
    printf 'OFF03D7A_EXISTING_%s=NOT_ACTIVE\n' "$svc"
  fi
done
for ctr in vinto-mvp-postgres postgres-vinto vinto-qa-postgres; do
  if [ "$(docker inspect -f '{{.State.Running}}' "$ctr" 2>/dev/null || true)" = true ]; then
    printf 'OFF03D7A_EXISTING_%s=RUNNING\n' "$ctr"
  else
    printf 'OFF03D7A_EXISTING_%s=NOT_RUNNING_OR_UNAVAILABLE\n' "$ctr"
  fi
done
# Do not infer Nginx routing, frontend runtime, QA DB roles or flags.
echo 'OFF03D7A_NGINX_ROUTE=UNVERIFIED'
echo 'OFF03D7A_QA_FRONTEND=NOT_DEPLOYED'
echo 'OFF03D7A_QA_BACKEND=NOT_DEPLOYED'
echo 'OFF03D7A_QA_APP_ROLE=NOT_VERIFIED'
echo 'OFF03D7A_QA_SEED_AND_SIGNER=NOT_READY'
echo 'OFF03D7A_PHYSICAL_MOBILE=NOT_RUN'
echo 'OFF03D7A_INVENTORY=COMPLETE_READ_ONLY'
