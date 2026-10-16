#!/usr/bin/env bash
# VINTO MVP WEB — build EXTERNO del frontend (CLOUD-DEP-02B.1-C.1).
#
# Se ejecuta en un host Linux x86_64 (CI o una máquina de desarrollo) — NUNCA en el VPS. El VPS
# nunca instala Node/Corepack/pnpm: solo recibe el artefacto ya construido aquí
# (deploy.sh install-frontend-artifact lo instala tras verificar su checksum y el commit).
#
# Qué hace, en orden:
#   1. Verifica que el repositorio está exactamente en el commit pedido y sin cambios locales
#      (un build reproducible exige un árbol limpio en el commit autorizado, nunca "lo que haya").
#   2. Compila con corepack/pnpm (ya versionados por packageManager en package.json).
#   3. Empaqueta dist/standalone/ en un .tar.gz.
#   4. Genera un manifiesto de texto (legible con lib_common.sh::env_value) con el commit exacto,
#      la versión de Node usada para compilar y el checksum SHA-256 del .tar.gz — es lo que
#      deploy.sh verifica antes de instalar nada en el VPS.
#
# Uso: VINTO_MVP_DOMAIN=<dominio> bash build-frontend-artifact.sh <directorio-del-repo> <sha-completo> <dir-salida>

set -euo pipefail

REPO_DIR="${1:?Uso: build-frontend-artifact.sh <directorio-del-repo> <sha-completo> <dir-salida>}"
COMMIT="${2:?Uso: build-frontend-artifact.sh <directorio-del-repo> <sha-completo> <dir-salida>}"
OUT_DIR="${3:?Uso: build-frontend-artifact.sh <directorio-del-repo> <sha-completo> <dir-salida>}"
DOMAIN="${VINTO_MVP_DOMAIN:?Definir VINTO_MVP_DOMAIN (p. ej. vinto-mvp.baltrekservices.com) antes de compilar}"

if [ "$(uname -s)" != "Linux" ] || [ "$(uname -m)" != "x86_64" ]; then
  echo "FALLA: este build debe ejecutarse en Linux x86_64 (la misma arquitectura que el VPS de destino). Detectado: $(uname -s) $(uname -m). No se da por compatible un artefacto construido en otro sistema operativo o arquitectura." >&2
  exit 1
fi
if ! [[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
  echo "FALLA: '$COMMIT' no es un SHA completo de 40 caracteres hexadecimales." >&2
  exit 1
fi

cd "$REPO_DIR"
actual_head="$(git rev-parse HEAD)"
if [ "$actual_head" != "$COMMIT" ]; then
  echo "FALLA: HEAD de $REPO_DIR es $actual_head, no coincide con el commit pedido $COMMIT. Hacer checkout exacto de ese commit antes de compilar." >&2
  exit 1
fi
if [ -n "$(git status --porcelain)" ]; then
  echo "FALLA: hay cambios locales sin confirmar en $REPO_DIR. Un build reproducible exige un árbol de trabajo limpio en el commit autorizado." >&2
  exit 1
fi

corepack pnpm install --frozen-lockfile
# NEXT_PUBLIC_API_URL se incrusta en el bundle del cliente EN TIEMPO DE BUILD (confirmado en
# CLOUD-01B-1): debe fijarse aquí, nunca en el systemd unit del frontend en el VPS.
NEXT_PUBLIC_API_URL="https://$DOMAIN" pnpm run build

if [ ! -f "$REPO_DIR/dist/standalone/server.js" ]; then
  echo "FALLA: el build no generó dist/standalone/server.js — revisar next.config.ts (output: \"standalone\") y .sites-runtime/execution-profile.json (debe estar AUSENTE para el perfil 'portable')." >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
ARTIFACT="$OUT_DIR/vinto-mvp-frontend-${COMMIT}.tar.gz"
tar -czf "$ARTIFACT" -C "$REPO_DIR/dist" standalone
ARTIFACT_SHA256="$(sha256sum "$ARTIFACT" | awk '{print $1}')"
NODE_VERSION="$(node --version | sed 's/^v//')"

MANIFEST="$OUT_DIR/vinto-mvp-frontend-${COMMIT}.manifest"
{
  printf 'VINTO_MVP_ARTIFACT_COMMIT=%s\n' "$COMMIT"
  printf 'VINTO_MVP_ARTIFACT_NODE_VERSION=%s\n' "$NODE_VERSION"
  printf 'VINTO_MVP_ARTIFACT_SHA256=%s\n' "$ARTIFACT_SHA256"
  printf 'VINTO_MVP_ARTIFACT_BUILT_AT=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
} > "$MANIFEST"

echo "Artefacto:   $ARTIFACT"
echo "Manifiesto:  $MANIFEST"
echo "SHA-256:     $ARTIFACT_SHA256"
echo "Node usado:  $NODE_VERSION"
echo
echo "Transferir ambos archivos al VPS (scp/rsync, fuera del alcance de este script) y luego:"
echo "  CONFIRM=yes bash deploy.sh install-frontend-artifact $COMMIT <ruta-tar.gz-en-vps> <ruta-manifiesto-en-vps>"
