# VINTO OFF-03D.3 — Puerta de roles y 31 migraciones en PostgreSQL QA

**Fecha:** 17-nov-2026. **Estado:** CANDIDATO / PR Draft. **No autorizado para ejecutar DDL.**

## Estado recibido de VPS

OFF-03D.2 completado por el operador con SHA pinneado y verificaciones independientes:
- `SCRIPT_INTEGRITY=PASS`, `OFF03D2_INSTALL=PASS_BOOTSTRAP_ONLY`, `OFF03D2_VERIFY=PASS_BOOTSTRAP_ONLY`.
- Contenedor exclusivo `vinto-qa-postgres`, base `vinto_qa_offline`, `127.0.0.1:6554`.
- Red `vinto-qa-internal`, volumen `vinto-qa-offline-pgdata`, superusuario bootstrap `vinto_qa_bootstrap`, archivo de contraseña 0600 de root.
- En esta etapa NO hay roles aplicativos, migraciones, cuentas, identidades, capturas, frontend o backend QA.
- El piloto sigue en `vinto_piloto`, port `6544`, con frontend `3100` y backend `8100`; TVC usa `postgres-vinto` puerto `6543`. Ninguno debe tocarse.

## Fase A (única ejecutable de este PR): preflight **READ ONLY**

Fijar y verificar el SHA completo del script publicado para OFF-03D.3 antes de usarlo. Nunca ejecutar un script de una rama mutable sin comparar hash o commit. Desde copia descargada de commit exacto:

```bash
bash -n scripts/off-03d3-qa-schema-preflight.sh
sudo bash scripts/off-03d3-qa-schema-preflight.sh inspect
```

Criterio: `OFF03D3_PREFLIGHT=PASS_READ_ONLY`, `QA_SCHEMA_EMPTY=PASS`, `QA_APPLICATION_ROLES_ABSENT=PASS`, `QA_MIGRATION_HISTORY_ABSENT=PASS`, `QA_CONTAINER_ISOLATION=PASS`, `QA_SECRET_PERMISSIONS=PASS`, `PILOT_TVC_RUNNING=PASS`. Si cualquiera bloquea, no ejecutar SQL ni regenerar el volumen/contraseña. El script consulta metadatos dentro de QA con `PGOPTIONS` de transacción de solo lectura y NO imprime secretos. Exige que la base todavía no haya sido migrada: no usar después de completar la fase B.

## Fase B propuesta (pendiente de autorización y tooling propio)

**No utilizar directamente el despliegue del piloto `deploy/mvp/scripts/deploy.sh`.** Es específico de sus rutas y puertos. Proveer instalador QA independiente o comandos pinneados y revisados.

1. Checkout independiente en directorio nuevo y de propiedad restringida, basado en commit completo de la cadena PR #184–#196; verificar `git rev-parse HEAD` antes de hacer nada. No usar `main` ni el release operativo `/opt/vinto-mvp-web/current`.
2. Respaldar/verificar base bootstrap VACÍA de QA antes de DDL; la copia/restore no puede apuntar a `6544` ni `6543`. Mantener el secreto bootstrap separado y sin imprimirlo.
3. Generar contraseñas nuevas y distintas para `vinto_app`, `vinto_migrator`, `vinto_reference` y opcionalmente `vinto_identity`, en archivos root 0600 fuera del checkout. Nunca reutilizar roles ni contraseñas del piloto o TVC.
4. Ejecutar `backend/roles/00_create_roles.sql` usando el administrador **del contenedor QA**, con `APP_PASSWORD`, `MIGRATOR_PASSWORD` y `REFERENCE_PASSWORD` transmitidas sin eco y no como argumentos visibles. Ejecutar `01_database_grants.sql` con `DBNAME=vinto_qa_offline`. No ejecutar `00b_create_test_admin_role.sql` por defecto: el test físico no necesita capacidad CREATEDB.
5. Ejecutar `backend/migrate.py --target dev` *solamente* desde un Python/venv exclusivos QA con `APP_ENV=qa`, `PG_PRIVILEGE_MODE=hardened` y `MIGRATOR_DATABASE_URL` al rol migrador de `127.0.0.1:6554/vinto_qa_offline`. La bandera `--target dev` es nomenclatura del ejecutor: **no implica** base de desarrollo. Esta operación exige guarda adicional que consulte `current_database()` y `inet_server_port()` antes de aplicar DDL; el ejecutor genérico NO comprueba que la base sea QA. No usar `--target test`, que exige sufijo `_test`.
6. Verificar las **31 migraciones exactas (0001–0031)** y sus checksums con `migrate.py --check` sobre QA. Si alguna falla, detenerse; la herramienta aplica una transacción por migración y no revierte las anteriores. NO hacer reset de datos, `DROP DATABASE` ni reejecutar sin diagnosticar.
7. Desde rol migrador QA aplicar privilegios iniciales `02_schema_grants.sql`, `03_table_grants.sql`, **inmediatamente `03b_d3b1_restrict_catalog_writes.sql`**, `04_function_grants.sql`, `05_no_default_privileges.sql`, `06_public_and_meta_protection.sql`. Revisar primero interacción con GRANTs aditivos incluidos en las migraciones 0007 y 0028; no reejecutar `03` sola, porque revertiría el hardening `03b`.
8. El rol `vinto_identity` (archivos `00c` y `03c`) es una decisión de alcance; **NO ejecutar `03d_d3b4_cut_identity_dml.sql`** sin aprobación independiente. El nuevo QA puede elegir política más restrictiva, pero debe probar el contrato de autenticación de FastAPI con el rol separado antes de habilitar servicios.
9. Consultar `07_verification_queries.sql` y `08_release_preflight.sql` read-only. Verificar que la API solamente pueda `SELECT` catálogos y conceder exactamente lo necesario para definir paquetes Calidad por máquina; no atribuir permisos de tablas nuevas por inferencia.

## Fase C (separada: referencias y operador sintético)

El bundle oficial `backend/seed_data` contiene catálogos, máquinas y definiciones; su importación no crea el operador ficticio ni los grants efectivos. **No mezclar con usuarios/capturas del piloto**. Revisar el manifest oficial antes de importarlo a QA y validar que existen definiciones publicadas compatibles para `VINTO-P1-18/22/26/27` sobre `MP1` y `MP3`. P1-26 se visualiza de forma solo lectura, con regla calculada. Crear cuenta ficticia Calidad/grants exclusivamente QA mediante un proceso autorizado, sin imprimir contraseñas.

## Fase D (posterior: backend/frontend)

Servicios propios `127.0.0.1:8110` y `127.0.0.1:3110`, configuración HTTPS mismo origen `qa-vinto-mvp.baltrekservices.com`, `NEXT_PUBLIC_API_URL` **en build time**, cookies `Secure/HttpOnly`, firma Ed25519 exclusiva QA. Flags `OFFLINE_SCOPE_ISSUE_ENABLED` y `OFFLINE_QUALITY_PACKAGE_ISSUE_ENABLED` solo QA; NO capturas offline ni outbox. Cabeceras `X-Forwarded-Proto` confiadas únicamente desde proxy local (no `*`), y revisar reglas de acceso de red del teléfono.

## Riesgos que obligan a frenar

- Un script de roles o migraciones apuntando a `vinto_piloto`, puerto `6544` o clúster TVC `6543`.
- SHA no pinneado, secretos en stdout, login con usuarios reales, ejecutar scripts que creen `vinto_test_admin` o habilitar `03d` sin aprobación.
- Reciclar `vinto-mvp` o reiniciar sus servicios.
- Migraciones no consecutivas, permisos faltantes o `OFF03D3_PREFLIGHT` diferente de PASS.

**Estado:** `OFF03D2_INSTALL=PASS_BOOTSTRAP_ONLY`; `OFF03D3_PREFLIGHT=NOT_RUN`; `QA_SCHEMA_APPLY=NOT_AUTHORIZED`; `MOBILE_PHYSICAL_QA=NOT_RUN`.