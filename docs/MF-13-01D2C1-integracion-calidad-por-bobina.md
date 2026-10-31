# MF-13-01D.2C.1 — Autorización efectiva en `POST /api/quality/bobbins/{bobbin_id}/captures`

Estado: **integrado y apagado por defecto (`off`)**. Tercera ruta conectada al motor `app/authz` (después de `POST /api/captures`, 2A, y `POST /api/bobbins`, 2B). **Calidad por máquina sigue sin motor.** No se activó `enforce` ni se tocó la VPS. No completa MF13-01 (ver §9).

Código: reutiliza la compuerta de 2A/2B (`OperationGate`), cambios mínimos en `app/quality/capture_service.py` (`submit_quality_capture(..., gate=None)`), `app/quality/router.py` y `app/config.py`. Pruebas: `tests/test_quality_bobbin_authz.py`.

## 1. Qué hace la operación hoy (diagnóstico)

Recursos que **escribe**: `vinto_txn.capture` (borrador → enviada, `revision = 1`), `vinto_txn.capture_detail` y, si el `device_key` es nuevo, `vinto_master.device`. Recursos que **solo lee**: la bobina y la captura F3 de origen (máquina, turno, fecha operativa y asignación **históricos**; no usa la asignación activa ni el turno actual), la versión publicada de área `quality` vinculada a la máquina de la bobina y el maestro. **No toca `quality_release`** (ni liberar, ni rechazar, ni `decided_*`), ni la bobina, ni órdenes, ni asignaciones.

### Orden de bloqueos

| Paso | Antes | Con la compuerta (`observe`/`enforce`) |
|------|-------|-----------------------------------------|
| 1 | `capture_id` (advisory, misma clave que F6/F3) | igual |
| 2 | contexto de auditoría; idempotencia | igual |
| 3 | — | reintento: **autorización** del par persistido |
| 4 | bobina + contexto histórico (lectura, alcance de sectores) | igual |
| 5 | — | captura nueva: **autorización** (usuario → perfiles → máquina+sector → concesión, `FOR SHARE` hasta el COMMIT) |
| 6 | dispositivo (advisory por `device_key`; puede crearlo) | igual (**después** de autorizar: una denegación no crea dispositivo) |
| 7 | — | reconfirmación: la bobina y su máquina siguen siendo las autorizadas (si no, 503) |
| 8 | versión publicada, validación de valores, mínimos, número de bobina declarado | igual |
| 9 | INSERT captura, detalles, `draft → submitted` | igual |

Esta ruta **no** toma el bloqueo de máquina ni el de asignación (a diferencia de F6/F3): los únicos bloqueos previos son `capture_id` y dispositivo. La autorización siempre va antes que cualquier bloqueo de máquina/dispositivo en las tres rutas (`capture_id → autorización → máquina/asignación → dispositivo → escrituras`), así que el orden global es consistente. Ningún flujo que modifica las filas de autorización las toca mientras espera otro bloqueo (pruebas de carga mixta sin interbloqueos incluidas).

## 2. Política

Solo `Operation.QUALITY_BOBBIN_CAPTURE`, permiso `quality.capture`, área `quality`. La **máquina sale de la bobina persistida** en PostgreSQL (captura nueva) o de la captura persistida (reintento); el cuerpo es cerrado y no admite máquina, operación ni bobina (422). El formulario es el solicitado, ya validado por la política positiva del servicio (`_allowed`). Una concesión de Producción (p. ej. P1-01 o P1-03) **no** autoriza Calidad: cada formulario necesita su propia concesión (probado).

## 3. Formularios admitidos y hallazgo de los candidatos

El motor lee en vivo las constantes del servicio: `CENTRAL_BOBBIN_FORM_CODES` (P1-19, P1-20) ∪ (`BOBBIN_CANDIDATE_FORM_CODES` ∩ `ENABLED_BOBBIN_CANDIDATE_FORM_CODES`). Ni se amplían ni se reducen; no se homologa ningún formulario.

> **Hallazgo para validación funcional.** Varias descripciones históricas dicen que los candidatos por bobina están deshabilitados («vacío en producción», «vacío con la política real»), pero el código actual define `ENABLED_BOBBIN_CANDIDATE_FORM_CODES = BOBBIN_CANDIDATE_FORM_CODES`: **P1-21, P1-24, P1-25 y P1-28 están habilitados hoy** (CLOUD-DEP G.12-C4, «QA interno»). Una prueba fija este comportamiento y otras demuestran que el motor sigue exactamente la constante (con `ENABLED = {}` solo P1-19/P1-20; con `{P1-28}` se añade solo ese). Hay que confirmar con producto si esa habilitación es la deseada **antes de activar `enforce`**: el motor no la decide, la hereda.

P1-28 sigue siendo documental: una captura autorizada de P1-28 no cambia `quality_release` ni crea aprobación o rechazo (prueba).

## 4. Modos independientes

`AUTHZ_QUALITY_BOBBIN_CAPTURES_MODE` (`settings.authz_quality_bobbin_captures_mode`) = `off` (inicial) | `observe` | `enforce`; solo servidor; valor desconocido impide arrancar. Independiente de `AUTHZ_CENTRAL_CAPTURES_MODE` y `AUTHZ_BOBBIN_PRODUCTION_MODE` (probado en ambos sentidos); cada router lee únicamente la suya. Calidad por máquina no usa el motor. `off` no invoca el motor; `observe` evalúa sin bloqueos en un savepoint y nunca cambia datos ni respuesta; `enforce` usa `authz.require(lock=True)` en la misma transacción.

## 5. Idempotencia y precedencia de errores

Orden de respuestas (se conserva el existente y se añade el motor donde se indica):

1. Sesión / `quality.capture` → 401 / 403 (capa existente).
2. `bobbin_id`, `capture_id`, `device_key` mal formados → 404 / 422; `form_code` vacío → 422.
3. Formulario fuera de la política positiva → 422 `UNSUPPORTED_FORM` (**antes** del motor, también en reintentos: el motor ni se invoca).
4. Reintento (capture_id ya guardado): **motor sobre el par persistido** → 403/404/503; después la comparación existente → `already_submitted` (200) o conflicto de idempotencia (409).
5. Captura nueva: bobina inexistente o fuera del alcance → 404 (**antes** del motor); **motor** → 403/404/503; después dispositivo, versión no disponible (409), valores (422).

Consecuencias probadas: reintento autorizado e idéntico → 200 `already_submitted` sin escribir nada; reintento tras revocación → 403 (con `off` seguiría siendo 200); valores, dispositivo, formulario o bobina contradictorios → 409; una captura persistida por otra ruta (p. ej. la bobina F3, P1-03) enviada con su `capture_id` → 403 en `enforce` (el par persistido no lo admite esta política) y el 409 histórico con `off`; las lecturas de capturas históricas no pasan por el motor y no cambian.

## 6. HTTP y observabilidad

403 / 404 / 503 con los cuerpos fijos del motor (sin razón interna, tablas ni identificadores). Registro `vinto.authz`: `authz mode=… operation=quality_bobbin_capture outcome=… reason=… request_id=…`, sin cookies, usuarios ni valores. La auditoría de la captura conserva su atribución (mismos eventos y mismo actor con `off` y con `enforce`; el motor no escribe nada).

## 7. Matriz de compatibilidad

| Situación | off | observe | enforce |
|-----------|-----|---------|---------|
| Formulario concedido (P1-19) | 201 | 201 + `allowed` | 201 |
| No concedido | 201 | 201 + `would_forbidden` | 403, nada escrito |
| Concesión de otro formulario o de Producción | 201 | 201 | 403 |
| MP1 concedida, bobina de MP3 | 201 | 201 | 403 |
| Perfil sin `quality.capture` / usuario inactivo | 403 / 401 | igual | igual |
| Sector no concedido | 404 existente | igual | igual |
| Formulario/máquina inactivos | error existente | igual | 403 antes de escribir |
| Formulario de otra ruta | 422 | 422 | 422 (antes del motor) |
| Versión vigente de otra área o sin vínculo | según flujo | log | 403 |
| Revocación antes / concurrente | 201 | no bloquea | 403 / la revocación espera |
| Reintento autorizado / tras revocar | 200 / 200 | 200 / 200 | 200 / 403 |
| Fallo del motor | n/a | se ignora | 503, nada escrito |

## 8. Riesgos de concurrencia

Los `FOR SHARE` duran toda la transacción de captura; una revocación espera y el `statement_timeout` puede convertir una espera larga en 503 reintentable, nunca en acceso. Solo se bloquean filas que `vinto_app` puede bloquear (límites en MF-13-01D.1 §4). Esta ruta no usa bloqueo de máquina, por lo que la confirmación del contexto se hace releyendo la bobina tras tomar los bloqueos de autorización y de dispositivo.

## 9. Pendientes para activar (sin cambios materiales)

1. Validar funcionalmente el hallazgo de los candidatos (§3).
2. Revocación de **sectores** concurrente (`DELETE` de `user_sector`, no bloqueable).
3. **Escritura directa** de concesiones por `vinto_app`.
4. **Calidad por máquina** sin motor.
5. **Concesiones de usuarios reales** de Calidad (`authz_readiness.py` mide el impacto de `quality_bobbin_capture`): sin concesión quedarían bloqueados en `enforce`.
6. **Frontend**: la disponibilidad no filtra por concesión.
7. Activación por operación: `observe` en ventana limitada revisando `would_forbidden`/`observe_error`; reversión = variable a `off` y reinicio.
