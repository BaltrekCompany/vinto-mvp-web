# MF-13-01D.3B.1 — Endurecimiento inicial de privilegios sin consumidores

Estado: **implementado y probado en bases PostgreSQL efímeras. NO adoptado en ningún entorno persistente ni en `deploy.sh`.** Este cambio no altera `DATABASE_URL`, login, logout, autenticación, `IDENTITY_DATABASE_URL`, perfiles, concesiones, las cuatro compuertas (siguen en `off`), formularios, Calidad, bobinas, turnos, asignaciones, TVC, ETL ni Power BI. No ejecuta migraciones, no crea roles y no modifica datos.

Diseño y límites: `docs/MF-13-01D3B-endurecimiento-privilegios-concesiones.md` (fase D.3B.1 de su §7). Este documento describe la implementación de esa fase y nada más.

## 1. Qué cambia

`vinto_app` pierde `INSERT` y `UPDATE` de **tabla** sobre `vinto_master.profile`, `vinto_master.machine` y `vinto_master.sector`, y recibe únicamente `UPDATE (updated_at)` sobre ellas. Conserva `SELECT`. `vinto_reference` (responsable del catálogo) no cambia.

| Artefacto | Función |
|-----------|---------|
| `backend/roles/03b_d3b1_restrict_catalog_writes.sql` | Endurecimiento. Transaccional, idempotente, con guardas y verificación final del estado efectivo |
| `backend/roles/rollback/ROLLBACK_D3B1.sql` | Reversión (`ROLLBACK_D3B1`). Transaccional e idempotente |
| `backend/roles/07_verification_queries.sql` | Consulta de deriva (`d3b1_compliant`) |
| `backend/roles/README.md` | Orden de aprovisionamiento 03 + 03b y condiciones |
| `backend/tests/test_d3b1_privilege_hardening.py` | 35 pruebas PostgreSQL (ver §5) |

Por qué `UPDATE (updated_at)`: PostgreSQL exige `UPDATE` de al menos una columna para **cualquier** bloqueo de fila (`FOR SHARE`, `FOR KEY SHARE`, `FOR NO KEY UPDATE`, `FOR UPDATE`). El motor de autorización toma `FOR SHARE` sobre usuario, perfiles, máquina+sector y concesión dentro de las cuatro capturas. El privilegio de columna lo permite sin dejar editar ningún dato de negocio.

## 2. Matriz de permisos antes y después (`vinto_app`)

Medida con `has_table_privilege`/`has_column_privilege` sobre un rol construido con los `GRANT` reales de `backend/roles/02`, `03`, `04` y la migración 0007.

| Tabla | Antes | Después | `SELECT` | `INSERT` | `UPDATE` tabla | `UPDATE (updated_at)` | `UPDATE` de `active`, `code`, `sector_id` y demás columnas |
|-------|-------|---------|----------|----------|----------------|-----------------------|------------------------------------------------------------|
| `profile` | `SIU` | `S;u=(updated_at)` | sí | **denegado** | **denegado** | sí | **denegado** |
| `machine` | `SIU` | `S;u=(updated_at)` | sí | **denegado** | **denegado** | sí | **denegado** |
| `sector` | `SIU` | `S;u=(updated_at)` | sí | **denegado** | **denegado** | sí | **denegado** |

Una prueba compara la lista completa de privilegios (tabla y columna, ACL real) de `vinto_app`, de `vinto_reference`, del rol amplio de referencia y de un rol sin privilegios antes y después: la **única** diferencia es lo anterior. Ninguna otra tabla cambia.

## 3. Aprovisionamiento: cómo se evita reintroducir permisos

`backend/roles/03_table_grants.sql` concede `SELECT, INSERT, UPDATE` a `vinto_app` sobre las tres tablas junto con otras diez. Re-ejecutarlo después de D.3B.1 restauraría lo retirado.

Opciones consideradas:

| Opción | Veredicto |
|--------|-----------|
| Quitar las tres tablas del `GRANT` de `03` | **Descartada**: destruye la línea base amplia que usan las pruebas de exposición de MF-13-01D.3B (`CurrentExposureTests`) para demostrar el estado anterior, y cambia el aprovisionamiento de todos los entornos a la vez |
| Dejar `03` intacto y estrechar después con un script aparte (**elegida**) | `03b` se ejecuta siempre justo después de `03` (procedimiento 03 + 03b), es idempotente y converge al mismo estado cuantas veces se repita |
| Revocar en un trigger de eventos o `ALTER DEFAULT PRIVILEGES` | Descartada: añade un mecanismo de base de datos nuevo para un caso que un orden de scripts resuelve (y `05_no_default_privileges.sql` fija que no hay privilegios por defecto) |

Controles contra la restauración accidental:

1. **Orden documentado** en `backend/roles/README.md` (paso 5b) y comentario en `03_table_grants.sql`. Una prueba exige que el README liste `03b` inmediatamente después de `03`.
2. **Detección de deriva** con la última consulta de `07_verification_queries.sql`: `d3b1_compliant` por tabla. Probado: `false` antes de adoptar, `true` tras `03b`, `false` tras re-ejecutar solo `03`, `true` otra vez tras `03` + `03b`.
3. **`deploy.sh`** (`postgres-grants`) ejecuta una lista fija `02…06` que incluye `03` y **no** `03b`; este PR no lo toca. Una prueba exige que, el día que se añada `03b`, quede inmediatamente después de `03`, y que el despliegue no ejecute nunca `rollback/` ni `proposals/`.
4. **Arnés manual** `backend/tests/roles_e2e.py` (requiere Docker): provisiona `03b` justo después de `03`. **No se ejecutó en esta tarea** (no hay daemon de Docker); su cambio es una línea y una prueba de texto lo verifica.

## 4. Procedimiento de verificación (para un futuro despliegue)

Condiciones **antes** de aplicar a un entorno persistente (ninguna se cumple automáticamente):

- Definir `REFERENCE_DATABASE_URL` con el rol `vinto_reference`, o `PG_PRIVILEGE_MODE=hardened`. En modo `legacy`, `import_reference.py` cae silenciosamente a `DATABASE_URL` (`vinto_app`) cuando la URL de referencia no está definida, y con D.3B.1 la importación fallaría con `42501`.
- Confirmar con qué rol se conecta realmente la API y quién es propietario de las tablas: el modelo de roles de `backend/roles/` **todavía no está adoptado** en DEV, QA ni operativo (`backend/roles/README.md`). Si la API usa un superusuario o el propietario, `03b` aborta y no endurece nada. No asumir que los roles reales coinciden con los de estas pruebas.
- Respaldo y ventana de cambio autorizada; ejecutar como `vinto_migrator` (el que concedió los privilegios en `03`). `REVOKE` solo retira lo concedido por el rol que lo ejecuta (o por el propietario si lo ejecuta un superusuario); si otro rol concedió privilegios, la verificación final aborta.

Pasos: `03` → `03b` → `07_verification_queries.sql` (las tres filas con `d3b1_compliant = true`) → importar referencia con `vinto_reference` en una copia → comprobar login, capturas y administración.

**Reversión:** `rollback/ROLLBACK_D3B1.sql` como `vinto_migrator`; después retirar `03b` del procedimiento. Probado: la ACL real vuelve **exactamente** a la anterior (tabla y columna), es idempotente y puede alternarse con `03b` repetidamente. No hay datos que deshacer.

## 5. Pruebas (PostgreSQL aislado, roles con los `GRANT` reales)

`backend/tests/test_d3b1_privilege_hardening.py`. Cada prueba monta una copia de una base migrada con el bundle de referencia y roles temporales.

| Requisito | Prueba |
|-----------|--------|
| Matriz antes/después | `PrivilegeMatrixTests` (matriz, diferencia exacta de ACL por rol, resto de tablas intacto, reejecución) |
| Denegación de `INSERT` y de `UPDATE` de columnas funcionales | `DeniedWritesTests` (todas las columnas de las tres tablas, `DELETE`, `TRUNCATE`; `vinto_reference` sigue pudiendo) |
| `FOR SHARE` y demás bloqueos | `RowLockTests.test_row_locks_still_work_with_the_column_privilege` |
| Bloqueos del motor conservados | `RowLockTests.test_engine_locks_are_kept_and_block_writers_until_the_capture_ends` (la edición de catálogo por `vinto_reference` espera la captura y avanza al terminar) |
| Concurrencia sin interbloqueos | `ConcurrencyTests` (cuatro capturas simultáneas + escritura continua de catálogo, sin `DeadlockDetected`) |
| Cuatro capturas en `enforce` | `ApplicationFlowsTests.test_the_four_captures_run_in_enforce` |
| Login, logout, resolución y renovación de sesión | `ApplicationFlowsTests.test_login_logout_and_session_resolution_and_renewal` |
| Administración de usuarios, sectores y máquina-formulario | `ApplicationFlowsTests.test_user_administration_and_sector_and_machine_form_grants`, `test_sector_revocation_still_waits_for_business_captures` |
| Importación de referencias con `vinto_reference` | `ReferenceImportTests` (importación **real** del bundle sobre un catálogo vacío ya endurecido) |
| Reejecución, reversión y deriva | `ScriptGuardTests`, `OwnerExecutionTests` (propietario no superusuario), `RollbackTests`, `ReprovisioningDriftTests` |
| Consistencia con el prototipo aprobado y la línea base | `ProvisioningFilesTests` |

Mutantes comprobados: omitir `GRANT UPDATE (updated_at)` o revocar solo `INSERT` en `profile` hace fallar las pruebas.

**Versión de PostgreSQL:** las pruebas se ejecutaron en **PostgreSQL 16.15** (paquete del sistema). No se obtuvo una instancia 17 (no hay daemon de Docker; el binario 17 descargable no se ejecutó). Nada del script depende de funciones de 17 (`GRANT`/`REVOKE`, `has_*_privilege`, `aclexplode`, bloques `DO`); aun así, **la evidencia en PostgreSQL 17 sigue pendiente**: ejecutar `python -B -m unittest tests.test_d3b1_privilege_hardening tests.test_grants_hardening_design` contra un clúster 17 (CI o `tests/roles_e2e.py`).

## 6. Riesgos residuales

1. **D.3B.1 no impide escalar privilegios**: `vinto_app` conserva `INSERT`/`UPDATE`/`DELETE` sobre `user_profile`, `credential`, `session`, `user_sector`, `user_machine_form_grant`, `auth_event`. Los ataques E1–E7 y E9 de MF-13-01D.3B siguen siendo posibles; solo E-profile y E-machine (actualizar `profile.active`, `machine`) quedan denegados. Depende de D.3B.2–D.3B.4.
2. **`updated_at` sigue escribible**: `UPDATE ... SET updated_at = ...` sobre las tres tablas es posible; el trigger `z_touch` fija la columna y `audit_changes` registra un evento. No cambia datos de negocio, pero puede generar ruido de auditoría.
3. **Bloqueos de fila ajenos**: con `UPDATE (updated_at)` el rol puede tomar también `FOR UPDATE` sobre esas filas (ya podía con la línea base). Un SQL inyectado podría bloquear catálogo; no lo modificaría.
4. **Dependencia de `REFERENCE_DATABASE_URL`** (ver §4): sin ella, la importación de referencias fallaría tras aplicarlo.
5. **Deriva por re-aprovisionamiento**: mitigada por la consulta de `07` y las pruebas, no impedida por la base de datos.
6. **Roles persistentes no verificados**: nada se comprobó contra DEV/QA/operativo; la guarda de `03b` aborta si el rol es superusuario o propietario, pero no sustituye la verificación previa del §4.
7. **Evidencia en PostgreSQL 17 pendiente** (ver §5) y arnés `roles_e2e.py` sin ejecutar.

## 7. Relación con D.3B.2 y condiciones de futuro despliegue

D.3B.1 solo retira lo que ningún consumidor usa: no requiere el rol de identidad ni cambios de código y puede aplicarse antes de D.3B.2. D.3B.2 (rol de identidad e `IDENTITY_DATABASE_URL`) y D.3B.4 (corte) siguen su orden propio y **no** forman parte de este cambio. Para aplicar D.3B.1 en un entorno: cumplir los puntos del §4, añadir `03b` a la lista de `deploy.sh` justo después de `03` en un PR de despliegue aparte, ejecutar la consulta de deriva y conservar el rollback a mano.
