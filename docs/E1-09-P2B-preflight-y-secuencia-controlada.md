# VINTO E1-09 — P2-B: preflight y secuencia de liberación controlada

**Estado:** preparación del siguiente paso tras merge del PR #137. **NO constituye autorización para migrar, desplegar o modificar una OT.** Fecha: 2026-11-06.

## G2 — Nuevo diagnóstico: instalador exit 1 sin log; causa de permisos identificada en código (06/nov/2026)

**Evidencia recibida:** staging original `/home/ubuntu/vinto-g2-staging-d5bc472` corregido a directorio `700` y dos archivos `600` **propiedad de `ubuntu`**. Tarball y manifiesto identifican `d5bc472b831eae8abd60899296ce8c146c119a5a`, SHA-256 tar `fed3605f81b72303d1aa3f3d8e73d0689a627075cfe2f5d2678bb2c3ccf2a88b`. Preflight previo a instalación PASS, pero `deploy.sh install-frontend-artifact` **exit 1**, detalle de stderr no conservado. **`dist` del release nuevo NO VERIFICADO después del fallo**; `check-release` no ejecutado. Release activo y servicios solo revalidados **antes** del intento. No se reportó ninguna migración ni modificación de negocio.

**Causa probable demostrable por inspección del script (aún NO confirmada como error concreto):**
`deploy.sh::phase_install_frontend_artifact` primero verifica manifiesto y `sha256sum` **como usuario operador `ubuntu`**, pero la extracción segura se hace mediante `sudo -u "$SERVICE_USER" python3.12 ... tarfile.open(artifact_path,"r:gz")` con `SERVICE_USER=vinto-mvp`. El directorio `700` y tarball `600` de `ubuntu` **impiden el acceso a `vinto-mvp`**; además `/home/ubuntu` podría impedir tránsito. Por tanto, el runbook anterior, al requerir staging 700/600 exclusivamente de ubuntu y pasar ese mismo path al instalador, impuso requisitos contradictorios. La integridad SHA PASS solo prueba la lectura como ubuntu. El error exacto no se conservó; pueden existir otros bloqueos, p.ej. validación del contenido del tar.

**Corrección de procedimiento, SIN elevar permisos globales:**

1. **Antes de escribir:** consultar `stat` del nuevo release y, bajo identidad `vinto-mvp` mediante utilidades `mvp_test` u `sudo -u vinto-mvp test`, confirmar si existen `dist` o `dist/standalone/server.js`. **Si `dist` existe, STOP / NO-GO** sin eliminarlo ni reinstalarlo: el instalador prohíbe sobrescribir. Revalidar release activo y salud; no tocar TVC. Verificar de forma no invasiva si `vinto-mvp` puede leer el tarball del staging original (fallo previsto), sin abrir su contenido.
2. Mantener intacto el staging privado original. Para la **única nueva instalación**, preparar un segundo directorio **aislado** en `/var/tmp` mediante `mktemp -d`, **propietario ubuntu, grupo vinto-mvp, modo 750**; copiar a él únicamente los dos archivos validados como **ubuntu:vinto-mvp, modo 640**. Estos modos conceden lectura a la identidad del servicio sin lectura pública, y permiten al operador verificar hash/manifest. No depender de traversal de `/home/ubuntu` por `vinto-mvp`. Si se requiere `sudo chgrp` o `sudo install -g vinto-mvp`, limitarlos a los archivos nuevos de esa ruta temporal y no modificar grupos/membresías/sudoers. Si política de sudo no lo permite, STOP.
3. Exigir explícitamente `test -r` sobre tarball como **ambos usuarios** (`ubuntu` y `vinto-mvp`) y `test -x` sobre el segundo staging como `vinto-mvp`. Comprobar SHA-256 de la copia **contra el valor exacto anterior** y manifiesto, y demostrar `dist` ausente inmediatamente antes del intento.
4. **Solo tras PASS de todas las guardas**, invocar una vez `deploy.sh install-frontend-artifact` con los archivos del segundo staging. Guardar stdout/stderr en un log **modo 600** de `ubuntu` (revisarlo y sanear secretos antes de compartir). Si exit !=0, **STOP y reportar el error real**, sin repetir. No editar scripts Ops ni extraer el tar manualmente.
5. Si PASS, comprobar `dist/standalone/server.js`, `current` antiguo y servicios sanos; ejecutar `deploy.sh check-release <SHA>` READ ONLY y esperar exit **2** con solo 0013/0014 pendientes. Sin `migrate-release`, `activate`, nuevos backups, flags, SQL ni cambios de OT/TVC. Conservar evidencia de staging hasta cierre de G2; limpieza solo con plan aparte.

**Límite:** no se puede afirmar aún que este sea el único fallo; `exit 1` sin stderr también podría deberse a guardas del tarball o instalación parcial. Esta sección reemplaza para el reintento G2 el consejo anterior de usar los archivos `700/600` de `ubuntu` directamente como argumentos del instalador.

## Resultado G2 — PARCIAL / NO-GO por artefacto frontend (06/nov/2026)

**Fuente:** informe Codex Desktop SSH entregado por el usuario. ChatGPT no realizó SSH ni escritura sobre el VPS.

| Fase | Resultado |
|---|---|
| Preflight G1 revalidado | PASS: host `vps-14d8e0ce`, operador `ubuntu`, release antiguo, backend/frontend y PostgreSQL MVP saludables, scripts Ops y P1-B íntegros, capacidad/concurrencia |
| Checkout | PASS: release nuevo `/opt/vinto-mvp-web/releases/d5bc472b831eae8abd60899296ce8c146c119a5a` recién creado; `origin` y `HEAD` exactos; propietario/grupo `vinto-mvp:vinto-mvp`, modo `775`; `.previous-release-path` correcto |
| Enlace `backend/.env` | PASS: apunta a `shared/backend.env`; archivo de destino regular, `vinto-mvp:600`, contenido no consultado |
| `python-venv` | PASS: dependencias Python instaladas solo en el nuevo release, exit 0 |
| Artefacto frontend | **PENDIENTE/BLOQUEO:** tarball + manifiesto válidos NO disponibles; CI PR #137 no generó artifacts |
| `check-release` | NO ejecutado: falta `dist/standalone/server.js`; correrlo ahora causaría error de preparación, no permite determinar esquema nuevo |
| Release activo | Sin cambios: `current` apunta a `86e4ec4fa6f6bf95c0e099279d8c51a016c7a6a4` |
| Migraciones y datos | SIN ALTERACIONES: no 0013/0014, activación, flags ni OT mutadas; último historial leído en G1 |
| Alcance de búsqueda | `find` amplio de artefactos produjo `Permission denied` en `/home/ubuntu/vinto/pgdata`. No inspeccionó datos y se detuvo; no repetir búsquedas amplias ni acceder a rutas TVC |

**Estado real:** G2 **PARCIAL**, NO-GO para G3/G4/G5. **No repetir** `checkout` ni `python-venv` por defecto: ya pasaron y el directorio versionado existe. No borrar/sobrescribir el release o revertir el symlink.

### Solución ya existente para el artefacto, sin cambios en producción

El repositorio `main@d5bc472b831eae8abd60899296ce8c146c119a5a` incluye el workflow versionado [`rc01-frontend-linux.yml`](https://github.com/BaltrekCompany/vinto-mvp-web/blob/main/.github/workflows/rc01-frontend-linux.yml): **`VINTO RC01 frontend artifact (Linux)`**, evento manual `workflow_dispatch`, input `source_commit` obligatorio. Ese workflow:

1. Comprueba `source_commit` de 40 hex, hace checkout exacto, verifica HEAD y árbol limpio, Linux x86_64.
2. Usa Node `22.18.0`, `VINTO_MVP_DOMAIN=vinto-mvp.baltrekservices.com` (validar que sea el dominio realmente autorizado antes de disparar), y llama a `deploy/mvp/scripts/build-frontend-artifact.sh`.
3. El script instala con pnpm lockfile, compila con `NEXT_PUBLIC_API_URL=https://$VINTO_MVP_DOMAIN`, completa dependencias standalone y pasa prueba HTTP 200 arrancando **el tarball extraído fuera del repositorio**.
4. Verifica `VINTO_MVP_ARTIFACT_COMMIT` y SHA-256 del `.tar.gz` contra el manifiesto; publica ambos mediante `upload-artifact` con retención 14 días y nombre `vinto-rc01-frontend-<source_commit>`.

**Forma de iniciar desde un cliente autenticado en GitHub (no desde VPS):** entrar a [Actions → VINTO RC01 frontend artifact (Linux)](https://github.com/BaltrekCompany/vinto-mvp-web/actions/workflows/rc01-frontend-linux.yml), pulsar **Run workflow**, seleccionar rama `main` y pegar `source_commit=d5bc472b831eae8abd60899296ce8c146c119a5a`. El input por defecto del workflow es antiguo; **no usarlo**. La conexión actual de ChatGPT no expone una operación para emitir el evento `workflow_dispatch`; no se ha lanzado por el asistente.

**Tras RUN exitoso:**
- Descargar ZIP del artifact **de esa misma ejecución** en GitHub Actions usando una cuenta autenticada; comprobar `source_commit`, conclusión SUCCESS, manifiesto completo y SHA-256 del tarball tras descomprimir, en el equipo externo. ZIP es contenedor de transporte: no pasar el ZIP como si fuese el `.tar.gz` al instalador.
- Transferir únicamente el tarball y el `.manifest` a una ruta de staging propiedad de `ubuntu` en el VPS, de acceso restringido. El canal se selecciona por el operador (p. ej. `scp`/SFTP autenticado), sin publicar enlaces secretos, tokens o variables de entorno. Nunca transferirlo a `/home/ubuntu/vinto/pgdata`, `/opt/vinto-web` o el árbol TVC.
- En el VPS **sin volver a ejecutar checkout o python-venv**: revalidar ruta SHA y salud, comprobar que el staging contiene exactamente `vinto-mvp-frontend-d5bc472b831eae8abd60899296ce8c146c119a5a.tar.gz` y su manifiesto. Verificar manualmente `sha256sum` frente al SHA del manifiesto, luego invocar únicamente:
  ```bash
  cd /home/ubuntu/vinto-mvp-ops/scripts
  SHA=d5bc472b831eae8abd60899296ce8c146c119a5a
  CONFIRM=yes bash deploy.sh install-frontend-artifact "$SHA" "<RUTA_STAGING>/vinto-mvp-frontend-$SHA.tar.gz" "<RUTA_STAGING>/vinto-mvp-frontend-$SHA.manifest"
  ```
  El script valida commit/hash, contenido tar seguro y no sobrescribe `dist`; en falla, detener sin "extraer a mano".
- Solo después de confirmar `dist/standalone/server.js` en release, ejecutar **`bash deploy.sh check-release "$SHA"`** (solo lectura). Esperado: exit **2**, pendientes **exactamente 0013 y 0014**; exit 1 o discrepancias ⇒ NO-GO, no migrar. No interpretar ese exit 2 como fallido en G2 cuando contiene precisamente las pendientes esperadas.
- Postchecks de no mutación: `current` igual, servicios MVP activos, migraciones y datos inalterados, flag E1 no habilitado, TVC no tocado. Reportar **G2 PASS / NO-GO** y detenerse antes de G3.

**Riesgos a retener:** el directorio versionado reportado como modo `775` es escribible por su grupo. Antes de activar en una intervención futura, validar que la membresía/permiso de grupo `vinto-mvp` está restringida al modelo de operación; no cambiar chmod/chown ni inspeccionar datos privados por su cuenta. El build del frontend incrusta dominio API en el cliente, por eso el dominio del workflow debe ser correcto antes de ejecutar.

## AUTORIZACIÓN G2 — vigente, instalación de release NO EJECUTADA (06/nov/2026)

El usuario confirmó explícitamente **«Autorizo ejecutar G2»** tras recibir el resultado G1 PASS. La autorización cubre **exclusivamente crear y preparar** el release inmutable de `main@d5bc472b831eae8abd60899296ce8c146c119a5a` en `/opt/vinto-mvp-web/releases/<SHA>`, sin modificar el enlace `current` ni ejecutar código nuevo en producción.

**Estado al registrar:** ChatGPT no dispone de canal SSH al VPS; no ha ejecutado G2. El operador autorizado Codex Desktop deberá ejecutar las acciones y devolver evidencia PASS/FAIL.

**Fases permitidas, condicionadas a controles PREVIOS otra vez PASS:**

1. Revalidar host `vps-14d8e0ce`, operador `ubuntu`, `current` apuntando a `86e4ec4fa6f6bf95c0e099279d8c51a016c7a6a4`, Docker Compose MVP/servicios sanos, G1 migraciones 0001–0012 y E1 flag efectivo OFF en release actual, capacidad y ausencia de operaciones de despliegue concurrentes. No leer secretos ni consultar/intervenir TVC.
2. Inspeccionar la **versión efectiva** de `/home/ubuntu/vinto-mvp-ops/scripts/deploy.sh` y `lib_common.sh` sin sobrescribirlos, confirmar que provee `checkout`, `link-backend-env`, `python-venv`, `install-frontend-artifact` y `check-release`. Rechazar drift de script o ruta anómala, no autocorregir Ops.
3. Confirmar que **no existe** `/opt/vinto-mvp-web/releases/d5bc472b831eae8abd60899296ce8c146c119a5a`. Si existe, **NO repetir `checkout`** ni borrar/sobrescribir el release: hacer solo inventario para evaluar un siguiente paso.
4. Desde usuario operador `ubuntu` y scripts Ops existentes (sin `sudo bash deploy.sh`), ejecutar exactamente una vez **solo si no existe**:
   ```bash
   cd /home/ubuntu/vinto-mvp-ops/scripts
   SHA=d5bc472b831eae8abd60899296ce8c146c119a5a
   CONFIRM=yes AUTHORIZED_COMMIT="$SHA" bash deploy.sh checkout "$SHA"
   ```
   Confirmar origin, `git rev-parse HEAD`, propietario del release y `.previous-release-path`. El checkout puede enlazar `backend/.env` a `shared/backend.env`; permitido solamente si su destino privado, propietario y permiso ya son válidos. Si no enlazó, ejecutar `CONFIRM=yes bash deploy.sh link-backend-env "$SHA"` **solo tras validar el contrato**; nunca mostrar contenido.
5. Crear el entorno Python dentro del release: `CONFIRM=yes bash deploy.sh python-venv "$SHA"`. Comprobar dependencias y `migrate.py --status` únicamente por el canal de lectura provisto por `check-release` **después de** que el frontend artefacto exista. No ejecutar migrador mutador.
6. El artefacto frontend debe **construirse fuera del VPS** en Linux x86_64 usando **`deploy/mvp/scripts/build-frontend-artifact.sh` del mismo commit**, con `VINTO_MVP_DOMAIN` autorizado, checkout limpio y Node/pnpm fijados; la prueba real de arranque aislada de ese script debe pasar. El artefacto y manifiesto deben trasladarse por canal validado al staging designado sin alterar `current`. **Jamás instalar Node/pnpm o construir frontend dentro de VPS**. En VPS instalar exclusivamente mediante `CONFIRM=yes bash deploy.sh install-frontend-artifact "$SHA" "<artefacto.tar.gz>" "<manifiesto>"`, que verifica commit y SHA256. Si no hay artefacto conforme, reportar **G2 PARCIAL / BLOQUEADO**, sin improvisar un build local en VPS.
7. Al quedar el release completo, ejecutar `bash deploy.sh check-release "$SHA"`, **solo lectura**, para comprobar historial/pendientes usando migrador legítimo. Exit **2** con únicamente 0013 y 0014 pendientes = **resultado previsto (no migrar)**; exit 0 inesperado, 1, divergencia o cualquier otra migración = STOP. Registrar hashes completos de 0013/0014 y resultado.
8. Postchecks: `current` y servicios intactos, release antiguo conservado, no alteración de la base, 0013/0014 sin aplicar, flag E1 OFF, no contenedores nuevos, sin intervención TVC. **Detenerse al finalizar G2.**

**Prohibido expresamente en este GO:** ejecutar `migrate-release`, `migrate.py` mutador, `activate`, `preflight-startup` de primera instalación a ciegas, `postgres-up`, `systemd-install`, backups nuevos, GRANT, DROP/ALTER/INSERT/UPDATE/DELETE de negocio, archivar OT, activar flags o tocar TVC. G3/G4/G5 requieren autorización independiente.

**Notas operativas:** `python-venv` puede instalar paquetes del lock/requirements del release en su propio `.venv`; ello está dentro de G2. Staging de artefactos frontend (fuera de release) debe estar identificado y auditado; no borrar otros artefactos. El comando `check-release` exige que exista el frontend y el venv, por eso NO invocarlo prematuramente. Mantener flag **OFF en configuración efectiva** antes de cualquier activación futura.

## G1 COMPLETADO — PASS; G2 GO técnico, pendiente de autorización (06/nov/2026)

**Fuente:** evidencia remitida por Codex Desktop/operador SSH, no ejecución directa de ChatGPT. **G1 solo lectura y sin cambios.**

| Control | Resultado |
|---|---|
| Host/operador | `vps-14d8e0ce` / `ubuntu`, PASS |
| Release activo | `/opt/vinto-mvp-web/current` → `86e4ec4fa6f6bf95c0e099279d8c51a016c7a6a4`, PASS |
| Servicios y DB MVP | Backend/frontend `active`; `vinto-mvp-postgres`, PostgreSQL 17, Compose `vinto-mvp`, `running/healthy`, PASS |
| Scripts Ops | SHA-256 de `backup.sh` y `lib_common.sh` coinciden con G1, PASS |
| Backup P1-B | Dump/manifiesto `sha256sum -c` PASS, marcador `.verified` presente |
| E1 flag release ACTIVO | `WORK_ORDER_LINE_EXECUTION_ENABLED` ausente del entorno y desconocido para release antiguo: **efectivamente OFF para release viejo**. Revalidar flag y default en release nuevo, NO asumir |
| Historial de migraciones | `vinto_migrator` legítimo verificó 0001–0012 continuas, nombres y checksums iguales a `main@d5bc472b831eae8abd60899296ce8c146c119a5a`. 0013 y 0014 NO APLICADAS |
| Checksums de nuevos archivos | 0013 `ef22f54c…b9ceac37`, 0014 `33f5a7a8…cd5edc0f` (resumen informado por Codex; utilizar SHA-256 **completo** calculado del checkout para G2/G4) |
| Objetos de esquema | Sin `work_order_line_execution` y sin `work_order.archived_at`, coherente con historial |
| Capacidad / procesos | 184 713 MiB disponibles, 25 734 019 inodos; ninguna operación de backup/deploy/migrador detectada |
| TVC | Fuera de alcance, no consultado/modificado |
| Datos agregados | 20 OT (7 draft, 12 in_progress, 1 published); 72 asignaciones asociadas a in_progress (11 active, 61 finished); 8 OT técnicamente candidatas sin asignaciones |
| Escrituras G1 | Ninguna: sin checkout, release preparado, migrations, DB, flags ni cambios de OT |

**Dictamen:** G1 **PASS / CERRADO**. Existe **GO técnico para solicitar autorización específica de G2** (preparar release, escribir solo dentro de nueva ruta versionada). **G2 no se ejecutó ni está autorizado por este informe**. G2 debe detenerse **antes de aplicar migraciones 0013/0014 o activar el release**.

**Conservación:** P1-B fue verificado pero está en filesystem del VPS; copia off-host aún NO VERIFICADA. Las 12 OT in_progress + 11 active siguen bloqueando activación de E1, aunque las 8 candidatas puedan eventualmente archivarse. Los datos son ficticios pero sus capturas/Calidad/auditoría conservan restricciones de integridad.

## 0. Línea base comprobada y alcance

- Repositorio: `BaltrekCompany/vinto-mvp-web`; merge PR #137 en `main@d5bc472b831eae8abd60899296ce8c146c119a5a`.
- Código nuevo: migración `0014_work_order_archive.sql`, endpoints `archive/restore`, histórico controlado y UI Jefatura; CI de PR #137 **9/9 SUCCESS**, incluida regresión de locks sobre asignaciones.
- Último estado del VPS **reportado por Codex** (no revalidado en esta fase): release activo `86e4ec4fa6f6bf95c0e099279d8c51a016c7a6a4`; PostgreSQL MVP 17 `vinto-mvp-postgres` healthy; migración **0013 no aplicada**; E1 flag **OFF**.
- P1-B: nuevo dump `vinto-mvp-vinto_piloto-20261106-154402-3915284.dump`, SHA-256 `4ea5aa54a8ebfc579d6703683e7252efe0acd432615072e39a0319a3b29b97a3`, marcador `.verified`, restauración temporal aislada 47 tablas / 0 discrepancias; 19 dumps y 19 verificaciones. Todos **en un único filesystem del VPS**, sin copia externa comprobada.
- Diagnóstico agregado P2-A2/P2-A3: 20 OT (7 draft, 12 in_progress, 1 published). Las 12 in_progress tienen 72 asignaciones (11 active / 61 finished), 63 capturas submitted relacionadas y dependencias de Calidad. **Archivado v1 no acepta estas 12** ni borra hechos.
- TVC en el mismo host (`postgres-vinto`, `vinto-web.service`) está **fuera del alcance**.
- No modificar `vinto_app` para permitirle leer `vinto_meta.schema_migration` ni `vinto_audit`: usar únicamente identidad de migrador para revisar historial de schema.

## 1. G1: preflight exclusivamente de lectura (próxima intervención)

**Objetivo:** obtener evidencia actualizada sin escribir, sin desplegar y sin imprimir credenciales ni IDs de negocio.

**Guardas obligatorias:**

1. Confirmar el operador/host VPS esperados; usuario no debe invocar scripts completos de Ops como root. Confirmar `/home/ubuntu/vinto-mvp-ops/scripts/backup.sh` instalado con SHA-256 `53bbda26c74b46f3868f239e27385f64d7c7c3d363a4e90a7427fb02259d3a25` y `lib_common.sh` SHA-256 `31696d213baaf5436cc09766327ed6e1f53605802ffce970f89bb2813318c31b`.
2. Confirmar `current` resuelve al release antiguo exacto; servicios backend/frontend `active`, contenedor MVP PostgreSQL 17, Compose `vinto-mvp`, `healthy`; no consultar, reiniciar ni intervenir TVC.
3. Revisar `WORK_ORDER_LINE_EXECUTION_ENABLED` **sin volcar `.env`**: solo reportar booleano efectivo **OFF/ON/NO VERIFICABLE**. **ON => NO-GO**.
4. Usando la identidad ya provisionada de `vinto_migrator` (a través de la configuración privada existente, nunca copiar credenciales a comandos, archivos o logs), comprobar historial `vinto_meta.schema_migration`: versiones consecutivas, nombres/checksums de 0001–0012, y si 0013 o 0014 están aplicadas. Consultar **solo metadatos**, no contenido de auditoría ni importaciones. No ampliar GRANT.
5. Comparar nombres y checksums de migraciones del checkout **`main@d5bc472b831eae8abd60899296ce8c146c119a5a`**. Rechazar cualquier 0013/0014 con nombre o checksum distinto, huecos o migraciones desconocidas. El `migrate.py --status` del release antiguo **no sirve para certificar** pendencias de un checkout nuevo: reconoce únicamente las migraciones incluidas en su propia versión.
6. Diagnóstico agregado, `REPEATABLE READ READ ONLY`, `lock_timeout <= 1500ms`, `statement_timeout <= 15000ms`: totales OT por estado, asignaciones activas/terminadas vinculadas, 8 candidatas sin ninguna asignación (por consulta con `NOT EXISTS`) y 12 en progreso; no mostrar UUID, números de OT, usuarios ni datos capturados. Confirmar que `to_regclass('vinto_txn.work_order_line_execution')` y `pg_attribute` para `archived_at` coinciden con el historial. No asumir que 20 OT globales son 20 visibles para cada sesión.
7. Revalidar P1-B solo por `sha256sum -c`, existencia de `.verified` y permisos; **no** ejecutar nuevo backup/verify/restauración ni limpieza sin un GO distinto. Comprobar espacio de disco y ausencia de procesos de `backup.sh`, `pg_dump`, `pg_restore`, `deploy.sh` o migrador concurrentes.
8. Concluir **PASS/NO-GO**. En cualquier discrepancia o acceso denegado, detenerse. No intentar otros roles ni elevar permisos automáticamente.

**Salida esperada G1:** tabla PASS/FAIL con SHA del código, histórico exacto de versiones 0012/0013/0014 (sin secretos), estado de flag, salud MVP, 8 candidatas potenciales y 12 legadas, verificación del backup y bloqueantes. **No realizar ninguna escritura**.

## 2. G2: preparación de release independiente (requiere GO nuevo)

Un nuevo release a partir del commit fusionado **no es** el checkout activo. Preparar exclusivamente bajo `/opt/vinto-mvp-web/releases/<sha>`, sin tocar `current`: checkout con `AUTHORIZED_COMMIT`, enlace privado `backend/.env` al `shared/backend.env`, venv, frontend artifact con manifiesto y SHA verificado (ver `deploy/mvp/scripts/deploy.sh`). Evitar resolver un `migrate-release` por medio de scripts ad hoc.

**Guard:** `deploy.sh check-release <sha>` solo tras `require_prepared_release` (requiere venv, migrador y `dist/standalone/server.js` verificados). Su código **2 significa migraciones pendientes previstas**, no error; **1 o historial divergente significa STOP**. No interpretar `--check` del release antiguo como certificación de 0013/0014.

Preparar/reutilizar artefactos solo mediante procedimientos existentes, con verificación de commit, permisos y coexistencia de otros servicios. El simple merge del PR #137 **no** da permiso para G2.

## 3. G3: copia de seguridad anterior a DDL (GO separado)

Antes de aplicar migraciones, crear **otro** respaldo `create-and-verify` con el `backup.sh` de Ops que ya pasó P1-B, sin sobrescribir ni depurar los 19 previos. Revalidar identidad estricta del contenedor MVP. Recomendable **copia fuera del host con comprobación de checksum/lectura restaurable**; si no existe, registrar riesgo y NO recomendar intervenir un entorno con datos que deban preservarse sin aceptación explícita. No exponer secretos del archivo `docker/.env`.

## 4. G4: migración controlada 0013 + 0014 (GO de base independiente)

Usar el script de Ops versionado: `deploy.sh migrate-release <commit>`, que exige `CONFIRM=yes` y `AUTHORIZED_COMMIT=<sha>`, toma el lock de activación/rollback y usa `migrate.py` del release **preparado**, en contexto de migrador. Exigir:

- Historial aplicado esperado **0001–0012** sin checksum drift; **exactamente 0013 y 0014 pendientes**. Si hay otra diferencia, detener.
- `WORK_ORDER_LINE_EXECUTION_ENABLED=false` confirmado en backend; no modificar flag durante G4.
- Cambios DDL aditivos: 0013 añade `vinto_txn.work_order_line_execution` **sin backfill**, 0014 incorpora columnas de archivado y triggers. No editar OT, asignaciones, capturas, Calidad o auditoría.
- **Una transacción por migración**: si 0013 pasa pero 0014 falla, 0013 permanece aplicada. Stop/no activate; preparar corrección hacia adelante, **no** DROP, DELETE ni borrado de historial como rollback.
- Postcheck con `migrate.py --check` del release nuevo, catálogo de columnas/triggers, conteos agregados contra línea base, continuidad backend/frontend/TVC **sin acciones sobre TVC**.

Este documento describe G4, **no lo ejecuta ni lo autoriza**.

## 5. G5: activación de release, smoke y OT ficticias (dos GO adicionales)

- **Release:** `deploy.sh preflight-startup` + `activate <sha>` solo tras migraciones PASS, build y salud aprobados; pruebas smoke de autenticación, Jefatura/Supervisión/Operación, listas, filtro de historial, permisos y rechazo de archivado en progreso. El flag lógico E1 debe seguir OFF. El rollback a un binario anterior sobre un esquema avanzado necesita análisis de compatibilidad; no intentar downgrade SQL.
- **OT:** después de UI/API productivas, y con autorización específica que enumere las OT permitidas por su responsable, archivar individualmente como máximo las `draft`/`published` sin ninguna asignación, usando API/Jefatura y motivo funcional; **no UPDATE manual SQL, no borrado**. Revalidar visibilidad por usuario/sector antes y después; conservar auditoría.
- **Legado:** las 12 `in_progress` (11 asignaciones active) permanecen **NO-GO** para archivado v1. Su resolución funcional requiere revisión de Supervisión/QA, propuesta independiente, QA y nuevo permiso para mutar; **ocultamiento NO satisface E1-08**. Mantener `WORK_ORDER_LINE_EXECUTION_ENABLED=false` hasta preflight E1-08 PASS real y validación funcional.

## 6. Criterios de parada inmediata

Historial/checksum no coincidente; migraciones no esperadas; flag E1 ON; backup no válido; falta de identidad estricta del contenedor/host; menos espacio del necesario; bloqueo/concurrencia; errores de permisos del migrador; cambios de estado no autorizados; fallo de tests o smoke; interferencia con TVC. **NO intentar solucionar saltando triggers, asignando roles más amplios ni limpiando datos ficticios a mano.**

**Referencias del repositorio:** `deploy/mvp/scripts/deploy.sh`, `backup.sh`, `backend/migrate.py`, `backend/migrations/0013_*.sql` y `0014_*.sql`; `docs/E1-09-archivado-OT-mecanismo-PR.md`; `docs/E1-08-preflight-legado-readonly.md`. Resultados P2-A anteriores en rama documental DRAFT #132; no fusionar #132 por este procedimiento.
