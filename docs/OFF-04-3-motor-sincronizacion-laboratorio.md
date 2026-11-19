# VINTO OFF-04.3 — Motor de sincronización offline (laboratorio, servidor simulado)

**Estado:** candidato de ensayo aislado, PR Draft apilado sobre #231. Seguimiento: #232.
**Solo laboratorio con servidor simulado.** No se conecta con FastAPI ni con ningún endpoint productivo, no habilita captura industrial, no modifica permisos ni paquetes de solo lectura, no toca PostgreSQL/VPS/Docker/Nginx/firewall, SEC-HOST-01 ni OFF-04.2-R3 (en backlog).

## 1. Auditoría (Fase A)

- **Base:** el SHA indicado (`b12c17eb…`) no existe en el clon de trabajo. Se construyó sobre la rama local de OFF-04.2-R2 (`043e249b75f7c6e998ca1fee1aed55cb49f14c4a`), que es lo que #231 debería contener. Todo el trabajo son archivos nuevos más tres cambios mínimos (script de build, `public/sw.js`, `.gitignore`), de modo que reubicarlo sobre otro SHA es una operación de `cherry-pick` sin conflictos previsibles. **Verificar la base antes de publicar.**
- **Contrato OFF-01 V2 (§8):** estados `queued`, `syncing`, `retry_wait`, `synced`, `synced_warning`, `requires_review`, `conflict`; `uncertain` se modela como **indicador** (no como estado) porque OFF-01 exige reconciliar por GET antes de repetir el POST. No se elimina ningún pendiente; los conflictos conservan su payload. Reglas de contexto (§6): nunca migrar silenciosamente a otro producto/OT.
- **Outbox operativo (`outbox` de `vinto-offline-v1`)** y **cola sintética** (`vinto-off04lab-v2`): el motor **no los lee ni los escribe**. Tiene su propia base (`vinto-off043-sync-lab-v1`, almacén `sync_queue`) y su propio registro. Las pruebas estáticas verifican que ningún módulo del motor importa ni menciona el outbox, el almacén de la aplicación ni la cola sintética (y viceversa), y que ningún código operativo referencia el motor (barrido con control negativo).
- **Restricciones heredadas:** `capture_eligible=false` / `captures_enabled=false` intactos; las capturas del laboratorio son registros sintéticos (`synthetic: true`) de prueba, no capturas industriales.

## 2. Contratos

### Transporte (`SyncTransport`) — lo que implementará FastAPI después
- `send(request)`: **POST idempotente por `capture_id`**. Cuerpo: `capture_id`, `author_user_id`, `device_key`, `form_code`, `form_version`, `context_version`, `payload_sha256`, `payload`. Respuestas: **200/201** aceptada (`created`/`duplicate`, `server_id`, `warnings[]`), **202** a revisión central, **401** sin sesión, **403** sin permiso/autor distinto, **409/422/400** conflicto (`context_changed`, `payload_mismatch`, versión incompatible…), **429/5xx** transitorio. Fallo de red/tiempo agotado ⇒ `SyncTransportError`.
- `lookup(capture_id)`: **GET de reconciliación**: `found:false` o `found:true` con `accepted | accepted_warning | review | conflict`.
- Un transporte FastAPI real es un cambio posterior, con su contrato de captura offline aprobado (OFF-04.5) y su autorización explícita.

### Servidor simulado (`FakeSyncServer`)
Registra cada captura **lógica una sola vez**, por `capture_id`, aunque reciba muchos intentos (los siguientes son `200 duplicate`; mismo id con otro payload ⇒ `409 payload_mismatch`). Valida sesión (401), autor (403) y contexto (409). Se puede programar para perder la respuesta tras persistir, agotar el tiempo, 5xx antes o **después** de persistir, 401/403/429, revisión central, advertencias, y fallos de reconciliación. Sin red, sin `fetch`.

## 3. Motor (Fase B)

`syncNow(deps)` («Sincronizar ahora»): una pasada, segura desde varias pestañas.

- **`capture_id` estable:** se fija al crear la captura y se envía idéntico en cada intento; el motor nunca genera identificadores.
- **Persistencia y estados:** cada registro guarda estado, intentos, `nextAttemptAt`, `uncertain`, arrendamiento (`lease`), contador de versión y último error. La carga cifrada (AES-GCM, AAD ligada al `capture_id`) se conserva siempre.
- **Exclusión entre pestañas:** `claim`/`finalize` son compare-and-swap con arrendamiento en una transacción (`offline-sync-rules.ts`, reglas compartidas por la base IndexedDB y la de memoria). Un `syncing` con arrendamiento vigente no se toca; si vence (pestaña caída) se **recupera** marcándolo incierto.
- **Conciliación antes de reenviar:** todo registro incierto o recuperado se consulta por `lookup` **antes** de cualquier reenvío. Si el servidor ya lo tiene, pasa al estado central sin reenviar; si no, se envía una vez. Un fallo de la consulta deja el registro en espera, nunca se reenvía a ciegas.
- **Identidad del autor:** se exige sesión en línea válida del **autor original** (por pasada y por registro). Sesión vencida ⇒ pausa `session_invalid`; otro usuario ⇒ pausa `different_user`; **nada cambia** ni se reasigna.
- **Errores:** red/tiempo agotado/5xx ⇒ `retry_wait` con **backoff exponencial** con jitter (`base·2^(n-1)`, tope, 50–100 %) e indicador incierto; agotados los intentos ⇒ `requires_review` conservando la carga. **401** ⇒ vuelve a `queued`, no consume intento y pausa `auth_required`. **403** ⇒ `requires_review`. **409/422/400** ⇒ `conflict`. **202** ⇒ `requires_review`. Advertencias ⇒ `synced_warning`.
- **Integridad:** la carga se descifra y su hash debe coincidir con el congelado; si no ⇒ `requires_review` y **no se envía**.
- **Dependencias:** un registro con `dependsOn` solo se envía cuando su dependencia está `synced`/`synced_warning`; si falla o queda en revisión/conflicto, el dependiente permanece `queued` y bloqueado (contado), nunca se envía.
- **Contadores y resultados:** cada pasada devuelve `paused`, `stopped`, `sent`, `reconciled`, omitidos (espera/bloqueo/ocupado), resultados por captura y contadores por estado.
- **Fallos de almacenamiento:** se propagan (no se tragan); si el resultado no pudo guardarse tras persistir en el servidor, el registro queda `syncing` y se recupera por conciliación al vencer el arrendamiento.

### Laboratorio («Sincronizar ahora»)
`/offline-sync-lab.html` (solo con `OFFLINE_DRAFT_LAB=1`, ausente en builds normales, sin enlace desde la app, no precacheado): banner «SERVIDOR SIMULADO Y DATOS SINTÉTICOS… NO se conecta con FastAPI», desbloqueo con frase local y confirmación, creación de capturas de prueba (con dependencia opcional), botón **Sincronizar ahora** (protegido contra doble clic), contadores y lista de estados, y panel del servidor simulado (armar fallas, contexto cambiado, sesión válida/vencida/otro usuario, reloj simulado +60 s). El servidor vive en la memoria de la pestaña; la cola persiste y funciona sin conexión tras reiniciar.

## 4. Pruebas (Fase C; solo datos sintéticos, sin API real)

- **Escenarios (24), escritos una vez y ejecutados sobre AMBAS bases** (memoria en Node; IndexedDB real en Chrome): éxito con contadores; enqueue idempotente y `capture_id` estable; pérdida de respuesta tras persistir; mismo `capture_id` repetido (registra una vez; `payload_mismatch`); dos pestañas; reinicio durante la sincronización (antes y después de persistir, y resultado tardío de la pestaña caída); sesión vencida; autor distinto; 401; 403; 5xx con backoff; 5xx tras persistir; red intermitente hasta revisión; dependencias y dependencia bloqueada; contexto industrial cambiado; revisión central; advertencia; carga alterada y hash alterado; fallo de conciliación; resultado no guardado tras persistir; función de backoff; y **cero llamadas `fetch`**.
- **Chrome IndexedDB** (`off-04-sync-browser.py`): la suite completa sobre IndexedDB real, **dos pestañas reales** sobre una misma base (ninguna captura la envían ambas), estados que **sobreviven al cierre del navegador** y se reanudan, fallos de almacenamiento (cuota al reclamar; fallo al guardar el resultado) que dejan un estado recuperable, y ausencia de peticiones de red o `/api/`.
- **Chrome UI** (`off-04-sync-lab-browser-smoke.py`, 7): flujo completo, doble clic, pérdida de respuesta conciliada sin duplicado, sesión vencida / otro usuario / 401 con pausa y reanudación, 403 y contexto cambiado sin reintento, reinicio **sin conexión** desde el Service Worker con estados persistidos, y cero tráfico `/api/`.
- **Contratos estáticos** (`off-04-sync-static.test.mjs`, 6): los siete estados exactos, separación del outbox/cola sintética, barrido con control negativo, sin red, reglas de seguridad presentes y laboratorio solo con opt-in.
- **Mutaciones de control (todas detectadas):** quitar la conciliación previa; quitar ambas comprobaciones de autor; ignorar el arrendamiento; reintentar 403; ignorar dependencias; tratar 401 como transitorio; quitar la comprobación de hash.
- **Regresiones:** OFF-02 a OFF-04.2-R2 y OFF-03C.4 (Node y Chrome), `tsc`, ESLint y compilación normal sin laboratorio.

## 5. Riesgos residuales y límites

- Todo es contra un **servidor simulado**: la semántica real de FastAPI (códigos, cuerpos, autoridad central, reglas de contexto histórico de OFF-01 §6) está **propuesta**, no verificada; el contrato de captura offline aprobado (OFF-04.5) y el endpoint idempotente real siguen pendientes.
- Las capturas del motor son sintéticas y se crean en el propio laboratorio; **no hay puente** desde la cola sintética de borradores ni desde un outbox operativo (deliberado, para mantener la separación).
- Arrendamiento por reloj local: un reloj manipulado puede acelerar o retrasar la recuperación (la conciliación impide la duplicación en el servidor, no el reenvío redundante).
- Sin retención, depuración ni exportación de registros; los terminales (`requires_review`, `conflict`) no tienen flujo de resolución en este incremento.
- La sesión en línea del laboratorio es simulada; la integración con `GET /api/auth/me` y la reautenticación del autor original son trabajo posterior.
- QA físico del móvil no ejecutado; pruebas locales con Chromium de Playwright.
- Heredado: restauración local de estados antiguos sin ancla externa; datos sintéticos garantizados por proceso.

## 6. Siguiente paso sugerido
Definir con backend el contrato real (POST idempotente + GET de reconciliación, códigos y reglas de contexto de OFF-01 §6) y un puente explícito y auditable desde la cola de capturas aprobada hacia `sync_queue`; después, un transporte FastAPI detrás de una bandera, con pruebas contra un backend aislado.
