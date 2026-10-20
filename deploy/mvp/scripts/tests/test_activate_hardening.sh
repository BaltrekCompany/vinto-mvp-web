#!/usr/bin/env bash
# VINTO MVP WEB — pruebas aisladas de assert_unit_is_ours, phase_activate y rollback_version
# (CLOUD-DEP-02B.2-G.12-B4-P3-H1).
#
# Motivo: un incidente real en la VPS dejó 'current' apuntando a un release nuevo mientras los
# servicios seguían ejecutando, sin reiniciar nunca, el release anterior -- causado por
# assert_unit_is_ours() tratando un fallo de LECTURA (grep sin privilegios contra un unit
# root:root 600) como una discrepancia de IDENTIDAD confirmada, y por phase_activate() conmutando
# el symlink 'current' ANTES de que esa y otras validaciones pudieran abortar la fase.
#
# Diseño de esta suite:
#   - Privilegio REAL, nunca simulado: se crean dos usuarios de verdad dentro de este contenedor
#     descartable ("testop", equivalente a "ubuntu", con sudo sin contraseña; "testsvc",
#     equivalente a "vinto-mvp", sin privilegios). assert_unit_is_ours/phase_activate/
#     rollback_version se ejecutan de verdad como "testop" contra un árbol de sandbox que posee
#     "testsvc" en exclusiva (750) -- la MISMA separación de identidades del incidente real, nunca
#     una aproximación. MVP_APP_DIR/MVP_SERVICE_USER usan la inyección por variable de entorno ya
#     prevista en lib_common.sh (": ${MVP_APP_DIR:=...}"), pensada exactamente para esto.
#   - "systemctl" y "curl" SÍ se simulan (funciones de shell): no hay systemd real arrancado como
#     PID 1 en este contenedor ni servicios HTTP reales que probar -- lo que se verifica es la
#     LÓGICA de control (orden de operaciones, manejo de códigos de salida, rollback automático),
#     no el resultado real de reiniciar un proceso.
#   - Las unidades systemd de prueba SÍ se escriben en /etc/systemd/system -- pero SOLO dentro de
#     este contenedor Docker descartable (--rm), NUNCA en la VPS real ni en el host. Ningún otro
#     archivo de este contenedor se toca fuera de /etc/systemd/system/vinto-mvp-*.service y el
#     sandbox temporal de cada prueba.
#   - "current" es un symlink real dentro del sandbox: cada prueba comprueba su destino real con
#     "readlink", nunca solo el código de salida de la fase.
#
# Ejecutar DENTRO de un contenedor descartable (ver deploy/mvp/scripts/tests/README_activate_hardening.md
# o el informe de la ronda G.12-B4-P3-H1 para el comando docker run exacto). Requiere: bash,
# coreutils, sudo, getent/useradd (base Debian/Ubuntu). Nunca requiere Docker, PostgreSQL ni
# systemd real -- y nunca debe ejecutarse contra la VPS real ni contra el host.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export SCRIPT_DIR

# CLOUD-DEP-02B.2-G.12-B4-P3-H2: el candado vive en $SCRIPT_DIR/.activate.lock (ver lib_common.sh),
# NUNCA dentro de $MVP_APP_DIR (que cambia por sandbox/prueba) -- es decir, es la MISMA ruta para
# TODAS las pruebas de este archivo, igual que en el VPS real (un único $SCRIPT_DIR para todas las
# invocaciones de un operador). Nunca se borra entre pruebas (mismo comportamiento que el real):
# basta con que cada prueba espere a que su propio subproceso termine antes de que empiece la
# siguiente para que el candado quede libre (el kernel lo libera al cerrarse el descriptor, sin
# limpieza de este archivo). acquire_activate_lock() corre como $OP_USER, SIN sudo -- por eso
# $SCRIPT_DIR debe pertenecerle (en el VPS real, $SCRIPT_DIR ya es de "ubuntu"; aquí se iguala
# explícitamente, cosa que las rondas anteriores no necesitaban porque no existía ningún candado).
LOCK_FILE="$SCRIPT_DIR/.activate.lock"

PASS=0
FAILED=0
report() {
  if [ "$2" -eq 0 ]; then
    printf 'PASS  %s\n' "$1"; PASS=$((PASS + 1))
  else
    printf 'FAIL  %s\n' "$1"; FAILED=$((FAILED + 1))
  fi
}

if [ "$(id -u)" -ne 0 ]; then
  echo "Esta suite necesita ejecutarse como root DENTRO de un contenedor descartable (crea usuarios y escribe en /etc/systemd/system de ESE contenedor, nunca de la VPS real ni del host)." >&2
  exit 2
fi

OP_USER="testop"      # equivalente a "ubuntu": invocador, con sudo sin contraseña.
SVC_USER="testsvc"    # equivalente a "vinto-mvp": propietario exclusivo del sandbox, sin login.
NEW_SHA="000000000000000000000000000000000000001a"
OLD_SHA="000000000000000000000000000000000000002b"

MOCK_SYSTEMCTL_LOG=/tmp/.mock-systemctl-calls.log
MOCK_SYSTEMCTL_EXIT_FILE=/tmp/.mock-systemctl-exit

setup_users_once() {
  getent passwd "$SVC_USER" >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin "$SVC_USER"
  getent passwd "$OP_USER" >/dev/null 2>&1 || useradd --create-home --shell /bin/bash "$OP_USER"
  echo "$OP_USER ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-$OP_USER-test"
  chmod 440 "/etc/sudoers.d/90-$OP_USER-test"
  # CLOUD-DEP-02B.2-G.12-B4-P3-H2: acquire_activate_lock() (lib_common.sh) abre
  # $SCRIPT_DIR/.activate.lock SIN sudo -- igual que en el VPS real, donde $SCRIPT_DIR ya
  # pertenece al operador ("ubuntu"). Aquí $SCRIPT_DIR es el árbol de scripts de ESTE
  # contenedor descartable; se iguala su propietario a $OP_USER por el mismo motivo.
  # Salvaguarda defensiva (nunca confiar ciegamente en "-R" sobre una variable): si $SCRIPT_DIR
  # no es la ruta esperada (absoluta, de al menos dos niveles, terminada en ".../scripts"), se
  # rehúsa a recursar -- un "chown -R" sobre "/" por un cálculo erróneo de SCRIPT_DIR sería
  # catastrófico para todo el contenedor. Confirmado necesario en esta misma ronda: un intento de
  # depuración con un script reubicado en otra ruta hizo que SCRIPT_DIR se calculara como "/".
  case "$SCRIPT_DIR" in
    /*/scripts) chown -R "$OP_USER:$OP_USER" "$SCRIPT_DIR" 2>/dev/null || true ;;
    *) echo "setup_users_once: SCRIPT_DIR ('$SCRIPT_DIR') no tiene la forma esperada ('/.../scripts'); no se recursa chown sobre él. Abortando la suite." >&2; exit 2 ;;
  esac
  # CLOUD-DEP-02B.2-G.12-B4-P3-H2: crear el archivo del candado AHORA, ya como $OP_USER y con
  # 600 -- antes de que ninguna prueba corra. Sin esto, "wait_for_lock_held"/"wait_for_lock_
  # released" (que sondean el candado desde ESTE proceso, que corre como root) podrían GANARLE la
  # carrera a la primera activación/reversión real de la suite y CREAR ellos mismos el archivo
  # (como root, con el modo por defecto) antes de que $OP_USER llegue a "acquire_activate_lock" --
  # dejando un archivo root:root que $OP_USER ya no puede abrir para escritura ("Permission
  # denied"). Confirmado como causa real de una prueba intermitente en esta misma ronda.
  sudo -u "$OP_USER" bash -c "exec 9>'$LOCK_FILE'; chmod 600 '$LOCK_FILE'" 2>/dev/null || true
  # "sudo systemctl ..." (como lo hace phase_activate/rollback_version de verdad) exec-a un
  # proceso NUEVO vía PATH -- una función de shell definida en el proceso que llama a "sudo" es
  # INVISIBLE para ese proceso nuevo (las funciones nunca cruzan un exec real). Por eso el mock de
  # "systemctl" es un EJECUTABLE real en PATH, nunca una función -- a diferencia de "curl" (que
  # mvp_healthcheck llama directo, sin "sudo" por delante, así que una función SÍ es visible ahí).
  # Controlado por archivos (no por variables de entorno: tampoco cruzan el "sudo" de systemctl)
  # con un nombre fijo y conocido, reinicializados por cada prueba.
  cat > /usr/local/bin/systemctl <<'SYSTEMCTL_MOCK'
#!/bin/sh
echo "$@" >> /tmp/.mock-systemctl-calls.log
if [ "$1" = "restart" ]; then
  # CLOUD-DEP-02B.2-G.12-B4-P3-H2: comprobación REAL (via /proc), no asumida, de que este hijo de
  # "systemctl restart" -- y cualquier nieto que el propio hijo genere -- no hereda el descriptor
  # del candado de activate/rollback. Resultado en un archivo fijo, reinicializado por la prueba
  # que lo necesite; el resto de las pruebas lo ignora sin que esto cambie su comportamiento.
  sleep 30 &
  child=$!
  sleep 0.2
  if ls -la "/proc/$child/fd/" 2>/dev/null | grep -qi 'activate\.lock'; then
    echo "INHERITED" >> /tmp/.mock-systemctl-fdcheck.log
  else
    echo "NOT-INHERITED" >> /tmp/.mock-systemctl-fdcheck.log
  fi
  kill "$child" 2>/dev/null
  wait "$child" 2>/dev/null
  exit "$(cat /tmp/.mock-systemctl-exit 2>/dev/null || echo 0)"
fi
exit 0
SYSTEMCTL_MOCK
  chmod 755 /usr/local/bin/systemctl
}
setup_users_once

reset_systemctl_mock() {
  rm -f "$MOCK_SYSTEMCTL_LOG" "$MOCK_SYSTEMCTL_EXIT_FILE"
  printf '%s' "${1:-0}" > "$MOCK_SYSTEMCTL_EXIT_FILE"
}

# --- sandbox de $APP_DIR: dos releases reales, "current" apuntando al anterior ------------------
# $1 (opcional): código de salida que debe devolver "migrate.py --check" (assert_schema_migrated)
# en el release AL QUE YA APUNTA 'current' (el chequeo de esquema corre sobre 'current', antes de
# conmutarlo) -- grabado DIRECTAMENTE en el script al crearlo (nunca leído de una variable de
# entorno en tiempo de ejecución: "sudo -u $MVP_SERVICE_USER <python> ..." es un "sudo" real, que
# no propaga el entorno del invocador salvo que se liste explícitamente -- mismo motivo por el que
# "systemctl" tampoco puede simularse con una variable de entorno).
make_sandbox() {
  local schema_exit="${1:-0}"
  # CLOUD-DEP-02B.2-G.12-B4-P3-H2: "schema_sleep" (2do parámetro, por defecto 0) hace que el
  # "migrate.py --check" DEL RELEASE AL QUE YA APUNTA 'current' (OLD_SHA, comprobado por
  # assert_schema_migrated ANTES de conmutar) duerma esa cantidad de segundos antes de responder.
  # Se usa únicamente para abrir una ventana de tiempo controlada y real -- nunca un "sleep" suelto
  # en la propia prueba -- entre "acquire_activate_lock" (ya adquirido justo antes, al principio de
  # phase_activate) y la conmutación de 'current', durante la cual una SEGUNDA invocación
  # concurrente puede intentar (y debe fallar) adquirir el mismo candado.
  local schema_sleep="${2:-0}"
  local dir
  dir="$(mktemp -d /tmp/sandbox-XXXXXX)"
  for sha in "$OLD_SHA" "$NEW_SHA"; do
    mkdir -p "$dir/releases/$sha/backend/.venv/bin" "$dir/releases/$sha/dist/standalone"
    printf '#!/bin/sh\nexit 0\n' > "$dir/releases/$sha/backend/.venv/bin/uvicorn"
    chmod +x "$dir/releases/$sha/backend/.venv/bin/uvicorn"
    : > "$dir/releases/$sha/dist/standalone/server.js"
    mkdir -p "$dir/releases/$sha/backend"
    : > "$dir/releases/$sha/backend/migrate.py"
    local this_exit=0 this_sleep=0
    if [ "$sha" = "$OLD_SHA" ]; then
      this_exit="$schema_exit"
      this_sleep="$schema_sleep"
    fi
    printf '#!/bin/sh\nsleep %s\nexit %s\n' "$this_sleep" "$this_exit" > "$dir/releases/$sha/backend/.venv/bin/python"
    chmod +x "$dir/releases/$sha/backend/.venv/bin/python"
  done
  ln -sfn "$dir/releases/$OLD_SHA" "$dir/current"
  chown -R "$SVC_USER:$SVC_USER" "$dir"
  chmod 750 "$dir"
  printf '%s' "$dir"
}

# wait_for_lock_held/wait_for_lock_released: sondean el ESTADO REAL del candado compartido
# ($LOCK_FILE) usando el mismo "flock -n" que acquire_activate_lock -- nunca un "sleep" fijo ni
# ningún texto de log -- para sincronizar con precisión el momento en que una segunda invocación
# concurrente debe intentar adquirirlo. Cada sondeo abre y cierra su PROPIO descriptor efímero
# (nunca el de ninguna prueba), así que sondear en sí nunca interfiere con el candado real.
wait_for_lock_held() {
  local max_wait="${1:-50}" waited=0
  while [ "$waited" -lt "$max_wait" ]; do
    if ! ( exec 9>"$LOCK_FILE"; flock -n 9 ) 2>/dev/null; then
      return 0
    fi
    sleep 0.1; waited=$((waited + 1))
  done
  return 1
}
wait_for_lock_released() {
  local max_wait="${1:-50}" waited=0
  while [ "$waited" -lt "$max_wait" ]; do
    if ( exec 9>"$LOCK_FILE"; flock -n 9 ) 2>/dev/null; then
      return 0
    fi
    sleep 0.1; waited=$((waited + 1))
  done
  return 1
}

# --- unidades systemd reales de prueba, SOLO en este contenedor ---------------------------------
UNIT_B=/etc/systemd/system/vinto-mvp-backend.service
UNIT_F=/etc/systemd/system/vinto-mvp-frontend.service

write_legit_units() {
  local app_dir="$1"
  for u in "$UNIT_B" "$UNIT_F"; do
    cat > "$u" <<EOF
[Service]
WorkingDirectory=$app_dir/current/backend
ExecStart=$app_dir/current/backend/.venv/bin/uvicorn
EOF
    chown root:root "$u"
    chmod 600 "$u"
  done
}

write_foreign_units() {
  for u in "$UNIT_B" "$UNIT_F"; do
    cat > "$u" <<'EOF'
[Service]
WorkingDirectory=/opt/otro-proyecto/current/backend
ExecStart=/opt/otro-proyecto/current/backend/.venv/bin/uvicorn
EOF
    chown root:root "$u"
    chmod 600 "$u"
  done
}

remove_units() { rm -f "$UNIT_B" "$UNIT_F"; }

# Ejecuta una prueba como $OP_USER, en un proceso bash COMPLETAMENTE NUEVO (nunca un "( ... )"
# anidado -- mismo motivo que test_assert_path_not_shared.sh/test_pg_run_sql_file.sh: reproduce
# fielmente cómo corren deploy.sh/rollback.sh de verdad, invocados una vez, de cero).
run_as_op() {
  local app_dir="$1"; shift
  sudo -u "$OP_USER" --preserve-env=SCRIPT_DIR,MVP_APP_DIR,MVP_SERVICE_USER,MOCK_SCHEMA_EXIT,MOCK_SYSTEMCTL_EXIT,MOCK_HEALTHCHECK_OK,MOCK_SEND_SIGNAL \
    env MVP_APP_DIR="$app_dir" MVP_SERVICE_USER="$SVC_USER" CONFIRM=yes \
    bash -c "$1" bash "${@:2}"
}

# ==================================================================================================
# 1-4: assert_unit_is_ours en aislamiento (privilegio REAL, nunca simulado)
# ==================================================================================================
ASSERT_UNIT_SNIPPET='
  set -uo pipefail
  source "$SCRIPT_DIR/lib_common.sh"
  assert_unit_is_ours "$1"
'

test_unidad_legitima_600_root() {
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  local rc=0
  run_as_op "$app_dir" "$ASSERT_UNIT_SNIPPET" "vinto-mvp-backend.service" >/tmp/tah1.out 2>&1 || rc=$?
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 0 ]
}

test_unidad_ajena_rechazada() {
  local app_dir; app_dir="$(make_sandbox)"
  write_foreign_units
  local rc=0
  run_as_op "$app_dir" "$ASSERT_UNIT_SNIPPET" "vinto-mvp-backend.service" >/tmp/tah2.out 2>&1 || rc=$?
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 1 ] && grep -q "FALLA DE IDENTIDAD" /tmp/tah2.out
}

test_unidad_ilegible_incluso_con_privilegio() {
  # Un unit real pero con un dueño/grupo que ni siquiera root puede resolver via sudo normal es
  # difícil de forzar de forma segura; se simula el mismo efecto práctico revocando "sudo" al
  # operador para ESTA prueba puntual (perfil de sudoers vacío) -- así "sudo cat" falla de verdad
  # por falta de privilegio, igual que "no pude leerlo" en el código.
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  rm -f "/etc/sudoers.d/90-$OP_USER-test"
  local rc=0
  run_as_op "$app_dir" "$ASSERT_UNIT_SNIPPET" "vinto-mvp-backend.service" >/tmp/tah3.out 2>&1 || rc=$?
  echo "$OP_USER ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-$OP_USER-test"
  chmod 440 "/etc/sudoers.d/90-$OP_USER-test"
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 1 ] && grep -q "no se pudo leer" /tmp/tah3.out && ! grep -q "FALLA DE IDENTIDAD" /tmp/tah3.out
}

test_unidad_ausente() {
  local app_dir; app_dir="$(make_sandbox)"
  remove_units
  local rc=0
  run_as_op "$app_dir" "$ASSERT_UNIT_SNIPPET" "vinto-mvp-backend.service" >/tmp/tah4.out 2>&1 || rc=$?
  rm -rf "$app_dir"
  [ "$rc" -eq 0 ]
}

# ==================================================================================================
# 5-20: phase_activate / rollback_version completos, con systemctl/curl simulados
# ==================================================================================================
# Snippet común: neutraliza el "exit" del dispatch final de deploy.sh SOLO durante el "source"
# (evitaría terminar este proceso con el uso: deploy.sh {...}), define systemctl/curl simulados
# (controlados por MOCK_SYSTEMCTL_EXIT / MOCK_HEALTHCHECK_OK, variables de entorno ya exportadas
# por "env ..." en run_as_op), y deja $SERVICE_USER (deploy.sh lo fija con un "=" plano, no
# inyectable por entorno) alineado con $MVP_SERVICE_USER para esta prueba.
ACTIVATE_PRELUDE='
  set -uo pipefail
  # "systemctl" NO se simula aquí como función: phase_activate/rollback_version siempre lo llaman
  # vía "sudo systemctl ...", que exec-a un proceso nuevo por PATH -- una función de este shell es
  # invisible ahí. El mock real es el ejecutable /usr/local/bin/systemctl (ver setup_users_once),
  # controlado por archivos fijos (reset_systemctl_mock), nunca por esta variable de entorno.
  curl() {
    [ "${MOCK_HEALTHCHECK_OK:-1}" = "1" ] && return 0
    return 7
  }
  # deploy.sh/rollback.sh activan "set -e" en su propia cabecera, y eso persiste en ESTE shell
  # tras un "source" (set es global, no por archivo). Neutralizar "exit" como función NO basta
  # por sí solo: bajo "set -e", que esa función devuelva un código distinto de 0 en la última
  # instrucción del "case" de despacho (ejecutado al sourcear, con "$1" vacío -> rama "*)") aborta
  # igual todo el proceso, sin llegar siquiera a la línea siguiente de este mismo preludio. Por
  # eso el "exit" simulado aquí SIEMPRE devuelve 0 (su código real no le importa a nadie: es pura
  # salida de uso del despacho), y además se desactiva "errexit" explícitamente justo después de
  # sourcear, para que el resto de esta prueba corra bajo "set -uo pipefail" únicamente, igual que
  # el resto de este archivo.
  exit() { return 0; }
  source "$SCRIPT_DIR/lib_common.sh"
  source "$SCRIPT_DIR/deploy.sh"
  source "$SCRIPT_DIR/rollback.sh"
  set +e
  unset -f exit
  SERVICE_USER="$MVP_SERVICE_USER"
'

test_prevalidacion_fallida_current_no_cambia() {
  # Unidad ajena -> assert_unit_is_ours debe abortar la fase ANTES de tocar "current" (orden
  # corregido en phase_activate).
  local app_dir; app_dir="$(make_sandbox)"
  write_foreign_units
  local before after rc=0
  before="$(readlink "$app_dir/current")"
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'
    phase_activate "'"$NEW_SHA"'"
  ' >/tmp/tah5.out 2>&1 || rc=$?
  after="$(readlink "$app_dir/current")"
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 1 ] && [ "$before" = "$after" ] && grep -q "FALLA DE IDENTIDAD" /tmp/tah5.out
}

test_esquema_no_migrado_current_no_cambia() {
  local app_dir; app_dir="$(make_sandbox 1)"
  write_legit_units "$app_dir"
  local before after rc=0
  before="$(readlink "$app_dir/current")"
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'
    phase_activate "'"$NEW_SHA"'"
  ' >/tmp/tah6.out 2>&1 || rc=$?
  after="$(readlink "$app_dir/current")"
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 1 ] && [ "$before" = "$after" ] && grep -q "esquema de vinto_piloto no está completamente migrado" /tmp/tah6.out
}

test_identidad_invalida_actor_current_no_cambia() {
  # Reutiliza el caso "unidad ilegible": revocar sudo al operador hace que assert_unit_is_ours
  # falle por lectura ANTES de tocar current (mismo punto de la prevalidación).
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  rm -f "/etc/sudoers.d/90-$OP_USER-test"
  local before after rc=0
  before="$(readlink "$app_dir/current")"
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'
    phase_activate "'"$NEW_SHA"'"
  ' >/tmp/tah7.out 2>&1 || rc=$?
  after="$(readlink "$app_dir/current")"
  echo "$OP_USER ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-$OP_USER-test"
  chmod 440 "/etc/sudoers.d/90-$OP_USER-test"
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 1 ] && [ "$before" = "$after" ]
}

test_activacion_exitosa_conmuta_y_reinicia() {
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  local after rc=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'
    phase_activate "'"$NEW_SHA"'"
  ' >/tmp/tah8.out 2>&1 || rc=$?
  after="$(readlink "$app_dir/current")"
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 0 ] && [ "$after" = "$app_dir/releases/$NEW_SHA" ] \
    && grep -q "restart vinto-mvp-backend.service vinto-mvp-frontend.service" "$MOCK_SYSTEMCTL_LOG"
}

test_fallo_reinicio_backend_dispara_rollback_automatico() {
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 1
  local after rc=0
  MOCK_HEALTHCHECK_OK=0 run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'
    phase_activate "'"$NEW_SHA"'"
  ' >/tmp/tah9.out 2>&1 || rc=$?
  after="$(readlink "$app_dir/current")"
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 1 ] && [ "$after" = "$app_dir/releases/$OLD_SHA" ] && grep -q "revertido a" /tmp/tah9.out
}

test_fallo_reinicio_frontend_tratado_igual() {
  # El mock de systemctl no distingue backend/frontend (ambos se reinician en una sola llamada,
  # igual que el código real); esta prueba confirma que el AVISO explícito del código de salida
  # aparece de todos modos, sin ocultar el fallo detrás de un reinicio "silencioso".
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 1
  local rc=0
  MOCK_HEALTHCHECK_OK=1 run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'
    phase_activate "'"$NEW_SHA"'"
  ' >/tmp/tah10.out 2>&1 || rc=$?
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 0 ] && grep -q "AVISO: 'systemctl restart' devolvió el código 1" /tmp/tah10.out
}

test_fallo_healthcheck_dispara_rollback() {
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  local after rc=0
  MOCK_HEALTHCHECK_OK=0 run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'
    phase_activate "'"$NEW_SHA"'"
  ' >/tmp/tah11.out 2>&1 || rc=$?
  after="$(readlink "$app_dir/current")"
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 1 ] && [ "$after" = "$app_dir/releases/$OLD_SHA" ]
}

test_rollback_automatico_exitoso() {
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  local rc=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'
    # El healthcheck de la activación (1er intento) debe fallar; el de la reversión (2do intento,
    # tras revertir current) debe responder OK -- un contador de llamadas distingue ambos, ya que
    # phase_activate llama al mismo "curl" simulado en los dos momentos. mvp_healthcheck encadena
    # 3 "curl" con "&&": si el PRIMERO falla, los otros dos ni se invocan -- el primer intento
    # completo consume exactamente 1 llamada, nunca 3.
    CURL_CALLS=0
    curl() {
      CURL_CALLS=$((CURL_CALLS + 1))
      [ "$CURL_CALLS" -le 1 ] && return 7
      return 0
    }
    phase_activate "'"$NEW_SHA"'"
  ' >/tmp/tah12.out 2>&1 || rc=$?
  local after; after="$(readlink "$app_dir/current")"
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 1 ] && [ "$after" = "$app_dir/releases/$OLD_SHA" ] && grep -q "healthcheck de la versión anterior OK" /tmp/tah12.out
}

test_rollback_automatico_fallido_error_explicito() {
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  local rc=0
  MOCK_HEALTHCHECK_OK=0 run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'
    phase_activate "'"$NEW_SHA"'"
  ' >/tmp/tah13.out 2>&1 || rc=$?
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 1 ] && grep -q "Intervención manual requerida de inmediato" /tmp/tah13.out
}

test_senal_interrupcion_controlable() {
  # Envía SIGTERM al proceso bash que ejecuta phase_activate justo después de que 'current' ya
  # haya sido conmutado -- detectado consultando el símbolo real "current" en el sandbox (nunca
  # el texto del log: evita cualquier dependencia del buffering de stdout de un proceso hijo).
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'
    phase_activate "'"$NEW_SHA"'"
  ' >/tmp/tah14.out 2>&1 &
  local pid=$!
  local waited=0
  while [ "$waited" -lt 50 ]; do
    [ "$(readlink -f "$app_dir/current" 2>/dev/null)" = "$app_dir/releases/$NEW_SHA" ] && break
    sleep 0.1; waited=$((waited + 1))
  done
  kill -TERM "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null
  local after; after="$(readlink -f "$app_dir/current")"
  # CLOUD-DEP-02B.2-G.12-B4-P3-H2: "wait $pid" solo espera al envoltorio inmediato de
  # "run_as_op ... &" (la función en segundo plano) -- NUNCA al "sudo"/"bash -c" real que
  # ejecuta phase_activate más abajo en el árbol de procesos. Confirmado empíricamente en esta
  # ronda: un "kill -TERM" sobre ESE envoltorio lo termina a él, pero el proceso real que todavía
  # sostiene el candado queda HUÉRFANO y sigue corriendo por su cuenta (terminará solo, de forma
  # normal, cuando le toque) -- sin este drenaje, el candado compartido seguiría ocupado para la
  # SIGUIENTE prueba de la suite durante esa cola. Mejor esfuerzo (nunca parte de la aserción de
  # ESTA prueba en concreto, que ya se verificó arriba): solo evita contaminar a las pruebas de
  # después con un candado que no es suyo.
  wait_for_lock_released 100 || true
  remove_units; rm -rf "$app_dir"
  [ "$after" = "$app_dir/releases/$NEW_SHA" ]
}

test_segundo_intento_tras_recuperacion_consistente() {
  # Tras una activación exitosa, un segundo "activate" al MISMO commit debe ser idempotente: no
  # hay fallo nuevo, 'current' sigue en el release nuevo.
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  local rc1=0 rc2=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah15a.out 2>&1 || rc1=$?
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah15b.out 2>&1 || rc2=$?
  local after; after="$(readlink "$app_dir/current")"
  remove_units; rm -rf "$app_dir"
  [ "$rc1" -eq 0 ] && [ "$rc2" -eq 0 ] && [ "$after" = "$app_dir/releases/$NEW_SHA" ]
}

test_rollback_manual_hacia_release_anterior() {
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  ln -sfn "$app_dir/releases/$NEW_SHA" "$app_dir/current.tmp"
  mv -T "$app_dir/current.tmp" "$app_dir/current"
  chown -h "$SVC_USER:$SVC_USER" "$app_dir/current"
  local rc=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'
    MVP_APP_DIR="$MVP_APP_DIR" rollback_version "'"$OLD_SHA"'"
  ' >/tmp/tah16.out 2>&1 || rc=$?
  local after; after="$(readlink "$app_dir/current")"
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 0 ] && [ "$after" = "$app_dir/releases/$OLD_SHA" ]
}

test_sin_cambios_sobre_releases_historicos() {
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  local old_sum new_sum_before
  old_sum="$(find "$app_dir/releases/$OLD_SHA" -type f -exec sha256sum {} \; | sort)"
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah17.out 2>&1 || true
  local old_sum_after
  old_sum_after="$(find "$app_dir/releases/$OLD_SHA" -type f -exec sha256sum {} \; | sort)"
  remove_units; rm -rf "$app_dir"
  [ "$old_sum" = "$old_sum_after" ]
}

test_sin_operaciones_sobre_tvc_etl() {
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah18.out 2>&1 || true
  local rc=0
  grep -qi "tvc\|vinto-web\|vinto-etl" "$MOCK_SYSTEMCTL_LOG" 2>/dev/null && rc=1
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 0 ]
}

test_idempotencia_sin_unidades_instaladas() {
  # Primera activación real (antes de "systemd-install"): no hay units que reiniciar; 'current'
  # debe conmutar igual, y una segunda llamada debe seguir siendo idempotente.
  local app_dir; app_dir="$(make_sandbox)"
  remove_units
  reset_systemctl_mock 0
  local rc1=0 rc2=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah19a.out 2>&1 || rc1=$?
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah19b.out 2>&1 || rc2=$?
  local after; after="$(readlink "$app_dir/current")"
  rm -rf "$app_dir"
  [ "$rc1" -eq 0 ] && [ "$rc2" -eq 0 ] && [ "$after" = "$app_dir/releases/$NEW_SHA" ] \
    && grep -q "nada que reiniciar" /tmp/tah19a.out
}

test_regresion_activacion_simple_sigue_funcionando() {
  # Caso "feliz" de siempre, de punta a punta: venv+frontend presentes, unidades legítimas,
  # esquema migrado, reinicio y healthcheck OK -- debe comportarse exactamente igual que antes de
  # este endurecimiento.
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  local rc=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah20.out 2>&1 || rc=$?
  local after; after="$(readlink "$app_dir/current")"
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 0 ] && [ "$after" = "$app_dir/releases/$NEW_SHA" ] && grep -q "Healthcheck OK tras activar" /tmp/tah20.out
}

# ==================================================================================================
# 21-25: CLOUD-DEP-02B.2-G.12-B4-P3-H1-R1 -- señales, fallos de conmutación y traps reentrantes
# ==================================================================================================

test_int_antes_de_conmutar_current_intacto() {
  # Antes de la conmutación no hay ningún trap instalado todavía (a propósito: nada que proteger
  # aún). Una señal aquí debe recibir el comportamiento por defecto de bash -- terminar de
  # inmediato -- y 'current' debe quedar exactamente como estaba, sin ningún "current.tmp" suelto.
  # Autoseñal INMEDIATA al propio proceso (nunca "kill" externo a través de varias capas de
  # sudo/subshell/backgrounding, cuya sincronización de temporización no es fiable para probar
  # "antes de que exista ningún trap"): sin "trap" registrado todavía, el comportamiento por
  # defecto de bash debe terminar el proceso en el acto, ANTES de llegar siquiera a "phase_activate".
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  local before; before="$(readlink "$app_dir/current")"
  local rc=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'
    kill -INT $$
    echo NO-DEBERIA-LLEGAR-AQUI
    phase_activate "'"$NEW_SHA"'"
  ' >/tmp/tah21.out 2>&1 || rc=$?
  local after; after="$(readlink "$app_dir/current")"
  local stray=0
  [ -e "$app_dir/current.tmp" ] && stray=1
  remove_units; rm -rf "$app_dir"
  [ "$before" = "$after" ] && [ "$stray" -eq 0 ] && ! grep -q "NO-DEBERIA-LLEGAR-AQUI" /tmp/tah21.out
}

test_fallo_conmutacion_symlink_primario() {
  # $app_dir sin permiso de escritura para testsvc justo antes de conmutar: "ln -sfn ... .tmp"
  # debe fallar con permiso denegado -- la fase debe reportarlo explícitamente, nunca afirmar
  # "'current' -> ..." como si hubiera tenido éxito, y 'current' debe seguir intacto.
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  chmod 550 "$app_dir"
  local before; before="$(readlink "$app_dir/current")"
  local rc=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah22.out 2>&1 || rc=$?
  chmod 750 "$app_dir"
  local after; after="$(readlink "$app_dir/current")"
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 1 ] && [ "$before" = "$after" ] && grep -q "no se pudo preparar la conmutación de 'current'" /tmp/tah22.out \
    && ! grep -q "'current' ->" /tmp/tah22.out
}

test_fallo_conmutacion_durante_rollback_automatico() {
  # El healthcheck inicial falla (dispara el rollback automático), y justo en ESE momento (dentro
  # del mock de "curl", como efecto colateral de la primera respuesta fallida) se retira el
  # permiso de escritura de $app_dir -- de modo que la conmutación de LA PROPIA reversión falle.
  # Debe reportarse como "no se puede garantizar un estado consistente", nunca como un
  # "set -e" silencioso, y con código de salida distinto de 0.
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  local rc=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'
    curl() {
      sudo chmod 550 "'"$app_dir"'" 2>/dev/null || true
      return 7
    }
    phase_activate "'"$NEW_SHA"'"
  ' >/tmp/tah23.out 2>&1 || rc=$?
  chmod 750 "$app_dir" 2>/dev/null || true
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 1 ] && grep -qi "no se puede garantizar un estado consistente" /tmp/tah23.out
}

test_sin_trap_reentrante_con_senales_dobles() {
  # Dos señales (TERM seguido de INT) enviadas en rápida sucesión tras la conmutación: el
  # manejador se autodesarma como primera acción ("trap '' INT TERM"), así que la SEGUNDA señal no
  # debe producir un segundo AVISO ni una segunda ejecución del manejador -- a lo sumo una.
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah24.out 2>&1 &
  local pid=$!
  local waited=0
  while [ "$waited" -lt 50 ]; do
    [ "$(readlink -f "$app_dir/current" 2>/dev/null)" = "$app_dir/releases/$NEW_SHA" ] && break
    sleep 0.1; waited=$((waited + 1))
  done
  kill -TERM "$pid" 2>/dev/null || true
  kill -INT "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null
  # CLOUD-DEP-02B.2-G.12-B4-P3-H2: mismo drenaje de mejor esfuerzo que test_senal_interrupcion_
  # controlable (ver su comentario) -- "wait $pid" aquí tampoco espera al proceso real huérfano.
  wait_for_lock_released 100 || true
  remove_units; rm -rf "$app_dir"
  local avisos; avisos="$(grep -c "señal de interrupción recibida" /tmp/tah24.out || true)"
  [ "${avisos:-0}" -le 1 ]
}

test_senal_durante_restart_bloqueante_se_difiere_documentado() {
  # Límite CONFIRMADO (no asumido): una señal que llega MIENTRAS "systemctl restart" (bloqueante,
  # en primer plano) todavía está en marcha NO interrumpe esa llamada -- bash la entrega solo al
  # volver al bucle de comandos. Se simula un "systemctl" lento (duerme antes de responder) y se
  # envía la señal a mitad de esa espera: el AVISO del manejador NO debe aparecer antes de que el
  # "systemctl" simulado termine por su cuenta -- documenta la limitación como hecho verificado,
  # no como suposición.
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  cat > /usr/local/bin/systemctl <<'SLOW_SYSTEMCTL_MOCK'
#!/bin/sh
echo "$@" >> /tmp/.mock-systemctl-calls.log
if [ "$1" = "restart" ]; then
  sleep 3
  exit "$(cat /tmp/.mock-systemctl-exit 2>/dev/null || echo 0)"
fi
exit 0
SLOW_SYSTEMCTL_MOCK
  chmod 755 /usr/local/bin/systemctl
  reset_systemctl_mock 0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah25.out 2>&1 &
  local pid=$!
  local waited=0
  while [ "$waited" -lt 50 ]; do
    [ "$(readlink -f "$app_dir/current" 2>/dev/null)" = "$app_dir/releases/$NEW_SHA" ] && break
    sleep 0.1; waited=$((waited + 1))
  done
  sleep 0.3
  kill -TERM "$pid" 2>/dev/null || true
  sleep 1
  local avisos_tempranos; avisos_tempranos="$(grep -c "señal de interrupción recibida" /tmp/tah25.out || true)"
  wait "$pid" 2>/dev/null
  # CLOUD-DEP-02B.2-G.12-B4-P3-H2: mismo drenaje de mejor esfuerzo que las otras pruebas de señal
  # (ver test_senal_interrupcion_controlable) -- aquí el huérfano real, al no haber recibido la
  # señal (solo la recibió el envoltorio ya terminado), completa su "systemctl restart" simulado
  # (3s) y el resto de la fase con normalidad; se le da margen de sobra antes de limpiar.
  wait_for_lock_released 150 || true
  remove_units; rm -rf "$app_dir"
  # restaurar el mock rápido (con la comprobación de herencia de descriptor de H2) para el resto
  # de la suite -- debe quedar IDÉNTICO al de setup_users_once.
  cat > /usr/local/bin/systemctl <<'SYSTEMCTL_MOCK'
#!/bin/sh
echo "$@" >> /tmp/.mock-systemctl-calls.log
if [ "$1" = "restart" ]; then
  sleep 30 &
  child=$!
  sleep 0.2
  if ls -la "/proc/$child/fd/" 2>/dev/null | grep -qi 'activate\.lock'; then
    echo "INHERITED" >> /tmp/.mock-systemctl-fdcheck.log
  else
    echo "NOT-INHERITED" >> /tmp/.mock-systemctl-fdcheck.log
  fi
  kill "$child" 2>/dev/null
  wait "$child" 2>/dev/null
  exit "$(cat /tmp/.mock-systemctl-exit 2>/dev/null || echo 0)"
fi
exit 0
SYSTEMCTL_MOCK
  chmod 755 /usr/local/bin/systemctl
  [ "${avisos_tempranos:-0}" -eq 0 ]
}

# ==================================================================================================
# 26-45: CLOUD-DEP-02B.2-G.12-B4-P3-H2 -- candado exclusivo (flock) compartido entre
# "deploy.sh activate" y "rollback.sh version" contra operaciones concurrentes sobre 'current'.
# ==================================================================================================

test_activacion_individual_libera_candado_tras_exito() {
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  local rc=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah26.out 2>&1 || rc=$?
  local after; after="$(readlink "$app_dir/current")"
  local lock_free=0; wait_for_lock_released 10 && lock_free=1
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 0 ] && [ "$after" = "$app_dir/releases/$NEW_SHA" ] && [ "$lock_free" -eq 1 ] && [ -e "$LOCK_FILE" ]
}

test_reversion_individual_libera_candado_tras_exito() {
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  local rc=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'rollback_version "'"$NEW_SHA"'"' >/tmp/tah27.out 2>&1 || rc=$?
  local after; after="$(readlink "$app_dir/current")"
  local lock_free=0; wait_for_lock_released 10 && lock_free=1
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 0 ] && [ "$after" = "$app_dir/releases/$NEW_SHA" ] && [ "$lock_free" -eq 1 ] && [ -e "$LOCK_FILE" ]
}

test_dos_activaciones_simultaneas_al_mismo_commit_solo_una_gana() {
  # El "migrate.py --check" de OLD_SHA (al que apunta 'current' antes de conmutar, comprobado por
  # assert_schema_migrated ANTES de tocar 'current') duerme 3s -- ventana real, no simulada con
  # texto, entre "acquire_activate_lock" (ya adquirido) y la conmutación. Durante esa ventana, una
  # SEGUNDA activación concurrente al MISMO commit debe fallar por candado ocupado, sin tocar
  # 'current' ni dejar 'current.tmp' huérfano; la primera debe completar con éxito normalmente.
  local app_dir; app_dir="$(make_sandbox 0 3)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah28a.out 2>&1 &
  local pid_a=$!
  local held=0; wait_for_lock_held 50 && held=1
  local mid_current mid_tmp_exists=0
  mid_current="$(readlink "$app_dir/current" 2>/dev/null)"
  [ -e "$app_dir/current.tmp" ] && mid_tmp_exists=1
  local rc_b=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah28b.out 2>&1 || rc_b=$?
  local rc_a=0
  wait "$pid_a" || rc_a=$?
  local after; after="$(readlink "$app_dir/current")"
  local final_tmp_exists=0; [ -e "$app_dir/current.tmp" ] && final_tmp_exists=1
  remove_units; rm -rf "$app_dir"
  [ "$held" -eq 1 ] && [ "$mid_current" = "$app_dir/releases/$OLD_SHA" ] && [ "$mid_tmp_exists" -eq 0 ] \
    && [ "$rc_b" -eq 1 ] && grep -q "otra activación o reversión ya está en curso" /tmp/tah28b.out \
    && ! grep -q "'current' ->" /tmp/tah28b.out \
    && [ "$rc_a" -eq 0 ] && [ "$after" = "$app_dir/releases/$NEW_SHA" ] && [ "$final_tmp_exists" -eq 0 ]
}

test_dos_reversiones_simultaneas_solo_una_gana() {
  # Mismo mecanismo que la prueba anterior, pero con rollback_version en ambos lados: el
  # "migrate.py" no aplica aquí (rollback_version nunca lo llama), así que la ventana se abre con
  # un "curl" (healthcheck) lento -- tras la conmutación, pero sigue demostrando que el candado
  # impide una SEGUNDA reversión concurrente mientras la primera todavía lo sostiene.
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'
    curl() { sleep 2; return 0; }
    rollback_version "'"$NEW_SHA"'"
  ' >/tmp/tah29a.out 2>&1 &
  local pid_a=$!
  # Se espera a que 'current' YA haya conmutado (no solo a que el candado esté tomado, que
  # podría ser aún durante la breve prevalidación de rollback_version) antes de lanzar B --
  # mismo ajuste aplicado a las pruebas 30/31 tras confirmar la condición de carrera real.
  local waited=0
  while [ "$waited" -lt 50 ]; do
    [ "$(readlink -f "$app_dir/current" 2>/dev/null)" = "$app_dir/releases/$NEW_SHA" ] && break
    sleep 0.1; waited=$((waited + 1))
  done
  local held=0; ( exec 9>"$LOCK_FILE"; flock -n 9 ) 2>/dev/null || held=1
  local mid_current; mid_current="$(readlink "$app_dir/current" 2>/dev/null)"
  local rc_b=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'rollback_version "'"$OLD_SHA"'"' >/tmp/tah29b.out 2>&1 || rc_b=$?
  local rc_a=0
  wait "$pid_a" || rc_a=$?
  local after; after="$(readlink "$app_dir/current")"
  remove_units; rm -rf "$app_dir"
  [ "$held" -eq 1 ] && [ "$mid_current" = "$app_dir/releases/$NEW_SHA" ] \
    && [ "$rc_b" -eq 1 ] && grep -q "otra activación o reversión ya está en curso" /tmp/tah29b.out \
    && [ "$rc_a" -eq 0 ] && [ "$after" = "$app_dir/releases/$NEW_SHA" ]
}

test_rollback_concurrente_con_activacion_en_curso_rechazado_durante_healthcheck() {
  # La activación (A) mantiene el candado durante TODO el healthcheck posterior a conmutar (no
  # solo durante la propia conmutación) -- una reversión (B) que intenta mientras A sigue en el
  # healthcheck debe ser rechazada igual, demostrando que la protección cubre toda la fase, no
  # solo el instante del "mv -T".
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'
    curl() { sleep 2; return 0; }
    phase_activate "'"$NEW_SHA"'"
  ' >/tmp/tah30a.out 2>&1 &
  local pid_a=$!
  # CLOUD-DEP-02B.2-G.12-B4-P3-H2: "wait_for_lock_held" por sí solo solo confirma que A YA
  # adquirió el candado -- podría ser todavía durante la prevalidación (assert_schema_migrated,
  # assert_unit_is_ours...), ANTES de conmutar 'current'. Para probar de verdad "el candado sigue
  # protegiendo DURANTE el healthcheck, después de conmutar" (el objetivo real de esta prueba),
  # se espera a que 'current' YA haya cambiado -- en ese punto el candado sigue sostenido con
  # certeza, porque A todavía no ha llegado al healthcheck lento que lo retiene.
  local waited=0
  while [ "$waited" -lt 50 ]; do
    [ "$(readlink -f "$app_dir/current" 2>/dev/null)" = "$app_dir/releases/$NEW_SHA" ] && break
    sleep 0.1; waited=$((waited + 1))
  done
  local held=0; ( exec 9>"$LOCK_FILE"; flock -n 9 ) 2>/dev/null || held=1
  local mid_current; mid_current="$(readlink "$app_dir/current" 2>/dev/null)"
  local rc_b=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'rollback_version "'"$OLD_SHA"'"' >/tmp/tah30b.out 2>&1 || rc_b=$?
  local rc_a=0
  wait "$pid_a" || rc_a=$?
  local after; after="$(readlink "$app_dir/current")"
  remove_units; rm -rf "$app_dir"
  [ "$held" -eq 1 ] && [ "$mid_current" = "$app_dir/releases/$NEW_SHA" ] \
    && [ "$rc_b" -eq 1 ] && grep -q "otra activación o reversión ya está en curso" /tmp/tah30b.out \
    && [ "$rc_a" -eq 0 ] && [ "$after" = "$app_dir/releases/$NEW_SHA" ]
}

test_activacion_concurrente_con_reversion_en_curso_rechazada_durante_healthcheck() {
  # Simétrico de la prueba anterior: la reversión (A) sostiene el candado durante su healthcheck;
  # una activación (B) concurrente al MISMO u otro commit debe ser rechazada igual.
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'
    curl() { sleep 2; return 0; }
    rollback_version "'"$NEW_SHA"'"
  ' >/tmp/tah31a.out 2>&1 &
  local pid_a=$!
  # Mismo ajuste que en la prueba simétrica anterior: se espera a que 'current' YA haya
  # conmutado (no solo a que el candado esté tomado, que podría ser aún durante la
  # prevalidación) antes de confirmar el candado y lanzar la operación concurrente B.
  local waited=0
  while [ "$waited" -lt 50 ]; do
    [ "$(readlink -f "$app_dir/current" 2>/dev/null)" = "$app_dir/releases/$NEW_SHA" ] && break
    sleep 0.1; waited=$((waited + 1))
  done
  local held=0; ( exec 9>"$LOCK_FILE"; flock -n 9 ) 2>/dev/null || held=1
  local mid_current; mid_current="$(readlink "$app_dir/current" 2>/dev/null)"
  local rc_b=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$OLD_SHA"'"' >/tmp/tah31b.out 2>&1 || rc_b=$?
  local rc_a=0
  wait "$pid_a" || rc_a=$?
  local after; after="$(readlink "$app_dir/current")"
  remove_units; rm -rf "$app_dir"
  [ "$held" -eq 1 ] && [ "$mid_current" = "$app_dir/releases/$NEW_SHA" ] \
    && [ "$rc_b" -eq 1 ] && grep -q "otra activación o reversión ya está en curso" /tmp/tah31b.out \
    && [ "$rc_a" -eq 0 ] && [ "$after" = "$app_dir/releases/$NEW_SHA" ]
}

test_candado_se_libera_tras_fallo_de_prevalidacion() {
  # Una activación rechazada por identidad (unidad ajena) falla ANTES de tocar 'current' -- el
  # candado, ya adquirido, debe quedar igualmente libre de inmediato al terminar el proceso.
  local app_dir; app_dir="$(make_sandbox)"
  write_foreign_units
  local rc=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah32.out 2>&1 || rc=$?
  local lock_free=0; wait_for_lock_released 10 && lock_free=1
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 1 ] && [ "$lock_free" -eq 1 ]
}

test_candado_se_libera_tras_senal_term_capturada() {
  # CLOUD-DEP-02B.2-G.12-B4-P3-H2: "kill -TERM \$pid" sobre el resultado de "run_as_op ... &"
  # (como en test_senal_interrupcion_controlable) solo alcanza al ENVOLTORIO de esa función en
  # segundo plano de ESTE shell -- nunca al "sudo"/"bash -c" real, más abajo en el árbol de
  # procesos, que seguiría corriendo huérfano. Para que ESTA prueba verifique de verdad que la
  # señal llega al proceso que sostiene el candado (y que su manejador la captura), el propio
  # proceso escribe su PID real ($$, dentro del "bash -c" que sourcea lib_common.sh) en un
  # archivo marcador ANTES de nada más -- la señal se envía a ESE pid, confirmado leyéndolo.
  rm -f /tmp/tah33.realpid
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'
    echo $$ > /tmp/tah33.realpid
    phase_activate "'"$NEW_SHA"'"
  ' >/tmp/tah33.out 2>&1 &
  local wrapper_pid=$!
  local waited=0
  while [ "$waited" -lt 50 ]; do
    [ "$(readlink -f "$app_dir/current" 2>/dev/null)" = "$app_dir/releases/$NEW_SHA" ] && break
    sleep 0.1; waited=$((waited + 1))
  done
  local real_pid; real_pid="$(cat /tmp/tah33.realpid 2>/dev/null || true)"
  [ -n "$real_pid" ] && kill -TERM "$real_pid" 2>/dev/null || true
  wait "$wrapper_pid" 2>/dev/null
  local lock_free=0; wait_for_lock_released 50 && lock_free=1
  remove_units; rm -rf "$app_dir" /tmp/tah33.realpid
  [ -n "$real_pid" ] && [ "$lock_free" -eq 1 ] && grep -q "señal de interrupción recibida" /tmp/tah33.out
}

test_candado_se_libera_tras_sigkill_sin_oportunidad_de_limpieza() {
  # SIGKILL no puede atraparse: ninguna limpieza de este script corre. El candado debe liberarse
  # de todos modos porque lo libera el KERNEL al cerrarse el descriptor cuando el proceso termina
  # -- confirmado empíricamente en el diseño de esta ronda, nunca asumido. Mismo mecanismo de PID
  # real que la prueba anterior (ver su comentario): sin él, SIGKILL solo alcanzaría el envoltorio.
  rm -f /tmp/tah34.realpid
  local app_dir; app_dir="$(make_sandbox 0 3)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'
    echo $$ > /tmp/tah34.realpid
    phase_activate "'"$NEW_SHA"'"
  ' >/tmp/tah34.out 2>&1 &
  local wrapper_pid=$!
  local waited=0
  while [ "$waited" -lt 50 ] && [ ! -s /tmp/tah34.realpid ]; do sleep 0.1; waited=$((waited + 1)); done
  local real_pid; real_pid="$(cat /tmp/tah34.realpid 2>/dev/null || true)"
  local held=0; wait_for_lock_held 50 && held=1
  [ -n "$real_pid" ] && kill -KILL "$real_pid" 2>/dev/null || true
  wait "$wrapper_pid" 2>/dev/null
  local lock_free=0; wait_for_lock_released 50 && lock_free=1
  remove_units; rm -rf "$app_dir" /tmp/tah34.realpid
  [ -n "$real_pid" ] && [ "$held" -eq 1 ] && [ "$lock_free" -eq 1 ] \
    && ! grep -q "señal de interrupción recibida" /tmp/tah34.out
}

test_candado_sin_residuo_tras_rollback_automatico_completo() {
  # El healthcheck inicial falla (dispara el rollback automático dentro de la misma fase, con el
  # MISMO candado sostenido todo el tiempo); al terminar, el candado debe quedar libre igual que
  # en cualquier otro camino de salida.
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  local rc=0
  MOCK_HEALTHCHECK_OK=0 run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah35.out 2>&1 || rc=$?
  local after; after="$(readlink "$app_dir/current")"
  local lock_free=0; wait_for_lock_released 10 && lock_free=1
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 1 ] && [ "$after" = "$app_dir/releases/$OLD_SHA" ] && [ "$lock_free" -eq 1 ]
}

test_archivo_de_candado_persiste_en_disco_tras_exito_y_tras_fallo() {
  rm -f "$LOCK_FILE"
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah36a.out 2>&1 || true
  local exists_after_success=0; [ -e "$LOCK_FILE" ] && exists_after_success=1
  remove_units
  local app_dir2; app_dir2="$(make_sandbox)"
  write_foreign_units
  run_as_op "$app_dir2" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah36b.out 2>&1 || true
  local exists_after_failure=0; [ -e "$LOCK_FILE" ] && exists_after_failure=1
  remove_units; rm -rf "$app_dir" "$app_dir2"
  [ "$exists_after_success" -eq 1 ] && [ "$exists_after_failure" -eq 1 ]
}

test_acquire_activate_lock_rechaza_symlink_en_lugar_del_candado() {
  rm -f "$LOCK_FILE"
  ln -s /etc/hostname "$LOCK_FILE"
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  local before; before="$(readlink "$app_dir/current")"
  local rc=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah37.out 2>&1 || rc=$?
  local after; after="$(readlink "$app_dir/current")"
  local still_symlink=0; [ -L "$LOCK_FILE" ] && still_symlink=1
  rm -f "$LOCK_FILE"
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 1 ] && [ "$before" = "$after" ] && grep -q "es un enlace simbólico" /tmp/tah37.out \
    && [ "$still_symlink" -eq 1 ]
}

test_archivo_de_candado_queda_con_permisos_600() {
  rm -f "$LOCK_FILE"
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah38.out 2>&1 || true
  local perms; perms="$(stat -c '%a' "$LOCK_FILE" 2>/dev/null || true)"
  remove_units; rm -rf "$app_dir"
  [ "$perms" = "600" ]
}

test_adquisicion_del_candado_no_usa_sudo() {
  # El único "sudo systemctl ..." que debe aparecer en el log del mock es el de los reinicios de
  # servicio -- acquire_activate_lock/run_with_lock_fd_closed nunca invocan "sudo" por sí mismos
  # (consistente con que $SCRIPT_DIR ya es del operador, sin necesitar privilegio adicional).
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  local rc=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah39.out 2>&1 || rc=$?
  local restart_calls; restart_calls="$(grep -c '^restart ' "$MOCK_SYSTEMCTL_LOG" 2>/dev/null || true)"
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 0 ] && [ "${restart_calls:-0}" -eq 1 ]
}

test_rollback_automatico_dentro_de_activate_no_se_autobloquea_con_su_propio_candado() {
  # phase_activate adquiere el candado UNA sola vez, al principio -- el rollback automático
  # interno (tras un healthcheck fallido) nunca vuelve a pedirlo. "timeout" demuestra que no hay
  # autobloqueo (deadlock): si lo hubiera, esta prueba colgaría hasta agotar el plazo (código 124).
  # Se inlinea el mismo comando que run_as_op ejecuta (en vez de llamar a la función) porque
  # "timeout" necesita un ejecutable externo real por delante, no una función de este shell.
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  local rc=0
  timeout 15 sudo -u "$OP_USER" --preserve-env=SCRIPT_DIR,MVP_APP_DIR,MVP_SERVICE_USER,MOCK_SCHEMA_EXIT,MOCK_SYSTEMCTL_EXIT,MOCK_HEALTHCHECK_OK,MOCK_SEND_SIGNAL \
    env MVP_APP_DIR="$app_dir" MVP_SERVICE_USER="$SVC_USER" CONFIRM=yes MOCK_HEALTHCHECK_OK=0 \
    bash -c "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah40.out 2>&1 || rc=$?
  remove_units; rm -rf "$app_dir"
  [ "$rc" -ne 124 ]
}

test_hijo_de_systemctl_no_hereda_el_descriptor_del_candado() {
  # Verificación empírica (vía /proc, nunca asumida) de que un hijo de larga duración generado
  # DENTRO del "systemctl restart" simulado -- el mismo riesgo que motivó run_with_lock_fd_closed
  # -- no hereda el descriptor del candado. Ver el mock de "systemctl" (setup_users_once).
  rm -f /tmp/.mock-systemctl-fdcheck.log
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  local rc=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah41.out 2>&1 || rc=$?
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 0 ] && [ -s /tmp/.mock-systemctl-fdcheck.log ] \
    && ! grep -qx "INHERITED" /tmp/.mock-systemctl-fdcheck.log \
    && grep -q "NOT-INHERITED" /tmp/.mock-systemctl-fdcheck.log
}

test_prevalidacion_fallida_libera_candado_para_el_siguiente_intento() {
  local app_dir; app_dir="$(make_sandbox)"
  write_foreign_units
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah42a.out 2>&1 || true
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  local rc=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah42b.out 2>&1 || rc=$?
  local after; after="$(readlink "$app_dir/current")"
  remove_units; rm -rf "$app_dir"
  [ "$rc" -eq 0 ] && [ "$after" = "$app_dir/releases/$NEW_SHA" ]
}

test_candado_se_recicla_correctamente_entre_ejecuciones_independientes_consecutivas() {
  local app_dir_1; app_dir_1="$(make_sandbox)"
  local app_dir_2; app_dir_2="$(make_sandbox)"
  write_legit_units "$app_dir_1"
  reset_systemctl_mock 0
  local rc1=0 rc2=0
  run_as_op "$app_dir_1" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah43a.out 2>&1 || rc1=$?
  remove_units
  write_legit_units "$app_dir_2"
  run_as_op "$app_dir_2" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah43b.out 2>&1 || rc2=$?
  local after1 after2
  after1="$(readlink "$app_dir_1/current")"; after2="$(readlink "$app_dir_2/current")"
  remove_units; rm -rf "$app_dir_1" "$app_dir_2"
  [ "$rc1" -eq 0 ] && [ "$rc2" -eq 0 ] \
    && [ "$after1" = "$app_dir_1/releases/$NEW_SHA" ] && [ "$after2" = "$app_dir_2/releases/$NEW_SHA" ]
}

test_archivo_de_candado_vive_en_script_dir_no_en_app_dir() {
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'phase_activate "'"$NEW_SHA"'"' >/tmp/tah44.out 2>&1 || true
  local in_script_dir=0 in_app_dir=0
  [ -e "$SCRIPT_DIR/.activate.lock" ] && in_script_dir=1
  [ -e "$app_dir/.activate.lock" ] && in_app_dir=1
  remove_units; rm -rf "$app_dir"
  [ "$in_script_dir" -eq 1 ] && [ "$in_app_dir" -eq 0 ]
}

test_rollback_systemd_no_toca_el_candado() {
  # rollback_systemd es un subcomando distinto (detiene/elimina las unidades), ajeno por completo
  # a 'current' -- nunca debe adquirir este candado. Se confirma que el candado sigue disponible
  # de inmediato (nunca quedó tomado por error) y que la operación en sí funciona igual que antes.
  local app_dir; app_dir="$(make_sandbox)"
  write_legit_units "$app_dir"
  reset_systemctl_mock 0
  local rc=0
  run_as_op "$app_dir" "$ACTIVATE_PRELUDE"'rollback_systemd' >/tmp/tah45.out 2>&1 || rc=$?
  local lock_free=0; wait_for_lock_released 5 && lock_free=1
  local units_gone=0
  [ ! -f "$UNIT_B" ] && [ ! -f "$UNIT_F" ] && units_gone=1
  rm -rf "$app_dir"
  [ "$rc" -eq 0 ] && [ "$lock_free" -eq 1 ] && [ "$units_gone" -eq 1 ]
}

t() { local name="$1" fn="$2"; local rc=0; "$fn" || rc=$?; report "$name" "$rc"; }

t "1  assert_unit_is_ours: unidad legítima root:root 600 -> aceptada"         test_unidad_legitima_600_root
t "2  assert_unit_is_ours: unidad ajena -> rechazada"                         test_unidad_ajena_rechazada
t "3  assert_unit_is_ours: ilegible incluso con privilegio -> fallo distinto" test_unidad_ilegible_incluso_con_privilegio
t "4  assert_unit_is_ours: ausencia de unidad -> PASS"                        test_unidad_ausente
t "5  prevalidación fallida (unidad ajena) -> current no cambia"             test_prevalidacion_fallida_current_no_cambia
t "6  esquema no migrado -> current no cambia"                               test_esquema_no_migrado_current_no_cambia
t "7  identidad inválida del operador -> current no cambia"                  test_identidad_invalida_actor_current_no_cambia
t "8  activación exitosa: conmuta y reinicia"                                 test_activacion_exitosa_conmuta_y_reinicia
t "9  fallo de reinicio backend -> rollback automático"                      test_fallo_reinicio_backend_dispara_rollback_automatico
t "10 fallo de reinicio frontend -> aviso explícito, no oculto"              test_fallo_reinicio_frontend_tratado_igual
t "11 fallo de healthcheck -> rollback automático"                           test_fallo_healthcheck_dispara_rollback
t "12 rollback automático exitoso"                                           test_rollback_automatico_exitoso
t "13 rollback automático fallido -> error explícito"                        test_rollback_automatico_fallido_error_explicito
t "14 señal de interrupción tras conmutar -> aviso + current ya conmutado"    test_senal_interrupcion_controlable
t "15 segundo intento tras recuperación consistente -> idempotente"          test_segundo_intento_tras_recuperacion_consistente
t "16 rollback manual hacia release anterior"                                 test_rollback_manual_hacia_release_anterior
t "17 sin cambios sobre releases históricos"                                  test_sin_cambios_sobre_releases_historicos
t "18 ninguna operación nombra TVC/ETL"                                       test_sin_operaciones_sobre_tvc_etl
t "19 idempotencia sin unidades instaladas (primera activación)"             test_idempotencia_sin_unidades_instaladas
t "20 regresión: activación simple sigue funcionando"                        test_regresion_activacion_simple_sigue_funcionando
t "21 señal INT antes de conmutar -> current intacto, sin current.tmp"       test_int_antes_de_conmutar_current_intacto
t "22 fallo de conmutación primaria -> error explícito, current intacto"     test_fallo_conmutacion_symlink_primario
t "23 fallo de conmutación durante el rollback automático -> error explícito" test_fallo_conmutacion_durante_rollback_automatico
t "24 dos señales rápidas -> sin trap reentrante, a lo sumo un AVISO"        test_sin_trap_reentrante_con_senales_dobles
t "25 señal durante restart bloqueante -> diferida, documentada y verificada" test_senal_durante_restart_bloqueante_se_difiere_documentado
t "26 activación individual -> libera el candado tras el éxito"              test_activacion_individual_libera_candado_tras_exito
t "27 reversión individual -> libera el candado tras el éxito"               test_reversion_individual_libera_candado_tras_exito
t "28 dos activaciones simultáneas al mismo commit -> solo una gana"         test_dos_activaciones_simultaneas_al_mismo_commit_solo_una_gana
t "29 dos reversiones simultáneas -> solo una gana"                          test_dos_reversiones_simultaneas_solo_una_gana
t "30 rollback concurrente con activación en curso -> rechazado"             test_rollback_concurrente_con_activacion_en_curso_rechazado_durante_healthcheck
t "31 activación concurrente con reversión en curso -> rechazada"            test_activacion_concurrente_con_reversion_en_curso_rechazada_durante_healthcheck
t "32 fallo de prevalidación -> candado liberado igual"                      test_candado_se_libera_tras_fallo_de_prevalidacion
t "33 señal TERM capturada -> candado liberado"                              test_candado_se_libera_tras_senal_term_capturada
t "34 SIGKILL sin limpieza posible -> candado liberado por el kernel"        test_candado_se_libera_tras_sigkill_sin_oportunidad_de_limpieza
t "35 rollback automático completo -> sin residuo de candado"                test_candado_sin_residuo_tras_rollback_automatico_completo
t "36 archivo de candado persiste en disco (éxito y fallo)"                   test_archivo_de_candado_persiste_en_disco_tras_exito_y_tras_fallo
t "37 candado rechaza enlace simbólico en su lugar"                          test_acquire_activate_lock_rechaza_symlink_en_lugar_del_candado
t "38 archivo de candado queda con permisos 600"                             test_archivo_de_candado_queda_con_permisos_600
t "39 adquirir el candado no usa sudo"                                        test_adquisicion_del_candado_no_usa_sudo
t "40 rollback automático interno no se autobloquea (sin deadlock)"         test_rollback_automatico_dentro_de_activate_no_se_autobloquea_con_su_propio_candado
t "41 hijo de systemctl no hereda el descriptor del candado (vía /proc)"     test_hijo_de_systemctl_no_hereda_el_descriptor_del_candado
t "42 prevalidación fallida libera el candado para el siguiente intento"    test_prevalidacion_fallida_libera_candado_para_el_siguiente_intento
t "43 candado se recicla entre ejecuciones independientes consecutivas"      test_candado_se_recicla_correctamente_entre_ejecuciones_independientes_consecutivas
t "44 archivo de candado vive en SCRIPT_DIR, nunca en APP_DIR"               test_archivo_de_candado_vive_en_script_dir_no_en_app_dir
t "45 rollback_systemd no toca el candado compartido"                       test_rollback_systemd_no_toca_el_candado

echo
echo "Resumen: $PASS PASS, $FAILED FAIL."
[ "$FAILED" -eq 0 ]
