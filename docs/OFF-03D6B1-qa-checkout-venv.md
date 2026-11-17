# VINTO OFF-03D.6B1 - Checkout y venv QA aislados

**Fecha:** 17-nov-2026. **Estado:** candidato Draft, pendiente de CI y ejecución VPS. **Sin DDL, sin respaldo y sin cambios en piloto/TVC.**

## Entrada real

El operador ejecutó OFF-03D.6A inspect con SCRIPT_INTEGRITY=PASS, OFF03D6A_D5_GATE=PASS, OFF03D6A_PATHS_AVAILABLE=PASS, OFF03D6A_PYTHON_VENV_CAPABLE=PASS, OFF03D6A_BACKUP_TOOLS=PASS, OFF03D6A_FREE_DISK_2GIB=PASS, OFF03D6A_PREFLIGHT=PASS_READ_ONLY, NO_DATABASE_WRITES=PASS. DB QA 7,689,907 bytes; sin tablas de aplicación ni migraciones. CI D6A run 44177339046: success.

## Operaciones del script D6B1

Archivo: scripts/off-03d6b1-qa-checkout-venv.sh (descargar por commit exacto y verificar blob Git).

1. **inspect:** solamente lectura. Exige D5 blob f296b71930a8820abea8666fb1aac01a16ede9e6 y D6A blob b52d2b2f5b9615b279163a9bfc1519b6331a94c4; ejecuta sus gates. Rechaza rutas ya ocupadas.
2. **prepare:** exige CONFIRM_QA_STAGE=YES y inspect PASS. Crea solo archivos bajo /srv/vinto-qa-offline con root 0700. source es clon aislado GitHub detached y validado al SHA 7b9eb8c82a290d06e719ee4990c2020076bbd11b, probado por D6A. venv es entorno exclusivo con psycopg[binary]==3.3.6 y pydantic-settings==2.15.0, incluyendo las dependencias que pip resuelva. backups es directorio root 0700 vacío, sin dumps ni secretos.
3. **verify:** inspección posterior repetible. Valida D5, directorio root 0700, origen remoto Git, SHA HEAD, detached y árbol limpio, imports Python, 31 migraciones consecutivas y directorio backups root 0700.

## Prohibiciones

- No usar migrate.py, pg_dump, pg_restore ni scripts SQL desde D6B1.
- No copiar .env ni credenciales del piloto; no iniciar backend/frontend QA todavía.
- No tocar /opt/vinto-mvp-web, /home/ubuntu/vinto, /home/ubuntu/vinto-mvp-build ni las bases del piloto/TVC (puertos 6544 y 6543).
- No fusionar PR #195-#200 con main.
- Ante fallo de git clone, checkout, venv o pip, detener, sin limpieza automática ni reintentos sobre árboles parciales.

## Salida prevista

OFF03D6B1_CHECKOUT=PASS_DETACHED_CLEAN, OFF03D6B1_MIGRATIONS_MANIFEST=31, OFF03D6B1_VENV=PASS_ISOLATED, OFF03D6B1_BACKUP=NOT_CREATED, OFF03D6B1_MIGRATIONS=NOT_STARTED, OFF03D6B1_VERIFY=PASS_NO_DDL, OFF03D6B1_PREPARE=PASS_FILES_ONLY, NO_DATABASE_WRITES=PASS.

## Fase posterior (NO incluida)

OFF-03D.6B2: backup QA, roles/ACL protegidos, hashes y ensayo de restauración aislada sin red. OFF-03D.6C migraciones QA solo después de demostrar restaurabilidad, wrapper de destino y autorización específica. Ninguno de esos pasos está autorizado por este PR.
