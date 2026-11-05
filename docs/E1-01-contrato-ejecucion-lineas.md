# VINTO — E1-01: Contrato de ejecución exclusiva y compatibilidad

**Fecha:** 2026-11-05  
**Proyecto:** BaltrekCompany/vinto-mvp-web  
**Baseline auditado:** `main` / `86e4ec4fa6f6bf95c0e099279d8c51a016c7a6a4`  
**Tipo:** especificación de diseño (sin implementación, sin migración, sin despliegue)  
**Estado:** propuesta técnica para revisión; decisiones pendientes explícitas.

## 1. Fundamento funcional confirmado con Sergio

- Jefatura crea/publica la OT; Supervisión inicia y finaliza líneas, y cierra manualmente la OT; Operación registra capturas sobre la línea efectivamente en producción.
- Una máquina ejecuta **un producto/línea a la vez**. Una misma OT puede tener varias líneas programadas/habilitadas en la misma máquina, pero solo una en producción.
- No existe pausa. Cada línea sigue el flujo iniciar → finalizar.
- Una OT solo puede cerrarse mediante acción manual de Supervisión una vez resueltas todas sus líneas; en esta primera entrega, todas deben estar finalizadas. La anulación de líneas se implementa en Entrega 3.
- Se conservan las protecciones actuales contra asignaciones de OT diferentes en la misma máquina.
- Fuera de esta entrega: reprogramación, notificaciones y anulación.

## 2. Hallazgos del código actual (verificados en el baseline)

| Componente | Estado actual |
|---|---|
| `backend/app/assignments/service.py` | `assignment.status` es `active` o `finished`. `active` significa línea habilitada; `finish` finaliza una asignación para el turno. |
| `backend/migrations/0011_assignment_same_work_order_lines.sql` | Varias asignaciones `active` para líneas distintas de **una misma OT** en una máquina; una OT diferente se bloquea. |
| `backend/migrations/0012_assignment_single_mode_guard.sql` | La restricción condicional protege el modo monolínea cuando la compuerta multimáquina está apagada. |
| `backend/app/work_orders/router.py` | Hay publicación y `activate-all`, pero no existe cierre manual de OT. |
| `backend/app/capture_service.py` | `lock_active_assignment` exige `assignment.status='active'` y turno vigente; falta verificar que la ejecución se inició. Lo usa F3 y F6. |
| `backend/app/bobbins/service.py` | F3 reutiliza `lock_active_assignment` para registrar bobinas. |
| `backend/app/auth/permissions.py` | Supervisión: `assignment.manage`; Jefatura: `work_order.manage`; Operación: `production.capture`. |
| `lib/vinto/assignments-api.ts` | Existe `finishAssignment` como cliente, pero no una acción funcional integral de cierre de línea/OT en UI. |

**Advertencia esencial:** `assignment.status='finished'` indica que una **asignación de turno** terminó (p. ej. vencida/reemplazada), **no prueba** que la línea de negocio terminó definitivamente. No debe usarse por sí sola como estado terminal de la línea.

## 3. Modelo lógico propuesto (E1-01, aún no DDL)

### 3.1. Separar tres conceptos

1. **OT**: `draft` → `published` → `in_progress` → `closed` (estado ya admitido por esquema; falta transición `closed`).
2. **Línea de OT (ejecución lógica de negocio)**: `enabled` → `in_production` → `finished`. La línea programada antes de habilitarse es `planned`. No existe `paused`. Una línea `finished` no se reinicia por una activación de turno. Los estados son una proyección lógica; E1-02 decidirá almacenamiento e índices.
3. **Asignación de turno**: mantener `assignment.status in ('active','finished')` con su significado de habilitación/vigencia y el `assignment_id` histórico utilizado por capturas, para no quebrar claves foráneas ni idempotencia.

### 3.2. Identidad estable

La identidad lógica de ejecución debe asociarse de forma estable a `(work_order_id, line_code)` y máquina **inmutable**, no únicamente a `work_order_line.id` de la versión operativa, porque existe copia versionada de las líneas. Usar una identidad lógica propia de línea o el par inmutable, a resolver en E1-02. No reinterpretar por defecto nuevas versiones de una línea como una nueva producción.

### 3.3. Invariantes

- **I1:** En cada máquina puede existir a lo sumo una ejecución lógica `in_production`; imponer en PostgreSQL y backend con escritura transaccional serializada por el advisory lock existente.
- **I2:** Asignaciones habilitadas de una misma OT pueden coexistir; asignaciones activas de distintas OT sobre la misma máquina siguen prohibidas.
- **I3:** Solo el perfil de Supervisión con alcance efectivo puede iniciar/finalizar ejecución y cerrar OT.
- **I4:** F3/F6 y cualquier endpoint productivo de nueva captura requieren `in_production` para la misma línea, máquina, OT y asignación válida en el turno. La comprobación debe ejecutarse bajo el mismo candado que inicio/finalización.
- **I5:** Un intento de captura nuevo después de `finished` se rechaza; los reintentos *exactamente idénticos* de una captura ya confirmada continúan siendo idempotentes previa verificación de permisos.
- **I6:** Una línea `finished` conserva capturas históricas y no vuelve a `enabled` ni `in_production` mediante otra activación ordinaria.
- **I7:** Cerrar OT requiere todas sus líneas con estado lógico `finished` en Entrega 1, ausencia de ejecución en producción, y confirmación manual de Supervisión. OT `closed` no admite inicio/capturas nuevas.
- **I8:** La migración y la activación gradual no convierten automáticamente en `in_production` las asignaciones `active` actuales. Nunca finalizar registros ni borrar capturas silenciosamente.
- **I9:** No introducir inversión en orden de bloqueos: OT → máquina(s) (ordenadas) → ejecución/asignación, en el camino de cierre y activación; captura máquina → ejecución/asignación. Revisar deadlocks bajo concurrencia real.
- **I10:** Si E1-01 contempla compuerta, que sea distinta de `WORK_ORDERS_MULTI_MACHINE_ENABLED`; apagarla no debe provocar selección o habilitación implícita peligrosa.

### 3.4. Tabla de estados

| Estado | Significado | Puede capturar | Acción de Supervisión |
|---|---|---|---|
| `planned` | Línea publicada aún no habilitada | No | Habilitar por activación existente |
| `enabled` | Asignación de turno habilitada, espera inicio | No | Iniciar |
| `in_production` | Máquina dedicada a esta línea | Sí, si assignment/turno/grants válidos | Finalizar |
| `finished` | Línea concluida definitivamente | No, salvo reintento idempotente ya confirmado | Ninguna ordinaria |

Una asignación puede vencer/cerrar al cambiar turno **sin** que la línea lógica quede `finished`. Los estados deben ser interpretados separadamente.

## 4. Contrato API propuesto (E1-03/E1-07, no existe todavía)

- `POST /api/work-orders/{work_order_id}/lines/{line_code}/start`: Supervisión; idempotente para la misma línea iniciada, 409 si otra línea está en producción en esa máquina, 409 si línea finalizada/no habilitada o OT cerrada; valida grants, turno y contexto, y audita.
- `POST /api/work-orders/{work_order_id}/lines/{line_code}/finish`: Supervisión; idempotente si ya finalizada, rechaza conflictos de estado, captura en curso se serializa por máquina, audita. El contrato de justificación/cantidad pendiente está pendiente de definición funcional.
- `POST /api/work-orders/{work_order_id}/close`: Supervisión; exige todas las líneas `finished`, ejecuta transacción atómica, es idempotente sobre OT `closed`, y retorna 409 con líneas que bloquean el cierre. Su alcance debe cubrir **todas** las máquinas de la OT.
- `GET /api/work-orders/{work_order_id}/execution`: lectura filtrada; estado de cada línea, línea en producción por máquina, fechas, actores y razón de bloqueo; no expone líneas fuera del alcance.

**Importante:** son rutas y respuestas **propuestas**; E1-03 debe aprobar el contrato final y evitar exposición de identificadores no autorizados. No reutilizar `/api/assignments/{id}/finish` como «finalización de línea»: ese endpoint actual tiene semántica de asignación de turno y debe permanecer compatible.

## 5. Preflight y transición segura (E1-02/E1-09)

1. Inventariar por máquina y OT: asignaciones activas, turnos vigentes/vencidos, capturas/bobinas asociadas, y versiones operativas.
2. Revisar de manera explícita las OT de QA existentes (ej. `OT-2026-0018`, `OT-2026-0019`) sin asumir que siguen en el mismo estado. No borrar ni finalizar por SQL.
3. Crear nuevos datos de ejecución sin elevar ninguno a `in_production`; hasta completar la transición, presentar `requires_supervisor_review` para las líneas legadas sin estado efectivo.
4. Preparar dos modos de implementación: migración aditiva compatible y habilitación del **nuevo flujo** solo con la compuerta independiente; el switch no debe causar pérdida de acceso a capturas vigentes sin decisión operacional explícita.
5. Preflight **NO-GO** si existen ejecuciones ambiguas que se mapearían automáticamente, capturas aceptadas sin estado firme, rollback que exige borrar historia, discrepancia de grants, o falta de prueba concurrente.
6. Ensayar restore/rollback de forma aislada; no probar cambios estructurales sobre `vinto_piloto` sin plan y autorización.

## 6. QA requerido

| ID | Escenario | Resultado esperado |
|---|---|---|
| QA-01 | `activate-all` deja L2 y L3 habilitadas en MP3 | Ambas `enabled`, ninguna `in_production` |
| QA-02 | Supervisión inicia L2 | L2 `in_production`, L3 `enabled` |
| QA-03 | Supervisión intenta iniciar L3 | 409, sin escrituras |
| QA-04 | Dos supervisores intentan iniciar L2 y L3 a la vez | Una gana; nunca 2 `in_production` |
| QA-05 | Operación intenta F3/F6 sobre L3 | Rechazo sin capturas ni bobinas nuevas |
| QA-06 | F3 válida sobre L2 | Captura ligada a la asignación, máquina y línea correctas |
| QA-07 | Supervisión finaliza L2 | L2 `finished`; captura nueva bloqueada |
| QA-08 | Supervisión inicia y finaliza L3 | PASS; conserva historia L2 |
| QA-09 | Supervisión intenta cerrar OT con otra línea pendiente | 409 con razón; sin cambios |
| QA-10 | Todas las líneas finalizadas, Supervisión cierra OT | `closed`, auditoría y bloqueo definitivo de nuevas capturas/inicios |
| QA-11 | Jefatura/Operación intentan iniciar/cerrar | 403 (o respuesta no reveladora según alcance) |
| QA-12 | Captura vs finalizar al mismo tiempo | Orden serializado: captura antes del cierre o rechazo; nunca captura nueva después de finalizar |
| QA-13 | Reintento de captura confirmada tras finalizar | Idempotencia histórica, ningún segundo registro |
| QA-14 | Asignaciones legadas con 2+ `active` en máquina | Sin inicio implícito ni pérdida de historia |
| QA-15 | Cambiar turno con línea no terminada | No implica finalización automática de línea; comportamiento operacional debe aprobarse |

## 7. Decisiones aún no cerradas

- **D1 - Cambio de turno:** ¿Una ejecución debe mantenerse lógica y exclusivamente en la máquina cuando el turno termina? ¿Cómo se habilita/captura en nuevo turno sin «pausa» ni cierre definitivo de línea?
- **D2 - Finalización incompleta:** ¿Se exige motivo cuando Supervisión finaliza una línea antes de alcanzar cantidad? ¿Quién registra saldo pendiente cancelado? (Entrega 3 amplía el detalle).
- **D3 - Líneas nunca iniciadas:** Para cerrar OT, ¿Supervisión debe iniciar y finalizar todas, o habrá otro estado de resolución en Entrega 3? En Entrega 1 se exige `finished`.
- **D4 - Corte de transición:** ¿Qué ventana y procedimiento autorizan pasar de habilitación heredada a control de inicio explícito con usuarios reales?

## 8. Alcance de la siguiente implementación

**E1-02:** diseño DDL y migración 0013 (aditiva), preflight/rollback, pruebas PostgreSQL 17, definición del identificador estable de línea. **E1-03:** operaciones de inicio/finalización y API. **E1-04:** integración completa F3/F6/central con captura idempotente. **E1-05–E1-07:** UI Supervisión, Operación y cierre. **E1-08:** QA integral. **E1-09:** despliegue con respaldo, migración, verificación y rollback controlado.

**Estado del documento:** elaborado a partir de código real y acuerdos funcionales; no equivale a aprobación de D1–D4, PR mergeado ni cambio productivo.