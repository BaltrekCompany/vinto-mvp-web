# VINTO MVP WEB — despliegue híbrido aislado en el VPS compartido con TVC

Preparado en CLOUD-DEP-02A (diseño y artefactos, sin ejecutar nada en el VPS). La ejecución real es
CLOUD-DEP-02B, bajo autorización explícita, fase por fase.

## Qué es esto y qué no es

Esta carpeta contiene **plantillas y scripts preparados**, no una instalación. Nada de lo que hay
aquí se ha ejecutado contra el VPS `51.79.65.225`. Ningún archivo contiene una contraseña real.

## Arquitectura (ver CLOUD-DEP-01B para el diseño completo)

- Frontend: vinext en modo standalone (Node.js), systemd, `127.0.0.1:3100`.
- Backend: FastAPI, venv Python 3.12, systemd, `127.0.0.1:8100`.
- PostgreSQL 17 en Docker, exclusivo del MVP, `127.0.0.1:6544` (nunca `0.0.0.0`).
- nginx existente reutilizado con un bloque nuevo (`vinto-mvp.conf`), sin tocar el de TVC.
- Usuario de servicio dedicado `vinto-mvp` (nunca `ubuntu`, que es el que usa TVC).
- Identidades PostgreSQL de CLOUD-01B-2 en modo `hardened`; `vinto_test_admin` nunca se crea aquí.

## Aislamiento de TVC — invariantes que ningún script de esta carpeta debe romper

- Nunca se edita `/etc/nginx/sites-available/vinto-tvc` ni se recarga nginx sin `nginx -t` previo.
- Nunca se nombra, detiene ni reinicia `vinto-web.service`, `postgres-vinto` ni la red `vinto_default`.
- Nunca se usa el rol `vintoadmin` ni ninguna credencial de TVC.
- Nunca se escribe dentro de `/opt/vinto-web` ni de `/home/ubuntu/vinto`.
- El puerto 6543 (PostgreSQL de TVC) nunca se toca ni se reutiliza.

## Orden de archivos para DEP-02B

1. `scripts/preflight.sh` — confirmar que los supuestos siguen siendo ciertos (solo lectura).
2. `env/backend.env.example` → copiar a `/opt/vinto-mvp-web/backend/.env` (600) con contraseñas reales.
3. `env/postgres.env.example` → copiar a `docker/.env` (no versionado) con contraseñas reales.
4. `scripts/deploy.sh` — fase por fase, cada una con `CONFIRM=yes` explícito.
5. `docker/docker-compose.postgres.yml` — lo levanta `deploy.sh postgres-up`.
6. `backend/roles/*.sql` (del repositorio principal, no de esta carpeta) — aplicar en el orden de
   `backend/roles/README.md`, **omitiendo `00b_create_test_admin_role.sql`**.
7. `systemd/*.service` — los instala `deploy.sh systemd-install`.
8. `nginx/vinto-mvp.conf.template` — **paso separado y posterior** (Fase 5 de CLOUD-DEP-02A); no se
   instala en la misma fase que el resto, y requiere autorización propia porque toca el mismo nginx
   que sirve TVC (aunque en un archivo distinto).

## Qué requiere autorización explícita de quien administra el VPS

Cada fase de `deploy.sh` exige `CONFIRM=yes` individualmente. Además, antes de cualquier fase:
confirmar con quien administra TVC que la coexistencia sigue autorizada (decisión pendiente de
CLOUD-DEP-01A/01B), y que el backup de `postgres-vinto` (TVC) existe y está verificado — no porque
este despliegue lo necesite técnicamente, sino como red de seguridad ante cualquier error humano
durante la operación en el mismo host.

## Pruebas que necesitan el VPS y quedan pendientes (ver CLOUD-DEP-02A, Fase 4)

- Arranque real de los dos servicios systemd en Ubuntu 24.04 (solo se validó la sintaxis de las
  unidades localmente, no su ejecución real en ese SO).
- `docker compose up` del Postgres del MVP en el VPS real (localmente solo se validó
  `docker compose config`, ver más abajo).
- Emisión del certificado HTTPS con certbot para el nuevo subdominio.
- Verificación de que el bloque `allow/deny` de nginx bloquea tráfico no autorizado tal como se espera.
