# VINTO OFF-04.8A — registro automático al reconectar (diseño de integración)

**Decisión de negocio aprobada (Issue #245):** toda captura offline válida debe terminar registrada **automáticamente** en Calidad operativa al recuperarse Internet, sin revisión humana anterior al registro. Una excepción queda disponible para corrección/revisión sin bloquear otros elementos de la cola. Registro de captura != decisión de aprobar/rechazar/liberar.

## Estado de este primer incremento

Este PR implementa únicamente un **candidato de adaptador de backend opt-in** (`app.offline_capture.operational.QualityOperationalPromoter`), con el contrato fail-closed y pruebas unitarias de barreras iniciales. **NO está cableado al receptor HTTP ni a la aplicación. NO sincroniza automáticamente aún.** No habilitarlo ni usarlo con datos reales hasta superar los gates siguientes.

### Confirmaciones verificadas en el código existente

- `receive_capture()` actual: autoriza, guarda un `capture_receipt`, evalúa contexto y validación de reglas online, reconcilia un resultado técnico; no escribe en `vinto_txn`.
- `submit_machine_capture()` y `submit_quality_capture()` actuales ya crean captura en `vinto_txn.capture` de manera idempotente por `capture_id`; ambos operan con transacciones internas y compuerta `gate`.
- `contextIdFor()` del cliente calcula UUID determinista basado en snapshot, máquina y formulario; para bobinas `bobbin_context.context_version()` es SHA256 de snapshot, bobina y digest del contexto F3.
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
