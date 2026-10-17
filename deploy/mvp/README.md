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
   a este archivo compartido; nunca se duplica por versión. **Si `checkout` ya se ejecutó ANTES
   de que `shared/backend.env` existiera** (avisa de esto explícitamente en su salida), ese
   release queda sin el enlace para siempre — `checkout` nunca se repite sobre un release ya
   existente (DEP55-04). Para ese caso, una vez `shared/backend.env` exista con 600/propietario
   correctos, ejecutar `CONFIRM=yes bash deploy.sh link-backend-env <sha>` (CLOUD-DEP-02B.2-C):
   crea exactamente ese mismo enlace sobre el release ya en disco, sin repetir `checkout` ni
   `python-venv`; es idempotente y nunca sobrescribe algo inesperado (ver "Contratos de
   configuración" más abajo).
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
- **DEP56-03 / DEP56-R2-01 (validación de Compose sin exponer secretos)**: `validate-compose` ya
  no ejecuta `config` sin más (imprimiría la configuración resuelta, incluidas las contraseñas).
  Exige que el comando Compose disponible soporte `-q/--quiet` ("solo valida, no imprime nada") y
  lo usa siempre. La primera versión, al fallar la validación, intentaba REDACTAR el detalle del
  error pasando la contraseña como ARGUMENTO a un proceso Python — visible en la lista de
  procesos del host mientras ese proceso corría (el mismo problema que PG54-03 ya corrigió para
  las conexiones a PostgreSQL). Corregido de raíz: la función ya NO lee ninguna contraseña en
  absoluto, y el detalle de un error de validación NUNCA se captura, imprime ni escribe en ningún
  archivo — solo se informa que falló, sin ningún detalle, invitando a depurar manualmente si se
  acepta el riesgo. Probado con una contraseña sintética inyectada en `docker/.env`: no aparece en
  stdout, stderr, ni como argumento de ningún proceso vigilado con `ps` mientras corre la
  validación, ni en el camino exitoso ni en el de error.

Hallazgo adicional corregido durante estas pruebas: dos asignaciones `var="$(grep ... | awk
...)"` sin `|| true` en `install-node-runtime`/`install-frontend-artifact` podían abortar el
script de forma SILENCIOSA (sin ningún mensaje) si el `grep` no encontraba coincidencia — el
mismo patrón que `lib_common.sh::env_value` ya evita internamente. Corregido con `|| true` y un
mensaje explícito en cada caso, siguiendo la misma convención que el resto del archivo.

## `link-backend-env` y contratos de configuración (CLOUD-DEP-02B.2-C)

Incremento reducido: cierra el hueco de un release ya clonado (`checkout`) antes de que
`shared/backend.env` existiera, y revisa/documenta los contratos de permisos de los dos archivos
`.env` reales de este despliegue. Ninguna credencial real se agrega en ningún archivo de este
repositorio; esta PR no se conecta al VPS ni ejecuta ninguna fase mutadora fuera de un laboratorio
Docker efímero.

### `deploy.sh link-backend-env <sha>`

`checkout` (ver "Versionado por releases" arriba) solo crea `releases/<sha>/backend/.env ->
shared/backend.env` EN EL MOMENTO del clonado, si `shared/backend.env` ya existe entonces; nunca
se repite sobre un release existente (DEP55-04), así que un release clonado antes quedaba sin ese
enlace para siempre. `link-backend-env` cierra ese hueco sin repetir `checkout` ni `python-venv`
(comprobado por código en `verify_local.sh`: el cuerpo de la fase nunca invoca ninguna de las
dos). Reutiliza exactamente el mismo enlace relativo que `checkout` ya usa
(`../../../shared/backend.env`) y el mismo chequeo de permisos 600 que `python-venv` ya aplica,
sumando además una comprobación de propietario que ningún script anterior hacía explícitamente
(ver abajo). Es idempotente: una segunda ejecución con el enlace ya correcto no hace nada (`exit
0`, sin mensaje de error). Nunca sobrescribe algo inesperado: comprueba primero `-L` (¿hay un
enlace ahí, resuelva o no?) antes de `-e` (que seguiría un enlace roto hasta su destino y
reportaría, incorrectamente, "no existe") — un archivo regular, un directorio, un enlace roto
hacia otro destino, o un enlace válido hacia otro destino, se rechazan todos sin tocarlos. Nunca
toca `current`. Probado en un laboratorio Docker efímero (operador sin privilegios + `vinto-mvp`
separado, estructura de `releases/`/`shared/` fabricada directamente — esta fase solo hace
`mkdir`/`ln`/`stat`, nunca clona, así que el laboratorio no instala git/python) contra los 11
casos pedidos (enlace correcto, idempotencia, destino inexistente, permisos incorrectos,
propietario incorrecto, release inexistente, enlace roto preexistente, enlace hacia otro destino,
archivo regular preexistente, fallo de sudoers, `current` sin cambios), más la validación de
`CONFIRM=yes` y de SHA completo (mismo patrón que el resto de `deploy.sh`): 16/16 PASS.

### Contratos de configuración

**`shared/backend.env`**: propietario `vinto-mvp:vinto-mvp`, permisos `600`. Verificado hasta
ahora solo por `python-venv` (permisos, resueltos a través del symlink vía `stat -L`);
`link-backend-env` añade la comprobación de **propietario** que ningún script anterior hacía de
forma explícita — antes, un `shared/backend.env` con permisos 600 pero propiedad incorrecta
habría fallado más adelante, en tiempo de lectura real, con un "permission denied" menos claro
que el mensaje explícito que da ahora esta fase. Se lee siempre como texto (`mvp_env_value`,
nunca `source`) desde `postgres-roles` (para reaprovisionar roles con las contraseñas ya
generadas) y, fuera de `deploy.sh`, desde el proceso de la API y las herramientas administrativas
(`migrate.py`, `import_reference.py`).

**`docker/.env`**: contrato de seguridad implementado en CLOUD-DEP-02B.2-D.1 (ver sección dedicada
más abajo) — a diferencia de `shared/backend.env`, el hueco documentado originalmente en
CLOUD-DEP-02B.2-C ya está cerrado.

**Comportamiento cuando falta una variable**: `env_value`/`mvp_env_value` (`lib_common.sh`)
fallan con un mensaje explícito (nunca una cadena vacía silenciosa ni un valor por defecto) y
`return 1`; el `set -euo pipefail` de cada script detiene la fase de inmediato. El YAML de
Postgres usa `${VAR:?mensaje}` para sus 4 claves obligatorias: una `.env` incompleta hace fallar
`docker compose config`/`up` con ese mensaje, antes de levantar ningún contenedor.

**Variables `*_TEST` de `backend.env.example`**: `TEST_DATABASE_URL`/`MIGRATOR_TEST_DATABASE_URL`/
`REFERENCE_TEST_DATABASE_URL` apuntan a `vinto_piloto_test`, una base que este pipeline nunca crea
(no existe ninguna fase `postgres-bootstrap-db-test` ni equivalente). Deben completarse con
contraseñas reales igual que el resto (nunca dejarse como `CHANGE_ME` literal en el archivo real
— ver siguiente punto), con el entendimiento explícito de que, mientras el piloto no tenga una
base de pruebas propia, no las usa ningún flujo de `deploy.sh`. Decisión pendiente, fuera del
alcance de esta PR: crear esa base realmente sería una fase nueva, no una reutilización de
`postgres-bootstrap-db`.

**Prohibición de contraseñas ficticias**: ningún `.env.example` de `deploy/mvp/env/` puede
contener algo distinto de `CHANGE_ME` — verificado automáticamente por la sección "comprobación
de secretos en logs/artefactos" de `verify_local.sh`. Esta PR no agrega ningún valor real a
ningún archivo del repositorio; `shared/backend.env`/`docker/.env` reales se crean y rellenan
exclusivamente en el VPS, a mano, por quien tiene acceso a la terminal.

**Prevención de filtraciones en logs/comandos/artefactos**: ninguna contraseña se pasa como
argumento de línea de comandos (`psql`, `docker exec -e`, ni ningún proceso) — ver
`lib_common.sh::pg_run_sql_inline`/`pg_run_sql_file` (PG54-03/DEP55-R2-03) y
`phase_validate_compose` (DEP56-03/DEP56-R2-01). La batería de pruebas de `link-backend-env`
añade su propia comprobación de que ningún valor del `shared/backend.env` sintético del
laboratorio queda impreso en ningún log de esa batería — mismo criterio que la comprobación
general ya existente, aplicado también a la fase nueva.

## Endurecimiento de `docker/.env` (CLOUD-DEP-02B.2-D.1)

Cierra el hueco señalado en CLOUD-DEP-02B.2-C: `docker/.env` contiene `POSTGRES_BOOTSTRAP_PASSWORD`
en texto plano y, hasta este incremento, ningún script verificaba su propietario, sus permisos, ni
rechazaba un enlace simbólico.

### Contrato exacto

- **Archivo regular, nunca un enlace simbólico** — incluso si el enlace resolviera a un archivo
  válido con permisos y propietario correctos (misma lección que DEP60-01 para
  `shared/backend.env`).
- **Propietario = quien invoca el script**, resuelto dinámicamente con `id -un` en el momento de
  la comprobación — **nunca un nombre de usuario fijo como `ubuntu`**: el VPS real podría nombrar
  distinto a ese operador, y `deploy.sh`/`rollback.sh` nunca se ejecutan completos como root/sudo.
- **Permisos exactamente `600`.**
- **El directorio que lo contiene no puede ser escribible por grupo ni por otros** — si lo fuera,
  cualquiera con ese acceso podría sustituir el archivo sin que ninguna comprobación sobre el
  archivo en sí lo detectara.
- **Nunca legible por `vinto-mvp`** — ni como propietario ni por ningún otro medio (grupo, otros,
  ACL). Se comprueba de forma ACTIVA (`sudo -u vinto-mvp test -r`), no solo infiriéndolo de
  propietario/modo: una ACL POSIX que conceda lectura a `vinto-mvp` recalcula además la máscara
  (el bit de grupo que `stat` reporta cambia en la práctica, confirmado empíricamente: `600` ->
  `640`), así que normalmente ya queda cubierto por el chequeo de permisos — la comprobación activa
  queda como defensa en profundidad para un mecanismo que `stat` no refleje en absoluto.

### Dónde vive la lógica

`lib_common.sh::docker_env_contract_check <path>` es el guardián compartido: nunca llama a `exit`
ni imprime el contenido del archivo — deja el resultado en su código de retorno y el motivo del
primer fallo en `DOCKER_ENV_CONTRACT_REASON` (una frase para el operador, nunca un valor leído del
archivo). Cada llamador decide qué hacer con un fallo:

- **Fases mutadoras de `deploy.sh`** (`validate-compose`, `postgres-up`, `postgres-bootstrap-db`,
  `postgres-roles`) usan `assert_docker_env_contract`, que se detiene (`exit 1`) con el motivo. Se
  invoca ANTES de cualquier operación mutadora o de leer ningún valor del archivo.
- **`rollback.sh rollback_postgres`** usa `docker_env_contract_check` directamente y, si falla por
  CUALQUIER motivo (ausente, symlink, permisos, propietario, legible por `vinto-mvp`), degrada al
  mismo camino ya existente de "tratarlo como ausente" (`down` por nombre de proyecto, sin
  `--env-file`) — una operación de **recuperación** nunca debe volverse imposible solo porque este
  archivo de configuración tenga un problema de permisos.
- **`preflight.sh stage_infra`** reporta el estado como diagnóstico de solo lectura: `OK` si no
  existe todavía (esperado antes de la primera `postgres-up`, igual que `shared/backend.env` antes
  del primer `checkout`), `OK` si existe y cumple el contrato, `FALLA` si existe pero lo viola.

### Procedimiento seguro de creación posterior

1. Copiar `env/postgres.env.example` a `docker/.env`, en el VPS, por quien tiene acceso a la
   terminal — nunca generado ni transcrito en una conversación con un asistente.
2. Generar cada contraseña con `openssl rand -base64 24` (o equivalente) directamente en esa
   terminal.
3. `chmod 600 docker/.env` y confirmar que el propietario es quien ejecuta `deploy.sh`/`docker
   compose` (normalmente ya lo es, por ser quien creó el archivo).
4. Confirmar que el directorio que lo contiene (`deploy/mvp/docker/`) no es escribible por grupo
   ni por otros.
5. Nunca aplicar `setfacl` ni ningún otro mecanismo que conceda acceso a `vinto-mvp` sobre este
   archivo — no lo necesita.

### Diferencia respecto a `shared/backend.env`

| | `shared/backend.env` | `docker/.env` |
|---|---|---|
| Propietario correcto | `vinto-mvp` | quien invoca el script (nunca `vinto-mvp`) |
| Quién debe poder leerlo | `vinto-mvp` (proceso de la API, `migrate.py`, `import_reference.py`) | solo el operador — `vinto-mvp` nunca |
| Por qué la diferencia | el proceso del MVP corre bajo esa identidad | Postgres se administra desde fuera del MVP; si `vinto-mvp` pudiera leerlo, comprometer el backend filtraría también el secreto de arranque del clúster |

### Comportamiento cuando falta el archivo

- **Fases mutadoras de `deploy.sh`**: `FALLA` explícita (`$path no existe.`) — nunca continúan sin
  él.
- **`rollback.sh rollback_postgres`**: comportamiento preexistente, sin cambios — se trata como
  legítimamente ausente (esperado si `postgres-up` nunca se ejecutó) y continúa con `down` por
  nombre de proyecto.
- **`preflight.sh`**: `OK`, nunca bloquea — es el estado esperado antes del primer `postgres-up`.

### Limitaciones operativas y riesgos residuales

- La comprobación del directorio padre solo mira el directorio INMEDIATO que contiene el archivo,
  no toda la cadena de directorios hasta la raíz (proporcional al resto del repositorio; una
  cadena completa de "ruta segura" tipo `ssh` sería un cambio de alcance mayor).
- El chequeo activo `sudo -u vinto-mvp test -r` requiere que `sudo -u vinto-mvp` funcione desde el
  invocador; si no funciona (p. ej. antes de `user-and-dirs`, cuando `vinto-mvp` todavía no
  existe), esa comprobación específica se omite en silencio — el contrato sigue siendo fail-closed
  gracias a los chequeos de propietario/permisos, que no dependen de `vinto-mvp` existiendo.
- `rollback_postgres` ya **no** depende de `detect_compose_cmd` para su camino degradado (ver
  DEP61-01 más abajo); su comportamiento ante un `docker/.env` inseguro se prueba ahora
  end-to-end con Docker real, no solo por código.
- Probado en `ubuntu:24.04` con ACLs POSIX estándar; no se ensayó contra NFS, SELinux, ni otros
  mecanismos de control de acceso que `stat`/ACL POSIX no cubran.

## DEP61-01: `rollback_postgres` sin depender de `docker/.env` (auditoría del PR #61)

**Hallazgo bloqueante**: el camino degradado original (cuando `docker/.env` faltaba o era
inseguro) invocaba `docker compose ... -p proyecto down` **sin** `--env-file`. Pero
`docker-compose.postgres.yml` exige `${VAR:?mensaje}` para sus 4 claves obligatorias
(`POSTGRES_BOOTSTRAP_DB/USER/PASSWORD`, `VINTO_MVP_PGDATA_DIR`) — sin un `--env-file` que las
resuelva, **Compose fallaba al interpretar el propio YAML, antes de intentar detener nada**
(confirmado empíricamente). La "recuperación" no recuperaba absolutamente nada.

### Corrección

El camino degradado ya **nunca pasa por Docker Compose**. `rollback_postgres` ahora:

1. Resuelve primero la identidad del contenedor con
   `lib_common.sh::resolve_confirmed_mvp_postgres_id` — exige nombre **+** etiqueta de proyecto
   compose **+** imagen (`postgres:17`, la que fija el YAML) coincidiendo, nunca solo el nombre
   (requisitos 3/4 del alcance). Si el contenedor no existe, es un estado legítimo e idempotente
   (`return 0`, mensaje explícito, nunca un error). Si existe pero cualquier señal no coincide,
   se detiene (`exit 1`) sin tocarlo.
2. Si `docker/.env` cumple el contrato de seguridad (DEP60-01/CLOUD-DEP-02B.2-D.1), intenta el
   camino normal (`compose down --env-file`) — comportamiento sin cambios para el caso válido.
3. Si el contrato falla, **o si incluso siendo válido `compose down` falla por otro motivo**
   (p. ej. contenido corrupto: una clave obligatoria ausente, que el contrato de seguridad del
   archivo no puede detectar porque nunca inspecciona claves/valores), degrada a `docker stop`
   **directo** sobre el ID ya confirmado — nunca lee `docker/.env`, nunca fabrica credenciales
   ficticias para completar el YAML (requisito 8).
4. El camino degradado es deliberadamente **conservador**: solo detiene, nunca elimina el
   contenedor ni la red `vinto-mvp-internal` (a diferencia de `compose down`, que sí los elimina)
   — recursos Docker que quedan creados a propósito; eliminarlos es una decisión aparte del
   operador (p. ej. repetir `rollback.sh postgres` una vez `docker/.env` esté restaurado).

### Pruebas (Docker real, no solo por código)

Un host Windows vía Git Bash **no garantiza semántica POSIX real** en su `/tmp` (confirmado
empíricamente: `chmod 600` seguido de `stat -c '%a'` seguía reportando `644`; `ln -s` no siempre
creaba un enlace real) — necesario para que `docker_env_contract_check` pruebe lo que de verdad
importa. La batería usa un contenedor Ubuntu con el **socket de Docker montado**
(`-v /var/run/docker.sock:/var/run/docker.sock`) y el CLI de Docker instalado dentro: los
contenedores que crea son **hermanos** en el mismo demonio que ve el resto de esta suite, con
semántica de archivo Linux real para `chmod`/`stat`/`ln -s`.

Casos cubiertos, todos con Docker real: `docker/.env` válido (camino normal sin cambios),
ausente, en `644`, como enlace simbólico (hacia un destino válido), con contenido corrupto (clave
obligatoria ausente — Compose falla, degrada igual sin fabricar nada), contenedor con el nombre
esperado pero identidad ajena (imagen distinta: rechazado, sigue activo), contenedor del MVP
inexistente (explícito e idempotente en dos ejecuciones), contenedor ajeno creado **antes** de
toda la batería (permanece activo después), ningún secreto impreso, y ninguna mención de TVC
salvo el reaseguro esperado del propio script. **11/11 PASS**, re-ejecutados junto con la
regresión completa de PR #57/#59/#60: **57/57 PASS**.
