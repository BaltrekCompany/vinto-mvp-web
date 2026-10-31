# MF-13-01D.2C.2 — Autorización efectiva en `POST /api/quality/machines/{machine_code}/captures`

Estado: **integrado y apagado por defecto (`off`)**. Cuarta y última ruta de captura conectada al motor `app/authz` (central 2A, F3 2B, Calidad por bobina 2C.1, Calidad por máquina 2C.2). Ningún modo se activó y la VPS no se tocó. **No completa MF13-01** (ver §9).

Código: reutiliza la compuerta de 2A/2B/2C.1 (`OperationGate`), cambios mínimos en `app/quality/machine_capture_service.py` (`submit_machine_capture(..., gate=None)`), `app/quality/machine_router.py` y `app/config.py`. Pruebas: `tests/test_quality_machine_authz.py`.

## 1. Qué hace la operación hoy (diagnóstico)

Esta ruta es **independiente de asignaciones, órdenes y bobinas**: `assignment_id` y `bobbin_id` quedan `NULL`; la máquina viene del código de la ruta; el turno y la fecha operativa los resuelve el backend (`resolve_shift`) con el reloj de PostgreSQL en el momento del registro; el responsable es el usuario autenticado (`created_by`, solo informativo).

Recursos que **escribe**: `vinto_txn.capture` (borrador → enviada, `revision = 1`), `vinto_txn.capture_detail` y, si el `device_key` es nuevo, `vinto_master.device`. **No toca** `quality_release`, bobinas, órdenes ni asignaciones.

### Orden de transacción y bloqueos

| Paso | Antes | Con la compuerta (`observe`/`enforce`) |
|------|-------|-----------------------------------------|
| 0 | `capture_id` y `device_key` válidos; `form_code` ∈ `MACHINE_QUALITY_FORM_CODES` (si no, 422) | igual |
| 1 | `capture_id` (advisory, misma clave que F6/F3/Calidad por bobina) | igual |
| 2 | contexto de auditoría; **máquina de la ruta resuelta contra PostgreSQL** (404 si no existe, 422 fuera de alcance o inactiva) | igual |
| 3 | idempotencia (captura existente) | reintento: **autorización** del par persistido, antes de comparar |
| 4 | — | captura nueva: **autorización** (usuario → perfiles → máquina+sector → concesión, `FOR SHARE` hasta el COMMIT) |
| 5 | reloj de PostgreSQL y turno (lectura) | igual |
| 6 | dispositivo (advisory por `device_key`; puede crearlo) | igual (**después** de autorizar: una denegación no crea dispositivo) |
| 7 | — | reconfirmación: la máquina **y su sector** siguen siendo los autorizados (si no, 503) |
| 8 | versión publicada (área `quality`), validación y cálculos (MF-08) | igual |
| 9 | INSERT captura, detalles, `draft → submitted` | igual |

Como Calidad por bobina, esta ruta **no** toma bloqueo de máquina ni de asignación: solo `capture_id` y dispositivo. La autorización va siempre antes de cualquier bloqueo de máquina/dispositivo en las cuatro rutas (`capture_id → autorización → máquina/asignación → dispositivo → escrituras`).

### Riesgo de concurrencia con el cambio de sector o de identidad de la máquina

El turno se resuelve con el `sector_id` leído al resolver la máquina (paso 2), antes del bloqueo de autorización. Un cambio de sector concurrente haría que el turno correspondiera a un sector que la máquina ya no tiene. Se resuelve **sin quitar ningún control**: la autorización retiene `FOR SHARE` sobre la fila de la máquina y de su sector, así que un `UPDATE` de la máquina (cambio de sector o de identidad) espera a que termine la captura (probado: `lock_timeout` sobre `machine`); y tras los bloqueos se relee `(máquina, sector)` y se compara con lo autorizado (pruebas que simulan el cambio de cualquiera de los dos → 503 sin escrituras). Riesgo residual: el cambio puede confirmarse **antes** del bloqueo de autorización pero **después** de la primera lectura; la reconfirmación lo detecta y la captura responde 503 reintentable en vez de usar un turno inconsistente.

## 2. Política

Solo `Operation.QUALITY_MACHINE_CAPTURE`, permiso `quality.capture`, área `quality`. La máquina es la del código de la ruta, **resuelta y validada contra PostgreSQL antes de autorizar** (un código inexistente responde 404 y uno fuera de alcance 422, ambos antes del motor); el cuerpo es cerrado y no admite otra máquina (422). El formulario debe estar en `MACHINE_QUALITY_FORM_CODES` (validación funcional previa, 422) y además lo admite la política del motor, que lee esa misma constante en vivo. Los formularios de Calidad por bobina no se admiten por esta ruta y viceversa (conjuntos disjuntos, probado). Una concesión de Producción no autoriza Calidad.

### Formularios habilitados hoy (QA interno, pendiente de confirmación)

> **Hallazgo para validación funcional.** El docstring del servicio habla de una política «VACÍA en la configuración real», pero el código habilita hoy **P1-18, P1-22, P1-26 y P1-27** (CLOUD-DEP G.12-C4: «EXCLUSIVAMENTE para QA interno sobre MP1/MP3», sin homologar contratos, rangos ni unidades). Una prueba fija este conjunto y otras demuestran que el motor sigue exactamente la constante (con `{}` no admite ninguno). El motor hereda esta habilitación, no la decide: hay que confirmarla con producto antes de activar `enforce`.

## 3. Modos independientes

`AUTHZ_QUALITY_MACHINE_CAPTURES_MODE` (`settings.authz_quality_machine_captures_mode`) = `off` (inicial) | `observe` | `enforce`; solo servidor; valor desconocido impide arrancar. **Independiente de las otras tres** (probado con cada una de las cuatro en `enforce` y las demás en `off`); cada router lee únicamente la suya y no existe interruptor global. `off` no invoca el motor; `observe` evalúa sin bloqueos en un savepoint y nunca cambia datos ni respuesta; `enforce` usa `authz.require(lock=True)` en la misma transacción.

## 4. Idempotencia y precedencia de errores

1. Sesión / `quality.capture` → 401 / 403.
2. `capture_id`, `device_key`, `form_code` mal formados → 422; formulario fuera de `MACHINE_QUALITY_FORM_CODES` → 422 `UNSUPPORTED_FORM` (**antes** del motor, también en reintentos).
3. Máquina inexistente → 404; fuera de alcance o inactiva → 422 `MACHINE_OUTSIDE_SCOPE` (**antes** del motor).
4. Reintento: **motor sobre el par persistido** (máquina y formulario guardados) → 403/404/503; después la comparación existente → `already_submitted` (200) o conflicto (409).
5. Captura nueva: **motor** → 403/404/503; después turno (409 si no hay turno), dispositivo, versión no disponible (409) y valores (422).

Probado: reintento idéntico autorizado → 200 sin escribir nada; tras revocar → 403 (con `off` seguiría siendo 200); valores, dispositivo, formulario o **máquina** contradictorios (la misma captura reenviada por la ruta de otra máquina) → 409 contra lo persistido; una captura persistida por otra ruta (p. ej. la bobina F3, P1-03) enviada con su `capture_id` → 403 en `enforce` y el 409 histórico con `off`; las lecturas históricas no pasan por el motor y no cambian.

## 5. Reglas de Calidad preservadas (probado off vs enforce)

Valores y cálculos automáticos idénticos (p. ej. `porcentaje_cantidad_de_seco` de P1-26 = 25.00), mismo turno, fecha operativa, hora de registro y responsable, sin asignación ni bobina, `quality_release` sin cambios y la auditoría de la captura con los mismos eventos y el mismo actor. Una concesión nunca convierte una captura en liberación ni rechazo.

## 6. HTTP y observabilidad

403 / 404 / 503 con los cuerpos fijos del motor (sin razón interna, tablas ni identificadores). Registro `vinto.authz`: `authz mode=… operation=quality_machine_capture outcome=… reason=… request_id=…`, sin cookies, usuarios ni valores.

## 7. Matriz de compatibilidad

| Situación | off | observe | enforce |
|-----------|-----|---------|---------|
| Formulario concedido | 201 | 201 + `allowed` | 201 |
| No concedido / concesión de otro formulario o de Producción | 201 | 201 + `would_forbidden` | 403, nada escrito |
| MP1 concedida, ruta de MP3 | 201 | 201 | 403 |
| Máquina inexistente / fuera de alcance | 404 / 422 | igual | igual (antes del motor) |
| Perfil sin `quality.capture` / usuario inactivo | 403 / 401 | igual | igual |
| Formulario inactivo | error existente | igual | 403 |
| Formulario de otra ruta | 422 | 422 | 422 (antes del motor) |
| Versión vigente de otra área o sin vínculo | según flujo | log | 403 |
| Revocación antes / concurrente | 201 | no bloquea | 403 / la revocación y el cambio de máquina esperan |
| Reintento autorizado / tras revocar | 200 / 200 | 200 / 200 | 200 / 403 |
| Fallo del motor | n/a | se ignora | 503, nada escrito |

## 8. Riesgos de concurrencia

Los `FOR SHARE` duran toda la transacción de captura; una revocación o un cambio de la máquina esperan y el `statement_timeout` puede convertir una espera larga en 503 reintentable, nunca en acceso. Solo se bloquean filas que `vinto_app` puede bloquear (usuario, perfiles, máquina+sector, concesión; `user_sector` y `vinto_config` no, ver MF-13-01D.1 §4). Pruebas de carga mixta sin interbloqueos y con el rol construido desde `backend/roles/*.sql`.

## 9. Pendientes para activar (sin cambios materiales)

1. Validar funcionalmente la habilitación de P1-18/22/26/27 (§2).
2. Revocación de **sectores** concurrente (`DELETE` de `user_sector`, no bloqueable).
3. **Escritura directa** de concesiones por `vinto_app`.
4. **Concesiones de usuarios reales** de Calidad (`authz_readiness.py` mide el impacto de `quality_machine_capture`).
5. **Frontend**: la disponibilidad no filtra por concesión.
6. Las cuatro operaciones se activan **por separado**: primero `observe` en ventana limitada revisando `would_forbidden`/`observe_error`; reversión = variable a `off` y reinicio.
