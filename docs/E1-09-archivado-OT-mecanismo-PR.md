# VINTO E1-09 — Mecanismo de archivado de órdenes ficticias

**Estado:** código en rama de revisión, **NO DESPLEGADO Y SIN MODIFICACIONES DE OT EN LA VPS**.  
**Repositorio:** BaltrekCompany/vinto-mvp-web. **Base:** `main@c64893e86a983a86d57f9a7406d0d736417f17e3`.  
**Diagnóstico previo:** P2-A2/P2-A3 PASS, 20 OT en BD (7 draft/12 in_progress/1 published); las 12 in_progress contienen 72 asignaciones (11 activas/61 terminadas), 63 capturas submitted, 1.151 detalles, 5 bobinas y 5 decisiones de Calidad. Auditoría e importaciones no legibles con `vinto_app`. [ADR de alcance](https://github.com/BaltrekCompany/vinto-mvp-web/blob/docs/e1-09-safe-vps-inspection-20261105/docs/E1-09-P2A4-decision-archivo-legado.md).

## Objetivo de esta primera implementación

Permitir a **Jefatura** archivar y, posteriormente, restaurar OT que no han entrado en ejecución real ni tienen ninguna asignación. Preservar toda la data, estados y trazabilidad; evitar que las OT archivadas aparezcan en la lista operativa por defecto. **No intenta limpiar/reconciliar los 12 escenarios en progreso, resolver las 11 asignaciones activas ni despejar E1-08 por exclusión de visibilidad.**

## Contrato exacto

| Operación | Autorización y reglas |
|---|---|
| POST `/api/work-orders/{id}/archive` | Solo `work_order.manage` (Jefatura); body `{"reason":"motivo 10–300 caracteres"}`. OT `draft` o `published`, sin **ninguna asignación** histórica, actor y alcance completo de sus máquinas. Respuesta `WorkOrderOut` tradicional; 409 si en progreso/tiene asignaciones; 404 si ya archivada o fuera de alcance; 422 si razón inválida |
| POST `/api/work-orders/{id}/restore` | Solo `work_order.manage` y OT archivada dentro del alcance. Rehabilita su visibilidad, mantiene el status previo y no toca capturas/Calidad |
| GET `/api/work-orders` | Listado operativo **excluye** archivadas por defecto; alcance de sector/máquina/rol original no cambia |
| GET `/api/work-orders?archived=true` | Solo Jefatura/Supervisión con permisos de lectura y gestión; lista solo históricas dentro del alcance, sin bypass de permisos |
| GET `/api/work-orders/{id}` | 404 por defecto para archivadas; `?include_archived=true` solo para Jefatura/Supervisión autorizadas |
| UI Programación | Botón **Archivar OT** solo en OT `draft`/`published` y para Jefatura; exige motivo explícito. Panel **OT archivadas** opt-in, con opción Restaurar. No usa datos locales ni borra capturas |

## Persistencia y seguridad

- Nueva migración **`0014_work_order_archive.sql`** (aditiva, no backfill) añade `work_order.archived_at`, `archived_by` y `archived_reason`; CHECK de coherencia y FK a usuario. Se mantiene `work_order.status` original; el historial de cambio lo conserva el trigger de auditoría de `work_order`.
- Trigger DB rechaza archivar `in_progress` o cualquier OT con asignaciones, exige actor con `vinto.actor_id` y razón, y bloquea cambios de estado/identidad mientras archivada. Restaurar exige actor de sesión y limpieza total de metadatos; el audit trail permanece.
- Los triggers de la migración protegen versiones y líneas hijas de OT archivadas, y las escrituras directas de asignación con `FOR SHARE` sobre el padre para serializarse frente al cambio de archivado. El servicio toma lock de la OT antes de archivar; no modifica capturas, bobinas, Calidad o auditoría.
- Se conservan los filtros de visibilidad existentes (sector, todas las máquinas de línea, modo de lecturas MF13 y permiso `work_order.manage` para escrituras). No se agregan privilegios, ni consultas a `vinto_meta` con `vinto_app`.
- Archivado reversible **no es DELETE**. Los campos quedan NULL al restaurar; la razón y el actor del evento previo permanecen en auditoría inmutable, no se muestran públicamente en los contratos históricos.
- La primera versión archiva como máximo las OT sin asignaciones y de estado apto; el inventario P2-A sugiere **8 candidatas iniciales** (7 draft + 1 published), **sujetas a nueva verificación de estado y alcance al ejecutar**. **No hay ejecución masiva** ni marcas ficticio automáticas.

## QA y restricciones de liberación

- Pruebas con PostgreSQL 17 efímero `*_test`: integridad y auditoría, visibilidad por defecto e historial, restauración, 409/403/404/422 y rechazo de INSERT/UPDATE directos de asignaciones y descendientes.
- CI: workflow `e1-09-archive-ot.yml`, test de dominio/HTTP, regresiones de OT/asignaciones/cierre, TS y lint de frontend. Si el CI no está verde, **NO merge**.
- **Dependencia de esquema:** `0014` sigue el orden de migraciones y requiere `0013` primero. La migración 0013 **NO está aplicada al VPS**. No se debe ejecutar `migrate.py` en la VPS para instalar archivado sin aprobar por separado una secuencia que incluye 0013, comprobar checksums y asegurar flag E1 **OFF**.
- **PR no es GO de despliegue**. Ningún archivo Ops, release activo `86e4ec4`, OT simulada, permiso, servicio, flag, base real, dato de captura ni TVC se modifica por esta PR.
- **Bloqueantes E1:** 12 OT in_progress + 11 asignaciones active carecen de ejecución lógica 0013. Archivado visual no los retira del preflight E1-08, y esta PR no cambia sus consultas. El saneamiento requiere una propuesta posterior con transición explícita de estados, auditoría y autorización mutadora independiente.
- **Rollback futuro:** reversión de la interfaz/API o restauración funcional de OT archivadas bajo autorización; **no DROP** del esquema ni DELETE de eventos de auditoría, especialmente si ya se registraron archivados.

## Verificación antes de cualquier instalación

Revisar PR con Jefatura, Supervisión y QA: comportamiento de OT visibles por sector/rol, transición `draft` y `published`, rechazo de `in_progress`, inmutabilidad de OT, compatibilidad API y UX, tests de concurrencia. Confirmar respaldo off-host si se ejecutará cualquier cambio de datos y definir aprobación por lotes. Revalidar el entorno sin deshabilitar triggers y no tocar TVC.
