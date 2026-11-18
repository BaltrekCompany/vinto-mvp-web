# VINTO — OFF-03D.7C4: respaldo POST-DDL de QA y restauración sin red

**18-nov-2026 | PR Draft apilado sobre #209.** Este incremento **prepara y prueba en CI** la recuperación de PostgreSQL QA tras las 31 migraciones. **No autoriza su ejecución de escritura en VPS**, creación de backups, modificación de DB, Nginx, Node, servicios, usuarios, catálogos, firma ni flags. El estado del dominio QA continúa sin control de acceso verificado: prohibido exponer UI/API.

## Antecedentes y evidencia

- D6C2/C3: 31 migraciones aplicadas solo en `vinto_qa_offline` (127.0.0.1:6554), propietarios/ACL auditados, respaldo B2 **PRE-DDL** íntegro. No repetir migración ni ejecutar C1/B2 verify sobre la base ya migrada.
- D7C3: Codex ejecutó el `inspect` inmutable, con `OFF03D7C3_PREFLIGHT=PASS_READ_ONLY`, `OFF03D7C3_POSTMIGRATION_AUDIT=PASS`, `OFF03D7C3_MIGRATIONS_31=PASS`, `OFF03D7C3_POST_DDL_SOURCE=EMPTY_QA_31_MIGRATIONS`, `OFF03D7C3_FREE_DISK_2GIB=PASS`, `OFF03D7C3_POST_DDL_BACKUP=NOT_CREATED`, `NO_DATABASE_WRITES=PASS`.
- El SQL D7C3 ya exige conteos de usuarios, concesiones, versiones e import batches en cero, aunque **emite un único indicador agregado**, no cuatro PASS individuales. No demuestra ausencia de todos los maestros de referencia; D7C anterior había confirmado baseline vacío por conteos independientes de otras tablas.
- D7C2: CI en PG17 desechable confirmó bundle oficial, dry-run, importación, idempotencia y cuatro versiones Calidad **published dentro de la misma transacción**; 8 vínculos a MP1/MP3 y ningún usuario/grant. En la VPS real todavía no se importó.

## Artefacto nuevo — modos y restricciones

`scripts/off-03d7c4-qa-postddl-backup-restore.sh` ofrece tres modos estrictos:

| Modo | Qué hace | Requiere autorización VPS |
|---|---|---|
| `inspect` | Verifica integridad del gate D7C3, auditoría POST-DDL, base QA vacía, ausencia de backup D7C4 previo y metadatos en lectura | No; read-only |
| `backup-restore` | Copia coherente de QA POST-DDL (custom dump + roles sin passwords), restaura en PG17 efímero sin red, compara metadatos/ACL/historial, conserva checksums y prueba de recuperación | **Sí, autorización específica nueva** |
| `verify` | Revisa hashes y metadatos del archivo de recuperación D7C4 ya creado, sin comparar con la base que puede haber cambiado tras futuras importaciones | No; read-only, **solo si D7C4 ya existe** |

**El modo `backup-restore` no está autorizado actualmente.** Requiere de forma explícita `CONFIRM_QA_POSTDDL_BACKUP=YES` y `CONFIRM_QA_TARGET=vinto_qa_offline_6554`, validados antes de cualquier archivo/contenedor. Solo el operador podrá aprobarlo en una etapa posterior. No inferir esa autorización de PASS de D7C3 ni de ejecutar `inspect`.

### Diseño de resguardo

- QA fuente: únicamente contenedor `vinto-qa-postgres`, PG17, `vinto_qa_offline`; el gate previo D7C3 fija puerto/red, servicios piloto y TVC y comprueba 31 migraciones.
- Directorio de backup: `/srv/vinto-qa-offline/backups/off03d7c4-XXXXXXXX`, root `0700`; archivos root `0600`. Conservar **un** directorio B2 PRE-DDL diferente; jamás escribir sobre él.
- Herramientas dentro del contenedor PG17: `pg_dump --format=custom --create`, `pg_dumpall --globals-only --no-role-passwords`; no se copian ni muestran contraseñas.
- Huella de fuente / posterior a dump / restauración: JSON estructurado **solo de metadatos** (nombre de DB, owner, flags de roles, esquemas y propietarios, propietarios de tablas y funciones, historial ordenado con checksums, ACL efectivas y conteos agregados). No contiene filas de usuarios, password hashes, capturas ni OT.
- Restauración: contenedor PG17 creado exclusivamente para la prueba, `--network none`, **sin puertos**, almacenamiento `tmpfs`, nombre propio y label exclusivo, sin montajes/volúmenes operativos. El proceso se elimina al terminar. Si falla, permanece el directorio de backup incompleto para diagnóstico (no borrar automáticamente); `inspect` impedirá accidentalmente repetir `backup-restore`.
- Evidencia: SHA256 de los artefactos, igualdad byte a byte de huellas `origin.json` / `after-dump.json` / `restored.json`, marcador `RESTORE_VERIFIED`. Un PASS asegura recuperabilidad estructural y ACL en ese ensayo, **no es estrategia offsite ni respaldo de contraseñas de roles**. Si en otro incidente fuera necesaria recuperación real, reconfigurar credenciales por mecanismo protegido y aprobar plan específico.
- **Nunca restaurar sobre la base QA operativa**. `verify` valida el respaldo histórico aunque la QA cambie después, sin exigir que permanezca vacía.

## Qué prueba GitHub Actions

`.github/workflows/off-03d7c4-qa-backup-restore.yml`:

1. Control estático de sintaxis y modos negativos; descarga/edición de archivos en GitHub solo en branch Draft.
2. PostgreSQL 17 **efímero en CI**: aplicar 31 migraciones + ACL, generar dump y globals sin passwords, arrancar una segunda instancia aislada sin red, restaurar y comparar la misma consulta de metadatos del runner VPS, verificando historial, roles y grants. Al terminar se eliminan ambos contenedores, archivos y secretos efímeros. GitHub Actions **no conecta a la VPS**.

Esta prueba valida el procedimiento, **no autoriza respaldar QA real**.

## Secuencia después de autorización futura

1. Recibir resultado CI 2/2 PASS y la inspección D7C4 en VPS por Codex (hash Git + `bash -n`, solo `inspect`).
2. Solicitar y registrar **autorización específica para crear los archivos de respaldo y un contenedor temporal sin red**, sin DML en QA ni cambiar piloto/TVC.
3. Ejecutar **una sola vez** `backup-restore` bajo las confirmaciones exactas del ejecutor inmutable; detener ante cualquier FAIL. Conservar la evidencia para recuperación futura.
4. Verificar y cerrar nuevo respaldo POST-DDL; luego **otra autorización separada** para importar bundle oficial usando `vinto_reference` y una barrera QA con dry-run, checksum y transacción. No mezclar estas fases.
5. Después evaluar usuario ficticio Calidad, 8 concesiones y firma Ed25519 exclusiva QA; el control de acceso VPN/allowlist con denegación predeterminada sigue siendo gate obligatorio antes de publicar frontend/API.

**Prohibiciones permanentes de este PR:** no fusionar a main, no desplegar, no tocar Nginx, servicios piloto, TVC ni PostgreSQL de producción. OFF-04 captura/sync sigue deshabilitada.
