# OFF-01 — Arquitectura y contrato funcional de operación offline

**Estado:** diseño documentado para revisión; no habilita operación offline ni despliegue.  
**Base auditada:** `main` en `2ca165af615ad5405a526e40d73e96ff8f83b4a6` (16-nov-2026).  
**Rama:** `docs/off-01-offline-architecture`.  
**Alcance de este entregable:** decisiones de arquitectura, límites de seguridad, estados, secuencia de implementación y criterios de aceptación. Sin cambios en frontend, backend, esquema PostgreSQL ni producción.

## 1. Modelo operativo confirmado

VINTO utilizará dispositivos compartidos por máquina, no asignados permanentemente a una persona:

- **Bobinas:** un dispositivo por máquina.
- **Rebobinado y Conversión:** dispositivos compartidos entre los operarios de las máquinas.
- **Identidad:** cada operario ingresa con su propia cuenta; nunca se utiliza una cuenta compartida para atribuir capturas.
- **Permisos:** una cuenta puede estar autorizada para más de una máquina y más de un formulario. La aplicación solo presenta los equipos y operaciones que la autorización efectiva permite.
- **Dispositivo:** mantiene una identidad técnica estable y se registra en el backend. La identidad del dispositivo no sustituye al usuario.

La captura deberá conservar como mínimo: usuario autenticado, dispositivo, máquina derivada/autorizada, asignación o contexto industrial, formulario y versión, identificador idempotente y datos capturados.

## 2. Hallazgos de la auditoría de main

- `app/page.tsx` detecta `navigator.onLine`, pero actualmente muestra que no es posible registrar capturas offline.
- Los intentos de envío de los formularios se conservan principalmente en estado React; no sobreviven de forma garantizada a recarga/cierre.
- `lib/vinto/capture-core.ts` ya genera `capture_id` UUID y dispone de envío/reconciliación para resultados inciertos.
- `backend/app/captures.py` y `backend/app/capture_service.py` implementan captura central y comprobación idempotente por `capture_id`.
- `lock_active_assignment()` comprueba asignación activa, máquina, OT, línea en producción y vigencia de turno/fecha usando el reloj de PostgreSQL.
- `published_form_version()` selecciona la versión publicada vigente; una cola offline no debe reinterpretar silenciosamente datos capturados con otra versión.
- No se identificó PWA/Service Worker ni un almacén IndexedDB/cola offline en el árbol auditado.
- La autenticación actual usa sesión/cookie HttpOnly y el cliente no persiste la sesión. No se deben copiar cookies ni credenciales a IndexedDB.

## 3. Arquitectura objetivo

1. **PWA / Service Worker:** cachear únicamente shell, bundles, fuentes, iconos y recursos estáticos versionados. No cachear endpoints de autenticación, autorizaciones privadas, APIs operativas ni respuestas con datos personales.
2. **IndexedDB:** almacenamiento local versionado para autorizaciones offline, snapshots de formularios/catálogos, borradores y outbox. Separación lógica por usuario y dispositivo; transacciones atómicas para persistir una captura y su entrada en cola.
3. **Offline authorization grant (lease):** concesión emitida por backend mientras el usuario está online, vinculada a usuario, dispositivo, máquina/sector, formularios/versiones, contexto operativo y expiración. Debe estar firmada/verificable por backend y no depender de confiar en el reloj del navegador.
4. **Sync Engine:** proceso de primer plano al recuperar conexión, con reintentos, backoff, reconciliación por identificador idempotente, estados visibles y orden de dependencias. Background Sync será mejora progresiva, nunca requisito para no perder datos.
5. **Backend:** valida concesión, identidad original, dispositivo, alcance, versión, integridad del payload, revocaciones conocidas y reglas industriales. El backend mantiene autoridad final para persistencia y auditoría.

## 4. Autenticación en dispositivos compartidos

- Online: conservar el login corporativo actual con usuario/contraseña y cookie HttpOnly.
- Offline: el servidor no puede validar una contraseña nueva mientras no existe conectividad. Se requiere un mecanismo local de desbloqueo previamente enrolado y limitado.
- **No se decide todavía PIN offline.** Es una alternativa a evaluar, no un requisito aprobado. Antes de implementarlo se debe acordar enrolamiento, complejidad, rate-limit local, bloqueo, recuperación, duración, protección de secretos y comportamiento cuando el usuario cambia.
- No persistir contraseñas, cookies HttpOnly, tokens de sesión ni secretos reutilizables de autenticación en IndexedDB.
- El desbloqueo offline solo permite utilizar una concesión previamente descargada; no puede ampliar permisos ni crear nuevas concesiones.
- Al cambiar de usuario, separar los espacios de datos y ocultar/bloquear los datos del usuario anterior. Una cola pendiente nunca se reasigna al siguiente operario.
- El logout debe bloquear la vista y limpiar datos sensibles temporales; las capturas pendientes cifradas o protegidas no se borran silenciosamente. Su retención/limpieza requiere política explícita.

## 5. Contrato de autorización offline

La concesión debe incluir o referenciar de forma verificable:

- `grant_id`, usuario, dispositivo y fecha de emisión.
- Máquina/sector y permisos concretos.
- Formularios y versiones exactas autorizadas, con checksum de definición y catálogos necesarios.
- Asignación/OT/línea y contexto operativo permitido.
- Ventana de validez, política de sincronización posterior y límites de uso.
- Identificador/versión de política y firma del servidor.

**Regla de vigencia por definir funcionalmente:** una captura realizada mientras la concesión era válida podría llegar al servidor después del fin del turno o de la asignación. El backend debe distinguir hora de captura local (no confiable por sí sola), concesión emitida por servidor, secuencia local y hora de recepción. No se debe aceptar automáticamente una captura tardía solo porque el cliente declare una hora anterior.

La autorización no convierte en válidas operaciones administrativas ni decisiones de Calidad sensibles. Liberar/rechazar bobinas, cambios de permisos, usuarios, OT, asignaciones y otras mutaciones administrativas permanecerán online en la primera fase.

## 6. Outbox y estados

Cada elemento de cola mantiene un ID estable, usuario propietario, dispositivo, grant, formulario/versión, contexto, payload, fecha local informativa, secuencia local y estado.

Estados mínimos:

- `draft`: borrador local editable.
- `queued`: persistido localmente, pendiente de sincronización.
- `syncing`: envío en curso.
- `synced`: backend confirmó creación o reconciliación.
- `retry_wait`: fallo transitorio; conserva payload e ID.
- `conflict`: rechazo definitivo o contexto/permisos/versiones incompatibles; requiere revisión.
- `uncertain`: no fue posible determinar si el servidor persistió; reconciliar antes de generar otro ID.

El ID idempotente se crea una sola vez por captura lógica y nunca cambia en reintentos. Si un mismo ID llega con datos distintos, se trata como conflicto de integridad, no se sobrescribe.

## 7. Resolución de dependencias y conflictos

- Las capturas independientes se pueden sincronizar individualmente.
- Las operaciones dependientes deben conservar relaciones locales y sincronizarse en orden topológico; no se inventan IDs centrales ni se simula éxito.
- P1-07/crías y Calidad vinculada a bobina requieren un diseño específico de genealogía y dependencias antes de habilitarse offline.
- Los formularios con validaciones de receta, peso maestro, catálogos dependientes, unicidad o restricciones por turno deben descargar un snapshot versionado y repetir validaciones en backend.
- Si una autorización venció, fue revocada, cambió el contexto o el formulario ya no es compatible, se conserva el registro local como `conflict`; no se descarta ni se altera su contenido.
- Las capturas ya sincronizadas no se vuelven a enviar automáticamente.

## 8. Entregables propuestos

| ID | Alcance | Resultado |
| --- | --- | --- |
| OFF-01 | Contrato y arquitectura (este documento) | Diseño revisable |
| OFF-02 | PWA, Service Worker, IndexedDB y borradores | App abre offline y conserva borradores |
| OFF-03 | Concesión offline backend y snapshots | Acceso limitado y verificable |
| OFF-04 | Outbox y Sync Engine; piloto F6 | Captura/sincronización idempotente |
| OFF-05 | Formularios centrales de Producción | Ampliación por formulario |
| OFF-06 | Calidad y flujos dependientes | Ampliación con genealogía/orden |
| OFF-07 | QA integral, runbook y liberación | Go/no-go documentado |

## 9. Piloto propuesto

Comenzar con **F6 — Registro de control de fardos**, por ser un flujo central con API existente e idempotencia por `capture_id`, y no generar en el primer piloto dependencias adicionales como crías o pallets.

El piloto debe validar: enrolamiento online, cambio de operario, desconexión, captura local, recarga del navegador, cierre/reapertura, reconexión, reintento, resultado incierto, duplicado, concesión vencida, revocación conocida y usuario distinto en el mismo dispositivo.

## 10. Criterios de aceptación globales

- La PWA abre offline después de una primera carga online.
- Ninguna API privada ni respuesta de autenticación se sirve desde caché estática.
- Una captura autorizada se guarda de forma atómica en IndexedDB y sobrevive a recarga/cierre.
- Cambio de usuario no expone borradores ni permite atribuir capturas al usuario equivocado.
- Una captura sincronizada se registra una sola vez en PostgreSQL.
- Un envío incierto se reconcilia usando el mismo ID.
- Rechazos/conflictos conservan el payload y explican el motivo.
- Cambios de formulario, permisos, asignación o vigencia no se eluden mediante el cliente.
- Se conserva trazabilidad de usuario, dispositivo, concesión y hora de recepción.
- QA aislado PostgreSQL 17 y regresiones completas pasan antes de merge.

## 11. Fuera de alcance y guardas

- No desplegar, activar ni migrar producción desde esta rama.
- No habilitar offline para todos los formularios en un único cambio.
- No guardar contraseñas, cookies ni tokens de sesión.
- No usar el reloj local como autoridad para validar turno/fecha.
- No cambiar reglas industriales para aceptar capturas fuera de contexto.
- No descartar automáticamente elementos pendientes ni reasignarlos a otro usuario.
- No hacer merge de futuras fases sin CI, QA, revisión formal y autorización expresa.

## 12. Decisiones funcionales aún requeridas

1. Método de desbloqueo offline: PIN individual enrolado online u otra alternativa.
2. Duración máxima de la concesión offline y tolerancia de sincronización tardía.
3. Qué hacer con capturas cuando una asignación se cierra/reprograma mientras el dispositivo está offline.
4. Política de retención local, cifrado y limpieza de datos en dispositivos compartidos.
5. Si el dispositivo se fija a una sola máquina o puede cambiar de máquina mediante enrolamiento/autorización online.

**Conclusión:** el modelo compartido por máquina y usuario individual queda incorporado. OFF-01 documenta la arquitectura objetivo y deja explícitas las decisiones que no deben suponerse. No habilita aún capturas offline ni modifica el comportamiento actual.
