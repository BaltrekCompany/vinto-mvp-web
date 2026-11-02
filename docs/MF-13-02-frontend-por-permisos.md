# MF-13-02 — Frontend por permisos y concesiones

Estado: implementado en la rama `feat/mf-13-02-frontend-por-permisos`. **No toca la VPS, TVC, ETL ni Power BI, no despliega y no cambia formularios, versiones ni reglas industriales.** Las cuatro compuertas de autorización siguen en `off` por defecto.

## 1. Qué cambia para el usuario

Cada persona ve solo los frentes, las máquinas y los formularios que puede usar hoy. Lo que no está concedido **se oculta** (no se muestra deshabilitado). Se aplica a: frentes (menú de escritorio y de móvil), máquinas de Bobinas, tarjetas F3 / F6, fichas candidatas de Bobinas, Rebobinado, Conversión y las dos modalidades de Calidad (por bobina y por máquina), incluidas las acciones P1-19 (humedad) y P1-20 (propiedades físicas).

Sin ningún frente disponible se muestra la pantalla «Sin accesos asignados» (sin motivos internos). Quien tiene `user.manage` conserva siempre el enlace a **Administración**, aunque no tenga sectores operativos.

## 2. Elegibilidad ≠ modo de autorización (decisión de diseño)

| Concepto | Qué decide | Dónde |
|---|---|---|
| **Elegibilidad** (`eligible`) | Si el usuario PUEDE usar el par máquina-formulario: permiso del perfil, sector concedido y operativo, máquina y formulario activos, versión publicada vigente vinculada a la máquina y concesión activa. | Motor `app/authz/engine.py` vía `app/authz/availability.py`. **No depende del modo.** |
| **Modo de la compuerta** (`off` / `observe` / `enforce`) | Si el backend RECHAZA una captura sin autorización. | `settings.authz_*_mode`, solo en `capture_gate`. |

- `eligible` es un booleano: nunca expone el motivo interno de una denegación.
- Con `off` u `observe`, `eligible` sigue siendo exacto (no se usa `enabled=true` como señal de concesión). La interfaz oculta lo no elegible, pero **la captura se sigue gobernando solo por el backend y su modo**.
- Ocultar un botón **no sustituye** la autorización: un POST directo sin concesión se trata según el modo de la compuerta.
- **Habilitación operativa futura:** exige poner las compuertas en `enforce` **después** de verificar las concesiones iniciales de cada usuario (la interfaz ya refleja esas concesiones; sin `enforce` el servidor no rechaza lo que la interfaz oculta).
- Falla cerrado: si la respuesta no trae `eligible` (versión antigua o incompleta), nada se considera elegible.

## 3. API (campos aditivos, sin endpoints nuevos)

| Endpoint | Cambio |
|---|---|
| `GET /api/production/machines` | `forms[].eligible` (operación `PRODUCTION_CAPTURE`) y `bobbin_forms[]` con F3 `VINTO-P1-03` (operación `BOBBIN_PRODUCTION`). |
| `GET /api/quality/bobbin-forms` | `forms[].eligible` (P1-21/24/25/28) y `bobbin_forms[]` con P1-19 y P1-20 (operación `QUALITY_BOBBIN_CAPTURE`). |
| `GET /api/quality/machine-forms` | `forms[].eligible` (P1-18/22/26/27, operación `QUALITY_MACHINE_CAPTURE`). |

Los campos nuevos solo se calculan con una sesión (`user`); sin ella la salida es idéntica a la anterior (prueba de compatibilidad). El cálculo ocurre dentro de la transacción de solo lectura y, si el motor no puede decidir, la respuesta es el 503 fijo existente (nunca un `true` por defecto).

## 4. Cobertura por operación (verificada una por una)

| Operación | Política que la gobierna | ¿Usa concesión máquina-formulario? | Disponibilidad en la interfaz |
|---|---|---|---|
| Programación (OT / asignaciones) | Permisos `work_order.*` / `assignment.*` + alcance de sector | **No** | No se filtra por elegibilidad. Frente visible a quien gestiona (`work_order.manage` / `assignment.manage`) si el sector está en su alcance. |
| Bobinas F3 `VINTO-P1-03` | `BOBBIN_PRODUCTION` | Sí | **Hueco encontrado:** antes no se listaba; ahora `bobbin_forms`. |
| Bobinas F6 `VINTO-P1-06` y fichas P1-01/02/04/05/31 | `PRODUCTION_CAPTURE` | Sí | `forms[].eligible` |
| Rebobinado (P1-10/29/30/07) | `PRODUCTION_CAPTURE` | Sí | `forms[].eligible` |
| Conversión (P1-11/12/13/16) | `PRODUCTION_CAPTURE` | Sí | `forms[].eligible` |
| Calidad por bobina P1-21/24/25/28 | `QUALITY_BOBBIN_CAPTURE` | Sí | `forms[].eligible` |
| Calidad por bobina P1-19 / P1-20 | `QUALITY_BOBBIN_CAPTURE` | Sí | **Hueco encontrado:** no se listaban y sus botones estaban siempre visibles; ahora `bobbin_forms` y botón oculto si no es elegible. |
| Calidad por máquina P1-18/22/26/27 | `QUALITY_MACHINE_CAPTURE` | Sí | `forms[].eligible` |

No se crearon concesiones ficticias ni se modificó ninguna regla industrial.

## 5. Reglas de visibilidad

- **Frente de producción** (Bobinas, Rebobinado, Conversión): el sector está en el alcance de la sesión **y** (la persona gestiona programación **o** tiene algún formulario elegible en él).
- **Calidad:** `quality.capture` **y** algún formulario elegible (por bobina o por máquina).
- **Ejecución** muestra solo lo elegible; **Programación y Seguimiento** se rigen por permiso y alcance de sector.
- Mientras los accesos no se confirman (cargando, 503, sin conexión) **no se muestra ningún frente**; la pantalla ofrece «Reintentar». Un 403 muestra «Sin accesos asignados».

## 6. Revocaciones y errores durante la sesión

- **Revalidación:** al volver a la pestaña (`visibilitychange`), al recuperar la conexión (`online`) y tras un **403 o 404** de una captura (un único punto: `submitAttemptOf`). Las ráfagas se limitan a 1 por segundo (`lib/vinto/revalidation.ts`). Solo se vuelven a pedir las listas de disponibilidad.
- **401:** se mantiene el mecanismo existente (`onUnauthorized` → Login).
- **503 / error de conexión:** estado «sin confirmar»; no se muestran accesos como confirmados.
- **Borradores:** los intentos pendientes viven en el estado de la pantalla y no se descartan al perder un acceso; las pantallas de captura se tratan antes de la pantalla de accesos y los intentos se conservan en memoria (nada se guarda en el navegador).
- **Sin filtraciones:** ningún texto menciona perfil, sector, concesión, política ni versión como motivo.

## 7. Pruebas

- Backend: `backend/tests/test_mf13_02_eligibility.py` (perfil, sector, máquina, formulario, concesión y revocación en vivo, F3, Calidad por bobina y por máquina, independencia del modo `off/observe/enforce`, sin motivos internos, 401, 503, compatibilidad sin sesión).
- Frontend: `scripts/mf13-02-access.test.mjs` (parser estricto, falla cerrado, perfiles, máquinas, formularios, revocación, 401/403/404/503/pérdida de conexión, revalidación, borradores, Administración).
- Corrección independiente de la auditoría de rutas D.3B.3: `RouteAuditCoverageTests` en `backend/tests/test_d3b3_two_role_gate.py` (commit propio).
- Regresión comparada contra `main` (`2bf006d`): ver la descripción del PR.

## 8. Fuera de alcance

Activar `enforce`, crear concesiones, cambiar formularios o versiones, y cualquier despliegue (el release único sigue pendiente de autorización explícita).
