# Modelo de privilegios mínimos de PostgreSQL (CLOUD-01B-2)

Diseñado en CLOUD-01B-2/CLOUD-01B-2A, implementado y probado en una instancia PostgreSQL 17 **efímera**
en CLOUD-01B-2B.1 (`backend/tests/roles_e2e.py`). **Todavía no se adoptó en DEV, QA ni operativo.**
Nada de lo que hay aquí se ejecuta automáticamente; cada script es SQL versionado que un administrador
del clúster (o el propio `vinto_migrator`, según se indica) ejecuta a mano, una vez por entorno.

No hay contraseñas reales en ningún archivo de esta carpeta: todas se pasan como variables de psql
(`-v nombre=valor`) o se generan al vuelo en pruebas efímeras.

## Las 4 identidades

| Rol | Puede | No puede |
|---|---|---|
| `vinto_app` | `SELECT`/`INSERT`/`UPDATE` (y `DELETE` solo en `vinto_master.user_sector`) sobre las tablas de negocio | `CREATE`/`ALTER`/`DROP`/`TRUNCATE`/`GRANT`; `CREATEDB`/`CREATEROLE`/`SUPERUSER`; nada sobre `vinto_meta` |
| `vinto_migrator` | Propietario de los 6 esquemas y de todo lo que contienen: DDL completo + el DML que una migración necesite para sus backfills | `CREATEDB`/`CREATEROLE`/`SUPERUSER`; crear otros roles |
| `vinto_reference` | `SELECT`/`INSERT`/`UPDATE` sobre las tablas de catálogo/formulario/receta que `import_reference.py` escribe | Nada sobre `vinto_txn`/`vinto_auth`/`vinto_meta`; ningún DDL |
| `vinto_test_admin` | `CREATEDB`, conectar a `postgres`, crear/destruir bases `*_test` | **Solo existe en DEV/QA**; nunca se crea en un entorno operativo |

## Orden de ejecución (una base/entorno a la vez)

1. `00_create_roles.sql` — administrador del clúster. Crea los 4 roles con `LOGIN` y fija `search_path = ''` en cada uno.
2. `01_database_grants.sql` — administrador del clúster, conectado a la base objetivo. `REVOKE CONNECT FROM PUBLIC` + `GRANT CONNECT` a `vinto_app`/`vinto_migrator`/`vinto_reference` (no a `vinto_test_admin`, que no opera sobre esta base) + `GRANT CREATE` a `vinto_migrator` únicamente (necesario para que pueda crear los esquemas en el paso siguiente; en una base nueva los esquemas todavía no existen, así que esto es `CREATE` de base, no de esquema).
3. **Aplicar las migraciones existentes conectando como `vinto_migrator`** (`MIGRATOR_DATABASE_URL`/`MIGRATOR_TEST_DATABASE_URL`, ver `backend/app/config.py`): `python migrate.py --target dev` (o `--target test`). Esto crea los 6 esquemas y todas las tablas/funciones/triggers con `vinto_migrator` como propietario — no hace falta ningún `ALTER ... OWNER TO` posterior en una base nueva.
4. `02_schema_grants.sql` — `vinto_migrator` (ya es propietario). `USAGE` por esquema.
5. `03_table_grants.sql` — `vinto_migrator`. DML por tabla, matriz completa con evidencia citada.
6. `04_function_grants.sql` — `vinto_migrator`. El único `EXECUTE` real (`vinto_txn.management_start_year`).
7. `05_default_privileges.sql` — `vinto_migrator`. Privilegio por defecto (`SELECT` únicamente) para tablas que una migración 0007+ cree en el futuro.
8. `06_public_and_meta_protection.sql` — `vinto_migrator`. Documentación explícita y verificable de que `PUBLIC` no tiene nada y `vinto_meta`/`vinto_auth` están protegidos.
9. `07_verification_queries.sql` — cualquier rol con visibilidad suficiente (superusuario o `vinto_migrator`). Solo lectura; confirma el contrato resultante.

## Qué NO hace este modelo todavía

- No se adopta en ninguna base persistente (DEV compartido, QA, operativo). CLOUD-01B-2B.2 decidirá esa estrategia, reutilizando el "despliegue paralelo" de CLOUD-01B-2A (§5): `GRANT` sobre objetos existentes sin cambiar su propietario legacy, antes de considerar un `ALTER ... OWNER TO` explícito objeto por objeto (nunca `REASSIGN OWNED BY` como operación por defecto).
- No crea ni modifica ninguna regla industrial, sector, formulario ni política de autorización del producto: estos scripts son exclusivamente de PostgreSQL (roles y privilegios), nunca tocan `backend/app/sectors.py`, `capture_service.py` ni ningún archivo de política de negocio.
