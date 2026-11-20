# VINTO OFF-04.5B-06B — Autenticación QA, emisor sintético P1-22 y cliente móvil offline

**Estado:** candidato de desarrollo aislado, PR Draft apilado sobre #240 (`9c3443f49c06d23a4f8496a980ef2725ce832b97`). Seguimiento: #241.
**NO despliega, NO activa servicios, NO crea usuarios ni concesiones reales, NO modifica PostgreSQL QA ni producción, NO expone la API, NO habilita captura industrial.** SEC-HOST-01 y OFF-04.2-R3 siguen en backlog. Sin identificadores de infraestructura en este documento.

## 1. Auditoría (resumen)
| Hallazgo | Consecuencia |
|---|---|
| `app.main` expone **77 operaciones** (39 lecturas, 38 escrituras). Login/me/logout y `/api/offline/scope` + `/quality-package` son **5** de ellas; el guard de #219 permite exactamente 4 POST: login, logout, scope y paquete. | Se montan **solo esos routers** (más el receptor) en la app QA aislada. No se monta nada industrial. |
| `current_user` resuelve la sesión con `get_connection` (rol de aplicación); el login usa `get_identity_connection`. | En la app QA la dependencia `get_connection` se **redirige** a la conexión de identidad: el rol de capturas no necesita ni recibe privilegios de identidad. |
| La cookie (`cookie_options`) es `HttpOnly`, `SameSite=Lax`, sin `Domain`, `Secure` fuera de `local`; su nombre es configurable (`AUTH_COOKIE_NAME`). | Nombre exclusivo de QA obligatorio (`vinto_qa_*`); la cookie de producción nunca es una sesión QA. |
| El cliente (OFF-03B/C) ancla la clave pública **desde la primera respuesta autenticada** (`storeOfflineScope`). | El emisor sintético firma con una clave que solo existe para el piloto; el dispositivo la fija en el enrolamiento y rechaza cualquier otra. |
| El emisor real lee definiciones publicadas (`capture_eligible=false`, nombre real) y usa la autorización industrial. El editor del laboratorio solo acepta definiciones `SINTÉTICO…`. | Emisor QA aparte, en los mismos paths y contratos, con definición sintética derivada del seed de P1-22 y concesiones explícitas del registro. |
| Hoy en QA `vinto_app` conserva DML de identidad (D3B4 pendiente). | No se amplía ni se confía en ello: las pruebas usan un rol de aplicación **sin ningún privilegio de identidad** y el flujo completo funciona. Retirar ese DML sigue siendo D3B4 (autorización aparte). |

## 2. Qué se añade
- `backend/app/qa_pilot_auth.py`: emisor sintético, Origin allow-list, verificación del rol de identidad, `AuthMount`.
- `backend/app/qa_offline_pilot.py` y `qa_pilot_main.py`: flag independiente `OFFLINE_QA_PILOT_AUTH_ENABLED` (**apagado por defecto**, solo con `APP_ENV=qa`), `OFFLINE_QA_PILOT_ALLOWED_ORIGINS`, `OFFLINE_QA_PILOT_SIGNING_SEED_B64URL`.
- `lib/vinto/offline-quality-e2e-lab.ts` + `lab/offline-e2e-lab.html`: cliente de mismo origen con login real y preparación en línea.
- Pruebas: `test_off045b06b_mobile_auth.py` (26, ASGI + PostgreSQL), `off-04-5b-06b-mobile-auth-e2e-browser.py` (15 casos Chrome), contratos estáticos del cliente.
- CI: `off-04-5b-06b-mobile-auth.yml` (PostgreSQL 17). El navegador E2E de 5A queda sustituido por este.

## 3. Condiciones de arranque (todas fail-closed, con códigos fijos y sin valores)
Con el flag de autenticación encendido: `APP_ENV=qa`; lista de orígenes exactos (https, o http solo en loopback para servidores descartables; nunca `*`); semilla Ed25519 sintética válida; concesiones del registro; nombre de cookie `vinto_qa_*`; cookie `Secure`; **conexión de identidad dedicada**, distinta de `DATABASE_URL`, que además se verifica: misma base QA aislada, rol distinto del de aplicación, sin superusuario/`CREATEDB`/`CREATEROLE`/`REPLICATION`/`BYPASSRLS`, sin `CREATE`, **sin acceso al esquema del receptor**, con `SELECT`/`UPDATE` pero sin `DELETE`/`TRUNCATE` sobre credenciales y sesiones, dueño de nada.

## 4. Autenticación
- Reutiliza **tal cual** `app.auth.router` (credenciales, bloqueo, misma respuesta 401, sesión en `vinto_auth.session`) y `current_user`.
- **Origin/CSRF:** toda escritura (POST/PUT/PATCH/DELETE) con la autenticación activa exige un `Origin` presente e **igual** a uno de los permitidos (sin Origin, `null`, otro puerto, otra mayúscula o con barra final: 403). No hay CORS en absoluto. Se suma `SameSite=Lax`.
- Sin sesión: 401; sesión vencida o revocada: 401; cookie con el nombre de producción: no es sesión.
- Autor original: el receptor exige que el usuario autenticado sea el autor de la captura (403 `author_mismatch`), y el GET de conciliación solo lo ve el autor.

## 5. Emisor sintético P1-22
- Mismos paths y modelos que el emisor real (`POST /api/offline/scope`, `/quality-package`), de modo que el contrato del cliente no cambia; el emisor real **no se monta** y su semilla nunca se lee (prueba que lo verifica).
- **Scope** readiness-only (`captures_enabled=false`) para las concesiones del registro del usuario autenticado; el snapshot es **el fijado en la concesión** (sin ambigüedad).
- **Paquete** readiness-only con la definición sintética: claves, tipos y obligatoriedad **idénticos al seed publicado** (5 campos manuales); nombre `SINTÉTICO…`, nota `Synthetic QA-only…`, `capture_eligible=false`; sin rangos ni unidades inventados; **no homologado**.
- Valida: scope firmado con la clave sintética (cualquier otra, incluso la real, se rechaza), sujeto = usuario autenticado, dispositivo, antigüedad ≤ 24 h y no futura, `grant_id` y versión actuales; **una concesión retirada del registro deniega**.
- Sincronización: el receptor sigue exigiendo la concesión explícita (usuario, máquina, formulario, versión **y snapshot fijado**). Un snapshot readiness-only o distinto del fijado no autoriza nada (403, nada se persiste). `observe` no concede.

## 6. Cliente móvil (laboratorio)
- **Un solo origen:** una única primitiva de red (`api()`), con rutas relativas `/api/…`, `credentials: "include"`, `cache: "no-store"`, sin cabecera de identidad y sin forma de indicar otra URL (se elimina `?receiver=`). Solo HTTPS, o http en loopback para servidores descartables de desarrollo/CI.
- Flujo: login (formulario) → preparación en línea (perfil local cifrado, alcance firmado cuya clave se ancla desde esa respuesta autenticada, definición sintética firmada) → desbloqueo → captura offline → borrador cifrado → pendiente local → puente explícito → «Sincronizar ahora».
- La sincronización consulta la **sesión real** (`/api/auth/me`) cada vez: otra cuenta, sesión vencida/revocada o ausente **pausan sin cambiar nada**; sin conexión no se envía nada. Solo el autor original autenticado sincroniza.
- Se registra el Service Worker público existente (activos públicos y páginas del laboratorio; nunca `/api/`), de modo que la página reabre sin Internet. La compilación operativa por defecto no incluye el laboratorio.

## 7. Pruebas
- **ASGI + PostgreSQL (26):** flags apagados, fuera de QA, arranques inseguros, rol de identidad separado y mínimo, rol de aplicación sin identidad, login/cookie/401/logout/vencida/revocada, Origin/CSRF, emisor (firma, sujeto, dispositivo, grant, antigüedad, otra clave), flujo de capturas idempotente con conflicto y autor, snapshot readiness-only, combinaciones de flags, superficie exacta de rutas, aislamiento estático y sin filtraciones en logs. **7 mutaciones** (Origin, redirección de identidad, firma del scope, relectura de la concesión, nombre de cookie, privilegios de identidad, snapshot fijado) son detectadas.
- **Chrome (15 casos, un solo origen, FastAPI + PostgreSQL):** login incorrecto y correcto con cookie real `HttpOnly`/`Secure`/`SameSite=Lax`; firmas alteradas rechazadas por el dispositivo; paquete firmado; captura offline completa y borrador incompleto; reinicio sin Internet; reconexión y sincronización con la sesión real (`capture_id` estable, **un solo registro** en PostgreSQL); respuesta perdida conciliada sin duplicado; interrupción de red; otro usuario / sin sesión / sesión revocada / vencida; snapshot readiness-only rechazado; dos pestañas; fallo de almacenamiento; escrituras no autorizadas con cookie real bloqueadas; flags apagados; solo el mismo origen contactado.
- Regresiones: OFF-04.4, OFF-04.5B-01/03, contratos Node, `tsc`, ESLint y compilación por defecto sin laboratorio.

## 8. Riesgos residuales y gates posteriores (autorización independiente)
- La cookie usa `Path=/` (el router reutilizado la fija así); un path acotado exigiría cambiar código compartido. Aislamiento por nombre exclusivo y host propio.
- Las concesiones del piloto viven en la configuración del servicio, no en la base; la semilla sintética debe entregarse por un mecanismo protegido y rotarse.
- Sin evaluación de contexto industrial real; homologación de P1-22 y OFF-04.2-R3 pendientes para cualquier uso real. QA físico del móvil no ejecutado.
- Para operar: servicio con rol de identidad separado y su credencial, usuario sintético y concesión mínima, firmador QA, alojamiento de la PWA y HTTPS privado con VPN/allowlist de rechazo por defecto, activación sintética y móvil físico. **Nada de esto se ejecutó ni se configuró.**
