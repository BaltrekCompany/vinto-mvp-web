# MF13-03.B PR8 — Operación: selección segura de línea activa

Base: `origin/main` 8af5773 (PR #111, migración 0012, fusionado). Solo frontend de Operación (Bobinas · Ejecución) y pruebas. **No cambia ningún endpoint, contrato HTTP, migración, F3, F6, Calidad, AUTHZ ni compuertas.** La compuerta multimáquina sigue apagada.

## 1. Auditoría (Fase A)

| Tema | Hallazgo |
|---|---|
| Flujo de Operación | `app/page.tsx` (Bobinas · Ejecución) leía `GET /api/assignments/active` (`useActiveAssignment`) y construía el contexto de captura con `contextFromActive`. Cada formulario (F3, P1-06, candidatas) recibe `CaptureContext.assignmentId`. |
| Con una sola activa | `/active` devuelve la asignación, el turno vigente y `stale`. Sin pasos extra. Es el flujo histórico. |
| Con varias activas (misma OT, compuerta encendida) | `/active` responde **409 `MULTIPLE_ACTIVE_ASSIGNMENTS`** (no elige una al azar). Antes de PR8 la pantalla mostraba el error y **no había forma de capturar**. |
| Backend ya listo | `GET /api/assignments/active-lines` (todas las activas de la máquina, cada una con `stale`; alcance por `visibility.operational_scope`, PR5) y `GET /api/assignments/operational-lines` ya existen. La captura se identifica por `assignment_id` y `lock_active_assignment` revalida bajo el lock de la máquina: asignación existente y visible, `active`, máquina activa, OT no cerrada y turno/fecha vigentes (`AssignmentNotActive` / `AssignmentStale`). El permiso máquina-formulario lo decide la compuerta (`authz_bobbin_production_mode`) por la máquina **de la asignación**, nunca la del cliente. |
| Resolución de OT/línea/máquina/turno | Todo lo resuelve el servidor (OT y línea por la asignación operativa; máquina por la línea; turno y fecha por `resolve_shift` con el reloj de PostgreSQL). El cliente solo envía `assignment_id`. |
| Otros consumidores de `/active` | `sector-central.tsx` (Rebobinado y Conversión). **No se tocan** (ver §6). |

Conclusión: **PR8 no necesita cambios de backend ni de contrato.** No hay dependencia estructural con otros módulos.

## 2. Diseño (Fase B)

- **Compuerta apagada / una sola línea activa / ninguna:** exactamente el flujo histórico. Misma solicitud (`GET /active`), mismo contexto, **ningún paso adicional**. Una prueba fija que son una sola solicitud y que no se llama a `/active-lines`.
- **Varias líneas activas:** la lectura recibe 409 `MULTIPLE_ACTIVE_ASSIGNMENTS` en `/active` y **solo entonces** pide `/active-lines`. El operario ve el selector «Líneas activas en MPx» con, por línea: OT, línea, producto, código, PV, máquina, turno, fecha y cantidad programada.
  - **No se preselecciona nada** y no hay contexto de captura hasta que se elige («Hay varias líneas activas en esta máquina: elige la línea que vas a capturar.»).
  - Una línea vencida (otro turno/fecha) o sin turno resoluble aparece **deshabilitada** con su motivo.
  - Solo se ofrece lo que el servidor devolvió para esta sesión y máquina (autorizado por PR5); el cliente no filtra ni amplía.
- **La selección es derivada, no un estado que haya que "limpiar":** se guarda `{sesión:máquina, assignment_id}` en memoria y se valida en cada render contra la lectura vigente (`validSelection`). Deja de valer, sin efectos ni temporizadores, si: cambia la máquina o la sesión, la línea ya no está activa (finalizada), cambia el turno/fecha (vencida) o no se puede resolver el turno. Entonces hay que elegir de nuevo.
- **Capturas:** el `CaptureContext` de la línea elegida lleva su propio `assignmentId`; F3/P1-06 y las candidatas no cambian. La selección **no autoriza**: el backend vuelve a validar sesión, alcance, permiso máquina-formulario, vigencia y turno en cada envío. Si la línea se finaliza o vence mientras el operario llena el formulario, el backend responde `AssignmentNotActive/Stale`, los formularios ya existentes llaman a `onAssignmentChanged` y la pantalla vuelve a leer: la línea desaparece o queda deshabilitada y la selección caduca.
- **Respuesta tardía / otra sesión o máquina:** la clave del recurso (`operation-selection:<sesión>:<máquina>`) hace que `deriveView` jamás muestre un resultado guardado bajo otra clave.
- **Doble envío / idempotencia:** sin cambios; la ejerce el `capture_id` y los intentos de cada formulario (probado en backend, §4).
- **Sin almacenamiento:** nada de `localStorage`, `sessionStorage`, cookies ni `console` en los módulos nuevos (verificado por pruebas de fuente).

## 3. Contratos

Reutilizados sin cambios: `GET /api/assignments/active`, `GET /api/assignments/active-lines`, captura con `assignment_id`.
Nuevo en cliente (sin contrato de red nuevo): `getActiveLines`, `getOperationSelection` (`lib/vinto/assignments-api.ts`), `parseActiveLines` estricto (valida forma, `stale` booleano/nulo, asignaciones repetidas), `useOperationSelection` (hook), `operationSelectionKey`.
`ContextCheck` gana la razón `unselected` (mensaje propio); `contextFromActive` no cambia.

## 4. Archivos y pruebas

- `lib/vinto/active-lines.ts` (puro), `components/vinto/line-selector.tsx`, `lib/vinto/assignments-api.ts`, `lib/vinto/use-central.ts`, `lib/vinto/resource-view.ts`, `lib/vinto/orders.ts` (razón `unselected`), `app/page.tsx` (cableado), `scripts/int-02a-stubs/use-central.ts` (stub del hook).
- `scripts/pr8-line-selection.test.mjs` (15): parser con asignaciones **reales** de la API (fixtures de PR4) y variantes malformadas; selección derivada (nunca automática, caduca por máquina, sesión, finalización, turno/fecha, turno no resoluble); cliente con `fetch` simulado (una solicitud en el flujo histórico; `/active-lines` solo con `MULTIPLE_ACTIVE_ASSIGNMENTS`; 403/404/401/500/otro 409 sin fallback; `/active-lines` fallido o malformado = fallo, nunca selección; carrera que deja una línea = contrato histórico); render del selector; cableado y ausencia de almacenamiento. Tres mutaciones (ignorar la clave, permitir líneas vencidas, tratar 2 líneas como una) rompen pruebas.
- `scripts/page-scope.test.mjs`: una aserción actualizada (el nombre del hook que fija «Calidad no consume la asignación central»; la intención —solo Bobinas · Ejecución— se mantiene).
- `backend/tests/test_pr8_operation_lines.py` (8, sin cambios de backend): cada línea elegida se captura contra **su** asignación; línea de otro turno/fecha = `AssignmentStale` sin escribir; línea finalizada mientras se prepara = `AssignmentNotActive` y su hermana sigue funcionando; capturas concurrentes sobre dos líneas; doble envío concurrente con el mismo `capture_id` = una captura; captura frente a finalización (guardada o rechazada, nunca a medias); sin concesión = `AuthorizationDenied` en cualquier línea; concesión revocada tras elegir la línea = bloquea la siguiente captura y conserva la guardada.

## 5. Evidencia visual

`docs/MF-13-03B-PR8-evidencia/`: `01` varias líneas sin selección, `02` línea elegida con su contexto, `03` línea vencida deshabilitada, cada una en escritorio y móvil (390 px). Son una **composición estática** del marcado real de los componentes con el CSS compilado (Chrome headless, tema claro), no una sesión de navegador.
**Límite explícito: no hay E2E real.** No se ejercitaron clics, el foco ni la red en vivo.

### Validación manual pendiente (compuerta encendida solo en un entorno aislado)
1. Operación con una sola línea activa: sin selector, captura como antes.
2. Con dos líneas activas de la misma OT: aparece el selector, ninguna marcada, no se puede abrir F3/P1-06 hasta elegir.
3. Elegir L2, capturar: la captura queda con la asignación de L2 (verificar en la lista central).
4. Finalizar L2 desde Supervisión mientras el formulario está abierto: el envío es rechazado y al volver hay que elegir de nuevo.
5. Cambio de turno: las líneas pasan a deshabilitadas; Supervisión reactiva; hay que elegir de nuevo.
6. Revocar la concesión máquina-formulario con `authz_bobbin_production_mode=enforce` (entorno aislado): el siguiente envío da 403.
7. Teclado y lector de pantalla: `fieldset/legend`, radios nativos, «Actualizar líneas».

## 6. Riesgos y pendiente

1. **Rebobinado y Conversión** (`sector-central.tsx`) siguen con `/active`: con varias líneas activas verían el error 409 (falla segura, sin capturar), no el selector. Integrarlo es una decisión aparte; no se afirma aquí.
2. Con la compuerta apagada pero un estado heredado con varias activas, Operación ahora muestra el selector en lugar de un callejón sin salida; las capturas se siguen validando en backend igual que siempre.
3. Sin E2E de navegador (ver §5).
4. La activación de la compuerta sigue siendo una decisión operativa del propietario; este PR no la habilita.
