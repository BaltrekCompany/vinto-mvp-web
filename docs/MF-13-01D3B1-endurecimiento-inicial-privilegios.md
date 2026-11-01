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
| `backend/tests/test_d3b1_privilege_hardening.py` | 42 pruebas PostgreSQL y de archivos (ver §5) |
| `deploy/mvp/scripts/deploy.sh` (`postgres-grants`) | Guarda de solo lectura que falla cerrado si D.3B.1 está aplicado (ver §3) |
| `deploy/mvp/scripts/tests/test_postgres_grants_d3b1_guard.sh` | 11 pruebas de la guarda, sin Docker ni PostgreSQL reales |
| `.github/workflows/d3b1-postgres17.yml` | Validación en PostgreSQL 17 para GitHub Actions (sin ejecutar todavía; ver §5) |

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
3. **Guarda en `deploy.sh`** (`postgres-grants`). La fase ejecuta una lista fija `02…06` que incluye `03` y **no** `03b`. Antes de cualquier `GRANT` cuenta, con una consulta de solo lectura como `vinto_migrator`, cuántas de las 3 tablas ya no tienen `INSERT` o `UPDATE` de tabla para `vinto_app`:

   | Resultado | Comportamiento |
   |-----------|----------------|
   | `0` (D.3B.1 no aplicado) | Despliegue idéntico al anterior: mismos cinco scripts, mismo orden, mismo mensaje final |
   | `1`–`3` (aplicado o parcial) | **Falla cerrado** (`exit 1`) sin ejecutar ningún archivo SQL; el mensaje indica el procedimiento correcto y no contiene secretos |
   | consulta fallida o respuesta inesperada | **Falla cerrado**: nunca se asume «no aplicado» |

   La guarda no aplica `03b` ni la reversión (D.3B.1 se aplica a mano, por decisión separada), no cambia la identidad del servidor, el clúster destino ni las protecciones de TVC, y se ejecuta después de `assert_schema_migrated`. Pruebas: `deploy/mvp/scripts/tests/test_postgres_grants_d3b1_guard.sh` (simulaciones; demuestra que no se ejecuta ningún SQL antes del fallo y que sin la guarda 8 de las 11 pruebas fallan) y, contra PostgreSQL real, `ReprovisioningDriftTests.test_the_deploy_guard_query_counts_hardened_tables_in_each_state` (ejecuta la consulta exacta de `deploy.sh`: 0 / 3 / 2 / 1 según el estado).

   **Reaprovisionar un entorno endurecido:** `postgres-grants` se detiene. Si solo hace falta `02` o `04…06`, ejecutarlos a mano sin `03`. Si hace falta `03`, ejecutar a mano `03` y justo después `03b` como `vinto_migrator` (ventana breve con los privilegios amplios entre ambos; hacerlo en mantenimiento) y comprobar `07` (`d3b1_compliant = true`). **Revertir:** `ROLLBACK_D3B1.sql` como `vinto_migrator`; después `postgres-grants` vuelve a funcionar sin cambios.
4. **Arnés manual** `backend/tests/roles_e2e.py` (requiere Docker): provisiona `03b` justo después de `03`. **No se ejecutó en esta tarea** (no hay daemon de Docker); su cambio es una línea y una prueba de texto lo verifica.

## 4. Procedimiento de verificación (para un futuro despliegue)

Condiciones **antes** de aplicar a un entorno persistente (ninguna se cumple automáticamente):

- Definir `REFERENCE_DATABASE_URL` (`REFERENCE_TEST_DATABASE_URL` en `--target test`) con el rol `vinto_reference`, o `PG_PRIVILEGE_MODE=hardened`. En modo `legacy`, `import_reference.py` (sin cambios en este PR) cae silenciosamente a `DATABASE_URL`/`TEST_DATABASE_URL` (`vinto_app`) cuando la URL de referencia no está definida, y con D.3B.1 la importación fallaría con `42501`. **Un entorno donde la URL falte y haya fallback a `vinto_app` no está listo para D.3B.1.** Comprobación sin imprimir secretos: ver `backend/roles/README.md`.
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
| Importación de referencias con `vinto_reference` | `ReferenceImportTests` (importación **real** del bundle sobre un catálogo vacío ya endurecido; la misma importación con la cuenta `vinto_app` endurecida falla con `42501` y no deja nada parcial) y `ReferenceConnectionReadinessTests` (el fallback `legacy` a la cuenta de la aplicación, `hardened` que se niega sin filtrar URLs, y que `import_reference.py` sigue resolviendo su conexión con el mismo ayudante) |
| Reejecución, reversión y deriva | `ScriptGuardTests`, `OwnerExecutionTests` (propietario no superusuario), `RollbackTests`, `ReprovisioningDriftTests` (incluye la consulta de la guarda de `deploy.sh`) |
| Flujo de PostgreSQL 17 | `Postgres17WorkflowTests` (estructura: servicio `postgres:17`, falla si la versión no es 17, sin secretos, solo lectura) |
| Consistencia con el prototipo aprobado y la línea base | `ProvisioningFilesTests` |

Mutantes comprobados: omitir `GRANT UPDATE (updated_at)` o revocar solo `INSERT` en `profile` hace fallar las pruebas.

**Versión de PostgreSQL:** todas las pruebas de este documento se ejecutaron en **PostgreSQL 16.15** (paquete del sistema). **No hay compatibilidad con PostgreSQL 17 verificada.** No hay daemon de Docker y el binario 17 descargable no se ejecutó (el entorno bloqueó su ejecución y no se intentó evadir). Nada del script depende de funciones de 17 (`GRANT`/`REVOKE`, `has_*_privilege`, `aclexplode`, bloques `DO`), pero eso es una expectativa, no evidencia. Queda preparado `.github/workflows/d3b1-postgres17.yml`: ejecuta `test_d3b1_privilege_hardening`, `test_grants_hardening_design` y la guarda de `deploy.sh` contra un servicio `postgres:17`, **falla si el servidor no es 17.x**, sin secretos (cuenta desechable del contenedor), sin VPS y con permisos de solo lectura. Sigue sin ejecutarse: requiere que la organización permita GitHub Actions (el repositorio no tenía ningún workflow). Hasta que ese flujo, o una instancia 17 aislada, pase, la evidencia en PostgreSQL 17 sigue pendiente.

## 6. Riesgos residuales

1. **D.3B.1 no impide escalar privilegios**: `vinto_app` conserva `INSERT`/`UPDATE`/`DELETE` sobre `user_profile`, `credential`, `session`, `user_sector`, `user_machine_form_grant`, `auth_event`. Los ataques E1–E7 y E9 de MF-13-01D.3B siguen siendo posibles; solo E-profile y E-machine (actualizar `profile.active`, `machine`) quedan denegados. Depende de D.3B.2–D.3B.4.
2. **`updated_at` sigue escribible**: `UPDATE ... SET updated_at = ...` sobre las tres tablas es posible; el trigger `z_touch` fija la columna y `audit_changes` registra un evento. No cambia datos de negocio, pero puede generar ruido de auditoría.
3. **Bloqueos de fila ajenos**: con `UPDATE (updated_at)` el rol puede tomar también `FOR UPDATE` sobre esas filas (ya podía con la línea base). Un SQL inyectado podría bloquear catálogo; no lo modificaría.
4. **Dependencia de `REFERENCE_DATABASE_URL`** (ver §4): sin ella, la importación de referencias fallaría tras aplicarlo.
5. **Deriva por re-aprovisionamiento**: mitigada por la consulta de `07` y las pruebas, no impedida por la base de datos.
6. **Roles persistentes no verificados**: nada se comprobó contra DEV/QA/operativo; la guarda de `03b` aborta si el rol es superusuario o propietario, pero no sustituye la verificación previa del §4.
7. **Evidencia en PostgreSQL 17 pendiente** (ver §5). El arnés manual `roles_e2e.py` no se ejecutó (requiere Docker); su único cambio es incluir `03b` justo después de `03` en la lista de scripts, verificado solo por una prueba de texto.
8. **Ventana entre `03` y `03b`** al reaprovisionar a mano un entorno endurecido: los privilegios amplios existen unos instantes. Adoptar D.3B.1 en el despliegue exigirá decidir cómo ejecutarlos de forma atómica (PR aparte).
9. **La guarda de `deploy.sh` protege solo esa fase**: ejecutar `03` a mano sin `03b` sigue siendo posible; lo detecta la consulta de deriva de `07`, no lo impide.

## 7. Relación con D.3B.2 y condiciones de futuro despliegue

D.3B.1 solo retira lo que ningún consumidor usa: no requiere el rol de identidad ni cambios de código y puede aplicarse antes de D.3B.2. D.3B.2 (rol de identidad e `IDENTITY_DATABASE_URL`) y D.3B.4 (corte) siguen su orden propio y **no** forman parte de este cambio. Para aplicar D.3B.1 en un entorno: cumplir los puntos del §4, añadir `03b` a la lista de `deploy.sh` justo después de `03` en un PR de despliegue aparte, ejecutar la consulta de deriva y conservar el rollback a mano.
