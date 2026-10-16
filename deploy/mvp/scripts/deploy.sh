#!/usr/bin/env bash
# VINTO MVP WEB — despliegue controlado (CLOUD-DEP-02A: preparado aquí; SE EJECUTA EN DEP-02B,
# tras autorización explícita de quien administra el VPS; NUNCA en este incremento).
# Corregido en CLOUD-DEP-02A.2 (DEP55-02/04) y en CLOUD-DEP-02A.2-R2 (punto 1 de la 3ª auditoría)
# tras las auditorías del PR #55.
#
# CLOUD-DEP-02A.2-R2, punto 1: "migrate" solo aplicaba con autorización explícita, pero nada
# impedía que "postgres-grants" o el primer arranque ("systemd-install") se ejecutaran igual
# aunque el esquema no estuviera migrado (si se saltaban fases fuera de orden). Ahora
# "postgres-grants", "systemd-install" y el reinicio dentro de "activate" verifican primero
# (lib_common.sh::assert_schema_migrated, "migrate.py --check") y se detienen con un mensaje claro
# si el esquema no está completo — la aprobación para APLICAR migraciones sigue siendo manual y
# explícita ("deploy.sh migrate"), esto solo IMPIDE continuar sin haberlo hecho.
#
# Principios de este script:
#   - Nunca toca nginx (eso es un paso separado y posterior — ver deploy/mvp/nginx/README más abajo
#     y Fase 5 de CLOUD-DEP-02A).
#   - Nunca toca TVC: ningún comando aquí nombra postgres-vinto, vinto-web.service, /opt/vinto-web
#     ni vinto_default.
#   - Nunca genera ni imprime contraseñas: exige que el operador ya haya creado
#     backend/.env (en deploy/mvp/env/shared, ver más abajo) y deploy/mvp/docker/.env a partir de
#     las plantillas .example, con las contraseñas reales puestas a mano.
#   - Cada fase se confirma por separado (variable CONFIRM=yes) para que un operador pueda
#     ejecutarlo fase por fase, revisando el resultado de cada una antes de seguir.
#   - No crea el rol vinto_test_admin en ningún momento (no se ejecuta backend/roles/00b_*.sql).
#   - Cada paso que modifica PostgreSQL queda limitado a vinto_piloto/vinto-mvp-postgres: ninguno
#     nombra postgres-vinto ni ninguna base de TVC (DEP55-02).
#
# Versionado por "releases" (DEP55-04): cada "checkout" clona en releases/<sha-completo>/, nunca
# reutiliza ni sobrescribe un release existente. "activate" conmuta atómicamente el symlink
# "current" a un release ya compilado, conservando siempre la referencia a la versión anterior
# (.previous-release-path) y dejando sus archivos intactos para poder revertir con
# rollback.sh version <sha-anterior> sin usar git en absoluto.
#
#   /opt/vinto-mvp-web/
#     shared/backend.env        <- el .env real, con contraseñas, fuera de cualquier release
#     releases/<sha>/           <- un checkout + venv + build completo por versión desplegada
#     current -> releases/<sha> <- symlink activo; lo referencian los units de systemd
#
# CLOUD-DEP-02B.1-C.1 ("build externo + runtime Node aislado"): el frontend ya NO se compila en
# el VPS. "install-frontend-artifact" instala un .tar.gz ya construido en Linux x86_64
# (deploy/mvp/scripts/build-frontend-artifact.sh, ejecutado fuera del VPS) tras verificar, ANTES
# de extraer nada, el commit del manifiesto, el checksum del .tar.gz y cada entrada dentro de él
# (CLOUD-DEP-02B.1-C.2, DEP56-01: ninguna fuera de "standalone/", ningún enlace ni dispositivo).
# "install-node-runtime" instala Node OFICIAL bajo $APP_DIR/runtime/ (nunca /usr/bin, nunca apt,
# nunca el PATH global) tras verificar su checksum contra env/node-runtime-checksums.txt, un
# archivo VERSIONADO en este repositorio (DEP56-02: nunca contra un SHASUMS256.txt suministrado
# junto al tarball en el momento de instalar — eso no demuestra procedencia). "validate-compose"
# resuelve el YAML de Postgres con el comando Compose disponible (plugin "docker compose" o
# binario "docker-compose", el que exista en el host — ver lib_common.sh::detect_compose_cmd) en
# modo silencioso (DEP56-03: nunca imprime la configuración resuelta, que contendría contraseñas),
# sin levantar ningún contenedor.
#
# Uso previsto (en el VPS, por fases, en este orden). DEP55-R2-02: el preflight ya no es un paso
# único — "preflight" cubre infraestructura/coexistencia, "preflight-build-deps" dependencias de
# compilación (repetir tras 'user-and-dirs', una vez existe el usuario de servicio) y
# "preflight-startup" justo antes de activar/arrancar:
#   CONFIRM=yes bash deploy.sh preflight
#   CONFIRM=yes bash deploy.sh user-and-dirs
#   bash deploy.sh preflight-build-deps
#   CONFIRM=yes bash deploy.sh install-node-runtime <version> <tarball>
#   CONFIRM=yes AUTHORIZED_COMMIT=<sha> bash deploy.sh checkout <sha>
#   CONFIRM=yes bash deploy.sh python-venv <sha>
#   CONFIRM=yes bash deploy.sh install-frontend-artifact <sha> <tar.gz> <manifiesto>
#   bash deploy.sh preflight-startup
#   CONFIRM=yes bash deploy.sh activate <sha>
#   CONFIRM=yes TVC_BACKUP_CONFIRMED=yes bash deploy.sh postgres-up
#   CONFIRM=yes bash deploy.sh postgres-bootstrap-db
#   CONFIRM=yes bash deploy.sh postgres-roles
#   CONFIRM=yes bash deploy.sh migrate
#   CONFIRM=yes bash deploy.sh postgres-grants
#   CONFIRM=yes bash deploy.sh import-reference
#   CONFIRM=yes bash deploy.sh systemd-install
#   CONFIRM=yes bash deploy.sh healthcheck

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/BaltrekCompany/vinto-mvp-web.git}"
SERVICE_USER=vinto-mvp
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=./lib_common.sh
source "$SCRIPT_DIR/lib_common.sh"
APP_DIR="$MVP_APP_DIR"

require_full_sha() {
  local commit="$1"
  if ! [[ "$commit" =~ ^[0-9a-f]{40}$ ]]; then
    echo "FALLA: '$commit' no es un SHA completo de 40 caracteres hexadecimales. Nunca se acepta una rama o un tag como commit a desplegar: podrían moverse después de autorizarse. Usar 'git rev-parse <ref>' para resolverlo primero." >&2
    exit 1
  fi
}

phase_preflight() {
  bash "$SCRIPT_DIR/preflight.sh" infra
}

phase_preflight_build_deps() {
  bash "$SCRIPT_DIR/preflight.sh" build-deps
}

phase_preflight_startup() {
  bash "$SCRIPT_DIR/preflight.sh" startup
}

phase_user_and_dirs() {
  require_confirm
  assert_service_user_is_ours "$SERVICE_USER"
  if id "$SERVICE_USER" >/dev/null 2>&1; then
    echo "El usuario $SERVICE_USER ya existe; no se recrea." >&2
  else
    sudo useradd --system --no-create-home --shell /usr/sbin/nologin "$SERVICE_USER"
    echo "Usuario de servicio $SERVICE_USER creado (sin login, sin home, aislado de 'ubuntu')."
  fi
  sudo mkdir -p "$APP_DIR/releases" "$APP_DIR/shared"
  sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"
  sudo chmod 750 "$APP_DIR" "$APP_DIR/releases" "$APP_DIR/shared"
  echo "Comprobando que $SERVICE_USER NO tiene acceso a los directorios de TVC (aislamiento, DEP55-04):"
  for path in "$TVC_APP_DIR" "$TVC_ETL_DIR"; do
    if sudo -u "$SERVICE_USER" test -r "$path" 2>/dev/null; then
      echo "FALLA: $SERVICE_USER puede leer $path. Esto no debería ser posible; revisar permisos antes de continuar." >&2
      exit 1
    else
      echo "  OK: $SERVICE_USER no puede leer $path."
    fi
  done
  if [ ! -f "$APP_DIR/shared/backend.env" ]; then
    echo "AVISO: $APP_DIR/shared/backend.env todavía no existe. Copiarlo de deploy/mvp/env/backend.env.example, completar con contraseñas reales y dejarlo con permisos 600, propietario $SERVICE_USER, antes de 'python-venv'." >&2
  fi
}

# Clona el commit EXACTO en un directorio de release nuevo, propio e inmutable. Nunca toca
# "current" (eso lo hace únicamente "activate", tras compilar con éxito) ni un release existente.
phase_checkout() {
  require_confirm
  local commit="${1:?Uso: deploy.sh checkout <commit-sha-40-caracteres>}"
  require_full_sha "$commit"
  if [ "${AUTHORIZED_COMMIT:-}" != "$commit" ]; then
    echo "FALLA: definir AUTHORIZED_COMMIT=$commit (exactamente igual al commit pedido) para confirmar de forma deliberada que ESTE commit concreto está autorizado a desplegarse. No hay valor por defecto ni atajo." >&2
    exit 1
  fi
  assert_service_user_is_ours "$SERVICE_USER"
  local release_dir="$APP_DIR/releases/$commit"
  if [ -e "$release_dir" ]; then
    echo "FALLA: ya existe $release_dir. Un release nunca se sobrescribe; si ya se compiló, usar 'activate $commit' directamente. Si está corrupto, revisar y borrar a mano tras confirmar que no es la versión activa." >&2
    exit 1
  fi
  sudo -u "$SERVICE_USER" mkdir -p "$APP_DIR/releases"
  sudo -u "$SERVICE_USER" git clone --quiet "$REPO_URL" "$release_dir"
  local actual_origin
  actual_origin="$(sudo -u "$SERVICE_USER" git -C "$release_dir" remote get-url origin)"
  if [ "$actual_origin" != "$REPO_URL" ]; then
    echo "FALLA: el origin clonado ('$actual_origin') no coincide con REPO_URL ('$REPO_URL'). No se usa este checkout." >&2
    sudo rm -rf "$release_dir"
    exit 1
  fi
  if ! sudo -u "$SERVICE_USER" git -C "$release_dir" cat-file -e "${commit}^{commit}" 2>/dev/null; then
    echo "FALLA: el commit $commit no existe en $REPO_URL. No se usa este checkout." >&2
    sudo rm -rf "$release_dir"
    exit 1
  fi
  # Checkout fresco en un directorio recién clonado y vacío: nunca hay cambios locales que
  # pudieran perderse, así que no se necesita (ni se usa) reset --hard/clean -f/checkout -- .
  sudo -u "$SERVICE_USER" git -C "$release_dir" checkout --quiet "$commit"
  local actual_head
  actual_head="$(sudo -u "$SERVICE_USER" git -C "$release_dir" rev-parse HEAD)"
  if [ "$actual_head" != "$commit" ]; then
    echo "FALLA: HEAD tras el checkout ($actual_head) no coincide con el commit pedido ($commit)." >&2
    exit 1
  fi
  echo "Checkout de $actual_head confirmado en $release_dir (origin verificado, commit autorizado explícitamente)."
  if [ -f "$APP_DIR/shared/backend.env" ]; then
    sudo -u "$SERVICE_USER" mkdir -p "$release_dir/backend"
    sudo -u "$SERVICE_USER" ln -s ../../../shared/backend.env "$release_dir/backend/.env"
  else
    echo "AVISO: $APP_DIR/shared/backend.env no existe todavía; crearlo antes de 'python-venv $commit'." >&2
  fi
  if [ -e "$APP_DIR/current" ]; then
    readlink -f "$APP_DIR/current" | sudo -u "$SERVICE_USER" tee "$release_dir/.previous-release-path" >/dev/null
    echo "Referencia a la versión anterior guardada (no se activa todavía)."
  fi
}

phase_python_venv() {
  require_confirm
  local commit="${1:?Uso: deploy.sh python-venv <commit-sha>}"
  require_full_sha "$commit"
  local release_dir="$APP_DIR/releases/$commit"
  if [ ! -d "$release_dir" ]; then
    echo "FALLA: $release_dir no existe. Ejecutar 'checkout $commit' primero." >&2
    exit 1
  fi
  if [ ! -f "$release_dir/backend/.env" ]; then
    echo "FALTA $release_dir/backend/.env (enlace a shared/backend.env, creado por 'checkout' si shared/backend.env ya existía). No se continúa." >&2
    exit 1
  fi
  local perms
  perms="$(stat -L -c '%a' "$release_dir/backend/.env")"
  if [ "$perms" != "600" ]; then
    echo "$APP_DIR/shared/backend.env tiene permisos $perms, deben ser 600. Corregir a mano y reintentar." >&2
    exit 1
  fi
  sudo -u "$SERVICE_USER" python3.12 -m venv "$release_dir/backend/.venv"
  sudo -u "$SERVICE_USER" "$release_dir/backend/.venv/bin/pip" install --no-cache-dir -r "$release_dir/backend/requirements.txt"
}

# CLOUD-DEP-02B.1-C.1: el frontend YA NO se compila en el VPS (eso exigiría Node/Corepack/pnpm
# instalados allí, aunque fuera de forma aislada, con todo el peso de un toolchain de build). Se
# compila fuera (deploy/mvp/scripts/build-frontend-artifact.sh, en Linux x86_64, igual arquitectura
# que el VPS) y el resultado — un .tar.gz de dist/standalone/ + un manifiesto de texto con el
# commit, la versión de Node usada y el checksum SHA-256 — se transfiere al VPS por el canal que
# decida el operador (scp/rsync; fuera del alcance de este script) ANTES de llamar a esta fase.
#
# Esta fase NUNCA confía en el nombre de archivo ni en la ruta: valida que el manifiesto declara
# EXACTAMENTE el commit pedido y que el checksum del artefacto coincide con el del manifiesto,
# ANTES de extraer nada. Si cualquiera de las dos cosas no coincide, rechaza el artefacto sin
# tocar el release. Nunca sobrescribe un "dist/" ya instalado en ese release.
phase_install_frontend_artifact() {
  require_confirm
  local commit="${1:?Uso: deploy.sh install-frontend-artifact <sha> <artefacto.tar.gz> <manifiesto>}"
  require_full_sha "$commit"
  local artifact="${2:?Uso: deploy.sh install-frontend-artifact <sha> <artefacto.tar.gz> <manifiesto>}"
  local manifest="${3:?Uso: deploy.sh install-frontend-artifact <sha> <artefacto.tar.gz> <manifiesto>}"
  local release_dir="$APP_DIR/releases/$commit"
  if [ ! -d "$release_dir" ]; then
    echo "FALLA: $release_dir no existe. Ejecutar 'checkout $commit' primero." >&2
    exit 1
  fi
  if [ ! -f "$artifact" ]; then
    echo "FALLA: no existe el artefacto $artifact." >&2
    exit 1
  fi
  if [ ! -f "$manifest" ]; then
    echo "FALLA: no existe el manifiesto $manifest." >&2
    exit 1
  fi
  local manifest_commit manifest_sha256
  manifest_commit="$(env_value "$manifest" VINTO_MVP_ARTIFACT_COMMIT)" || {
    echo "FALLA: el manifiesto no declara VINTO_MVP_ARTIFACT_COMMIT (ver mensaje anterior). Artefacto rechazado." >&2
    exit 1
  }
  manifest_sha256="$(env_value "$manifest" VINTO_MVP_ARTIFACT_SHA256)" || {
    echo "FALLA: el manifiesto no declara VINTO_MVP_ARTIFACT_SHA256 (ver mensaje anterior). Artefacto rechazado." >&2
    exit 1
  }
  if [ "$manifest_commit" != "$commit" ]; then
    echo "FALLA: el manifiesto declara el commit '$manifest_commit', no coincide con el commit pedido '$commit'. Artefacto rechazado, no se instala nada." >&2
    exit 1
  fi
  local actual_sha256
  actual_sha256="$(sha256sum "$artifact" | awk '{print $1}')" || true
  if [ "$actual_sha256" != "$manifest_sha256" ]; then
    echo "FALLA: el checksum del artefacto ($actual_sha256) no coincide con el declarado en el manifiesto ($manifest_sha256). Artefacto rechazado, no se instala nada." >&2
    exit 1
  fi
  if [ -e "$release_dir/dist" ]; then
    echo "FALLA: $release_dir/dist ya existe. Nunca se sobrescribe un artefacto ya instalado en este release." >&2
    exit 1
  fi

  # CLOUD-DEP-02B.1-C.2, DEP56-01: el commit/checksum ya verificados arriba demuestran que el
  # .tar.gz es EL QUE SE ESPERABA, pero no dicen nada sobre lo que hay DENTRO de cada entrada —
  # un artefacto con esas dos cosas correctas podría igual contener una ruta absoluta, un
  # recorrido "../", un enlace simbólico que escape del destino, o un dispositivo. Se valida cada
  # entrada ANTES de extraer (todas deben vivir bajo "standalone/", ninguna puede ser un enlace ni
  # un tipo especial) y se usa el filtro endurecido "data" de tarfile (Python 3.12, PEP 706) como
  # segunda barrera, nunca solo una de las dos. Se extrae en un STAGING propio, nunca directamente
  # sobre el release: solo si TODO resulta íntegro se mueve (mv, no copia parcial) al destino
  # final. El staging se borra en cualquier salida de esta fase (trap EXIT), nunca queda basura
  # propia ni se toca ninguna ruta ajena al staging/release de este commit.
  local staging_parent="$APP_DIR/.artifact-staging"
  sudo -u "$SERVICE_USER" mkdir -p "$staging_parent"
  local staging_dir
  staging_dir="$(sudo -u "$SERVICE_USER" mktemp -d "$staging_parent/XXXXXXXX")" || {
    echo "FALLA: no se pudo crear un directorio de staging." >&2
    exit 1
  }
  # shellcheck disable=SC2064 # se expande AHORA: la ruta exacta de ESTE staging.
  trap "sudo -u '$SERVICE_USER' rm -rf '$staging_dir' >/dev/null 2>&1" EXIT

  if ! sudo -u "$SERVICE_USER" python3.12 - "$artifact" "$staging_dir" <<'PYEOF'
import sys
import tarfile

artifact_path, staging_dir = sys.argv[1], sys.argv[2]
try:
    with tarfile.open(artifact_path, "r:gz") as tar:
        for member in tar.getmembers():
            name = member.name
            if name.startswith("/") or name.startswith("\\"):
                print(f"FALLA: ruta absoluta no permitida: {name}", file=sys.stderr)
                sys.exit(1)
            # Comprobación por COMPONENTE (no solo el prefijo de texto): "standalone/../../x"
            # empieza literalmente por "standalone/" pero sale del destino igualmente — se
            # rechaza aquí por nombre, y el filtro "data" de abajo es además la segunda barrera
            # real (confirmado: es quien efectivamente detiene un recorrido así).
            parts = name.split("/")
            if ".." in parts or "." in parts:
                print(f"FALLA: la entrada contiene un componente '..' o '.': {name}", file=sys.stderr)
                sys.exit(1)
            if parts[0] != "standalone":
                print(f"FALLA: entrada fuera de 'standalone/': {name}", file=sys.stderr)
                sys.exit(1)
            if member.issym() or member.islnk():
                print(f"FALLA: entrada de tipo enlace no permitida: {name}", file=sys.stderr)
                sys.exit(1)
            if not (member.isfile() or member.isdir()):
                print(f"FALLA: entrada de tipo no permitido ({member.type!r}): {name}", file=sys.stderr)
                sys.exit(1)
        # El filtro "data" (PEP 706, Python >= 3.12) es la segunda barrera: rechaza además rutas
        # absolutas, recorridos "..", y cualquier enlace/dispositivo que esta validación propia
        # hubiera dejado pasar por error.
        tar.extractall(path=staging_dir, filter="data")
except Exception as exc:  # noqa: BLE001 - cualquier excepción de tarfile es un rechazo, no un bug.
    print(f"FALLA: artefacto rechazado por tarfile: {exc}", file=sys.stderr)
    sys.exit(1)
PYEOF
  then
    echo "FALLA: el artefacto contiene entradas no permitidas (fuera de standalone/, enlaces, dispositivos, u otra violación detectada por el filtro 'data'). Rechazado, no se instaló nada." >&2
    exit 1
  fi

  if [ ! -f "$staging_dir/standalone/server.js" ]; then
    echo "FALLA: el artefacto extraído (en staging) no contiene standalone/server.js. No se mueve nada al release." >&2
    exit 1
  fi

  sudo -u "$SERVICE_USER" mkdir -p "$release_dir/dist"
  sudo -u "$SERVICE_USER" mv -T "$staging_dir/standalone" "$release_dir/dist/standalone"
  trap - EXIT
  sudo -u "$SERVICE_USER" rm -rf "$staging_dir"
  echo "Artefacto frontend instalado y verificado para $commit (commit y checksum coinciden con el manifiesto: $actual_sha256; contenido del tar validado entrada por entrada antes de extraer)."
}

# Instala una versión de Node AISLADA bajo $APP_DIR/runtime/, nunca en /usr/bin ni vía apt (nunca
# toca el PATH global, compartido con TVC/ETL).
#
# CLOUD-DEP-02B.1-C.2, DEP56-02: comparar el tarball contra un SHASUMS256.txt que viaja JUNTO a
# él (pasado como argumento, controlado por el mismo operador que el tarball) NO demuestra
# procedencia — quien pueda sustituir uno puede sustituir el otro. El checksum esperado se lee
# AHORA de env/node-runtime-checksums.txt, un archivo VERSIONADO en este repositorio cuyos valores
# se obtuvieron de forma independiente directamente desde nodejs.org y cuyo cambio exige un commit
# y una revisión de PR — nunca de un archivo suministrado en el momento de instalar. Si la versión
# pedida no está en esa lista, se rechaza: aprobarla es un cambio de código, no una decisión del
# operador en el momento del despliegue. Verificado ANTES de extraer nada; "runtime/active" nunca
# cambia si cualquier validación falla. Nunca borra una versión anterior: cada versión vive en su
# propio directorio (node-v<version>-linux-x64/) y "active" es un symlink que se conmuta
# atómicamente, igual que "current" para los releases de código.
phase_install_node_runtime() {
  require_confirm
  local version="${1:?Uso: deploy.sh install-node-runtime <version> <tarball.tar.xz>}"
  local tarball="${2:?Uso: deploy.sh install-node-runtime <version> <tarball.tar.xz>}"
  local checksums_file="$SCRIPT_DIR/../env/node-runtime-checksums.txt"
  if ! [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "FALLA: '$version' no tiene forma de versión (X.Y.Z)." >&2
    exit 1
  fi
  local tarball_name="node-v${version}-linux-x64.tar.xz"
  if [ "$(basename "$tarball")" != "$tarball_name" ]; then
    echo "FALLA: el tarball se llama '$(basename "$tarball")', se esperaba exactamente '$tarball_name'. Rechazado." >&2
    exit 1
  fi
  if [ ! -f "$checksums_file" ]; then
    echo "FALLA: no existe $checksums_file. No se puede instalar ninguna versión de Node sin un checksum aprobado y versionado en el repositorio." >&2
    exit 1
  fi
  local expected_sha256
  expected_sha256="$(grep -E "^${version} " "$checksums_file" | awk '{print $2}')" || true
  if [ -z "$expected_sha256" ]; then
    echo "FALLA: la versión '$version' no está en $checksums_file (no fue aprobada para este proyecto). Añadirla allí mediante una revisión de PR, con un checksum obtenido independientemente de nodejs.org, antes de poder instalarla." >&2
    exit 1
  fi
  local actual_sha256
  actual_sha256="$(sha256sum "$tarball" | awk '{print $1}')" || true
  if [ "$actual_sha256" != "$expected_sha256" ]; then
    echo "FALLA: el checksum del tarball ($actual_sha256) no coincide con el aprobado en el repositorio ($expected_sha256) — posible archivo corrupto o manipulado. Rechazado, no se instala; 'runtime/active' no se modifica." >&2
    exit 1
  fi
  local runtime_dir="$APP_DIR/runtime/node-v${version}-linux-x64"
  if [ -e "$runtime_dir" ]; then
    echo "$runtime_dir ya existe; no se reinstala ni se sobrescribe (una versión instalada nunca se borra al instalar otra)."
  else
    sudo -u "$SERVICE_USER" mkdir -p "$APP_DIR/runtime"
    sudo -u "$SERVICE_USER" tar -xJf "$tarball" -C "$APP_DIR/runtime"
    if [ ! -x "$runtime_dir/bin/node" ]; then
      echo "FALLA: tras extraer, no existe $runtime_dir/bin/node ejecutable. Abortando sin activar." >&2
      exit 1
    fi
  fi
  sudo -u "$SERVICE_USER" ln -sfn "$runtime_dir" "$APP_DIR/runtime/active.tmp"
  sudo -u "$SERVICE_USER" mv -T "$APP_DIR/runtime/active.tmp" "$APP_DIR/runtime/active"
  sudo -u "$SERVICE_USER" sh -c "printf 'INSTALLED_AT=%s VERSION=%s SHA256=%s\n' \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" '$version' '$actual_sha256' >> '$APP_DIR/runtime/INSTALLED.log'"
  echo "Runtime Node $version activo (runtime/active -> $runtime_dir). Checksum verificado: $actual_sha256."
}

# Valida el YAML de docker-compose.postgres.yml con el comando Compose realmente disponible en
# este host (lib_common.sh::detect_compose_cmd), SIN levantar ningún contenedor ni red
# persistente — "config" solo resuelve y muestra la configuración final.
# CLOUD-DEP-02B.1-C.3, DEP56-R2-01: la versión anterior pasaba la contraseña como ARGUMENTO de un
# proceso Python para redactarla de un log de error — un argumento de línea de comandos es visible
# en la lista de procesos del host mientras ese proceso corre (/proc/<pid>/cmdline, "ps aux"),
# exactamente el mismo problema que PG54-03 ya corrigió para las conexiones a PostgreSQL. La
# redacción, además, exigía CONSERVAR el detalle del error en algún sitio (aunque fuera
# temporalmente) para poder reescribirlo — un riesgo innecesario.
#
# Diseño nuevo, completamente silencioso y fail-closed: nunca se lee ni se pasa ningún secreto a
# esta función en absoluto (no hace falta conocer la contraseña para decidir si el YAML es
# válido). "config --quiet" ya no imprime nada en el camino exitoso; en el camino de error, el
# detalle de "${COMPOSE_CMD[@]} config" NUNCA se captura, nunca se imprime y nunca se escribe en
# ningún archivo — ni siquiera con permisos restrictivos (podría, en teoría, citar un valor
# interpolado) — solo se informa que la validación falló, un mensaje genérico, sin detalle.
phase_validate_compose() {
  detect_compose_cmd
  local compose_dir="$SCRIPT_DIR/../docker"
  if [ ! -f "$compose_dir/.env" ]; then
    echo "FALTA $compose_dir/.env. No se puede validar sin él (las variables son obligatorias en el YAML)." >&2
    exit 1
  fi
  # "-q/--quiet" ("Only validate the configuration, don't print anything") es obligatorio: si el
  # comando disponible no la soporta, se rechaza validar en vez de caer a un modo que sí
  # imprimiría la configuración resuelta (y las contraseñas que contiene).
  if ! "${COMPOSE_CMD[@]}" config --help 2>&1 | grep -qE '(^|[^-])(-q|--quiet)([^a-zA-Z-]|$)'; then
    echo "FALLA: '${COMPOSE_CMD[*]} config' no ofrece una opción de validación silenciosa (-q/--quiet) en este host. No se valida, para no arriesgar imprimir secretos resueltos." >&2
    exit 1
  fi
  # Redirigido a /dev/null, nunca capturado: si la validación falla, no queda ningún detalle en
  # ningún sitio que pudiera citar un valor interpolado — ni stdout, ni stderr, ni un archivo.
  if "${COMPOSE_CMD[@]}" -f "$compose_dir/docker-compose.postgres.yml" --env-file "$compose_dir/.env" \
      config --quiet >/dev/null 2>/dev/null; then
    echo "Compose command detectado: ${COMPOSE_CMD[*]}"
    echo "YAML válido (validación silenciosa con --quiet: no se imprimió ninguna configuración ni contraseña)."
    return 0
  fi
  echo "FALLA: el YAML de PostgreSQL no es válido con ${COMPOSE_CMD[*]}. El detalle no se muestra aquí deliberadamente (podría citar un valor interpolado del .env); para depurar, ejecutar manualmente '${COMPOSE_CMD[*]} -f docker-compose.postgres.yml --env-file .env config --quiet' y revisar su salida usted mismo, sabiendo que puede contener datos sensibles." >&2
  exit 1
}

# Conmuta "current" al release ya compilado. Es la ÚNICA fase que mueve el symlink para una
# activación normal: hasta este punto, cualquier fallo en checkout/python-venv/frontend-build deja
# "current" intacto apuntando a la versión previa en servicio (DEP55-04: "preparar versiones
# separadas para permitir rollback").
#
# DEP55-R2-04 ("recuperación de la versión anterior cuando una activación falla", "health checks
# después de reiniciar"): si los servicios YA estaban instalados, esta fase reinicia ambos y
# comprueba el healthcheck; si falla, revierte "current" automáticamente a la versión anterior y
# reinicia de nuevo, dejando el sistema en el último estado conocido-bueno en vez de a medio
# camino. Esta fase NUNCA toca PostgreSQL (ni esquema ni datos): revertir código y revertir un
# esquema de base de datos son operaciones independientes — un rollback de código nunca implica,
# por sí solo, deshacer una migración (ver backend/migrations/README.md para el procedimiento,
# aparte, de revertir una migración si alguna vez hiciera falta).
phase_activate() {
  require_confirm
  local commit="${1:?Uso: deploy.sh activate <commit-sha>}"
  require_full_sha "$commit"
  local release_dir="$APP_DIR/releases/$commit"
  if [ ! -x "$release_dir/backend/.venv/bin/uvicorn" ]; then
    echo "FALLA: $release_dir no tiene un venv con uvicorn instalado. Ejecutar 'python-venv $commit' primero." >&2
    exit 1
  fi
  if [ ! -f "$release_dir/dist/standalone/server.js" ]; then
    echo "FALLA: $release_dir no tiene el build del frontend. Ejecutar 'frontend-build $commit' primero." >&2
    exit 1
  fi

  local previous_target=""
  if [ -e "$APP_DIR/current" ]; then
    previous_target="$(readlink -f "$APP_DIR/current")"
    readlink -f "$APP_DIR/current" | sudo -u "$SERVICE_USER" tee "$APP_DIR/.previous-release-path" >/dev/null
  fi

  sudo -u "$SERVICE_USER" ln -sfn "$release_dir" "$APP_DIR/current.tmp"
  sudo -u "$SERVICE_USER" mv -T "$APP_DIR/current.tmp" "$APP_DIR/current"
  echo "'current' -> $release_dir."

  local units_installed=0
  if [ -f /etc/systemd/system/vinto-mvp-backend.service ] && [ -f /etc/systemd/system/vinto-mvp-frontend.service ]; then
    units_installed=1
  fi
  if [ "$units_installed" -ne 1 ]; then
    echo "Los units de systemd no están instalados todavía: nada que reiniciar. Continuar con 'systemd-install' para la primera activación."
    return 0
  fi

  # CLOUD-DEP-02A.2-R2-2, punto 1: no reiniciar (ni arrancar por primera vez) sobre un esquema
  # incompleto. Solo verifica (--check); aplicar migraciones sigue exigiendo su propia fase y
  # confirmación explícita ("deploy.sh migrate").
  assert_schema_migrated
  for unit in vinto-mvp-backend.service vinto-mvp-frontend.service; do
    assert_unit_is_ours "$unit"
  done
  sudo systemctl restart vinto-mvp-backend.service vinto-mvp-frontend.service
  echo "Servicios reiniciados con $commit. Verificando healthcheck..."
  sleep 2
  # Archivo único por ejecución (CLOUD-DEP-02A.2-R2-2, punto 3): nunca un nombre fijo compartido
  # entre invocaciones concurrentes o consecutivas; se borra en todos los caminos de salida.
  local hc_log
  hc_log="$(mktemp)"
  if mvp_healthcheck >"$hc_log" 2>&1; then
    cat "$hc_log"
    rm -f "$hc_log"
    echo "Healthcheck OK tras activar $commit."
    return 0
  fi
  echo "FALLA: el healthcheck no pasó tras activar $commit:" >&2
  cat "$hc_log" >&2
  rm -f "$hc_log"
  if [ -n "$previous_target" ] && [ -d "$previous_target" ]; then
    echo "Revirtiendo 'current' automáticamente a la versión anterior ($previous_target)..." >&2
    sudo -u "$SERVICE_USER" ln -sfn "$previous_target" "$APP_DIR/current.tmp"
    sudo -u "$SERVICE_USER" mv -T "$APP_DIR/current.tmp" "$APP_DIR/current"
    sudo systemctl restart vinto-mvp-backend.service vinto-mvp-frontend.service
    # CLOUD-DEP-02A.2-R2-2, punto 2: no afirmar que la recuperación fue exitosa sin comprobarlo.
    sleep 2
    local revert_hc_log
    revert_hc_log="$(mktemp)"
    if mvp_healthcheck >"$revert_hc_log" 2>&1; then
      rm -f "$revert_hc_log"
      echo "'current' revertido a $previous_target; healthcheck de la versión anterior OK tras reiniciar. $commit queda sin activar; investigar antes de reintentar." >&2
    else
      echo "'current' revertido a $previous_target, pero el healthcheck SIGUE SIN pasar tras reiniciar con la versión anterior (no se confirma que la recuperación automática haya funcionado):" >&2
      cat "$revert_hc_log" >&2
      rm -f "$revert_hc_log"
      echo "Intervención manual requerida de inmediato: ni $commit ni $previous_target responden al healthcheck." >&2
    fi
  else
    echo "No había una versión anterior a la que revertir automáticamente (primera activación real). Los servicios siguen apuntando a $commit, que no pasó el healthcheck: intervención manual requerida." >&2
  fi
  exit 1
}

phase_postgres_up() {
  require_confirm
  if [ "${TVC_BACKUP_CONFIRMED:-}" != "yes" ]; then
    echo "FALLA: esta fase crea/arranca PostgreSQL del MVP en el mismo host que TVC. Requiere TVC_BACKUP_CONFIRMED=yes (atestación explícita de que el backup de postgres-vinto existe y está verificado) antes de continuar." >&2
    exit 1
  fi
  local compose_dir="$SCRIPT_DIR/../docker"
  if [ ! -f "$compose_dir/.env" ]; then
    echo "FALTA $compose_dir/.env (copiar de deploy/mvp/env/postgres.env.example y completar a mano). No se continúa." >&2
    exit 1
  fi
  assert_container_is_ours "$MVP_POSTGRES_CONTAINER"
  assert_network_is_ours "$MVP_NETWORK"
  local pgdata_dir
  pgdata_dir="$(env_value "$compose_dir/.env" VINTO_MVP_PGDATA_DIR)"
  assert_path_not_shared_with_other_containers "$pgdata_dir"
  sudo mkdir -p "$pgdata_dir"
  sudo chown 999:999 "$pgdata_dir"  # UID/GID del rol postgres dentro de la imagen oficial
  detect_compose_cmd
  "${COMPOSE_CMD[@]}" -f "$compose_dir/docker-compose.postgres.yml" --env-file "$compose_dir/.env" up -d
  "${COMPOSE_CMD[@]}" -f "$compose_dir/docker-compose.postgres.yml" --env-file "$compose_dir/.env" ps
}

# Crea la base de negocio "vinto_piloto" dentro del contenedor del MVP (el contenedor arranca
# solo con la base de arranque POSTGRES_BOOTSTRAP_DB; "vinto_piloto" es la que usan la app y las
# migraciones, y no existe hasta esta fase). Operación de administrador del clúster, separada de
# las identidades de aplicación (DEP55-02).
phase_postgres_bootstrap_db() {
  require_confirm
  local compose_dir="$SCRIPT_DIR/../docker"
  local bootstrap_db bootstrap_user bootstrap_password
  bootstrap_db="$(env_value "$compose_dir/.env" POSTGRES_BOOTSTRAP_DB)"
  bootstrap_user="$(env_value "$compose_dir/.env" POSTGRES_BOOTSTRAP_USER)"
  bootstrap_password="$(env_value "$compose_dir/.env" POSTGRES_BOOTSTRAP_PASSWORD)"
  local exists
  exists="$(pg_run_sql_inline "$bootstrap_user" "$bootstrap_password" "$bootstrap_db" \
    "SELECT 1 FROM pg_database WHERE datname = 'vinto_piloto';")"
  if [ "$exists" = "1" ]; then
    echo "La base vinto_piloto ya existe; no se recrea."
  else
    pg_run_sql_inline "$bootstrap_user" "$bootstrap_password" "$bootstrap_db" \
      "CREATE DATABASE vinto_piloto OWNER ${bootstrap_user};"
    echo "Base vinto_piloto creada (propietaria: $bootstrap_user, el administrador del clúster; los 6 esquemas de dentro serán de vinto_migrator tras 'migrate')."
  fi
}

# Ejecuta 00_create_roles.sql y 01_database_grants.sql contra vinto_piloto, EXACTAMENTE en el
# orden de backend/roles/README.md, usando el release activo como fuente de los .sql y las
# contraseñas ya puestas en shared/backend.env (nunca se piden ni se imprimen de nuevo).
# Deliberadamente NO ejecuta 00b_create_test_admin_role.sql: vinto_test_admin nunca se crea aquí.
phase_postgres_roles() {
  require_confirm
  local compose_dir="$SCRIPT_DIR/../docker"
  local roles_dir="$APP_DIR/current/backend/roles"
  local backend_env="$APP_DIR/current/backend/.env"
  if [ ! -d "$roles_dir" ]; then
    echo "FALLA: $roles_dir no existe. Ejecutar 'activate <sha>' primero." >&2
    exit 1
  fi
  local bootstrap_db bootstrap_user bootstrap_password
  bootstrap_db="$(env_value "$compose_dir/.env" POSTGRES_BOOTSTRAP_DB)"
  bootstrap_user="$(env_value "$compose_dir/.env" POSTGRES_BOOTSTRAP_USER)"
  bootstrap_password="$(env_value "$compose_dir/.env" POSTGRES_BOOTSTRAP_PASSWORD)"
  local app_url migrator_url reference_url app_pw migrator_pw reference_pw
  app_url="$(env_value "$backend_env" DATABASE_URL)"
  migrator_url="$(env_value "$backend_env" MIGRATOR_DATABASE_URL)"
  reference_url="$(env_value "$backend_env" REFERENCE_DATABASE_URL)"
  app_pw="$(password_from_pg_url "$app_url")"
  migrator_pw="$(password_from_pg_url "$migrator_url")"
  reference_pw="$(password_from_pg_url "$reference_url")"
  echo "Ejecutando 00_create_roles.sql (idempotente) contra vinto_piloto, como $bootstrap_user..."
  pg_run_sql_file "$bootstrap_user" "$bootstrap_password" vinto_piloto "$roles_dir/00_create_roles.sql" \
    "APP_PASSWORD=$app_pw" "MIGRATOR_PASSWORD=$migrator_pw" "REFERENCE_PASSWORD=$reference_pw"
  echo "Ejecutando 01_database_grants.sql contra vinto_piloto, como $bootstrap_user..."
  pg_run_sql_file "$bootstrap_user" "$bootstrap_password" vinto_piloto "$roles_dir/01_database_grants.sql" \
    "DBNAME=vinto_piloto"
  echo "Roles y privilegios de base creados. Deliberadamente NO se ejecutó 00b_create_test_admin_role.sql."
  echo "Siguiente paso: 'migrate' (crea los esquemas como vinto_migrator), luego 'postgres-grants' (02-06)."
}

phase_migrate() {
  require_confirm
  local release_dir="$APP_DIR/current"
  if [ ! -d "$release_dir/backend" ]; then
    echo "FALLA: $release_dir/backend no existe. Ejecutar 'activate <sha>' primero." >&2
    exit 1
  fi
  cd "$release_dir/backend"
  # migrate.py lee backend/.env directamente (pydantic-settings, env_file=BACKEND_DIR/".env") y,
  # en PG_PRIVILEGE_MODE=hardened, usa MIGRATOR_DATABASE_URL (nunca la cuenta de la API): ver
  # resolve_role_url en backend/app/db_guard.py.
  sudo -u "$SERVICE_USER" "$release_dir/backend/.venv/bin/python" migrate.py --target dev --check
  echo "Si el --check anterior muestra pendientes, ejecutar 'migrate.py --target dev' (sin --check) solo tras revisar la salida."
}

# Ejecuta 02_schema_grants.sql .. 06_public_and_meta_protection.sql contra vinto_piloto, como
# vinto_migrator (ya es propietario de los 6 esquemas tras 'migrate'), exactamente en el orden de
# backend/roles/README.md.
phase_postgres_grants() {
  require_confirm
  local roles_dir="$APP_DIR/current/backend/roles"
  local backend_env="$APP_DIR/current/backend/.env"
  if [ ! -d "$roles_dir" ]; then
    echo "FALLA: $roles_dir no existe. Ejecutar 'activate <sha>' primero." >&2
    exit 1
  fi
  # CLOUD-DEP-02A.2-R2-2, punto 1: 02..06 otorgan privilegios SOBRE objetos que "migrate" crea;
  # sin el esquema migrado, estos GRANT fallarían contra objetos inexistentes o (peor) quedarían
  # aplicados de forma incompleta. Nunca continuar sin confirmar primero que el esquema está.
  assert_schema_migrated
  local migrator_url migrator_pw
  migrator_url="$(env_value "$backend_env" MIGRATOR_DATABASE_URL)"
  migrator_pw="$(password_from_pg_url "$migrator_url")"
  for step in 02_schema_grants 03_table_grants 04_function_grants 05_no_default_privileges 06_public_and_meta_protection; do
    echo "Ejecutando $step.sql contra vinto_piloto, como vinto_migrator..."
    pg_run_sql_file vinto_migrator "$migrator_pw" vinto_piloto "$roles_dir/$step.sql"
  done
  echo "02..06 aplicados. Ejecutar 07_verification_queries.sql a mano (solo lectura) para confirmar el modelo."
}

# Importa el catálogo OFICIAL (backend/seed_data) en vinto_piloto, como vinto_reference. Nunca un
# bundle candidato: import_reference.py ya rechaza --target dev --apply con un bundle distinto del
# oficial o marcado scope.candidate (ver backend/import_reference.py), coherente con un piloto
# cerrado que no ensaya catálogos no aprobados.
phase_import_reference() {
  require_confirm
  local release_dir="$APP_DIR/current"
  if [ ! -d "$release_dir/backend" ]; then
    echo "FALLA: $release_dir/backend no existe. Ejecutar 'activate <sha>' primero." >&2
    exit 1
  fi
  cd "$release_dir/backend"
  sudo -u "$SERVICE_USER" "$release_dir/backend/.venv/bin/python" import_reference.py --target dev
  echo "Dry-run anterior sin --apply: revisar la salida (crear=.../ya_presentes=...) antes de aplicar."
  echo "Para aplicar de verdad: CONFIRM=yes bash deploy.sh import-reference-apply"
}

phase_import_reference_apply() {
  require_confirm
  local release_dir="$APP_DIR/current"
  cd "$release_dir/backend"
  sudo -u "$SERVICE_USER" "$release_dir/backend/.venv/bin/python" import_reference.py --target dev --apply
}

phase_systemd_install() {
  require_confirm
  # CLOUD-DEP-02A.2-R2-2, punto 1: "impedir que ... el arranque continúen si el esquema requerido
  # no está migrado". El primer arranque del backend contra un esquema incompleto fallaría en
  # tiempo de ejecución; verificarlo aquí, antes de instalar/arrancar, evita ese fallo tardío.
  assert_schema_migrated
  for unit in vinto-mvp-backend.service vinto-mvp-frontend.service; do
    assert_unit_is_ours "$unit"
  done
  sudo cp "$SCRIPT_DIR/../systemd/vinto-mvp-backend.service" /etc/systemd/system/vinto-mvp-backend.service
  sudo cp "$SCRIPT_DIR/../systemd/vinto-mvp-frontend.service" /etc/systemd/system/vinto-mvp-frontend.service
  sudo systemctl daemon-reload
  sudo systemctl enable --now vinto-mvp-backend.service vinto-mvp-frontend.service
  sudo systemctl status --no-pager vinto-mvp-backend.service vinto-mvp-frontend.service
}

phase_healthcheck() {
  # Versión verbosa de uso manual (muestra cada respuesta). La MISMA comprobación, en forma
  # silenciosa para decidir pass/fail programáticamente, vive en lib_common.sh::mvp_healthcheck
  # y es la que usan "activate" y rollback.sh "version" para decidir si una activación/reversión
  # fue realmente exitosa — un único criterio de salud, nunca dos copias que puedan divergir
  # (CLOUD-DEP-02A.2-R2-2).
  curl -fsS http://127.0.0.1:8100/health && echo
  curl -fsS http://127.0.0.1:8100/api/health && echo
  curl -fsS http://127.0.0.1:3100/ >/dev/null && echo "frontend OK (127.0.0.1:3100)"
}

case "${1:-}" in
  preflight) phase_preflight ;;
  preflight-build-deps) phase_preflight_build_deps ;;
  preflight-startup) phase_preflight_startup ;;
  user-and-dirs) phase_user_and_dirs ;;
  checkout) phase_checkout "${2:-}" ;;
  python-venv) phase_python_venv "${2:-}" ;;
  install-frontend-artifact) phase_install_frontend_artifact "${2:-}" "${3:-}" "${4:-}" ;;
  install-node-runtime) phase_install_node_runtime "${2:-}" "${3:-}" ;;
  validate-compose) phase_validate_compose ;;
  activate) phase_activate "${2:-}" ;;
  postgres-up) phase_postgres_up ;;
  postgres-bootstrap-db) phase_postgres_bootstrap_db ;;
  postgres-roles) phase_postgres_roles ;;
  migrate) phase_migrate ;;
  postgres-grants) phase_postgres_grants ;;
  import-reference) phase_import_reference ;;
  import-reference-apply) phase_import_reference_apply ;;
  systemd-install) phase_systemd_install ;;
  healthcheck) phase_healthcheck ;;
  *)
    echo "Uso: deploy.sh {preflight|preflight-build-deps|preflight-startup|user-and-dirs|checkout <sha>|python-venv <sha>|install-frontend-artifact <sha> <tar.gz> <manifiesto>|install-node-runtime <version> <tarball>|validate-compose|activate <sha>|postgres-up|postgres-bootstrap-db|postgres-roles|migrate|postgres-grants|import-reference|import-reference-apply|systemd-install|healthcheck}" >&2
    exit 1
    ;;
esac
