# VINTO OFF-03D.1 — Preflight para ensayo físico de Calidad en móvil (solo lectura)

**17 de noviembre de 2026.** Origen: OFF-03C.3 PR #193 y anteriores (#192 a #184); todos **Draft**.  
**Estado:** procedimiento y preflight preparados; **NO se ha configurado un HTTPS de QA ni reiniciado un teléfono**. No usar `main` productivo para simular un pase.

## 1. Regla de seguridad y decisión

El siguiente paso NO es desplegar el PR al piloto activo: se precisa un **origen HTTPS aislado de QA** al que pueda acceder el móvil desde su red de prueba. Se requiere una base **no productiva**, identidad/sector/concesiones sintéticos, firma Ed25519 con semilla exclusiva de QA y los dos flags read-only activados **solo en QA**.

No se permite reutilizar `vinto_piloto`, roles/credenciales/usuarios de producción, la cookie del piloto, el puerto/servicio activo o la ruta `/opt/vinto-mvp-web/current` sin autorización específica y separación formal; no editar nginx productivo ni reiniciar otros servicios en este hito. Si no hay infraestructura de QA aislada, **el gate queda BLOQUEADO**, no se ejecutan las acciones M01–M11 del equipo físico.

**No hay una dirección HTTPS de staging confirmada en el repositorio.** El dominio antiguo `vinto-mvp.baltrekservices.com` aparece como plantilla del MVP, no se debe asumir como URL de QA. Tampoco se confirma un dispositivo desde GitHub.

## 2. Preflight de inventario en VPS (Codex — SOLO LECTURA)

Ejecutar la siguiente tarea desde el agente que **sí** tenga acceso autorizado al servidor, sin modificarlo:

> **VINTO OFF-03D.1 / INVENTARIO-ONLY:** Audita únicamente infraestructura/recursos VINTO existentes (dominios HTTPS, puertos/frontend/backend, roles y nombres de DB SIN CONTRASEÑAS, Git SHA release, namespaces, systemd, docker, nginx y políticas de acceso), y determina si existe una instalación QA genuinamente separada del piloto. NO leas ni imprimas valores de `.env`, cookies, JWT, contraseñas, claves, URLs con credenciales, datos de captures o identidad de operarios; si una URL de DB tiene contraseña, muestra solo el nombre de DB o `REDACTED`. NO ejecutes `nginx -T` completo en la respuesta, no `docker compose config` con secretos. NO hagas checkout, pull, merge, migraciones, cambios DNS/nginx, creación de usuarios, escritura PostgreSQL, restart, recarga de nginx, instalación, test de login real ni despliegue. Devuelve únicamente `QA_HOST=EXISTS|ABSENT|UNVERIFIED`, `QA_HTTPS=PASS|BLOCKED|UNVERIFIED`, `QA_DB_ISOLATED=PASS|BLOCKED|UNVERIFIED`, `QA_PORTS_ISOLATED=PASS|BLOCKED|UNVERIFIED`, `QA_RELEASE_SHA=<sha o UNVERIFIED>`, `PILOT_UNCHANGED=PASS|UNVERIFIED`, resumen de las evidencias no sensibles y blockers. Bloquea si no puedes probar aislamiento.

**Criterio:** nombres y configuración referencial no prueban que una DB no productiva esté disponible. La identidad real de la DB solo se confirma por inspección segura de configuración **sin imprimir secretos** y consulta read-only de metadatos, nunca por una URL `TEST_DATABASE_URL` inexistente o plantilla.

## 3. Preparación de entorno (fase futura, requiere aprobación separada)

| Control | Gate obligatorio |
|---|---|
| Origen | Host de QA distinto, certificado TLS confiable, `/api` y frontend del **mismo origen** HTTPS; accesible desde red/VPN del móvil |
| Código | Un único checkout construido desde SHA exacto `242a6034f41c32e5223eff928a924bfa66105462` + posteriores verificados en PR candidato; no `main` |
| Backend | FastAPI apuntando solo a BD QA, migraciones únicamente sobre BD QA y roles mínimos; no `vinto_piloto` |
| Frontend | `NEXT_PUBLIC_API_URL` compilado con URL HTTPS **del mismo host de QA**, nunca `127.0.0.1` vista por el móvil |
| Nginx/proxy | TLS termina en el origen correcto; proxy sólo de QA. Comprobar `request.url.scheme=https` de forma segura con cabeceras de proxy **confiadas solo desde loopback**; no aceptar cabeceras spoof de Internet |
| Autenticación | Cookies Secure/HttpOnly, CORS mismo origen, QA operator ficticio con perfil Calidad, sector y grants P1-18/22/26/27 mínimos |
| Firma | `OFFLINE_SCOPE_ISSUE_ENABLED=true` y `OFFLINE_QUALITY_PACKAGE_ISSUE_ENABLED=true` **solamente QA**; semilla nueva Ed25519, nunca en Git o capturas |
| Operaciones | No habilitar POST de capturas offline, outbox, aprobaciones ni liberar/rechazar; flag QA se apaga al finalizar |
| Acceso | Restringir QA a oficina/VPN o allowlist aprobada; el móvil debe estar dentro del perímetro autorizado. No abrir público por conveniencia |

No ejecutar esta tabla automáticamente. Es la **lista de aceptación para la próxima autorización de cambios de QA**, si el inventario confirma capacidad.

## 4. Preflight HTTPS de red (no autenticado y no destructivo)

Una vez que el entorno de ensayo exista y su URL haya sido autorizada, ejecutar desde un equipo **en la misma red/VPN del móvil**:

```bash
bash scripts/off-03d1-https-preflight.sh https://DOMINIO-QA-AUTORIZADO
```

El script NO inicia sesión ni modifica nada. Comprueba 9 recursos públicos (shell, build, SW, manifest) y exige `401` de `/api/auth/me`, `POST /api/offline/scope` y `POST /api/offline/quality-package` sin cookies. **No sigue redirecciones**, no acepta HTTP, no omite verificación de certificado. Se ejecuta con `curl` del cliente y no almacena cuerpos persistentes.

`OFF03D1_REMOTE_GATE=PASS_NETWORK_ONLY` significa **únicamente** que el origen parece preparado y los POST anónimos no pudieron emitir paquetes. NO valida SHA desplegado, flags, permisos, BD aislada, HTTPS visto por FastAPI tras proxy o dispositivo físico. Los cuatro indicadores pendientes salen explícitamente como `NOT_VERIFIED` o `NOT_RUN`. Cualquier 302, 403, 404, 5xx o respuesta 200 de una API protegida se trata como **BLOCKED**, sin reconfigurar ni relajar la red de producción.

## 5. Protocolo sobre teléfono/tablet real

Solo tras cumplir los gates de inventario y red:

1. Registrar **equipo modelo/OS/navegador** sin IMEI/serial/operario; abrir el **mismo origen HTTPS QA** en navegador normal (nunca incógnito).
2. Autenticar usuario ficticio Calidad (M01), preparar frase local diferente a contraseña corporativa (M02).
3. Emitir alcance firmado para máquina concedida (M03) y descargar una definición vigente P1-18/22/26/27 (M04); comprobar que no se ofrece captura (M05).
4. Verificar instalación/caché del SW, **desactivar Wi-Fi + datos móviles** y asegurarse de que API no responde; no usar solo el indicador `navigator.onLine` (M06).
5. Cerrar completamente la app/navegador desde multitarea, **reiniciar físicamente el sistema**, y conservar conectividad apagada (M07).
6. Reabrir VINTO desde el mismo navegador/origen (M08); ejecutar «Comprobar preparación técnica» en `/offline.html` y documentar `PASS/BLOCKED/REVISAR` (M09).
7. Desbloquear con frase offline, comprobar formulario, campos, versión y opciones **sin inputs ni botones de envío** (M10).
8. Recuperar conexión; comprobar que sesión y permisos se revalidan online; **no crear ni sincronizar captura** (M11).
9. Negativos N01–N06 del [protocolo OFF-03C.3](./OFF-03C3-qa-movil-calidad.md): primera apertura sin enrolamiento, frase errónea, otro navegador, expulsión/persistencia, revocación en servidor QA y ausencia de escrituras.
10. Registrar solo `M01-M11` y `N01-N06`, `PASS/FAIL/BLOCKED`, SHA, modelo SO/navegador y screenshots **sin datos sensibles**. No subir el contenido de IndexedDB, cookies, mensajes con usuarios reales ni pantallas de administración con grants.

**GO para lectura offline de QA:** 11 pasos M y 6 N pasan, firma+hash verifican, origen HTTPS/BD aislados, QA de móvil real documentado y responsable firma aceptación.  
**NO-GO:** falta host QA seguro, móvil cambia navegador/origen, cualquier lectura de paquete falla, datos se pierden tras reinicio o no puede demostrar aislamiento.

## 6. Fallos típicos que deben bloquear, no solucionarse con atajos

- `/offline-preparacion` no puede leer la API: comprobar `NEXT_PUBLIC_API_URL` y CORS; **no sustituirlo** por IP 127.0.0.1 del servidor o HTTP.
- `POST /api/offline/scope` 503 en HTTPS: posible `request.url.scheme=http` si Uvicorn no confía en el proxy local. Revisar `--proxy-headers` y `--forwarded-allow-ips=127.0.0.1` **solo en QA**, no aceptar proxies arbitrarios; la decisión exige prueba de seguridad.
- Se conserva alcance pero desaparece paquete: revisar vínculo `scope_snapshot_id` y renovación atómica. **No borrar IndexedDB de un usuario real para “resolverlo”**.
- Cache SW antiguo: requiere acceso online inicial para actualizar `vinto-off03c3-static-v1`; no modificar caché de otros orígenes.
- Navegador/iOS con `indexedDB.databases()` no disponible: diagnóstico marca `REVISAR`; se requiere verificación funcional del desbloqueo, no un PASS inventado.
- El permiso `persisted()` no garantiza retención eterna; eliminación manual de datos o modo privado rompe continuidad.

## 7. Estado y ruta de entrega

`OFF03D1_HTTPS_QA=NOT_VERIFIED`  
`OFF03D1_PG_QA_ISOLATION=NOT_VERIFIED`  
`OFF03D1_PHYSICAL_REBOOT=NOT_RUN`  
`OFF04_CAPTURE=DISABLED`

**Este PR es solo preflight y documentación; no merge, VPS, despliegue, migración, ni modificación de permisos.**
