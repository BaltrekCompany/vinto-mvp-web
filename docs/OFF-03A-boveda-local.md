# VINTO OFF-03A — Núcleo local de bóveda cifrada (prototipo aislado)

**Estado:** candidato de investigación/QA; NO habilita offline real ni enrolamiento de operarios.  
**Origen:** rama `feat/off-03a-local-profile-vault` desde OFF-02 `d08d3904bba529bc4032ad1232f290949ec69eda`.  
**Relación:** PR #184 (contrato V2, Draft) → PR #186 (PWA e IndexedDB, Draft) → OFF-03A (esta rama).

## Alcance mínimo implementado

- `lib/vinto/offline-vault.ts`: genera clave aleatoria AES-256 de contenido (no exportable al entregarla); deriva clave de envoltura PBKDF2-SHA-256 con 650 000 iteraciones, salt aleatorio y frase **local independiente** de la contraseña corporativa; cifra la clave de contenido con AES-GCM.
- Cifrado/descifrado de **datos sintéticos**, nunca capturas industriales, con AES-GCM e identificadores vinculados criptográficamente como datos adicionales autenticados (autor, navegador, capture_id, contexto, formulario y versión).
- `lib/vinto/offline-profile-store.ts`: perfil de envoltura guardado en IndexedDB propio, con política **un perfil por navegador**, sin sobrescribirlo ni asociar datos a otro operario. Después del cierre/reinicio debe permitir leer el perfil y usar la frase local para desbloquearlo **sin red**.
- No depende de cookie ni `/api/auth/me` para DESBLOQUEAR; la emisión de autorizaciones y el primer enrolamiento **sí** deberán exigir sesión online válida.
- Las claves descifradas solo se mantienen en memoria y la interfaz deberá descartarlas al bloquear/logout.

## GATES pendientes: no utilizar en piloto ni producción

1. **Autorización de enrolamiento online (OFF-03B):** obtener identidad desde `/api/auth/me`, validar permisos y dispositivo, emitir/grabar snapshot de máquina y formularios firmado y verificable. NO permitir que la API pública de esta librería sea usada por UI de producción sin esos controles.
2. **Elección de factor offline y seguridad del dispositivo:** el prototipo usa frase local de 16+ caracteres como umbral mínimo, pero PBKDF2 NO ofrece limitación a ataques offline contra una copia robada de IndexedDB. Evaluar resistencia real a diccionario/ataques de GPU, credencial de plataforma/WebAuthn PRF cuando sea compatible, y exigencias del entorno industrial. Un PIN corto no es aceptable por sí solo.
3. **Cifrado no equivale a permiso:** el hecho de que el dato local se pueda descifrar no permite modificar OT, liberar/rechazar, ni sincronizar sin revalidar en el backend con la identidad original del autor y el contexto autorizado.
4. **Revocación y pérdida de equipo:** sin red no puede conocerse una revocación reciente. El backend deberá bloquear recepción si la cuenta o concesión ya no es válida según política. No limpiar jamás colas sin confirmación central y un plan de recuperación. Borrar datos del sitio o perder la frase local impide recuperación; el cifrado no protege contra ataques XSS mientras la clave está desbloqueada.
5. **Equipos reales:** probar Chromium/Edge/Firefox y almacenamiento tras reinicio físico; medir latencia de KDF en hardware limitado y decidir protección/cierre automático y bloqueo por inactividad en UI.
6. **No hay soporte aún para sincronización ni formularios de Calidad**: OFF-03B + OFF-04 requieren PR y QA independientes.

## Pruebas automatizadas propuestas

- `node --experimental-strip-types --test scripts/off-03a-vault.test.mjs`: controles de KDF, AES-GCM, propiedad de no-exportable, reingreso sintético tras serialización, cambio de autor/formulario/contexto, manipulación de ciphertext, PIN corto, tamaño máximo, falta de IndexedDB y verificación de no integración con capturas reales.
- `pnpm exec tsc --noEmit`, `pnpm lint`, `pnpm build`.
- **Siguiente fase de QA:** pruebas reales IndexedDB y recuperación tras cierre/reapertura en navegador de ensayo; ninguna afirmación de PASS físico se desprende de tests Node.

## Suposiciones y riesgos

- **No hay vencimiento de captura offline por turno durante el piloto**, según contrato OFF-01; esto no crea autorización ilimitada del lado servidor.
- Cada navegador en un mismo dispositivo es un recinto de almacenamiento distinto. Chrome no abrirá las claves ni sincronizará colas de Firefox.
- Una captura posterior a cambio de OT/asignación debe conservar el contexto original y requerir conciliación con evidencias, sin confiar exclusivamente en la hora local.
- El perfil cifrado por sí solo NO demuestra que el usuario haya iniciado sesión online: OFF-03B debe hacer ese enlace con una concesión firmada por servidor.
- No desplegar, no fusionar ni modificar `main` sin aprobación expresa.
