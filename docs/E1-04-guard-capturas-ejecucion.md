# VINTO E1-04 — Capturas vinculadas a ejecución de línea

**Dependencias:** E1-02 #118 (SQL 0013), E1-03 #120 (inicio y finalización de línea).  
**Estado:** candidato en PR DRAFT; sin cambios en producción.

## Decisión funcional aplicada (Sergio, 2026-11-05)

- Una sola línea `in_production` por máquina.
- Una línea finalizada puede tener un **déficit de cantidad** (120 solicitado, 90 producido, déficit 30), sin motivo textual obligatorio; esto se reporta en Seguimiento y KPI, no bloquea la finalización.
- Continuar el mismo producto en otro turno es operativamente posible, pero **no arrastrar automáticamente** cantidades ni fechas. Para el MVP, Jefatura registra manualmente una nueva OT/programación si requiere continuar. Se conserva en backlog la alternativa de traspaso automatizado si más adelante agrega valor.
- La diferencia programado-real **no se convierte automáticamente en «cancelado»**. La cancelación expresa corresponde a Entrega 3.
- Antes de iniciar una nueva OT en una máquina, Supervisión debe finalizar explícitamente la línea en producción de la OT anterior y cerrar la OT cuando todas sus líneas estén concluidas; sin cierre implícito.

## Implementación

Se agrega una verificación al guard compartido `capture_service.lock_active_assignment()`, reutilizado por F3 y F6:

1. Se bloquea la máquina, se valida estado de asignación y turno vigente (sin cambios).
2. Con `WORK_ORDER_LINE_EXECUTION_ENABLED=true`, se une la asignación operativa a su línea baseline por OT, código de línea y máquina.
3. Se exige `work_order_line_execution.status='in_production'` y se toma `FOR SHARE OF e` bajo el lock de máquina, serializando captura vs. finalización.
4. Si no hay ejecución, la línea está solo `enabled` o ya finalizó, se rechaza la **captura nueva** con `409 LINE_NOT_IN_PRODUCTION` (o error específico de asignación terminada).
5. Si el capture_id ya tiene una captura confirmada **idéntica**, el sistema devuelve el mismo resultado histórico y no pasa por el guard de nueva captura; mantiene la comprobación de autorización existente. Cambiar el contenido o autor no permite el reintento.
6. Con la compuerta OFF, el flujo anterior sigue igual; no se consulta `work_order_line_execution` en nuevas capturas.

**Cobertura:** F3 y todos los formularios centrales de producción que utilizan este guard compartido; no altera por sí mismo rutas de Calidad.

## Pruebas

`backend/tests/test_capture_line_execution_guard.py` (PG17 aislado):
- F3/F6: antes del inicio, durante producción y después de finalizar.
- Bloqueo de L2 habilitada mientras L1 produce.
- Idempotencia histórica F3/F6 después de finalizar L1.
- Línea heredada `active` sin ejecución lógica: NO se promueve ni permite capturar bajo bandera.
- Bandera OFF: compatibilidad.
- Captura simultánea a finalización de línea: serialización, sin captura posterior al cierre.

GitHub Actions `.github/workflows/e1-04-postgres17.yml` ejecuta la nueva suite y regresiones históricas F3/F6 y E1-03.

## NO-GO productivo

La compuerta **permanece OFF** hasta concluir E1-05/06 (interfaces), E1-07 (cierre de OT), E1-08 (QA integral) y E1-09 (preflight y transición segura de OT activas). Una migración aditiva sin la interfaz de inicio no autoriza bloquear las capturas productivas.