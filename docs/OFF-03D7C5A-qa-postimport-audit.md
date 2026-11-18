# VINTO — OFF-03D.7C5A: auditoría independiente tras importar referencias a QA

**18-nov-2026 | GitHub Draft | SOLO LECTURA.** No crea ni modifica registros, archivos de configuración, secretos, usuarios, concesiones ni servicios. No repite `apply` ni reabre la autorización D7C5. Tampoco restaura respaldos.

## Evidencia y clasificación del incidente

El operador entregó resultado de Codex en la VPS: `OFF03D7C5_REFERENCE_APPLY=PASS_ONE_QA_TRANSACTION`, `OFF03D7C5_FOUR_QUALITY_VERSIONS=PUBLISHED`, `OFF03D7C5_MACHINE_VERSION_LINKS=8`, `OFF03D7C5_USER_AND_GRANTS=NOT_CREATED`, `OFF03D7C5_IMPORT=PASS_QA_ONLY`. El modo `apply` se ejecutó una sola vez; piloto/TVC no fueron modificados por esas acciones, sin comprobación independiente posterior.

Luego se ejecutó `scripts/off-03d7c5-qa-reference-import-gate.sh inspect`, y falló `OFF03D7C5_BLOCKED: QA_catalog_not_empty_or_changed`. **Es un gate de fuente vacía (PRE-IMPORT) invocado fuera de fase.** Su SQL obliga a tener 0 perfiles, sectores, máquinas, formularios y lotes; un import completado no puede satisfacerlo. **El FAIL posterior no demuestra un fallo de la transacción**. No cambiar el gate histórico ni reintentar `apply`.

El script original D7C5 imprime `OFF03D7C5_IMPORT=PASS_QA_ONLY` **después** del segundo dry-run idempotente y su validación de `CONSISTENT / NO CHANGES` o `NO-OP:`, sin conflicto/drift; ese marcador reportado proporciona evidencia a favor de la idempotencia **al concluir el apply original**. Aun así, se necesita un informe independiente y actualizado de integridad, historial/ACL, catálogo y estabilidad.

## Gate OFF-03D.7C5A

`scripts/off-03d7c5a-qa-postimport-audit.sh`, modo único `audit`:

1. **Auditor histórico post-DDL D6C3:** comprueba el blob del script `ebb773f88ba6740ddf4fef53f1b76de541346a85`, ejecuta solo `audit`, verifica 31 migraciones/checksums, propiedad y ACL, contenedores/servicios piloto/TVC presentes y checkout QA protegido. No depende de base de datos vacía.
2. **Respaldo D7C4:** comprueba blob `6f772a25a9b552d792d7d2215cc5676cca56b5fe`, ejecuta exclusivamente `verify` (SHA256 y coincidencia de huella del respaldo histórico restaurado). **No** usa `inspect`, que exigiría ausencia de catálogo; no restaura, crea ni elimina archivos.
3. **Origen canónico fijo:** exige checkout QA detached, limpio y SHA `7b9eb8c82a290d06e719ee4990c2020076bbd11b`; manifiesto/servicio/importador idénticos a los previamente aprobados, cargados por `load_bundle()` con verificación SHA256 de cada fuente.
4. **QA aislada:** PostgreSQL17 `vinto-qa-postgres`, red `vinto-qa-internal`, `127.0.0.1:6554`; no toca `vinto_piloto`, `vinto-mvp-postgres` ni `postgres-vinto`.
5. **Catálogo ya poblado (SQL READ ONLY):** 31 migraciones; 3 sectores, 5 perfiles, 18 máquinas, 315 artículos, 340 vínculos artículo-máquina, 26 formularios y 26 versiones publicadas; un único import batch `completed` de fuente `vinto-reference-bobinas` y checksum del bundle validado; P1-18 v2, P1-22 v2, P1-26 v3, P1-27 v2 con exactamente ocho asociaciones P1/MP1 y P1/MP3; 0 usuarios/grants.
6. **Idempotencia independiente:** corre `import_reference.py --target dev` **SIN `--apply`**, con rol `vinto_reference`, conexión fija `127.0.0.1:6554/vinto_qa_offline`, secreto QA root:0600 nunca impreso, y `PGOPTIONS='default_transaction_read_only=on'` a nivel libpq para rechazar posibles escrituras. Exige `CONSISTENT / NO CHANGES` o `NO-OP:`, sin `CONFLICT / DRIFT`.
7. Solo muestra marcadores PASS/BLOCKED, nunca filas, claves, contraseñas ni URLs con credenciales. Ante falla: **STOP**, no reintentar ni reparar, no usar `apply`, no restaurar el respaldo.

## Prueba GitHub CI

`.github/workflows/off-03d7c5a-qa-postimport.yml`:

- Job A: sintaxis, modos prohibidos, controles negativos de ausencia de comandos de escritura, identidades QA y presencia de auditor D6C3 + D7C4 verify.
- Job B: PostgreSQL17 efímero **solo GitHub Actions**; reaplica 31 migraciones/ACL a una DB **nueva desechable**, importa el bundle oficial allí una vez (prueba CI heredada D7C2), ejecuta literalmente el mismo SQL de verificación postimport de D7C5A, con fuente checksum real, y comprueba que vuelve PASS. Elimina contenedor temporal y secretos CI. **Ningún acceso a la VPS real**.

**El éxito CI no reemplaza el auditor real de Codex.** No se debe presentar `OFF03D7C5A_AUDIT=PASS_READ_ONLY` hasta obtenerlo desde la VPS.

## Siguiente fase, todavía bloqueada

Una vez recibidos y registrados los marcadores de auditoría independiente PASS, preparar revisión D7C6: rol de identidad QA y ACL efectivos, bloqueo total de operaciones de escritura en API QA, usuario sintético `qa.offline.calidad`, sector `BOBINAS`, cuatro formularios para MP1/MP3, ocho grants, firma Ed25519 exclusiva QA. El perfil CALIDAD también concede `quality.capture` y `quality.release`: **no es solo lectura por sí mismo**. La creación de usuarios, grants, claves y cualquier despliegue requieren autorizaciones nuevas.

**Acceso web QA pendiente:** TLS válido pero aún sin control de acceso externo probado. Mantener `/` y `/api` sin publicar hasta VPN/allowlist autenticada con pruebas negativas desde cliente no autorizado. No fusionar PR Draft a main, ni modificar Nginx/piloto/TVC/servicios.


## Incidencia de ejecución y corrección D7C5A-R1

El primer audit en VPS llegó a OFF03D7C5A_MIGRATIONS_31_CHECKSUMS_ACL=PASS, OFF03D7C5A_PILOT_TVC_STATUS=PASS_AT_AUDIT y OFF03D7C5A_POST_DDL_BACKUP=PASS_FILE_INTEGRITY, pero se detuvo con OFF03D7C5A_BLOCKED: QA_python_missing. No evaluó el catálogo ni la idempotencia. No se modificó PostgreSQL ni se repitió la importación.

**Análisis de código:** el primer ejecutor impuso un control adicional que rechazaba el ejecutable venv/bin/python si era enlace simbólico, una disposición habitual de entornos virtuales Python. El auditor D6C3 **ya ejecutado antes de ese punto** comprobó el mismo intérprete, su identidad sys.prefix, el directorio /srv/vinto-qa-offline/venv y el checkout fijo. La regla adicional era redundante e incompatible. No se conoce por inspección directa si el ejecutable es un symlink en la VPS: no hay evidencia de ausencia real de Python.

**Corrección R1:** exigir que el directorio venv exista y NO sea symlink, que venv/bin/python sea ejecutable (sí puede ser symlink), y conservar la comprobación de identidad del entorno mediante D6C3. CI prueba venv con ejecutable enlazado válido, ejecutable roto y raíz venv enlazada. La corrección solo cambia GitHub; **no instala ni repara Python en la VPS**. Codex deberá descargar el nuevo commit y verificar nuevo blob, bash -n y ejecutar **solo audit** después de que CI final sea PASS. Ante un error distinto: detener sin ensayar reparaciones.
