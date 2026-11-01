# Modelo de privilegios mínimos de PostgreSQL (CLOUD-01B-2)

Diseñado en CLOUD-01B-2/CLOUD-01B-2A, implementado y probado en una instancia PostgreSQL 17 **efímera**
en CLOUD-01B-2B.1 (`backend/tests/roles_e2e.py`), corregido en PG54-01/02/03/04/05/06 tras la auditoría
del PR #54. **Todavía no se adoptó en DEV, QA ni operativo.** Nada de lo que hay aquí se ejecuta
automáticamente; cada script es SQL versionado que una identidad concreta (ver tabla "Contexto de
ejecución" más abajo) ejecuta a mano, una vez por entorno.

No hay contraseñas reales en ningún archivo de esta carpeta. Ninguna contraseña se pasa como argumento
`-v` de psql (quedaría visible en la lista de procesos del host/contenedor): todas se leen con `\getenv`
desde una variable de ENTORNO del proceso que invoca `psql`, nunca de la línea de comandos (PG54-03).

## Las 4 identidades: LOGIN vs propietario

Las 4 son roles `LOGIN` (se usan para autenticar una conexión). Solo una es propietaria de objetos.

| Rol | `LOGIN` | Propietario de objetos | Puede | No puede |
|---|---|---|---|---|
| `vinto_app` | sí | no, de nada | `SELECT`/`INSERT`/`UPDATE` (y `DELETE` solo en `vinto_master.user_sector`) sobre las tablas de negocio existentes | `CREATE`/`ALTER`/`DROP`/`TRUNCATE`/`GRANT`; `CREATEDB`/`CREATEROLE`/`SUPERUSER`; nada sobre `vinto_meta`; **nada sobre una tabla que una migración futura no le haya concedido explícitamente** |
| `vinto_migrator` | sí | sí — los 6 esquemas y todo lo que contienen | DDL completo + el DML que una migración necesite para sus backfills | `CREATEDB`/`CREATEROLE`/`SUPERUSER`; crear otros roles |
| `vinto_reference` | sí | no, de nada | `SELECT`/`INSERT`/`UPDATE` sobre las tablas de catálogo/formulario/receta existentes que `import_reference.py` escribe | Nada sobre `vinto_txn`/`vinto_auth`/`vinto_meta`; ningún DDL; **nada sobre una tabla futura sin GRANT explícito** |
| `vinto_test_admin` | sí | sí — solo de las bases `*_test` que él mismo crea | `CREATEDB`, conectar a `postgres`, crear/destruir bases `*_test` | **Solo existe en DEV/QA**; nunca se crea en un entorno operativo (por eso vive en un script separado, `00b_create_test_admin_role.sql`, nunca en `00_create_roles.sql`) |

## Orden de ejecución y contexto de autorización de cada script

| Paso | Script | Quién lo ejecuta | Autorización requerida antes de ejecutarlo |
|---|---|---|---|
| 1 | `00_create_roles.sql` | Administrador del clúster (superusuario o rol con `CREATEROLE`) | Autorización para crear roles de login en el clúster destino. Idempotente (PG54-05): seguro de re-ejecutar; aborta sin tocar nada si detecta un nombre de rol que ya existe y no fue creado por este mismo script (posible colisión en un clúster compartido) |
| 1b | `00b_create_test_admin_role.sql` | Administrador del clúster | **Solo en DEV/QA.** Confirmar explícitamente, antes de ejecutar, que el clúster destino NO es operativo — no hay ninguna comprobación automática que lo impida |
| 2 | `01_database_grants.sql` | Administrador del clúster, conectado a la base objetivo | Autorización para modificar privilegios de la base de destino (dev/qa/operativa o la base efímera de prueba) |
| 3 | `python migrate.py --target dev\|test` conectando como `vinto_migrator` (`MIGRATOR_DATABASE_URL`/`MIGRATOR_TEST_DATABASE_URL`) | Quien opera el despliegue/migración | Autorización para aplicar el esquema completo; crea los 6 esquemas y todas las tablas/funciones/triggers con `vinto_migrator` como propietario |
| 4 | `02_schema_grants.sql` | `vinto_migrator` (ya es propietario) | Ninguna adicional: ya autorizado por el paso 3 |
| 5 | `03_table_grants.sql` | `vinto_migrator` | Ninguna adicional |
| 5b | `03b_d3b1_restrict_catalog_writes.sql` | `vinto_migrator` | **MF-13-01D.3B.1 — todavía NO adoptado en ningún entorno persistente ni en `deploy.sh`.** Siempre justo después de 03 (ver «D.3B.1» más abajo): retira `INSERT`/`UPDATE` de tabla sobre `profile`, `machine` y `sector` a `vinto_app` |
| 6 | `04_function_grants.sql` | `vinto_migrator` | Ninguna adicional |
| 7 | `05_no_default_privileges.sql` | `vinto_migrator` | Ninguna adicional. **No concede ningún privilegio** (corregido en PG54-01): declara explícitamente que `PUBLIC` no recibe nada sobre objetos futuros. El modelo es fail-closed — una tabla que una migración 0007+ cree permanece sin ningún privilegio para `vinto_app`/`vinto_reference` hasta que esa misma migración lo conceda explícitamente |
| 8 | `06_public_and_meta_protection.sql` | `vinto_migrator` | Ninguna adicional. Documentación explícita y verificable de que `PUBLIC` no tiene nada y `vinto_meta`/`vinto_auth` están protegidos |
| 9 | `07_verification_queries.sql` | Cualquier rol con visibilidad suficiente (superusuario o `vinto_migrator`) | Ninguna; solo lectura |

## Nombres de rol en un clúster compartido (PG54-05)

`vinto_app`/`vinto_migrator`/`vinto_reference`/`vinto_test_admin` son nombres de rol **globales al
clúster** (PostgreSQL no tiene roles por base de datos). Si el mismo clúster hospeda más de un entorno
de VINTO (por ejemplo DEV y QA juntos) o más de un proyecto, hay dos opciones:
1. **Un clúster por entorno** (recomendado; es el supuesto de CLOUD-01B-2A: DEV, QA y operativo son
   instancias PostgreSQL separadas).
2. Sufijar los 4 nombres de rol por entorno (`vinto_app_dev`, `vinto_app_qa`, ...) editando los 8
   scripts de esta carpeta de forma consistente antes de ejecutarlos contra un clúster compartido. Estos
   scripts no sufijan automáticamente.

`00_create_roles.sql`/`00b_create_test_admin_role.sql` detectan una colisión de nombre (un rol que ya
existe pero no fue creado por este script, identificado por `COMMENT ON ROLE`) y **abortan sin modificar
nada**, en vez de sobrescribir o asumir que es el mismo rol.

## D.3B.1 — primer endurecimiento de privilegios (MF-13-01D.3B.1)

**Estado: implementado y probado en bases efímeras; NO adoptado en ningún entorno persistente ni en `deploy.sh`.** Diseño y límites: `docs/MF-13-01D3B-endurecimiento-privilegios-concesiones.md`; evidencia y procedimiento: `docs/MF-13-01D3B1-endurecimiento-inicial-privilegios.md`.

| Tabla (`vinto_master`) | `vinto_app` antes (03) | `vinto_app` después (03 + 03b) | `vinto_reference` |
|---|---|---|---|
| `profile`, `machine`, `sector` | `SELECT`, `INSERT`, `UPDATE` de tabla | `SELECT` + `UPDATE (updated_at)`; sin `INSERT`; sin `UPDATE` de ninguna otra columna | sin cambio (`SELECT`, `INSERT`, `UPDATE`) |

`UPDATE (updated_at)` se conserva porque PostgreSQL exige `UPDATE` de al menos una columna para cualquier bloqueo de fila y el motor de autorización toma `FOR SHARE` sobre usuario, perfiles, máquina+sector y concesión dentro de las capturas. Ningún módulo de `backend/app` escribe estas tres tablas (solo `import_reference.py`, con `vinto_reference`).

**Orden obligatorio: `03_table_grants.sql` y después `03b_d3b1_restrict_catalog_writes.sql`, siempre juntos (03 + 03b), ambos como `vinto_migrator`.** `03` no se modificó a propósito: sigue siendo la línea base amplia que usan las pruebas de exposición de MF-13-01D.3B para comprobar el estado anterior. Consecuencia: **re-ejecutar `03` sola restaura `INSERT`/`UPDATE` de tabla (deriva)**. `deploy.sh` (`postgres-grants`) ejecuta una lista fija `02…06` con `03` y **sin** `03b` (no aplica D.3B.1 por su cuenta). Para que ese `03` no deshaga el endurecimiento, la fase ejecuta ANTES de cualquier `GRANT` una consulta de solo lectura: con D.3B.1 sin aplicar (0 de 3 tablas) el despliegue es idéntico al de siempre; si está aplicado, parcial o no se puede determinar, **falla cerrado sin ejecutar ningún archivo SQL** y muestra este procedimiento. Al adoptar D.3B.1 en el despliegue habrá que decidir, en un PR aparte, cómo ejecutar `03` + `03b` de forma atómica.

- **Detección de deriva:** la última consulta de `07_verification_queries.sql` devuelve una fila por tabla con `d3b1_compliant`. Tras adoptar D.3B.1 las tres deben ser `true`; `false` indica `03` sin `03b` o `03b` sin aplicar. Ejecutarla después de cada re-aprovisionamiento.
- **Reaprovisionar un entorno endurecido:** `postgres-grants` se detiene (ver arriba). Si solo hace falta `02` o `04…06`, ejecutarlos a mano **sin `03`**. Si hace falta `03` (por ejemplo, una tabla nueva), ejecutar a mano `03` y **justo después** `03b`, como `vinto_migrator`, y comprobar la consulta de deriva de `07` (`d3b1_compliant = true`). Entre `03` y `03b` hay una ventana breve con los privilegios amplios: hacerlo en una ventana de mantenimiento.
- **Reversión:** `rollback/ROLLBACK_D3B1.sql` (como `vinto_migrator`) restaura el estado de `03`; a partir de ahí `postgres-grants` vuelve a funcionar sin cambios. Después hay que retirar `03b` del procedimiento de aprovisionamiento; si no, el siguiente 03 + 03b vuelve a endurecer. El rollback no es un paso de aprovisionamiento y ningún despliegue lo ejecuta.
- **Guardas de `03b` (aborta sin cambiar nada, en una sola transacción):** `vinto_app` no existe, es superusuario o es propietario de las tablas (el endurecimiento no lo limitaría); falta alguna tabla o su columna `updated_at`; `vinto_app` no tiene `SELECT` (falta ejecutar `03`); o el estado efectivo final no es exactamente el esperado (por ejemplo, privilegios concedidos por otro rol que `vinto_migrator` no puede revocar). Es idempotente.
- **Dependencia crítica antes de adoptarlo (un entorno sin esto NO está listo para D.3B.1):** `import_reference.py` (sin cambios en este PR) usa `REFERENCE_DATABASE_URL` (`REFERENCE_TEST_DATABASE_URL` con `--target test`) y, en `PG_PRIVILEGE_MODE=legacy`, **cae silenciosamente a `DATABASE_URL`/`TEST_DATABASE_URL` (`vinto_app`)** si no está definida; con D.3B.1 la importación fallaría con `42501` (probado con la importación real). Antes de aplicar `03b`: definir la URL dedicada con el rol `vinto_reference` (o usar `PG_PRIVILEGE_MODE=hardened`, que se niega a caer) y comprobarlo sin imprimir secretos: `cd backend && .venv/bin/python -c "from app.config import settings as s; print('REFERENCE_DATABASE_URL definida:', bool(s.reference_database_url and s.reference_database_url.get_secret_value()))"` debe mostrar `True`, y `import_reference.py --target dev` (dry-run) debe ejecutarse correctamente. No pegar URLs ni contraseñas en tickets, logs ni documentación.
- **No asumir que los roles persistentes coinciden con estas pruebas:** este modelo de privilegios todavía no está adoptado en DEV/QA/operativo (ver arriba). Antes de aplicar nada, ejecutar `07_verification_queries.sql` y comprobar quién es propietario de las tablas y con qué rol se conecta la API realmente; si la API usa un propietario o superusuario, `03b` se detiene y no endurece nada.
- **Qué NO resuelve:** D.3B.1 no impide escalar privilegios mediante `user_profile`, `credential`, `session`, `user_sector`, `user_machine_form_grant` ni `auth_event`. Esa protección depende de completar D.3B.2 a D.3B.4 (rol de identidad, verificación con ambos roles y corte).

## Qué NO hace este modelo todavía

- No se adopta en ninguna base persistente (DEV compartido, QA, operativo). CLOUD-01B-2B.2 decidirá esa estrategia, reutilizando el "despliegue paralelo" de CLOUD-01B-2A (§5): `GRANT` sobre objetos existentes sin cambiar su propietario legacy, antes de considerar un `ALTER ... OWNER TO` explícito objeto por objeto (nunca `REASSIGN OWNED BY` como operación por defecto).
- No crea ni modifica ninguna regla industrial, sector, formulario ni política de autorización del producto: estos scripts son exclusivamente de PostgreSQL (roles y privilegios), nunca tocan `backend/app/sectors.py`, `capture_service.py` ni ningún archivo de política de negocio.
- No concede ningún privilegio automático sobre objetos futuros (PG54-01): cada migración nueva es responsable de sus propios `GRANT`.
