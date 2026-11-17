# VINTO OFF-03D.5 — Ensayo de 31 migraciones y gate de VPS QA

**Fecha:** 17-nov-2026. **Estado:** OFF-03D.5 gate de lectura cerrado PASS; PR Draft, **sin DDL en VPS**.

## Entrada verificada

El operador instaló en PostgreSQL QA los tres roles técnicos y concedió permisos de conexión exclusivamente sobre `vinto_qa_offline`:

- `OFF03D4_INSTALL=PASS_ROLES_ONLY`
- `OFF03D4_VERIFY=PASS_ROLES_ONLY` (repetido en una llamada de verificación independiente)
- `QA_ROLE_PRIVILEGES=PASS`
- `QA_ROLE_AUTH=PASS`
- `QA_MIGRATION_HISTORY=EMPTY`

El contenedor `vinto-qa-postgres` está aislado en `127.0.0.1:6554`, volumen `vinto-qa-offline-pgdata`, red `vinto-qa-internal`. El piloto tiene otro clúster/base `vinto-mvp-postgres/vinto_piloto`, puerto `6544`; TVC usa `postgres-vinto`, puerto `6543`. No tocar ninguno de ellos.

## A. Ensayo automatizado en GitHub Actions (sin VPS)

`scripts/off-03d5-migrations-ci-e2e.sh` exige `GITHUB_ACTIONS=true` y usa un PostgreSQL 17 **efímero en el runner GitHub**, con credenciales ficticias distintas. Corre:

1. `backend/roles/00_create_roles.sql` y `01_database_grants.sql` con administrador del **clúster efímero**.
2. Instala solo las dependencias Python pinneadas que necesita `backend/migrate.py`: psycopg[binary] 3.3.6 y pydantic-settings 2.15.0, en un virtualenv efímero.
3. Rechaza una conexión cuyo host, puerto, DB o usuario no coincidan con el PostgreSQL del runner. Exige 31 archivos consecutivos de migración, 0001–0031, sin historial previo.
4. Ejecuta `migrate.py --target dev --status`, luego `migrate.py --target dev` y finalmente `migrate.py --target dev --check`, con `PG_PRIVILEGE_MODE=hardened` y rol `vinto_migrator`. **La palabra dev es una opción del CLI genérico, NO autorización para modificar desarrollo.** El runner verifica origen y credenciales antes de esa opción.
5. Ejecuta `02_schema_grants.sql`, `03_table_grants.sql`, **inmediatamente** `03b_d3b1_restrict_catalog_writes.sql`, `04_function_grants.sql`, `05_no_default_privileges.sql`, `06_public_and_meta_protection.sql` y las consultas read-only `07_verification_queries.sql` y `08_release_preflight.sql` usando rol migrador.
6. Verifica 31 versiones registradas, seis esquemas, falta de USAGE de `vinto_app` en `vinto_meta`, ausencia de INSERT de aplicación en profile/machine/sector y ausencia de CONNECT para PUBLIC. Destruye exclusivamente el contenedor y los secretos efímeros del runner.

**Resultado CI = ensayo de compatibilidad, no prueba de migración en la VPS.** No autoriza por sí mismo ejecutar DDL real.

## B. Gate de solo lectura en la VPS

Descargar `scripts/off-03d5-qa-migration-preflight.sh` del SHA exacto del PR y comparar con su blob Git, luego:

```bash
bash -n scripts/off-03d5-qa-migration-preflight.sh
sudo bash scripts/off-03d5-qa-migration-preflight.sh inspect
```

Exige TLS QA, aislamiento Docker + bind localhost, secreto migrador root:0600, servicios existentes sanos, tres roles QA, ningún esquema ni historial migratorio, autenticación real del migrador usando solo credencial QA (sin imprimirla), y reporta Python local. Los metadatos PostgreSQL se consultan con `default_transaction_read_only=on`.

**PASS previsto:** `OFF03D5_PREFLIGHT=PASS_READ_ONLY`, `QA_MIGRATOR_AUTH=PASS`, `QA_SCHEMA_EMPTY=PASS`, `QA_MIGRATION_HISTORY=EMPTY`, `NO_DATABASE_WRITES=PASS`. **No prueba que exista entorno virtual QA**, lo señala como `PYTHON_VENV_INSTALLATION=NOT_VERIFIED`; tampoco prueba checkout QA (`QA_CHECKOUT_SHA=NOT_VERIFIED`).

## C. Fase de escritura posterior (NO incluida en este PR)

Sin una tercera revisión, no ejecutar migraciones contra la VPS. La siguiente autorización debe contemplar:

1. Crear checkout íntegramente **separado** de `/opt/vinto-mvp-web` y `/home/ubuntu/vinto`, en SHA completo del candidato que incluya #184–#198. Confirmar árbol limpio y sin mezcla con `main` desplegado.
2. Crear entorno virtual Python exclusivo de QA, con dependencias fijadas y sin tocar el venv del piloto. La preparación es una operación de archivos separada, no un comando de migración.
3. Respaldo de clúster/base QA y verificación de restaurabilidad **antes de DDL**, sin transportar secretos/capturas a GitHub.
4. Preparar wrapper migrador **que no admita DSN arbitraria**, fuerce host 127.0.0.1, puerto 6554, DB `vinto_qa_offline`, usuario `vinto_migrator`, y compruebe la identidad SQL real; requiere gate `CONFIRM_QA_MIGRATIONS=YES`.
5. Aplicar 0001–0031 solo en QA, comprobar checksum e historial mediante `migrate.py --check`; después aplicar 02 / 03 + 03b / 04 / 05 / 06, verificar ACL de todas las nuevas tablas y las APIs de paquete offline. No ejecutar `03d_d3b4_cut_identity_dml.sql` ni `00b_create_test_admin_role.sql` por defecto.
6. Solo tras comprobar la ACL de QA, instalar datos oficiales de catálogo, usuarios ficticios y firma QA, con procedimiento independiente. Después preparar frontend/backend aislados.

## Bloqueos

Cualquier conexión a `vinto_piloto`, clúster `vinto-mvp-postgres`/port 6544 o TVC port 6543; código checkout diferente de SHA aprobado; env o secretos del piloto; falta de backup verificable; migraciones existentes y no alineadas; `migrate.py --check` falla; deriva de ACL o cualquier dato real en QA.

**Estado:** OFF-03D.4 PASS. OFF-03D.5 CI y VPS preflight PASS (detalles abajo); DDL VPS NO autorizado. El móvil real continúa NOT_RUN.

## Incidencia de preflight en VPS — 17-nov-2026

La primera ejecución del candidato SHA `3c0ba58c1d11b3f955f8d4940ebf4b619dbd80c9` (blob `2e85d16f365ddad5552e614dc188acad77965181`) pasó integridad, HTTPS QA, aislamiento Docker, salud del piloto/TVC, roles y ausencia de esquemas/historial. Se bloqueó al validar el login migrador: el sub-shell `sh -ceu '...'` contenía un literal SQL con comillas simples (`'|'`), quebrando el argumento; `bash -n` no descubrió el defecto por tratarse de código anidado. **No equivale a credencial fallida**. No hubo DDL.

Corregido en la rama de PR #198 con `chr(124)` en el SQL para no anidar las comillas; autenticación por stdin redirigido desde el archivo QA root 0600, manejo de contraseña sin salto de línea; prueba de regresión de parsing del shell interno. **No volver a usar SHA 3c0ba58c para inspect.** Ejecutar preflight solo con commit y blob nuevos tras CI satisfactoria, confirmando `QA_MIGRATOR_AUTH=PASS` y `OFF03D5_PREFLIGHT=PASS_READ_ONLY`. El bloqueo a migraciones VPS sigue intacto: no usar `migrate.py` ni hacer DDL hasta preparar checkout/venv, respaldo/restauración y wrapper con protección de destino y autorización específica.

## Cierre auditado OFF-03D.5 — 17-nov-2026

Evidencia entregada por el operador tras descargar y verificar el script de `78ad58d8941f3263f3386a1acdff9eebdf66507b`, blob `f296b71930a8820abea8666fb1aac01a16ede9e6`:

```text
SCRIPT_INTEGRITY=PASS
QA_HTTPS=PASS
QA_DB_ISOLATION=PASS
PILOT_TVC_RUNNING=PASS
QA_ROLES_READY=PASS
QA_SCHEMA_EMPTY=PASS
QA_MIGRATION_HISTORY=EMPTY
QA_MIGRATOR_AUTH=PASS
PYTHON_VERSION=3.12.3
PYTHON_VENV_INSTALLATION=NOT_VERIFIED
QA_CHECKOUT_SHA=NOT_VERIFIED
QA_MIGRATION_DDL=NOT_STARTED
OFF03D5_PREFLIGHT=PASS_READ_ONLY
NO_DATABASE_WRITES=PASS
```

GitHub Actions `44176282847` (commit `78ad58d8941f3263f3386a1acdff9eebdf66507b`) concluyó `success`. Ambos jobs `read-only-qa-migration-preflight` y `postgres17-31-migrations-and-acl` concluyeron `success`. Corresponde al ensayo en runner PG17 efímero, **no** a DDL en VPS.

**Dictamen:** `OFF03D5_CLOSE=PASS_NO_DDL`. El preflight sigue siendo válido para la versión exacta probada; modificaciones posteriores de documentación no autorizan ejecutar un script diferente. El estado de checkout QA y venv es NOT_VERIFIED, no una falta de instalación confirmada. Mantener PR #198 Draft; no hacer merge, no crear datos, no ejecutar migraciones en VPS. Continuar con OFF-03D.6 solo mediante propuesta separada, respaldos restaurables y permisos explícitos.
