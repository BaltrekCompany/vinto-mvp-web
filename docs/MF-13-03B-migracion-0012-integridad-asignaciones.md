# MF13-03.B — Migración 0012: guarda de BD «una asignación activa por máquina» con la compuerta apagada

Base: `origin/main` 1c00070 (merge de PR7). Solo backend/BD. No cambia endpoints, contratos HTTP, frontend, F3/F6, AUTHZ ni TVC/ETL/Nginx. **No activa ninguna compuerta ni modo AUTHZ y no se aplicó a ninguna base real.**

## 1. Diagnóstico (Fase A)

| Tema | Hallazgo |
|---|---|
| Migraciones | 0001…0011; 0012 es la siguiente. El ejecutor (`migrate.py`) solo lee `migrations/NNNN_*.sql`, una transacción por migración, checksum SHA-256, sin downgrade. |
| Tabla | `vinto_txn.assignment` (línea operativa, máquina, turno, fecha, `status` active/finished). |
| Restricciones vigentes | `assignment_one_active_line` (única por línea activa); trigger `validate_assignment_exclusivity` (0011): bajo el advisory lock por máquina rechaza otra **OT** en la misma máquina (23P01) y la misma línea lógica activa (23505), y hace inmutables identidad e historial. **`assignment_one_active_machine` se eliminó en 0011.** |
| Compuerta | `settings.work_orders_multi_machine_enabled` (variable de entorno del proceso backend; **global**, no por OT ni por máquina). Se evalúa solo en la aplicación (`assignments.service._multi_machine_enabled`, `work_orders.service`, router de capacidades, visibilidad). **PostgreSQL no puede observarla.** |
| Único camino de escritura | `INSERT INTO vinto_txn.assignment` solo existe en `assignments.service._activate_target` (usado por activación individual y masiva). La finalización es `UPDATE`. |
| Regla con compuerta apagada | Solo en la aplicación: activar sustituye la asignación vigente de la máquina; si hay varias activas (compuerta apagada después de usarla) → 409 `MULTIPLE_ACTIVE_ASSIGNMENTS`. **Laguna:** ninguna restricción de BD impide, con la compuerta apagada, dos activas de la **misma** OT en una máquina por un defecto del código o un escritor SQL directo. |
| Concurrencia | Orden de locks: OT → máquina (advisory, clave `sha256('vinto-assignment-machine:<id>')`) → asignación. El trigger 0011 toma el mismo lock (re-entrante). |

## 2. Invariantes y diseño (Fase B)

Invariantes: (i) con modo «una sola» una máquina no gana una segunda activa; (ii) misma OT y OT distinta se distinguen (0011 sigue siendo quien separa OT); (iii) la activación masiva legítima (compuerta encendida) no se bloquea; (iv) compatibilidad total con el flujo anterior; (v) sin estados inconsistentes bajo concurrencia; (vi) historia intacta.

**Diseño elegido:** trigger `BEFORE INSERT` `validate_assignment_single_mode` + declaración de modo por transacción.
- El backend declara `vinto.assignment_multi_line = 'on'|'off'` con `set_config(..., true)` en `_activate_target` (único `INSERT`).
- El trigger es **a prueba de fallos**: todo lo que no sea exactamente `'on'` (sin declarar, `'off'`, `'ON'`, `'true'`, backend antiguo, escritor SQL directo) se trata como modo «una sola» y rechaza (23P01) un `INSERT` activo si la máquina ya tiene otra activa. Solo un `'on'` explícito lo relaja, y entonces siguen rigiendo las reglas de 0011.
- Toma el **mismo lock por máquina**, por lo que dos transacciones concurrentes no pueden pasar ambas la comprobación (READ COMMITTED).
- Solo `INSERT`: finalizar y actualizar filas existentes nunca se bloquea; no se lee, cambia ni rechaza ningún dato existente. El flujo legítimo «finalizar anterior → insertar nueva» pasa porque la anterior ya está `finished`.

**Cómo se garantiza algo que PostgreSQL no puede ver:** la compuerta real no se observa; se garantiza la *declaración*. Toda escritura del backend pasa por un único punto que declara el modo desde el valor real del proceso, y cualquier omisión degrada al lado seguro. **Límite honesto:** protege contra defectos y escritores que no conocen el protocolo; **no** contra una sesión privilegiada que declare `'on'` a propósito, ni cubre un backend con la compuerta encendida que declare `'off'` (sería un defecto visible: rechazaría). No es una autorización.

**Alternativas descartadas**
1. *Índice único parcial por máquina (restaurar `assignment_one_active_machine`)*: incompatible con la compuerta encendida (varias líneas de la misma OT) y con el estado legado de varias activas; es justo lo que 0011 eliminó. → **Conflicto de diseño evitado**, no implementado.
2. *Constraint/trigger que lea el estado de la compuerta de una tabla de BD*: crea una segunda fuente de verdad que puede divergir de la variable de entorno y exige un procedimiento de sincronización en cada cambio de configuración.
3. *Trigger que rechace por estado/OT sin declaración*: no distingue compuerta apagada de encendida; bloquearía la activación masiva legítima.
4. *Solo bloqueos en la aplicación*: ya existen; no protegen frente a defectos ni escritores directos.

## 3. Archivos

- `backend/migrations/0012_assignment_single_mode_guard.sql` — función, trigger y comprobaciones posteriores. Sin DDL sobre datos.
- `backend/rollbacks/0012_assignment_single_mode_guard_rollback.sql` — elimina trigger y función y la fila de `schema_migration`; sin precondición de datos.
- `backend/preflights/0012_assignment_single_mode_preflight.sql` — verificación previa **solo lectura**: máquinas con 2+ activas.
- `backend/app/assignments/service.py` — 2 líneas: declara el modo en `_activate_target`.
- `backend/tests/test_assignment_single_mode_guard.py` — 20 pruebas.

## 4. Datos conflictivos: comportamiento seguro

0012 **no aborta ni corrige** nada: no hay precondición de datos porque el trigger solo actúa en `INSERT`. Una máquina con varias activas heredadas (periodo con compuerta encendida) sigue igual; con la compuerta apagada la aplicación responde 409 `MULTIPLE_ACTIVE_ASSIGNMENTS` y se resuelve finalizando explícitamente con `finish` (auditado). Nunca hay corrección destructiva automática. El preflight lista esas máquinas para decidir antes de apagar la compuerta.

## 5. QA (Fase D, base efímera `*_test`, datos sintéticos)

Ver resultados reales de ejecución en la descripción del PR. Cobertura: activación individual y masiva válidas, varias líneas de una OT (compuerta encendida), conflicto entre OT, doble activación simultánea (aplicación y `INSERT` directo sin pasar por el lock de la aplicación), activación vs. finalización concurrentes, reintentos idempotentes, compuerta apagada/encendida, valores de declaración inválidos, migración sobre datos compatibles e incompatibles, rollback + reaplicación con historia (asignaciones, capturas y auditoría) idéntica, y preflight de solo lectura. Mutación: sin la declaración del servicio fallan 3 pruebas con compuerta encendida.

## 6. Procedimiento

**Aplicar (en laboratorio primero, nunca `vinto_piloto` sin autorización del propietario):** 1) respaldo; 2) preflight (solo lectura); 3) desplegar el backend con la declaración; 4) `migrate.py --status`, `migrate.py`, `migrate.py --check`; 5) verificar `pg_trigger` y una activación individual en entorno aislado.
**Orden importante:** la migración puede ir antes o después del backend **mientras la compuerta esté apagada** (estado actual de producción). **Con la compuerta encendida, el backend con la declaración debe estar desplegado antes de la migración**, o las activaciones múltiples serán rechazadas.
**Revertir:** ejecutar el rollback en una transacción con la aplicación quieta. Limitación real: tras revertir, la regla con compuerta apagada vuelve a depender solo de la aplicación; el backend sigue declarando el modo (inofensivo).

## 7. Riesgos y GO / NO-GO

Riesgos: (1) declaración asertada por la aplicación, no leída de la compuerta real (ver límites); (2) backend antiguo + compuerta encendida + 0012 = activaciones múltiples rechazadas (mitigado por el orden de despliegue); (3) escritores SQL directos que inserten varias activas deben declarar `'on'` (hoy solo existen en pruebas).
**GO** si: preflight revisado, suite sin regresiones frente a la línea base, compuerta apagada en el entorno destino y backend desplegado antes de encender la compuerta. **NO-GO** si: hay un escritor externo que inserta asignaciones, o se pretende encender la compuerta sin el backend nuevo.
