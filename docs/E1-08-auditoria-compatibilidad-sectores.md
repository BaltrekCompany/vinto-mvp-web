# E1-08 — Auditoría de cobertura y corrección de sectores centrales

**Hallazgo inicial:** el flag `WORK_ORDER_LINE_EXECUTION_ENABLED` y el guard E1-04 son **globales**. Activarlo con los PR #118–#128 sin integrar la UI de Rebobinado/Conversión bloquearía nuevas capturas por falta de línea `in_production`, mientras las pantallas de esos sectores seguían mostrando únicamente `assignment.active`.

## Inventario de escrituras centralizadas

| Ruta de producción | Contrato | Guard transaccional E1-04 | Superficie UI |
| --- | --- | --- | --- |
| POST /api/bobbins | F3 · VINTO-P1-03 | `bobbins.service` llama a `capture_service.lock_active_assignment` | Bobinas · Ejecución |
| POST /api/captures | F6 y otros 13 formularios del conjunto explícito `CENTRAL_FORM_CODES` | `capture_service.submit_production_capture` llama a `lock_active_assignment` | Bobinas, Rebobinado y Conversión |

**14 códigos del conjunto `CENTRAL_FORM_CODES`:** VINTO-P1-06, -01, -02, -04, -05, -31, -07, -10, -30, -11, -12, -13, -16 y -29. No se admiten códigos nuevos automáticamente. Todos los POST nuevos pasan por el guard compartido cuando la compuerta está ON.

**Fuera del guard de ejecución, intencionalmente:** `POST /api/quality/bobbins/{id}/captures` (Calidad sobre bobina ya producida; puede evaluarse después del fin de línea) y `POST /api/quality/machines/{code}/captures` (control de Calidad independiente de OT). No bloquear Calidad retroactivamente.

## Correctivo en PR E1-08

1. Rebobinado y Conversión usan la misma capacidad confirmada por servidor que Bobinas para que Supervisión habilite, inicie y finalice líneas y cierre la OT completa. Sin `line_execution=true` verificado, los controles nuevos no aparecen.
2. El módulo Ejecución de ambos sectores usa ahora `useOperationSelection` (una línea o varias), `useMachineExecution` (estado lógico) y el mismo `LineSelector`. La máquina/sector se resuelve contra el alcance MF13 del usuario en la API.
3. Con la compuerta ON, una línea solo habilitada permanece visible pero no capturable; solo `in_production` y asignación vigente puede abrir captura.
4. 409 `LINE_NOT_IN_PRODUCTION` en un formulario central candidato también provoca revalidar/cerrar el contexto, sin generar un capture_id nuevo.
5. Con flag OFF, la API devuelve `line_execution=false` y se mantiene la semántica histórica de ejecución. La lectura de capacidad de Supervisión es independiente de `/capabilities` (la forma anterior no cambia).
6. La opción de cerrar OT se habilita solo con todas las líneas `finished`, sin razón textual por déficit ni arrastre automático entre turnos.

## Riesgos aún por verificar antes del GO

- Revisión final de roles MF13 y concesiones reales por máquina para Rebobinado/Conversión.
- Auditoría de asignaciones heredadas `active` sin ejecución lógica: con gate ON se bloquearían; no forzar una promoción automática.
- Migración 0013: rollback y permiso de `vinto_app` en el esquema desplegado.
- Revisión de diferencias con `main` y corrida completa de todas las suites.
- Manual QA productivo con flag OFF primero, luego la secuencia controlada de activación solo bajo E1-09.
- Despliegue VPS, backup y rollback **no ejecutados**.

Este PR es una corrección para eliminar un bloqueante de integración. **No equivale por sí solo al GO de E1-08** y no autoriza un merge ni la activación de la bandera.