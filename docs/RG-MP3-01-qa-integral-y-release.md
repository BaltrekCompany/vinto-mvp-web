# VINTO · RG-MP3-01 — Plan de preproducción, permisos y QA

**Ámbito:** únicamente `MP3` / `VINTO-MP3-01`. No hay una nueva migración SQL: se reutilizan `vinto_config.form`, `form_version`, `form_version_machine` y `field_definition` y sus controles de importación. `VINTO-P1-01` v4 para MP1 no cambia; sus registros históricos de MP3 tampoco se eliminan.

> **No ejecutar los pasos de escritura en la VPS sin autorización expresa de release, evidencia de CI y un backup reciente verificado.** PR #161 solo prepara código y pruebas. No activa ni fusiona producción.

## Paso 1 — Validar la rama de CI (sin producción)

Las pruebas de `.github/workflows/mp3-rg01-contract.yml` deben concluir **PASS** para el SHA exacto:

- Contrato: 20 secciones, 133 campos, los siete Pulper obligatorios, campos de Limpieza libres, químicos decimales, posiciones 1/2/3 independientes; tests estructurales, TypeScript, ESLint.
- Suite histórica de frontend actualizada: las 6 pruebas que antes asumían exactamente 25 formularios; las 25 versiones existentes siguen conservadas.
- Backend unitario: la ficha RG01 solo se ofrece en MP3, `VINTO-P1-01` sigue para MP1, el control de turno usa la fecha operativa y el turno real.
- PG17 HTTP: validación 422, capturas reales 201, reintentos 200, segundo ID 409, dos concurrentes 201+409, y registro antiguo MP3 del turno de transición cuenta como ocupado.
- PG17 permisos: operador sin concesión -> `eligible=false` y 403 con `enforce`; concesión exacta -> `eligible=true` y captura permitida; revocación -> denegación de nuevo.
- PG17 importación: 25 formularios preexistentes y 464 campos; dry-run solo permite añadir 1 formulario + 1 versión + 1 relación MP3 + 133 campos (=136 filas de referencia); apply idempotente y segundo dry-run sin pendientes.
- Regresiones E1/E2: sin fallas nuevas respecto del baseline anterior. Un test obsoleto debe actualizarse con una regla explícita que preserve MP1; NO se excluye un fallo por conveniencia.

## Paso 2 — Preparar release sin activarlo (solo con SHA autorizado)

El operador VPS `ubuntu` debe usar los scripts de release existentes y el flujo de artefacto frontend portátil, verificar commit/manifiesto y checksum. El release candidato debe tener:

- `backend/.venv/bin/python` y enlace `backend/.env` correctos.
- `backend/seed_data/forms/VINTO-MP3-01.json` y el manifest congruente.
- `backend/mp3_rg01_import_gate.py` y `backend/mp3_rg01_operator_readiness.py`.
- `deploy/mvp/scripts/mp3_rg01_import_release.sh`.

El formulario del candidato se puede **evaluar antes de activar**. IMPORTANTE: el operador `ubuntu` no tiene acceso de lectura al árbol privado de releases. No ejecutar `bash /opt/vinto-mvp-web/releases/...` directamente: instalar primero una copia idéntica, identificada por SHA, en el directorio operativo protegido.

```bash
set -euo pipefail
SHA=<SHA_EXACTO_40_CARACTERES>
REL="/opt/vinto-mvp-web/releases/$SHA"
OPS="/home/ubuntu/vinto-mvp-ops/scripts"
SCRIPT="mp3_rg01_import_release.sh"
test "$(sudo -u vinto-mvp git -C "$REL" rev-parse HEAD)" = "$SHA"
test -d "$OPS"
if test -e "$OPS/$SCRIPT"; then
  sudo cmp -s "$REL/deploy/mvp/scripts/$SCRIPT" "$OPS/$SCRIPT" || {
    echo "MP3_RG01_STOP=OPS_SCRIPT_DIFFERS" >&2
    exit 2
  }
else
  sudo install -o ubuntu -g ubuntu -m 700 "$REL/deploy/mvp/scripts/$SCRIPT" "$OPS/$SCRIPT"
fi
test -x "$OPS/$SCRIPT"
bash "$OPS/$SCRIPT" check "$SHA"
```

Estado esperado `MP3_RG01_DRY_RUN=PASS`; `state=new`, `pending_creates=136`. Si la base ya importó exactamente ese formulario, `state=already_imported`, `pending_creates=0` es un no-op aceptable. Cualquier otro valor o error: **STOP**, no improvisar `UPDATE` ni `INSERT` SQL.

## Paso 3 — Respaldo verificado y aplicación controlada

```bash
cd /home/ubuntu/vinto-mvp-ops/scripts
CONFIRM=yes bash backup.sh create-and-verify
bash backup.sh list
```

El operador identifica el respaldo NUEVO y confirma `verified`. La escritura de catálogo aún requiere autorización de release, con commit y ruta del backup explícitos:

```bash
SHA=<SHA_EXACTO_40_CARACTERES>
BACKUP_FILE="/home/ubuntu/vinto-mvp-backups/<RUTA_REAL_DEL_BACKUP>.dump"
CONFIRM=yes AUTHORIZED_COMMIT="$SHA" BACKUP_FILE="$BACKUP_FILE" \
  bash "/home/ubuntu/vinto-mvp-ops/scripts/mp3_rg01_import_release.sh" apply "$SHA"
```

El script verifica backup, SHA y candidatas, comparte el candado de `/home/ubuntu/vinto-mvp-ops/scripts` con `activate/rollback`, repite dry-run, aplica con el importador oficial y hace postcheck. **No** modifica `current`, no reinicia servicios ni concede permisos. Se exige `MP3_RG01_PREACTIVATION_IMPORT=PASS`. La nueva definición puede coexistir con el código anterior hasta la activación.

## Paso 4 — Comprobar y conceder permisos exactos (sin concesión automática)

El motor MF-13 exige **perfil funcional con `production.capture` + sector BOBINAS concedido + máquina MP3 activa + versión RG01 publicada + concesión activa (usuario, MP3, VINTO-MP3-01)**.

Después de importar y antes de activar, ejecutar **solo lectura**:

```bash
SHA=<SHA_EXACTO_40_CARACTERES>
sudo -u vinto-mvp bash -c '
  cd "$1/backend"
  exec .venv/bin/python mp3_rg01_operator_readiness.py
' -- "/opt/vinto-mvp-web/releases/$SHA"
```

La salida enumera operadores `eligible`, `needs_grant` y `not_authorized`, sin claves ni tokens. `NEEDS_EXPLICIT_GRANTS` significa **STOP**, no habilitar UI para operador ausente. Conceder solo a usuarios seleccionados mediante el panel administrativo de VINTO, por un administrador autenticado; no hacer una inserción SQL manual ni una concesión masiva a todos. Repetir la consulta, confirmar `eligible` para los operadores responsables; auditar las concesiones.

**Ojo:** incluso si `AUTHZ_CENTRAL_CAPTURES_MODE=off` en backend, la UI usa `eligible` del motor real; sin concesión puede ocultar el formulario. No se debe ampliar implícitamente el permiso por estar autenticado.

## Paso 5 — Activación y QA manual (otra autorización, no forma parte del PR)

Solamente con backup verificado, CI del mismo SHA en PASS, importación PASS y permisos confirmados, usar las compuertas ya existentes (E2-D2, `check-release`, `preflight-startup`) y el `deploy.sh activate <SHA>` controlado.

El QA funcional debe verificar captura con solo siete Pulper, opcionales sin valor, decimales correctos, cabeceras automáticas, botón/errores, cierre de sesión, historial, registros con fecha operativa nocturna, reintento y doble envío, un operador autorizado, otro sin concesión, MP1 intacto y bloqueo del formulario viejo en MP3 para nuevos registros. El resultado de QA manual es independiente del PASS técnico de CI.

## Rollback

- El script de activación puede devolver el código a la versión previa; el **catálogo aditivo no debe borrarse** automáticamente. Un rollback de código no revierte datos ni concesiones.
- El release antiguo podría volver a ofrecer el formulario `VINTO-P1-01` en MP3. Revisar capturas y el turno afectado antes de reanudar operación, pues su política previa no conocía RG01. Registrar incidente y detener nuevas capturas si hay riesgo de duplicación.
- Si el importador detecta drift, parar y diagnosticar. **No** borrar versiones, formularios ni campos históricos como reparación.
