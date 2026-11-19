# VINTO OFF-04.5A — Calidad offline de punta a punta (laboratorio sintético)

**Estado:** candidato de ensayo aislado, PR Draft apilado sobre #235. Seguimiento: #236.
**Solo identidades, capturas, contextos y autorizaciones sintéticos.** No conecta el outbox operativo, no habilita captura industrial, no cambia permisos ni paquetes de solo lectura, no registra rutas operativas, no aplica migraciones y no toca PostgreSQL real, VPS, Docker, Nginx, firewall, SEC-HOST-01 ni OFF-04.2-R3.

## 1. Auditoría (Fase A)

- **Base:** el SHA indicado (`975acede…`) no existe en el clon de trabajo; se construyó sobre la rama local de OFF-04.4 (`62aed871f7b49c956f1681d2cb7ada4d3ea669b7`), que debería ser lo que contiene #235. **Verificar la base antes de publicar.** No se pudo leer el Issue #236.
- **Piezas integradas** (sin reescribirlas): editor y borradores cifrados (OFF-04.1/04.2-R2: `offline-draft-store`, `offline-lab-db`), pendiente local inmutable (`offline-lab-queue`), cola y motor de sincronización de pruebas (OFF-04.3), adaptador HTTP y receptor FastAPI (OFF-04.4).
- **Elección del formulario candidato — P1-22 «Grado de refinación Schopper»** (seed `backend/seed_data/forms/VINTO-P1-22.json`):

| | P1-18 Porcentaje de consistencia | **P1-22 Schopper** |
|---|---|---|
| Campos | 10 (producto, cuba, hora, 2 masas, % consistencia, 3 de papel, observaciones) | **5** (cuba, masa húmeda, grado SR, amperaje, observación) |
| Tipos | text, time, decimal, textarea | **text, decimal, textarea** |
| Obligatorios | 8 | **4** |
| Calculados / opciones | ninguno en el seed (el % de consistencia figura como manual, probable fórmula pendiente) | **ninguno / ninguna** |
| Dependencias | posible relación masa seca/húmeda ↔ % consistencia, **sin regla publicada** | **ninguna** |

  Se eligió **P1-22**: menor superficie, sin tipos ni reglas sin contrato (hora, fórmula), y todos los campos son de ingreso manual. La definición del laboratorio (`definition_p122` en `scripts/off04_fixture.py`) replica claves, tipos y obligatoriedad del seed, se marca `SINTÉTICO…` / `Synthetic QA-only…`, la firma el firmador real y **no se declara homologada**: rangos, unidades, precisión y reglas entre campos **no existen en el seed y no se inventan**.
- **Restricciones intactas:** `capture_eligible=false` / `captures_enabled=false`; la definición se edita solo porque es sintética; el receptor sigue deshabilitado por defecto y fuera de `app.main`.

## 2. Flujo (Fase B) — `lab/offline-e2e-lab.html` + `lib/vinto/offline-quality-e2e-lab.ts`

Página de laboratorio, solo con `OFFLINE_DRAFT_LAB=1` (ausente en builds normales, sin enlace desde la app, no precacheada). Funciona **sin conexión** desde el Service Worker.

1. Abrir el formulario sin Internet (desbloqueo con la frase del **perfil original** + confirmación de datos sintéticos).
2. Registrar datos sintéticos → 3. **borrador cifrado** («Guardado localmente») → 4. validaciones (un borrador incompleto se guarda pero no puede convertirse) → 5. **pendiente local inmutable** (contenido congelado).
6. **Incorporación explícita** a la cola del motor de pruebas (botón «Incorporar a la cola de sincronización», solo sobre pendientes; ningún paso lo hace solo): crea un registro de `sync_queue` con el **mismo `capture_id`** derivado (propietario+navegador+borrador), el contenido congelado, el autor original y las referencias de formulario/versión/máquina/snapshot (`context_version` = snapshot firmado).
7–9. Cerrar y reabrir sin conexión, desbloquear el perfil original y recuperar borradores, pendientes y cola.
10–12. Simular la reconexión; **reautenticar al autor original** (selector de sesión: válida / vencida / otro usuario; el motor pausa con las dos últimas, sin cambiar nada); **«Sincronizar ahora»** con el motor OFF-04.3.
13–15. Envío al receptor FastAPI aislado (OFF-04.4) por **un único `fetch` a un receptor loopback** indicado en `?receiver=` (validado: `http`, `127.0.0.1`/`localhost`, sin ruta); sin él la sincronización no está disponible y nada sale del dispositivo. El estado visible se actualiza con la respuesta verificada.

## 3. Interfaz (Fase C)

Cada captura muestra su etapa y un texto claro: **Guardado localmente** (borrador) · **Pendiente local — NO sincronizado** · **Pendiente de sincronización** (`queued`/`retry_wait`) · **Sincronizando…** · **Sincronizado: recepción técnica confirmada (NO es aprobación industrial)** · **Sincronizado con advertencia** · **Requiere revisión** · **Conflicto**. Contadores por etapa, «Sincronizar ahora» y reloj simulado (+60 s) solo en el laboratorio. El banner y los textos distinguen **guardado local ≠ recepción técnica ≠ aprobación industrial**; no hay botones de aprobar, liberar, eliminar ni exportar.

## 4. Pruebas extremo a extremo (Fase D)

`scripts/off-04-5a-quality-e2e-browser.py`: Chrome real contra el **receptor FastAPI descartable sobre una base PostgreSQL `*_test` desechable** (`OFF044_PG_URL` en CI; localmente una instancia efímera de usuario). Verifica además que `capture_id` es la derivación estable esperada y que **ninguna solicitud sale** salvo al servidor de desarrollo y al receptor loopback.

Cubre los 16 escenarios pedidos: captura completa sin conexión; borrador incompleto; cierre y reapertura offline con recuperación y perfil original; sincronización exitosa; **respuesta perdida tras persistir** (el servidor la guardó, el navegador no la vio) y **reintento sin duplicados** (conciliación por GET, **una sola entrega** al servidor); **dos pestañas simultáneas** (una entrega, un registro); otro usuario autenticado; sesión vencida; contexto cambiado (⇒ `synced_warning`); captura rechazada (⇒ `conflict`); captura en revisión (⇒ `requires_review`); interrupción de red (nada llega al servidor, el pendiente se conserva); **fallo de almacenamiento** durante la sincronización (se recupera sin perder nada); confirmación única (una fila por captura y una entrega por captura, comprobadas en la base y en la bitácora append-only); conservación de pendientes ante todos los errores.
`scripts/off-04-5a-e2e-static.test.mjs` fija los contratos estructurales (lab-only, un solo `fetch` loopback, puente explícito con mismo `capture_id`, siete estados visibles, nada operativo lo referencia).
**Mutaciones de control (detectadas):** motor sin conciliación previa (falla «sin duplicados»); puente que genera un `capture_id` nuevo; «otro usuario» tratado como el autor.
Regresiones: OFF-02 a OFF-04.4 (Node, Chrome, pytest), `tsc`, ESLint (56 avisos, sin cambios) y compilación normal sin laboratorio.
**Nota de entorno:** la ejecución local usó PostgreSQL **16.2** (instancia efímera sin Docker); el flujo de CI usa **PostgreSQL 17** como servicio.

## 5. Preparación del piloto físico — requisitos mínimos de OFF-04.5B (no ejecutado)

1. **Formulario de Calidad homologado:** definición publicada y aprobada por Calidad, con rangos, unidades, precisión, fórmulas (si las hay) y dependencias explícitas (hoy P1-22 es solo un candidato sintético sin esas reglas).
2. **Autorización real de captura offline:** concesión máquina/formulario del motor `authz` aplicada por el receptor (hoy: interfaz con implementación sintética y autorizador por defecto que deniega todo); el contrato de captura offline aprobado distinto del de solo lectura; revocación efectiva al sincronizar.
3. **API QA privada validada:** receptor montado en el entorno QA tras una bandera, detrás del guard de escrituras de QA (no verificado aquí: el middleware de #219 no está en este clon), con CORS/CSRF y sesión real (`current_user`), y **migración `vinto_offline` revisada y autorizada** (propuesta en `backend/offline_capture_migration/`, no aplicada).
4. **Identidad sintética de prueba y controles de acceso:** operario y dispositivo sintéticos dedicados, alcance firmado de una sola máquina, sin datos reales, sin privilegios industriales más allá del formulario de ensayo; registro de quién ejecuta el piloto.
5. **Dispositivo móvil físico:** navegador real de planta (cuota de almacenamiento, persistencia concedida, bloqueo de pantalla, suspensión, batería) y prueba de la instalación/precarga del Service Worker.
6. **Verificación de cierre/reinicio y reconexión en el dispositivo:** cierre forzado del navegador y reinicio del teléfono con pendientes, apagado de red a mitad de envío, cambio de red/cambio de usuario.
7. **Validación de persistencia y conciliación en QA:** una sola captura lógica por `capture_id` en la base QA, respuesta perdida reconciliada, bitácora de eventos revisada, sin efectos sobre órdenes, asignaciones ni stock.
8. **Procedimiento de desactivación y recuperación:** bandera para apagar el receptor y la página de laboratorio, qué hacer con pendientes `requires_review`/`conflict`, copia y restauración de la base `vinto_offline`, y retorno a «solo consulta» sin pérdida de datos locales.

## 6. Observaciones secundarias (sin ampliar el alcance)

- La interfaz de este laboratorio duplica el renderizado de campos del editor de borradores (extraerlo a un módulo común es una limpieza posterior).
- La sesión «en línea» es un selector sintético y el receptor recibe un encabezado de prueba; la integración con cookie de sesión real y la reautenticación guiada del autor original son trabajo de OFF-04.5B.
- `context_version` se deriva del snapshot firmado; la evaluación de contexto industrial real (OT/asignación/turno, OFF-01 §6) sigue sin existir.
- Sin flujo de resolución de `requires_review`/`conflict`, retención ni exportación; sin límite de pendientes; sin QA físico del móvil.
- Heredado: restauración local de estados antiguos sin ancla externa (fuera del alcance acordado de OFF-04.2-R3); el guard QA de #219 no se pudo contrastar.
