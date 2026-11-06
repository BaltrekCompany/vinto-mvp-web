# VINTO E1-09 — Instalación controlada del script Ops de respaldo (PR #136)

**Estado:** preparación documental, **NO EJECUTADA**. Fecha 2026-11-06.  
**Integrado GitHub:** PR #136, `main@c64893e86a983a86d57f9a7406d0d736417f17e3`. QA [42240240275](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/42240240275) y [42240251528](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/42240251528) PASS.  
**Cambio:** solo `deploy/mvp/scripts/backup.sh` respecto de código Ops; `lib_common.sh` intacto. Git blob SHA-1 *nuevo* `5ae19d8a8db75bb61f8e67bd1159acfab684ddc3`.  
**Antes:** Ops `backup.sh` SHA-256 `12151e680a2ef8dd400393794041c18adf4425bfd4ebfea38d5882e7b345738a`; `lib_common.sh` SHA-256 `31696d213baaf5436cc09766327ed6e1f53605802ffce970f89bb2813318c31b` (P1-A).  
**Límites:** el usuario autorizó integrar #136 y **preparar** instalación controlada, así como permitir uso *interno programático* de credenciales durante un posterior backup, sin exponerlas. **No se ejecutó instalación ni respaldo** desde ChatGPT.

## A. Política de secretos y concurrencia

- Instalación de script: **no requiere acceso** a `docker/.env`. No abrirlo, mostrar variables, habilitar `set -x`, imprimir credenciales ni ejecutar Docker / PostgreSQL.
- Ejecución futura de `backup.sh create-and-verify`: el usuario permite exclusivamente que `backup.sh`, dentro de su contrato de permisos del archivo 600, consuma credenciales de `docker/.env` internamente para autenticación. Esto NO concede permiso para visualizarlas, copiarlas, incluirlas en argumentos/logs ni enviarlas al chat/GitHub.
- Nuevo `flock` protege `create`, `verify`, `create-and-verify` y `prune-apply` entre invocaciones **del script corregido**, usando un archivo privado en el mismo directorio de backups. No protege scripts antiguos, accesos manuales ni otros respaldos que no usen ese lock. Confirmar operativamente que no hay tales procesos y no lanzar tareas concurrentes en la ventana.
- No cambiar `lib_common.sh`, `deploy.sh`, la release activa `86e4ec4`, servicios, flags, migración 0013, datos simulados, permisos ni recursos TVC.

## B. Origen verificado y staging (preparación sin sustitución)

Codex Desktop debe obtener el archivo `deploy/mvp/scripts/backup.sh` de un checkout autorizado de GitHub fijado al commit `c64893e86a983a86d57f9a7406d0d736417f17e3`, **no** de la release remota antigua ni de un `main` móvil. Confirmar `git rev-parse HEAD` y `git hash-object deploy/mvp/scripts/backup.sh` = `5ae19d8a8db75bb61f8e67bd1159acfab684ddc3`, más `bash -n`.

Transferir ese archivo por medio autenticado a un staging **privado y perteneciente a ubuntu** en el VPS. Definir la ruta exacta en `CANDIDATE`. No descargar código por `curl | bash` ni interpolar rutas/credenciales arbitrarias.

**Preflight READ ONLY con staged CANDIDATE (no instala):**

~~~bash
set -euo pipefail
OPS=/home/ubuntu/vinto-mvp-ops/scripts
: "${CANDIDATE:?Definir ruta privada del script staged}"
test "$(id -un)" = ubuntu
test -f "$CANDIDATE" && test ! -L "$CANDIDATE"
test "$(stat -c %U "$CANDIDATE")" = ubuntu
case "$(stat -c %a "$CANDIDATE")" in 600|700) ;; *) exit 1;; esac
test -f "$OPS/backup.sh" && test ! -L "$OPS/backup.sh"
test -f "$OPS/lib_common.sh" && test ! -L "$OPS/lib_common.sh"
test "$(sha256sum "$OPS/backup.sh" | awk '{print $1}')" = 12151e680a2ef8dd400393794041c18adf4425bfd4ebfea38d5882e7b345738a
test "$(sha256sum "$OPS/lib_common.sh" | awk '{print $1}')" = 31696d213baaf5436cc09766327ed6e1f53605802ffce970f89bb2813318c31b
test "$(git hash-object "$CANDIDATE")" = 5ae19d8a8db75bb61f8e67bd1159acfab684ddc3
bash -n "$CANDIDATE"
bash -n "$OPS/lib_common.sh"
command -v flock >/dev/null
echo "PASS: staged candidate, scripts historicos y flock correctos"
~~~

## C. Instalación atómica — SOLO TRAS GO ESPECÍFICO PARA SUSTITUCIÓN

Este bloque **ES MUTADOR**: escribe respaldo del *script* Ops y sustituye `backup.sh`, no la BD. No ejecutarlo todavía. Exigir preflight B completo y ausencia de procesos de respaldo no cooperativos.

~~~bash
set -euo pipefail
umask 077
OPS=/home/ubuntu/vinto-mvp-ops/scripts
: "${CANDIDATE:?Ruta privada del nuevo script}"
test "$(id -un)" = ubuntu
test "$(sha256sum "$OPS/backup.sh" | awk '{print $1}')" = 12151e680a2ef8dd400393794041c18adf4425bfd4ebfea38d5882e7b345738a
test "$(sha256sum "$OPS/lib_common.sh" | awk '{print $1}')" = 31696d213baaf5436cc09766327ed6e1f53605802ffce970f89bb2813318c31b
test "$(git hash-object "$CANDIDATE")" = 5ae19d8a8db75bb61f8e67bd1159acfab684ddc3
bash -n "$CANDIDATE"
command -v flock >/dev/null

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
saved="$OPS/backup.sh.pre-e1-09-$stamp"
test ! -e "$saved"
cp -p -- "$OPS/backup.sh" "$saved"
test "$(sha256sum "$saved" | awk '{print $1}')" = 12151e680a2ef8dd400393794041c18adf4425bfd4ebfea38d5882e7b345738a

mode="$(stat -c %a "$OPS/backup.sh")"
temp="$(mktemp -p "$OPS" .backup.sh.new.XXXXXX)"
install -m "$mode" -- "$CANDIDATE" "$temp"
test "$(git hash-object "$temp")" = 5ae19d8a8db75bb61f8e67bd1159acfab684ddc3
bash -n "$temp"
mv -T -- "$temp" "$OPS/backup.sh"
test "$(git hash-object "$OPS/backup.sh")" = 5ae19d8a8db75bb61f8e67bd1159acfab684ddc3
bash -n "$OPS/backup.sh"
echo "INSTALACION_OPS_PASS; NO ejecutar backup en esta fase"
~~~

Guardar la ruta `saved` y el SHA-256 **nuevo** informado por `sha256sum`. Si hay error después del `mv`, no afirmar PASS y ejecutar rollback autorizado sobre el script. Si ocurre antes, el script anterior continúa activo. No limpiar respaldos existentes ni alterar servicios.

## D. Rollback EXCLUSIVO de backup.sh Ops

Solo si se requiere revertir esta instalación, validando la copia correcta:

~~~bash
set -euo pipefail
OPS=/home/ubuntu/vinto-mvp-ops/scripts
: "${SAVED:?Ruta exacta de la copia previa de backup.sh}"
test "$(sha256sum "$SAVED" | awk '{print $1}')" = 12151e680a2ef8dd400393794041c18adf4425bfd4ebfea38d5882e7b345738a
temp="$(mktemp -p "$OPS" .backup.sh.rollback.XXXXXX)"
install -m "$(stat -c %a "$SAVED")" -- "$SAVED" "$temp"
bash -n "$temp"
mv -T -- "$temp" "$OPS/backup.sh"
test "$(sha256sum "$OPS/backup.sh" | awk '{print $1}')" = 12151e680a2ef8dd400393794041c18adf4425bfd4ebfea38d5882e7b345738a
echo "ROLLBACK_OPS_PASS"
~~~

No emplear `rollback.sh version` de la aplicación para esta operación.

## E. Puertas de decisión

**Ahora:** PR #136 mergeado; código QA PASS; **instalación solo preparada**.  
**Para instalar:** aprobación expresa de ejecución de C, revalidación in situ, transferencia privada del candidato íntegro y copia vieja verificable.  
**Para P1-B posterior:** tras instalar, verificar `flock` activo, permisos y salud, ausencia de trabajos no cooperativos; usar `backup.sh create-and-verify` con autenticación programática **sin revelar secretos**; guardar evidencia de dump nuevo verificado y restauración efímera aislada.  
**Aún prohibidos:** restaurar datos sobre `vinto_piloto`, borrar OT simuladas, ejecutar 0013, desplegar E1, cambiar flags, grants o TVC.
