# OFF-02 — Base técnica PWA e IndexedDB

**Estado:** candidato de desarrollo aislado, NO aprobado para capturas reales.  
**Base:** `main` en `2ca165af615ad5405a526e40d73e96ff8f83b4a6`.  
**Rama:** `feat/off-02-pwa-indexeddb-foundation`.  
**Dependencia contractual:** [OFF-01 V2](./OFF-01-arquitectura-operacion-offline.md), todavía PR #184 en Draft (no fusionado).

## Alcance

1. Registro de Service Worker estático en un componente cliente que no cambia navegación, login ni permisos existentes.
2. Manifest PWA con inicio `/` e icono SVG existente.
3. Solo se precachean `/offline.html`, `/offline-probe.js`, `/manifest.webmanifest` y `/favicon.svg`. Se pueden cachear recursos inmutables de `/_next/static/` si el cliente los solicita.
4. Navegación offline a `/` devuelve **pantalla pública de contingencia** y nunca HTML de usuario autenticado. Las rutas administrativas y APIs NO se cachean.
5. Diagnóstico de persistencia de una marca sintética en `vinto-off02-probe`; el usuario debe abrir online primero y luego volver a abrir offline para comprobar la persistencia. No contiene datos de operario.
6. `lib/vinto/offline-store.ts` añade un almacén IndexedDB versionado con stores de borradores cifrados y outbox, índices por usuario y navegador, traslado atómico a cola, validación de forma y rechazo de sobrescritura interusuario. No tiene conexión a red ni acceso automático desde formularios existentes.

## Restricciones de seguridad

- **No** se guardan credenciales, tokens de sesión, cookies, OT ni capturas operativas en caché estática.
- **No** se conectan formularios reales a IndexedDB en OFF-02; no existe aún enrolamiento, cifrado de payload, clave local recuperable, ni desbloqueo (OFF-03).
- La interfaz offline NO debe sugerir que puede registrar datos industriales.
- El contrato de `SealedValues` requiere `aes-gcm-v1`; validar formato no verifica criptográficamente autenticidad de un ciphertext. El cifrado/descifrado reales, la gestión de claves y los vínculos de identidad requieren OFF-03.
- El `device_key` existente se guarda por navegador; no se crea aquí una identidad física multisistema.
- `navigator.onLine` no certifica disponibilidad de API; el motor de sincronización queda para OFF-04.
- El almacenamiento persistente del navegador no garantiza recuperación cuando se borran los datos del sitio o se restablece el dispositivo.

## Pruebas que deben ejecutarse antes de merge

### Unitarias y estáticas
- `node --test scripts/off-02-foundation.test.mjs`
- `npx tsc --noEmit`
- `npm run lint`
- `node --test scripts/int-02a-central-only.test.mjs` (regresión central-only)
- `npm run build` (perfil de ejecución del repo)

### Manuales en un dispositivo/browser real de prueba
1. Abrir VINTO online en HTTPS y confirmar instalación/control del Service Worker; no realizar capturas.
2. Abrir `/offline.html` online una vez y comprobar que almacena la marca sintética.
3. Desconectar Internet completamente, cerrar navegador y reiniciar el dispositivo.
4. Reabrir `/`; debe mostrar la pantalla estática offline, nunca una sesión autenticada ni un formulario operativo.
5. En la pantalla de contingencia, comprobar que la marca técnica persiste; si se borró el storage, debe informar que vuelve a crearla, sin prometer recuperaciones.
6. Abrir `/admin` offline; no debe mostrar datos administrativos cacheados. Confirmar que los endpoints `/api/auth/me`, `/api/captures` y RSC no están en Cache Storage.
7. Reconectar, verificar login y capturas online previamente existentes, y que el Service Worker no devuelve respuestas antiguas de API.
8. Probar modo incógnito, cuota agotada y almacenamiento bloqueado: la prueba debe mostrar error, nunca éxito simulado.
9. Inspeccionar en Chrome, Edge y Firefox el funcionamiento y tamaño de caché en hardware objetivo.

**No reivindicar PASS de build completo ni validación en navegador hasta ejecutar esas pruebas.** Este PR debe permanecer DRAFT hasta QA y autorización explícita. No hay migraciones ni cambios de backend.

## Gate para OFF-03

En OFF-03 se implementarán enrolamiento, elección de credencial local segura, cifrado, claves protegidas, perfiles de operario y desbloqueo offline después de cerrar/reiniciar. Recién entonces podrán incorporarse formularios reales y contexto industrial.

## Rollback

Como todavía no se instala en producción, no hay rollback requerido. Si se distribuye en piloto futuro, la retirada del Service Worker deberá gestionar la caché versionada y la protección de datos sin borrar colas offline automáticamente.
