# VINTO OFF-03D.7C3 — Gate READ ONLY para respaldo QA posterior a las 31 migraciones

**18-nov-2026 — PR Draft, SIN autorización de backup.** Este gate se ejecuta únicamente con `inspect` en la VPS, después del D7C PASS y antes de una eventual importación de catálogos. No crea archivos ni contenedores, no dumpea ni restaura; es una comprobación de que **podremos** construir un respaldo QA de la fase POST-DDL bajo controles separados.

## Dependencias

1. QA `vinto-qa-postgres` PostgreSQL17 en `127.0.0.1:6554`, 31 migraciones, ACL PASS, piloto/TVC activos.
2. Auditor POST-DDL D6C3 original en `/tmp/vinto-off03d6c3-qa-postmigration-audit.sh`, Git blob **`ebb773f88ba6740ddf4fef53f1b76de541346a85`**, vigente, sin rutas cambiadas y con `OFF03D6C3_AUDIT=PASS_READ_ONLY`. Este auditor valida el respaldo B2 PRE-DDL como evidencia histórica, pero **NO compara ese snapshot con la base actual migrada**, evitando falso bloqueo.
3. Directorio privado de respaldos `/srv/vinto-qa-offline/backups` root:0700. Exactamente un respaldo histórico `off03d6b2-*`, ningún respaldo `off03d7c3-*` previo, sin enlaces simbólicos.
4. Herramientas PG17 `pg_dump`, `pg_dumpall`, `pg_restore` disponibles en el contenedor QA, imagen PG17 local apta para futura restauración efímera sin red, y al menos 2GiB libres.
5. Consulta SQL con `default_transaction_read_only=on`: DB QA exacta, 31 migraciones, 0 usuarios, 0 concesiones, 0 versiones y 0 lotes importados. Si cualquier contador cambió después de D7C: **BLOCKED**, revisar y diseñar respaldo específico, no borrar/normalizar datos.

## Qué significa PASS

`OFF03D7C3_PREFLIGHT=PASS_READ_ONLY` indica que el entorno reúne requisitos para desarrollar posteriormente una operación **autorizada** de backup y restauración probada. **No significa que exista un nuevo backup POST-DDL** ni que esté protegido contra fallos de VPS: ambos aspectos deberán demostrarse en un gate posterior con evidencia de hashes, recuperación de esquemas/tablas y ACL.

## Diseño futuro de backup RESTORE (NO ejecutable por este PR)

Bajo una aprobación de escritura de archivos de respaldo y contenedor efímero independiente:

- Validar de nuevo origen, puerto y roles. Capturar dump custom `pg_dump` y globals `pg_dumpall --globals-only --no-role-passwords`, con modo root:0600 dentro de carpeta root:0700 que NO sea B2. Evitar guardar contraseñas; usar rol QA bootstrap dentro del contenedor.
- Restaurar en PostgreSQL17 efímero con `--network none`, sin puertos publicados, volumen tmpfs y tamaño compatible con el dump, sin tocar el contenedor QA.
- Comparar SHA256, esquema, migraciones y ACL de fuente/restauración; usar un manifiesto inequívoco del **estado POST-DDL** para no confundir con B2 PRE-DDL. Preservar pruebas de restauración. Fallar cerrado y detener ante cualquier discrepancia.
- Solo tras `BACKUP_POST_DDL=PASS_RESTORED_NETWORKLESS` aprobar, por separado, importar el bundle oficial de referencia: ensayo GitHub CI #44328721030 PASS demuestra que la importación completa termina con cuatro formularios `published`, 8 vínculos MP1/MP3, sin usuarios ni concesiones. **No copiar datos industriales/usuarios reales**.
- La importación real del bundle en QA debe usar checkout/manifest SHA pin, rol `vinto_reference`, `PG_PRIVILEGE_MODE=hardened`, destino fijo `127.0.0.1:6554/vinto_qa_offline`, dry-run primero, después apply solo con autorización independiente. Después usuario sintético/grants/Ed25519 cada cual con gate propio.
- Nginx QA aún sin control de acceso verificado: **no** abrir / y /api públicos ni desplegar web/API hasta completar VPN o allowlist fail-closed con pruebas positivo/negativo y rollback.

## Uso operativo

Script `scripts/off-03d7c3-qa-postddl-backup-preflight.sh` solo acepta `inspect`; descargar desde commit SHA completo y verificar blob Git exacto + `bash -n` en la VPS antes de ejecución con `sudo -n bash`. Ante error, NO recrear backups, modificar permisos, limpiar carpetas, reiniciar contenedores ni forzar reintentos: reportar `OFF03D7C3_BLOCKED` para revisión.

**No ejecutar `off-03d6b2 verify` ni `off-03d6c1 inspect` tras el DDL:** esos gates requieren esquema vacío y marcarían falso bloqueo. Tampoco volver a ejecutar las 31 migraciones.
