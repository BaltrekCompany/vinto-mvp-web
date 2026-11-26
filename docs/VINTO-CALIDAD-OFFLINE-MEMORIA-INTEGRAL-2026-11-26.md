# VINTO MVP — Memoria integral de implementación de Calidad Offline
**Cierre técnico y funcional:** 26 de noviembre de 2026  
**Proyecto:** VINTO MVP Web · Calidad · Bobinas y Rebobinado  
**Repositorio:** [BaltrekCompany/vinto-mvp-web](https://github.com/BaltrekCompany/vinto-mvp-web)  
**Versión productiva validada:** `54df1defedcf91e12d50c497e9b44a37ad3e9a50` (PR [#256](https://github.com/BaltrekCompany/vinto-mvp-web/pull/256))  
**Estado:** desarrollo de **Calidad Offline** cerrado funcionalmente; despliegue productivo y verificación de pantalla confirmados. **No equivale a puesta en marcha oficial de planta ni a certificación para todos los dispositivos físicos.** Los datos de las pruebas son ficticios.  
**Alcance documental:** reconstrucción de decisiones, código, incidencias, ensayos y entregas vinculadas al proyecto; las ramas experimentales en Draft se distinguen de los PR fusionados realmente en `main`.

## 1. Resumen ejecutivo

Se incorporó captura de controles de Calidad sin conexión al MVP de VINTO, integrada en los **formularios originales de la plataforma**, no como una segunda aplicación industrial. Un usuario autorizado prepara los formularios con conexión; el dispositivo conserva sus contextos y borradores cifrados; el operario puede reabrir la interfaz preparada sin Internet, completar mediciones y dejarlas en cola. Una vez recuperada la conectividad y la sesión del **autor original**, el envío se ejecuta automáticamente; el botón manual es una alternativa. El servidor revalida permisos, versión, identidad y contexto, y registra únicamente capturas operativamente válidas.

El alcance comprende **10 formularios**: por máquina, P1-18, P1-22, P1-26 y P1-27; por bobina/madre, P1-19, P1-20, P1-21, P1-24, P1-25 y P1-28, **solo donde exista oferta publicada y grant efectivo**. Cada bobina pendiente de cada máquina autorizada se trata individualmente, incluida una pluralidad de madres de rebobinado identificadas por UUID real. Las crías sirven para derivar la madre y **no se presentan como controles de madre independientes**. Se implementó unicidad de formulario por bobina y una presentación comprensible de «Formulario realizado», «Pendiente de sincronización», «Requiere revisión» y «No preparado».

**Límite industrial:** liberación, rechazo, aprobación, cambios de OT, asignaciones y concesiones de permisos permanecen online. La sincronización de una captura de Calidad **no libera ni aprueba** una bobina.

## 2. Decisiones de alcance y operación

Origen: contrato [OFF-01 V2, PR #184](https://github.com/BaltrekCompany/vinto-mvp-web/pull/184) y acuerdos posteriores.

- Prioridad elegida: **Calidad móvil compartida**, seguida más adelante por Conversión y Bobinas/Rebobinado. La finalización de Calidad Offline no implica que esos otros frentes ya operen offline.
- Preparación inicial **online** y captura local **offline**; sincronización automática por retorno de conectividad / reactivación con sesión válida y respaldo manual.
- Dispositivos compartidos, perfiles asociados al usuario original y navegador. Dos navegadores no comparten necesariamente identidad ni cola; no sustituir una identidad por otra.
- Reingreso con el navegador cerrado/reabierto o tras reinicio, sujeto a que PWA y datos del sitio se conserven. El borrado de IndexedDB/datos del sitio o daño físico del equipo **no** queda resuelto por el sistema.
- No establecer vencimiento obligatorio por turno para los borradores piloto; las autorizaciones firmadas sí tienen expiración y el servidor verifica de nuevo al registrar.
- Ante cambio de contexto histórico o ausencia de permisos, retener la captura para revisión y no atribuirla silenciosamente a otra OT, autor o bobina.
- Captura operativa automática tras validación del backend, **sin aprobación humana previa de la sincronización** (decisión [#245](https://github.com/BaltrekCompany/vinto-mvp-web/issues/245), OFF-04.8).

## 3. Arquitectura implementada

```text
Sesión VINTO Online (usuario, permisos, navegador/dispositivo)
    |
    +-- Consulta ofertas de Calidad publicadas y bobinas pendientes
    +-- Enrolamiento del dispositivo y autoridad CAPTURE firmada Ed25519
    |   (usuario + dispositivo + máquina + formulario + versión + grant)
    |
    v
PWA / interfaz original de Calidad
    +-- Caché de interfaz y recursos públicos (no cookies/API/secretos)
    +-- Perfil y bóveda local cifrada AES-GCM + PBKDF2
    +-- IndexedDB: preparaciones, borradores y cola por autor/dispositivo
    +-- Autoguardado / validación / congelado inmutable de captura
    |
  [Sin conexión: registrar, guardar, cerrar/reabrir]
    |
    v
Reconexión + sesión online del autor original
    +-- Sincronización automática, botón manual opcional
    +-- POST /api/offline/captures
    +-- GET de conciliación por capture_id en caso incierto
    |
    v
FastAPI / PostgreSQL 17
    +-- Verifica usuario, grant vigente, versión y contexto bobina
    +-- Guardas de idempotencia y unicidad por bobina/formulario
    +-- Inserción en vinto_txn.capture solo tras validación
    +-- ACK operativo / 409 duplicado / 403 denegación / 202 revisión
    |
    v
Calidad Online: historial y decisiones posteriores por separado
```

### 3.1 Identidad, login y autorización — qué se cambió y qué NO

El **login principal de VINTO no fue sustituido por un login offline independiente**. Para preparar y sincronizar se mantiene la autenticación central por sesión/cookie (por ejemplo, `GET /api/auth/me`). Lo nuevo fue una **segunda operación, local y delimitada**: enrolar el navegador/dispositivo con la sesión autenticada y desbloquear con una **frase local fuerte** la bóveda cifrada de ese usuario/dispositivo. Desbloquear la bóveda **no crea una cookie de sesión ni concede acceso al servidor**. Si la sesión expiró o el usuario autenticado no es el autor de la captura, la sincronización se detiene y preserva el pendiente.

Durante el desarrollo QA se adaptaron login/me/logout, cookie QA segura, `Origin`/`CSRF` y conexiones de identidad separadas para que el cliente móvil de ensayo pudiera autenticarse en un único origen HTTPS, **sin reutilizar credenciales ni permisos de producción** ([#241](https://github.com/BaltrekCompany/vinto-mvp-web/issues/241), [PR #242](https://github.com/BaltrekCompany/vinto-mvp-web/pull/242)). Esos cambios fueron parte del **arnés y entorno QA**; no deben describirse como migración del login productivo a otro proveedor ni como modificación general de contraseñas o roles.

La implementación final usa [`backend/app/quality/offline_router.py`](../backend/app/quality/offline_router.py): `POST /api/offline/quality/enroll` y `POST /api/offline/quality/capture-authority`; exige dispositivo activo, permiso `quality.capture`, grant efectivo por máquina/formulario y versión publicada. El permiso se comprueba de nuevo al sincronizar en [`offline_sync_router.py`](../backend/app/quality/offline_sync_router.py). Se mantiene el motor MF-13, alcance por sectores y separación de funciones. **No se otorgaron grants nuevos para sortear errores de preparación** y la autoridad de lectura no se confundió con la de captura.

### 3.2 Persistencia y protección

- PWA/Service Worker: disponibilidad de la interfaz previamente preparada, con caché de recursos estáticos y sin almacenar respuestas de API, credenciales o administración en caché ([OFF-02 PR #186](https://github.com/BaltrekCompany/vinto-mvp-web/pull/186)).
- Criptografía local: clave AES-256-GCM, derivación PBKDF2-SHA256 para protegerla con frase local, datos de identidad/contexto asociados criptográficamente y IndexedDB por usuario/dispositivo ([OFF-03A PR #187](https://github.com/BaltrekCompany/vinto-mvp-web/pull/187)). No es un sustituto de credenciales online ni garantía ante eliminación del almacenamiento.
- Autorización: alcances firmados Ed25519 emitidos por servidor y verificados en cliente; pin de clave pública; operaciones de consulta y CAPTURE separadas, expiración y versiones ([#189](https://github.com/BaltrekCompany/vinto-mvp-web/pull/189), [#190](https://github.com/BaltrekCompany/vinto-mvp-web/pull/190)).
- Definiciones de Calidad: paquetes firmados, hashes, versión, campos, opciones y reglas; persistencia cifrada y renovación atómica para evitar mezclas de snapshots/definiciones ([#191](https://github.com/BaltrekCompany/vinto-mvp-web/pull/191), [#192](https://github.com/BaltrekCompany/vinto-mvp-web/pull/192), [#225](https://github.com/BaltrekCompany/vinto-mvp-web/pull/225)).
- Edición/cola: borradores cifrados, bloqueo por revisión, autoguardado, inmutabilidad después de congelar para envío, `capture_id` estable, estados recuperables y conciliación central. No borrar silenciosamente borradores viejos ni volver a utilizar un ID con otro contenido.

### 3.3 Formas y políticas

| Alcance | Formularios | Regla |
|---|---|---|
| Calidad por máquina | P1-18, P1-22, P1-26, P1-27 | Controles generales; repetibles según necesidad hasta definir periodicidad formal |
| Calidad por bobina / madre | P1-19, P1-20, P1-21, P1-24, P1-25, P1-28 | **Una captura registrada por par `(bobbin_id, form_code)`**, sujeta a oferta y permiso |
| Rebobinado | Madre técnica de P1-07 | Identidad por UUID; crías no se convierten en controles duplicados |

La existencia de diez códigos admitidos **no significa** que cada operario, máquina o madre tenga diez controles. La lista depende de permisos efectivos y formularios publicados.

## 4. Cronología de construcción y ensayos

| Fecha | Fase / referencias | Entrega y aprendizaje |
|---|---|---|
| **16–17 nov** | [OFF-01 V2 #184](https://github.com/BaltrekCompany/vinto-mvp-web/pull/184) | Contrato funcional: móvil compartido, recuperación sin red, autor original, sync automática+manual, centralización de decisiones |
| **17 nov** | [OFF-02 #186](https://github.com/BaltrekCompany/vinto-mvp-web/pull/186) | Base PWA/IndexedDB, caché, arranque offline y pruebas Chrome |
| **17 nov** | [OFF-03A/03B #187–190](https://github.com/BaltrekCompany/vinto-mvp-web/pull/187) | Bóveda cifrada, perfil local, enrolamiento, identidad, firma Ed25519 y validación tras reinicio |
| **17–18 nov** | [OFF-03C #191–193](https://github.com/BaltrekCompany/vinto-mvp-web/pull/191), [#225](https://github.com/BaltrekCompany/vinto-mvp-web/pull/225) | Definiciones autorizadas versionadas, consulta cifrada, diagnóstico móvil y renovación atómica |
| **17–20 nov** | [OFF-03D](https://github.com/BaltrekCompany/vinto-mvp-web/pull/195) | Preparación QA aislada: HTTPS, PostgreSQL 17, roles/ACL de mínima atribución, migraciones, restore y barreras para evitar escrituras productivas |
| **18–19 nov** | [OFF-04.1 #227](https://github.com/BaltrekCompany/vinto-mvp-web/pull/227), [OFF-04.2 #229](https://github.com/BaltrekCompany/vinto-mvp-web/pull/229), [R2 #231](https://github.com/BaltrekCompany/vinto-mvp-web/pull/231) | Editor sintético, cifrado de borradores, cola congelada/atómica y recuperación sin tocar capturas industriales |
| **19 nov** | [OFF-04.3 #233](https://github.com/BaltrekCompany/vinto-mvp-web/pull/233), [OFF-04.4 #235](https://github.com/BaltrekCompany/vinto-mvp-web/pull/235) | Sync idempotente con servidor simulado, reintentos/ACK incierto; receptor FastAPI y conciliación aislada |
| **19–20 nov** | [OFF-04.5 #237](https://github.com/BaltrekCompany/vinto-mvp-web/pull/237), [#242](https://github.com/BaltrekCompany/vinto-mvp-web/pull/242) | E2E offline con login QA, HTTPS, cookie/CSRF, PostgreSQL aislado y cliente móvil sintético |
| **20–24 nov** | [OFF-04.6 #244](https://github.com/BaltrekCompany/vinto-mvp-web/pull/244), [OFF-04.8 #245](https://github.com/BaltrekCompany/vinto-mvp-web/issues/245), [#246](https://github.com/BaltrekCompany/vinto-mvp-web/pull/246) | Lote de diez controles, QA física controlada, paso desde recibo técnico a **registro operativo automático**; pilotos por formulario y evolución v6/v7 |
| **25 nov** | [PR #250](https://github.com/BaltrekCompany/vinto-mvp-web/pull/250) | Integración final en **pantallas originales**, endpoints de Calidad, bóveda y cola; primer merge productivo `06f17d6a` |
| **25 nov** | [Issue #251](https://github.com/BaltrekCompany/vinto-mvp-web/issues/251), [PR #252](https://github.com/BaltrekCompany/vinto-mvp-web/pull/252) | Corregido reloj de autoridad y preparación automática al desbloquear; merge `570afab4` |
| **25 nov** | [PR #253](https://github.com/BaltrekCompany/vinto-mvp-web/pull/253) | Navegación por bobinas/máquinas, títulos humanos y OT; merge `d31bf0b7` |
| **25 nov** | [PR #254](https://github.com/BaltrekCompany/vinto-mvp-web/pull/254) | Unicidad y 409 online/offline, «Formulario realizado», conservación histórica; merge y despliegue `cc85f864` |
| **26 nov** | [Issue #255](https://github.com/BaltrekCompany/vinto-mvp-web/issues/255), [PR #256](https://github.com/BaltrekCompany/vinto-mvp-web/pull/256) | Todas las bobinas pendientes y madres, preparación por par, estados completos y UX; merge/despliegue `54df1def` y validación visual del usuario |

**Nota de trazabilidad:** varios PR iniciales fueron *Draft apilados* y laboratorios aislados; no deben sumarse como despliegues individuales de producción. Los merges confirmados de la integración final son #250, #252, #253, #254 y #256.

## 5. Registro de errores, causas y soluciones

| Incidente / referencia | Causa investigada | Resolución o estado final |
|---|---|---|
| Service Worker no iniciaba en `http://[::1]` (OFF-02) | Comprobación rígida de host en vez de contexto seguro | Se usó `window.isSecureContext`; Chrome con reapertura offline PASS |
| Reingreso/cache y fixtures Chrome de OFF-03 | URL de contingencia o harness no correspondía a recurso precacheado; algunas aserciones usaban rótulos erróneos | Se corrigieron pruebas y navegación, sin desactivar cifrado/firma |
| Renovación de paquete → conflicto (OFF-03C.4; [#248](https://github.com/BaltrekCompany/vinto-mvp-web/issues/248)) | Inconsistencia entre snapshot y paquetes históricos, incluyendo revoke→regrant; se observó `OFFLINE_RENEWAL_CONFLICT` | Renovación atómica y pruebas; **issue histórico #248 permanece abierto en GitHub**. No afirmar cierre total de todos los casos sin evidencia independiente |
| Cola laboratorio: H1–H4 ([#230](https://github.com/BaltrekCompany/vinto-mvp-web/issues/230)) | Carrera entre stores, pendiente corrupto, reutilización de ID y render de draft en lugar de snapshot congelado | Endurecimiento sintético OFF-04.2-R2 con CAS, transacción y cuarentena; no reutilizar datos de laboratorio como captura industrial |
| Envío confirmado técnicamente, no registrado operativamente (OFF-04.7/04.8) | El `capture_receipt` anterior no equivalía a registro `vinto_txn.capture` | Ruta de registro operativo automático y transaccional + verificación central; revisión para conflictos, sin aprobación previa |
| Segunda captura con botón «Guardar» inhabilitado ([#249](https://github.com/BaltrekCompany/vinto-mvp-web/issues/249)) | Estado `disabled` heredado de editor anterior congelado | Corregido en evolución del piloto; se probaron nuevos editores, bloqueo del anterior y actualización tras ACK. Mantener issue histórico como antecedente, sin asegurar su cierre administrativo |
| Estado visual tras autosincronizar (OFF-04.8 v7) | La lista local no refrescaba siempre al llegar ACK automático | Ajuste de actualización/reconciliación; se diferenció «Sincronizado» del pendiente |
| `OFF048_CAPTURE_SCOPE_EXPIRED` en piloto productivo ([#251](https://github.com/BaltrekCompany/vinto-mvp-web/issues/251)) | La validación usaba `Date.now` del dispositivo sin calibrar frente a autoridad emitida por servidor | PR #252 usa cabecera `Date` de respuesta autenticada para calibrar, sin omitir caducidad, firma ni permisos |
| Formularios no aparecían automáticamente ([#251](https://github.com/BaltrekCompany/vinto-mvp-web/issues/251)) | Integración original exigía preparar cada formulario manualmente | PR #252 prepara al desbloquear, conserva anteriores y ofrece selector manual |
| Navegación confusa (PR #253) | Listado por códigos técnicos en vez de contexto operacional | Agrupación por bobina o máquina, OT/línea y títulos legibles |
| Repetición de P1-24 / borradores múltiples (PR #254) | Faltaba guardia central de unicidad por bobina/formulario y proyección única de controles locales | Advisory lock + verificación transaccional; duplicado nuevo → `409 QUALITY_BOBBIN_FORM_ALREADY_SUBMITTED`; mismo `capture_id` idempotente. Borradores/capturas históricas conservados |
| MP3 mostraba bobina 5 pero no 4 ([#255](https://github.com/BaltrekCompany/vinto-mvp-web/issues/255)) | `bobbins.find()` elegía una bobina por máquina/formulario | PR #256 enumera **todas** las combinaciones autorizadas |
| COPASA madre 25 y 5 formularios faltantes (#255) | Offline recibía crías sin proyectarlas a madre; digest exigía `INNER JOIN quality_release`, inexistente en madres | Proyección por `mother_bobbin_id` y `LEFT JOIN quality_release` para madres, sin aceptar crías como destino. Los cinco 403 de COPASA P1-19/20/21/24/25 quedaron explicados |
| Múltiples madres con etiqueta «25» | Etiqueta visible no es identificador único | Separación por UUID y sufijo identificador visible ante colisión |
| Orden «1,10,11…» | Orden lexicográfico de títulos | Orden numérico mediante `localeCompare(...,{numeric:true})` |
| Bobinas con todo registrado desaparecían | Solo se renderizaban preparaciones cifradas locales | Proyección de controles realizados basada en historial autorizado, sin abrir formulario duplicado |
| Historial HTTP 503 durante preparación | Consulta de historial completa se declara indisponible; se prioriza no emitir capturas erróneas | Comportamiento **fail-closed** validado: nuevos pares no reciben autoridades; borradores locales previos pueden permanecer abribles, pero backend controla duplicados al sincronizar. Mensaje técnico pendiente de humanizar |
| Bobina F3 cambia a liberada/rechazada tras preparación | Digest incorpora `quality_status` | Respuesta 202 `bobbin_context_changed`, sin insertar captura; comportamiento intencional previo que exige revisión del caso |
| Fallos de CI durante PR #256 | Aserción test antigua, comparación cross-realm, salto de línea en Python, tipo TS implícito | Corregidos en la misma rama; **4 workflows / 6 check-runs PASS** en el SHA final |

**Importante:** no confundir borradores locales repetidos con duplicados de capturas operativas ya enviadas. Tampoco se eliminan de oficio los duplicados históricos de los ensayos.

## 6. Seguridad, escenarios negativos y permisos

Controles implementados y validados:

1. **Una identidad original:** la sesión online del remitente debe coincidir con el autor de la captura; la frase local únicamente descifra datos. Separación por navegador/dispositivo.
2. **Privilegios mínimos:** grants efectivos MF-13, sector, máquina, formulario y versión, con negativa 401/403 ante falta de sesión o permiso. En los ensayos se revocó un grant individual antes de sincronizar: backend devolvió **403 y 0 capturas nuevas** tanto para bobina como para madre.
3. **Integridad:** Ed25519 firmado por backend para CAPTURE, pin de clave pública, firma temporal, contexto de bobina y digest. Datos locales cifrados AES-GCM con AAD; no almacenar contraseñas centrales/cookies en IndexedDB.
4. **Idempotencia:** capturas `capture_id` estables; ACK/GET conciliación; carreras concurrentes sobre misma bobina+formulario producen un único 201 y restantes 409; el reintento del mismo ID no genera doble escritura.
5. **Concurrencia y pérdida de red:** la cola se conserva con reintentos, recuperación por reinicio y estados de revisión/conflicto. Fallos del historial de otro dispositivo no autorizan nuevas capturas por suposición.
6. **Separación industrial:** permisos de capturar no otorgan permiso de liberar/rechazar; las decisiones de Calidad permanecen online.
7. **Compatibilidad de firmas anteriores:** el cambio de digest para madres en #256 **mantiene idéntico el cálculo de bobinas F3**; tres capturas preparadas con build anterior pudieron sincronizarse en QA tras upgrade.

No registrar semillas privadas, frases locales, cookies, identidades personales, URLs firmadas temporales ni credenciales en esta documentación.

## 7. QA: alcance, cifras y evidencias

### 7.1 QA funcional PR #254 (25 nov)
- Validación del formulario único por bobina con creación 201 y duplicado 409.
- Carrera de tres solicitudes: un 201, dos 409; idempotencia mismo ID 200; formulario distinto permitido y controles por máquina repetibles.
- Validación móvil en producción de P1-24: una sola tarjeta «Formulario realizado», borradores anteriores conservados.

### 7.2 QA completo PR #256 (26 nov)
Evidencia reportada por Codex en VPS: `/home/ubuntu/off048-transfer/qa-pr256-20261126/` y `/home/ubuntu/off048-transfer/qa-pr256-visual-20261126/` (rutas internas; acceso mediante operación VPS autorizada).

| Métrica QA de cobertura completa | Resultado |
|---|---:|
| Bobinas pendientes MP1 | 17 |
| Bobinas pendientes MP3 | 7 |
| Madres COPASA con crías pendientes | 2 |
| Combinaciones esperadas | 153 |
| Preparaciones nuevas | 126 |
| Formularios ya realizados | 27 |
| Errores / omitidas por límite | 0 / 0 |

**11 pruebas funcionales PASS:** todas las bobinas, madres separadas por UUID, permisos publicados, sincronización automática 201, colisión entre dispositivos 409, tres capturas antiguas aceptadas tras actualización, 16 borradores existentes reutilizados, revocaciones individuales 403, cambios de estado, límite (prueba sintética de 1.500 pares: 1.000 procesados / 500 omitidos y declarados), contadores y CI.

**6 validaciones visuales PASS** sobre `f13249d7`: todas las pendientes, dos madres misma etiqueta diferenciadas, orden numérico, bobina MP1-2 completada íntegramente visible sin borradores, «No preparado» ante 403 intencional, historia 503 fail-closed. En este ensayo específico se contabilizaron **147 combinaciones** (118 nuevas, 28 realizadas, 1 fallo provocado); **no** confundir con las 153 del ensayo de cobertura anterior.

### 7.3 Verificación productiva final (26 nov)
- Release anterior #254: `cc85f864a32c53cffb67a773b39fd9c4de19934a`.
- Release final #256: `54df1defedcf91e12d50c497e9b44a37ad3e9a50`, desplegado a las **18:08:19 GMT-5** con `D2_OPS_GATE_ACTIVATE=PASS`.
- Artefacto GitHub Actions para merge #256: workflow [#45908146919](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/45908146919), ZIP SHA-256 `6440a618328b061c0aebd68d124e30fd05e4f0feb98ff773c72a187e3bb91dd2`, TAR SHA-256 `d7159085670c9981ad450687f63e8583353298a3978f15e4a616b7373aee5f06`.
- Backup nuevo previo: `vinto-mvp-vinto_piloto-20261126-230720-1977717.dump`, SHA-256 `1b1e5e8bd22017135eb84f36c7acaa94f6ebae7612ff198b2753d1cc4d146594`, restauración aislada **53 tablas PASS**. Rollback disponible al SHA `cc85f864`.
- Recuento antes/después: **115 capturas, 44 bobinas, 6 pending / 9 rejected / 23 released, 8 excedentes históricos por duplicados, 31 migraciones y 53 tablas**, sin cambios atribuibles al despliegue. Sin modificaciones de configuración Nginx, `backend.env`, permisos o clave Ed25519; servicios/HTTPS/health en 200.
- Pantalla de usuario final: captura recibida en la conversación confirma **MP3 bobinas 4 y 5 separadas** con P1-20/21/24/25 según autorización, «Formulario realizado» para P1-24 de bobina 4, y encabezado visible de **Bobina 25 · COPASA**. La auditoría SQL y QA cubrieron también MP1 bobina 2 y la identidad técnica de la madre. La captura final **no muestra todos los formularios de la madre ni la totalidad de MP1**: no presentar esa imagen parcial como prueba visual de pantallas no capturadas.
- QA aislada desactivada tras ensayos; datos ficticios conservados.

### 7.4 Trazabilidad de evidencias de la VPS
- `/home/ubuntu/off048-transfer/audit-255-20261126/RESULTADO.md` — auditoría read-only de cobertura, bobinas y permisos.
- `/home/ubuntu/off048-transfer/qa-pr256-20261126/` — pruebas funcionales y SQL.
- `/home/ubuntu/off048-transfer/qa-pr256-visual-20261126/` — capturas y pruebas visuales.
- `/home/ubuntu/off048-transfer/predeploy-pr256-20261126/RESULTADO.md` — artefacto, compatibilidad y preflight.
- `/home/ubuntu/off048-transfer/deploy-pr256-20261126/` — logs, respaldo y postdeploy.

Esas rutas son **referencias técnicas internas de la VPS**, no documentos públicos ni adjuntos automáticamente a GitHub.

## 8. Diferencia entre QA, despliegue y uso oficial

**Al 26 nov** se han completado el desarrollo, integración en `main`, CI, QA aislada, despliegue productivo y validación visual representativa. La aplicación **aún no está siendo utilizada oficialmente** por los operarios y los datos existentes son de prueba, según decisión del proyecto.

No se realizó una habilitación masiva de dispositivos de planta ni una certificación de uso industrial en todos los equipos. Cuando se decida el inicio oficial, corresponde definir capacitación, inventario de dispositivos/navegadores, alta de operarios, procedimientos ante pérdida/borrado del dispositivo, política de retención de datos ficticios y supervisión del primer ciclo real. Esto es **transición operativa posterior**, no una falla del incremento de Calidad Offline.

## 9. Observaciones de producto pendientes (no bloquean cierre técnico)

1. Traducción del error `offline_quality_history_unavailable` a un mensaje entendible para el operario.
2. Lista de errores de preparación actualmente limita la vista a las primeras ocho entradas; ofrecer detalle completo/expandible.
3. Mejoras de recuperación cuando falla una consulta aislada del historial: mantener seguridad fail-closed, evitar ocultar causas y no autorizar envíos sin comprobación.
4. Política de periodicidad para los cuatro controles por máquina (por turno/día/muestra), separada de la unicidad estricta por bobina.
5. Tratamiento contextual `202 bobbin_context_changed` si una F3 es liberada/rechazada tras la captura offline, previa definición funcional; **no eliminar** esta protección sin acuerdo.
6. Issue histórico [#248](https://github.com/BaltrekCompany/vinto-mvp-web/issues/248) sobre revoke→regrant permanece abierto y debe revisarse antes de extrapolar la arquitectura a otros sectores.
7. Límite de preparación automática de **1.000 pares por sesión**; si se supera, los omitidos se contabilizan. No prometer preparación ilimitada de una sola vez sin adaptar rendimiento/paginación.

## 10. Registro de decisiones y próximas líneas de trabajo

**Cierre de esta entrega:** Calidad Offline terminado funcionalmente para las máquinas y bobinas autorizadas y desplegado con versión productiva identificada. El sistema protege al autor, preserva borradores y colas cifradas, exige autenticación/permiso al sincronizar, muestra múltiples bobinas y madres, y evita nuevos duplicados registrados de formulario por bobina.

**Siguiente línea de planificación (todavía no desarrollada aquí):** evaluar **Conversión Offline**, porque fue el segundo frente priorizado en OFF-01 V2; definir formularios concretos C-01–C-07, dependencias de OT/bobinas consumidas y cómo se resuelve la disponibilidad de catálogos/órdenes offline. Alternativamente, primero realizar capacitación y checklist de puesta en marcha de Calidad en dispositivos reales; no afirmar que la elección ya fue tomada.

Para comunicación ejecutiva se recomienda compartir **este enlace de GitHub** y un resumen en el correo, reservando el detalle técnico, evidencia y enlaces históricos para quienes deseen profundizar.

## 11. Referencias principales

- [Contrato funcional OFF-01 V2 — PR #184](https://github.com/BaltrekCompany/vinto-mvp-web/pull/184)
- [PWA / IndexedDB — PR #186](https://github.com/BaltrekCompany/vinto-mvp-web/pull/186)
- [Firma y autorización — PRs #187–#192](https://github.com/BaltrekCompany/vinto-mvp-web/pull/189)
- [Renovación de definiciones — PR #225](https://github.com/BaltrekCompany/vinto-mvp-web/pull/225)
- [Sincronización operativa automática — Issue #245](https://github.com/BaltrekCompany/vinto-mvp-web/issues/245)
- [Integración definitiva en VINTO — PR #250](https://github.com/BaltrekCompany/vinto-mvp-web/pull/250)
- [Reloj y preparación automática — PR #252](https://github.com/BaltrekCompany/vinto-mvp-web/pull/252)
- [Navegación por bobina/máquina — PR #253](https://github.com/BaltrekCompany/vinto-mvp-web/pull/253)
- [Unicidad/historial — PR #254](https://github.com/BaltrekCompany/vinto-mvp-web/pull/254)
- [Auditoría de cobertura — Issue #255](https://github.com/BaltrekCompany/vinto-mvp-web/issues/255)
- [Cobertura completa — PR #256](https://github.com/BaltrekCompany/vinto-mvp-web/pull/256)
- [Build final GitHub Actions #45908146919](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/45908146919)

---
**Control de documento:** elaborado a partir de issues/PR de GitHub, reportes de Codex aportados en las conversaciones y evidencia visual comunicada por el usuario. El historial de ramas experimentales y de pruebas puede contener pasos no desplegados; **el estado productivo comprobado es el commit `54df1def`**.
