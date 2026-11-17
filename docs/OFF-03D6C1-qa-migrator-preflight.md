# VINTO OFF-03D.6C1 — Puerta de lectura del migrador QA

**Fecha:** 17-nov-2026. **Estado:** candidato Draft. No ejecuta migraciones ni cambia bases de datos.

## Evidencia de entrada

El operador completó OFF-03D.6B2 con backup y restauración de QA real, reporte independiente `OFF03D6B2_VERIFY=PASS_NO_QA_DDL`, hashes y comparación de roles/ACL PASS, sin red en la instancia restaurada, `NO_QA_DATABASE_WRITES=PASS`. Evidencia completa en PR #201. CI run 44180439478 2/2 PASS.

El checkout QA existente usa el commit `7b9eb8c82a290d06e719ee4990c2020076bbd11b` (31 migraciones, sin cambios), venv Python aislado; PostgreSQL QA es `vinto-qa-postgres` con puerto host localhost:6554 y DB `vinto_qa_offline`.

## Revisión del migrador

`backend/migrate.py` recibe `--target dev` y, en modo hardened, exige `MIGRATOR_DATABASE_URL`. Esa opción de CLI **NO** garantiza por sí sola que el destino sea QA: el código genérico invoca `psycopg.connect(url)` sin confrontar host, puerto, identidad del clúster. **No ejecutar `migrate.py --target dev` directamente en VPS**. Los comandos de migración precisan wrapper posterior, prohibiendo DSN arbitrarias y bloqueando DDL hasta autorización explícita.

## Script D6C1 (solo inspect)

Archivo `scripts/off-03d6c1-qa-migrator-preflight.sh`:
1. Exige script B2 exacto (blob Git `8d7193acfe59acc243bff47c65048705f2847c1d`) en /tmp, invoca **`B2 verify`**, comprueba hashes y que el origen QA sigue igual que la evidencia del backup. **No usar B2 inspect tras haberse creado un backup: ese modo exige carpeta vacía y fallaría correctamente.**
2. Verifica directorio QA, checkout detached al SHA anterior y árbol limpio. Rechaza archivos `.env` en raíz/backend, comprueba 31 SQL consecutivos y sus blobs Git reales (no solo nombres), para detectar modificaciones incluso ignoradas.
3. Verifica archivo secreto QA root:0600. Toma una marca de tiempo del postmaster en el contenedor QA mediante SQL read-only.
4. Desde el **venv QA** abre una conexión temporal PostgreSQL con parámetros inmutables: host `127.0.0.1`, puerto `6554`, DB `vinto_qa_offline`, rol `vinto_migrator`. Lee la contraseña directamente desde el archivo protegido sin imprimirla ni pasarla por argumentos CLI. Impone modo `default_transaction_read_only=on`; compara nombre de base, rol, puerto **interno** 5432, marca de postmaster, estado `pg_is_in_recovery()`, ausencia de esquemas e historial, CREATE del migrador y ausencia de CONNECT a PUBLIC.
5. Reporta `OFF03D6C1_BACKUP_RESTORE_GATE=PASS`, `OFF03D6C1_CHECKOUT_MIGRATIONS_31=PASS`, `OFF03D6C1_HOST_TO_QA_DB_IDENTITY=PASS`, `OFF03D6C1_REAL_ROLE_MIGRATOR=PASS`, `OFF03D6C1_MIGRATION_HISTORY=EMPTY`, `OFF03D6C1_PREFLIGHT=PASS_READ_ONLY`, `NO_DATABASE_WRITES=PASS`.

El script no crea archivos, no ejecuta `migrate.py`, y no restaura ni migrará ninguna base. No admite modos de escritura.

## Próximos gates no autorizados

- D6C2: desarrollar un wrapper que fije destino y SHA, compare la identidad PostgreSQL efectiva otra vez **antes del primer DDL**, tenga punto de bloqueo único `CONFIRM_QA_MIGRATIONS=YES`, y valide backup previo; revisar/reproducir en CI con PG17 efímero.
- D6C3: ejecutar sobre la VPS solo tras aprobación independiente, sin tocar `vinto_piloto` (6544), TVC (6543), sus servicios, ni main. Aplicar en QA 0001–0031 y controles ACL 02,03,03b,04,05,06; NO ejecutar 03d, ni crear roles de test admin por defecto.
- El backup B2 es **PRE-DDL**. Después de migraciones válidas `B2 verify` sobre el origen deja de pasar deliberadamente porque el esquema cambió; se requiere un control post-migración distinto, no actualizar retroactivamente el fingerprint anterior.

El PR debe permanecer Draft y encadenado a #201, sin merge a main.

## Incidente real del primer preflight D6C1 (17-nov-2026)

El operador ejecutó el script del SHA `d467387d1ff369e9144d3c8342916c03f093a96b` (blob `0e4f73da04736cc415dd16544d688d44b6246874`) y obtuvo `OFF03D6C1_BACKUP_RESTORE_GATE=PASS`, seguido de **`OFF03D6C1_BLOCKED: venv QA ausente`**. En la misma salida, B1 verify confirmó `OFF03D6B1_PYTHON_IMPORTS=PASS`, `OFF03D6B1_VENV=PASS_ISOLATED`, `OFF03D6B1_CHECKOUT=PASS_DETACHED_CLEAN`; B2 verify repitió integridad, restauración y origen inalterado en PASS. No se ejecutó SQL DDL ni migraciones.

**Causa de código:** el primer D6C1 exigía `[ ! -L "$PYTHON" ]` sobre `/srv/vinto-qa-offline/venv/bin/python`, aunque `python3 -m venv` crea habitualmente un symlink del ejecutable al intérprete base en Linux. Es una diferencia respecto de B1, que correctamente admite ese enlace; no prueba que falte el venv. **No reinstalar, borrar, reconstruir checkout/venv ni repetir backup** para resolver esta condición.

**Corrección:** reemplazar ese veto por una validación del **directorio** de venv (no symlink), ejecutable Python presente, `sys.prefix` igual al venv fijo, `sys.base_prefix` diferente y módulos QA importables. Test de regresión reproduce symlink normal de ejecutable, rechazo de raíz de venv enlazada y Python faltante; parser Python independiente. Un nuevo script requiere su **propio SHA completo, blob Git y CI PASS** antes de reintentar `inspect` en VPS. Hasta nueva evidencia `OFF03D6C1_PREFLIGHT=NOT_PASSED`; no autorización de DDL ni inicio D6C2.
