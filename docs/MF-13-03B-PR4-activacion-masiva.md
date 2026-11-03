# MF13-03.B PR4 — activación masiva transaccional de una OT (backend)

`POST /api/work-orders/{work_order_id}/activate-all`: deja disponibles **todas** las líneas de una OT, en sus máquinas, en **una sola transacción de PostgreSQL**. Reutiliza las primitivas de PR3 (`_load_target`, `_activate_target`, `_lock_machines`, `_ensure_operational`). Sin UI (PR7), sin filtrado de Operación por concesiones (PR5), sin migraciones nuevas. La activación individual (`POST /api/assignments/activate`) no cambia.

Activar = dejar la línea disponible para que Operación la elija, no fabricar varios productos a la vez.

## Contrato
Permiso: `assignment.manage` (Supervisión). Cuerpo estricto (`extra="forbid"`); el cliente nunca envía máquina, turno, fecha operativa ni versión operativa.

| Fase | Cuerpo | Efecto |
|---|---|---|
| Vista previa | `{"dry_run": true}` | `200`. Solo lectura, devuelve el plan y `plan_hash`. |
| Confirmación | `{"dry_run": false, "plan_hash": "<64 hex>"}` | `201` si se activó algo (`outcome: applied`); `200` si ya estaba vigente (`already_in_effect`). |

`dry_run` es obligatorio (sin valor por defecto, para que una confirmación nunca ocurra por omisión); `plan_hash` es obligatorio al confirmar y prohibido en la vista previa.

Respuesta (ambas fases): `work_order{id,number}`, `status`, `plan_hash`, `can_confirm`, `summary{activate, already_active, blocked, expired_to_finish, conflicts}`, `lines[]` (`baseline_line_id`, `line_code`, `pv_reference`, `article`, `machine`, `shift`, `operating_date`, `action` = `activate | already_active | blocked`, `reason`, `assignment_id`), `expired[]` (asignaciones vencidas de **esta** OT que se finalizarían) y `conflicts[]` (asignaciones activas de **otra** OT; incluyen su número y si están vencidas). La confirmación añade `activated[]`, `already_active[]`, `finished[]` con el detalle completo de cada asignación (OT, máquina, turno, línea).

`reason` de una línea bloqueada: `MACHINE_INACTIVE`, `MACHINE_ACTIVE_WITH_OTHER_WORK_ORDER`, `SHIFT_NOT_CONFIGURED`, `SHIFT_AMBIGUOUS`.

Errores: `401`; `403` (perfil sin `assignment.manage`); `404 WORK_ORDER_NOT_FOUND` (OT inexistente, id mal formado o **alguna** máquina de la OT fuera del alcance del actor); `409 WORK_ORDER_NOT_ACTIVATABLE` (borrador/cerrada); `409 ACTIVATION_PLAN_CHANGED`; `409 ACTIVATION_BLOCKED`; `422` (cuerpo inválido, o `MULTI_MACHINE_DISABLED`).

## Compuerta `WORK_ORDERS_MULTI_MACHINE_ENABLED`
Apagada (por defecto): **vista previa y confirmación responden `422 MULTI_MACHINE_DISABLED`** antes de tocar la base, incluso para una OT de una sola máquina (activar varias líneas a la vez contradice la semántica histórica de una activa por máquina). Cuerpo, query o header no pueden encenderla (probado). La activación individual histórica sigue igual. No activar en la VPS.

## Vista previa sin escrituras
Se ejecuta en `REPEATABLE READ, READ ONLY`: PostgreSQL rechaza cualquier escritura (probado inyectando un `INSERT`). No crea versión operativa, ni asignaciones, ni auditoría, ni toma bloqueos de fila ni advisory. Resuelve turno y fecha por sector con el reloj de PostgreSQL.

## Plan y `plan_hash`
El hash son 64 hex: **32 de estado final aprobado** (OT, y por línea: línea, máquina, turno y fecha) + **32 de acciones** (acción y motivo por línea, asignación vigente, asignaciones vencidas a finalizar, conflictos). Es un control de concurrencia, no una credencial: la autorización la da `assignment.manage` y el alcance de sectores.

### Criterio de idempotencia (confirmación)
Se recalcula el plan bajo bloqueo y se compara:

| Situación | Resultado |
|---|---|
| Mismo estado final **y** mismas acciones | se aplica |
| Mismo estado final y **nada que hacer** (todas las líneas ya vigentes) | `200 already_in_effect`, sin escribir |
| Estado final distinto (otro turno/fecha, otra OT, otra máquina) | `409 ACTIVATION_PLAN_CHANGED`, sin escribir |
| Mismo estado final pero acciones distintas con trabajo pendiente (p. ej. alguien activó o finalizó una línea tras la vista previa) | `409 ACTIVATION_PLAN_CHANGED`, sin escribir |
| Plan con bloqueos o conflictos | `409 ACTIVATION_BLOCKED`, sin escribir |
| `plan_hash` mal formado | `409 ACTIVATION_PLAN_CHANGED` (servicio) / `422` (HTTP) |

- **Respuesta perdida**: el reintento con el mismo hash encuentra todo vigente → `already_in_effect`; no duplica nada. No se usa auditoría para detectarlo (`vinto_app` solo tiene `INSERT` en `audit_event`).
- **Hash anterior** (turno vencido, estado cambiado): `409` y hay que repetir la vista previa.
- Límite conocido: dos confirmaciones concurrentes con el mismo hash producen una `applied` y la otra `already_in_effect`.

## Reglas
- Misma OT, misma máquina: varias activas (L1 y L2 en MP1).
- **Otra OT activa en una máquina de la OT** (aunque esté vencida): bloquea **toda** la operación (`409`); no se finaliza ni se reemplaza nada. No hay `replace_assignment_ids`. La resolución es una acción explícita de Supervisión (`finish` de esa asignación, auditado) y repetir la vista previa; cualquier sustitución automática queda para una decisión funcional posterior.
- Línea ya activa en el turno vigente: `already_active`, sin insertar.
- Asignaciones vencidas **de la misma OT**: se finalizan y se reactivan **todas** las líneas para el turno actual (la activación de una línea ya no deja otras sin reactivar). Se verifica que lo finalizado sea exactamente lo aprobado; si no, se revierte todo.
- Máquina inactiva, turno no configurado/ambiguo, OT no activable: nada se escribe.
- Alcance: se valida la máquina de la cabecera y de **todas** las líneas antes de cualquier escritura. Si alguna está fuera del alcance → `404` sin datos de esa máquina; no existe el resultado parcialmente autorizado.

## Atomicidad y orden de bloqueos
Una única transacción (`connection.transaction()`); no hay una transacción por línea ni llamadas HTTP encadenadas. Orden:
1. OT (`FOR UPDATE`).
2. Máquinas de **todas** las líneas (cabecera incluida en el alcance), `pg_advisory_xact_lock` en orden por id.
3. Asignaciones activas de esas máquinas (`FOR UPDATE`, orden por id).
4. Recalcular y comparar el plan; abortar sin escribir si no coincide o hay bloqueos.
5. Escribir: por cada línea `activate` → `_load_target` + `_activate_target` con el **mismo** turno resuelto en el paso 4 (un cambio de turno durante la operación no puede producir un contexto mixto; si cambia antes de confirmar, el hash no coincide).
6. Comprobar que lo finalizado coincide con lo aprobado; cualquier fallo revierte todo (probado con un fallo inyectado en la última línea y con un rechazo de la base de datos).

**Sin ciclos con el trigger de 0011**: el trigger toma el mismo advisory lock por máquina que el servicio (re-entrante en la misma transacción), por lo que no añade un orden nuevo. Los bloqueos de fila de `assignment` solo se toman con el lock de su máquina ya adquirido (activate, finish, bulk, `lock_active_assignment`), de modo que nunca esperan por separado. `finish` y las capturas toman máquina → asignación; la masiva y la individual toman OT → máquina(s) → asignación. Todas son subsecuencias del mismo orden global. Dos masivas de OT distintas sobre máquinas comunes las bloquean en el mismo orden determinista.

## Auditoría
`vinto.actor_id` y un `request_id` generado por el servidor (nunca el del cliente) se fijan al inicio y quedan en todas las filas: versión operativa, líneas copiadas, estado de la OT y asignaciones. El `reason` de cada asignación creada o finalizada lleva el lote: `activate assignment [activate-all <plan_hash>]` / `finish previous assignment [activate-all <plan_hash>]`, para reconstruir qué plan aprobó cada cambio.

## Privilegios (`vinto_app`)
Sin tablas, roles ni `GRANT` nuevos. Vista previa: solo `SELECT` (`work_order*`, `assignment`, `machine`, `sector`, `shift*`, `article*`). Confirmación: los `INSERT/UPDATE` que ya usa la activación individual (`work_order_version`, `work_order_line`, `assignment`, `work_order.status`). `SET TRANSACTION … READ ONLY`, los advisory locks y `SELECT … FOR UPDATE` no requieren privilegios adicionales (`FOR UPDATE` exige `UPDATE` sobre la tabla, que ya existe para `work_order` y `assignment`).

## Compuerta apagada y escritores SQL directos (efecto de 0011)
Desde 0011 la base garantiza «una OT por máquina» y «una activa por línea», **no** «una activa por máquina». Con la compuerta apagada, la regla histórica la impone el servicio (único escritor de `assignment`); un escritor SQL directo ya podría crear una segunda línea activa de la **misma** OT. El riesgo es operativo (no hay otro escritor en la aplicación; `vinto_app` solo puede escribir lo que el servicio escribe) pero es una garantía menos que antes.
**Recomendación antes del despliegue operativo** (no hecha aquí; no se modifican migraciones fusionadas): una migración posterior (0012) que reintroduzca la restricción de forma condicionada, por ejemplo un trigger que consulte una fila de configuración `vinto_config` (`multi_machine_enabled`, solo escribible por el propietario/migrador y sincronizada con el despliegue de la variable), de modo que la BD rechace la segunda activa por máquina mientras esté en `false`. Alternativa mínima: mantener el flag apagado y la prueba de SQL directo como alarma operativa (consulta de auditoría de máquinas con 2+ activas). Decisión pendiente del propietario.

## Riesgos residuales
- La compuerta debe seguir apagada en la VPS hasta PR5 (Operación filtrada por concesiones) y PR8 (UI de `/active-lines`). Con ella encendida, `GET /api/assignments/active` responde 409 con 2+ activas.
- La visibilidad de OT multimáquina sigue siendo todo-o-nada por sectores (PR2).
- Conflicto con otra OT: sin atajo de sustitución; exige `finish` explícito. Decisión funcional pendiente para un flujo guiado en PR7.
- Una OT con muchas líneas (límite 200) ejecuta ~10 consultas por línea dentro de la transacción; aceptable para el límite, medir antes de ampliarlo.
- Pendiente de la suite global: ver la descripción del PR (incidencias heredadas vs. nuevas).
