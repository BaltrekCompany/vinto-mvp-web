# VINTO E1-09 — P2-B: preflight y secuencia de liberación controlada

**Estado:** preparación del siguiente paso tras merge del PR #137. **NO constituye autorización para migrar, desplegar o modificar una OT.** Fecha: 2026-11-06.

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
