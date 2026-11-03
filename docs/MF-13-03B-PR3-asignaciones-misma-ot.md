# MF13-03.B PR3 — varias líneas activas de una misma OT en una máquina

Evolución transaccional de las asignaciones: migración `0011` + servicio de asignaciones. No incluye activación masiva (PR4), listados de Operación filtrados por concesiones (PR5) ni UI (PR6–PR8). Depende de PR1 (`work_order_line.machine_id`) y de la compuerta de PR2.

Activar significa **dejar una línea disponible para que Operación la elija**, no producir dos productos a la vez.

## Regla de negocio
| Situación en una máquina | Resultado |
|---|---|
| L1 y L2 de la misma OT | ambas activas a la vez; activar L2 no finaliza L1 |
| Línea de otra OT mientras hay líneas activas (del turno actual) | `409 MACHINE_ACTIVE_WITH_OTHER_WORK_ORDER`; nunca se finaliza la ajena |
| La misma línea otra vez, mismo turno y fecha | idempotente (`already_active`), sin escribir ni auditar |
| Asignaciones de otro turno/fecha (vencidas) | la siguiente activación en la máquina las finaliza; no cuentan para el conflicto entre OT |
| L3 de la OT en otra máquina (MP3) | independiente de MP1 |

La máquina de la asignación es la de la **línea** (0010), no la de la cabecera de la OT.

## Base de datos (0011)
`migrations/0011_assignment_same_work_order_lines.sql`:
1. `assignment_one_active_line`: índice único parcial `(work_order_line_id) WHERE status='active'`. Una línea tiene como máximo una asignación activa.
2. Trigger `validate_assignment_exclusivity` (BEFORE INSERT OR UPDATE): con asignación activa, toma el **mismo advisory lock por máquina que usa el backend** (clave = 8 primeros bytes de `sha256('vinto-assignment-machine:<id>')`; re-entrante en la misma sesión) y rechaza
   - otra OT activa en esa máquina → `23P01`;
   - la misma línea lógica (OT + `line_code`) ya activa → `23505`.
   La consulta se ejecuta tras obtener el lock, así que en READ COMMITTED una segunda transacción ve lo ya confirmado por la primera. Probado con dos escritores SQL directos sin el servicio.
3. Identidad inmutable: `work_order_line_id`, `machine_id`, `shift_schedule_id`, `operating_date`, `assigned_by` no cambian en UPDATE, y una asignación `finished` no se reactiva (`23514`). Así la FK compuesta de `capture` y el contexto histórico no pueden reescribirse.
4. `assignment_one_active_machine` se elimina **al final y en la misma transacción**, cuando los puntos 1–3 ya existen. La migración comprueba antes que los datos actuales cumplen la regla nueva y después que los índices y el trigger quedaron como se esperaba.

Sin cambios: 0001–0010, FK compuesta de `capture`, `z_touch`, `audit_changes`, `validate_assignment`, `work_order.machine_id`. Sin tablas, roles ni `GRANT` nuevos: la función es de tipo `trigger` (no invocable, sin `SECURITY DEFINER`), corre como invocador y solo lee `assignment`, `work_order_line` y `work_order_version`, sobre las que `vinto_app` ya tiene `SELECT` (`roles/03_table_grants.sql`).

## Servicio (`app/assignments/service.py`)
- `activate` se divide en `_load_target` (bloquea la OT, valida estado, línea, máquina de la línea, alcance, compuerta) y `_activate_target` (versión operativa, lock de máquina, conflictos, escritura). **PR4** podrá validar N líneas y activarlas en una sola transacción con las mismas piezas; `_lock_machines` ya ordena los locks por id.
- Orden de bloqueos: **OT (`FOR UPDATE`) → máquinas (advisory, orden por id) → asignaciones (`FOR UPDATE`)**. `finish` toma máquina → asignación y las capturas máquina → asignación: son subsecuencias del mismo orden, sin ciclos (probado con activar/finalizar concurrentes). El trigger usa el mismo lock re-entrante, así que no añade un orden nuevo.
- Todas las decisiones se toman **antes de escribir**; un 409 deja el estado idéntico (sin versión operativa creada, sin cambio de estado de la OT, sin auditoría).
- Visibilidad: la OT es visible si la máquina de su cabecera o de alguna línea baseline está en el alcance del actor; la línea de una máquina fuera de alcance es indistinguible de una inexistente (`BASELINE_LINE_NOT_FOUND`). Máquina de la línea inactiva → `WORK_ORDER_NOT_ACTIVATABLE`. La línea operativa debe estar en la misma máquina que su baseline.
- El cambio de máquina de una línea publicada ya lo impide `guard_order_line` (probado).

## Compuerta `WORK_ORDERS_MULTI_MACHINE_ENABLED` (apagada por defecto)
| Compuerta | Comportamiento |
|---|---|
| Apagada | Semántica histórica: una activa por máquina; otra línea u otra OT **reemplaza** a la anterior (`finished_assignment_id`). Una línea de una máquina distinta de la cabecera → `422 MULTI_MACHINE_DISABLED`. |
| Encendida (solo pruebas aisladas) | Varias líneas de la misma OT; otra OT → 409. |

**Se apaga con varias activas ya creadas.** No se oculta, borra ni finaliza nada por adivinación:
- Activar algo que reemplazaría a una de varias → `409 MULTIPLE_ACTIVE_ASSIGNMENTS`, sin escribir. Reactivar una de las ya activas sigue siendo idempotente.
- `finish` sigue funcionando: se resuelve de forma explícita y auditada. Con una sola activa vuelve la sustitución histórica.
- `GET /api/assignments/active` responde 409 (no elige una); `GET /api/assignments` y `/active-lines` siguen mostrando todas.
- Como la BD ya no impone «una por máquina», con la compuerta apagada esa garantía la da el servicio (único escritor de `assignment`). Si se quiere que la garantice la BD, es una migración nueva y reversible solo sin multiplicidad (ver rollback).

## Contrato HTTP
| Endpoint | Cambio |
|---|---|
| `POST /api/assignments/activate` | Mismo cuerpo (`extra=forbid`) y semántica de 200/201. Respuesta añade `finished_assignment_ids` (lista completa). `finished_assignment_id` es la finalizada solo si fue exactamente una; si fueron varias (turno nuevo) es `null`, nunca una elegida. |
| `GET /api/assignments/active?machine_code=` | **Forma idéntica** con 0 o 1 activa. Con 2+: `409 MULTIPLE_ACTIVE_ASSIGNMENTS` (devolver `assignment: null` se leería como «sin asignación»). |
| `GET /api/assignments/active-lines?machine_code=` | **Nuevo.** `{current_shift, assignments:[{assignment, stale}]}` con todas las activas, antiguas primero, sin selección implícita. Mismo permiso (`assignment.read`) y alcance de sectores. |
| `POST /api/assignments/{id}/finish`, `GET /api/assignments` | Sin cambios. |

Contrato para PR5/PR8: la pantalla de Operación debe leer `/active-lines` (o `GET /api/assignments?status=active`), listar **todas** las líneas, mostrar `stale`, y enviar `assignment_id` explícito en cada captura. Hasta entonces la compuerta sigue apagada: `lib/vinto/assignments-api.ts` y `use-central.ts` consumen `/active` y con 2+ activas verían un 409.

## Dependencias de una sola asignación (análisis)
- **F3 / F6 / captura central / bobinas / Calidad**: reciben `assignment_id` del cliente; `lock_active_assignment` toma el lock de la máquina y valida *esa* asignación (activa, vigente, OT no cerrada). No consultan «la» activa de la máquina, por lo que admiten varias. Probado: F3 sobre L1, L2 y L1 de nuevo con ambas activas; cada captura conserva su `assignment_id`. Calidad deriva OT/línea de `bobbin → capture → assignment`.
- **`capture_uniqueness` (P1-16)**: unicidad por máquina **y OT**; con varias líneas de la misma OT en la máquina, un correlativo se considera ya usado en toda la OT. No cambia respecto de hoy, pero PR5 debe confirmar si la regla de negocio es por OT o por línea.
- **Frontend**: ver contrato arriba. No se tocó UI.

## Plan de reversión
`backend/rollbacks/0011_assignment_same_work_order_lines_rollback.sql` (no es migración; una transacción, app inactiva, propietario):
- **Se rechaza** si alguna máquina tiene 2+ asignaciones activas (`Rollback refused`). Nunca finaliza, borra ni edita asignaciones o capturas para que el índice antiguo «encaje»: primero se resuelve con `finish` (explícito y auditado) o se avanza con una migración nueva.
- Si pasa la guarda: recrea `assignment_one_active_machine`, elimina trigger, función e índices nuevos y borra la fila 11 de `schema_migration`. Datos y capturas intactos.
- Ensayo en pruebas: con datos representativos (historial, activas, capturas) la secuencia reversión → reaplicación deja filas idénticas; con multiplicidad la reversión aborta y deja todo igual.
- Antes de producción: respaldo de `vinto_txn.assignment` y `vinto_audit.audit_event`. Recordar que revertir el **código** a PR2 con asignaciones múltiples ya creadas es seguro para la BD pero dejaría el `/active` histórico ambiguo; con la compuerta apagada no deberían existir.

## Riesgos y bloqueos pendientes
- **Compuerta apagada en producción; no activar en la VPS.** Mientras esté apagada, PR3 no cambia el comportamiento visible.
- Con la compuerta encendida hoy: la UI actual (`/active`) fallaría con 2+ activas → **bloquea PR8**.
- Asignaciones vencidas: se finalizan al activar en la máquina; hasta entonces siguen `active` (igual que hoy). PR4 (activar todo) debe reactivar todas las líneas deseadas del turno nuevo, porque activar una sola finaliza las vencidas restantes.
- **PR4**: reutilizar `_load_target`/`_activate_target` en una transacción; ordenar máquinas con `_lock_machines`; decidir el resultado parcial/atómico (recomendado todo o nada).
- **PR5**: listados y capturas filtrados por máquina autorizada; hoy la visibilidad de OT multimáquina es todo-o-nada por sectores/perfil (PR2).
- La BD ya no garantiza «una activa por máquina» para escritores que no sean el servicio con la compuerta apagada (solo «una OT por máquina» y «una por línea»).

## Evidencia (solo `vinto_test`, Docker local; nada en `vinto_piloto` ni en la VPS)
Ver la descripción del PR: pruebas nuevas `tests/test_assignment_same_work_order.py` (43) y `tests/test_assignment_same_work_order_api.py` (9), y comparación de la suite completa con el baseline.
