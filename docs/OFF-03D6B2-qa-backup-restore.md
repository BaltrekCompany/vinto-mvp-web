# VINTO OFF-03D.6B2 — Respaldo lógico QA y restauración efímera

**Fecha:** 17-nov-2026. **Estado:** candidato Draft; sin ejecución en VPS, sin DDL en QA real.

## Entrada comprobada

OFF-03D.6B1 fue ejecutado por el operador y verificado independientemente:
`OFF03D6B1_PREPARE=PASS_FILES_ONLY`, `OFF03D6B1_CHECKOUT=PASS_DETACHED_CLEAN`, `OFF03D6B1_CHECKOUT_SHA=7b9eb8c82a290d06e719ee4990c2020076bbd11b`, `OFF03D6B1_VENV=PASS_ISOLATED`, `OFF03D6B1_MIGRATIONS_MANIFEST=31`, `OFF03D6B1_VERIFY=PASS_NO_DDL`, `NO_DATABASE_WRITES=PASS`. Queda `OFF03D6B1_BACKUP=NOT_CREATED`. Resultado documentado en PR #200.

## Alcance exacto

Script `scripts/off-03d6b2-qa-backup-restore.sh`:

- `inspect`: **solo lectura**. Verifica blob de B1 `d398cedb367c151b3bb0a916c1d59f610a441703`, ejecuta B1 verify, imagen PostgreSQL 17, contenedor QA `vinto-qa-postgres`, red `vinto-qa-internal`, bind `127.0.0.1:6554`, carpeta de backup root 0700 y ausencia de backups anteriores OFF03D6B2. No crea ningún archivo/contenedor.
- `backup-restore`: únicamente tras `CONFIRM_QA_BACKUP_RESTORE=YES`. Vuelve a pasar inspect. Crea carpeta privada `/srv/vinto-qa-offline/backups/off03d6b2-XXXXXXXX` (root 0700), exporta **solo QA** con `pg_dumpall --globals-only --no-role-passwords` y `pg_dump --format=custom --create`, más firma de metadatos de roles, ACL y estado de esquema. Las consultas de origen usan `default_transaction_read_only=on`.
- Ensaya los artefactos en un **contenedor postgres:17 efímero**, red Docker `none`, ningún puerto publicado y datos en tmpfs. Los roles se restauran **sin contraseñas originales** (en el contenedor aislado); la base se reconstruye con `pg_restore --create`. Compara una firma SQL de roles/ACL/esquemas de origen y restaurado.
- Calcula SHA-256 de dump, globals y ambas firmas; registra `RESTORE_VERIFIED` solo tras comparación satisfactoria. Elimina exclusivamente el contenedor temporal creado por esta ejecución, nunca QA/piloto/TVC.
- `verify`: verifica hashes, firmas comparadas y que QA original aún coincide con firma previa (solo lectura). **No crea ni restaura nada**.
- Si algo falla, detener: el backup parcial queda para auditoría sin sobrescritura ni limpieza automática del archivo. El contenedor temporal queda programado para destrucción segura; inspeccionar evidencia y script antes de reintentar.

## Limitaciones y prevención de falsa confianza

La restauración prueba **estructura, roles, ACL y base vacía**. **No es un backup físico completo ni incluye contraseñas de roles**, que permanecen únicamente en secretos QA protegidos fuera del respaldo. En una recuperación operativa habría que reprovisionar contraseñas por procedimiento separado. Tampoco incluye servicios, datos futuros, secretos, VPN ni Nginx.

No se ejecutan migraciones, ni `migrate.py`, ni se importan datos de piloto. No se conecta a bases `vinto_piloto`/6544 o TVC/6543. `main` y PR #195-#201 siguen sin merge.

## Gates de cierre

1. GitHub Actions: pruebas negativas y prueba integral PostgreSQL 17 efímero de `pg_dumpall`, dump custom, recreación de roles/ACL/base y sin red.
2. VPS: `SCRIPT_INTEGRITY=PASS` + `OFF03D6B2_PREFLIGHT=PASS_READ_ONLY` (inspección).
3. **Solo tras autorización de escritura limitada a artefactos QA/PG efímero:** `OFF03D6B2_RESTORE_TEST=PASS_NETWORKLESS`, `OFF03D6B2_BACKUP_INTEGRITY=PASS`, `OFF03D6B2_RESTORE_ACL=PASS`, `OFF03D6B2_SOURCE_QA_UNCHANGED=PASS`, `OFF03D6B2_BACKUP_RESTORE=PASS`, `NO_QA_DATABASE_WRITES=PASS`.

Tras los tres pasos, pedir nueva revisión y autorización separada para OFF-03D.6C wrapper de migración segura. No iniciar DDL de QA por efecto de este PR.
