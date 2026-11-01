# MF-13-01D.3B — Diseño seguro y endurecimiento de privilegios de concesiones

Estado: **auditoría, modelo de amenazas, diseño y prueba de viabilidad en PostgreSQL 17 aislado. Este PR NO cambia ningún privilegio real, no añade migraciones, no toca la VPS ni datos.** El motivo es un hallazgo que cambia el alcance (§1): el diseño debe aprobarse antes de ejecutar cambios extensos en servicios y despliegue.

Artefactos: `backend/roles/proposals/D3B_split_identity_role.sql` (prototipo, **no** lo ejecuta ningún despliegue) y `backend/tests/test_grants_hardening_design.py` (matrices, exposición actual, viabilidad, plantilla `SECURITY DEFINER`, inventario de escrituras).

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

| Fase | Contenido | Riesgo de despliegue |
|------|-----------|----------------------|
| **D.3B.1** | Solo privilegios sin uso: `REVOKE INSERT, UPDATE` sobre `profile`, `machine`, `sector`; `SELECT` por columna sobre `credential`; `UPDATE` por columna donde el motor solo bloquea. Sin cambios de código; script de roles versionado y reversible | Bajo; verificable con el inventario |
| **D.3B.2** | Rol de identidad: `IDENTITY_DATABASE_URL` opcional (ausente ⇒ comportamiento actual, activación gradual); `get_connection` con dos variantes; los routers de autenticación y administración usan la de identidad; CLI (`manage_user.py`, `create_user.py`) con el rol de identidad | Medio: toca la fábrica de conexiones y routers |
| **D.3B.3** | Corte: quitar al rol de negocio el DML de identidad (`proposals/…` aplicado como script de roles), con verificación (`07_verification_queries.sql` ampliado) | Medio-alto: requiere ventana y pruebas con ambos roles reales |
| **D.3B.4** (opcional) | Auditoría `SECURITY DEFINER` y funciones de validación (O2/O3) como defensa en profundidad dentro del rol de identidad | Medio |

### Procedimiento de despliegue y reversión (para las fases futuras; nada de esto se ejecuta ahora)
- **Despliegue**: (1) respaldo; (2) `00_create_roles.sql` crea el rol de identidad (idempotente); (3) desplegar el código con `IDENTITY_DATABASE_URL` aún sin definir (el comportamiento no cambia); (4) definir la variable y reiniciar; verificar login, administración y las cuatro capturas en `off`/`observe`; (5) solo entonces aplicar el script de revocación al rol de negocio; (6) `07_verification_queries.sql` y la matriz fijada confirman el estado.
- **Reversión**: los privilegios se restauran con el `GRANT` de `03_table_grants.sql` + 0007 (idempotente); la variable `IDENTITY_DATABASE_URL` se elimina y se reinicia para volver al rol único. No hay datos que deshacer.
- **No se aplica nada en la VPS en esta tarea.**

## 8. Documentación de D.3A actualizada

Se corrigieron las recomendaciones obsoletas de `FOR UPDATE` donde ya se adoptó `FOR NO KEY UPDATE`: `docs/MF-13-01D1-motor-autorizacion-efectiva.md` §4, `docs/MF-13-01D2A-integracion-capturas-centrales.md` §9, el comentario de `app/authz/engine.py` (solo texto) y la tabla de `docs/MF-13-01D3A-sincronizacion-revocacion-sectores.md`, que ahora marca `FOR UPDATE` como alternativa **descartada**.
