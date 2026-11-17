# VINTO OFF-03D.4 — Roles técnicos exclusivos de PostgreSQL QA

**17-nov-2026. Estado: CANDIDATO / PR Draft. No ejecutado en VPS por GitHub.**

## Entrada de la fase

El operador reportó `OFF03D3_PREFLIGHT=PASS_READ_ONLY`, `QA_CONTAINER_ISOLATION=PASS`, `QA_SCHEMA_EMPTY=PASS`, `QA_APPLICATION_ROLES_ABSENT=PASS`, `QA_MIGRATION_HISTORY_ABSENT=PASS` y `NO_DATABASE_WRITES=PASS`. Estas verificaciones son de la VPS, no de CI.

El único clúster permitido en OFF-03D.4 es el contenedor **`vinto-qa-postgres`**, base **`vinto_qa_offline`** en **`127.0.0.1:6554`**, red **`vinto-qa-internal`**, volumen **`vinto-qa-offline-pgdata`**. Los recursos `vinto-mvp-postgres` (puerto 6544) y `postgres-vinto` (6543) quedan FUERA del alcance.

## Alcance y resultados esperados

- Ejecutar exactamente los SQL **existentes** de roles `backend/roles/00_create_roles.sql` y `backend/roles/01_database_grants.sql`, en ese orden, descargados por SHA de commit fijo y verificados contra hashes Git blob.
- Crear en el clúster QA los roles `vinto_app`, `vinto_migrator`, `vinto_reference` (no superusuarios, no CREATEDB, no CREATEROLE, no herencia).
- Crear contraseñas **nuevas y exclusivas** en `/etc/vinto-qa/role-{app,migrator,reference}.password`, propiedad root y modo 0600. No leer ni reutilizar `.env` de piloto/TVC. Contraseñas via stdin a shell dentro del contenedor y variables de entorno del proceso **psql dentro del contenedor**, sin argumentos Docker con secretos.
- Quitar CONNECT/TEMPORARY a PUBLIC en `vinto_qa_offline`; dar CONNECT a los tres roles, CREATE solo a migrador.
- Verificar las tres autenticaciones TCP dentro del **contenedor QA**, así como ACL de base, imagen, red, volumen, puerto, certificados QA y servicios existentes, sin imprimir ningún password.
- **No aplicar migraciones** ni crear identidad/operario, catálogos o frontend/backend, ni activar captura/firma offline.

## Procedimiento por puertas separadas

Obtener el script de `scripts/off-03d4-qa-roles.sh` de un SHA de **commit completo**, verificar su Git blob SHA, y ejecutar:

**A. Gate solo lectura:**
```bash
bash -n scripts/off-03d4-qa-roles.sh
sudo bash scripts/off-03d4-qa-roles.sh preflight
```
Requiere `OFF03D4_PREFLIGHT=PASS_READ_ONLY`, `QA_ROLES_ABSENT=PASS`, `QA_SCHEMA_EMPTY=PASS`.

**B. Escritura exclusiva QA (AUTORIZACIÓN SEPARADA):**
```bash
sudo env CONFIRM_QA_ROLE_CREATE=YES bash scripts/off-03d4-qa-roles.sh install
```
Repite preflight, comprueba origen/imagen/volumen/puertos, descarga SQLs pinneados, verifica ambos hashes **antes de generar contraseñas**, y crea roles/GRANT de base. **No ejecutar sin autorización específica.** Si una operación falla a mitad, se conservan secretos y roles para diagnóstico: NO reejecutar automáticamente, NO eliminar el volumen ni recrear el cluster.

**C. Validación posterior (solo consulta):**
```bash
sudo bash scripts/off-03d4-qa-roles.sh verify
```
PASS exige `QA_ROLE_PRIVILEGES=PASS`, `QA_ROLE_AUTH=PASS`, `QA_MIGRATION_HISTORY=EMPTY`, `OFF03D4_VERIFY=PASS_ROLES_ONLY`. Ninguno implica que la migración/servicios estén listos.

## Restricciones y siguiente incremento

El código de aplicación `backend/migrate.py` usa `--target dev` para conexiones de migración normales, con `MIGRATOR_DATABASE_URL`. Esa etiqueta **no es garantía de base QA**. Antes de aplicar migraciones se necesita una barrera separada, con validación del contenedor y base reales, credencial migrador QA y exactamente **31 migraciones del SHA candidato**. No ejecutar `python backend/migrate.py` genérico contra el piloto. No usar `--target test` para `vinto_qa_offline` porque exige sufijo `_test`.

`03_table_grants.sql` debe ir seguido de `03b_d3b1_restrict_catalog_writes.sql` en una fase posterior; `03d_d3b4_cut_identity_dml.sql` no entra en alcance ni se debe activar implícitamente. Evitar `00b_create_test_admin_role.sql` para este QA físico, porque no necesita CREATEDB.

**Estado:** OFF-03D.3 PRE-FLIGHT PASS, OFF-03D.4 ROLE-APPLY NOT RUN, OFF-03D.5 MIGRATIONS NOT AUTHORIZED, PHYSICAL MOBILE NOT RUN.