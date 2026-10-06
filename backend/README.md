# Backend local VINTO — Fase 5

FastAPI y Uvicorn corren en Windows; PostgreSQL 17 sigue en Docker.
Psycopg 3 verifica la conexión con SELECT 1. El esquema inicial está definido
en migraciones SQL del backend. No se conecta el frontend ni se cargan datos
de negocio o catálogos ficticios.

## Preparación en PowerShell

Desde la raíz del repositorio, si el venv todavía no existe:

```powershell
Set-Location .\backend
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Puede usarse `python -m venv .venv` o un Python 3.12 por ruta absoluta.
No hace falta activar el venv ni cambiar políticas de PowerShell.

## Variables locales

backend/.env es privado e ignorado por Git. En un clon nuevo:

```powershell
Copy-Item .env.example .env
notepad .env
```

Configurar DATABASE_URL con host 127.0.0.1, puerto 5432, base vinto y
usuario vinto_app. La contraseña debe coincidir con la configuración de
PostgreSQL. Codificar caracteres especiales del usuario/contraseña en la URL.
No imprimir ni publicar la URL. Una variable de entorno del proceso tiene
prioridad sobre backend/.env. Reiniciar Uvicorn tras cambiar .env.

La configuración carga este archivo por ruta calculada desde config.py.
La URL se almacena como SecretStr y no se registra en logs.
Si no está configurada, /health sigue funcionando y /api/health devuelve 503.

## Ejecutar

Desde backend/:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Verificar desde otra ventana PowerShell

```powershell
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health'
Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -TimeoutSec 10
curl.exe -i --max-time 10 'http://127.0.0.1:8000/api/health'
```

- /health: HTTP 200, {"status":"ok"}; no accede a PostgreSQL.
- /api/health: HTTP 200, {"status":"ok","database":"ok"}.
- DB no disponible: HTTP 503, {"status":"error","database":"unavailable"}.

Documentación: http://127.0.0.1:8000/docs. Detener con Ctrl+C.

## Estrategia de conexión

Una conexión por comprobación, cerrada mediante context managers incluso
si falla la consulta. Autocommit evita transacciones abiertas para SELECT 1.
El endpoint síncrono usa el thread pool de FastAPI, sin bloquear el event loop.
No se conecta a PostgreSQL al importar la aplicación ni al iniciar Uvicorn.

DB_CONNECT_TIMEOUT=3 limita el intento de conexión por host a 3 segundos;
DB_STATEMENT_TIMEOUT_MS=2000 limita la consulta en PostgreSQL a 2 segundos.
No constituyen un límite total garantizado de HTTP ante cualquier fallo de red.
Los logs indican éxito, configuración ausente o tipo de fallo, sin URL,
contraseña ni detalle bruto de excepciones.

Para una API de negocio con mayor carga se evaluará un pool posteriormente.

## Migraciones iniciales

Desde backend/:

```powershell
.\.venv\Scripts\python.exe migrate.py --status
.\.venv\Scripts\python.exe migrate.py
.\.venv\Scripts\python.exe migrate.py --check
```

Las pruebas ya no se ejecutan contra la base de desarrollo: ver
"Base de pruebas (vinto_test)". Para migrar o comprobar la base de pruebas
se usa `migrate.py --target test`.

La única fuente del esquema es migrations/*.sql. Drizzle sigue separado.
El ejecutor registra versiones y checksum, usa un bloqueo de ejecución y
revierte cada migración fallida. No se ejecuta automáticamente al iniciar
FastAPI. Leer migrations/README.md antes de añadir nuevas versiones.

Las consultas de verificación están en verification.sql. Para ejecutarlas
con psql del contenedor desde la raíz del repositorio:

```powershell
Get-Content -Raw -Encoding UTF8 .\backend\verification.sql | docker compose exec -T postgres psql -U vinto_app -d vinto -v ON_ERROR_STOP=1
```
## Base de pruebas (vinto_test)

El mismo PostgreSQL local aloja dos bases:

| Variable | Base | Uso |
|---|---|---|
| DATABASE_URL | vinto | aplicación y desarrollo |
| TEST_DATABASE_URL | vinto_test | únicamente suites automáticas |

En Docker Compose el servicio backend recibe ambas, construidas con
POSTGRES_USER y POSTGRES_PASSWORD del .env raíz (host `postgres`). Nada se
hardcodea. backend/.env.example muestra TEST_DATABASE_URL para ejecución
fuera de Docker.

Todo se ejecuta dentro del contenedor, porque Windows puede bloquear la DLL
de psycopg-binary. Desde la raíz del repositorio:

```powershell
docker compose up -d
# 1. Crear vinto_test si falta y aplicar migraciones (idempotente)
docker compose exec backend python prepare_test_db.py
# 2. Verificar el historial de la base de pruebas
docker compose exec backend python migrate.py --target test --check
# 3. Ejecutar toda la suite
docker compose exec backend python -B -m unittest discover -s tests -v
```

`prepare_test_db.py` se conecta a la base de mantenimiento `postgres` (no a
vinto), crea la base indicada por TEST_DATABASE_URL solo si no existe y le
aplica las migraciones pendientes. Al volver a ejecutarlo no cambia nada. Si
una migración cambia en el futuro, se aplica de la misma forma a ambas bases:
`migrate.py` para vinto y `migrate.py --target test` para vinto_test.

### Protección contra mutaciones accidentales

app/db_guard.py abre toda conexión de pruebas con `connect_test_database()`,
que ejecuta `SELECT current_database()` y exige que el nombre real que
informa PostgreSQL termine en `_test`. No se confía en el texto de la URL.
Si no se cumple, se aborta con `UnsafeDatabaseError` antes de cualquier DDL o
fixture. Tampoco hay respaldo a DATABASE_URL: sin TEST_DATABASE_URL las
pruebas fallan con un mensaje claro.

La misma regla protege `migrate.py --target test` y `prepare_test_db.py`,
que además se niega a operar si TEST_DATABASE_URL apunta a la misma base que
DATABASE_URL. tests/test_db_guard.py verifica que vinto_test se acepta y que
vinto se rechaza, incluso cuando la cadena de conexión menciona `_test`.

Las fixtures siguen revirtiéndose al final de cada prueba; el contador
`vinto_txn.capture` de vinto debe permanecer en 0 tras ejecutar la suite.

## Importación de datos de referencia (bundle Bobinas)

`import_reference.py` importa `backend/seed_data/` (generado por
`scripts/export-seed-data.mjs`) a `vinto_master`, `vinto_config` y
`vinto_audit.import_batch/import_record`. La lógica vive en `app/seed/`
(`bundle.py` valida; `reference.py` importa); el CLI solo orquesta.

```powershell
# dry-run: valida el bundle, consulta la base y muestra el plan; escribe 0 filas
docker compose exec backend python import_reference.py --target test
# importar (primera vez) y repetir (NO-OP)
docker compose exec backend python import_reference.py --target test --apply
```

- `--target test|dev` es obligatorio. `test` usa `TEST_DATABASE_URL` mediante
  `connect_test_database()`; `dev` usa `DATABASE_URL`. Sin `--apply` siempre es
  un dry-run en una transacción `READ ONLY`.
- Se valida el bundle completo antes de abrir una conexión: manifest, SHA-256 y
  tamaños, archivos faltantes o extra, conteos, `definition_checksum` y
  referencias internas.
- `source_checksum` = SHA-256 del JSON canónico de `manifest.json` (claves
  ordenadas, compacto, UTF-8). Como el manifest contiene el hash de cada
  archivo, identifica el bundle completo.
- El `source` estable es `vinto-reference-bobinas`. 0001 no tiene
  `UNIQUE(source, source_checksum)`, así que la transacción toma primero
  `pg_advisory_xact_lock` con una clave de 64 bits derivada **solo del
  source**: bundles con checksum distinto compiten por el mismo lock y nunca
  modifican los mismos maestros a la vez. El checksum identifica el batch, no
  la exclusión mutua.
- Un batch `completed` del mismo checksum no se vuelve a crear, pero **no oculta
  el drift**: dry-run y `--apply` comparan siempre la base actual con el bundle.
  Si coincide exactamente: dry-run `CONSISTENT / NO CHANGES` y apply `NO-OP`
  (0 escrituras). Si algo difiere o falta (por ejemplo una `article_machine`
  borrada a mano): `CONFLICT / DRIFT` y `--apply` se detiene sin escribir ni
  reparar nada.
- Todo ocurre en una transacción. Un maestro ausente se inserta; uno idéntico
  se acepta como `already_present`; uno distinto es un conflicto y revierte la
  importación completa (no hay `ON CONFLICT DO UPDATE`).
- Las versiones de artículo y de formulario no se actualizan ni se crean
  versiones nuevas automáticamente. `form_version` se inserta como `draft`, se
  crean sus máquinas, campos y opciones, y al final se publica.
- No se importan usuarios, credenciales, dispositivos, OT, asignaciones,
  capturas ni recetas, y no se asigna actor (`created_by` queda NULL).

Pruebas (`tests/test_import_reference.py`): usan bases efímeras `*_test` creadas
desde una plantilla migrada, así que no dependen de lo que contenga `vinto_test`.

## Autenticación interna

`app/auth/` contiene el dominio de autenticación (service, passwords, permissions), las sesiones
(`sessions.py`) y la capa HTTP (`router.py`, `schemas.py`, `dependencies.py`); ver "Sesiones y endpoints de autenticación".

- `passwords.py`: Argon2id con `argon2-cffi` (parámetros por defecto: t=3, m=64 MiB, p=4).
  `hash_password`, `verify_password`, `validate_password_policy`. La contraseña debe tener de
  12 a 256 caracteres; no se exigen mayúsculas, números ni símbolos.
- `service.py`: `normalize_username` (strip + minúsculas, `^[a-z0-9._-]{1,64}$`), `create_user` y
  `authenticate`. Ambas esperan una conexión autocommit y gestionan su transacción.
- `permissions.py`: matriz en código, sin acceso a la base de datos (`permissions_for_profiles`,
  `has_permission`). Un perfil desconocido no concede nada. DATA_BALTREK administra catálogos y
  usuarios pero no recibe permisos funcionales de planta.
- `errors.py`: `InvalidCredentialsError` y `AccountLockedError` deberán exponerse con un mensaje
  externo genérico en la futura API.

Bloqueo: 5 intentos fallidos bloquean la cuenta 15 minutos (`AUTH_MAX_FAILED_ATTEMPTS`,
`AUTH_LOCKOUT_MINUTES`). Un login correcto reinicia el contador; un bloqueo vencido reinicia la
cuenta con 5 intentos nuevos. La fila de la credencial se toma con `SELECT ... FOR UPDATE`, así
que intentos concurrentes no pierden incrementos, y contador y `auth_event` se confirman juntos.
Usuario inexistente, inactivo y contraseña incorrecta dan el mismo `InvalidCredentialsError`; para
un usuario inexistente se verifica la contraseña contra un hash ficticio válido. `auth_event` no
guarda el username intentado.

Crear un usuario (la contraseña se pide con getpass y nunca se imprime):

```powershell
docker compose exec backend python create_user.py --target test --username dev.jefatura --display-name "Jefatura DEV" --profile JEFATURA
```

`--target test|dev` es obligatorio y el perfil debe existir y estar activo; el CLI no crea perfiles.
Para automatización existe `--password-env NOMBRE` (lee la contraseña de esa variable de entorno solo
si se pide explícitamente). No hay opción para pasar la contraseña como argumento ni se guarda en
`.env.example`.

## Sesiones y endpoints de autenticación

| Endpoint | Resultado |
|---|---|
| `POST /api/auth/login` `{"username","password"}` | 200 `{"user": {...}}` + cookie de sesión; 401 `{"detail":"Credenciales inválidas"}` |
| `GET /api/auth/me` | 200 `{"user": {...}}`; 401 `{"detail":"No autenticado"}` |
| `POST /api/auth/logout` | 204 y cookie borrada (idempotente); 503 `{"status":"error","database":"unavailable"}` con la cookie también borrada si PostgreSQL falla |

`user` = `id`, `username`, `display_name`, `profiles` y `permissions` (ordenados alfabéticamente) y `must_change`.
Credenciales inexistentes, incorrectas, cuenta bloqueada o usuario inactivo devuelven el MISMO 401 y el mismo
cuerpo, sin `Retry-After` ni cookie. Los 422 de `/api/auth/*` no repiten la entrada. Un fallo de PostgreSQL da un
503 sin URL, contraseña ni SQL.

- **Token**: `secrets.token_urlsafe(32)` (256 bits). El cliente solo lo recibe en la cookie; PostgreSQL guarda
  únicamente su SHA-256 (64 hex minúscula) y el token nunca se registra ni aparece en JSON, errores, logs,
  `audit_event` ni `auth_event`.
- **TTL fijo**: `AUTH_SESSION_HOURS` (12 por defecto, 1 a 72). `expires_at` no se extiende; resolver una sesión solo
  actualiza `last_seen_at`. No hay refresh tokens. Se permiten varias sesiones por usuario.
- **Cookie** (`AUTH_COOKIE_NAME`, `vinto_session`): `HttpOnly`, `SameSite=Lax`, `Path=/`, sin `Domain`,
  `Max-Age` = TTL y `Secure` salvo con `APP_ENV=local`.
- **Logout best-effort**: la cookie local se borra SIEMPRE. Sin cookie responde 204 sin consultar la base. Con cookie,
  intenta revocar la sesión: si funciona, 204 y evento `logout`; si PostgreSQL falla, 503 con el cuerpo seguro de
  "base no disponible" Y la cookie borrada. El 503 indica que la revocación en el servidor NO pudo confirmarse: no se
  registra `logout` y **la sesión del servidor puede seguir viva hasta su `expires_at`** (limitación conocida: quien
  conserve el token podría seguir usándolo hasta entonces). El cliente debe tratar el 503 como "sesión local cerrada,
  revocación pendiente".
- **Atomicidad del login**: autenticar y crear la sesión van en una transacción exterior. Con credenciales
  inválidas se confirman los eventos y contadores y después se responde 401. Si falla la creación de la sesión se
  revierte todo (incluido `login_ok`): no hay login ni cookie.
- **request_id**: cada login y logout genera un UUID en el servidor; no se confía en `X-Request-ID`.
- **Dependencias** (`app/auth/dependencies.py`): `current_user` (401 sin sesión válida) y
  `require_permission("work_order.manage")` (401 sin sesión, 403 sin el permiso). Las usarán OT, asignaciones y
  capturas.

CORS: `allow_credentials=True`, métodos `GET` y `POST`, cabecera `Content-Type` y orígenes explícitos
(`CORS_ORIGINS`, por defecto `http://127.0.0.1:8787`); nunca `*`. El frontend deberá usar `credentials: "include"`.

CSRF: por ahora basta `SameSite=Lax` más orígenes CORS explícitos (un POST JSON entre sitios exige preflight).
Antes de añadir acciones sensibles cross-site, subdominios distintos o formularios HTML hay que reevaluarlo
(token CSRF o cabecera personalizada con verificación de `Origin`).

Rate limiting: NO está implementado y es un requisito antes de producción: límite por origen/IP para
`/api/auth/login` (preferiblemente también en Nginx). El bloqueo por cuenta no lo sustituye (un atacante puede
bloquear cuentas ajenas). No se añadió un limitador en memoria porque fallaría con varios workers.

## Órdenes de trabajo BASE (Bobinas)

`app/work_orders/` (`service.py` dominio, `router.py` y `schemas.py` HTTP, `errors.py`). Alcance: solo la versión
`baseline` (v1) de OT del sector BOBINAS; no hay versiones operativas, asignaciones ni capturas todavía. El frontend
sigue usando `vinto-ot`/`vinto-asg` de `localStorage`.

| Endpoint | Permiso | Resultado |
|---|---|---|
| `POST /api/work-orders` | `work_order.manage` | 201; crea OT en borrador + baseline v1 + líneas L1..Ln |
| `POST /api/work-orders/{id}/lines` | `work_order.manage` | 201; añade la siguiente línea (solo borrador) |
| `POST /api/work-orders/{id}/publish` | `work_order.manage` | 200; idempotente |
| `GET /api/work-orders?machine_code=&status=&limit=` | `work_order.read` | lista, más recientes primero |
| `GET /api/work-orders/{id}` | `work_order.read` | detalle |

Solo JEFATURA tiene `work_order.manage`; SUPERVISION, OPERACION, CALIDAD y DATA_BALTREK leen. Cuerpo de creación:
`{"machine_code": "MP1", "lines": [{"pv_reference", "article_code", "quantity", "due_date"}]}`. El cliente nunca envía
número, `line_code`, descripción, unidad ni ids (`extra=forbid`): el servidor los resuelve.

- **Máquina y artículos**: por código contra los maestros. La máquina debe existir (404), estar activa y ser del sector
  BOBINAS (422). El artículo debe existir (404), estar activo, ser producto y tener `article_machine` para esa máquina
  (422). Cada línea congela el `article_version_id` de mayor `version_number` y toma su unidad.
- **Número** `OT-AAAA-NNNN` (año del reloj de PostgreSQL): se genera en el servidor dentro de la transacción tras
  `pg_advisory_xact_lock` y el siguiente correlativo del año; `UNIQUE(number)` es la defensa final. Sin tabla nueva.
  Puede reemplazarse cuando Expertus sea la autoridad de las OT. **`line_code`**: `L{n+1}` bajo `SELECT ... FOR UPDATE`
  sobre la OT y su baseline.
- **Ciclo**: `draft` -> `published`. Publicar fija `published_at` de la baseline y `status='published'`; repetirlo
  devuelve el estado actual sin escribir. Publicada, la baseline es inmutable: no hay endpoints para editar o borrar y
  los triggers de 0001 lo imponen en la base (409 al añadir líneas).
- **Errores**: 401 sin sesión, 403 sin permiso, 404 OT/máquina/artículo inexistente (un id mal formado también es 404),
  409 conflicto de estado, 422 datos inválidos, 503 base no disponible. Los mensajes no incluyen SQL.
- **Auditoría**: cada operación fija `vinto.actor_id` (created_by/updated_by), un `vinto.request_id` generado en el
  servidor y `vinto.reason` ("work order create", "work order add baseline line", "work order publish baseline").
- `quantity`: hasta 15 dígitos y 3 decimales; se devuelve como número JSON.

## Copia operativa y asignaciones (Bobinas)

`app/assignments/` (`service.py`, `router.py`, `schemas.py`, `errors.py`). El frontend sigue con su demo en
`localStorage`; no hay capturas, F6 central ni cierre de OT todavía.

| Endpoint | Permiso | Resultado |
|---|---|---|
| `POST /api/assignments/activate` `{"work_order_id","baseline_line_id"}` | `assignment.manage` | 201 si crea; 200 `already_active` si ya estaba activa para esa línea, turno y fecha |
| `POST /api/assignments/{id}/finish` | `assignment.manage` | 200; idempotente |
| `GET /api/assignments?machine_code=&status=&operating_date=&work_order_id=&limit=` | `assignment.read` | más recientes primero |
| `GET /api/assignments/active?machine_code=MP1` | `assignment.read` | `{assignment, current_shift, stale}`\|null, current_shift, stale}` |

Solo SUPERVISION tiene `assignment.manage`: JEFATURA (aunque tenga `work_order.manage`), OPERACION, CALIDAD y
DATA_BALTREK solo leen.

- **Versión operativa**: las asignaciones nunca apuntan a una línea baseline. La primera activación de una OT
  `published` crea la versión `operational` (siguiente `version_number`, normalmente v2): INSERT con `published_at`
  NULL, copia de TODAS las líneas de la baseline (nuevos ids; se conservan `line_code`, PV, `article_version_id`,
  unidad, cantidad y fecha) y solo entonces `published_at`, tras lo cual los triggers de 0001 la hacen inmutable. Las
  siguientes activaciones reutilizan la operativa publicada de mayor `version_number` (no se crea una por turno ni por
  asignación). La baseline no se modifica. El cliente envía la línea BASE; el backend busca la línea operativa con el
  mismo `line_code` y rechaza ids de líneas operativas o de otra OT (404).
- **Estado de la OT**: solo `published` o `in_progress` (409 en `draft`/`closed`); la primera asignación la pasa a
  `in_progress`. No se cierra.
- **Turno y fecha operativa**: el cliente no los envía. Se resuelven con `resolve_shift` sobre `clock_timestamp()` de
  PostgreSQL y el sector de la máquina de la OT. Sin turno configurado o con configuración ambigua: 409
  (`SHIFT_NOT_CONFIGURED` / `SHIFT_AMBIGUOUS`) con mensaje seguro, sin escribir nada.
- **Una asignación activa por máquina**: bajo lock transaccional por máquina, la activa anterior (si es distinta) pasa
  a `finished` con `finished_at` y se crea una nueva, todo en una transacción; una `finished` nunca se reactiva y el
  cambio de turno genera una asignación nueva. Orden de locks (sin interbloqueos): OT (`FOR UPDATE`) -> máquina
  (advisory) -> asignación (`FOR UPDATE`); `finish` toma máquina -> asignación.
- **Auditoría**: cada paso fija su motivo ("create operational work order version", "activate assignment", "finish
  previous assignment", "finish assignment"), el supervisor como actor y un `request_id` generado en el servidor.
- `stale` en `/active`: `true` si la asignación activa ya no corresponde al turno/fecha actuales (hay que reactivar
  para poder capturar); `null` si el turno actual no se puede resolver.

# Primera integración: contador de capturas

`GET /api/captures/count?front=Bobinas` devuelve:

```json
{"front":"Bobinas","count":0,"source":"database"}
```

Admite Bobinas, Rebobinado, Conversión y Calidad; otros valores o un front
ausente devuelven 422. Cuenta todos los estados de captura. Para producción
filtra por el nombre del sector de la máquina; para Calidad filtra por
form_version.area = 'quality'. Los nombres de los sectores deberán coincidir
con los fronts existentes al cargar los maestros reales.

La consulta usa Psycopg con transacción de solo lectura, conexión breve y los
timeouts configurados. No importa localStorage ni escribe datos. DB no
disponible devuelve 503 con status=error y database=unavailable; los logs
solo incluyen el tipo de error. /health conserva su comprobación sin DB.

CORS_ORIGINS admite una lista JSON en backend/.env. Por defecto únicamente
autoriza http://127.0.0.1:8787, GET y sin cookies. CORS no sustituye autenticación.
La conexión de FastAPI requiere lectura de capture, machine, sector y
form_version; esta integración no provisiona ni modifica roles.

Con Uvicorn activo, probar desde PowerShell:

```powershell
Invoke-RestMethod 'http://127.0.0.1:8000/api/captures/count?front=Bobinas'
$vintoFront = [uri]::EscapeDataString('Conversión')
Invoke-RestMethod "http://127.0.0.1:8000/api/captures/count?front=$vintoFront"
curl.exe -i 'http://127.0.0.1:8000/api/captures/count?front=Inventado'
```

Comparación SQL de solo lectura:

```sql
SELECT count(*) FROM vinto_txn.capture c
JOIN vinto_master.machine m ON m.id = c.machine_id
JOIN vinto_master.sector s ON s.id = m.sector_id
WHERE s.name = 'Bobinas';

SELECT count(*) FROM vinto_txn.capture c
JOIN vinto_config.form_version f ON f.id = c.form_version_id
WHERE f.area = 'quality';
```

Pruebas de contrato, CORS, conexión fallida y conteos reales con fixtures
revertidas (contra vinto_test, ver "Base de pruebas"):

```powershell
docker compose exec backend python -B -m unittest tests.test_capture_api -v
```

Las pruebas de consulta reutilizan las fixtures técnicas del esquema y
requieren permisos administrativos de prueba; no ejecutar esas fixtures
con la futura cuenta restringida de producción. No quedan datos de prueba.

## Captura central F6 (VINTO-P1-06, Bobinas)

`POST /api/captures` (permiso `production.capture`, solo OPERACION) registra el "Registro de control de fardos". Payload:
`{capture_id (UUIDv4 del cliente), form_code: "VINTO-P1-06", assignment_id, device_key (UUID), values{cantidad_fardos, punto_merma, tipo_producto, peso_kg, observaciones?}}`.
El esquema es cerrado (`extra="forbid"`): máquina, turno, fecha operativa, OT, PV, artículo, línea, versión del formulario, revisión, estado, marcas de tiempo y usuario los deriva el backend.

- **Idempotencia**: `capture.id = capture_id` con lock advisory por id. Reintento idéntico -> 200 `{created:false, already_submitted:true}` sin escrituras; mismo id con otro contexto/actor/valores -> 409 `CAPTURE_IDEMPOTENCY_CONFLICT`.
- **Asignación**: debe estar activa, en Bobinas, sobre una línea operativa y con OT no cerrada, y seguir vigente ahora (reloj de PostgreSQL + `resolve_shift`); si cambió el turno o la fecha -> 409 `ASSIGNMENT_STALE`.
- **Dispositivo**: `device_key` se resuelve contra `device.external_key`; se crea (sin máquina) si no existe y se revierte con la captura; inactivo o ligado a otra máquina -> 409.
- **Valores**: se validan contra `field_definition`/`field_option` de la versión publicada más alta (opciones por `option_key`, decimales como `Decimal` y devueltos como texto). Errores -> 422.
- **Transacción**: lock -> contexto de auditoría -> asignación -> dispositivo -> versión -> validación -> INSERT draft -> `capture_detail` tipados -> UPDATE a `submitted` (revisión final 1). Todo o nada.
- `GET /api/captures` (filtros `assignment_id`, `machine_code`, `operating_date`, `limit` 1..200; más recientes primero) y `GET /api/captures/{id}`; `GET /api/captures/count` se mantiene.

Orden de locks: capture_id -> máquina (misma clave que asignaciones) -> asignación FOR SHARE -> device_key.
