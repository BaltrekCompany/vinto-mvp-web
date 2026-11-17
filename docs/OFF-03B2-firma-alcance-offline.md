# VINTO OFF-03B.2 — Alcance offline firmado por FastAPI (sin escrituras)

**Estado:** candidato en rama `feat/off-03b2-signed-scope-snapshot`, apilado sobre OFF-03B.1 PR #188, el cual depende de #187 y #186. El contrato OFF-01 V2 es PR #184, todos Draft.  
**Meta:** demostrar que el servidor puede generar una fotografía de permisos efectiva, limitada y **firmada asimétricamente**, sin crear una segunda autoridad funcional ni habilitar capturas offline.

## 1. Contrato

**Endpoint candidato (apagado inicialmente):** `POST /api/offline/scope`.

- Requiere cookie HttpOnly vigente que FastAPI resuelve con `Depends(current_user)`, y `APP_ENV` + HTTPS si no es `local/test/qa/ci`.
- **Feature gate exclusivo del servidor:** `OFFLINE_SCOPE_ISSUE_ENABLED=false` por defecto. Con OFF responde 404; con ON pero sin firma válida, 503. No activarlo en producción por incorporar este código.
- **Secreto de firma:** `OFFLINE_SCOPE_SIGNING_SEED_B64URL` (32 bytes aleatorios, codificados base64url canónico, conservados fuera de Git y de respuestas/logs). Con ON se exige este secreto o se falla cerrado. No compartirlo con el cliente.
- **Solicitud:** `{"device_key":"<UUIDv4 por navegador>","machine_codes":["MP1","MP3"]}`, máximo 25 códigos, sin repeticiones. Solo solicita un recorte: el cliente NO concede máquinas/formularios.
- **Motor de autorización real:** enumera únicamente ternas de concesiones activas en `vinto_master.user_machine_form_grant`; reevalúa cada terna en `app.authz.engine.authorize(..., lock=True)`, con perfiles, permiso funcional, sector, máquina, formulario, versión publicada vigente, oferta y concesión activos.
- **Transacción:** la decisión y firma ocurren en un único `connection.transaction()` con bloqueos `FOR SHARE` sobre filas habilitadas por el rol, para reducir ventanas de revocación concurrente. Se preservan las limitaciones documentadas del catálogo de referencias y sectores.
- **Respuesta `Cache-Control: no-store`**: `{algorithm:"Ed25519",key_id,public_key_b64url,payload,signature_b64url}`. La firma abarca bytes JSON canónicos con prefijo de dominio `VINTO-OFFLINE-SCOPE-V1\\x00`. La verificación requiere una clave pública **anclada independientemente a una conexión HTTPS autenticada**, no confiar ciegamente en la clave enviada en el mismo sobre.
- **Alcance de cada fila:** `{machine_code,form_code,form_version,grant_id,operation}` con versión publicada vigente y concesión exacta. Ningún par se inventa por tener el sector. Máximo 200 pares; mayor alcance da 409.
- **Metadatos:** `schema=vinto.offline.scope.v1`, `issuer=vinto-backend`, `audience=vinto-offline-readiness`, `snapshot_id`, `subject_user_id`, `device_key`, `issued_at` UTC. **No `expires_at` forzado por turno** de acuerdo con OFF-01 V2.
- **Cláusula decisiva:** `kind=scope_readiness_only`, `captures_enabled=false`. Este sobre NO es una autorización para POST, no desbloquea el formulario real, ni demuestra que una OT/turno/receta sigue válida al sincronizar.

## 2. Casos denegados

- Sin sesión 401 por las dependencias existentes; sin permiso `production.capture` o `quality.capture`, cuenta con cambio forzoso de contraseña, o sin concesión efectiva: 403.
- Parámetros inválidos, código de máquina fuera de patrón, UUID inválido, más de 25 máquinas: 422. Repetidos y UUID no v4: 403.
- Falta de material de firma, rol que no puede consultar permisos o fallo PostgreSQL: 503 (sin detalles internos). Demasiadas concesiones (más de 200): 409.
- Otra concesión revocada, máquina/formulario inactivo, sector no operativo, versión publicada reemplazada o falta de vínculo: **nunca se firma como permiso actual**.
- No se añade tabla ni migración; el registro de emisión queda en logging servidor con `snapshot_id` y número de pares, sin credenciales ni nombres de usuario. **Auditoría durable por emisión** requiere decisión futura; no reclamarla en esta fase.

## 3. Seguridad y límites (no confundir integridad con vigencia)

1. **Firma válida ≠ autorización vigente.** Una firma histórica continúa siendo verificable incluso si después se revoca la concesión. Al reconectar, el POST deberá revalidar usuario original, permisos, máquina y contexto; guardar como pendiente de conciliación si la asignación cambió, sin atribuir a otra OT silenciosamente.
2. **`device_key` no prueba identidad física.** Hoy es un identificador local por navegador que el cliente declara. Para un vínculo resistente al robo/copias hacen falta clave de prueba de posesión no exportable, registro y política de recuperación: OFF-03B.3.
3. **Confianza de clave pública:** el retorno de `public_key_b64url` permite verificar sintaxis en pruebas. La futura UI debe fijar/trust-anchor la clave pública desde enrolamiento online, proteger rotación y no aceptar un par envelope+clave arbitrario traído de IndexedDB.
4. **Tiempo y cambios de OT:** no introducir TTL por turno durante el piloto. La ausencia de `expires_at` no implica autorización para enviar capturas eternamente ni exime de controles centrales.
5. **Firmar alcance no carga formularios ni recetas.** No se incluyen campos de datos, artículos, turnos, cotizaciones, pesos ni asignaciones. La descarga/cifrado de snapshots operativos queda fuera de este PR.
6. **HTTPS tras proxy:** el endpoint se niega con HTTP si `APP_ENV` es productivo. Debe configurarse correctamente la cadena trusted proxy/Uvicorn antes de cualquier activación futura; NO leer `X-Forwarded-Proto` sin una lista de proxies confiables.
7. **No se activa automáticamente:** `OFFLINE_SCOPE_ISSUE_ENABLED` es falso de origen. No hacer merge ni despliegue hasta revisar claves, funciones de prueba, auditoría, revocación y política de dispositivos.

## 4. Evidencia automatizada

- `backend/tests/test_off03b2_signing.py`: generación/validación Ed25519, comparación de clave pública previamente confiada, alteración de datos/identidad, secret faltante, flag OFF, prueba de motor bloqueado en transacción, falsos permisos y límites de la solicitud. **No usa secretos de producción**.
- `backend/tests/test_off03b2_pg17.py`: PostgreSQL 17 aislado con plantilla de referencias, concesión real a usuario sintético, firmar versión publicada, revocación e intento de reemitir, ausencia de permisos en otra máquina y cuenta desactivada. **Sin tocar VINTO piloto**.
- `.github/workflows/off-03b2-signed-scope.yml`: CI prueba pura + PostgreSQL17 efímero, requisitos Python instalados, sin credenciales externas.
- Verificar rutas anteriores con `test_auth_api.py` y seguridad del motor cuando se integre en rollout posterior; este PR solo añade una ruta bajo feature gate apagado.

## 5. Avance y próximos gates

| Entregable | Estado |
|---|---|
| Firmas Ed25519 y sobre canónico | Implementado |
| Alcance efectivo por motor central con locks | Implementado |
| Endpoint de emisión bajo feature gate OFF | Implementado |
| Prueba real de PostgreSQL17 y test unitarios | Configurados en CI |
| Verificación offline en navegador y pin de clave pública | **Pendiente OFF-03B.3** |
| Contrato activo de formularios, recetas, OT y turnos | **Pendiente OFF-03B.3** |
| Acceso real del operario a formularios offline | **Pendiente** |
| Sincronización, reautenticación y conciliación | **Pendiente OFF-04** |
| Reinicio físico de hardware de planta | **Pendiente QA campo** |

**Rollback/activación:** no hace falta retirar datos porque no hay migraciones ni emisión en default. Si se distribuyera código futuro, OFFLINE_SCOPE_ISSUE_ENABLED=false mantiene la ruta inoperativa. La rotación de claves debe administrarse con `key_id` y política explícita antes de habilitarlo.
