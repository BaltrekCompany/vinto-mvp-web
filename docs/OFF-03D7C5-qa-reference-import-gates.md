# VINTO OFF-03D.7C5 — importación oficial de referencias en QA, sin acceso público

**18-nov-2026 — GitHub Draft sobre PR #210.** La autorización previa para respaldar en D7C4 **NO autoriza importar catálogos**. Hasta recibir un permiso distinto, Codex solo puede ejecutar `inspect`, que no escribe. No fusionar a `main`, no desplegar Nginx/API/Frontend ni modificar piloto/TVC.

## Evidencia y punto de partida

- Codex informó `OFF03D7C4_BACKUP_RESTORE=PASS_POSTDDL_QA_ONLY`, `OFF03D7C4_RESTORE_TEST=PASS_NETWORKLESS`, `OFF03D7C4_VERIFY=PASS_FILE_INTEGRITY`, `OFF03D7C4_SOURCE_QA_UNCHANGED=PASS`, `NO_QA_DATABASE_WRITES=PASS`. Contenedor restaurador temporal retirado; B2 PRE-DDL intacto. **Es un respaldo físico real de QA restaurado en otro PG17; no es un backup offsite ni de contraseñas de roles.**
- El entorno QA sigue en PostgreSQL 17 `vinto-qa-postgres` con `127.0.0.1:6554/vinto_qa_offline`, 31 migraciones y ACL auditadas. Aún no se han importado referencias en la VPS.
- PR #208 ya probó en GitHub Actions PG17 desechable importación oficial: dry-run, apply de una sola transacción, segundo dry-run idempotente, 4 versiones Calidad **published**, 8 vínculos MP1/MP3, **0 usuarios y grants**. No hizo escritura real en VPS.
- Comparación GitHub con checkout protegido `7b9eb8c82a290d06e719ee4990c2020076bbd11b`: tanto el manifest del bundle (blob `892cabe2acc80e60abf0c52aaf6ff616b84a5bae`) como `backend/import_reference.py` (`26ef9a3b3ce74f9a1df9a47b411758d8ceb1dc24`), `app/seed/reference.py` (`622dadfe7dbd0b77cde36654733cb4eeda97f415`) y `app/seed/bundle.py` (`e50d9842a7e071b754144c04037dc66a39c04bdc`) son idénticos a los del candidato actual. **No modificar el checkout protegido, no hacer git pull ni utilizar main.** El manifest verifica todos los archivos y sus hashes SHA256, tamaños y relaciones internas.

## Nuevo ejecutor

`scripts/off-03d7c5-qa-reference-import-gate.sh`:

| Modo | Operaciones | Permiso necesario |
|---|---|---|
| `inspect` | Solo lectura: verifica el backup POST-DDL y su restauración anterior (`D7C4 verify`), auditoría de migraciones/ACL D6C3, servicios piloto/TVC, checkout+blobs oficiales y rol `vinto_reference` realmente conectado al destino QA; exige catálogos/usuarios/grants aún vacíos; ejecuta dry-run oficial con `PG_PRIVILEGE_MODE=hardened` y entorno sanitizado | Permitido como diagnóstico |
| `apply` | Repite todas las validaciones y el dry-run, exige dos confirmaciones explícitas, ejecuta **una vez** la importación transaccional oficial, verifica batch único completo, cuatro versiones publicadas, ocho vínculos máquina/formulario, sin usuarios ni grants, después realiza otro dry-run de idempotencia | **Requiere autorización posterior específica** |

**Barrera SQL:** destino fijo `127.0.0.1:6554/vinto_qa_offline`; rol dedicado `vinto_reference`, nunca `vinto_qa_bootstrap` para importar, `vinto_migrator` ni `vinto_app`. Contraseña existente en `/etc/vinto-qa/role-reference.password` root:0600, usada solo en entorno de subprocess sin imprimir ni escribir al disco. SQL bootstrap es exclusivamente de metadata y ejecutada con `default_transaction_read_only=on`, no expone nombres/UUID ni contraseñas de usuarios.

**Barrera de recuperación:** `D7C4 verify` comprueba hash de backup POST-DDL y prueba de restauración, pero **no compara con la QA después de importar** (es correcto). `D6C3 audit` sigue verificando 31 migraciones, propietario/ACL y conserva B2 PRE-DDL. **Nunca ejecutar `D7C4 inspect`, `D6B2 verify` ni `D6C1 inspect` después de importar**: asumían base vacía.

**Barrera de idempotencia:** `import_reference.py --target dev` valida el bundle oficial y ejecuta dry-run real en transacción READ ONLY; si detecta cualquier conflicto o drift, la operación termina antes de escribir. La operación `--apply` utiliza la transacción/advisory lock del importador, rollback automático SQL ante conflicto, no rellena por heurísticas ni ejecuta SQL adicional de publicación. Tras importar se comprueba que 4 versiones están `published` y que no hay ningún usuario ni concesión. **El estado published es técnico y no sustituye la homologación industrial.**

## Secuencia operativa y autorizaciones

1. GitHub CI: pruebas negativas del script y rehearse completo del importador con PG17 efímero (2 jobs), sin conectar a VPS.
2. Codex descarga ejecutor D7C5 de commit y Git blob fijados, verifica integridad `git hash-object` + sintaxis `bash -n`, ejecuta **solo** `inspect`; reporta `OFF03D7C5_REFERENCE_DRY_RUN=PASS_READ_ONLY`, `OFF03D7C5_PREFLIGHT=PASS_READ_ONLY`, `OFF03D7C5_IMPORT=NOT_AUTHORIZED`. Ante error: detener sin reparar ni reintentar.
3. Con CI y preflight PASS, **solicitar autorización nueva al operador** para importar exclusivamente el bundle canónico dentro de QA. El permiso D7C4 respaldar/restaurar no lo incluye.
4. Si hay autorización posterior, ejecutar `apply` **una sola vez**, sin modificaciones a catálogos del piloto/TVC; tras éxito, preservar respaldo histórico sin limpieza. Ante fallo, detener sin repetir aplicación, porque puede haber transacciones revertidas o cambios legítimos.
5. Más adelante, un incremento distinto crear **solo usuario sintético Calidad** y concesiones mínimas para MP1/MP3×P1-18/22/26/27, luego firma Ed25519 QA. Los catálogos importados **son referencias versionadas**, no capturas ni datos personales ficticios.

## Riesgo de exposición y condición de cierre

El dominio `qa-vinto-mvp.baltrekservices.com` tiene TLS válido, pero el vhost NO tiene una política de acceso demostrada. **No publicar / ni /api sin VPN o allowlist verificada (deny-by-default) y prueba desde cliente permitido y denegado.** No alterar Nginx ni instalar Node/pnpm durante D7C5. OFF-04 captura/sync/outbox/aprobaciones siguen deshabilitadas.

**Resultado esperado:** `OFF03D7C5_GITHUB=PASS` tras CI, `OFF03D7C5_PREFLIGHT_VPS=PENDING` hasta Codex, `QA_REFERENCE_IMPORT=NOT_AUTHORIZED`, `QA_TEST_USER=NOT_CREATED`, `QA_ACCESS_CONTROL=BLOCKED`. PR Draft sin merge ni deploy.
