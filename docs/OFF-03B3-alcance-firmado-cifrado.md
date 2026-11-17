# VINTO OFF-03B.3 — Alcance firmado cifrado y consulta offline (incremento protegido)

**17 de noviembre de 2026 — candidato de ensayo, no producción.**

## Objetivo
Unir el perfil cifrado OFF-03A/03B.1 con el alcance efectivo firmado por FastAPI en OFF-03B.2. En el navegador compartido, cada operario conserva su compartimento; mientras está online, confirma su sesión, obtiene un alcance firmado y lo guarda cifrado. Al cerrar y reabrir sin red, puede verificar localmente la firma y consultar **solo el índice de formularios y versiones**.

Este PR apilado requiere OFF-01 (#184), OFF-02 (#186), OFF-03A (#187), OFF-03B.1 (#188), OFF-03B.2 (#189), **todos en Draft**. La rama parte del HEAD de #189 con la corrección de la regresión histórica de concesiones.

## Flujo de ensayo, en dos sesiones

1. **Enrolamiento online** en `/offline-preparacion`: usuario real autenticado por cookie HttpOnly y `GET /api/auth/me`, con `quality.capture` o `production.capture`; crea la bóveda local una única vez. El perfil permanece separado por navegador y no puede sustituir otro operario.
2. **Preparación del alcance** online: el mismo usuario revalida `GET /api/auth/me`, desbloquea la bóveda con su frase local, indica las máquinas de interés (hasta 25). El cliente invoca `POST /api/offline/scope` con `credentials:include`, `cache:no-store`, únicamente por **HTTPS** (excepción de loopback para desarrollo).
3. **Anclaje inicial de confianza:** bajo la sesión autenticada y la conexión HTTPS, el cliente utiliza la clave pública Ed25519 devuelta por el servidor, verifica el sobre *antes* de guardarlo y cifra **juntos** el sobre y esa clave confiada con la clave AES-GCM local. No basta una clave adjunta a un sobre leído de IndexedDB. **Este primer anclaje depende de TLS y del backend autenticado; no es un pin externo de despliegue ni attestation de hardware.**
4. **Actualización online:** admite refrescar el alcance con la misma clave pública. Rechaza cambiar silenciosamente a otra clave (`pin_mismatch`); la rotación requerirá un procedimiento autenticado de renovación/recuperación todavía no implementado.
5. **Sin Internet:** el Service Worker ofrece exclusivamente `offline.html` y código público cacheado; el operario ingresa su frase, se desbloquea la clave en memoria, se descifra el alcance y se valida **de nuevo** firma, key ID, pin, usuario, navegador, versión, tipo y `captures_enabled=false`. Solo entonces aparecen pares **máquina–código de formulario–versión**, en texto seguro no ejecutable.
6. **Estado con firma alterada/almacenamiento corrupto:** no aparecen formularios. La pantalla mantiene su leyenda de que captura, aprobación y sincronización están deshabilitadas.

## Modelo local y migración

- `vinto-off03a-profiles-v1`: mismo nombre de base IndexedDB, pasa de versión **1 a 2** mediante `onupgradeneeded`, preserva `profiles` y añade `scopes` (un alcance por navegador).
- `scopes` solo guarda `{profileId,ownerId,deviceKey,snapshotId,sealed}`. **No** persiste formularios, permisos, nombres ni clave pública en claro. El conjunto completo va dentro de `SealedValues` AES-GCM, ligado por AAD a usuario, navegador, ID de snapshot y marca `VINTO-OFFLINE-SCOPE`.
- La referencia pública de la clave `trustedPublicKey` se guarda **dentro** de los datos cifrados. Si se manipulan el ID, la bóveda o el ciphertext, la recuperación falla.
- `storeOfflineScope` verifica el sobre antes de escribir, bloquea la rotación inadvertida de clave y rechaza otros perfiles; controla una escritura concurrente mediante comparación del `snapshotId` previo.
- No existe `expires_at` por turno durante el piloto: **la firma describe el estado histórico de autorización en el momento de emisión y NO concede una sesión válida por tiempo indefinido**.

## API y limitaciones de confianza

- Reutiliza el endpoint **solo lectura** `POST /api/offline/scope` de OFF-03B.2, con `OFFLINE_SCOPE_ISSUE_ENABLED=false` inicialmente. El backend sigue siendo la única autoridad para permitir una captura real y para decidir conciliaciones por cambios de OT/asignación.
- El cliente NO puede elevar un `scope_readiness_only` a una operación de captura; exige `captures_enabled=false`.
- Un `device_key` almacenado en el navegador es **identificador, no prueba criptográfica de posesión de dispositivo físico**.
- El pin local cifrado depende de la autenticidad de la **primera sesión HTTPS**. El administrador aún necesita política de origen/clave autorizada, cambios de clave, revocación, recuperación y auditoría persistente.
- **No descarga todavía la definición completa del formulario, campos, rangos, validaciones ni recetas**. El índice firmado permite identificar qué paquete versionado deberá solicitarse. La distribución cifrada y verificación de esquemas de formularios y sus dependencias es un gate separado antes de captura piloto.
- **No** hay autorización offline para una aprobación de Calidad, liberación, rechazo, modificación de OT o inventario. No hay motor outbox ni sincronización. No se toca SQL ni Power BI.

## Pruebas y evidencia esperada

- `scripts/off03b3_fixture.py` utiliza **el firmador Python real** de OFF-03B.2 con semilla sintética local. Ninguna credencial real ni clave privada de producción aparece en GitHub.
- `scripts/off-03b3-signature.test.mjs`: Node WebCrypto verifica el JSON firmado por Python. Prueba sustitución de pin, usuario, dispositivo, hora, versión, firma, capacidades y campos adicionales; valida ausencia de APIs de captura en el arranque offline.
- `scripts/off-03b3-browser-smoke.py`: Chrome real; backend simulado únicamente para `GET /api/auth/me` y `POST /api/offline/scope`, siempre con usuario sintético. Comprueba enrolamiento, índice cifrado en IndexedDB (sin `VINTO-P1-18` en claro), denegación de rotación, cierre, reapertura sin conexión, rechazo de frase errónea, verificación de índice firmado y corrupción de ciphertext sin mostrar datos.
- La prueba `scripts/off-03b-browser-smoke.py` de OFF-03B.1 se adapta a versión 2 de IndexedDB para mantener la regresión.
- `.github/workflows/off-03b3-verified-scope.yml`: pruebas cruzadas Python–Node, TypeScript, lint, build portable, Chrome e imágenes de evidencia.

## Gates para habilitación operativa

1. **Gate A:** publicar en HTTPS de ensayo bajo clave/autoridad verificada sin habilitar producción. Ejecutar test físico de tablet/teléfono Calidad: cerrar navegador, reiniciar sistema, operar sin red, recuperar y reconectar.
2. **Gate B:** completar prueba de posesión del dispositivo (o decisión formal de riesgo para navegador compartido), recuperación y revocación.
3. **Gate C:** auditar emisión, publicación/rotación de claves, controles anti-rollback y gestión de fraude en un almacenamiento extraíble.
4. **Gate D:** construir y descargar un **paquete completo, autorizado y versionado** de formularios/calidad/recetas; verificar hash/firma e integridad y disponibilidad offline. El índice de este PR NO reemplaza ese paquete.
5. **Gate E (OFF-04):** registro real, contexto de OT/turno, idempotencia, cola, revalidación central y conciliación por modificaciones de OT/asignación. Sin ello NO habilitar captura.

**Estado de release:** documentación y QA en ramas Draft. Ningún merge, ninguna migración, ningún despliegue ni modificación de la VPS.
