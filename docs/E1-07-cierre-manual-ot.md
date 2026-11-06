# VINTO — E1-07 Cierre manual de OT completa por Supervisión

**Dependencias:** E1-02 #118 → E1-03 #120 → E1-04 #122 → E1-05 #124 → E1-06 #126 → **E1-07**.  
**Estado:** candidato en PR DRAFT, sin merge ni despliegue. La compuerta `WORK_ORDER_LINE_EXECUTION_ENABLED` permanece OFF.

## Regla funcional validada con Sergio

- Jefatura crea y programa. Supervisión habilita y empieza cada línea; las finaliza individualmente.
- **Finalizar una línea no cierra automáticamente la OT**: cuando todas estén finalizadas, Supervisión confirma manualmente **Cerrar OT**.
- Una línea puede cerrarse con producción incompleta (ej. 120 KG programados y 90 KG producidos). El déficit de 30 KG se informa en Seguimiento/indicadores. No se exige motivo libre ni se marca el déficit como cancelado.
- No existe pausa. No hay traslado automático de saldos entre turnos.
- La anulación de líneas no iniciadas se definirá en Entrega 3; una línea no iniciada no puede marcarse `finished` sin pasar por producción.

## Backend
- `POST /api/work-orders/{id}/close`, protegido por `assignment.manage`; ni Jefatura ni Operación pueden cerrar.
- Valida compuerta, OT y **todos los sectores de su baseline**; una OT fuera del alcance se trata como inexistente, sin detalle parcial.
- Cierre transaccional: bloqueo OT/baseline → candados de máquinas ordenados → filas de ejecución. Comprueba que **todas** las líneas baseline tengan estado `finished` y ninguna asignación operativa de esa OT siga activa (incluidos turnos antiguos).
- En rechazo `409 WORK_ORDER_CLOSE_PENDING_LINES` devuelve `pending_lines` con códigos seguros de la propia OT visible para Supervisión. En estado incorrecto: `409 WORK_ORDER_CLOSE_INVALID_STATE`.
- Doble cierre autorizado sobre una OT ya `closed` devuelve el mismo detalle sin reescritura; se mantiene el historial, los datos de producción y la auditoría.
- Sin nueva migración: `work_order.status=closed` ya existe en esquema original. No modifica cantidad programada, ni los registros de producción o Calidad.
- Con flag OFF: `422 LINE_EXECUTION_DISABLED` y no toca OT.

## Pantalla de Supervisión
- Progreso `finalizadas / total` según la consulta protegida de E1-05, cotejada con **todos** los IDs/códigos/máquinas de la baseline.
- Botón **Cerrar OT** solo cuando la respuesta confirma que todas las líneas finalizaron y la OT está `in_progress`.
- Confirmación obligatoria con explicación de conservación del déficit; no hay cierre automático ni actualización optimista.
- Los cambios se reconcilian con el backend. El nuevo estado `Cerrada` llega por `GET /api/work-orders`.

## QA / controles
- PostgreSQL 17 aislado: publicado no cerrable; pendientes `planned|enabled|in_production`; cierre de OT multimáquina tras finalizar; bloqueo entre turnos; idempotencia, auditoría, 401/403, compatibilidad flag OFF y carrera cierre versus finalización.
- Node/TypeScript: progreso UI, coincidencia de baseline y proyección, rechazo por línea faltante, duplicada o discrepancia de máquina, sin exigir cantidad producida completa.
- Regresión E1-03, E1-04, E1-05 y E1-06; CI `.github/workflows/e1-07-close-order.yml`.

**NO MERGE / NO DEPLOY / FLAG OFF.** Después de E1-07 completar E1-08 QA integral, especialmente auditoría de rutas de captura adicionales, consistencia de versiones, autorización MF13, escenarios con asignaciones de producción heredadas, pruebas manuales y preflight. Solo E1-09 habilitará despliegue con respaldo y rollback.