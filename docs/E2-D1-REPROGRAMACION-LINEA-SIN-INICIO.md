# E2-D1: reprogramacion aislada de linea sin historial en OT in_progress

**Estado: desarrollo; NO autorizado para produccion.** Sin migraciones. Flag WORK_ORDER_REPROGRAM_UNASSIGNED_IN_PROGRESS_ENABLED=false por defecto.

## Contrato
- Endpoint separado del E2-B: POST /api/work-orders/{id}/lines/{line_code}/reprogram-unassigned-in-progress; requiere work_order.manage.
- Solo OT in_progress, sin archivo ni retiro QA, con una asignacion activa de otra linea.
- La linea objetivo no puede tener ninguna asignacion historica, ni estado E1 previo, ni capturas.
- Snapshot operativo completo y nuevo, solo append. Baseline, snapshots anteriores, capturas y asignaciones inmutables.
- expected_version y campos anteriores exigidos. Maquina y line_code inmutables.
- Re-activar una linea logica sin cambios en el mismo turno no debe crear otra asignacion solo porque cambio el ID de su snapshot.
- Avisos de E2-C2 existentes; D1 no habilita D2/D3 ni altera control de capturas.

## Puertas de cierre
1. PG17: nuevas pruebas, asignaciones, E1, E2-D0, permisos y API.
2. Concurrencia real: revision versus activacion y vs inicio de captura.
3. Cambios de turno, modo multimaquina OFF/ON, historiales legacy y lineas terminadas.
4. Asegurar que no se reemplazan asignaciones de otras lineas y que los avisos E2-C1/C2 conservan trazabilidad.
5. Auditar versionado y bloqueos contra deadlocks; no fusionar ni desplegar antes de PASS.
