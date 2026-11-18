# VINTO OFF-03D.7C2 — Ensayo aislado del catálogo oficial y plan de importación QA

**Estado al 18-nov-2026:** GitHub-only, candidato Draft; **NO autorizado importar, publicar formularios, crear usuarios, activar flags o acceder por red a QA**. Base: PR #207 D7C con `OFF03D7C_REFERENCE_BASELINE=EMPTY_QA_ONLY` e historial de 31 migraciones (informe Codex), sin ninguna escritura. Este PR se apila sobre #207, NO sobre main.

## Qué demuestra la CI

`scripts/off-03d7c2-reference-import-ci-e2e.sh` reutiliza el procedimiento aprobado de **31 migraciones + ACL** en un contenedor PostgreSQL 17 nuevo de GitHub Actions, ligado exclusivamente a `127.0.0.1` con puerto efímero. El runner genera credenciales temporales, no usa archivos de claves de la VPS ni accede a 51.79.65.225. La rutina elimina el contenedor y el directorio temporal al terminar, aun con error.

Tras las 31 migraciones y ACL, en ese contenedor **desechable**:

1. Verifica `backend/seed_data` mediante `app.seed.bundle.load_bundle` y `qa_offline_fixture_contract`, con fuente y versiones fijadas: P1-18 v2, P1-22 v2, P1-26 v3 y P1-27 v2, todas MP1/MP3 y perfil Calidad.
2. Ejecuta `import_reference.py --target dev` **dry-run** como `vinto_reference`, `PG_PRIVILEGE_MODE=hardened` y DB `vinto_qa_offline` del **runner**, sin conflictos.
3. Ejecuta **una sola vez** el `--apply` del mismo bundle oficial dentro del contenedor descartable. Este es el único punto de escritura, **jamás en VPS**. Comprueba un lote de importación completado.
4. Ejecuta un segundo dry-run y exige idempotencia (NO-OP o CONSISTENT).
5. Consulta solamente metadatos de esa instancia desechable: 31 migraciones, cuatro versiones de Calidad en estado `draft`, ocho vínculos versión-máquina, ningún usuario ni concesión. Esto demuestra que `--apply` **no publica** automáticamente las versiones ni crea la identidad de prueba.

Se imprime únicamente PASS/BLOCKED, no contraseñas. Si falla, **NO liberar un importador para la VPS**; corregir el contrato de GitHub primero.

## Fuente de verdad y diferencia crítica

El bundle `backend/seed_data` es referencia versionada con checksum del repositorio; incluye catálogos/homologaciones técnicas del proyecto y **no debe presentarse como una copia de producción ni íntegramente sintético**. Es distinto del usuario de prueba futuro `qa.offline.calidad`, que sí debe ser sintético.

El importador crea nuevas versiones como `draft`. P1-18/22/26/27 no se consideran **publicadas** hasta revisar definición/campos y ejecutar por mecanismo autorizado una publicación independiente sobre QA. El perfil `CALIDAD` + sector `BOBINAS` NO concede automáticamente los ocho pares MP1/MP3 × esos cuatro formularios; requieren grants explícitos y verificación del motor de autorización. Para evitar despliegues que parezcan correctos pero no entreguen sobres, esas dependencias se mantienen visibles.

## Plan de escritura futura QA (no ejecutar en este PR)

**Gate previo adicional: respaldo POST-DDL, no B2 PRE-DDL.** La copia B2 es anterior a las 31 migraciones y se conserva intacta como evidencia histórica. Antes de incorporar catálogos se requiere nuevo snapshot de `vinto_qa_offline` ya migrada con PG17, roles/ACL y checksums, modo 0600/0700, restauración probada en contenedor efímero sin red, origen QA 6554 fijo y evidencia del operador. Es una fase separada y debe tener autorización expresa.

**Gate de acceso:** Nginx del dominio `qa-vinto-mvp.baltrekservices.com` tiene TLS válido, pero no se ha comprobado ninguna restricción de acceso real. No levantar `/` ni `/api/` públicos ni habilitar flags hasta aprobar VPN o allowlist con denegación predeterminada y verificar desde un cliente autorizado y otro no autorizado. HTTPS + 404 no es control de acceso. No cambiar vhosts de piloto/TVC.

**Secuencia controlada posterior, con autorización nueva en cada operación que cambie QA:**

1. Respaldar la DB QA **POST-DDL** (31 migraciones) y validar restauración en PG17 efímero. Confirmar no hay catálogos y comprobar checksum exacto de `backend/seed_data` en checkout candidato inmutable distinto al checkout histórico `/srv/vinto-qa-offline/source`.
2. Instalar o preparar checkout QA de importación de solo uso en ubicación nueva y protegida, sin tocar deployment activo ni `main`. Cualquier instalación/copias en la VPS requieren su propia autorización.
3. Ejecutar dry-run `import_reference.py --target dev` como rol `vinto_reference`, URL fijada explícitamente a `127.0.0.1:6554/vinto_qa_offline`, sin fallback a otra DB, validar historial=31, hashes, red y permisos efectivos. El dry-run devuelve plan y estado; no debe imprimir datos del piloto ni secretos.
4. Con un plan aprobado y nueva autorización, aplicar **solo** el bundle oficial mediante importador blindado, sin CLI directa desde consola sin controles de DB/rol. Verificar lotes/conteos/integridad y que las versiones recién creadas siguen `draft`.
5. Revisar técnicamente la fuente de las cuatro definiciones y sus versiones; crear procedimiento de publicación exacto sobre QA con checksums y verificación de área/máquina, independiente de importación. **No se ha localizado ni validado aún un CLI de publicación de versión apropiado para el release**: no improvisar `UPDATE status='published'`.
6. Posteriormente, crear exactamente un usuario de prueba `qa.offline.calidad`, hash Argon2id, sector `BOBINAS`, grants exactos de MP1/MP3 y las cuatro versiones aprobadas, con revocación/rollback individual. No usar usuarios reales. Solo después habilitar la firma Ed25519 QA (secreto de 32 bytes exclusivamente QA) y los flags de emisión de paquetes, para pruebas de **solo lectura** M01–M11/N01–N06.
7. QA web/API y su control de acceso necesitan el gate de instalación propio D7D; Node20, servicios piloto/TVC y main quedan inalterados.

**Reversión:** después de importar catálogos, no borrar manualmente tablas ni restaurar B2 PRE-DDL. Un rollback de importación completa requerirá el respaldo **POST-DDL** previamente verificado y una decisión explícita, con bloqueo de escrituras, ventana de mantenimiento y evaluación de cambios posteriores. No programar rollback automático.

## Decisión actual

- `OFF03D7C_VPS_PREFLIGHT=PASS_READ_ONLY` (informado por Codex)
- `OFF03D7C2_CI_IMPORT=PENDING` hasta CI final
- `QA_POST_DDL_BACKUP=PENDING`
- `QA_REFERENCE_IMPORT=NOT_AUTHORIZED`
- `QA_FORM_PUBLISH=NOT_AUTHORIZED`
- `QA_TEST_USER=NOT_CREATED`
- `QA_SIGNER=NOT_CONFIGURED`
- `QA_ACCESS_CONTROL=BLOCKED`
- `QA_WEB=NOT_DEPLOYED`

Este PR no trae comandos de ejecución sobre la VPS. No confundir éxito de la CI efímera con autorización de escritura real. Mantener Draft, sin merge a `main`.
