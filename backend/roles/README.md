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

## Qué NO hace este modelo todavía

- No se adopta en ninguna base persistente (DEV compartido, QA, operativo). CLOUD-01B-2B.2 decidirá esa estrategia, reutilizando el "despliegue paralelo" de CLOUD-01B-2A (§5): `GRANT` sobre objetos existentes sin cambiar su propietario legacy, antes de considerar un `ALTER ... OWNER TO` explícito objeto por objeto (nunca `REASSIGN OWNED BY` como operación por defecto).
- No crea ni modifica ninguna regla industrial, sector, formulario ni política de autorización del producto: estos scripts son exclusivamente de PostgreSQL (roles y privilegios), nunca tocan `backend/app/sectors.py`, `capture_service.py` ni ningún archivo de política de negocio.
- No concede ningún privilegio automático sobre objetos futuros (PG54-01): cada migración nueva es responsable de sus propios `GRANT`.
