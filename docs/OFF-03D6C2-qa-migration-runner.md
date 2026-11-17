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

### apply (NO AUTORIZADO EN ESTE PASO)
1. Requiere simultáneamente CONFIRM_QA_MIGRATIONS=YES y CONFIRM_QA_TARGET=vinto_qa_offline_6554 antes de cualquier acceso; repite C1 y todas las verificaciones pre-DDL.
2. Usa exclusivamente el entorno de Python QA aislado y el destino fijo; ejecuta 0001-0031 con rol vinto_migrator y luego exige migrador --check con 31 checksums.
3. Ejecuta en orden SQL de roles: 02_schema_grants, 03_table_grants, 03b_d3b1_restrict_catalog_writes, 04_function_grants, 05_no_default_privileges, 06_public_and_meta_protection; finalmente los controles read-only 07_verification_queries y 08_release_preflight. Contraseña y SQL se envían por stdin, nunca en la línea de comandos.
4. Verifica historial 31, seis esquemas, vinto_app sin USAGE en vinto_meta, INSERT no autorizado sobre catálogos e inexistencia de CONNECT de PUBLIC. Sólo entonces OFF03D6C2_APPLY=PASS_QA_ONLY.

## Recuperación y riesgos

Ante cualquier error detener; no repetir apply, ni borrar respaldo, ni manipular historial a mano. Las migraciones son transaccionales por archivo, pero una falla tardía puede dejar un estado parcial en QA. El respaldo B2 es PRE-DDL: su comparación contra QA activa fallará legítimamente después de cambios de esquema y NO debe ejecutarse como post-check de una migración exitosa.

No ejecutar 03d_d3b4_cut_identity_dml.sql, 00b_create_test_admin_role.sql, ni crear usuarios/datos reales. No hacer merge a main.

La CI cubre barreras negativas, parsing Python y una ejecución real de las 31 migraciones más ACL mediante el harness CI de D5 sobre PG17 efímero. No constituye prueba E2E de este wrapper en la VPS. Siguiente: CI y revisión, después inspect manual; una autorización independiente será necesaria antes de ejecutar apply.
