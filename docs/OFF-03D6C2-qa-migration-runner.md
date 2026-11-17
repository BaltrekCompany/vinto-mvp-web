# VINTO OFF-03D.6C2 - Ejecutor protegido de migraciones QA

**Estado 17-nov-2026:** Candidato Draft en GitHub. No se ha aplicado DDL en la VPS.

## Evidencia de entrada
- OFF-03D.6C1 PASS en VPS: respaldo previo B2 restaurable, venv QA, 31 SQL íntegros, rol vinto_migrator y destino PostgreSQL efectivo 127.0.0.1:6554 confirmado. Ver PR #202.
- Respaldo lógico pre-DDL OFF-03D.6B2 restaurado y comprobado; hash y ACL PASS, sin credenciales originales. Ver PR #201.
- Checkout QA inmutable: 7b9eb8c82a290d06e719ee4990c2020076bbd11b; QA vinto-qa-postgres / vinto_qa_offline / 6554. No tocar el piloto 6544 ni TVC 6543.

## Script y condiciones

Archivo scripts/off-03d6c2-qa-migration-runner.sh, siempre descargado del commit aprobado y verificado mediante blob Git.

### inspect (solo lectura)
1. Revalida script C1 exacto, blob 376bad3820642ac0efa038222f171bd5f2d97607; ejecuta C1 inspect, que también valida el respaldo PRE-DDL de B2.
2. Comprueba checkout fijo, backend/migrate.py y ocho scripts ACL con los blobs del SHA original. C1 verifica además las 31 migraciones SQL originales.
3. Conecta al contenedor QA y al puerto host fijo 127.0.0.1:6554, rol vinto_migrator, compara postmaster, base, ACL, esquemas e historial vacío. No acepta DSN arbitraria.
4. Ejecuta el estado genérico del migrador con ambiente de subproceso sanitizado: APP_ENV=qa, PG_PRIVILEGE_MODE=hardened, MIGRATOR_DATABASE_URL fija sin password en URL y PGPASSWORD suministrada al proceso solo desde secreto local QA; sin heredar DATABASE_URL ni variables del piloto/TVC. Exige 31 pendientes.
5. Salida: OFF03D6C2_PINNED_MIGRATOR_ACL=PASS, OFF03D6C2_EFFECTIVE_TARGET=PASS, OFF03D6C2_HISTORY_BEFORE=EMPTY, OFF03D6C2_MIGRATOR_STATUS=31_PENDING, OFF03D6C2_PREFLIGHT=PASS_READ_ONLY, OFF03D6C2_MIGRATIONS=NOT_STARTED, NO_DATABASE_WRITES=PASS.

### apply (requiere autorización explícita; recibida para QA en esta conversación, pendiente de revalidación del artefacto final)
1. Requiere simultáneamente CONFIRM_QA_MIGRATIONS=YES y CONFIRM_QA_TARGET=vinto_qa_offline_6554 antes de cualquier acceso; repite C1 y todas las verificaciones pre-DDL.
2. Usa exclusivamente el entorno de Python QA aislado y el destino fijo; ejecuta 0001-0031 con rol vinto_migrator y luego exige migrador --check con 31 checksums.
3. Ejecuta 02_schema_grants y 03_table_grants; antes de 03b valida login dedicado vinto_reference y corre import_reference.py --target dev como dry-run READ ONLY con REFERENCE_DATABASE_URL fija en QA y PG_PRIVILEGE_MODE=hardened. Exige plan sin conflictos. Después ejecuta 03b_d3b1_restrict_catalog_writes, 04_function_grants, 05_no_default_privileges, 06_public_and_meta_protection y los controles read-only 07_verification_queries / 08_release_preflight. Contraseña y SQL se envían por stdin o entorno aislado, nunca en argumentos de proceso.
4. Verifica historial 31, seis esquemas, vinto_app sin USAGE en vinto_meta, INSERT no autorizado sobre catálogos e inexistencia de CONNECT de PUBLIC. Sólo entonces OFF03D6C2_APPLY=PASS_QA_ONLY.

## Requisito adicional D3B1: rol de referencias

El repositorio backend/roles/README.md declara una dependencia crítica antes de adoptar 03b_d3b1_restrict_catalog_writes.sql: import_reference.py debe conectarse con el rol dedicado vinto_reference; en modo hardened exige REFERENCE_DATABASE_URL y no puede caer a DATABASE_URL/vinto_app. El runner comprueba el secreto QA /etc/vinto-qa/role-reference.password (root:0600), prueba la autenticación efectiva de ese rol contra el mismo postmaster QA en modo read-only, y tras aplicar 02 + 03 ejecuta import_reference.py --target dev como dry-run con URL fija 127.0.0.1:6554/vinto_qa_offline, PG_PRIVILEGE_MODE=hardened y password del rol de referencia. Exige plan dry-run sin escrituras ni conflictos antes de ejecutar 03b; así detecta ausencia de configuración o privilegios de lectura antes de endurecer los permisos de catálogo. Después del conjunto ACL, una consulta read-only valida SELECT/INSERT/UPDATE de vinto_reference sobre todas las tablas de importación, además de import_record/audit_event y ausencia de USAGE en txn/auth/meta.

La CI D5 invocada por este PR ejecuta el mismo dry-run de referencia en PG17 efímero entre 03 y 03b. El dry-run de QA no importa datos y no crea ni modifica filas. La importación real de datos de catálogo no forma parte de D6C2; solo se valida el dry-run. La escritura del bundle oficial se evaluará en una fase posterior y autorización propia.

## Recuperación y riesgos

Ante cualquier error detener; no repetir apply, ni borrar respaldo, ni manipular historial a mano. Las migraciones son transaccionales por archivo, pero una falla tardía puede dejar un estado parcial en QA. El respaldo B2 es PRE-DDL: su comparación contra QA activa fallará legítimamente después de cambios de esquema y NO debe ejecutarse como post-check de una migración exitosa.

No ejecutar 03d_d3b4_cut_identity_dml.sql, 00b_create_test_admin_role.sql, ni crear usuarios/datos reales. No hacer merge a main.

La CI cubre barreras negativas, parsing Python y una ejecución real de las 31 migraciones más ACL mediante el harness CI de D5 sobre PG17 efímero. No constituye prueba E2E de este wrapper en la VPS. Siguiente: CI y revisión, después inspect manual; una autorización independiente será necesaria antes de ejecutar apply.
