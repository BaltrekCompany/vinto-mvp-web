# OFF-01 V2 — Contrato funcional y arquitectura de VINTO Offline

**Estado:** contrato funcional V2 revisado con la decisión de reingreso offline tras cierre/reinicio; PR DRAFT pendiente de revisión/aprobación formal y sin funcionalidad offline habilitada.  
**Fecha de revisión:** 17-nov-2026.  
**Fuente operativa:** reunión VINTO del 17-nov-2026 y planos referenciales de puntos de captura de Bobinas, Rebobinado, Calidad y Conversión.  
**Base de código auditada:** `main` en `2ca165af615ad5405a526e40d73e96ff8f83b4a6`.  
**Rama:** `docs/off-01-offline-architecture`.  
**Cambio V2:** sustituye el diseño inicial generalista por el modelo offline-first de **solo captación**, con prioridad Calidad -> Conversión -> Bobinas/Rebobinado; define ausencia de vencimiento automático por turno durante el piloto, conciliación tardía con advertencia, navegadores independientes por operario y **reingreso offline después de cerrar el navegador o reiniciar el dispositivo** (decisión confirmada).

> Este documento define comportamiento objetivo; NO afirma que esté implementado. OFF-01 es únicamente documentación. No cambia código, contratos HTTP, migraciones, datos ni servicios de producción.

## 1. Propósito y frontera funcional

El MVP offline permite **registrar información cuando la red no está disponible**, guardarla de forma persistente en el dispositivo y **sincronizarla automáticamente** cuando vuelva la conectividad real hacia FastAPI; incluir botón de sincronización manual como respaldo.

**Offline permitido (por etapas):**
- Abrir la PWA ya instalada/preparada online **después de cerrar por completo el navegador o reiniciar el equipo**, sin necesitar una nueva conexión.
- Desbloquear localmente el perfil de un operario que completó el enrolamiento online con anterioridad; este desbloqueo **no crea** una sesión de backend.
- Consultar únicamente snapshots locales autorizados: máquinas, formularios, catálogos, asignación/OT y datos mínimos de contexto.
- Crear/editar borradores locales; cerrar captura en cola inmutable con `capture_id` estable.
- Recuperar pendientes tras recarga o cierre, reintentar, reconciliar y ver estados.

**Solo online:**
- Crear/modificar/cerrar órdenes de trabajo, programación, asignaciones y activación de línea.
- Conceder/revocar permisos y administrar usuarios.
- Liberar, rechazar o aprobar registros y productos; decisiones de Calidad y traspasos que dependen de una autorización central.
- Consultar indicadores centrales actualizados; alimentar Power BI desde la fuente PostgreSQL confirmada.
- Comunicación entre distintos dispositivos desconectados.

**Regla:** una captura `queued` es evidencia LOCAL de registro, no una captura confirmada por PostgreSQL ni una aprobación. No debe generar liberación, stock disponible, despacho ni indicadores antes de la confirmación central.

## 2. Topología de captura y priorización

Los planos referenciales contemplan **14 PUNTOS** de captura, que NO equivalen necesariamente a 14 dispositivos físicos confirmados. Validar tipo de equipo, sistema operativo, almacenamiento y conectividad reales antes del despliegue.

| Punto | Zona y uso | Observación offline |
| --- | --- | --- |
| B-01 | Bobinas / MP3 | Conectividad fija prevista; offline de contingencia |
| B-02 | Bobinas / MP1 | Conectividad fija prevista; offline de contingencia |
| B-03 | Bobinas / Patio de Pulper | Confirmar conectividad de la instalación |
| R-01 | Rebobinado / Copasa | Conectividad fija prevista; offline de contingencia |
| R-02 | Rebobinado / Over | Conectividad fija prevista; offline de contingencia |
| R-03 | Rebobinado / Beloit, Perichun y Tubetera | Dispositivo compartido y selección de máquina autorizada |
| Q-01 | Calidad / laboratorio | Punto conectado y de sincronización; analistas circulan por dos plantas y exterior |
| C-01 | Conversión / inicio PH | Consumo de bobinas |
| C-02 | Conversión / final PH | Producción, pallets y salida a almacén: control prioritario |
| C-03 | Conversión / OMET I-II | Captura de producción |
| C-04 | Conversión / Serv 8.2, Serv 8002 y Pañuelera | Varias máquinas/operarios por dispositivo |
| C-05 | Conversión / Serv 8.5 y Serv 4 | Varias máquinas/operarios por dispositivo |
| C-06 | Conversión / Wally | Captura de producción |
| C-07 | Conversión / merma central | Pesaje y registro de merma |

**Prioridad funcional:** 1) Calidad móvil compartida (primera experiencia de extremo a extremo); 2) Conversión C-01–C-07; 3) Bobinas y Rebobinado (contingencia). Se implementa motor técnico común antes del primer piloto. Se validará físicamente qué puestos de Conversión pueden moverse al punto conectado; un dispositivo fijo sin red no podrá sincronizar hasta disponer de conexión.

## 3. Identidad y dispositivo compartido

**Decisión operativa 17-nov:** un dispositivo puede ser utilizado por distintos operarios. Cada operario tendrá credenciales y permisos propios, posiblemente sobre varias máquinas. **Para el MVP se utilizarán navegadores diferentes por operario** (ej. Chrome, Edge y Firefox), en lugar de varias pestañas compartiendo la misma sesión.

- Cada navegador mantiene su propia cookie HttpOnly, espacio IndexedDB, caché PWA y cola. No compartir datos entre navegadores.
- Cada usuario debe iniciar sesión mientras exista conexión y preparar el contexto y los formularios autorizados. No guardar contraseñas, cookies ni tokens de sesión manualmente en IndexedDB.
- No atribuir automáticamente a otro operario los registros pendientes cuando cambien las cuentas.
- La sincronización automática se ejecuta **por navegador abierto y perfil desbloqueado**, no globalmente en todo el dispositivo: Chrome no sincroniza la cola local de Firefox. Cada perfil debe verificar sus pendientes en la rutina de conexión/fin de turno. Al recuperar conexión, una sesión online expirada o de otro usuario requiere reautenticación antes de enviar la cola.
- Se debe identificar de manera inequívoca al autor original de cada registro. Una cookie de sesión válida al sincronizar no puede sustituir arbitrariamente al autor registrado.
- No utilizar cuatro pestañas de un mismo navegador como cuatro identidades independientes.
- **Decisión funcional confirmada:** después de cerrar completamente un navegador o reiniciar el dispositivo, el operario previamente enrolado **debe** poder reabrir la PWA sin red, desbloquear SU perfil local y recuperar borradores, cola y formularios autorizados. Se requiere desarrollar una pantalla y máquina de estados de desbloqueo offline independientes de `GET /api/auth/me`; usar navegadores distintos no resuelve por sí solo este caso.
- El perfil offline no equivale a una sesión de servidor, no revalida permisos por sí mismo y no puede ejecutar operaciones centrales. Al recuperar conexión, si la cookie expiró, la API responde 401 o la identidad online no coincide con el autor, la sincronización se pausa **sin borrar ni reasignar** registros, y requiere login online del autor original y comprobación del contexto.
- El mecanismo exacto de desbloqueo seguro (credencial local robusta, cifrado de claves y, cuando el hardware lo permita, autenticador de plataforma) se diseñará y probará en OFF-03. Un PIN corto almacenado o verificable sin resistencia a ataques offline no es una seguridad aceptable por defecto. No reutilizar ni almacenar la contraseña del backend.
- Sin enrolamiento previo y sin contexto local autorizado, **no** será posible el primer ingreso offline; deberá realizarse al menos una preparación con conexión.
- Cierre/reinicio ordinario debe conservar los datos; cierre explícito de sesión bloquea la vista offline y limpia datos temporales, sin borrar capturas pendientes. La política de revocación/remoción del enrolamiento local se especificará y probará.
- El número de navegadores/perfiles simultáneos dependerá del hardware y sistema operativo reales. Hacer prueba de capacidad, memoria y cuota de almacenamiento antes de comprometer dispositivos.

## 4. Conectividad y sincronización

**Decisión:** automática al recuperar acceso efectivo a API y manual de respaldo, no modalidad exclusivamente checkpoint.

- No depender exclusivamente de `navigator.onLine`: comprobar disponibilidad de API y sesión válida; eventos `online` y retorno de visibilidad son disparadores de prueba, no prueba de conectividad.
- El motor corre en primer plano cuando la aplicación del navegador está abierta y desbloqueada; Background Sync es opcional, no garantía de entrega.
- Tras detectar red: reconciliar los intentos inciertos -> enviar la cola elegible -> recibir confirmaciones -> refrescar autorizaciones, contexto y formularios; evitar cambiar el contexto de una captura que ya se cerró.
- Incluir acción visible «Sincronizar ahora» con contador de pendientes, resultados, fallos y última sincronización exitosa.
- Si un navegador no vuelve a abrirse conectado, sus pendientes no serán enviados por otro navegador. Establecer rutina de revisión al volver al laboratorio/punto conectado y al final de turno.
- El laboratorio conectado Q-01 sirve como lugar natural de sincronización de Calidad; los analistas emplean **dispositivo móvil compartido** para capturas durante desplazamientos.
- Los cambios de setup de Conversión pueden aprovecharse para refrescar el contexto online, pero NO se impondrá una desconexión máxima por horas ni un checkpoint obligatorio.

## 5. Autorización offline sin vencimiento automático por turno (decisión de piloto)

**Decisión funcional confirmada:** no imponer un TTL fijo ni un bloqueo automático de captura al finalizar el turno durante el primer piloto; permitir que el operario continúe capturando en el contexto previamente preparado y sincronice al reencontrar conectividad.

Para no convertir esta decisión en permisos irrestrictos:

- El backend debe emitir un **snapshot/concesión firmada de alcance limitado** que vincule usuario original, dispositivo, máquinas/sectores permitidos, formulario/versión exacta y contexto original OT/asignación.
- **Sin caducidad funcional por tiempo durante el piloto** no implica autorización universal. El snapshot nunca permite agregar máquinas, usuarios, OT o formularios que no estuvieran en su alcance.
- Al sincronizar, el servidor verifica la integridad del snapshot, identidad y permisos según política vigente, revocaciones y validaciones industriales; una revocación puede impedir la aceptación automática.
- Conectarse permite actualizar/sustituir el snapshot, no reescribir capturas cerradas ni su identidad.
- El reloj local no es prueba suficiente para acreditar que una captura ocurrió antes de un cambio de turno o de asignación.
- Registrar para observabilidad: tiempo sin conectividad, antigüedad de pendientes, fallos, porcentaje de sincronización, conflictos y reintentos. La eventual política temporal se decidirá con evidencia del piloto, no de antemano.

**Riesgo aceptado de diseño, pendiente de control técnico:** sin límite temporal y sin un reloj/atestación confiable, el servidor no puede demostrar solo con la hora que envía el dispositivo cuándo se capturó realmente un dato. La validación y conciliación histórica requieren medidas de integridad adicionales; no presentar esta decisión como garantía de seguridad ilimitada.

## 6. Cambios de OT, asignación o turno durante desconexión

**Decisión funcional:** no descartar ni rechazar automáticamente por el solo hecho de que la asignación haya cambiado al momento de sincronizar. Permitir **conciliación tardía con aviso y auditoría**, cuando las comprobaciones lo hagan seguro.

Casos definidos:

1. **Misma OT, mismo producto/máquina; ajuste de cantidad:** candidato a aceptación central con `warning` de contexto cambiado, si pasan identidad original, snapshot, reglas del formulario y consistencia de la captura. No sobrescribir cantidades ni contexto original.
2. **Se cerró o reemplazó la asignación después de preparar la captura:** candidato a flujo de aceptación histórica controlada, siempre que pueda probarse el contexto inicial; conservar OT/asignación original, registrar recepción tardía y emitir alerta a supervisión/seguimiento. No atribuirlo a la asignación siguiente.
3. **Cambió producto, máquina, OT de referencia o faltan pruebas suficientes del contexto original:** mantener en `conflict` o `requires_review`, con aviso; jamás migrar silenciosamente el registro a otro producto u OT.
4. **Credenciales revocadas, discrepancia de identidad, captura duplicada con otro payload o fraude detectado:** no aceptar automáticamente; mantener evidencia local y estado de revisión/denegación según política de seguridad.

**Cambio de backend requerido en fases posteriores:** hoy `lock_active_assignment()` comprueba turno/fecha y estado ACTUAL de asignación. Una notificación en la UI no basta; se necesita una vía de aceptación histórica explícita con evidencia verificable, control de permisos, auditoría y tests de regresión. No debilitar el endpoint normal online ni reinterpretar `captured_at` basándose solo en el reloj local.

La advertencia al usuario debe explicar «Captura registrada sin conexión; el contexto de la asignación cambió antes de sincronizar». Mostrar si fue aceptada con observación o sigue pendiente de revisión.

## 7. Arquitectura técnica

- **PWA / Service Worker:** precache versionado únicamente de shell, bundles, fuentes, iconos y recursos públicos. Nunca cachear como estáticos los endpoints de auth, permisos, respuesta de API, órdenes ni datos de clientes.
- **IndexedDB:** store versionado para snapshots mínimos, borradores y outbox, con partición por navegador/usuario y contexto de dispositivo. Proteger los datos sensibles en reposo mediante cifrado y un mecanismo de desbloqueo local: tras reinicio no deben aparecer descifrados antes de autenticación local. Validar diseño criptográfico y protección de claves en OFF-03.
- **Persistencia real:** comprobar que el dispositivo admite IndexedDB, almacenamiento persistente y cuotas suficientes; solicitar `navigator.storage.persist()` cuando sea compatible, verificar su resultado, estimar cuota/uso y gestionar errores de almacenamiento. La persistencia no está garantizada si el operario borra los datos del sitio, usa modo incógnito o el SO/restablecimiento elimina el perfil. La PWA y cola no pueden prometer recuperación después de esos eventos: requieren una política operativa de protección/recuperación.
- **Aislamiento técnico:** la actual `device_key` está asociada al almacenamiento de cada **navegador**, no identifica por sí sola el equipo físico. Si se necesita un identificador único del equipo compartido, registrar una identidad física administrada adicional, sin fusionar colas de navegadores distintos.
- **Modelo de captura:** identificador UUID inmutable por captura lógica, autor original, navegador/dispositivo, contexto OT/asignación, máquina, formulario y versión, payload congelado, timestamps informativos, orden local y snapshot firmado/identificador.
- **Motor de sincronización:** enviar/reconciliar idempotentemente (`capture_id`), backoff, deduplicación, control de dependencias y alertas.
- **Backend FastAPI:** autoridad sobre permisos y persistencia; contrato nuevo para contexto offline y conciliación tardía que NO altere por defecto la semántica de capturas online existentes.
- **PostgreSQL 17:** fuente de verdad; metadata offline aislada en tablas/columnas o auditoría dedicadas, sin duplicar el esquema completo en cada navegador.
- **Power BI:** alimentarse solo de datos centrales confirmados; publicar vistas compatibles/estables, evitando romper el modelo semántico existente.

## 8. Outbox: estados y semántica

- `draft`: borrador local editable.
- `queued`: captura congelada y persistida, aún no central.
- `syncing`: envío en curso; no generar un nuevo ID.
- `uncertain`: no es posible saber si el backend registró; GET de reconciliación antes de repetir el mismo POST.
- `retry_wait`: fallo transitorio, conservar datos.
- `synced`: confirmación de recepción/persistencia central.
- `synced_warning`: confirmada con advertencia por contexto histórico o cambio observado.
- `requires_review`: necesita revisión central por cambio industrial/autoridad insuficiente.
- `conflict`: conflicto de integridad, versión incompatible, rechazo definitivo u otra contradicción que impide aceptación automática.

No eliminar pendientes sin una confirmación verificable. Una sincronización desde otro navegador no autoriza borrar la cola local. Conservar payload de los conflictos para revisión autorizada y exportación segura según política posterior.

## 9. Dependencias industriales y límites

- Una captura de producto terminado aún local NO autoriza liberación, despacho o ingreso de stock central.
- En Conversión, C-02 merece prueba de extremo a extremo de entrega a almacén y procedimiento operativo de contingencia.
- Calidad móvil: captar datos en campo; controles, revisiones y liberaciones se realizan online al llegar al laboratorio u otro punto conectado.
- El proceso nuevo de recepción de materia prima / Supply Chain comentado en la reunión NO forma parte del MVP offline actual; requiere desarrollo aparte.
- Si una captura depende de la existencia de una bobina, madre/crías, pallet, otro registro o receta, el motor debe respetar la dependencia o bloquear temporalmente la sincronización; no inventar claves centrales ni omitir reglas.
- Formularios específicos que requieran decisiones online permanecen fuera de captación offline hasta tener contrato aprobado.

## 10. Secuencia de entregables revisada

| Entregable | Producto | Criterio de salida |
| --- | --- | --- |
| OFF-01 V2 | Contrato, topología, prioridades, decisiones y riesgos (este documento) | Revisión y aprobación funcional |
| OFF-02 | PWA/Service Worker + IndexedDB + persistencia + indicadores de cola | Abre offline tras cierre/reinicio y mantiene datos locales sin exponerlos; prueba de almacenamiento |
| OFF-03 | Enrolamiento online, desbloqueo local offline tras reinicio, identidad por navegador y snapshot del backend | Aislamiento, recuperación de perfil, contexto verificable y login online necesario para sincronizar |
| OFF-04 | Sync Engine y primer piloto real de Calidad | Captura móvil -> reconexión -> registro central único |
| OFF-05 | Conversión C-01–C-07 por lotes/dependencias | Pruebas de multiusuario y C-02/almacén |
| OFF-06 | Bobinas y Rebobinado | Contingencia y genealogía segura |
| OFF-07 | QA integral, observabilidad, hardware y runbook de despliegue | Go/no-go validado |

**Piloto de Calidad:** la selección exacta del primer formulario se hará mediante matriz código/version/formulario/endpoints/dependencias/dispositivo, contrastada contra el código vigente; no afirmar que todo Calidad ya es apto. F6 deja de ser la prioridad funcional y puede reutilizarse como prueba técnica interna aislada, si resulta útil.

## 11. Pruebas de aceptación mínimas

1. Enrolar perfil online, descargar formularios, cerrar TOTALMENTE el navegador y reiniciar el dispositivo; reabrir PWA sin Internet, desbloquear perfil y recuperar borradores/capturas pendientes sin llamar a `/api/auth/me` para autorizar la vista local.
2. Guardar múltiples capturas en Calidad móvil sin Internet; recargar/cerrar/reabrir y recuperarlas.
3. Asegurar aislamiento entre Chrome, Firefox/Edge o perfiles de navegador independientes; comprobar bloqueo/desbloqueo por operario y que el perfil anterior no queda legible tras cierre/reinicio.
4. Confirmar que cada navegador envía únicamente su propia cola cuando se abre con conexión y el autor original se reautenticó online; probar sesión expirada, otra cuenta online activa, 401, red intermitente y acción manual.
5. Enviar el mismo `capture_id` repetidamente y obtener una sola captura central.
6. Perder señal entre POST y respuesta; reconciliar sin duplicados.
7. Mantener la captura offline sin vencimiento automático por turno; medir desfase y registrar alertas.
8. Cambiar cantidad o cerrar asignación durante desconexión; aceptar con advertencia SOLO si el servidor valida evidencia y reglas; de lo contrario revisión sin pérdida.
9. Cambiar producto/OT, revocar usuario o faltar permiso; bloquear la aceptación automática, conservar evidencia.
10. Validar que ninguna captura local aparezca como producto liberado, despacho confirmado o indicador central.
11. Garantizar que `GET /api/auth/me` y las respuestas privadas no se sirven de una caché pública; el desbloqueo offline no debe emitir cookies ni suplantar la respuesta autenticada del servidor.
12. QA aislado PostgreSQL 17, regresiones y casos de hardware antes de merge o despliegue.
13. Validar PWA offline sin modo incógnito, cuotas de IndexedDB, persistencia concedida/denegada, espacio agotado y comportamiento tras reinicio; prohibir éxito engañoso cuando una transacción no se pudo persistir.
14. Probar copia/robo del almacenamiento local y credencial de desbloqueo débil: el perfil no debe quedar accesible mediante un PIN simple sin protección; impedir nuevas capturas si la integridad del almacén se pierde.

## 12. Pendientes para el diseño técnico detallado, no decisiones del cliente ya aprobadas

1. **Reapertura sin conexión (DECIDIDA):** SÍ; debe funcionar tras cierre del navegador y reinicio del dispositivo, para un perfil preparado online. **Pendiente técnico, NO funcional:** elegir y validar un desbloqueo local seguro y cifrado por navegador, no equivalente a sesión online; definir recuperación y bloqueo ante pérdida de llave/datos.
2. **Dispositivos reales:** SO, navegadores disponibles, recursos y si los puntos C-01–C-07 son móviles o fijos; validar almacenamiento/caché y cuota.
3. **Prueba de contexto histórico:** diseño verificable para aceptación tardía sin confiar solo en el reloj local. Definir trazabilidad y revisión de alertas.
4. **Retención y protección de datos:** política de cifrado, limpieza, exportación segura y recuperabilidad si se daña o reinicia un dispositivo.
5. **Matriz de formularios:** elegir piloto de Calidad y definir lista exacta de capturas por punto y dependencias antes de programar adaptadores.

## 13. Restricciones de cambio y control de entrega

- Este PR es SOLO documentación, no modifica producción ni activa offline.
- OFF-02 y posteriores usarán ramas separadas, PRs pequeños, pruebas, revisión formal, aprobación de merge y despliegue por el responsable de VPS.
- Nunca guardar contraseñas ni tokens de sesión en IndexedDB, ni aceptar automáticamente datos de otro usuario.
- No ocultar conflictos, no transformar silenciosamente OT/producto/turno, no usar hora local como autoridad única.
- La aceptación de capturas tardías requiere implementación explícita y pruebas de autorización; no relajar silenciosamente reglas online actuales.

## 14. Contrato de reingreso offline tras cierre completo o reinicio (decisión confirmada)

**Precondiciones:** navegador normal compatible (no incógnito), PWA instalada/cargada antes con Internet, datos guardados correctamente y perfil del operario previamente enrolado en ese navegador. Cada navegador mantiene su propio perfil, credencial local y cola.

**Secuencia de referencia:**

1. **Online inicial:** el operario ingresa con credenciales corporativas; se valida su identidad y alcance de máquinas/formularios, se descarga un snapshot mínimo y se enrola un desbloqueo local protegido. Se confirma que los recursos PWA y el almacenamiento están disponibles antes de indicar «Listo para trabajar offline».
2. **Cierre/reinicio:** el navegador se cierra completamente o se reinicia el dispositivo; el estado en memoria desaparece y no se reutiliza una sesión JavaScript previa.
3. **Arranque offline:** el Service Worker carga los recursos permitidos desde caché estática. El frontend muestra `offline_locked`, no «sesión online autenticada». Si falta perfil o datos verificados, falla cerrado.
4. **Desbloqueo local:** se verifica el mecanismo previamente enrolado y se recupera la clave local que protege las capturas del usuario; pasa a `offline_unlocked` con permisos del snapshot acotado, sin acceder a APIs centrales.
5. **Captura:** permite solo formularios autorizados por snapshot; persistencia transaccional de borradores y outbox. La hora local se registra como referencia informativa, no es prueba de vigencia industrial.
6. **Reconexión:** comprobar API, `GET /api/auth/me` y la correspondencia exacta entre usuario online, usuario enrolado y autor de cada captura. Si no hay sesión válida, solicitar login online del mismo usuario; no enviar con la cookie de otro operario. Luego reconciliar por `capture_id` y aplicar reglas de contexto/historial y alertas.
7. **Cierre de sesión deliberado:** bloquear perfil local y limpiar claves descifradas de memoria; conservar la cola persistente protegida hasta sincronización o gestión autorizada, sin eliminarla automáticamente.

**Estados de interfaz añadidos:** `offline_locked`, `offline_unlocked`, `online_reauth_required`, `online_verified` y `offline_data_unavailable`. Ninguno de los estados `offline_*` implica autorización de backend para mutaciones centrales. Diferenciar claramente «guardado localmente» de «sincronizado».

**Controles de seguridad obligatorios:** protección criptográfica en reposo, resistencia razonable a ataque de fuerza bruta del mecanismo local, no persistencia de contraseñas/cookies/tokens de sesión, no compartir autores entre navegadores, no sincronizar con identidad distinta, comprobación de integridad de snapshots, y ensayos de pérdida de almacenamiento y compatibilidad por equipo. No atribuir seguridad fuerte a un PIN de cuatro dígitos ni a la separación de navegadores por sí sola.

**Límite explícito:** reabrir tras reinicio ordinario **sí es requisito**; recuperar capturas tras borrar el perfil, limpiar datos del sitio, restablecer el dispositivo o fallo físico de almacenamiento **no está garantizado por IndexedDB**. Requiere procedimientos operativos de respaldo y respuesta a incidentes.

**Referencias técnicas de validación:**
- MDN: [Storage quotas and eviction criteria](https://developer.mozilla.org/en-US/docs/Web/API/Storage_API/Storage_quotas_and_eviction_criteria).
- MDN: [StorageManager.persist()](https://developer.mozilla.org/en-US/docs/Web/API/StorageManager/persist).
- MDN: [Web Authentication extensions](https://developer.mozilla.org/en-US/docs/Web/API/Web_Authentication_API/WebAuthn_extensions) — compatibilidad de funcionalidades avanzadas de autenticadores sujeta a prueba de navegador/dispositivo.

**Cierre propuesto OFF-01 V2:** alcance de captación, topología, prioridades y reingreso offline tras cierre/reinicio definidos; sincronización automática + manual, sin TTL de captura por turno durante piloto, aceptación histórica condicionada y navegadores independientes. La implementación concreta de desbloqueo local y cifrado es un gate de OFF-03; el PR documental queda en DRAFT hasta revisión y autorización formal. No ejecuta merge, migraciones ni despliegue.
