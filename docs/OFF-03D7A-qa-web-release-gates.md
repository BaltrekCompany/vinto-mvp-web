# VINTO OFF-03D.7A — código candidato y gates web/API de QA Offline

**18-nov-2026 | Estado: preparación GitHub exclusivamente. No instalar ni desplegar.** Este documento responde al inventario OFF-03D.7 de Codex y a los cierres reportados OFF-03D.6C2/6C3. Todos los PR siguen Draft; no modificar main, piloto ni TVC.

## 1. Entrada verificada y selección de código

- Informe Codex: 31 migraciones y ACL aplicadas en PostgreSQL QA `vinto_qa_offline`, puerto loopback `127.0.0.1:6554`; auditoría independiente `OFF03D6C3_AUDIT=PASS_READ_ONLY`. El respaldo B2 fue probado restaurable en su estado PRE-DDL. No reutilizar B2 verify ni C1 inspect después de las migraciones.
- DNS `qa-vinto-mvp.baltrekservices.com` apunta a `51.79.65.225`; Nginx tiene bloque TLS QA y /qa-ready pero `/` responde 404. **Esto NO acredita un certificado validado, upstream QA ni web funcional.**
- El código OFF-03C.3 de consulta/diagnóstico offline está en PR #193 SHA `242a6034f41c32e5223eff928a924bfa66105462`; los PR #194–#204 están apilados sobre él y permanecen Draft. Seleccionamos como **línea de base de código para planificación QA** `2cd82cd58d9f6e544adacb3ce00501b07424073d` (PR #204) porque contiene el frontend/backend OFF-03, los scripts y el auditor posterior.
- Este PR D7A se construye **encima** de la rama de #204, sin hacer merge. **El candidato a construir, cuando las pruebas de D7A pasen, será el HEAD exacto de este PR**, no main ni el checkout de migraciones `7b9eb8c...`.
- Ojo: #204 se creó antes de los últimos commits del ejecutor de #203; **su HEAD no debe usarse para reejecutar migraciones**, aunque sirva como punto de partida de frontend/backend offline. La migración ya está aplicada; no volver a ejecutar C2 apply.
- Las migraciones YA existen en una base QA vacía; no se ha hecho un snapshot de datos de piloto y eso es deliberado. La preparación de fixtures sintéticas necesita un gate separado.

## 2. Hallazgos del código que condicionan el despliegue

| Componente | Fuente inspeccionada | Consecuencia QA |
|---|---|---|
| Frontend | `package.json` | **Next 16.2.6 sobre Vinext 1.0.0-beta.5/Vite 8/Cloudflare plugin**. Node >=22.18.0, pnpm 11.25.0. `pnpm build` usa `scripts/run-framework.mjs`. `pnpm start` hoy ejecuta Wrangler local `dev --local`, **no** un arranque Node de producción aceptado sin una prueba del artefacto. |
| Salida portable | `next.config.ts`, workflow OFF-03C.2 | Se solicita `output: standalone`; CI previa produjo `dist/standalone/server.js`. Aún hay que demostrar el contrato exacto de arranque/puerto de QA en un entorno aislado, no asumirlo. |
| API cliente | `lib/vinto/api.ts` | `NEXT_PUBLIC_API_URL` sin definir **cae a `http://127.0.0.1:8000`**, inservible/peligroso desde el móvil. El build QA debe fijar `https://qa-vinto-mvp.baltrekservices.com` (mismo origen público); verificarlo antes de publicar. |
| Backend | `backend/app/config.py`, `backend/app/main.py` | FastAPI con /health y /api/health; `DATABASE_URL` debe apuntar a QA **como `vinto_app`**, nunca migrator/bootstrap. `PG_PRIVILEGE_MODE=hardened` requiere comprobar dependencias y roles en una prueba separada. |
| Autenticación | `backend/app/auth/router.py` | Cookies `HttpOnly; Secure` para todo salvo APP_ENV=local. Proponer `AUTH_COOKIE_NAME=vinto_qa_session` para evitar cruces; no imprimir valor de cookie. |
| Firma y alcance | `backend/app/offline_scope/router.py` | Flags `OFFLINE_SCOPE_ISSUE_ENABLED` y `OFFLINE_QUALITY_PACKAGE_ISSUE_ENABLED` OFF por defecto. Activar juntos **solo en QA**, tras credencial sintética, firma Ed25519 QA y HTTPS/VPN; sin escribir esas claves en Git. |
| Seguridad de QA | `backend/app/main.py` + `backend/app/qa_offline_guard.py` nuevos en D7A | El backend histórico conserva muchos POST/PATCH operativos. Con `APP_ENV=qa`, el nuevo guard bloquea todos salvo login/logout y emisión de scope/quality-package firmados; GET/HEAD/OPTIONS conservan su flujo. Middleware es complementario, no reemplaza Nginx restrictivo, permisos, autenticación ni PostgreSQL aislado. |
| Operación móvil | `docs/OFF-03C3-qa-movil-calidad.md` | Protocolo M01–M11 + N01–N06 en celular físico. Solo lectura de definiciones P1-18/22/26/27; **sin captura offline, outbox, aprobaciones ni sincronización**. |

**Importante:** el guard de QA acepta POST de login/logout, que puede modificar sesiones QA en `vinto_auth`, y la emisión de sobres puede generar auditoría; **no significa que toda la base QA sea de solo lectura**, sino que no permite las escrituras operativas de VINTO por HTTP. Para comprobar la persistencia offline se necesitan esas operaciones controladas sobre identidades ficticias.

## 3. Arquitectura propuesta (sujeta a inspección y aprobación)

```
Móvil (red/VPN autorizada)
  -> HTTPS qa-vinto-mvp.baltrekservices.com (TLS válido, acceso restringido)
  -> Nginx bloque exclusivo QA
       /api/*  -> 127.0.0.1:8200 (FastAPI QA, solo loopback) [PUERTO CANDIDATO]
       /*      -> 127.0.0.1:3200 (frontend QA, solo loopback) [PUERTO CANDIDATO]
  -> FastAPI APP_ENV=qa, guard de escrituras, cookies Secure
  -> postgresql://vinto_app@127.0.0.1:6554/vinto_qa_offline
```

**3200/8200 son propuestas, NO reservaciones ni puertos confirmados libres.** Codex debe comprobar ocupación/servicios actuales, runtime de frontend real, certificados y vhost before planning deployment. No reutilizar `127.0.0.1:3100` (frontend piloto), `127.0.0.1:8100` (backend piloto) ni `127.0.0.1:8000` (otro backend observado), ni `6543/6544` (TVC/piloto).

El origen Nginx QA actualmente responde 404 en /; no se debe solucionar encaminándolo al piloto. Una configuración final separará rutas, upstreams y logs sin añadir un catch-all que redirija tráfico ajeno. **No aplicar cambios Nginx todavía.**

## 4. Configuración QA requerida — contrato, NO archivo .env

- `APP_ENV=qa` activa obligatoriamente el guard HTTP de D7A. **No usar `APP_ENV=local` en QA**: deshabilita cookies Secure y el guard.
- `DATABASE_URL`: secreto de `vinto_app` limitado exclusivamente a QA, vía archivo protegido root / servicio con permisos mínimos. No usar usuario propietario, `vinto_migrator`, bootstrap, ni credenciales de producción; no copiar .env del piloto.
- `IDENTITY_DATABASE_URL`: **NO configurar** salvo que exista rol `vinto_identity` y SQL 03c validados por un procedimiento separado (el QA inicial instalado no tiene ese rol). Usar el comportamiento existente de identidad con `vinto_app` únicamente para usuario ficticio y dentro del entorno aislado.
- `PG_PRIVILEGE_MODE=hardened`, tras prueba del funcionamiento de auth y de lectura de alcance sobre `vinto_app`; fallar cerrado si faltan permisos.
- `CORS_ORIGINS=["https://qa-vinto-mvp.baltrekservices.com"]` como valor estructurado aceptado por Pydantic; evitar wildcard. API y frontend compartirán dominio HTTPS. Validar la representación real en la configuración protegida antes de iniciar.
- `AUTH_COOKIE_NAME=vinto_qa_session`, no copiar cookie/sesión de otro entorno.
- `OFFLINE_SCOPE_ISSUE_ENABLED=false` y `OFFLINE_QUALITY_PACKAGE_ISSUE_ENABLED=false` hasta que usuario, dominio y firma sintéticos estén aprobados; al comenzar el ensayo físico habilitarlos **ambos solo en QA**, retirar al terminar.
- `OFFLINE_SCOPE_SIGNING_SEED_B64URL`: semilla Ed25519 de 32 bytes, aleatoria y exclusiva de QA, suministrada por archivo/servicio protegido, nunca GitHub. Registrar huella pública, nunca clave privada.
- `AUTHZ_CENTRAL_CAPTURES_MODE`, `AUTHZ_BOBBIN_PRODUCTION_MODE`, `AUTHZ_QUALITY_BOBBIN_CAPTURES_MODE`, `AUTHZ_QUALITY_MACHINE_CAPTURES_MODE`: los flags de autorización central no son un interruptor global de bloqueo; **el guard HTTP QA es obligatorio**. Ningún nuevo POST operativo se habilita para ensayo.
- Control de acceso: VPN o allowlist de red del móvil. Mantener QA bajo credenciales, rate limit y TLS; si no existe una ruta de acceso privada demostrable, bloquear habilitación externa.

## 5. Datos sintéticos/identidades — diseño, sin ejecutar

No importar `vinto_piloto` ni datos industriales reales. Usar seed existente y verificado por controles específicos cuando se autorice; crear **un usuario ficticio Calidad**, sector y concesiones mínimas a MP1/MP3 y versiones publicadas P1-18/22/26/27. No asumir que migraciones implican catálogos existentes o usuario de test. No generar credenciales personales reales. La cuenta debe poder autenticarse únicamente en QA y ser revocable al cierre. La emisión de paquetes exige definición publicada, permisos efectivos y autorización original; no cargar formularios/OT mediante heurísticas.

Orden propuesto de siguientes PR: **D7B** contrato de build/arranque de Vinext en entorno efímero; **D7C** fixture/rol QA y contrato de firma/flags; **D7D** instalación de servicios QA y vhost Nginx con respaldo/rollback del vhost y autorización explícita; **D7E** ensayo HTTPS + dispositivo físico. Ninguno se ejecuta por este PR.

## 6. Puertas que faltan en la VPS — solo lectura (Codex)

1. **TLS:** curl/openssl con verificación normal de cadena y vigencia, SNI del dominio correcto; no usar `-k`, no confiar en DNS como TLS PASS.
2. **Nginx:** informar qué vhost atiende `qa-vinto-mvp...` y qué upstream recibe / y /api; sanitizar nombres/rutas, nunca volcar configuración completa o cabeceras de autenticación. `/qa-ready` no demuestra que / ni /api esté listo. Confirmar titularidad y procedimiento de rollback antes de editar.
3. **Puertos:** leer `ss`/servicios para 3200/8200; no iniciar nada, marcar `FREE|OCCUPIED`.
4. **Versión runtime:** Node y pnpm reales y disponibilidad de recursos/espacio. Confirmar si `dist/standalone/server.js` generado puede arrancar en loopback con puerto seleccionado y sin usar runtime Wrangler development; **no construir ni arrancar aún**.
5. **Config y secrets:** reportar solamente presencia/forma/permisos, nunca valores. App role `vinto_app`, ausencia de datos sintéticos, existencia de rutas QA exclusivamente, y cumplimiento de puertos sin fuga; verificar metadatos SQL solo lectura.
6. **Invariantes:** conservar servicios piloto/TVC y la base migrada; no repetir migraciones, no ejecutar B2/C1 inspect post-DDL, no cambiar Nginx.
7. Entregar reporte con bloqueos y propuesta de instalación atómica y rollback. No ejecutar D7D sin autorización.

## 7. Criterios de cierre del incremento GitHub

- Test unitario del guard con middleware real y pruebas negativas, API QA bloquea todas las escrituras operativas.
- Tests estáticos de contratos de runtime, flags, API same-origin requerida y protección HTTP QA.
- CI de compilación: Node 22.18, pnpm 11.25, `pnpm exec tsc --noEmit`, lint, `pnpm build`, shell offline byte-identical; `dist/standalone/server.js` presente. **No implica que el servidor ya esté desplegado o escuchando.**
- Revisión de Codex VPS read-only. Gate de instalación debe ser otro PR + aprobación del operador.
- **Nada se fusiona a main y no se modifican piloto/TVC.**

**Estado esperado:** `OFF03D7A_GITHUB_CONTRACT=PASS` tras CI, `OFF03D7A_VPS_INVENTORY=PENDING`, `OFF03D7_QA_WEB=NOT_DEPLOYED`, `OFF03D7_PHYSICAL_DEVICE=NOT_TESTED`, `OFF04_CAPTURE=DISABLED`.
