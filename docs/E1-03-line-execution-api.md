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
- D1 (precisado por Sergio): se puede continuar físicamente un producto al siguiente turno, pero para el MVP **no se implementará traslado automático de saldos, cantidades ni fechas**. Si hace falta continuar, Jefatura registrará **manualmente otra OT/programación**, por rapidez y para evitar modificar los plazos. Antes de utilizar la máquina para una OT nueva, Supervisión finaliza la línea anterior y cierra la OT si todas sus líneas terminaron. Una ejecución iniciada no se cierra automáticamente al vencer el turno: la política de continuidad directa de una misma línea queda como *backlog*, no requisito E1-03.
- D2 (confirmado): si se programan 120 y producen 90, Supervisión **puede finalizar** la línea sin texto justificativo obligatorio; la diferencia de 30 queda como **déficit de producción** en seguimiento/indicadores. No transformar automáticamente el saldo en «cancelado». Los motivos se investigan mediante los tableros operativos, no una explicación libre del operador. El saldo «cancelado» se reserva para una anulación expresa (Entrega 3).
- Preflight E1-09 para asignaciones `active` preexistentes: sin inicio implícito.

## QA y entrega
- Pruebas E1-03 con PostgreSQL 17 efímero, dos líneas habilitadas, inicio exclusivo, doble inicio concurrente, fin idempotente, antigua API y regresiones con bandera OFF.
- No tocar `main`, no desplegar VPS ni activar variables hasta QA integral E1-08.
- PR apilado sobre E1-02 (#118); fusionarlo solo después de completar dependencias y revisión.
## Aclaración funcional posterior — alcance mínimo (Sergio, 2026-11-05)

**Escenario turno Día → Noche:** Jefatura solicita 500 unidades en Día, se producen 450; faltan 50. Existe programación de 550 para Noche. Aunque la continuación del mismo producto es operativamente posible, **no automatizamos** el traspaso de 50 ni reescribimos las cantidades y la entrega de otras OTs. Para el MVP, Jefatura crea manualmente la OT/programación necesaria y define el nuevo objetivo (no suponer automáticamente 550+50). Antes de iniciar una nueva OT en esa máquina se finaliza la línea previa; así se conserva el bloqueo entre OT distintas y la trazabilidad por orden.

**Escenario finalización parcial:** 120 programados, 90 producidos. Supervisión finaliza la línea y el déficit observable es 30; **ningún motivo textual obligatorio**. La diferencia no es anulación ni «pendiente cancelado». Seguimiento deberá calcular programado vs. real y exponer el déficit, con el desglose de indicadores cuando exista.

**Precisión técnica:** el fin de turno no implica por sí solo fin de línea, ni equivale a una continuación automática. E1-03 exige asignación vigente para iniciar; E1-04 exigirá la misma vigencia para capturar. El uso manual de una **nueva OT** supone liberar de forma explícita las ejecuciones anteriores; no terminar procesos activos en silencio.

**Fuera de alcance actual:** arrastre automático, prorrateo de cantidades, edición automática de fecha de entrega, transferir capturas entre OTs y exigir texto explicativo por producción incompleta.
