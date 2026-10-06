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

