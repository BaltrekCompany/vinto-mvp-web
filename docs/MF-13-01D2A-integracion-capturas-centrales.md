# MF-13-01D.2A — Autorización efectiva en `POST /api/captures`

Estado: **integrado y apagado por defecto (`off`)**. Es la única ruta conectada al motor `app/authz`. No se activó ninguna restricción real ni se tocó la VPS. **Este PR no completa MF13-01** (ver §9).

Código: `app/authz/capture_gate.py` (compuerta), cambios mínimos en `app/capture_service.py` (`submit_production_capture(..., gate=None)` y `resolve_assignment_machine`), `app/captures.py`, `app/config.py` y un manejador de errores en `app/main.py`. Pruebas: `tests/test_central_capture_authz.py`.

## 1. Orden de bloqueos (documentado antes de modificarlo)

Antes de este cambio (`capture_service`, docstring del módulo):
`capture_id` (advisory) → idempotencia → contexto de auditoría → **máquina** (advisory, compartido con `assignments` activate/finish) → **asignación** (`FOR SHARE`) → **dispositivo** (advisory por `device_key`) → versión publicada → inserciones. `activate` toma OT → máquina → asignación y `finish` máquina → asignación; la captura nunca toma la OT.

Con la compuerta (`observe`/`enforce`):

`capture_id` → idempotencia → **autorización (usuario → perfiles → máquina+sector → concesión, `FOR SHARE` hasta el COMMIT)** → máquina → asignación → dispositivo → inserciones.

Por qué no hay ciclo: ningún flujo que toma el bloqueo de máquina (activate/finish/capturas) modifica filas de usuario, perfil, máquina, sector ni concesión mientras lo mantiene (comprobado: `assignments` y `work_orders` no escriben `vinto_master`), y quien las modifica (administración de concesiones, desactivación de usuarios) toca **una sola** fila sin esperar otros bloqueos. Una revocación espera a la captura en curso; una captura que llega con una revocación pendiente espera y, al confirmarse, la ve (READ COMMITTED). No se eliminó ni se reordenó ningún control existente. Prueba de carga mixta sin interbloqueos incluida.

## 2. Resolución confiable de la máquina

- **Captura nueva**: la máquina sale de la asignación registrada en PostgreSQL (`resolve_assignment_machine`, lectura sin bloqueo y con el mismo alcance de sectores que el flujo normal; asignación inexistente o no visible → `AssignmentNotFoundError`, igual que hoy). El cuerpo es cerrado (`extra=forbid`): un `machine_code` enviado por el cliente se rechaza con 422 y jamás se usa. Se autoriza **antes** del bloqueo de máquina y, ya bajo ese bloqueo, se comprueba que el contexto definitivo (`lock_active_assignment`) es la misma máquina; si no, **503** (falla cerrado, reintentable).
- **Captura existente**: el par (máquina, formulario) sale de la captura **persistida** (`capture.machine_id` y el formulario guardado), no del reintento. Un reintento que nombra otro formulario se autoriza por el persistido y después choca con la idempotencia (409), como hoy.

## 3. Modos (solo servidor)

Variable de entorno `AUTHZ_CENTRAL_CAPTURES_MODE` (`settings.authz_central_captures_mode`), valores `off` (inicial) | `observe` | `enforce`, sin distinguir mayúsculas. Un valor desconocido **impide arrancar** (nunca cae a `off` en silencio). No existe cabecera, parámetro ni campo de cuerpo que lo cambie, ni un interruptor global: cada operación tendrá el suyo; F3 y Calidad no usan el motor.

| Modo | Efecto |
|------|--------|
| `off` | El router no construye la compuerta: el flujo es **idéntico al anterior** (ni se llama al motor). |
| `observe` | Evalúa **sin bloqueos**, dentro de un *savepoint* (un fallo SQL del motor no aborta la captura), registra la decisión y no cambia datos ni respuesta; cualquier excepción del motor se registra y se ignora. |
| `enforce` | `authz.require(lock=True)` en la misma transacción que registra la captura: 403 / 404 / 503. |

## 4. Idempotencia

- `enforce`: **todo reintento** de una captura existente vuelve a autorizarse. Tras una revocación, el reintento idéntico recibe 403 y no se crea ni modifica nada (capturas y detalles intactos).
- Una captura legítima cuya asignación terminó después sigue devolviendo `already_submitted` (200) si el acceso sigue vigente: el flujo de reintento no vuelve a exigir una asignación activa (comportamiento histórico, sin cambios).
- Se conserva la detección de conflictos por `capture_id`, actor, formulario, asignación, dispositivo y valores (409).
- `off`: el mismo reintento tras la revocación sigue siendo idempotente (200), como antes.

## 5. Respuestas y observabilidad

| Situación | Respuesta |
|-----------|-----------|
| Denegado | 403 `{"detail": "Acceso no autorizado", "code": "FORBIDDEN"}` |
| Usuario/máquina/formulario inexistente según el motor | 404 `{"detail": "Recurso no encontrado", "code": "NOT_FOUND"}` |
| No se pudo decidir (tabla ausente, privilegio, bloqueo/tiempo, contexto cambiado) | 503 `{"detail": "Autorización no disponible", "code": "AUTHORIZATION_UNAVAILABLE"}` |
| Errores funcionales existentes (422, 409, 404 de asignación, turno…) | sin cambios |

Los cuerpos son fijos: no incluyen razón interna, SQL, sectores, perfiles ni identificadores. Nota: un sector no concedido al usuario sigue produciendo el 404 de «asignación inexistente» del alcance de sectores existente, **antes** de que el motor decida.

Registro técnico (logger `vinto.authz`): `authz mode=… operation=production_capture outcome=… reason=… request_id=…` (`allowed` INFO; `forbidden`, `would_forbidden`, `context_changed` WARNING; `unavailable`, `observe_error` ERROR). No contiene cookies, credenciales, identificadores de usuario ni valores del formulario (prueba). No es una tabla de auditoría: no se escribe nada en PostgreSQL por observar o autorizar (la auditoría de capturas conserva su atribución, comprobada igual en `off` y `enforce`).

## 6. Matriz de compatibilidad

| Situación | off | observe | enforce |
|-----------|-----|---------|---------|
| Par concedido, captura nueva | 201 | 201 + log `allowed` | 201 |
| Par **no** concedido | 201 | 201 + log `would_forbidden` | 403, nada escrito |
| Concesión revocada antes | 201 | 201 + log | 403 |
| MP1 concedida, asignación MP3 | 201 | 201 | 403 (independientes) |
| Usuario inactivo / perfil sin permiso | 401 / 403 (capa existente) | igual | igual (el motor no se alcanza) |
| Sector no concedido | 404 (alcance existente) | igual | igual |
| Formulario no ofrecido por la máquina | error funcional existente | igual | 403 antes del error funcional |
| Versión vigente de otra área | según captura (por área) | log | 403 (`EFFECTIVE_VERSION_OTHER_AREA`) |
| Reintento idéntico, acceso vigente | 200 `already_submitted` | 200 | 200 |
| Reintento idéntico tras revocar | 200 | 200 | **403**, sin cambios |
| Reintento con asignación ya terminada | 200 | 200 | 200 si sigue autorizado |
| Reintento con valores distintos | 409 | 409 | 409 (si autorizado) |
| Fallo del motor | n/a | se ignora (201) | **503**, nada escrito |
| Contexto definitivo ≠ autorizado | n/a | log | 503 |

## 7. Riesgos de concurrencia

- Los bloqueos `FOR SHARE` se mantienen durante toda la transacción de captura (incluye validación e inserciones): una revocación espera hasta que termine; el `statement_timeout` de la aplicación (2 s por defecto) puede convertir una espera larga en **503** (reintentable), nunca en acceso.
- Solo se bloquean las filas que `vinto_app` puede bloquear (usuario, perfiles, máquina+sector, concesión); `user_sector` y `vinto_config` no admiten bloqueo de fila con sus privilegios reales (`42501`). Riesgos residuales (retiro de sector concurrente, importaciones de catálogo durante una captura): ver `docs/MF-13-01D1-motor-autorizacion-efectiva.md` §4.
- `observe` no retiene bloqueos: solo informa; una revocación concurrente no se ve bloqueada.
- Coste: `observe` añade lecturas por captura; `enforce` añade además bloqueos compartidos (compatibles entre capturas concurrentes).

## 8. Confirmación de que `off` reproduce el comportamiento previo

- Con `off` el router pasa `gate=None` y el servicio ejecuta exactamente las mismas sentencias que antes (todas las llamadas nuevas están detrás de `if gate is not None`); una prueba verifica que el motor no se invoca.
- Toda la suite existente de capturas, asignaciones, F3 y Calidad se ejecuta sin cambios en modo por defecto y se compara contra `main` (0 fallos nuevos).

## 9. Lo que NO resuelve este PR (dependencias de seguridad)

1. Sincronización de la **revocación de sectores** con capturas concurrentes (`DELETE` de `user_sector` no bloqueable; propuesta: que su administración tome `FOR UPDATE` sobre la fila del usuario).
2. **Endurecimiento de la escritura directa** de concesiones por `vinto_app` (INSERT/UPDATE directos sobre la tabla; propuesta en el documento de MF-13-01D.1 §7).
3. **Integración de F3 (`/api/bobbins`) y de Calidad** (por bobina y por máquina): siguen sin motor.
4. **Preparación de concesiones para usuarios reales** (`authz_readiness.py` mide el impacto; hoy los usuarios reales pueden no tener concesiones individuales y quedarían bloqueados en `enforce`).
5. **Visibilidad en el frontend según permisos** (la lista de máquinas/formularios disponibles no filtra por concesión).
6. Decisiones funcionales abiertas: lecturas de capturas y áreas mixtas por formulario (`docs/MF-13-01D11-…`).

## 10. Pendientes para activar `enforce`

1. Medir con `authz_readiness.py` y sembrar las concesiones iniciales (con actor y motivo) hasta que ningún operador autorizado quede bloqueado.
2. Resolver los puntos 1 y 2 de §9 o aceptarlos por escrito.
3. Periodo en `observe` (ventana limitada) revisando `would_forbidden` y `observe_error` en el registro.
4. Activar `enforce` en ventana de baja actividad con administración lista para conceder en caliente; reversión = volver la variable a `off` y reiniciar (no hay migración que deshacer).
5. Decidir el tratamiento de 503 en el cliente (reintento) antes de exponerlo a operadores.
