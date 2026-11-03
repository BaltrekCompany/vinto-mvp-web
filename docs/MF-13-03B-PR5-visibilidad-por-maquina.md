# MF13-03.B PR5 — visibilidad de líneas por máquina y autorización de capturas (backend)

Solo seguridad y consultas backend. Sin UI (PR6–PR8), sin tocar la semántica de activación masiva (PR4), sin migraciones (0010/0011 intactas; **0012 no se implementa**, ver «Dependencias»). No se habilita ninguna compuerta ni modo `enforce` en ningún entorno real.

## 1. Definición de acceso operativo a una máquina
Se reutiliza el motor de MF13-01 (`app/authz/engine.py`); no hay un sistema paralelo de concesiones. Una máquina es **visible** para un usuario si el motor **permite** al menos una operación de captura sobre (máquina, formulario) con una concesión **activa**. El motor comprueba, a la vez: usuario activo; permiso funcional de sus perfiles activos; sector de la máquina activo, operativo y **concedido al usuario**; máquina y formulario activos; formulario admitido por la política de esa operación; versión publicada vigente del área correcta y vinculada a la máquina; concesión activa de la terna (usuario, máquina, formulario).

Reglas derivadas (todas probadas):
- **Varias concesiones de formulario** en una máquina: cualquier formulario que la política de una operación admita **abre la visibilidad** de las líneas de esa máquina. Ver ≠ capturar: la captura de un formulario concreto exige **su** concesión en el POST.
- **Producción vs Calidad**: cada operación tiene su permiso y su área. Una concesión de un formulario de Calidad **no** abre producción (un perfil de producción no tiene `quality.capture`; un formulario de producción no concede nada a un perfil de Calidad). Calidad ve las líneas de las máquinas donde tiene concesión de **sus** formularios.
- El **sector no equivale a la máquina**: leer un sector no concede ninguna máquina.
- Jefatura (`work_order.manage`) y Supervisión (`assignment.manage`) conservan su alcance por sector. Operación, Calidad y DATA_BALTREK quedan restringidos; DATA_BALTREK no tiene permisos de captura, así que **no ve ninguna línea** (falla cerrado; ver brechas).
- Implementación: `app/authz/visibility.py`. Solo se evalúan las ternas con concesión activa (poda: condición necesaria del paso 7 del motor); la decisión es siempre del motor. Un fallo del motor es 503, nunca acceso.

## 2. Cuándo se aplica (servidor; el cliente no lo controla)
| Ruta | Filtro por máquina |
|---|---|
| `GET /api/assignments/operational-lines` (nuevo), `GET /api/assignments/active-lines` | **Siempre** para no gestores (contrato nuevo, sin consumidores previos) |
| `GET /api/assignments/active`, `GET /api/assignments`, `GET /api/work-orders` y `/{id}`, `GET /api/captures` y `/{id}` | Cuando `WORK_ORDERS_MULTI_MACHINE_ENABLED` está encendida **o** `AUTHZ_ASSIGNMENT_READS_MODE=enforce`. `observe` registra qué se ocultaría y no cambia la respuesta. |

`AUTHZ_ASSIGNMENT_READS_MODE` (`off` por defecto; valores `off/observe/enforce`; un valor desconocido impide arrancar; no hay interruptor global ni parámetro HTTP). Acoplar el filtro a la compuerta multimáquina impide publicar OT multimáquina sin esta protección. **Con compuerta apagada y modo `off`, las rutas históricas siguen siendo por sector (comportamiento anterior): brecha conocida.** Antes de `enforce` en producción hay que verificar las concesiones iniciales de cada operador (de lo contrario verían una lista vacía).

## 3. Contrato de lectura para PR8
`GET /api/assignments/operational-lines` → `{lines: [{assignment_id, selectable, stale, current_shift, assignment}]}` con **todas** las líneas activas de las máquinas autorizadas (varias máquinas, varias líneas por máquina), ordenadas por máquina y antigüedad. `assignment` trae máquina, OT (id y número), línea, producto, turno y fecha. `stale` indica si la asignación quedó vencida; `selectable` es verdadero solo si no lo está. El servidor **nunca elige** una línea: el cliente selecciona una y envía su `assignment_id` en la captura. `GET /active-lines?machine_code=` (misma forma que en PR3) y `GET /active` (409 con 2+ activas) no cambian de forma. Una máquina no autorizada responde igual que una fuera de sector (`422 MACHINE_OUTSIDE_SCOPE`): no se distingue «sin acceso» de «sin asignaciones». Los filtros de `GET /api/assignments` (máquina, OT, fecha, estado, histórico) se intersectan con las máquinas autorizadas: no amplían nada.

## 4. OT multimáquina
`/api/work-orders` conserva su contrato de gestión. Con el filtro activo, un no gestor solo ve una OT si **todas** sus máquinas (cabecera y líneas) están autorizadas; si la autorización es parcial es un 404, nunca una OT recortada ni con líneas de otras máquinas. Para una vista parcial el contrato es **`operational-lines`** (OT, línea y producto de las líneas que sí puede ver, sin datos del resto de la OT). Jefatura y Supervisión trabajan con la OT completa dentro de sus permisos (sin cambios).

## 5. Autorización de capturas
Las cuatro rutas de escritura ya tienen compuerta propia de MF13-01 (variable y operación independientes): central `AUTHZ_CENTRAL_CAPTURES_MODE`, F3 `AUTHZ_BOBBIN_PRODUCTION_MODE`, Calidad por bobina `AUTHZ_QUALITY_BOBBIN_CAPTURES_MODE`, Calidad por máquina `AUTHZ_QUALITY_MACHINE_CAPTURES_MODE`. La máquina **nunca la aporta el cliente**: sale de la asignación leída de PostgreSQL (o de la propia captura en un reintento), y el contexto definitivo se confirma bajo los bloqueos de máquina y asignación. Con `enforce` se autoriza dentro de la misma transacción con `FOR SHARE` sobre usuario, perfiles, máquina/sector y concesión.

Demostrado en PR5 con una OT de tres líneas en dos máquinas bajo `enforce`: cada línea de una máquina autorizada se captura y queda vinculada a **su** `assignment_id`; un `assignment_id` de una máquina sin concesión se rechaza (403) sin escribir captura, detalle, bobina ni dispositivo; sin concesión, con concesión revocada, con concesión de otro formulario de producción o solo de Calidad: rechazo. Una revocación concurrente no puede colarse entre la autorización y el registro (la revocación espera al `COMMIT`). Las rutas de Calidad se cubren con sus pruebas de MF13-01 (`test_quality_*_authz.py`) y una prueba estática de cableado.

**Con `off`/`observe` NO protegen** (comprobado y documentado en una prueba): una captura sobre una línea de una máquina sin concesión se acepta si el modo de **esa** ruta no es `enforce`. La transición a `enforce` queda fuera de este PR y no está autorizada para producción.

## 6. Matriz (OT: L1/MP1, L2/MP1, L3/MP3, todas activas)
| Usuario | Concesión | `operational-lines` | Captura F3 (enforce) |
|---|---|---|---|
| Operación | solo MP1 (F3) | L1, L2 | L1, L2 sí; L3 no |
| Operación | solo MP3 (F3) | L3 | L3 sí; L1/L2 no |
| Operación | MP1 y MP3 | L1, L2, L3 | las tres |
| Operación | ninguna (con sector) | — | no |
| Operación | concesión revocada | — | no |
| Operación | concesión sin el sector | — | no |
| Operación | solo formulario de Calidad | — | no |
| Operación | máquina o formulario inactivo | — (esa máquina) | no |
| Calidad | formulario de Calidad en MP1 | L1, L2 | (rutas de Calidad) |
| Calidad | formulario de producción | — | no |
| DATA_BALTREK | cualquiera | — | sin permiso de captura |
| Jefatura / Supervisión | n/a | L1, L2, L3 (por sector) | n/a |

## 7. P1-16 (unicidad del correlativo): sin cambio, recomendación aparte
`capture_uniqueness` comprueba `numero_correlativo` por **máquina y OT** (`c.machine_id = ? AND v.work_order_id = ?`) bajo el bloqueo de máquina. Con varias líneas de la misma OT en MP1 (L1, L2), un correlativo usado en L1 **no puede repetirse en L2**. No se modifica sin aprobación funcional. Pregunta de negocio: ¿el correlativo es la secuencia física de fardos de una máquina dentro de una OT (se mantiene por máquina y OT) o cada línea/producto numera por separado (pasaría a máquina y línea)? Recomendación: mantener máquina y OT mientras la numeración sea física y continua; solo cambiar a máquina y línea con una regla funcional explícita, porque relajarla permite correlativos repetidos dentro de una misma OT y máquina. L3 (MP3) no se ve afectada.

## 8. Brechas que impiden afirmar seguridad completa
1. **Modos `off` por defecto**: las cuatro capturas y las lecturas históricas son por sector hasta decidir `enforce` (y, para lecturas, hasta encender la compuerta o el modo). Sin `enforce` no hay protección por máquina en esas rutas.
2. **Lecturas no cubiertas** (siguen por sector; documentadas, no se improvisó una solución): `GET /api/bobbins/{id}`, las consultas de Calidad (`/api/quality/bobbins`, capturas por bobina y por máquina, `machine-captures`), `GET /api/captures/count` y `GET /api/production/machines` (lista máquinas, formularios y artículos del sector, con `eligible` por formulario). Proponer extender `visibility.legacy_scope` a ellas en un PR dedicado.
3. **DATA_BALTREK** queda sin líneas con el filtro activo (no tiene permisos de captura). Si necesita lectura por sector, requiere una decisión explícita (perfil «lector» sin grants).
4. La visibilidad es una lectura puntual (sin bloqueo): una revocación se refleja en la siguiente consulta, no en una respuesta ya enviada. Residual del motor: retirar una concesión de **sector** concurrentemente a una captura (ya documentado en MF-13-01D.1).
5. **Dependencia 0012** (garantía de «una activa por máquina» con la compuerta apagada, PR4): sin implementar; sigue siendo decisión del propietario antes del despliegue operativo.
6. `observe` solo registra; no produce alertas.

## 9. Compatibilidad
Gestores y flujos con compuerta apagada y modo `off`: sin cambios (pruebas de PR1–PR4 sin modificaciones salvo ajustes de contrato ya documentados). Los datos y las asignaciones no se tocan; las capturas siguen vinculadas por `assignment_id` (FK compuesta intacta).
