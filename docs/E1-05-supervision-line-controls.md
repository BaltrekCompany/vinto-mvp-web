# E1-05 — Interfaz de Supervisión: inicio y finalización por línea

**Estado:** candidato en PR borrador, sin merge ni despliegue.  
**Dependencias apiladas:** E1-02 PR #118 → E1-03 PR #120 → E1-04 PR #122 → **E1-05**.

## Flujo para Supervisión

1. Jefatura publica la OT con una o varias líneas por máquina.
2. Supervisión pulsa «Habilitar» en cada línea o «Habilitar todas las líneas» para la OT. Habilitar **no inicia producción**.
3. Cada línea aparece como Programada, Habilitada, En producción, Finalizada o Requiere revisión; el estado y la asignación del turno se obtienen directamente del servidor.
4. Solo se ofrece «Iniciar línea» cuando está habilitada, tiene asignación vigente y ninguna otra línea de esa máquina produce.
5. «Finalizar línea» exige confirmación. Conserva la producción real (incluso incompleta), no solicita motivo obligatorio y **no cierra automáticamente la OT**.
6. Una línea antigua `active` sin fila lógica de ejecución requiere revisión; nunca se interpreta como producción confirmada.

## Contratos

- `GET /api/work-orders/capabilities`: ahora también `line_execution: bool`, a partir de `WORK_ORDER_LINE_EXECUTION_ENABLED` (OFF por defecto). Los clientes antiguos siguen aceptando `multi_machine`.
- `GET /api/work-orders/{ot_id}/execution`: solo `assignment.manage` (Supervisión), datos del estado lógico por línea, máquina y `current_assignment_id` cuando coincide con el turno actual. **Si la OT abarca varias máquinas, el actor debe tener alcance sobre todas**; nunca se filtra silenciosamente a una vista parcial.
- Acciones ya implementadas en E1-03: `POST /api/work-orders/{ot_id}/lines/{line_code}/start` y `/finish`.

### Protección del frontend
- No se renderizan controles E1-05 si el servidor no confirma `line_execution: true` o falta permiso `assignment.manage`.
- Cada solicitud se valida en backend. El frontend no concede autorización ni deduce «En producción» de `assignment.active`.
- Estado separado por OT y sesión, sin almacenar credenciales ni optimismo; la confirmación de cambios solo ocurre tras respuesta del servidor.
- Botones bloqueados mientras se recargan estados, no hay asignación vigente o una línea ocupa esa máquina.
- Respuestas de error 401/403/409/422 generan mensaje seguro y revalidación.

## Criterios funcionales de Sergio (5 de noviembre)
- **Sin pausa**.
- **Sin motivo obligatorio por déficit**; 120 planificados / 90 producidos ⇒ déficit 30 en Seguimiento; no equivale a saldo cancelado.
- **Sin arrastre automático entre turnos**; Jefatura puede registrar otra OT manual y Supervisión debe liberar explícitamente la ejecución anterior.
- El cierre manual completo de la OT corresponde a **E1-07**.

## QA
- Node: parser/estados/roles/capacidades antiguas + nuevas, botones y errores.
- PostgreSQL 17 aislado: proyección, turnos, scope por sector, asignaciones legadas, flag OFF y regresiones E1-03/04.
- TypeScript y ESLint de archivos afectados.
- Workflow `.github/workflows/e1-05-supervision.yml`.

**NO MERGE / NO DEPLOY / FLAG OFF** hasta E1-06 a E1-09 y QA integral.