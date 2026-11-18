# VINTO OFF-03C.4 — Renovación atómica del alcance firmado y de los paquetes de Calidad

**Estado:** candidato de ensayo aislado, PR Draft apilado sobre OFF-03C.3 (#193). Solo consulta de definiciones. **No** habilita captura, aprobación, liberación ni sincronización. Sin cambios en PostgreSQL, VPS, flags, `main` ni despliegues. Los pendientes SEC-HOST-01 A0.3 siguen diferidos (#223).

## 1. Problema real encontrado en la base de #193

Un paquete de Calidad queda ligado al `snapshot_id` exacto del alcance bajo el cual se emitió. Con el código previo, alcance y paquetes se guardaban por separado y eso hacía **imposible renovar el conjunto**:

1. Si el alcance nuevo se guardaba primero, todos los paquetes quedaban huérfanos: `readQualityPackage` devuelve `null` cuando `scopeSnapshotId` no coincide, y `storeQualityPackage` rechaza sobrescribirlos (`scope`) por no existir un flujo de recuperación aprobado.
2. Si se intentaba guardar primero el paquete nuevo, no podía: la transacción exige que el alcance **ya guardado** tenga su mismo `snapshot_id`.
3. `storeOfflineScope` aceptaba **cualquier** instantánea firmada con la misma clave, también una anterior (sin anti-rollback).
4. No existía registro local de una revocación conocida: una firma íntegra se mostraba como «Firma y perfil verificados» aunque el servidor ya hubiera negado el alcance.

## 2. Diseño implementado (`lib/vinto/offline-renewal.ts`)

**Dos fases: preparar en memoria y confirmar en una sola transacción.**

Preparación (sin ninguna escritura en IndexedDB):
1. Comprueba perfil local, propietario y navegador (`identity_mismatch`).
2. Lee y descifra el conjunto actual (alcance + paquetes). Datos ilegibles ⇒ `needs_recovery` salvo recuperación explícita.
3. Solicita el alcance nuevo con sesión online (cliente inyectado; HTTPS lo impone `offline-scope-api.ts`).
4. Verifica Ed25519, identidad, dispositivo y **pin de clave ya anclado** (nunca el de un sobre leído offline).
5. **Anti-rollback:** solo se acepta un `issued_at` estrictamente mayor, o la misma instantánea idéntica. Anterior, o igual con otro `snapshot_id` ⇒ `rollback`.
6. Para cada paquete ya guardado que siga concedido: lo solicita con el alcance nuevo, verifica firma, `content_sha256`, concesión, **versión concedida** y `scope_snapshot_id`, y exige no retroceder de versión ni cambiar el cuerpo con la misma versión.
7. Cifra todo en memoria (alcance, marca de renovación y paquetes). Un fallo aquí aún deja intacto el conjunto anterior.

Confirmación: **una única transacción `readwrite`** sobre `profiles`, `scopes` y `quality_packages`:
- Revalida el perfil dentro de la transacción.
- **Compare-and-swap:** el alcance almacenado debe seguir siendo el `snapshot_id` leído al preparar, y cada paquete su `packageId` previo. Si otra pestaña lo cambió ⇒ `conflict` y se aborta.
- Solo entonces reemplaza alcance, paquetes y marca. Cualquier error aborta **todo**.

Todo o nada: ningún fallo de red, firma, versión, identidad, cifrado o almacenamiento se informa como éxito parcial, y el resultado `renewed` solo se devuelve después de `tx.oncomplete`.

### Integridad histórica ≠ vigencia de permisos

- Una firma válida acredita la integridad de esa instantánea histórica, **no** que la concesión siga vigente.
- Si la renovación online recibe **HTTP 403** (sin concesiones efectivas) se guarda una **marca sellada** AES-GCM `revocation_known` (AAD ligada a usuario, navegador y snapshot). No borra nada. Con esa marca, o con una marca ilegible, la pantalla offline **no lista formularios ni paquetes** y pide renovar con Internet.
- 401 (sesión expirada), 5xx/404 (servicio) y errores de red **no** se tratan como revocación y no cambian el estado.
- Solo una renovación online verificada vuelve a `renewed_online`. Los registros anteriores a OFF-03C.4 se leen como `legacy_unverified` (compatibilidad) con el aviso «sin marca de renovación».
- Offline, la pantalla muestra la fecha de la última renovación y que sin Internet **no puede confirmarse** la vigencia.

### Compatibilidad y migración local

- IndexedDB **no cambia de versión** (`vinto-off03a-profiles-v1`, v3) ni de stores: el diagnóstico OFF-03C.3 y los datos existentes siguen válidos.
- El registro de `scopes` gana dos campos opcionales: `schemaVersion: 2` y `renewal` (sellado). Los registros sin `schemaVersion` se tratan como versión 1 y siguen leyéndose; una versión desconocida se rechaza.
- `storeOfflineScope` (flujo de primera preparación) ahora **rechaza reemplazar** un alcance con otro snapshot mientras existan paquetes (`renewal_required`) y rechaza instantáneas anteriores o ambiguas (`rollback`). La primera preparación y el refresco idéntico siguen funcionando.
- El runtime público `offline-boot.js` cambió, por eso la caché pública rotó a `vinto-off03c4-static-v1`.
- No se persiste en claro ningún secreto, token, contraseña, permiso ni dato industrial; la API de `/api/` nunca se cachea.

### Política de recuperación (explícita, sin borrado automático)

| Situación | Comportamiento |
|---|---|
| Datos locales ilegibles (cifrado alterado, clave distinta) | `needs_recovery`: no se toca nada. El operario puede activar «Recuperación explícita» y repetir; solo entonces se reemplazan los datos ilegibles. |
| Alcance reducido | Se confirma el alcance reducido y se renuevan los paquetes que siguen concedidos. Los paquetes retirados quedan **conservados e inertes** (no se leen). |
| Limpieza de paquetes obsoletos | `discardSupersededPackages(identity, "DISCARD_SUPERSEDED_PACKAGES")`: solo con el token exacto, nunca desde renovación ni arranque, y **no está conectada a la interfaz**. |
| Revocación conocida | Datos preservados y no mostrados como vigentes hasta una renovación verificada. |

## 3. Cobertura de los casos obligatorios

| # | Caso | Prueba |
|---|---|---|
| 1 | Renovación válida y completa | Chrome IDB 01, 01b; UI 03 |
| 2 | Error de red antes del paquete | Chrome IDB 02; UI 02 |
| 3 | Interrupción durante la preparación | Chrome IDB 03 (navegador terminado con la preparación en curso) |
| 4 | Error antes del commit IndexedDB | Chrome IDB 04a (cifrado), 04b (dentro de la transacción), 04c (nunca conjunto mezclado) |
| 5 | Reapertura tras renovación confirmada | Chrome IDB 05; UI 04 |
| 6 | Firma o hash alterado | Chrome IDB 06 (firma de alcance, firma y cuerpo de paquete, hash, clave rotada) |
| 7 | Cambio de usuario | Chrome IDB 07 (alcance de otro usuario/navegador, identidad distinta) |
| 8 | Alcance reducido o revocado | Chrome IDB 08a/08b; UI 05–07 |
| 9 | Paquete incompatible con la versión concedida | Chrome IDB 09 (versión distinta, snapshot anterior, versión menor) |
| 10 | Snapshot anterior al aceptado | Chrome IDB 10 (anterior, mismo segundo, repetición del primero); Node |
| 11 | Fallo de desbloqueo local | Chrome IDB 11 (frase errónea, clave ajena, cifrado alterado, recuperación explícita) |
| 12 | Reinicio tras transacción incompleta | Chrome IDB 12 (navegador terminado con la transacción abierta) |

Además: pruebas Node de ordenación anti-rollback, plan de renovación, esquema local y contratos estáticos (`scripts/off-03c4-renewal.test.mjs`); firmas sintéticas generadas por el **firmador Python real** (`scripts/off03c4_fixture.py`). Se comprobó con una mutación (commit repartido en dos transacciones) que el caso 04c **falla** si la atomicidad se rompe.

Regresiones ejecutadas: pruebas Node OFF-02/03A/03B/03B.3/03C.2/03C.3 y humos de Chrome OFF-02, OFF-03B.1, OFF-03B.3 y OFF-03C.2 (incluye el diagnóstico OFF-03C.3).

## 4. Riesgos residuales y límites

- **Reversión local total:** quien pueda escribir IndexedDB puede restaurar blobs cifrados antiguos (AES-GCM no impide reponer un estado anterior completo). El anti-rollback protege frente a respuestas del servidor y flujos de la app, no frente a manipulación local del almacenamiento; requeriría un ancla externa (Gate C).
- **Reloj y precisión:** el orden se basa en `issued_at` firmado con precisión de segundo; dos instantáneas del mismo segundo con distinto id se rechazan por ambigüedad (el reintento a los pocos segundos funciona).
- **La revocación solo se aprende al renovar online.** No hay sondeo en segundo plano; mientras tanto el estado offline sigue siendo «histórico, no verificable».
- **Marca ilegible = fail-closed:** si la marca sellada se corrompe, la consulta offline se bloquea hasta renovar con Internet.
- **Paquetes retirados** permanecen cifrados hasta una limpieza explícita (política «no borrar automáticamente»); la limpieza aún no tiene interfaz.
- **Concurrencia:** el CAS cubre pestañas distintas del mismo navegador; no hay coordinación entre navegadores (cada uno es un compartimento independiente).
- **Memoria:** el conjunto nuevo se prepara completo en memoria (máx. 24 paquetes ≈ 350 KB cada uno).
- **QA físico NO ejecutado.** Las pruebas de Chrome en CI/local no sustituyen el cierre y reinicio real de un teléfono (M01–M11 / N01–N06, #193).
- El navegador de las pruebas locales fue Chromium de Playwright; la CI usa Google Chrome estable.
- Sigue vigente que el `device_key` es un identificador, no una prueba de posesión del dispositivo.

## 5. Siguiente incremento sugerido

Ejecutar el protocolo físico M01–M11 / N01–N06 con la renovación incluida (después de contar con API QA aislada, identidad sintética y firmas solo QA, gates de #224), y decidir si la interfaz debe ofrecer la limpieza explícita de paquetes obsoletos y un recordatorio de renovación por antigüedad. OFF-04 (captura/sincronización) sigue fuera de la Entrega 1.
