# VINTO MVP WEB — despliegue híbrido aislado en el VPS compartido con TVC

Preparado en CLOUD-DEP-02A (diseño y artefactos, sin ejecutar nada en el VPS); corregido en
CLOUD-DEP-02A.2 tras la auditoría del PR #55 (ver "Correcciones de CLOUD-DEP-02A.2" más abajo) y en
una segunda ronda de correcciones, DEP55-R2-01 a 04 (ver "Correcciones de la ronda 2" más abajo). La
ejecución real es CLOUD-DEP-02B, bajo autorización explícita, fase por fase.

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

## Versionado por "releases" (CLOUD-DEP-02A.2, DEP55-04)

`deploy.sh` nunca despliega directamente sobre un único directorio mutable: cada `checkout`
clona el commit exacto en `releases/<sha-completo>/`, nunca sobrescribe un release existente, y
`activate` conmuta atómicamente el symlink `current` solo cuando ese release ya tiene venv y build
completos. Esto permite revertir una versión (`rollback.sh version <sha-anterior>`) sin tocar git
ni PostgreSQL, y conserva siempre la referencia a la versión anterior.

```
/opt/vinto-mvp-web/
  shared/backend.env        <- el .env real, con contraseñas, fuera de cualquier release
  releases/<sha>/           <- un checkout + venv + build completo por versión desplegada
  current -> releases/<sha> <- symlink activo; lo referencian los units de systemd
```

## Orden de archivos y fases para DEP-02B

1. `scripts/preflight.sh infra` — confirmar que los supuestos de infraestructura/coexistencia
   siguen siendo ciertos (solo lectura; DEP55-R2-02: ya no mezcla dependencias de build).
2. `env/backend.env.example` → copiar a `/opt/vinto-mvp-web/shared/backend.env` (600) con
   contraseñas reales. `deploy.sh checkout` enlaza automáticamente `releases/<sha>/backend/.env`
   a este archivo compartido; nunca se duplica por versión.
3. `env/postgres.env.example` → copiar a `docker/.env` (no versionado) con contraseñas reales.
4. `scripts/deploy.sh` — fase por fase, cada una con `CONFIRM=yes` explícito, en este orden:
   `user-and-dirs` → `preflight-build-deps` (repetir: ahora ya existe el usuario de servicio, se
   puede confirmar la ruta real de node/corepack PARA ÉL) → `checkout <sha>` (requiere además
   `AUTHORIZED_COMMIT=<sha>`) → `python-venv <sha>` → `frontend-build <sha>` →
   `preflight-startup` → `activate <sha>` →
   `postgres-up` (requiere además `TVC_BACKUP_CONFIRMED=yes`) → `postgres-bootstrap-db` →
   `postgres-roles` → `migrate` → `postgres-grants` → `import-reference` (dry-run) →
   `import-reference-apply` → `systemd-install` → `healthcheck`.
5. `docker/docker-compose.postgres.yml` — lo levanta `deploy.sh postgres-up`.
6. `backend/roles/*.sql` (del repositorio principal, no de esta carpeta) — los ejecuta
   `deploy.sh postgres-roles`/`postgres-grants` en el orden de `backend/roles/README.md`,
   **omitiendo `00b_create_test_admin_role.sql`**.
7. `systemd/*.service` — los instala `deploy.sh systemd-install`; referencian `current/`, nunca
   una ruta de release fija.
8. `nginx/vinto-mvp.conf.template` — **paso separado y posterior** (Fase 5 de CLOUD-DEP-02A); no se
   instala en la misma fase que el resto, y requiere autorización propia porque toca el mismo nginx
   que sirve TVC (aunque en un archivo distinto). Requiere completar `__ALLOWED_CIDR__` con una
   IP/rango real: la plantilla deniega todo el tráfico por defecto (DEP55-05) hasta que se edite.

## Qué requiere autorización explícita de quien administra el VPS

Cada fase de `deploy.sh` exige `CONFIRM=yes` individualmente. Además, antes de cualquier fase:
confirmar con quien administra TVC que la coexistencia sigue autorizada (decisión pendiente de
CLOUD-DEP-01A/01B), y que el backup de `postgres-vinto` (TVC) existe y está verificado — no porque
este despliegue lo necesite técnicamente, sino como red de seguridad ante cualquier error humano
durante la operación en el mismo host.

## Pruebas que necesitan el VPS y quedan pendientes (ver CLOUD-DEP-02A, Fase 4)

- Arranque real de los dos servicios systemd en Ubuntu 24.04. `verify_local.sh` (CLOUD-DEP-02A.2-R2)
  ensaya en un contenedor Ubuntu 24.04 efímero la propiedad de directorios, la resolución de
  symlinks hacia `shared/backend.env` y la activación atómica entre releases como el usuario
  `vinto-mvp`, pero un contenedor normal no corre systemd como PID 1: `systemctl`
  start/restart/enable, la política `Restart=on-failure` y el sandboxing de `ProtectSystem=strict`
  siguen sin ejercitarse realmente — solo su sintaxis se validó localmente.
- `docker compose up` del Postgres del MVP en el VPS real (localmente solo se validó
  `docker compose config`, ver más abajo).
- Emisión del certificado HTTPS con certbot para el nuevo subdominio.
- Verificación de que el bloque `allow/deny` de nginx bloquea tráfico no autorizado tal como se espera
  (localmente sí se verificó con un contenedor `nginx:alpine` real, con tráfico HTTP real).

## Correcciones de la ronda 2 (CLOUD-DEP-02A.2-R2, auditoría del PR #55, DEP55-R2-01 a 04)

Segunda auditoría de ChatGPT sobre el commit correctivo de la ronda 1 ("arquitectura y correcciones
DEP55-01 a 05 favorables", 4 observaciones nuevas, ninguna de arquitectura):

- **DEP55-R2-01 (`scripts/tests/verify_local.sh`, seguridad del runner)**: eliminado cualquier
  `docker rm -f <nombre fijo>` preventivo al empezar una prueba. Cada contenedor que el runner crea
  usa un nombre único por ejecución, comprueba que no colisiona con nada preexistente antes de
  crearlo, se registra por su ID real (confirmado con `docker inspect`, nunca por el nombre pedido)
  y se limpia exclusivamente por ese ID — incluso ante un error o una interrupción del propio
  runner (`trap cleanup_all EXIT INT TERM` sobre la lista de IDs registrados).
- **DEP55-R2-02 (`scripts/preflight.sh`, preflight por etapas)**: dividido en 3 etapas
  independientes — `infra` (puertos, rutas, identidad de recursos, TVC, backup; nunca depende de
  node/python/git/corepack), `build-deps` (dependencias de compilación, y confirma la ruta real de
  node/corepack **para el usuario de servicio**, comparándola con la que asumen los units de
  systemd) y `startup` (justo antes de activar/arrancar). Antes, una dependencia de build ausente
  podía bloquear un chequeo de infraestructura que no la necesitaba para nada.
- **DEP55-R2-03 (`scripts/lib_common.sh`, archivos temporales de credenciales)**: el `.pgpass`
  temporal dentro del contenedor y el `--env-file` en el host ahora usan una ruta única por llamada
  (PID + aleatorio + nanosegundos), nunca un nombre fijo — dos invocaciones concurrentes no pueden
  pisarse. La limpieza usa `trap ... EXIT INT TERM` con la ruta exacta ya resuelta, y el comando
  bloqueante (`docker exec ... psql`) se lanza en segundo plano y se espera con el builtin `wait`
  (no directamente en primer plano): así, una señal con trap se atiende de inmediato en vez de
  diferirse hasta que el comando en curso termine por sí solo. `password_from_pg_url` decodifica
  porcentaje (RFC 3986), para contraseñas con `@`/`:`/`+` codificados dentro de la URL.
- **DEP55-R2-04 (`deploy.sh`, `rollback.sh`, releases/rollback)**: `deploy.sh activate` ahora
  reinicia los servicios (si ya estaban instalados), comprueba el healthcheck y, si falla, revierte
  automáticamente `current` a la versión anterior y reinicia de nuevo — en vez de dejar el sistema
  a medio camino. Ensayado en un contenedor Ubuntu 24.04 efímero (propiedad, symlinks, activación
  atómica, aislamiento de `/opt/vinto-web`, `su`/git/python3 como el usuario de servicio) con la
  limitación explícita de que ese ensayo NO ejercita systemd en sí (ver arriba). Documentado que un
  rollback de código (`rollback.sh version`) nunca implica deshacer una migración de base de datos:
  son operaciones independientes.

## Correcciones de CLOUD-DEP-02A.2 (auditoría del PR #55, DEP55-01 a 05)

ChatGPT auditó directamente los 10 archivos publicados en el PR #55 y dio "arquitectura aprobada,
NO-GO para ejecutar scripts en el VPS" hasta corregir 5 observaciones. Resumen de lo corregido
(detalle completo en los propios archivos y en el mensaje del commit correctivo):

- **DEP55-01 (`rollback.sh`)**: eliminado por completo cualquier `rm -rf` de datos de PostgreSQL
  del flujo ordinario — **ningún subcomando de `rollback.sh` puede destruir datos**, bajo ninguna
  variable de entorno. Eliminado el `source` de `.env`; los valores se leen como texto
  (`lib_common.sh::env_value`). Añadida verificación de identidad antes de detener o eliminar
  cualquier unidad systemd o contenedor (`assert_unit_is_ours`/`assert_container_is_ours`). Añadido
  el subcomando `version` para revertir código sin tocar PostgreSQL ni git.
- **Destrucción deliberada de datos (fuera de alcance de este PR)**: si alguna vez se necesita
  borrar el bind-mount de datos de PostgreSQL del MVP (p. ej. para reinstalar desde cero), es un
  procedimiento manual, separado, documentado y autorizado aparte — nunca una opción de
  `rollback.sh`. No existe en este repositorio ningún script para esa operación.
- **DEP55-02 (aprovisionamiento)**: añadidas las fases que faltaban en el ciclo completo
  (`postgres-bootstrap-db` para crear `vinto_piloto`, `postgres-grants` para 02-06,
  `import-reference`/`import-reference-apply`, ausentes en la versión original de `deploy.sh`).
  Las operaciones administrativas (rol de arranque) quedan separadas de las identidades de
  aplicación (`vinto_app`/`vinto_migrator`/`vinto_reference`) en todas las fases nuevas.
- **DEP55-03 (`preflight.sh`)**: los conflictos de propiedad desconocida (ruta, contenedor, red,
  usuario que ya existen pero no se pueden confirmar como del MVP) ahora son `FALLA` y detienen el
  procedimiento, no solo un `AVISO`. Añadidos controles de red Docker, bind-mount potencialmente
  compartido, dependencias ausentes y evidencia de backup de TVC antes de autorizar fases de
  riesgo. Añadida una clasificación explícita primera-instalación vs. actualización.
- **DEP55-04 (`deploy.sh checkout`)**: solo acepta un SHA completo de 40 caracteres (nunca una
  rama/tag); exige `AUTHORIZED_COMMIT=<sha>` idéntico al commit pedido; verifica el `origin`
  clonado contra `REPO_URL`; nunca sobrescribe un release existente; nunca ejecuta `reset --hard`
  ni `clean -f` (cada release es un clon nuevo en un directorio vacío). Ver "Versionado por
  releases" arriba para cómo se conserva la versión anterior y se preparan versiones separadas.
- **DEP55-05 (`nginx/vinto-mvp.conf.template`)**: el bloque de restricción de acceso ahora
  **deniega por defecto** (`deny all` activo, con un `allow __ALLOWED_CIDR__` que debe completarse
  con un valor real antes de instalar) — antes estaba comentado y el piloto quedaba abierto si se
  instalaba sin editar. Documentado explícitamente que HTTP plano nunca es el medio de acceso de
  usuarios reales y que los cookies `Secure` de la API no se transmiten sobre HTTP.
