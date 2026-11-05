# VINTO — E1-03: Inicio y finalización de línea lógica (API)

**Estado:** implementación candidata, en rama separada. **No activar en producción.**  
**Dependencia:** PR #118 (E1-02, migración 0013).  
**Regla funcional:** una máquina produce **una sola línea/producto** a la vez; la activación masiva sigue habilitando varias.

## Implementado
- Compuerta de servidor `WORK_ORDER_LINE_EXECUTION_ENABLED=false` por defecto, separada de `WORK_ORDERS_MULTI_MACHINE_ENABLED`.
- `POST /api/work-orders/{ot_id}/lines/{line_code}/start`, cuerpo estricto `{"assignment_id": "<uuid>"}`. Permiso `assignment.manage`. Validación de OT, máquina, sector, turno, asignación operativa vigente y exclusividad.
- `POST /api/work-orders/{ot_id}/lines/{line_code}/finish`, sin cuerpo. Permiso `assignment.manage`. Cierra la línea lógica y sus asignaciones activas, preservando capturas.
- Integración con la activación individual/masiva existente: cuando la compuerta está ON, una asignación NUEVA deja la línea en `enabled`, nunca en `in_production`. Una asignación histórica `active` sin fila de ejecución exige revisión explícita, no se promueve en silencio.
- `POST /api/assignments/{id}/finish` antiguo rechaza finalizar una asignación de línea en producción bajo la compuerta, evitando un fin de turno confundido con cierre lógico.
- Bloqueos: OT → advisory de máquina → asignación/ejecución. Índice único de 0013 protege también escritores que no pasen por la aplicación.
- La lógica histórica se conserva con compuerta apagada.

## Reglas previstas
| Solicitud | Estado | Respuesta |
|---|---|---|
| Inicio sobre `enabled` y asignación vigente | Sin otra línea produciendo | `200 in_production` |
| Inicio repetido sobre la misma línea | Misma asignación vigente | `200`, sin escritura |
| Inicio de otra línea en la misma máquina | Otra en producción | `409 LINE_MACHINE_IN_PRODUCTION` |
| Finalización de línea `in_production` | Válida | `200 finished` + cierre de sus asignaciones activas |
| Finalización repetida | Ya `finished` | `200`, sin escritura |
| Inicio de línea `finished` | Terminal | `409 LINE_EXECUTION_CONFLICT` |
| Llamada con compuerta OFF | Cualquier estado | `422 LINE_EXECUTION_DISABLED`, sin escritura |
| Línea fuera del sector autorizado | Cualquier estado | `404`, sin revelar información |

## Límites y bloqueos para GO-LIVE
- E1-04: F3/F6 **aún no exigen** `in_production`. La bandera debe seguir OFF.
- E1-05/E1-06: no hay botones en Supervisión ni protección/estado en Operación.
- E1-07: la finalización de línea **no cierra la OT**, porque el cierre manual es una tarea separada.
- D1: continuidad entre turnos sigue pendiente de Sergio. El nuevo inicio exige asignación y turno vigentes, y el fin lógico no es automático.
- D2: cantidad producida inferior a programada y motivo de saldo pendiente, pendiente del funcional.
- Preflight E1-09 para asignaciones `active` preexistentes: sin inicio implícito.

## QA y entrega
- Pruebas E1-03 con PostgreSQL 17 efímero, dos líneas habilitadas, inicio exclusivo, doble inicio concurrente, fin idempotente, antigua API y regresiones con bandera OFF.
- No tocar `main`, no desplegar VPS ni activar variables hasta QA integral E1-08.
- PR apilado sobre E1-02 (#118); fusionarlo solo después de completar dependencias y revisión.