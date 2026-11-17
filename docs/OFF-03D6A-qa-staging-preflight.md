# VINTO OFF-03D.6A — Preflight read-only de staging/venv/backups QA

**Estado:** propuesta Draft, 17-nov-2026. No instala nada en VPS. No migraciones/DDL, ni escritura de archivos, ni cambios de producción.

## Fuente de verdad / dependencias

- PR #198 / OFF-03D.5: runner PG17 efímero con 31 migraciones + ACL 2/2 PASS, ejecución `44176282847`.
- VPS validada mediante script del commit `78ad58d8941f3263f3386a1acdff9eebdf66507b`, blob `f296b71930a8820abea8666fb1aac01a16ede9e6`:
  `OFF03D5_PREFLIGHT=PASS_READ_ONLY`, `QA_MIGRATOR_AUTH=PASS`, `QA_SCHEMA_EMPTY=PASS`, `NO_DATABASE_WRITES=PASS`.
- Piloto y TVC intocables. QA es contenedor `vinto-qa-postgres`, imagen PG17, puerto localhost `6554`, DB `vinto_qa_offline`.

## Entrega D6A (inspección únicamente)

`scripts/off-03d6a-qa-staging-preflight.sh inspect` verifica el blob de D5 en `/tmp` y ejecuta de nuevo todo ese gate; posteriormente confirma:

1. Disponibilidad de rutas **nuevas** y **fijas**: `/srv/vinto-qa-offline/source` (checkout), `/srv/vinto-qa-offline/venv` (entorno Python) y `/srv/vinto-qa-offline/backups` (respaldo). Rechaza cualquier ruta ocupada o enlace simbólico; no toca `/opt/vinto-mvp-web`, `/home/ubuntu/vinto` ni `/home/ubuntu/vinto-mvp-build`.
2. Python `venv` disponible, sin crearlo.
3. `pg_dump`, `pg_dumpall` y `pg_restore` disponibles en el contenedor QA, sin ejecutarlos contra ninguna base.
4. Tamaño estimado de base QA con consulta de metadatos en modo read-only y al menos 2 GiB libres en `/srv`. Es solo el umbral preliminar: el dimensionamiento real del backup/restauración se verifica antes de escribir.

**Salida válida:** `OFF03D6A_D5_GATE=PASS`, `OFF03D6A_PATHS_AVAILABLE=PASS`, `OFF03D6A_PYTHON_VENV_CAPABLE=PASS`, `OFF03D6A_BACKUP_TOOLS=PASS`, `OFF03D6A_FREE_DISK_2GIB=PASS`, `OFF03D6A_PREFLIGHT=PASS_READ_ONLY`, `NO_DATABASE_WRITES=PASS`.

El script aborta si no encuentra el D5 probado exactamente, si no está libre el árbol reservado o si el gate de aislamiento deja de cumplir. No acepta `install`, `prepare`, `backup`, `restore`, `migrate` ni `apply`.

## Futuro D6B: **NO implementar ni ejecutar desde D6A**

Requiere inspección PASS, autorización explícita y artefactos propios revisados para operaciones de escritura limitadas a QA:

1. Preparar checkout **detached** con SHA fijo desde GitHub que contenga toda la cadena de PR QA; verificar `git status --porcelain` vacío y equivalencia del SHA, sin cambiar el checkout del piloto.
2. Crear `venv` QA aislado; instalar dependencias fijadas necesarias para migrador desde requisitos verificables, sin cambiar paquetes del piloto.
3. Respaldo QA con metadatos de roles/ACL, copia de DB QA y checksum local protegido; restaurar y auditar en un contenedor efímero diferente. Nunca restaurar sobre piloto/TVC ni sobre QA activa.
4. **Después y por separado**: desarrollar wrapper de migraciones que imponga nombre de contenedor/red/volumen/puerto y *conexión SQL efectiva* QA; sin DSN arbitraria; requiera `CONFIRM_QA_MIGRATIONS=YES`, verifique backup restaurado y abortará ante historial anómalo. Hasta entonces `migrate.py --target dev` está prohibido en VPS.
5. No aplicar `03d_d3b4_cut_identity_dml.sql`, no crear usuarios reales y no incorporar datos del piloto.

## Plan de autorización

- D6A: lectura solamente; el operador puede correr `inspect` con script descargado del SHA y blob exactos aprobados tras CI.
- D6B: los cambios de filesystem, respaldo y prueba de restauración requerirán nuevo artefacto y aprobación de escritura.
- DDL de migraciones: autorización específica futura **posterior** a backup/restauración y revisión de ACL.

**Estado final D6A en GitHub:** hasta recibir salida de la VPS, `OFF03D6A_PREFLIGHT=NOT_RUN`. El PR se conserva Draft y sin merge.
