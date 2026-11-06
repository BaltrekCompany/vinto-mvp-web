# VINTO — E1-06: pantalla de Operación basada en ejecución real

**Estado:** candidato, DRAFT / NO DEPLOY / FLAG OFF.  
**Cadena:** E1-02 #118 → E1-03 #120 → E1-04 #122 → E1-05 #124 → E1-06.

## Requisito de Sergio

Una máquina produce un solo producto/línea simultáneamente. Supervisión **habilita** varias líneas de una OT y **inicia** únicamente la que debe producirse. Operación solo registra nuevas capturas F3/F6 en esa línea. La siguiente línea espera a que Supervisión finalice expresamente la anterior. No hay pausa. No existe arrastre automático de cantidades entre turnos ni motivo obligatorio para déficit.

## Implementación

**Backend**
- Nuevo `GET /api/assignments/execution-status?machine_code=MP3`, con `assignment.read` y comprobación MF13 de máquina/formulario del usuario cuando el modo nuevo está ON. No reemplaza `/active` ni `/active-lines`.
- Con compuerta `WORK_ORDER_LINE_EXECUTION_ENABLED=false` (valor por defecto), devuelve `{ "line_execution": false, "assignments": [] }` y **no consulta** la tabla 0013 ni añade restricciones al flujo legado.
- Con compuerta ON, devuelve estados por `assignment_id` de asignaciones activas de la máquina concedida, basados en la **línea baseline de la OT**. Una asignación activa sin ejecución lógica pasa a `requires_review`; jamás se presume `in_production`.
- GET de solo lectura, `Cache-Control: private, no-store`. No expone datos de otra máquina o sesión.
- F3/F6 conservan el control transaccional del E1-04 (POST siempre valida estado con la base de datos; el GET no concede permiso).

**Frontend**
- Recurso independiente por **sesión + máquina**, sin estado optimista; se refresca al cambiar selección, después de capturar, al volver al navegador y ante un 409.
- Selector de Operación conserva todas las líneas habilitadas, pero muestra claramente `Habilitada · pendiente de inicio`, `En producción` o `Requiere revisión`. Solo `in_production`, asignación vigente, es seleccionable.
- Con una sola línea el contexto de captura igualmente depende del inicio por Supervisión, no de `assignment.active`.
- Si falta/fracasa la consulta o cambia la máquina/turno, **no se abre una nueva captura**. Reintentos idénticos con `capture_id` previo conservan su ruta idempotente.
- Cuando F3/F6 reciben `409 LINE_NOT_IN_PRODUCTION`, se muestra un aviso específico y se actualiza el contexto; no se repite con un identificador distinto.
- Con la compuerta OFF el selector conserva su comportamiento anterior.

## Pruebas y No-Go

- Contratos puros Node: parseo, modo legado, líneas iniciadas/no iniciadas, selección y códigos F3/F6.
- PostgreSQL 17: habilitación masiva, inicio, finalización, contexto por turno, asignación antigua, alcance de máquina y grants por formulario.
- Regresión completa E1-03 y E1-04, pruebas existentes de selección PR8, TypeScript y ESLint.
- CI: `.github/workflows/e1-06-operation.yml`.
- **Fuera de alcance E1-06:** otras familias de formularios de producción no protegidas por E1-04, cambios en Calidad/Rebobinado/Conversión, cierre manual de OT (E1-07), traslado de saldos entre turnos. E1-08 debe auditar rutas de captura adicionales antes de considerar el flujo integral liberable.
- **No activar ni desplegar** hasta E1-07/E1-08/E1-09 y aprobación del QA integral.