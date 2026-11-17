# VINTO OFF-03C.2 — Formularios Calidad firmados, cifrados y consultables sin red

**Estado:** candidato de ensayo aislado. Sin captura, sin producción ni cambios en VPS.  
**Base:** OFF-03C.1 PR #191, que depende de OFF-03B.3 PR #190 y de #189/#188/#187/#186. Contrato OFF-01 V2 en #184.

## Función entregada

Con sesión online y autorización efectiva emitida por FastAPI, el operario prepara su perfil cifrado y su alcance firmado tal como en OFF-03B.3. Después puede seleccionar **una máquina y un formulario de Calidad por máquina** de los códigos P1-18/22/26/27 que ya aparezcan en su alcance y solicitar un paquete de definición completa al nuevo endpoint `POST /api/offline/quality-package`.

El cliente:
1. Revalida online `/api/auth/me` y el propietario del navegador; desbloquea el perfil local mediante la frase de acceso.
2. Recupera y verifica el alcance firmado **contra el pin de clave pública previamente cifrado**.
3. Solicita al servidor la definición actual para `machine_code` y `form_code`, entregando el alcance firmado original; no permite ampliarlo ni elegir una versión arbitraria.
4. Verifica **firma Ed25519 de paquete en dominio propio**, `content_sha256` calculado sobre JSON canónico, identidad, dispositivo, concesión, versión, `scope_snapshot_id` y tipo `quality_machine_capture`.
5. Rechaza propiedades desconocidas, campos automáticos, grupos/opciones dependientes no soportados, recetas externas y cualquier indicador de capacidad de captura.
6. Cifra AES-256-GCM todo el paquete, incluido el nombre, las etiquetas, opciones y la definición. La clave local es la misma bóveda que protege el alcance; AAD vincula usuario, navegador, paquete y snapshot.
7. Guarda solo `{packageKey` opaco hasheado, propietario/dispositivo, `packageId`, `scopeSnapshotId`, `sealed`}` en IndexedDB. **La definición no se guarda en claro.**
8. Al cerrar/reabrir el navegador sin Internet, desbloquea la clave, verifica el alcance, descifra cada paquete de Calidad y vuelve a verificar SHA256 y firma. Muestra un `details` de **solo lectura** con campos, tipos, obligatoriedad, unidades y opciones. Campos calculados aparecen con la etiqueta «calculado por backend»; **no hay inputs editables de captura**.

## Actualización de IndexedDB

Se conserva el nombre `vinto-off03a-profiles-v1` y se eleva versión de esquema **2 a 3** mediante `onupgradeneeded`: se mantienen intactos `profiles` y `scopes`, se agrega `quality_packages`. Se ajustan pruebas heredadas para evitar `VersionError` al volver a abrir una base actualizada.

**Política conservadora contra rollback:** solo se acepta reescritura del mismo paquete si la versión no retrocede ni cambia silenciosamente el hash con igual versión. Cuando cambia el `scope_snapshot_id`, los paquetes anteriores no se consideran vigentes; su reemplazo sin proceso de recuperación queda bloqueado. **Este último flujo requiere diseñar renovación autenticada/rotación antes del piloto**, para no obligar a borrar indiscriminadamente datos cifrados.

## Pruebas

- Generador sintético `scripts/off03b3_fixture.py`, extendido sin cambiar la firma de alcance anterior: usa el **firmador Python real** para firmar una definición de Calidad P1-18 ficticia, con campos y hash.
- `scripts/off-03c2-package.test.mjs`: WebCrypto Node comprueba firma Python→JavaScript, hash, pin, vinculación a concesión, usuario, navegador, máquina, versión, rechazo de corrupción y ausencia de cambios en captura.
- `scripts/off-03c2-browser-smoke.py`: Chrome real con APIs **simuladas exclusivamente en QA**, enrolamiento, scope, paquete cifrado en IndexedDB, cierre de navegador, reapertura sin conexión, campos de solo lectura, rechazo de ciphertext alterado. No emplea datos industriales.
- Workflow `OFF-03C2 Encrypted Quality Form Package Browser QA`: Node, TypeScript, lint, build portable y Chrome. Mantener regresiones OFF-02/03A/03B.1/03B.3.

## Separación de riesgos y gates

- **El servidor de #191 sigue apagado por defecto**: `OFFLINE_SCOPE_ISSUE_ENABLED=false` y `OFFLINE_QUALITY_PACKAGE_ISSUE_ENABLED=false`. El mock de CI NO equivale a un backend de ensayo activado.
- La definición firmada y cifrada acredita integridad **histórica**. No afirma que el usuario conserve permisos, que una OT siga igual o que el formulario haya sido homologado.
- No incluye recetas por artículo, resultados ni valores de producción. La fuente es la versión publicada en `vinto_config`, no un JSON de semilla. Al detectar una dependencia de formulario no soportada, el backend deniega el paquete.
- Calidad por bobina (madre/F3) queda fuera del primer lote: exige genealogía y contexto distintos.
- **No hay formulario editable, validación industrial offline ni cola de envíos.** OFF-04 sigue pendiente.
- **Antes del piloto**: revisión de seguridad (dispositivo, clave, revocación, recuperación, anti-rollback), prueba física de reinicio de dispositivo y datos en HTTPS de ensayo, validación de coherencia de la definición vigente, homologación funcional de Calidad y aceptación de la ruta de captura/sincronización.

## Control de liberación

No hacer merge ni despliegue, no activar flags en producción, no almacenar firmas privadas en repositorio, no migrar PostgreSQL productivo. El contrato de usuario «abrir VINTO offline tras cerrar y reiniciar» se prueba en Chrome de CI, pero el reinicio **físico del móvil compartido** aún debe ejecutarse.
