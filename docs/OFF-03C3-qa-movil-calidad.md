# VINTO OFF-03C.3 — QA de dispositivo compartido de Calidad

**Fecha:** 17-nov-2026. **Estado:** protocolo y diagnóstico técnico preparados; **prueba física NO ejecutada**, despliegue HTTPS de ensayo NO autorizado/realizado.  
**Base:** OFF-03C.2 PR #192 (Draft); depende de #191, #190, #189, #188, #187, #186 y contrato #184.  
**Objetivo:** distinguir CI de un verdadero reinicio del equipo, medir persistencia del navegador y documentar aceptación/rechazo del módulo de **solo lectura**.

## Entregable OFF-03C.3

La interfaz pública `/offline.html` incluye un control **Comprobar preparación técnica** y `/offline-device-qa.js` precacheado por Service Worker versión `vinto-off03c4-static-v1`.

El diagnóstico funciona **sin red ni backend**, no requiere desbloquear la frase local, no usa cookies/fetch, no almacena ni modifica registros y no revela IDs, contraseñas, concesiones, etiquetas de formularios, capturas ni claves. Comprueba:

| Control | Aprobación técnica | Si no se cumple |
|---|---|---|
| Contexto seguro | `window.isSecureContext` | Bloqueado: usar origen HTTPS |
| Service Worker | La página tiene controlador activo | Bloqueado: instalar/abrir antes online |
| Recursos de caché | Existen caché de versión exacta y seis archivos públicos precargados | Bloqueado: volver online; no borrar perfil ni concesiones |
| IndexedDB | Base existente `vinto-off03a-profiles-v1` v3 y stores esperados | Bloqueado: revisar migración y almacenamiento |
| Perfil compartido | **Exactamente 1** registro en `profiles` de ese navegador | Bloqueado: no usar navegador de otro operador |
| Alcance firmado | **Exactamente 1** registro cifrado en `scopes` | Bloqueado: preparación online y permisos |
| Definiciones cifradas | **Al menos 1** registro en `quality_packages` | Bloqueado: preparar formulario online |
| Persistencia | `navigator.storage.persisted()` confirma permiso | Si no, **REVISAR**: riesgo de expulsión; la prueba física sigue obligatoria |
| Vigencia de permisos | **No comprobable offline** | Siempre se señala **REVISAR**, nunca se interpreta como autorización industrial |

En navegadores donde `indexedDB.databases()` no esté disponible, el sistema **no crea ni abre una base nueva para diagnosticar**. Muestra `REVISAR`, no declara falso PASS. La comprobación local es de estructura y presencia, no descifra ni valida los sobres; esto lo hace **por separado** el desbloqueo existente OFF-03C.2.

**Advertencia:** un diagnóstico local positivo no demuestra ni autorización actual, ni ausencia de expulsión futura de datos, ni reinicio físico, ni capacidad de capturar.

## Prerrequisitos para QA físico (gate de autorización)

1. Solo después de una **autorización separada**, preparar un entorno VINTO **HTTPS de ensayo**, aislado de producción. No se autoriza ese despliegue mediante este PR. Usar base PostgreSQL de ensayo y usuarios de prueba, sin pacientes/clientes/producción/OT reales.
2. Publicar el código de PR #192 + este candidato **solo en ensayo**, por mecanismo autorizado de build o rama de prueba. Nunca activar flags en producción.
3. Configurar exclusivamente en ensayo `OFFLINE_SCOPE_ISSUE_ENABLED=true`, `OFFLINE_QUALITY_PACKAGE_ISSUE_ENABLED=true`, semilla Ed25519 de ensayo y permiso mínimo `CALIDAD`. No subir claves, `.env`, logs con credenciales ni tokens a GitHub.
4. El administrador de ensayo concede exactamente el sector y los pares MP1/MP3 + P1-18/22/26/27 necesarios al usuario de prueba. En la app validar que la consulta publicada y la autorización efectiva concuerdan.
5. Dispositivo móvil de Calidad dedicado a QA; navegador **normal, no incógnito**, una identidad por navegador. Registrar de forma no identificable modelo/OS/versión navegador y si es PWA instalada o pestaña. Confirmar capacidad de almacenamiento y permisos del equipo.
6. Mantener origen y navegador idénticos de principio a fin; cambiar entre HTTPS, subdominios, perfiles o navegadores cambia la separación de almacenamiento.

## Protocolo físico — 11 puntos

| ID | Acción verificable | Resultado esperado |
|---|---|---|
| M01 | Con conexión real, abrir el HTTPS de ensayo y autenticar usuario Calidad permitido | Sesión válida y origen seguro; ningún error de API |
| M02 | Preparar perfil local y frase **distinta** a la corporativa | Perfil único y bóveda cifrada, sin datos sensibles en claro |
| M03 | Solicitar alcance firmado para MP1 o MP3 | Par máquina–formulario–versión concedido; permiso efectivo del backend |
| M04 | Seleccionar un P1-18/22/26/27 autorizado y preparar definición | Firma y hash verificados, paquete cifrado; no hay captura |
| M05 | Abrir una vez la aplicación online y comprobar control SW / caché | Versión `vinto-off03c4-static-v1` instalada |
| M06 | Desactivar **Wi-Fi y datos móviles** (no confiar solo en `navigator.onLine`) | API realmente inaccesible; no usar modo de prueba solo de DevTools |
| M07 | Cerrar completamente navegador/PWA, **reiniciar físicamente el móvil** y mantener ambas radios apagadas | No se restablece Internet durante el reinicio |
| M08 | Abrir VINTO desde acceso guardado o PWA en **el mismo navegador/origen** | Aparece shell público de contingencia sin conexión |
| M09 | Pulsar «Comprobar preparación técnica» y revisar todos los controles | Sin `BLOQUEADO`; `REVISAR` de persistencia debe documentarse |
| M10 | Ingresar frase offline, desplegar definición del formulario | Firma+SHA256 correctos, nombre/campos/tipos/opciones/versión intactos; **sin inputs ni aprobación** |
| M11 | Recuperar red, volver a VINTO online, evaluar sesión y permisos nuevamente | Sin envío automático de captura; ninguna escritura de Calidad; verificar que el cambio de red no pierde paquete |

### Pruebas negativas indispensables

- **N01:** navegador sin enrolamiento o perfil nuevo → no entra a datos offline. No iniciar sin Internet desde cero.
- **N02:** frase local incorrecta → no se muestran definiciones.
- **N03:** operar en un navegador distinto al del enrolamiento → no recupera el paquete de otro operador.
- **N04:** almacenamiento/quota sin garantía → el diagnóstico indica `REVISAR`, sin ocultar el riesgo.
- **N05:** tras revocar concesión en el servidor (solo QA aislado), el **paquete histórico puede seguir siendo verificable offline**, pero al volver online la API debe denegar nueva emisión; no intentar escribir capturas.
- **N06:** controles de liberación/rechazo o envío deben seguir deshabilitados. Ningún «PASS» técnico da permiso industrial.

## Matriz de evidencia y decisión

En el registro de QA escribir **solo**: ID de caso, fecha/hora del ensayo, equipo/OS/navegador sin números de serie, versión de commit (branch), resultado PASS/FAIL/BLOCKED, notas no sensibles y capturas de pantalla **sin perfil, UUID, contraseñas, datos ni nombres reales**. Si alguno de M06–M10 falla, clasificación **NO APTO PARA USO OFFLINE** y reproducir con instalación limpia en equipo de ensayo, sin borrar manualmente datos de usuarios productivos.

**PASS físico** requiere los 11 casos M01–M11 y N01–N06 verificados; esta decisión debe quedar firmada por responsable de QA de VINTO. Un test Chrome de CI **no** sustituye reinicio del sistema operativo real.

## Evidencias automatizadas

- `scripts/off-03c3-device-qa.test.mjs`: contrato sin fetch, escritura ni exposición; simulación de navegador preparado, no enrolado y sin `indexedDB.databases`.
- `scripts/off-03c2-browser-smoke.py`: ampliado para pulsar diagnóstico después de cerrar/reabrir Chrome **offline**. Comprueba shell precacheado, stores v3, perfil/scope/paquete cifrado y ausencia de IDs en la lista.
- La integración corre desde workflow `.github/workflows/off-03c2-quality-browser.yml`, además de regresiones heredadas OFF-02/03A/03B. **NO** enciende API real de ensayo.

## Bloqueos previos a OFF-04

- Resolver **renovación atómica del snapshot firmado y paquetes cifrados**: hoy reemplazar alcance por otro snapshot puede invalidar paquetes y obstaculizar su sustitución. No forzar limpieza del navegador ni eliminar datos para “reparar”.
- Definir posesión física del equipo, revocación y recuperación de clave, control anti-rollback y política de borrado remoto si aplica.
- Homologar oficialmente el formulario de Calidad que será piloto y establecer fuente de hora de ensayo/turno. Para P1-26, el cálculo es del **backend**.
- Diseñar registro offline y reconciliación de OT/asignación sin atribuciones silenciosas, idempotencia y outbox en OFF-04. El presente hito **es de lectura y diagnóstico**.

**Gate de liberación:** PR Draft; NO merge, NO despliegue, NO migración, NO cambios en la VPS ni datos industriales.

> **Nota OFF-03C.4:** el runtime público `offline-boot.js` cambió (estado de renovación). Por eso la caché pública rotó a `vinto-off03c4-static-v1`; el Service Worker elimina las versiones anteriores al activarse. El protocolo M01–M11 / N01–N06 no cambia.
