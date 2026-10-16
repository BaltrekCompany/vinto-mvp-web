#!/usr/bin/env bash
# VINTO MVP WEB — preflight de solo lectura (CLOUD-DEP-02A / se ejecuta en DEP-02B).
#
# No modifica nada. Verifica que los supuestos de este despliegue siguen siendo ciertos en el VPS
# ANTES de ejecutar deploy.sh: puertos libres, rutas todavía no ocupadas, TVC sigue intacto, Docker
# disponible. Seguro de ejecutar repetidamente. Pensado para correrse EN EL VPS (no localmente).
#
# Uso: bash preflight.sh

set -euo pipefail

FAIL=0
ok()   { printf 'OK    %s\n' "$1"; }
warn() { printf 'AVISO %s  -- %s\n' "$1" "$2"; }
fail() { printf 'FALLA %s  -- %s\n' "$1" "$2"; FAIL=1; }

echo "=== VINTO MVP WEB — preflight (solo lectura) ==="

# 1. Puertos candidatos deben estar libres.
for port in 3100 8100 6544; do
  if ss -ltn "( sport = :$port )" 2>/dev/null | grep -q LISTEN; then
    fail "puerto $port" "ya está en uso; no se puede reutilizar sin revisar antes"
  else
    ok "puerto $port libre"
  fi
done

# 2. Rutas del MVP no deben existir todavía (evita sobrescribir algo sin querer).
for path in /opt/vinto-mvp-web /home/vinto-mvp; do
  if [ -e "$path" ]; then
    warn "$path" "ya existe; confirmar que es de una corrida previa de ESTE despliegue antes de continuar, nunca sobrescribir sin revisar"
  else
    ok "$path no existe todavía (esperado antes del primer despliegue)"
  fi
done

# 3. TVC debe seguir intacto (no tocar nada de esto; solo lectura para confirmar que sigue vivo).
for unit in vinto-web.service nginx.service docker.service; do
  if systemctl is-active --quiet "$unit"; then
    ok "$unit sigue activo (TVC/infraestructura compartida intacta)"
  else
    warn "$unit" "no está activo — investigar ANTES de continuar, podría no ser por este despliegue"
  fi
done
if [ -e /etc/nginx/sites-enabled/vinto-tvc ]; then
  ok "sites-enabled/vinto-tvc sigue presente"
else
  warn "sites-enabled/vinto-tvc" "no está presente — no continuar sin entender por qué"
fi

# 4. Docker disponible y el usuario actual puede usarlo sin sudo (grupo docker).
if docker info >/dev/null 2>&1; then
  ok "docker accesible sin sudo"
else
  fail "docker" "no accesible; revisar pertenencia al grupo docker antes de continuar"
fi

# 5. Nombres/puertos de TVC no deben chocar con los del MVP (defensivo; ya diseñado para no chocar).
if docker ps -a --format '{{.Names}}' | grep -qx "vinto-mvp-postgres"; then
  warn "vinto-mvp-postgres" "ya existe un contenedor con ese nombre — confirmar que es de una corrida previa de este mismo despliegue"
fi
if docker ps -a --format '{{.Names}}' | grep -qx "postgres-vinto"; then
  ok "postgres-vinto (TVC) presente, no se tocará"
fi

# 6. Usuario de servicio dedicado: debe NO existir todavía (lo crea deploy.sh, una sola vez).
if id vinto-mvp >/dev/null 2>&1; then
  warn "usuario vinto-mvp" "ya existe — confirmar que es de una corrida previa antes de reutilizarlo"
else
  ok "usuario vinto-mvp no existe todavía (esperado antes del primer despliegue)"
fi

echo "=== Resultado: $([ "$FAIL" -eq 0 ] && echo 'SIN FALLAS BLOQUEANTES' || echo 'HAY FALLAS — NO CONTINUAR CON deploy.sh') ==="
exit "$FAIL"
