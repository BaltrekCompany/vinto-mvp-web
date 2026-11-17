# VINTO OFF-03D.6C3 — Auditoría independiente posterior a migraciones QA

**Estado (17-nov-2026):** preparado en GitHub, NO ejecutado en la VPS; las 31 migraciones QA siguen pendientes. Este control no autoriza ejecución de DDL.

## Evidencia de entrada
- OFF-03D.6C2 `inspect` en VPS: `SCRIPT_INTEGRITY=PASS`, `OFF03D6C2_PINNED_MIGRATOR_ACL=PASS`, `OFF03D6C2_EFFECTIVE_TARGET=PASS`, `OFF03D6C2_HISTORY_BEFORE=EMPTY`, `OFF03D6C2_MIGRATOR_STATUS=31_PENDING`, `OFF03D6C2_PREFLIGHT=PASS_READ_ONLY`, `OFF03D6C2_MIGRATIONS=NOT_STARTED`, `NO_DATABASE_WRITES=PASS`. Commit del ejecutor `e42ad032ed9f056bed79d97394b0bc53e4941fd0`, blob `0885bf02d9cc5f298de795499b9f6a36e34c4c43`. CI run `44186765461`: 2/2 PASS.
- OFF-03D.6B2: respaldo inicial QA restaurado en PostgreSQL 17 sin red, con controles de integridad y ACL PASS. Ubicación local protegida bajo `/srv/vinto-qa-offline/backups`.
- El estado de QA actual aún es PRE-DDL, con historial vacío. El PR #203 permanece Draft y sin merge.

## Justificación

El script B2 `verify` y C1 `inspect` comprueban intencionadamente que el esquema QA sigue igual que antes de migrar. Por tanto **no deben invocarse después de un DDL exitoso**: producirían un falso bloqueo por cambio legítimo del esquema. Se necesita un verificador POST-DDL separado, únicamente de lectura.

## Script D6C3

Archivo `scripts/off-03d6c3-qa-postmigration-audit.sh`, único modo `audit`:

1. Comprueba que siguen activos los servicios del piloto y TVC (sin reiniciarlos). Verifica checkout detached, limpio, remoto y SHA `7b9eb8c82a290d06e719ee4990c2020076bbd11b`, y el entorno Python QA aislado.
2. Revalida que existe un **único** respaldo B2 con carpeta root 0700, marcador `RESTORE_VERIFIED`, sumas SHA256 correctas y firmas `origin.json`/`restored.json` idénticas. **No vuelve a comparar ese origen PRE-DDL con el esquema actual POST-DDL.**
3. Comprueba imagen, estado healthy, red, volumen, etiqueta y puerto del contenedor `vinto-qa-postgres`, `127.0.0.1:6554`, sin conectarse a piloto/TVC.
4. Calcula los checksums SQL canónicos de 31 archivos locales y verifica cada blob contra Git HEAD; compara versión, nombre y SHA256 con **cada una de las 31 filas reales** de `vinto_meta.schema_migration`.
5. Consulta metadatos PostgreSQL con `default_transaction_read_only=on`: seis esquemas, propiedad de esquemas/objetos, roles técnicos sin privilegios peligrosos, ausencia de roles identity/test_admin, permiso CREATE solo del migrador, ausencia de CONNECT a PUBLIC, ACL de `vinto_meta`, restricción de escritura a catálogos para app y conservación de escritura para reference.
6. Confirma que el corte de identidad 03d no se ejecutó, comprobando que `vinto_app` conserva su INSERT base sobre `vinto_master.user`.

No acepta `apply`, `migrate`, `restore` ni modo de escritura. No hace SQL DDL/DML, no crea archivos, no instala paquetes ni elimina contenedores. Los comandos `docker exec` usan SELECT con `default_transaction_read_only=on`; el entorno de subproceso se reconstruye sin heredar variables PG/DOCKER del operador. No se imprimen filas de negocio ni secretos.

## Cierre esperado **solo después de autorización y aplicación D6C2**

- `OFF03D6C3_PILOT_TVC_RUNNING=PASS`
- `OFF03D6C3_CHECKOUT_VENV=PASS`
- `OFF03D6C3_PRE_DDL_BACKUP_INTEGRITY=PASS`
- `OFF03D6C3_QA_DB_ISOLATION=PASS`
- `OFF03D6C3_LOCAL_MIGRATIONS_31=PASS`
- `OFF03D6C3_MIGRATION_HISTORY_31=PASS`
- `OFF03D6C3_MIGRATION_CHECKSUMS=PASS`
- `OFF03D6C3_SCHEMAS_6_OWNERSHIP=PASS`
- `OFF03D6C3_POSTMIGRATION_ACL=PASS`
- `OFF03D6C3_NO_IDENTITY_CUT=PASS`
- `OFF03D6C3_AUDIT=PASS_READ_ONLY`
- `NO_DATABASE_WRITES=PASS` (solo la auditoría).

## Límites y liberación

GitHub Actions prueba sintaxis, lógica estática, modo fail-closed y compatibilidad de 31 migraciones/ACL en una instancia PG17 efímera. **No constituye prueba E2E del verificador sobre QA real**. El verificador se descarga con SHA completo y se compara con blob Git antes de su ejecución. No se debe ejecutar antes de las migraciones: la ausencia de historial causaría bloqueo previsto.

Cualquier `apply` sobre QA requiere consentimiento explícito en un turno independiente, tras revisar ambos PR. Si la aplicación falla o queda parcialmente aplicada, NO ejecutar B2 verify ni restaurar automáticamente sobre QA: detener y diagnosticar el estado con consultas de lectura y propuesta específica. Ninguna operación está autorizada sobre `main`, piloto ni TVC.
