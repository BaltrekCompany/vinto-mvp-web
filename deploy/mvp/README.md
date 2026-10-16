# VINTO MVP WEB — despliegue híbrido aislado en el VPS compartido con TVC

Preparado en CLOUD-DEP-02A (diseño y artefactos, sin ejecutar nada en el VPS); corregido en
CLOUD-DEP-02A.2 tras la auditoría del PR #55 (ver "Correcciones de CLOUD-DEP-02A.2" más abajo), en
una segunda ronda de correcciones, DEP55-R2-01 a 04 (ver "Correcciones de la ronda 2" más abajo), y
en un cierre focalizado, CLOUD-DEP-02A.4 (ver "Cierre focalizado" más abajo). La ejecución real es
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
   `user-and-dirs` → `preflight-build-deps` → `install-node-runtime <version> <tarball>`
   (checksum verificado contra `env/node-runtime-checksums.txt`, versionado — ver más abajo) →
   `checkout <sha>` (requiere además `AUTHORIZED_COMMIT=<sha>`) →
   `python-venv <sha>` → `install-frontend-artifact <sha> <tar.gz> <manifiesto>` (artefacto
   construido APARTE con `scripts/build-frontend-artifact.sh`, ver más abajo) →
   `preflight-startup` → `activate <sha>` →
   `postgres-up` (requiere además `TVC_BACKUP_CONFIRMED=yes`) → `postgres-bootstrap-db` →
   `postgres-roles` → `migrate` → `postgres-grants` → `import-reference` (dry-run) →
   `import-reference-apply` → `systemd-install` → `healthcheck`.
   `validate-compose` puede ejecutarse en cualquier momento (solo lectura, resuelve el YAML).
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

## Cierre focalizado (CLOUD-DEP-02A.4, tercera auditoría del PR #55)

Tercera auditoría de ChatGPT sobre el HEAD de la ronda 2: "arquitectura y correcciones R2
aceptables", 3 bloqueos puntuales antes del merge:

- **Punto 1 (orden migrate → postgres-grants/arranque)**: `migrate` seguía siendo solo `--check`
  (la aprobación para APLICAR migraciones sigue siendo manual y explícita, sin cambios), pero
  nada impedía ejecutar `postgres-grants` o el primer arranque (`systemd-install`) saltándose esa
  fase. Ahora `phase_postgres_grants`, `phase_systemd_install` y el reinicio dentro de `activate`
  llaman a `lib_common.sh::assert_schema_migrated` (el mismo `migrate.py --target dev --check`) y
  se detienen con un mensaje claro si el esquema no está completo. Validado empíricamente contra
  un Postgres efímero real: `--check` falla antes de migrar, pasa a OK justo después.
- **Punto 2 (`rollback.sh version`, salud tras reiniciar)**: reiniciaba los servicios pero no
  comprobaba que respondieran. Ahora ejecuta `lib_common.sh::mvp_healthcheck` (la misma
  comprobación que usa `deploy.sh`) tras el `systemctl restart` y, si no responde, lo dice
  explícitamente y sale con código de error — nunca afirma que la recuperación fue exitosa sin
  haberlo comprobado. La misma comprobación se añadió también al camino de reversión automática
  dentro de `deploy.sh activate` (CLOUD-DEP-02A.2-R2 ya cubría el caso de ida; el de reversión
  quedaba sin verificar).
- **Punto 3 (archivo temporal del healthcheck)**: `/tmp/.deploy-activate-healthcheck.log` (nombre
  fijo) se sustituyó por un `mktemp` por invocación en `deploy.sh activate` y en
  `rollback.sh version`, con limpieza en todos los caminos de salida.

## Build externo y runtime Node aislado (CLOUD-DEP-02B.1-C.1)

Decisión arquitectónica: el frontend ya NO se compila en el VPS, y Node nunca se instala a nivel
de sistema (nunca `apt`/NodeSource, nunca `/usr/bin/node`) — ambas cosas tocarían algo compartido
con TVC/ETL (el PATH global, el gestor de paquetes del sistema). En su lugar:

- **`scripts/build-frontend-artifact.sh`** — se ejecuta en un host Linux x86_64 APARTE (CI o un
  dev box), nunca en el VPS. Verifica que el repositorio está exactamente en el commit pedido y
  sin cambios locales, compila con `corepack pnpm` (versionado por `packageManager` en
  `package.json`), empaqueta `dist/standalone/` en un `.tar.gz` y genera un manifiesto de texto
  con el commit, la versión de Node usada y el checksum SHA-256 del artefacto.
- **`deploy.sh install-frontend-artifact <sha> <tar.gz> <manifiesto>`** — instala ese artefacto en
  el VPS. Rechaza el artefacto si el commit del manifiesto no coincide EXACTAMENTE con el release,
  o si el checksum del `.tar.gz` no coincide con el del manifiesto; nunca sobrescribe un `dist/` ya
  instalado en ese release. Verificado con un artefacto sintético: instala con commit+checksum
  correctos, rechaza commit erróneo, artefacto manipulado y reinstalación.
- **`deploy.sh install-node-runtime <version> <tarball>`** — instala Node OFICIAL (tarball de
  `nodejs.org`) bajo `$APP_DIR/runtime/node-v<version>-linux-x64/`, verificando su checksum contra
  `env/node-runtime-checksums.txt` (versionado en este repositorio — ver "Hardening final" más
  abajo) ANTES de extraer nada; rechaza el tarball si no coincide, y rechaza cualquier versión que
  no esté en esa lista aprobada.
  `runtime/active` es un symlink que se conmuta atómicamente (igual que `current` para el código);
  **nunca borra una versión anterior** al instalar otra. Verificado end-to-end con el tarball
  OFICIAL real `node-v22.18.0-linux-x64.tar.xz`: rechazo de un tarball corrupto, instalación real
  (confirmado `node --version` como el usuario `vinto-mvp`), idempotencia, y coexistencia de dos
  versiones sin que la más reciente borre la anterior.
- El unit `systemd/vinto-mvp-frontend.service` apunta su `ExecStart` a
  `$APP_DIR/runtime/active/bin/node`, nunca a `/usr/bin/node`.
- `preflight.sh build-deps` ya no exige `node`/`corepack` en el VPS (no se compila allí); en su
  lugar comprueba que existe un comando Compose utilizable. `preflight.sh startup` comprueba que
  `runtime/active/bin/node` existe antes de activar/arrancar.
- **Hallazgo adicional, corregido de paso**: al ejercitar por primera vez `systemd-analyze verify`
  contra los units (misma versión de systemd que el VPS, 255), apareció `Unknown key name
  'StartLimitIntervalSec'` — esa directiva (junto con `StartLimitBurst`) pertenece a la sección
  `[Unit]`, no a `[Service]`; estaba mal ubicada en ambos units desde su creación, así que la
  política de reinicio controlada nunca se aplicaba de verdad. Corregido en los dos archivos.

## Docker Compose: `docker compose` o `docker-compose` (Fase D, CLOUD-DEP-02B.1-C.1)

El VPS real solo tiene el binario standalone `docker-compose` (v5.3.1, confirmado el mismo motor
que el plugin oficial — su propio `--help` se autodenomina `docker compose`), no el plugin
`docker compose`. `lib_common.sh::detect_compose_cmd` detecta cuál de los dos existe y expone el
array `COMPOSE_CMD`, usado por `deploy.sh`/`rollback.sh` en vez de invocar `docker compose`
literal. `deploy.sh validate-compose` resuelve el YAML con `config` (nunca `up`/`down`) para
confirmarlo sin levantar ningún recurso persistente.

## Hardening final (CLOUD-DEP-02B.1-C.2, tercera auditoría del PR #56)

- **DEP56-01 (extracción segura de artefactos)**: `install-frontend-artifact` ya no extrae el
  `.tar.gz` directamente sobre el release. Antes de extraer nada, valida CADA entrada (Python,
  `tarfile`): debe vivir bajo `standalone/`, sin componentes `..`/`.` ni rutas absolutas, y no
  puede ser un enlace simbólico/duro ni un tipo especial; además usa el filtro endurecido `data`
  de `tarfile` (PEP 706, Python ≥ 3.12) como segunda barrera. Extrae en un directorio de staging
  propio (`$APP_DIR/.artifact-staging/<único>`) y solo lo mueve al release si todo resultó íntegro
  y `standalone/server.js` existe; el staging se borra siempre (`trap ... EXIT`), ante error o
  éxito. Probado con artefactos reales: entrada fuera de `standalone/`, recorrido `../..`, enlace
  simbólico que escapa del destino y tar truncado/corrupto — los 4 rechazados, el release nunca
  se toca y el staging queda vacío.
- **DEP56-02 (procedencia del runtime Node)**: comparar el tarball contra un `SHASUMS256.txt`
  suministrado junto a él (como antes) no demuestra procedencia — quien controla el tarball
  controla igual ese archivo. El checksum esperado se lee ahora de
  `env/node-runtime-checksums.txt`, versionado en este repositorio (aprobar una versión nueva
  exige un commit y una revisión de PR); `install-node-runtime` ya solo toma `<version>
  <tarball>`, sin un tercer argumento. Probado con el tarball oficial real
  `node-v22.18.0-linux-x64.tar.xz`: instala la versión aprobada, rechaza una versión NO aprobada
  (aunque el tarball sea válido) y rechaza un tarball manipulado para la versión aprobada —
  `runtime/active` nunca cambia en ningún caso de rechazo. Confirma además que una segunda versión
  aprobada no borra la primera.
- **DEP56-03 (validación de Compose sin exponer secretos)**: `validate-compose` ya no ejecuta
  `config` sin más (imprimiría la configuración resuelta, incluidas las contraseñas). Ahora exige
  que el comando Compose disponible soporte `-q/--quiet` ("solo valida, no imprime nada") y lo
  usa siempre; si un error de validación llegara a citar un valor, se redacta cualquier secreto
  conocido del propio `.env` antes de mostrarlo (sustitución literal vía Python, no `sed`/glob).
  Probado con una contraseña sintética inyectada en `docker/.env`: no aparece en stdout ni stderr,
  ni en el camino exitoso ni en el de error (variable requerida ausente).

Hallazgo adicional corregido durante estas pruebas: dos asignaciones `var="$(grep ... | awk
...)"` sin `|| true` en `install-node-runtime`/`install-frontend-artifact` podían abortar el
script de forma SILENCIOSA (sin ningún mensaje) si el `grep` no encontraba coincidencia — el
mismo patrón que `lib_common.sh::env_value` ya evita internamente. Corregido con `|| true` y un
mensaje explícito en cada caso, siguiendo la misma convención que el resto del archivo.
