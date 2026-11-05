# VINTO — E1-02: modelo PostgreSQL de ejecución exclusiva por línea

**Baseline:** `main` at `86e4ec4fa6f6bf95c0e099279d8c51a016c7a6a4` (migrations 0001-0012).  
**Estado:** candidato técnico; no aplicado ni validado contra PostgreSQL de producción.  
**Dependencia:** `docs/E1-01-contrato-ejecucion-lineas.md` (contrato funcional; entregarlo junto a E1-02).

## A. Decisión de identidad

`work_order_line_execution.baseline_line_id` es la **PK** y referencia la línea de la versión `baseline` número 1. La identidad de la línea es estable aunque existan copias de `work_order_line` en versiones `operational`. El trigger confirma que OT y máquina coincidan con la línea baseline. Esas columnas son inmutables; una reprogramación futura crea otra versión sin sustituir esa identidad.

No se toca la tabla `assignment`. Su `status=active` **continúa significando habilitada para el turno**, no producción real. Una ejecución es un registro lógico por línea de negocio, independiente de los ciclos de asignaciones/turnos. Las capturas existentes siguen apuntando al `assignment_id` original.

## B. Estados y transiciones de ejecución

| Estado | Significado | Transición permitida |
|---|---|---|
| `planned` | Línea inicial, todavía no habilitada para el control nuevo | `enabled` |
| `enabled` | Disponible; no autoriza captura por sí sola | `in_production` |
| `in_production` | Única línea en producción de la máquina | `finished` |
| `finished` | Línea de negocio concluida; historia permanente | Ninguna |

**No hay pausa ni reactivación.** Una fila nueva solo puede insertarse como `planned`. El backend posterior (E1-03) debe crear `planned` y transicionar a `enabled` al habilitar formalmente una línea, o cuando Supervisión reconcilie explícitamente una asignación heredada. La finalización debe quedar registrada con `started_at/by` y `finished_at/by`.

**Importante:** la migración no hace backfill (ni a `planned`, `enabled` o `in_production`). Si una OT publicada/activa carece de fila de ejecución, el nuevo backend debe resolverla por acción de Supervisión, **nunca inventar un inicio**. Mientras la compuerta de ejecución esté apagada, la aplicación antigua conserva su comportamiento.

## C. Exclusividad y concurrencia

`UNIQUE(machine_id) WHERE status='in_production'` hace imposible que dos líneas de una máquina estén simultáneamente `in_production`, incluso si otra sesión hace SQL directo. **El backend E1-03/E1-04 deberá tomar el advisory lock de máquina** que ya usan `assignments` y `capture_service`, antes de actualizar la fila de ejecución. El trigger no adquiere ese lock directamente: un `BEFORE UPDATE` corre después de que PostgreSQL bloquea la fila y hacerlo invertiría el orden de locks frente a una captura concurrente. El índice UNIQUE es la garantía independiente contra dos ejecuciones simultáneas incluso para SQL directo.

El nuevo backend debe preservar el orden de locks: **OT → máquinas (en orden) → ejecución/asignaciones**. La captura usa **máquina → ejecución/asignación**. No sostener el lock de ejecución antes del de máquina. Los endpoints deben usar permisos efectivos y contexto de turno, no IDs enviados sin validar.

## D. Seguridad de esquema

- Nueva tabla en `vinto_txn`, con `SELECT, INSERT, UPDATE` para `vinto_app` si existe; **nunca DELETE**.
- Trigger de identidad y transiciones; trigger de no `TRUNCATE` y auditoría usando los helpers existentes.
- No se alteran ni borran `assignment`, `capture`, `bobbin`, versiones de OT, grants ni las migraciones históricas.
- No se cambia el estado de ninguna OT. El estado `closed` se conectará en E1-07.
- La capa de autorización por sector/máquina/grant sigue en la API, no se delega a una columna SQL editable por el cliente.

## E. Operaciones backend futuras y responsabilidad

| Acción | E1-03/E1-04/E1-07 debe hacer |
|---|---|
| Activación masiva | Dejar asignaciones `active` y sus líneas lógicas `enabled`, sin producir; idempotente |
| Inicio | Verificar permiso Supervisión, turno/assignment, OT y máquina; cambiar `enabled -> in_production` |
| Captura F3/F6 | Tras lock de máquina, comprobar **la misma** ejecución `in_production` y `assignment.active` vigente; idempotencia histórica para reintentos |
| Finalizar línea | Cambiar `in_production -> finished`, finalizar cualquier asignación activa relacionada y bloquear nuevas capturas |
| Cierre OT | Verificar todas las líneas baseline en `finished`, ninguna en producción, confirmar `work_order.closed` |
| Cambio de turno | No transformar implícitamente línea en `finished`; política final pendiente de Sergio |

Atención: una línea puede permanecer lógicamente `in_production` después de que venza una asignación de turno; eso NO debe autorizar capturas con asignación vencida. El procedimiento concreto para continuar en el siguiente turno está pendiente y se debe cerrar antes de activar el nuevo flujo en usuarios reales.

## F. Cómo incorporar estos archivos

1. Crear rama desde SHA exacto `86e4ec4fa6f6bf95c0e099279d8c51a016c7a6a4`.
2. Copiar `backend/migrations/0013_work_order_line_execution.sql`, `backend/preflights/0013_work_order_line_execution_preflight.sql`, `backend/preflights/0013_work_order_line_execution_verify.sql`, `backend/rollbacks/0013_work_order_line_execution_rollback.sql` y esta documentación.
3. Ejecutar el preflight de **solo lectura** en entorno autorizado y guardar evidencia.
4. Montar PostgreSQL 17 aislado y ejecutar **todas** las migraciones 0001-0013 con el runner real, luego pruebas de restricciones y concurrencia. No declarar PASS antes de esto.
5. Revisar que la nueva migración pasa con `vinto_migrator` y que `vinto_app` dispone solo de permisos mínimos; comprobar `--check`.
6. Integrar los endpoints y F3/F6 tras E1-03/E1-04, y solo entonces considerar despliegue y habilitación de una **compuerta nueva** independiente de `WORK_ORDERS_MULTI_MACHINE_ENABLED`.
7. En producción: respaldo, preflight, QA, estrategia de retroceso y autorización expresa antes de ejecutar el runner. **No instalar 0013 de forma aislada como activación funcional.**

## G. GO/NO-GO

- **GO para revisar E1-02:** contrato de estados aprobado, DDL sujeto a QA aislado, no cambios en datos actuales.
- **NO-GO para despliegue:** D1 cambio de turno no definido; E1-03/E1-04 aún no integrados; ausencia de prueba PG17 con runner; asignaciones activas heredadas sin reconciliación; falta de rollback probado.
- **Rollback:** solo mientras la tabla esté completamente vacía. Si ya tiene filas, aborta y exige avanzar con migración correctiva que conserve historia.

## H. Riesgos / validaciones

1. Verificar que `vinto_audit.touch_row()` y `record_change()` aplican a la nueva tabla y su PK.
2. Probar bloqueo de `DELETE`, `TRUNCATE`, transiciones inválidas, cambio de máquina, duplicidad en producción y rollback.
3. Probar concurrencia inicio/inicio, inicio/fin, captura/fin y captura simultánea; el esquema solo es una capa de protección.
4. E1-03 debe controlar que `assignment.finish` legado no marque automáticamente la ejecución `finished` ni permita reactivar una línea terminal.
5. Los 9 tickets de Entrega 1 continúan pendientes hasta las pruebas y su integración en código.