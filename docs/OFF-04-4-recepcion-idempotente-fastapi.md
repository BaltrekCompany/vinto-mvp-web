# VINTO OFF-04.4 — Recepción idempotente y conciliación central (receptor FastAPI aislado)

**Estado:** candidato de ensayo aislado, PR Draft apilado sobre #233. Seguimiento: #234.
**Solo identidades, capturas y contextos sintéticos.** El receptor **no está registrado** en la aplicación operativa, está **deshabilitado por defecto**, no aprueba/libera/modifica órdenes ni registros industriales y no habilita sincronización real. Sin cambios en PostgreSQL real, VPS, Docker, Nginx, firewall, permisos, paquetes de solo lectura, SEC-HOST-01 ni OFF-04.2-R3.

## 1. Auditoría (Fase A)

- **Base:** el SHA indicado (`2cf95e4c…`) no existe en el clon de trabajo; se construyó sobre la rama local de OFF-04.3 (`30060a18126744ab59314727ea586820e58f1dcd`), que debería ser lo que contiene #233. Los cambios al motor son mínimos y aditivos (campos opcionales); la rama nueva es `feat/off-04-4-fastapi-sync-contract`. **Verificar la base antes de publicar.**
- **FastAPI existente:** psycopg directo (sin ORM), autenticación por cookie de sesión (`app.auth.dependencies.current_user` → `AuthenticatedUser`), conexiones breves por petición (`app.database`), enrutadores incluidos en `app.main`, módulo `offline_scope` (alcance/paquetes firmados de solo lectura; sin rutas de captura offline). Migraciones numeradas `NNNN_*.sql` descubiertas por `migrate.py`.
- **Guard QA de #219:** su middleware **no está presente** en este clon (no hay ningún middleware de escritura en `app.main`), por lo que no se pudo revisar ni se tocó. El receptor es compatible con él por construcción: no se registra en `app.main`; si el guard bloquea escrituras en QA, un receptor no montado ni siquiera existe.
- **Paquetes readiness-only:** `capture_eligible=false` / `captures_enabled=false` no se modifican. El autorizador por defecto del receptor **deniega todo**, y un snapshot de solo consulta **nunca** autoriza una captura (`read_only_scope`), aunque existan concesiones.
- **Contratos reutilizados:** forma de `SyncRequest`/`SyncReply`/`LookupReply` de OFF-04.3, estados OFF-01 §8, `AuthenticatedUser` y `current_user`, guardas de base de pruebas (`db_guard.assert_test_database`). Nada de `captures`, `work_orders`, `assignments` ni del motor `authz` se importa ni se modifica.

## 2. Contrato HTTP

### `POST /api/offline/captures` (idempotente por `capture_id`)
Cuerpo (`extra=forbid`; ningún campo puede pedir aprobación): `capture_id`, `author_user_id` (autor **original**, inmutable), `device_key`, `form_code`, `form_version`, `machine_code`, `scope_snapshot_id?`, `context_version`, `payload_sha256`, `payload` (JSON de escalares: cadenas/booleanos/enteros; los decimales viajan como texto). Hash canónico = SHA-256 del JSON compacto de claves ordenadas, idéntico en TypeScript y Python (vectores compartidos).

| Situación | HTTP | `outcome` / `reason` | Estado del motor |
|---|---|---|---|
| Primera recepción aceptada | 201 | `created` (+ `warnings` si el contexto cambió de forma compatible) | `synced` / `synced_warning` |
| Duplicado idéntico | 200 | `duplicate`, mismo `server_id` y respuesta persistida | `synced` |
| Contexto incompatible / no verificable | 202 | `review` · `context_incompatible` / `context_unverifiable` | `requires_review` |
| Mismo `capture_id`, otro contenido | 409 | `conflict` · `payload_mismatch` | `conflict` |
| `capture_id` de otro autor | 409 | `conflict` · `author_immutable` | `conflict` |
| Checksum declarado ≠ payload | 409 | `conflict` · `integrity_mismatch` | `conflict` |
| Versión de formulario incompatible | 409 | `conflict` · `form_version_incompatible` (persistido) | `conflict` |
| Valor no soportado (decimal) / cuerpo inválido | 422 | — | `conflict` |
| Usuario autenticado ≠ autor original | 403 | `author_mismatch` | `requires_review` |
| Sin concesión industrial / snapshot de consulta | 403 | `capture_not_authorized` / `read_only_scope` | `requires_review` |
| Sin sesión / sesión vencida | 401 | — | pausa `auth_required` |
| Almacenamiento no disponible | 503 | `receiver_unavailable` | `retry_wait` |
| Receptor deshabilitado | 404 | `Recurso no disponible` | `retry_wait` (nunca `synced`) |

Toda respuesta incluye `technical_acceptance` e `industrial_approval` (**siempre `false`**): la aceptación técnica **no** es aprobación industrial.

### `GET /api/offline/captures/{capture_id}` (conciliación)
200 `{found:true, outcome: accepted|accepted_warning|review|conflict, capture_id, payload_sha256, server_id, warnings, reason, technical_acceptance, industrial_approval:false}`; 404 `{found:false}` si no existe **o no pertenece al usuario** (no filtra existencia); 401 sin sesión; 503 si no se puede decidir. Solo el autor original puede consultar su captura.

## 3. Fases separadas del receptor (`service.py`)
1. **Recibir:** forma + checksum. 2. **Autorizar:** identidad autenticada = autor original; autorización de captura por `CaptureAuthorizer` inyectado. 3. **Persistir** de forma idempotente en **una transacción**. 4. **Evaluar contexto** solo de una captura recién persistida (`ContextProvider`; nunca altera lo almacenado). 5. **Conciliar:** resultado y respuesta **persistidos** en la misma transacción y reutilizados tal cual en los reintentos. Por defecto: `DenyAllAuthorizer` y `UnverifiableContext` (nada se acepta sin autoridad probada).

## 4. Persistencia idempotente
- **Contrato** (`store.py`): `insert_received` atómico por `capture_id` (un insert concurrente espera al otro y reporta «ya existe»); identidad de **escritura única**; `finalize` una sola vez dentro de la transacción del insert (una fila confirmada es siempre final); sin borrados; bitácora de eventos **solo-añadir** (recibida, duplicada, conflictos, denegadas).
- **PostgreSQL** (`PgOfflineCaptureStore`): `INSERT … ON CONFLICT (capture_id) DO NOTHING`; la restricción `PRIMARY KEY` y los **triggers** garantizan inmutabilidad (autor, contenido, checksum), resultado final, ausencia de borrados y que `industrial_approval` no pueda ser `true`.
- **SQLite** (`SqliteOfflineCaptureStore`): reproduce el contrato con `BEGIN IMMEDIATE` para las pruebas locales.
- **Migración preparada, NO aplicada:** `backend/offline_capture_migration/proposed_0032_offline_capture_receipt.sql` (+ rollback). Esquema aislado `vinto_offline`, sin claves foráneas a tablas operativas. Está **fuera** de `backend/migrations/` para que `migrate.py` no la recoja; se promueve solo con autorización explícita.

## 5. Adaptador del motor (Fase D)
`lib/vinto/offline-sync-http-transport.ts` implementa `SyncTransport` sobre una función `http` **inyectada** (no llama a la red por sí mismo). Conserva `capture_id` y autor; el motor sigue comprobando la identidad original y **consulta antes de repetir** una entrega incierta. Una respuesta cuenta como confirmación central **solo** si repite el mismo `capture_id` y checksum, trae `server_id` y `technical_acceptance:true`; cualquier otra cosa es `conflict` (`response_unverifiable`), nunca `synced`. Una conciliación no definitiva (401/5xx/malformada) es error de transporte: ni «encontrada» ni «no encontrada». Los conflictos y pendientes se conservan. El motor y el servidor simulado de OFF-04.3 siguen funcionando sin cambios (la petición ganó dos campos opcionales: `machine_code`, `scope_snapshot_id`).

## 6. Pruebas (solo datos sintéticos; bases y servidores desechables)
- **pytest** (`test_off044_receiver.py`, 19 casos × SQLite/PostgreSQL = 38): recepción correcta; duplicado idéntico; mismo id con otro contenido; **8 POST concurrentes ⇒ 1 captura**; respuesta perdida + GET + reintento; no filtración de existencia; autor distinto; sesión vencida; sin permiso industrial; snapshot de solo consulta (y autorizador por defecto deniega todo); contexto compatible/incompatible/versión antigua; contexto no verificable ⇒ revisión con respuesta persistida; conflicto de integridad, decimales y campos extra; error temporal 503 sin estado parcial; **reinicio** (nueva instancia/conexión); inmutabilidad en PostgreSQL (UPDATE/DELETE/aprobación rechazados por triggers); autor inmutable; **receptor deshabilitado ⇒ 404 sin escrituras**; la app operativa no registra el receptor; sin tablas operativas ni aprobación; vectores de hash.
- **Node ↔ FastAPI** (`off-04-sync-fastapi.test.mjs`, 16 escenarios): el motor OFF-04.3 contra el receptor real por un servidor **loopback descartable**: primera recepción, duplicado, otro contenido, concurrencia, respuesta perdida conciliada sin segundo POST, autor distinto, 401, sin permiso, snapshot de consulta, contexto modificado, revisión, integridad, error temporal, respuesta no verificable ⇒ nunca `synced`, **reinicio del receptor** y receptor deshabilitado.
- **Mutaciones de control (todas detectadas):** sin comprobación de contenido, de autor inmutable, de autor autenticado, de checksum, ni del autorizador; sin `ON CONFLICT`; ignorar el estado deshabilitado; duplicados que no reutilizan la respuesta persistida.
- **Regresiones:** OFF-04.3 y anteriores (Node y Chrome), `tsc`, ESLint y compilación normal sin laboratorio.
- **PostgreSQL local:** sin Docker ni servicios del equipo, con una instancia efímera de usuario (paquete `pgserver`, socket Unix, base `*_test`). En CI: `postgres:17` como servicio, con `OFF044_REQUIRE_PG=1` (la ausencia de PostgreSQL falla).

## 7. Observaciones y riesgos pendientes (sin crear subincrementos)
- **Autorización real:** el autorizador de producción debe usar el motor `authz` y concesiones máquina/formulario (hoy es una interfaz con implementación sintética); sin ella el receptor niega todo.
- **Contexto real:** el `ContextProvider` productivo (OT/asignación/turno según OFF-01 §6) no existe; por defecto todo va a revisión.
- **Sesión/cookies:** las pruebas usan un encabezado sintético; la integración con `current_user` y CORS/CSRF para POST queda para el montaje real. La validación del cuerpo ocurre antes del 404 del receptor deshabilitado (un cuerpo inválido da 422, no 404).
- **Sin retención ni resolución** de `requires_review`/`conflict` en el servidor; sin cuotas ni límite de tamaño de payload más allá del de FastAPI.
- **Migración sin aplicar**; promoverla exige revisión de DDL y autorización. El guard QA de #219 no se pudo contrastar.
- Hash canónico: solo cadenas/booleanos/enteros (los flotantes se rechazan); el orden de claves difiere entre lenguajes solo para caracteres fuera del plano básico.
