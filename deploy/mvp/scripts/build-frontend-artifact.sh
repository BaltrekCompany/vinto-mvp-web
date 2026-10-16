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
#   3. CLOUD-DEP-02B.1-E.2: completa las dependencias de runtime que "vinext build" no copió al
#      standalone (ver más abajo) y, SOLO si el resultado arranca de verdad y responde HTTP 200 en
#      un directorio AISLADO del repositorio, empaqueta dist/standalone/ en un .tar.gz.
#   4. Genera un manifiesto de texto (legible con lib_common.sh::env_value) con el commit exacto,
#      la versión de Node usada para compilar y el checksum SHA-256 del .tar.gz — es lo que
#      deploy.sh verifica antes de instalar nada en el VPS. Nunca se genera si el paso 3 no pasó.
#
# CLOUD-DEP-02B.1-E.1/E.2 — defecto real encontrado y corregido aquí:
#   El artefacto que "vinext build" deja en dist/standalone/ puede NO incluir todo lo que su
#   propio código (node_modules/vinext/dist/server/*.js, no el bundle de la app) necesita en
#   tiempo de ejecución: confirmado con el tarball real de este repositorio (commit
#   ebbe1afedb5d39f2605cc534b1278fd92f614394), el standalone resultante no traía "react" y el
#   servidor moría con "ERR_MODULE_NOT_FOUND: Cannot find package 'react'" al arrancar. "vinext
#   check" no detecta esto, y la documentación de vinext afirma que el standalone "incluye
#   runtime deps" — empíricamente, bajo el layout simbólico de pnpm, no siempre es así.
#
#   Corrección (deliberadamente DINÁMICA, no una lista fija de paquetes): un análisis estático de
#   qué imports hace falta copiar resultó, en la práctica, lleno de falsos positivos (código de
#   terceros empaquetado dentro de dependencias legítimas — parsers, generadores de bundles —
#   contiene literales de texto que PARECEN imports pero no lo son). En vez de adivinar, esta
#   corrección ARRANCA el standalone de verdad, en un directorio AISLADO (nunca dentro de
#   $REPO_DIR: Node resuelve módulos buscando node_modules hacia arriba desde el archivo que
#   importa, así que probar dentro del repo podría "ver" node_modules/react del repo y ocultar
#   que el ARTEFACTO por sí solo no lo trae). Si falla con "Cannot find package/module '<pkg>'",
#   resuelve '<pkg>' con el PROPIO resolutor de Node desde $REPO_DIR (nunca una ruta fija de
#   pnpm/.pnpm/<paquete>@<versión>: eso dependería de una estructura de store que puede cambiar
#   entre versiones de pnpm) — camino de entrada resuelto + subir directorios hasta encontrar el
#   package.json cuyo "name" coincide — lo copia dentro de dist/standalone/node_modules/ y
#   reintenta. Esto además resuelve dependencias TRANSITIVAS sin necesidad de recorrerlas a mano:
#   si el paquete recién copiado necesita otro, el siguiente intento de arranque lo revela igual.
#   Si una versión no puede resolverse, o se agotan los reintentos, el build FALLA explícitamente
#   (nunca empaqueta ni genera manifiesto de un artefacto que no se demostró que arranca).
#
# Uso: VINTO_MVP_DOMAIN=<dominio> bash build-frontend-artifact.sh <directorio-del-repo> <sha-completo> <dir-salida>

set -euo pipefail

: "${MAX_FIX_ITER:=20}"
# Unidades de 0.5s (p. ej. 30 -> 15s). Deliberadamente parametrizable: las pruebas negativas de
# verify_local.sh necesitan un tiempo de espera corto para no volverse lentas.
: "${BOOT_TIMEOUT_UNITS:=30}"

# --- Funciones reutilizables (también las usa verify_local.sh para probar los caminos de FALLA,
# sin tener que clonar ni compilar el repositorio real en cada corrida) -------------------------

# pick_free_port -- imprime un puerto TCP libre en 127.0.0.1, elegido por el propio sistema
# operativo (puerto 0), nunca uno fijo que pudiera colisionar con otra prueba en paralelo.
pick_free_port() {
  node -e "const net=require('net');const s=net.createServer();s.listen(0,'127.0.0.1',()=>{const p=s.address().port;s.close(()=>{process.stdout.write(String(p));});});"
}

# resolve_pkg_root <nombre-paquete> <directorio-base> -- imprime la ruta ABSOLUTA del directorio
# raíz real de ese paquete (el que contiene su package.json), resuelta con el propio algoritmo de
# resolución de módulos de Node desde <directorio-base> (nunca una ruta fija de
# node_modules/.pnpm/<paquete>@<versión>: eso ataría la corrección a una versión concreta del
# store de pnpm). Si <directorio-base> usa pnpm, el "require.resolve" ya sigue sus symlinks hasta
# la ubicación real dentro de .pnpm/ — aquí solo se sube desde el archivo de entrada resuelto
# hasta encontrar el package.json cuyo "name" coincide exactamente (mismo truco que usan
# herramientas como "resolve-pkg"/"pkg-dir"). Sale con código distinto de 0 (y SIN imprimir nada)
# si el paquete no se puede resolver en absoluto, o si se resuelve pero no se encuentra su
# package.json subiendo directorios — ambos casos son un error a tratar explícitamente por quien
# llama, nunca un resultado ambiguo.
resolve_pkg_root() {
  local pkg="$1" base_dir="$2"
  node - "$pkg" "$base_dir" <<'NODEEOF'
const path = require("path");
const fs = require("fs");
const { createRequire } = require("module");
const [pkgName, baseDir] = process.argv.slice(2);
const req = createRequire(path.join(baseDir, "package.json"));
let entry;
try {
  entry = req.resolve(pkgName);
} catch {
  process.exit(3);
}
let dir = path.dirname(entry);
for (;;) {
  const pkgJsonPath = path.join(dir, "package.json");
  if (fs.existsSync(pkgJsonPath)) {
    try {
      const pkgJson = JSON.parse(fs.readFileSync(pkgJsonPath, "utf8"));
      if (pkgJson.name === pkgName) {
        process.stdout.write(dir);
        process.exit(0);
      }
    } catch {
      // package.json ilegible: seguir subiendo, no es necesariamente un error.
    }
  }
  const parent = path.dirname(dir);
  if (parent === dir) break;
  dir = parent;
}
process.exit(4);
NODEEOF
}

# boot_and_check <directorio-con-server.js> -- arranca "server.js" de ese directorio con un
# puerto libre y HOST=127.0.0.1, espera de forma ACOTADA (BOOT_TIMEOUT_UNITS * 0.5s) una respuesta
# HTTP de la página inicial, y SIEMPRE termina el proceso que arrancó (exista éxito, fallo, o un
# error de módulo) antes de devolver el control — nunca deja un proceso huérfano escuchando.
# Imprime por stdout exactamente una de:
#   "OK"             -- respondió HTTP 200 en "/" dentro del tiempo acotado.
#   "MISSING:<pkg>"  -- murió con "Cannot find package/module '<pkg>'" (ERR_MODULE_NOT_FOUND o
#                       MODULE_NOT_FOUND, según el formato ESM/CJS del error de Node).
#   "FAIL"           -- ni lo anterior ni lo otro (murió por otra causa, o no respondió a tiempo
#                       sin un error de módulo reconocible); el log completo se vuelca a stderr
#                       para que quien llama pueda diagnosticarlo.
# Código de salida: 0 solo en el caso "OK"; distinto de 0 en cualquier otro caso.
boot_and_check() {
  local dir="$1"
  if ! command -v curl >/dev/null 2>&1; then
    echo "FAIL" ; echo "boot_and_check: 'curl' no está disponible en este host de build; requerido para la prueba de arranque." >&2
    return 1
  fi
  local port
  port="$(pick_free_port)"
  local log
  log="$(mktemp)"
  ( cd "$dir" && PORT="$port" HOST=127.0.0.1 node server.js ) >"$log" 2>&1 &
  local pid=$!
  local waited=0
  local ok=0
  while [ "$waited" -lt "$BOOT_TIMEOUT_UNITS" ]; do
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
    if curl -fsS -o /dev/null "http://127.0.0.1:${port}/" 2>/dev/null; then
      ok=1
      break
    fi
    sleep 0.5
    waited=$((waited + 1))
  done
  # Terminar el proceso SIEMPRE: tanto si sigue vivo (éxito o timeout) como si ya murió por su
  # cuenta (error de módulo u otro crash) — en ese segundo caso "kill" ya no tiene nada que hacer,
  # pero "wait" recoge el estado para no dejar un zombie.
  #
  # CLOUD-DEP-02B.1-E.3: SIGTERM (lo que "kill" envía por defecto) puede ser IGNORADO por el
  # proceso — confirmado empíricamente con un server.js que instala su propio manejador de
  # SIGTERM sin terminar: sigue vivo indefinidamente. El "wait" de más abajo, sin esto, podría
  # entonces bloquear esta función (y por tanto todo el build) para siempre, justo lo que la
  # prueba de arranque acotada en el tiempo existe para evitar. Se da un margen breve tras
  # SIGTERM y, si el proceso sigue vivo, se escala a SIGKILL (que el proceso no puede ignorar)
  # antes de "wait" — nunca se confía en que un SIGTERM simple haya sido suficiente.
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    local kill_wait=0
    while [ "$kill_wait" -lt 10 ] && kill -0 "$pid" 2>/dev/null; do
      sleep 0.2
      kill_wait=$((kill_wait + 1))
    done
    if kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  fi
  wait "$pid" 2>/dev/null || true
  if [ "$ok" -eq 1 ]; then
    echo "OK"
    rm -f "$log"
    return 0
  fi
  local missing
  missing="$(grep -oE "Cannot find (package|module) '[^']+'" "$log" | head -1 | sed -E "s/Cannot find (package|module) '([^']+)'/\\2/")" || true
  if [ -n "$missing" ]; then
    echo "MISSING:$missing"
    rm -f "$log"
    return 1
  fi
  echo "FAIL"
  echo "boot_and_check: el servidor en '$dir' no respondió HTTP 200 dentro del tiempo acotado y no se detectó un error de módulo reconocible. Log:" >&2
  cat "$log" >&2
  rm -f "$log"
  return 1
}

# assert_isolated_from_repo <directorio> <directorio-del-repo> -- rechaza si <directorio> está
# DENTRO de <directorio-del-repo>: la prueba de arranque exige poder demostrar que el artefacto
# funciona POR SÍ SOLO, sin apoyarse (ni por accidente) en node_modules del repositorio de origen.
assert_isolated_from_repo() {
  local dir="$1" repo_dir="$2"
  case "$dir" in
    "$repo_dir"|"$repo_dir"/*)
      echo "FALLA: el directorio de prueba aislado ('$dir') está dentro del repositorio ('$repo_dir'). Esto invalidaría la prueba: Node podría resolver módulos desde el node_modules del repositorio en vez de desde el artefacto, ocultando una dependencia realmente ausente." >&2
      return 1
      ;;
  esac
  return 0
}

# complete_standalone_deps <directorio-standalone> <directorio-del-repo> -- completa, de forma
# iterativa y dinámica (ver cabecera del archivo), las dependencias de runtime que falten en
# <directorio-standalone>/node_modules para que el servidor arranque y responda. Nunca copia nada
# "por si acaso": cada paquete que añade está demostrado, empíricamente, que el arranque lo pidió.
# FALLA explícitamente (código de salida distinto de 0, nada de node_modules queda a medio
# completar silenciosamente) si un paquete pedido no se puede resolver, o si se agotan
# MAX_FIX_ITER intentos sin lograr un arranque exitoso.
complete_standalone_deps() {
  local standalone_dir="$1" repo_dir="$2"
  local iter=0
  while [ "$iter" -lt "$MAX_FIX_ITER" ]; do
    iter=$((iter + 1))
    local isolated
    isolated="$(mktemp -d)"
    assert_isolated_from_repo "$isolated" "$repo_dir" || { rm -rf "$isolated"; return 1; }
    cp -r "$standalone_dir" "$isolated/standalone"
    local check_out check_status
    set +e
    check_out="$(boot_and_check "$isolated/standalone")"
    check_status=$?
    set -e
    rm -rf "$isolated"
    if [ "$check_status" -eq 0 ]; then
      echo "complete_standalone_deps: arranque verificado tras $iter intento(s)."
      return 0
    fi
    case "$check_out" in
      MISSING:*)
        local pkg="${check_out#MISSING:}"
        local pkg_root
        set +e
        pkg_root="$(resolve_pkg_root "$pkg" "$repo_dir")"
        local resolve_status=$?
        set -e
        if [ "$resolve_status" -ne 0 ] || [ -z "$pkg_root" ]; then
          echo "FALLA: el standalone necesita '$pkg' en tiempo de ejecución, pero no se pudo resolver desde '$repo_dir' (¿falta en package.json, o el lockfile no lo instaló?). No se completa el empaquetado." >&2
          return 1
        fi
        echo "complete_standalone_deps: falta '$pkg' -> resuelto en '$pkg_root', copiando a node_modules del standalone."
        local dest="$standalone_dir/node_modules/$pkg"
        mkdir -p "$(dirname "$dest")"
        rm -rf "$dest"
        cp -r "$pkg_root" "$dest"
        ;;
      *)
        echo "FALLA: el standalone no arrancó y el fallo no fue un 'Cannot find package/module' reconocible (ver log de boot_and_check arriba). No se completa el empaquetado." >&2
        return 1
        ;;
    esac
  done
  echo "FALLA: se agotaron $MAX_FIX_ITER intentos de completar node_modules sin lograr un arranque exitoso. Revisar si hay una dependencia circular sin resolver o un fallo real de la aplicación." >&2
  return 1
}

# isolated_boot_gate <ruta-tar.gz> <directorio-del-repo> -- la puerta de salida FORMAL (Fase C):
# extrae el ARTEFACTO YA EMPAQUETADO (no el dist/standalone suelto) a un directorio aislado nuevo
# y confirma que arranca y responde HTTP 200, exactamente como lo recibiría el VPS. Nunca debería
# fallar si complete_standalone_deps ya tuvo éxito sobre el mismo contenido, pero es la
# comprobación que de verdad importa: valida los BYTES que se van a instalar, no una aproximación
# de ellos — detectaría, por ejemplo, un error del propio paso de "tar" (permisos perdidos, una
# entrada excluida por accidente) que complete_standalone_deps no vería.
isolated_boot_gate() {
  local artifact="$1" repo_dir="$2"
  if [ ! -f "$artifact" ]; then
    echo "FALLA: isolated_boot_gate: no existe el artefacto '$artifact'." >&2
    return 1
  fi
  local isolated
  isolated="$(mktemp -d)"
  assert_isolated_from_repo "$isolated" "$repo_dir" || { rm -rf "$isolated"; return 1; }
  # CLOUD-DEP-02B.1-E.3, DEP58-01: el stderr de "tar" se captura DENTRO del propio directorio
  # aislado (único por invocación, vía mktemp -d arriba) en vez de una ruta fija compartida bajo
  # /tmp — nunca puede colisionar entre invocaciones concurrentes, y el "rm -rf '$isolated'" que
  # ya existe en todos los caminos de salida de esta función lo limpia igual, sin necesitar un
  # "rm -f" aparte sobre una ruta ajena.
  local tar_err="$isolated/.tar-stderr.log"
  if ! tar -xzf "$artifact" -C "$isolated" 2>"$tar_err"; then
    echo "FALLA: isolated_boot_gate: no se pudo extraer '$artifact' (artefacto incompleto o corrupto)." >&2
    cat "$tar_err" >&2 2>/dev/null || true
    rm -rf "$isolated"
    return 1
  fi
  if [ ! -f "$isolated/standalone/server.js" ]; then
    echo "FALLA: isolated_boot_gate: el artefacto extraído no contiene standalone/server.js. Artefacto incompleto, rechazado." >&2
    rm -rf "$isolated"
    return 1
  fi
  local check_out check_status
  set +e
  check_out="$(boot_and_check "$isolated/standalone")"
  check_status=$?
  set -e
  rm -rf "$isolated"
  if [ "$check_status" -eq 0 ]; then
    echo "isolated_boot_gate: '$artifact' arranca de forma aislada y responde HTTP 200 en '/'."
    return 0
  fi
  echo "FALLA: isolated_boot_gate: '$artifact' NO pasó la prueba de arranque aislado (resultado: $check_out). Artefacto rechazado, no se genera manifiesto." >&2
  return 1
}

# --- Flujo principal -----------------------------------------------------------------------

main() {
  local REPO_DIR COMMIT OUT_DIR DOMAIN
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
  local actual_head
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

  echo "--- Completando dependencias de runtime del standalone (CLOUD-DEP-02B.1-E.2) ---"
  if ! complete_standalone_deps "$REPO_DIR/dist/standalone" "$REPO_DIR"; then
    echo "FALLA: no se pudo completar un standalone que arranque. No se empaqueta nada." >&2
    exit 1
  fi

  mkdir -p "$OUT_DIR"
  local artifact
  artifact="$OUT_DIR/vinto-mvp-frontend-${COMMIT}.tar.gz"
  rm -f "$artifact"
  tar -czf "$artifact" -C "$REPO_DIR/dist" standalone

  echo "--- Prueba de arranque aislado sobre el artefacto ya empaquetado (Fase C) ---"
  if ! isolated_boot_gate "$artifact" "$REPO_DIR"; then
    rm -f "$artifact"
    echo "FALLA: artefacto rechazado tras la prueba de arranque aislado; eliminado, no se genera manifiesto." >&2
    exit 1
  fi

  local artifact_sha256 node_version manifest
  artifact_sha256="$(sha256sum "$artifact" | awk '{print $1}')"
  node_version="$(node --version | sed 's/^v//')"

  manifest="$OUT_DIR/vinto-mvp-frontend-${COMMIT}.manifest"
  {
    printf 'VINTO_MVP_ARTIFACT_COMMIT=%s\n' "$COMMIT"
    printf 'VINTO_MVP_ARTIFACT_NODE_VERSION=%s\n' "$node_version"
    printf 'VINTO_MVP_ARTIFACT_SHA256=%s\n' "$artifact_sha256"
    printf 'VINTO_MVP_ARTIFACT_BUILT_AT=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  } > "$manifest"

  echo "Artefacto:   $artifact"
  echo "Manifiesto:  $manifest"
  echo "SHA-256:     $artifact_sha256"
  echo "Node usado:  $node_version"
  echo
  echo "Transferir ambos archivos al VPS (scp/rsync, fuera del alcance de este script) y luego:"
  echo "  CONFIRM=yes bash deploy.sh install-frontend-artifact $COMMIT <ruta-tar.gz-en-vps> <ruta-manifiesto-en-vps>"
}

# Igual que lib_common.sh (pensado para "source"): cuando verify_local.sh hace "source" de este
# archivo para probar las funciones de arriba de forma aislada (sin clonar ni compilar nada), NO
# se ejecuta "main" — solo cuando este archivo se invoca directamente ("bash build-frontend-artifact.sh ...").
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
