# VINTO OFF-04.8A — registro automático al reconectar (diseño de integración)

**Decisión de negocio aprobada (Issue #245):** toda captura offline válida debe terminar registrada **automáticamente** en Calidad operativa al recuperarse Internet, sin revisión humana anterior al registro. Una excepción queda disponible para corrección/revisión sin bloquear otros elementos de la cola. Registro de captura != decisión de aprobar/rechazar/liberar.

## Estado de este primer incremento

Este PR implementa únicamente un **candidato de adaptador de backend opt-in** (`app.quality.offline_operational.QualityOperationalPromoter`), con el contrato fail-closed, verificador obligatorio de alcance de captura firmado y pruebas unitarias de barreras iniciales. **NO está cableado al receptor HTTP ni a la aplicación. NO sincroniza automáticamente aún.** No habilitarlo ni usarlo con datos reales hasta superar los gates siguientes.

### Confirmaciones verificadas en el código existente

- `receive_capture()` actual: autoriza, guarda un `capture_receipt`, evalúa contexto y validación de reglas online, reconcilia un resultado técnico; no escribe en `vinto_txn`.
- `submit_machine_capture()` y `submit_quality_capture()` actuales ya crean captura en `vinto_txn.capture` de manera idempotente por `capture_id`; ambos operan con transacciones internas y compuerta `gate`.
- `contextIdFor()` calcula únicamente la clave interna de borrador; el `context_version` que se envía para formularios por máquina es el `snapshot_id`. Para bobinas `bobbin_context.context_version()` es SHA256 de snapshot, bobina y digest del contexto F3.
- `offline-sync-engine` tiene estados de recibo técnico y retries, pero la PWA de laboratorio aún exige puente manual + botón `Sincronizar ahora`.
- `public/sw.js` usa cache-first y nombre de caché estático. No borrar datos del sitio en una actualización real.

## Contrato objetivo (por implementar y cubrir E2E)

1. Recuperar conectividad y sesión **del autor original**; el dispositivo incorpora automáticamente pendientes cifrados a la cola y activa el envío, sin pedir intervención humana.
2. Verificar alcance firmado **capaz de capturar** (no `scope_readiness_only`), políticas efectivas actuales y permiso `quality.capture`. Si falta sesión, mantener pendientes locales y retomarlos al reautenticar; si falta permiso, excepción con razón estable.
3. Reconciliar por `capture_id`: transacción del recibo + guardado de la **captura operativa** en **la misma BD y transacción**, reutilizando los dos servicios de Calidad; autoría original, dispositivo y versión sin cambio; sin reinsertar valores calculados del cliente.
4. No devolver/mostrar `synced` como **registro operativo confirmado** hasta que `vinto_txn.capture` esté en `submitted` y exista un acuse persistido de éxito **operacional** (no solo técnico). En caso de fallo transitorio, rollback total y reintento idempotente.
5. Una captura inválida puede conservar un recibo técnico en `review`, sin captura operativa, sin bloquear el resto. Si la política exige corrección, no insertar a escondidas tras cambiar datos sellados. Un reintento idéntico no duplica registros.
6. Persistir correlación `capture_id` ↔ `receipt` y un estado de promoción distinto del resultado técnico. El mecanismo que permite que eventos técnicos anteriores (G8 y los 11 del piloto) queden históricos y no sean promocionados debe estar explícitamente protegido.
7. Actualización versionada del service worker y assets sin borrar IndexedDB, pendientes ni claves offline.

## Brechas/gates antes de conectar el adaptador

- **G1 (obligatorio):** diseñar transacción real compartida entre `vinto_offline` y `vinto_txn` en la misma base de datos, incluyendo permisos de roles separados. Si no es posible: outbox transaccional + worker con garantía de convergencia, nunca decir `operational_registered` antes de commit. No usar conexión QA que solo posea tablas técnicas.
- **G2 (obligatorio):** construir esquema específico de alcance para captura (actual alcance QA es read-only/sintético). Prohibir la simple mutación de `synthetic:true` a `false`; validar firma/snapshot server-side.
- **G3 (obligatorio):** validar misma versión publicada y el contexto real de bobina/máquina; resolver bloqueo, orden de locks y diferencia entre momento de ensayo y hora de registro.
- **G4 (obligatorio):** tests PG17 descartable de 10 formularios + 1 inválido, 20 reintentos/concurrencia, caída tras commit antes de respuesta, cambios de versión o revocación, distintos usuarios, cero liberaciones y migración inversa.
- **G5 (obligatorio):** PWA autocolocación en cola, envío con evento online, reintentos al arranque/enfoque y backoff. Garantizar no duplicar ni perder registros por múltiples pestañas. La UI debe separar recepción técnica, registro operativo y aprobación.
- **G6 (obligatorio):** migración y activación por feature flag inicialmente OFF; no tocar producción ni reactivar el piloto OFF-04.7 sin autorización.

### Invariantes de esta rama

No activar ninguna API, no modificar `main`, no merge, no desplegar, no tocar VPS ni QA. El adaptador es **candidato no conectado** y la implementación completa requiere los gates anteriores y aprobación específica de despliegue.

## OFF-04.8B — integración opt-in de ACK y atomicidad (candidato, todavía NO productivo)

- `receive_capture(..., promoter=None)` y `create_offline_capture_router(..., promoter=None)` preservan el flujo técnico del QA de OFF-04.7 sin cambios por defecto. **Ninguna ruta en `app.main` activa el promotor.**
- Si se inyecta un promotor, el receptor exige un validador central. Para una captura nueva aceptada (nunca para `review` ni duplicado), el receptor invoca el adaptador dentro de un **savepoint propio** (`promotion_savepoint` en PostgreSQL y SQLite de tests); solo un retorno de `capture_id` coincidente permite fijar `operational_registered=true` en la respuesta persistida.
- Si el registro falla de forma transitoria, se revierte la transacción de recibo y escritura candidata. Si un rechazo determinista `PromotionReview` ocurre luego de alguna escritura candidata, el savepoint revierte esa escritura y deja el recibo técnico en revisión, sin registro operativo. No hay cambios a decisiones o liberación industrial.
- Al consultar o reintentar un recibo, el ACK operativo se reconstruye **exclusivamente del resultado persistido**. Los recibos técnicos históricos que no guardaron ACK no se pueden confundir con registros operativos.
- `SyncOptions.requireOperationalAck` es **opt-in**. Cuando está habilitado, una respuesta técnica exitosa o una conciliación sin `operational_registered=true` y `operational_capture_id` idéntico a `capture_id` deja la captura en `requires_review` con `operational_unconfirmed`; nunca informa éxito operativo. El transporte HTTP valida la identidad del ACK. Los demás flujos de laboratorio mantienen comportamiento anterior.
- Tests agregados: SQLite contrato de revisión/rollback/reintento; PostgreSQL descartable con tabla **solo de prueba** para demostrar que recibo y efecto candidato comparten transacción; Node de sync-ACK incluyendo respuesta perdida y consulta posterior. **Esto NO sustituye** el gate de PostgreSQL 17 integrado contra el servicio real de Calidad, ni firma de alcance operativo.

### Estado y restricciones

**IN_PROGRESS, sin autorización de despliegue.** Falta: conectar los servicios de Calidad reales en PG17 descartable y verificar autorización de roles/DDL; implementar emisor y verificador robustos de snapshot **capture-capable** del servidor (el actual de QA es `readiness_only`); activar el controlador de autocolocación en cola y la reconexión en la PWA real; versionar SW y cache; validar cortes de Internet, sesión expirada, author mismatch, 10 formularios + 1 negativa. Ninguna de estas brechas se resuelve con cambiar `synthetic` de true a false; está expresamente prohibido.

## OFF-04.8D — autoridad revocable preparada (sin instalación)

- Nuevo SQL **propuesto**, no numerado ni instalado: `backend/offline_capture_migration/proposed_0033_offline_capture_scope_authority.sql`. Tabla aislada `vinto_offline.capture_scope_authority` para snapshot, identidad original, dispositivo, huella y sobre Ed25519, vigencia y revocación; guard contra edición/borrado; permisos columna `revoked_at` únicamente al rol app.
- `quality/offline_capture_authority.py`: emisión solo por una sesión del usuario Calidad, dispositivo UUID válido, pares permitidos por **el motor efectivo de autorización con `lock=True`** y conjunto cerrado de diez formularios. El payload se firma con dominio distinto del read-only y se registra en la **misma transacción** que su emisión. Revocación unidireccional. El verificador obtiene el sobre firmado del servidor (NO del payload cliente), constata huella/estado y mantiene un bloqueo de fila `FOR SHARE` hasta el commit operativo.
- `test_off048d_capture_authority_db.py` comprueba emisión, verificación, revocación, inmutabilidad, vinculación de usuario/dispositivo/versión y negativa de reaplicar DDL, usando únicamente PostgreSQL descartable. Las decisiones de autorización efectiva de este test son dobles sintéticos: las pruebas específicas de `app.authz.engine` cubren el bloqueo por permisos reales.
- **Aún NO** hay endpoint, emisor productivo habilitado, conexión de la PWA a este tipo de token ni migración instalada. `QualityOperationalPromoter` sigue siendo inyectable/no montado. OFF-04.7 continúa apagado.

### Decisión pendiente de política
La ventana actual del contrato `capture_authority` es **máximo 24 horas desde emisión hasta sincronización**. Esto es seguro por defecto, pero **puede impedir el registro automático de capturas válidas si el dispositivo permanece más de 24 horas desconectado**. No se habilitará para uso operativo hasta definir explícitamente duración, tratamiento de captura hecha durante una sesión válida pero sincronizada después de caducar y criterio de revocación. Ninguna captura local se borra aunque el plazo expire.

## OFF-04.8E — política aprobada: hasta OCHO horas sin Internet + experiencia sin botones técnicos

Decisión funcional: **un operario permanecerá como máximo 8 horas sin Internet**. No habrá botones obligatorios de «Autorizar», «Preparar dispositivo» ni «Sincronizar». **«Guardar captura»** es la confirmación explícita de un formulario terminado. El guardado automático previo es solo **borrador editable cifrado**, sin envío ni aprobación.

### Contrato de cobertura propuesto

- Firma operativa server-side con vigencia máxima **24 horas** desde su emisión. Renovación **automática mientras existe conexión y sesión del autor**, cuando restan **12 horas o menos**. Prepara una jornada offline de hasta **8 horas** con margen de 4 horas.
- Antes de informar «Preparado sin conexión», comprobar que el alcance cubre las siguientes 8 horas. Si falta cobertura, mostrar «Se requiere conexión para renovar» sin borrar borradores ni pendientes.
- Al reconectar, el servidor valida permisos actuales y firma. Revocación, contexto incompatible o validación fallida dejan solo el registro afectado para corrección/revisión, sin bloquear los demás.
- La vida útil de 24h **no autoriza trabajar sin Internet por 24h**; el máximo operacional permanece 8h.
- Reingreso bajo el usuario original cuando su sesión haya expirado; no autorizar capturas con otra cuenta.
- La política de captura hecha con firma vigente pero enviada tras caducar requiere gate adicional. Los datos permanecen locales; nunca se asumirán aprobados.

### Componentes aislados, aún no montados

- `lib/vinto/offline-capture-coverage.ts`: función pura que evalúa cobertura de 8 horas y cuándo renovar.
- `lib/vinto/offline-capture-renewal.ts`: renovación opt-in en evento online/focus o reautenticación. No gestiona claves ni llama a una API sin el adaptador futuro.
- `lib/vinto/offline-draft-autosave.ts`: autosave coalescente con escritor cifrado y CAS de revisión inyectado. No congela, encola ni envía: la confirmación explícita es «Guardar captura».
- Pruebas Node `off-04-8e-coverage.test.mjs`, `off-04-8e-renewal.test.mjs`, `off-04-8e-draft-autosave.test.mjs` en workflow OFF-04.6; **CI todavía sin PASS**.

Antes de montar en una PWA real: E2E de 8h simuladas, suspensión y reapertura, expiración de sesión, identidad original, múltiples pestañas, servicio de emisión real, actualización Service Worker sin borrar IndexedDB y confirmación operativa idempotente. **Sin merge ni deploy o reactivación QA en este incremento.**

## OFF-04.8F — confirmación de captura y recuperación de la cola (opt-in, sin montar)

La UX aprobada tiene **un solo botón «Guardar captura»**. El autoguardado del borrador ocurre automáticamente durante la edición, sin crear pendiente ni enviarlo.

- `offline-draft-autosave.ts` ahora tiene `flush()` como **barrera de durabilidad**: si el usuario escribe mientras se guarda una revisión anterior, espera y guarda también la más reciente antes de permitir congelar el formulario. Un CAS conflictivo, almacenamiento no disponible o bóveda bloqueada impiden avanzar; nunca se confirma falsamente.
- `offline-confirm-capture.ts` implementa el comando único: espera al autoguardado → congela mediante transición inmutable con revisión esperada → incorpora idempotentemente a la cola → despierta la sincronización, sin exigir acción manual adicional. Doble pulsación en la misma pestaña comparte la promesa; si falla el puente a la cola, se conserva el pendiente local congelado para recuperación, sin borrarlo.
- `offline-frozen-queue-bridge.ts` es el adaptador propuesto para `AutoSyncDeps.prepareQueue`: vuelve a incorporar pendientes operativos al arrancar/volver Internet sin alterar `capture_id`, autor ni payload; rechaza pendientes sintéticos del piloto, no cruza identidades y procesa individualmente fallos de almacenamiento.
- Pruebas nuevas: `off-04-8f-confirm-capture.test.mjs` y `off-04-8f-frozen-bridge.test.mjs`, añadidas al workflow del PR.

**Importante:** estos son componentes de coordinación aislados, todavía **no montados** en la aplicación de operarios ni en el laboratorio OFF-04.7, y no sustituyen el emisor de autorización vigente ni el gate real PostgreSQL 17 con los diez formularios. El flujo real debe **bloquear edición al iniciar la confirmación hasta completar la transición**, coordinar múltiples pestañas mediante compare-and-swap IndexedDB, conservar evidencia congelada ante fallo y verificar el ACK operativo del servidor antes de mostrar «Registrada en Calidad». No mezclar los borradores `synthetic:true` de laboratorio con el nuevo flujo `synthetic:false`.

**Estado:** implementación de módulos y pruebas propuesta; esperar CI verde y construir la integración PWA autorizada antes de considerar funcional OFF-04.8.
