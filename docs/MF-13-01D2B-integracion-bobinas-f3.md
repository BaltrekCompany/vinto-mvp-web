# MF-13-01D.2B — Autorización efectiva en `POST /api/bobbins` (F3)

Estado: **integrado y apagado por defecto (`off`)**. Segunda y última ruta conectada al motor `app/authz` (la primera es `POST /api/captures`, MF-13-01D.2A). Calidad sigue sin motor. No se activó `enforce` ni se tocó la VPS. **No completa MF13-01** (ver §8).

Código: reutiliza la compuerta de 2A generalizada con el cambio mínimo (`OperationGate(user, mode, request_id, operation)`; `CentralCaptureGate` queda como su especialización para `PRODUCTION_CAPTURE`, sin cambios de comportamiento), `app/bobbins/service.py` (`submit_bobbin_production(..., gate=None)`), `app/bobbins/router.py` y `app/config.py`. Pruebas: `tests/test_bobbin_authz.py`.

## 1. Política

Solo `Operation.BOBBIN_PRODUCTION` y solo el formulario `VINTO-P1-03`, que el backend toma de su constante funcional (`bobbins.service.FORM_CODE`). El cuerpo de F3 es cerrado y no contiene formulario, máquina ni operación (prueba: un `form_code`, `machine_code` u `operation` enviados dan 422 y nunca se usan). Se exigen las siete condiciones del motor (usuario activo, permiso `production.capture` de perfiles activos, sector concedido y operativo, máquina y formulario activos, formulario admitido por la política, versión vigente del área vinculada y concesión individual activa). Una concesión de MP1 no autoriza MP3.

## 2. Configuración independiente

`AUTHZ_BOBBIN_PRODUCTION_MODE` (`settings.authz_bobbin_production_mode`) = `off` (inicial) | `observe` | `enforce`; solo servidor; valor desconocido impide arrancar. Es **independiente** de `AUTHZ_CENTRAL_CAPTURES_MODE`: cada router lee únicamente la suya (prueba estática y de comportamiento: F3 en `enforce` con la central en `off` deja pasar la captura central sin concesión, y al revés). No existe interruptor global. `off` no invoca el motor (prueba).

## 3. Orden de bloqueos: F3 frente a la captura central

| Paso | Captura central (2A) | F3 (2B) |
|------|----------------------|---------|
| 1 | `capture_id` (advisory) | `capture_id` (advisory) |
| 2 | idempotencia / contexto de auditoría | idempotencia / contexto de auditoría |
| 3 | **autorización** (usuario → perfiles → máquina+sector → concesión, `FOR SHARE` hasta el COMMIT) | **autorización** (igual) |
| 4 | máquina (advisory, compartido con `assignments`) | máquina (advisory) |
| 5 | asignación (`FOR SHARE`) | asignación (`FOR SHARE`) |
| 6 | dispositivo (advisory por `device_key`) | dispositivo (advisory por `device_key`) |
| 7 | versión publicada, validación, correlativo de formulario | versión publicada, validación, gramaje |
| 8 | — | **fila del contador** `bobbin_sequence` (UPSERT que bloquea la fila) |
| 9 | INSERT captura y detalles | INSERT captura y detalles, bobina y `quality_release` `pending` |

La única diferencia estructural es el paso 8, que ya existía y queda **después** de la autorización: una solicitud denegada nunca llega a reservar número. El contador solo lo toca F3, siempre con el bloqueo de máquina ya tomado, y quien modifica las filas de autorización toca una sola sin esperar otros bloqueos, así que la autorización antepuesta no abre ciclos. No se eliminó ni reordenó ninguna validación existente. La máquina autorizada (leída de la asignación en PostgreSQL con `resolve_assignment_machine`) se confirma contra la definitiva bajo el bloqueo; si difiere, 503. En un reintento el par sale de la captura **persistida**.

## 4. Atomicidad (demostrada)

Una solicitud denegada (`403`), con fallo de infraestructura (`503`) o con contexto cambiado deja **intactos**: capturas, detalles, bobinas, `quality_release`, dispositivos y el contador de numeración (comparación de recuentos antes/después en cada caso). Tras denegaciones intercaladas la numeración sigue siendo correlativa (sin saltos), también bajo concurrencia (4 hilos de registro + 2 de concesión/revocación, sin interbloqueos ni errores).

## 5. Idempotencia

- `enforce`: todo reintento vuelve a autorizarse. Tras una revocación el reintento idéntico da 403 y no crea ni modifica nada (con `off` seguiría siendo 200).
- Reintento legítimo y autorizado con la asignación ya terminada: `already_submitted` (200) con la misma bobina; ni captura, ni bobina, ni correlativo nuevos.
- Conflictos por `capture_id` (valores o dispositivo distintos): 409 como antes.
- Un `capture_id` que pertenece a otra operación (p. ej. una captura central P1-06) no obtiene acceso ni se reutiliza: se autoriza el par persistido, que la política de F3 no admite (403); con `off` sigue siendo el 409 histórico.

## 6. Respuestas y observabilidad

403 / 404 / 503 con los cuerpos fijos del motor (sin razón interna, tablas ni identificadores); los errores funcionales de F3 no cambian. Registro `vinto.authz`: `authz mode=… operation=bobbin_production outcome=… reason=… request_id=…` (sin cookies, usuarios ni valores). En `observe` cualquier fallo del motor, incluso SQL, se registra y se ignora (savepoint) y la bobina se registra igual.

## 7. Matriz de compatibilidad

| Situación | off | observe | enforce |
|-----------|-----|---------|---------|
| P1-03 concedido | 201 | 201 + `allowed` | 201 |
| No concedido | 201 | 201 + `would_forbidden` | 403, nada escrito |
| MP1 concedida, asignación MP3 | 201 | 201 | 403 |
| Perfil sin permiso / usuario inactivo | 403 / 401 (capa existente) | igual | igual |
| Sector no concedido o inactivo | 404/409 existentes | igual | igual |
| Formulario o máquina inactivos | error existente | igual | 403 antes de escribir |
| Versión vigente de otra área o sin vínculo | según flujo existente | log | 403 |
| Revocación antes de registrar | 201 | 201 | 403 |
| Revocación concurrente | n/a | no bloquea | espera a la transacción; la siguiente se deniega |
| Reintento autorizado (asignación terminada) | 200 | 200 | 200 |
| Reintento tras revocar | 200 | 200 | 403 |
| Conflicto de idempotencia | 409 | 409 | 409 (si autorizado) |
| Fallo del motor | n/a | se ignora | 503, nada escrito |

## 8. Riesgos y pendientes (sin cambios respecto a 2A salvo lo anotado)

1. Revocación de **sectores** concurrente con capturas/bobinas (`DELETE` de `user_sector`, no bloqueable con los privilegios de `vinto_app`).
2. **Escritura directa** de concesiones por `vinto_app` (propuesta en MF-13-01D.1 §7).
3. **Calidad** (por bobina y por máquina) sigue sin motor.
4. **Concesiones de usuarios reales**: en `enforce` quedarían bloqueados sin concesión de `VINTO-P1-03` (`authz_readiness.py` mide el impacto de `bobbin_production`).
5. **Frontend**: la disponibilidad no filtra por concesión.
6. Los bloqueos `FOR SHARE` duran toda la transacción de registro; el `statement_timeout` puede convertir una espera larga en 503 reintentable, nunca en acceso.
7. Activación independiente por operación: primero `observe` en ventana limitada revisando `would_forbidden`/`observe_error`; reversión = variable a `off` y reinicio.
