# MF-13-01D.3B — Diseño seguro y endurecimiento de privilegios de concesiones

Estado: **auditoría, modelo de amenazas, diseño y prueba de viabilidad en PostgreSQL 17 aislado. Este PR NO cambia ningún privilegio real, no añade migraciones, no toca la VPS ni datos.** El motivo es un hallazgo que cambia el alcance (§1): el diseño debe aprobarse antes de ejecutar cambios extensos en servicios y despliegue.

Artefactos: `backend/roles/proposals/D3B_split_identity_role.sql` (prototipo por fases, **no** lo ejecuta ningún despliegue) y `backend/tests/test_grants_hardening_design.py` (matrices, exposición actual, viabilidad, plantilla `SECURITY DEFINER`, inventario de escrituras, transiciones entre fases y guardas del orden del plan).

**Alcance de la protección propuesta.** Cubre **SQL arbitrario ejecutado con las credenciales del rol de negocio** (p. ej. una inyección en un endpoint de capturas, órdenes o lecturas): ese rol dejaría de poder concederse permisos, perfiles, sesiones o contraseñas. **No cubre** un compromiso del proceso completo de la aplicación (ejecución de código), que posee también la credencial del rol de identidad, ni una inyección en un endpoint de autenticación o administración (§3, A2 y A3).

## 1. Hallazgo central

Con los privilegios actuales de `vinto_app`, **un SQL directo (p. ej. una inyección en cualquier endpoint de negocio) puede escalar a administrador sin tocar la tabla de concesiones**. Evidencia reproducida con un rol construido desde `backend/roles/*.sql` + la 0007 (todas las pruebas declaran además `vinto.actor_id` = administrador, lo que el rol puede hacer libremente):

| # | Ataque con el rol actual | Resultado |
|---|---------------------------|-----------|
| E1 | `INSERT` de una concesión máquina-formulario para sí mismo (incluso atribuida al administrador) | **permitido** |
| E2 | `INSERT` de una concesión de sector para sí mismo | **permitido** |
| E3 | `INSERT` en `user_profile` del perfil `DATA_BALTREK` (administrador) para sí mismo | **permitido** |
| E4 | `UPDATE` del hash de contraseña del administrador (`vinto_auth.credential`) | **permitido** |
| E5 | `INSERT` de una **sesión válida** del administrador con un token elegido por el atacante (`vinto_auth.session`) | **permitido** |
| E6 | `UPDATE` de `user.active`; E7 `UPDATE` de `profile.active` | **permitido** |
| E8 | `DELETE`/`TRUNCATE` de concesiones máquina-formulario | denegado (42501): sin privilegio |
| E9 | `DELETE` de `user_sector` (revocación fuera de la aplicación) | **permitido** |
| E10 | `UPDATE`/`DELETE` de la auditoría | denegado (42501) |
| E11 | `INSERT` de eventos de auditoría falsos | **permitido** (los triggers son `SECURITY INVOKER`) |

**Consecuencia:** endurecer solo `user_machine_form_grant` y `user_sector` (el alcance literal de D.3B) **no protege frente a ese atacante**: E3, E4 y E5 le dan el control de administrador por otra vía. Cualquier mejora real exige cerrar también la **identidad** (perfiles, credenciales, sesiones, usuarios, perfiles).

## 2. Matriz de privilegios efectivos (rol actual) y consumidores

Calculada con `has_table_privilege` sobre el rol de prueba (S=SELECT, I=INSERT, U=UPDATE, D=DELETE):

| Tabla | Hoy | DML de la aplicación (consumidor) | Observación |
|-------|-----|-----------------------------------|-------------|
| `vinto_master.user` | SIU | `INSERT`/`UPDATE` en `auth/service.py` (crear, desactivar, reactivar) | El motor la bloquea `FOR SHARE`; `revoke_sector` `FOR NO KEY UPDATE` |
| `vinto_master.user_profile` | SIU | `INSERT` en `auth/service.py` (crear usuario) | `UPDATE` sin uso; **E3** |
| `vinto_master.profile` | SIU | **ninguno** | Sobreprivilegio; el motor la bloquea `FOR SHARE` (basta `UPDATE` de una columna) |
| `vinto_master.user_sector` | SID | `INSERT`/`DELETE` en `auth/grants.py` | Sin `UPDATE`: el motor **no** puede bloquearla (D.3A sincroniza por la fila del usuario) |
| `vinto_master.user_machine_form_grant` | SIU | `INSERT`/`UPDATE` en `auth/machine_form_grants.py` | Sin `DELETE`; triggers de guarda y auditoría; el motor la bloquea `FOR SHARE` |
| `vinto_master.machine`, `sector` | SIU | **ninguno** (los escribe solo `vinto_reference`) | Sobreprivilegio; el motor las bloquea `FOR SHARE` |
| `vinto_auth.credential` | SIU | `INSERT`/`UPDATE` en `auth/service.py` (crear usuario, contadores de intentos) | **E4**; además `SELECT` expone el hash |
| `vinto_auth.session` | SIU | `INSERT` (login), `UPDATE` (renovar actividad, revocar) en `auth/sessions.py`/`service.py` | **E5** |
| `vinto_auth.auth_event` | I | `INSERT` en `auth/service.py`/`sessions.py` | Solo añadir |
| `vinto_audit.audit_event` | I | indirecto (triggers `SECURITY INVOKER`) | **E11** |

Un test fija este inventario de escrituras (`WriteInventoryTests`): cualquier SQL nuevo que escriba identidad o autorización obliga a decidir a qué rol pertenece. Sobreprivilegios adicionales fuera de identidad (p. ej. `UPDATE` en `bobbin`, `capture_detail`, `capture_group_row`, `device`, `work_order_line`; `bobbin_relation` sin uso) son candidatos a una revocación posterior; **no se tocan aquí** (alguno puede tener uso futuro, como las decisiones de `quality_release`).

## 3. Modelo de amenazas

| Actor | Capacidad | ¿Cubierto por el diseño recomendado? |
|-------|-----------|--------------------------------------|
| **A1** SQL inyectado en un endpoint de **negocio** (capturas, órdenes, lecturas) | SQL arbitrario con las credenciales del rol de negocio | **Sí**: pierde todo DML de identidad/autorización (E1–E7, E9 pasan a 42501) y deja de leer hashes |
| **A2** SQL inyectado en un endpoint de **autenticación/administración** | SQL arbitrario con el rol de identidad | **No**: ese rol es la autoridad de identidad por definición (E3/E5 siguen siendo posibles) |
| **A3** Proceso de la aplicación comprometido (ejecución de código) | Ambas credenciales y las sesiones en memoria | **No**: ningún mecanismo de base de datos con un proceso único lo evita |
| **A4** Administrador legítimo que abusa | Acciones permitidas | Fuera de alcance; solo auditoría |
| **A5** Superusuario / `vinto_migrator` | Todo | Fuera de alcance |

## 4. Opciones evaluadas

| Opción | ¿Resuelve A1? | Veredicto |
|--------|---------------|-----------|
| **O1** Estado actual | No (E1–E7) | Rechazada |
| **O2** Funciones `SECURITY DEFINER` con parámetros (actor, usuario…) invocables por `vinto_app` | No: el mismo rol que inyecta SQL puede llamar a la función con cualquier parámetro; `vinto.actor_id` y los argumentos los fija el propio rol, no demuestran quién es el administrador | Rechazada como mecanismo de seguridad (sí sirve como envoltorio de validación/consistencia) |
| **O3** `SECURITY DEFINER` + **token de sesión** como prueba (la función calcula `sha256(token)` y lo contrasta con `vinto_auth.session`) | **Solo si nadie puede forjar sesiones**; pero E5 (insertar una sesión con un token elegido) lo anula mientras el rol de negocio pueda insertar sesiones, y el login obliga a que la aplicación pueda hacerlo (la contraseña se verifica en Python, no en la base) | Insuficiente por sí sola |
| **O4** **Separación de roles por camino de código**: rol de *negocio* (sin DML de identidad) y rol de *identidad/administración*, con **privilegios por columna** para lo mínimo que el negocio necesita | **Sí** (A1) | **Recomendada** |
| **O5** Row-Level Security por variable de sesión | No: la variable la fija el propio rol | Rechazada |
| **O6** `SET ROLE` elevado por petición | No: el rol de aplicación tendría que poder asumirlo siempre | Rechazada |

O4 es la única que cambia lo que A1 puede hacer, y puede **combinarse** con O2/O3 más adelante como defensa en profundidad dentro del rol de identidad (no protege frente a A2/A3).

## 5. Diseño recomendado (O4) y cómo resuelve cada punto del encargo

`backend/roles/proposals/D3B_split_identity_role.sql` (prototipo verificado):

El diseño se aplica **por fases** (§7): primero lo que no tiene consumidores, después la integración del rol de identidad y, solo con ambos roles verificados, el corte.

- **Rol de negocio** (hoy `vinto_app`): `REVOKE INSERT, UPDATE, DELETE` sobre `user`, `user_profile`, `profile`, `user_sector`, `user_machine_form_grant`, `credential`, `session`, `auth_event`; `REVOKE INSERT, UPDATE` sobre `machine`, `sector` (la aplicación no las escribe). Conserva el `SELECT` y recibe **privilegios por columna** mínimos: `SELECT (user_id, username, must_change)` sobre `credential` (el hash deja de ser legible), `UPDATE (last_seen_at)` sobre `session` (renovar actividad) y `UPDATE (updated_at)` sobre las filas que el motor bloquea.
- **Rol de identidad** (nuevo): `SELECT` de lectura y el DML actual sobre `user`, `user_profile`, `user_machine_form_grant`, `user_sector`, `credential`, `session`, `auth_event`, más `UPDATE` de las columnas de `profile` que usa la administración.

| Punto del encargo | Resolución | Evidencia |
|-------------------|------------|-----------|
| 1. Conceder/revocar sin DML directo del rol de aplicación | Las concesiones, sectores y usuarios se escriben **con el rol de identidad**, usado solo por los routers/servicios de autenticación y administración; el rol de negocio no tiene DML | `ProposedMatrixTests`, `IdentityRoleTests` |
| 2. Mantener el bloqueo transaccional sobre las concesiones activas | `FOR SHARE` solo exige `UPDATE` de **una columna**: `UPDATE (updated_at)` basta, y el trigger de guarda rechaza (23514) cualquier cambio de una concesión activa que no sea revocarla, así que el privilegio de columna no permite alterar nada | `test_the_column_privilege_that_enables_row_locks_cannot_alter_a_grant`, `test_the_engine_decisions_and_locks_work…` |
| 3. Conservar la sincronización de sectores de D.3A | `revoke_sector` pasa a ejecutarse con el rol de identidad; su `FOR NO KEY UPDATE` sobre `user` sigue chocando con el `FOR SHARE` del motor ejecutado por el rol de negocio. Probado en las cuatro operaciones con **ambos roles distintos** | `test_sector_revocation_by_the_identity_role_still_waits…` |
| 4. Auditoría, actor y `request_id` | Sin cambios: los triggers siguen registrando con el actor de la sesión de la conexión de identidad. **Límite**: el actor sigue siendo declarado por la aplicación (§6) | `AuditResidualRiskTests` |
| 5. Funciones no ejecutables por PUBLIC | Este diseño no necesita funciones nuevas. Si una fase posterior las adopta (O2/O3): `REVOKE ALL … FROM PUBLIC` y `GRANT EXECUTE` solo al rol que corresponda | `SecurityDefinerTemplateTests` |
| 6. `search_path`, propietario, privilegios y dependencias | Plantilla probada: `SECURITY DEFINER SET search_path = pg_catalog`, objetos siempre calificados por esquema, propietario `vinto_migrator`, sin `CREATE` para los roles de aplicación (el intento de suplantar nombres con objetos de `pg_temp` no altera la función) | `SecurityDefinerTemplateTests` |
| 7. Impedir que el rol de aplicación simule una autorización administrativa | No con parámetros ni con `vinto.actor_id` (se demuestra que fijarlos es libre). La defensa es **no darle al rol de negocio el DML ni la ejecución**: sin privilegio, declarar un actor no sirve de nada | `test_a_session_variable_or_a_parameter_cannot_make_the_database_trust…`, `test_the_business_role_can_no_longer_escalate_or_touch_grants` |

### Qué demuestra el prototipo (PostgreSQL 17, rol construido desde los scripts reales)
Con el rol de negocio propuesto: E1–E7 y E9 pasan de «permitido» a **42501**; las **cuatro capturas** (central, F3, Calidad por bobina y por máquina) siguen funcionando en `enforce`; el motor toma sus `FOR SHARE`; `resolve_session` resuelve y renueva sesiones pero no puede crearlas ni alterarlas; el hash de contraseña deja de ser legible. Con el rol de identidad: crear usuarios, conceder y revocar (idempotente) accesos de máquina-formulario y de sector, y el login completo. Seis mutantes del SQL de propuesta (no revocar, no dar `UPDATE (last_seen_at)`, no dar el privilegio de columna para los bloqueos, etc.) hacen fallar las pruebas.

## 6. Límites y riesgos residuales (sin afirmar que queden resueltos)

1. **A2 y A3 no se cubren** (§3): el rol de identidad sigue pudiendo E3/E5 por definición; con un proceso único que posee ambas credenciales, un compromiso de la aplicación lo salta todo.
2. **El actor sigue siendo declarado por la aplicación** (`vinto.actor_id`): ninguna variable de sesión demuestra criptográficamente quién es el administrador. La atribución depende de la integridad del código que usa el rol de identidad.
3. **Auditoría falsificable por añadidura**: ambos roles pueden insertar eventos falsos en `audit_event` (no modificarlos ni borrarlos) porque los triggers son `SECURITY INVOKER`. Cerrarlo exigiría volver `SECURITY DEFINER` la función de auditoría (otra fase, con su propia prueba).
4. **Secretos en el mismo host**: dos credenciales de base de datos implican gestionar dos secretos en la misma máquina; separar procesos (un servicio de identidad independiente) sería una mejora arquitectónica mayor.
5. **Deriva de privilegios futuros**: cada tabla nueva debe declarar su rol; el inventario de escrituras (`WriteInventoryTests`) y la matriz fijada hacen visible el cambio, no lo impiden.
6. **Sobreprivilegios fuera de identidad** (§2) siguen sin tocar.

## 7. Plan por fases (PR pequeños; nada se ejecuta sin aprobar este diseño)

> **Corrección de orden.** La primera versión de este plan revocaba en D.3B.1 el `SELECT` sobre `vinto_auth.credential` y otros privilegios **antes** de que login y administración usaran el rol de identidad. Eso habría interrumpido la autenticación y la administración con el código actual (hechos verificados abajo). El plan se reescribe con una regla de orden y una prueba que la hace cumplir.

**Regla de orden (inviolable):** un privilegio solo se revoca al rol de negocio cuando (a) todo consumidor que lo usa ya emplea el rol de identidad, y (b) las verificaciones con **ambos roles** han aprobado. Los privilegios sin consumidores son la única excepción y pueden retirarse antes, sin cambios de código.

### 7.1 Hechos del código actual que fijan el orden

| Punto de entrada | Qué hace hoy | Por qué impide revocar antes |
|------------------|--------------|------------------------------|
| `app/auth/router.py::login` | usa `get_connection` y llama a `login_with_session` → `authenticate` | necesita el rol que luego pierde el DML |
| `app/auth/service.py::_lock_credential` | lee `password_hash` y toma `SELECT … FOR UPDATE OF c` sobre `vinto_auth.credential`; después actualiza contadores de intentos | revocar `SELECT` (hash) o `UPDATE` rompe todos los logins |
| `app/auth/router.py::logout` | abre `open_connection()` directamente (no es una dependencia) y llama a `revoke_session` (`UPDATE` de sesión + `INSERT` de `auth_event`) | un cambio solo en `get_connection` **no** lo migra |
| `app/auth/dependencies.py::current_user` | `get_connection` → `resolve_session` (lee `user_id, username, must_change` de la credencial y actualiza `last_seen_at`) | es un camino de **negocio**: debe seguir con el rol de negocio y por eso conserva privilegios por columna |
| `app/admin/router.py` | todas las rutas usan `get_connection`; escriben usuarios, sectores y concesiones vía `app/admin/service.py`, `app/admin/grants_write.py`, `app/auth/grants.py`, `app/auth/machine_form_grants.py` | sin migrar, la administración pierde el DML |
| `manage_user.py`, `create_user.py` | CLI con su propia `open_connection(target)` y `DATABASE_URL` | quedarían fuera del rol de identidad |

### 7.2 Fases

| Fase | Contenido | Código | Riesgo |
|------|-----------|--------|--------|
| **D.3B.1** | **Solo privilegios sin consumidores:** `REVOKE INSERT, UPDATE` sobre `profile`, `machine`, `sector` y `GRANT UPDATE (updated_at)` sobre las mismas tablas (los bloqueos `FOR SHARE` del motor solo exigen una columna). Verificado: ningún módulo escribe esas tablas (`WriteInventoryTests`) | Ninguno | Bajo; reversible con `ROLLBACK_D3B1` |
| **D.3B.2** | **Integración del rol de identidad, sin ninguna revocación.** Crear el rol (solo `GRANT`, aditivo), `IDENTITY_DATABASE_URL` opcional, `open_identity_connection()`/`get_identity_connection` y migración de **todos** los consumidores del inventario 7.4 | Sí | Medio |
| **D.3B.3** | **Puerta de verificación con ambos roles** (7.5). No cambia nada: produce la evidencia que autoriza el corte | Ninguno | Bajo |
| **D.3B.4** | **Corte:** retirar al rol de negocio el DML y el hash de `credential` (sección `D3B4` del prototipo, con guardas) y probar la reversión | Ninguno | Medio-alto: ventana de despliegue |
| **D.3B.5** (opcional) | Auditoría `SECURITY DEFINER` y funciones de validación (O2/O3) dentro del rol de identidad | Sí | Medio |

**Qué se movió respecto a la primera versión:** `SELECT` sobre `credential` (el hash), `UPDATE` por columna sobre `user`, `user_profile` y `user_machine_form_grant`, y toda revocación sobre `user_sector`, `session`, `auth_event` pasan de D.3B.1 a D.3B.4.

**Estado de D.3B.2:** implementada en MF-13-01D.3B.2 (`docs/MF-13-01D3B2-integracion-rol-identidad.md`): `IDENTITY_DATABASE_URL` opcional, login/logout/administración/CLI con la conexión de identidad, revalidación del actor dentro de la transacción y scripts `00c`/`03c`/`ROLLBACK_D3B2`. No revoca nada a `vinto_app` y no está aplicada en ningún entorno persistente. D.3B.3 y D.3B.4 se completan en el release único (`docs/MF-13-PLAN-release-unico.md`).

**Estado de D.3B.1:** implementada en MF-13-01D.3B.1 (`backend/roles/03b_d3b1_restrict_catalog_writes.sql`, `backend/roles/rollback/ROLLBACK_D3B1.sql`; detalle, matriz y evidencia en `docs/MF-13-01D3B1-endurecimiento-inicial-privilegios.md`). No está adoptada en ningún entorno persistente. Las demás fases siguen sin implementar.

### 7.3 Matriz de revocaciones (fuente de la prueba de orden)

Cada revocación declara cuándo se ejecuta, quién la usa hoy y en qué fase se migra el último consumidor. `PhaseOrderGuardTests` exige que la fase de migración sea **estrictamente anterior** a la de revocación, que una revocación sin consumidores sea la de D.3B.1 y que la tabla coincida con las secciones del prototipo SQL y con el inventario real de escrituras.

| Revocación | Revocada en | Consumidores actuales | Migrados en |
|------------|-------------|-----------------------|-------------|
| `vinto_master.profile` INSERT, UPDATE | D.3B.1 | ninguno | — |
| `vinto_master.machine` INSERT, UPDATE | D.3B.1 | ninguno | — |
| `vinto_master.sector` INSERT, UPDATE | D.3B.1 | ninguno | — |
| `vinto_master.user` INSERT, UPDATE | D.3B.4 | `app/auth/service.py` | D.3B.2 |
| `vinto_master.user_profile` INSERT, UPDATE | D.3B.4 | `app/auth/service.py` | D.3B.2 |
| `vinto_master.user_sector` INSERT, DELETE | D.3B.4 | `app/auth/grants.py` | D.3B.2 |
| `vinto_master.user_machine_form_grant` INSERT, UPDATE | D.3B.4 | `app/auth/machine_form_grants.py` | D.3B.2 |
| `vinto_auth.credential` INSERT, UPDATE | D.3B.4 | `app/auth/service.py` | D.3B.2 |
| `vinto_auth.credential` SELECT (hash; queda `SELECT` por columna) | D.3B.4 | `app/auth/service.py` | D.3B.2 |
| `vinto_auth.session` INSERT, UPDATE (queda `UPDATE (last_seen_at)`) | D.3B.4 | `app/auth/sessions.py`, `app/auth/service.py` | D.3B.2 |
| `vinto_auth.auth_event` INSERT | D.3B.4 | `app/auth/service.py`, `app/auth/sessions.py` | D.3B.2 |

### 7.4 Inventario de D.3B.2 (todo consumidor migra o se declara de negocio)

`PhaseOrderGuardTests` compara este inventario con los archivos que llaman hoy a las funciones que escriben identidad: un llamador nuevo sin declarar hace fallar la prueba.

| Consumidor | Hoy | En D.3B.2 | Rol |
|------------|-----|-----------|-----|
| `app/auth/router.py::login` | `Depends(get_connection)` | `Depends(get_identity_connection)` | identidad |
| `app/auth/router.py::logout` | `open_connection()` directo dentro del handler | `open_identity_connection()` en el mismo lugar, para seguir borrando la cookie aunque la conexión falle | identidad |
| `app/auth/dependencies.py::current_user` (resolución de sesiones) | `Depends(get_connection)` → `resolve_session` | **sin cambio**: `resolve_session` solo lee columnas de la credencial y actualiza `last_seen_at` | negocio |
| `app/admin/router.py` (todas las rutas, lecturas incluidas) | `Depends(get_connection)` | `Depends(get_identity_connection)`; la autorización `require_permission(USER_MANAGE)` sigue resolviendo la sesión con el rol de negocio | identidad |
| `app/admin/service.py`, `app/admin/grants_write.py` | reciben la conexión del router | heredan la conexión de identidad; además revalidan al actor (`app/admin/actor.py`) dentro de la transacción de la escritura | identidad |
| `app/auth/service.py` (`create_user`, `authenticate`, `deactivate_user`, `reactivate_user`) | reciben la conexión del llamador | sin cambio de código | identidad |
| `app/auth/grants.py`, `app/auth/machine_form_grants.py` | reciben la conexión del llamador | sin cambio de código | identidad |
| `app/auth/sessions.py` (`login_with_session`, `create_session`, `revoke_session`; `resolve_session` es de negocio) | reciben la conexión del llamador | sin cambio de código | identidad / negocio |
| `manage_user.py` | `open_connection(target)` con `DATABASE_URL` | conexión de identidad (`IDENTITY_DATABASE_URL`; para `--target test`, una variable equivalente con las mismas guardas de nombre `*_test`) | identidad |
| `create_user.py` | `open_connection(target)` con `DATABASE_URL` | ídem | identidad |

Fuera de alcance (no escriben identidad ni autorización): `migrate.py` (rol migrador), `import_reference.py`/`authz_readiness.py` (rol de referencia) y el resto de routers de negocio (capturas, bobinas, calidad, órdenes, asignaciones), que siguen con `get_connection`.

### 7.5 Transición sin pérdida de acceso y puerta de verificación

**Transición.**
- `IDENTITY_DATABASE_URL` **ausente o vacía** ⇒ `open_identity_connection()` se comporta exactamente como `open_connection()` con `DATABASE_URL`: el comportamiento existente se conserva sin cambios hasta el corte. Es también el estado de reversión.
- Variable **presente y válida** ⇒ los consumidores de identidad usan ese rol; el rol de negocio sigue conservando todo su DML mientras no se ejecute D.3B.4, de modo que cualquier camino aún no migrado o cualquier fallo de la variable no interrumpe nada.
- Variable **presente pero con fallo de conexión** ⇒ error seguro (503), **sin retroceso silencioso** a `DATABASE_URL`: un retroceso ocultaría una mala configuración justo antes del corte. Contrapartida aceptada: durante la activación gradual un error de la variable es visible en lugar de enmascarado.
- Cada arranque registra, sin URL ni credenciales, si la conexión de identidad es *dedicada* o *compartida*.

**Puerta de verificación (D.3B.3): el corte queda prohibido si falta cualquiera de estas evidencias.**
1. Suite completa verde con `IDENTITY_DATABASE_URL` ausente (comportamiento actual intacto).
2. En una base **aislada** con el script `D3B4` ya aplicado al rol de negocio y la variable definida: login, logout, `/auth/me` (resolución de sesión), todas las rutas de administración (usuarios, sectores, concesiones), `manage_user.py`, `create_user.py` y las cuatro capturas con `enforce` aprueban.
3. La conexión de identidad devuelve `current_user` distinto del rol de negocio (misma identidad ⇒ no hay separación y el corte no se ejecuta).
4. El ensayo de reversión (`ROLLBACK_D3B4`, 7.6) se ejecutó en la base aislada y la matriz volvió a la actual.
5. Las pruebas de orden (`PhaseOrderGuardTests`) están en verde.
6. Aprobación humana explícita registrada en el PR de D.3B.4.

Defensa en profundidad: la sección `D3B4` del prototipo **aborta sin cambiar nada** si el rol de identidad no tiene ya todo lo que el rol de negocio va a perder, o si ambos roles son el mismo. Esa guarda protege el privilegio; la puerta anterior protege el comportamiento de la aplicación y no puede automatizarse solo con SQL.

### 7.6 Despliegue y reversión (para las fases futuras; nada de esto se ejecuta ahora)

**Despliegue de D.3B.4**
1. Respaldo.
2. `00_create_roles.sql` crea el rol de identidad (idempotente) y se aplica `D3B2`.
3. Se despliega el código de D.3B.2 con `IDENTITY_DATABASE_URL` aún sin definir; se confirma que nada cambió.
4. Se define la variable y se reinicia; se completa la puerta D.3B.3.
5. Solo entonces se aplica `D3B4` (en una sola transacción; las guardas abortan si no procede).
6. `07_verification_queries.sql` ampliado y la matriz fijada confirman el estado.

**Reversión (el orden evita el estado en que ningún rol puede administrar usuarios)**
1. **Privilegios primero:** ejecutar `ROLLBACK_D3B4`. Solo concede al rol de negocio lo que tenía y no toca al de identidad; desde ese momento **ambos** roles administran.
2. Verificar login y administración con el rol de negocio.
3. **Después** quitar `IDENTITY_DATABASE_URL` y reiniciar: vuelve el rol único.
4. No retirar privilegios al rol de identidad ni eliminarlo durante la reversión: se deja inerte y se limpia en una tarea posterior.
5. `ROLLBACK_D3B1` restaura `INSERT, UPDATE` sobre `profile`, `machine` y `sector` si fuera necesario.

**Prohibido:** quitar `IDENTITY_DATABASE_URL` mientras los privilegios del corte sigan aplicados (login y administración fallarían con `42501`), o revocar al rol de identidad antes de restaurar al de negocio.

**Pruebas del prototipo** (`PhaseTransitionTests`): en cada estado intermedio (tras D3B1, D3B2, D3B4, `ROLLBACK_D3B4` y `ROLLBACK_D3B1`) al menos un rol ejecuta el flujo completo de autenticación y administración; tras `ROLLBACK_D3B4` ambos lo ejecutan, y el rol de negocio por sí solo (conexión única, sin variable) lo ejecuta; la matriz del rol de negocio tras la reversión completa es idéntica a la actual; el corte aborta si el rol de identidad no tiene aún sus privilegios y si los dos roles coinciden.

**No se aplica nada en la VPS en esta tarea.**

## 8. Documentación de D.3A actualizada

Se corrigieron las recomendaciones obsoletas de `FOR UPDATE` donde ya se adoptó `FOR NO KEY UPDATE`: `docs/MF-13-01D1-motor-autorizacion-efectiva.md` §4, `docs/MF-13-01D2A-integracion-capturas-centrales.md` §9, el comentario de `app/authz/engine.py` (solo texto) y la tabla de `docs/MF-13-01D3A-sincronizacion-revocacion-sectores.md`, que ahora marca `FOR UPDATE` como alternativa **descartada**.
