# VINTO OFF-03B.1 — Preparación online y verificación local offline

**Estado:** incremento de infraestructura de prueba; no habilita formularios, órdenes de trabajo ni sincronización.  
**Rama:** `feat/off-03b-enrollment-offline-unlock`.  
**Base exacta:** OFF-03A en `4446e703f4a16e7beb96b70d7fb681f6a973398f`, con dependencia de OFF-02 en `d08d3904bba529bc4032ad1232f290949ec69eda`.  
**Contrato:** OFF-01 V2 PR #184 (sin TTL de captura por turno, usuarios por navegador, reconexión automática+manual, conflicto de asignación revisable).  
**PRs requeridos antes de integración:** #184, #186 y #187, todos aún Draft al iniciar este incremento.

## 1. Qué puede comprobarse ahora

1. Con acceso online y una sesión **real de backend** confirmada por `GET /api/auth/me`, el usuario abre la **ruta de ensayo** `/offline-preparacion` y configura una **frase local diferente de su contraseña VINTO**.
2. El cliente revalida inmediatamente `/api/auth/me` al confirmar. Solo prepara el perfil si la sesión está autenticada, `must_change=false`, tiene `quality.capture` o `production.capture`, y el identificador técnico del navegador persiste en localStorage.
3. `createLocalVault` genera clave AES-GCM no exportable y guarda únicamente la envoltura cifrada en IndexedDB `vinto-off03a-profiles-v1`. Se prohíbe sobreescribir un perfil previo, incluido uno de otro operador.
4. `scripts/build-offline-boot.mjs` compila el código TS que reutiliza `offline-vault.ts` y `offline-profile-store.ts` a `public/offline-boot.js`. **No hay una segunda implementación del algoritmo criptográfico**. Se genera antes de ejecutar `pnpm dev` o `pnpm build`; el archivo compilado no se versiona.
5. El Service Worker precachea `offline-boot.js` y ofrece la pantalla de contingencia sin almacenar HTML autenticado, respuestas API ni datos sensibles.
6. Tras cerrar Chrome/reiniciar el dispositivo y abrir VINTO sin red, la pantalla pública busca el único perfil local de ese navegador, compara el `deviceKey` persistido y ofrece ingresar la frase; verifica mediante WebCrypto local **sin llamar a la API**.
7. Al acertar la frase, se muestra **«perfil local verificado»**. No se genera una sesión de servidor, no se conserva la clave para capturas y no se habilita ningún formulario industrial.

## 2. Controles de identidad y seguridad

- **Un usuario por navegador:** la preparación falla cuando IndexedDB ya contiene un perfil, incluso si es del mismo usuario; rotación, migración, borrado y recuperación requieren proceso aprobado, no sustitución silenciosa.
- **La autoridad sigue siendo online:** `GET /api/auth/me` decide quién puede PREPARAR su perfil. El verificador offline no atribuye permisos vigentes ni da autorización de backend.
- **Frase no es contraseña corporativa:** no se almacenan contraseñas de la aplicación, cookies, JWT ni tokens; el usuario debe introducir una frase local con longitud y complejidad mínima.
- **Protección relativa:** la envoltura AES-GCM y PBKDF2 no previene por sí misma fuerza bruta contra una copia robada del almacenamiento. Para datos de planta, definir factor fuerte hardware/WebAuthn-PRF o medidas compensatorias y validación de seguridad.
- **Integridad del equipo:** si el identificador local del navegador no coincide con la identidad de la envoltura, no hay desbloqueo. Los navegadores permanecen aislados.
- **No hay regla temporal nueva:** OFF-01 excluye vencimiento automático por turno durante el primer piloto; OFF-03B.1 no crea ni gestiona autorización de captura.
- **Datos perdidos:** borrar perfiles del navegador, borrar IndexedDB, modo incógnito, formatear el equipo o perder la frase local puede destruir el acceso; todavía no hay mecanismo de recuperación autorizado.
- **No se autoriza ningún POST de captura** por tener un perfil local verificado. Todo control industrial actual permanece online.

## 3. Cambios técnicos

| Archivo | Propósito |
| --- | --- |
| `app/offline-preparacion/page.tsx` | Pantalla online de ensayo, autentica dos veces y prepara la envoltura |
| `lib/vinto/offline-boot.ts` | Verificación local en pantalla offline, sin red ni captura |
| `scripts/build-offline-boot.mjs` | Compila WebCrypto TS a runtime público autocontenido |
| `scripts/run-framework.mjs` | Genera runtime antes de dev/build, falla si falla la compilación |
| `public/offline.html` | Añade formulario de frase local, marcado explícitamente como desarrollo |
| `public/sw.js` | Versión nueva de precaché, incluye runtime offline; elimina caché anterior |
| `scripts/off-02-foundation.test.mjs` | Actualiza contrato del conjunto de recursos públicos |
| `.github/workflows/off-02-foundation.yml` | Genera bundle para QA público de OFF-02 que sigue activo |
| `scripts/off-03b-contract.test.mjs` | Guardas estáticas de enrolamiento online y límites del runtime |
| `scripts/off-03b-browser-smoke.py` | Chrome real, perfil persistente, login simulado de QA y desbloqueo sin red |
| `.github/workflows/off-03b-enrollment.yml` | Node, TypeScript, ESLint, portable build, Chrome integrado |

## 4. Cómo interpretar las pruebas

- **Node/WebCrypto:** OFF-03A conserva las pruebas criptográficas con datos sintéticos.
- **Contrato OFF-03B:** verifica que la pantalla exige comprobación online y que el runtime no contiene API/captura.
- **Chrome de ensayo:** la red del backend se simula SOLO para `GET /api/auth/me`, con usuario sintético. Se valida que el frontend llama a ese endpoint; esta simulación **no prueba la emisión de una concesión firmada**.
- **Chrome real sin Internet:** el navegador se cierra por completo, reabre el mismo perfil sin red, encuentra la envoltura en IndexedDB, rechaza frase incorrecta y acepta la original. Aun con PASS, no significa que el operador pueda completar formularios industriales.
- **Backend:** no se han añadido ni modificado endpoints, permisos o migraciones PostgreSQL.

## 5. Gates que siguen pendientes

1. **OFF-03B.2:** emitir desde el backend un snapshot de alcance **firmado, específico para usuario/dispositivo/máquina/formularios/versiones**, con política de revocación, auditoría y pruebas PostgreSQL17 aisladas. Sin expiración por turno no equivale a autorización indefinida.
2. **OFF-03B.3:** UI offline autorizada para mostrar formularios descargados, con bloqueo/auto-lock, manejo seguro de claves, almacenamiento y reactivación por identidad; evitar duplicar código de dominio en una UI estática sin contrato.
3. **OFF-04:** motor de sincronización, reautenticación del autor original, conciliación de OT/cambios de cantidad, idempotencia y alertas; ningún dato local aparece en Power BI ni almacén antes de confirmación central.
4. **QA físico de OFF-02/OFF-03:** prueba de SO/navegador concretos y reinicio de dispositivo en entorno HTTPS aislado, cuotas de IndexedDB, pérdida de almacenamiento y prueba de que nadie puede leer el perfil de otro navegador.
5. **Revisión de seguridad humana:** autentificador fuerte/gestión del factor, fuerza bruta, XSS, pérdida de equipo y política de recuperación.

**Criterio de este PR:** confirmar solo que un usuario previamente autenticado online puede preparar un perfil de ensayo y que la envoltura puede verificarse offline tras un reinicio normal del navegador. No publicar como «VINTO ya opera offline» ni habilitar capturas.

**Control de release:** No merge, no producción, no VPS, no PostgreSQL y no migraciones. Los PRs #184/#186/#187 continúan pendientes y la integración debe respetar el orden de dependencias.
