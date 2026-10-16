# Migraciones SQL del backend VINTO

Los archivos `NNNN_descripcion.sql` de esta carpeta son la única fuente de
verdad del esquema PostgreSQL del backend. No se generan desde Drizzle,
SQLAlchemy ni una segunda definición de modelos. No contienen credenciales.

Se eligió SQL versionado porque la aplicación usa Psycopg directamente y no
tiene modelos ORM. Alembic añadiría SQLAlchemy sin aportar autogeneración a
este esquema; sus capacidades serán reevaluadas si la arquitectura cambia.

## Aplicación desde PowerShell

Desde backend/:

```powershell
.\.venv\Scripts\python.exe migrate.py --status
.\.venv\Scripts\python.exe migrate.py
.\.venv\Scripts\python.exe migrate.py --check
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

El ejecutor usa DATABASE_URL de la configuración existente, un bloqueo
advisory de sesión y una transacción por migración. Una migración fallida
revierte su DDL y no registra su versión. Si varias migraciones pendientes
se ejecutan, las anteriores ya exitosas permanecen aplicadas.

El historial vive en vinto_meta.schema_migration. SHA-256 se calcula sobre
SQL UTF-8 con saltos de línea LF para tolerar checkouts CRLF en Windows.
Se rechazan huecos, duplicados, archivos aplicados modificados y versiones
aplicadas ausentes del checkout. --status y --check no modifican la base.

No editar una migración aplicada. Crear 0002_descripcion.sql y sucesivas.
Los SQL deben ser transaccionales y no incluir BEGIN, COMMIT, ROLLBACK ni
operaciones que requieran ejecución fuera de transacción, como índices
CONCURRENTLY. No hay comando automático de downgrade o borrado de datos.
Los siguientes cambios se hacen con nuevas migraciones hacia adelante.

## Esquema inicial

- vinto_master: 12 tablas de identidad, máquinas, artículos y unidades.
- vinto_config: 14 tablas de formularios, campos, opciones, turnos y recetas.
- vinto_txn: 10 tablas de OT, asignaciones, capturas, bobinas y calidad.
- vinto_audit: 3 tablas de auditoría y procedencia de importaciones.
- vinto_meta: historial técnico de migraciones.

0001 no carga datos. Maestros y configuración se poblarán con fuentes reales
conciliadas en otra fase. Las pruebas crean fixtures exclusivamente en
transacciones revertidas. Las secuencias de auditoría pueden tener huecos;
un hueco no implica pérdida de registros ni se reinician las secuencias.

## Integridad y escritura futura

FK/PK, unicidades y CHECK protegen identidad, tipos y relaciones. Triggers
mantienen timestamps del servidor y auditoría en la misma transacción.
Las definiciones de formulario/receta y las líneas de OT publicadas son
inmutables. Las versiones de artículo también son inmutables.

Cada escritura futura del backend debe usar SET LOCAL mediante set_config
para vinto.actor_id, vinto.request_id y vinto.reason dentro de la transacción.
El actor de aplicación debe ser un UUID existente de vinto_master."user".
La auditoría conserva además session_user. No poner secretos ni tokens en
los campos de negocio ni en los payloads de importación/auditoría.

Las capturas comienzan como draft. Cabecera y detalles deben guardarse en
una transacción. Las FK compuestas impiden mezclar versiones, capturas y
grupos; una validación diferida comprueba campos requeridos y cardinalidad
al enviar/cerrar. Una captura enviada requiere creador/modificador.

Para corregir una captura enviada, pasarla a draft con motivo auditado,
editar sus detalles y volver a enviarla en una sola transacción. revision
sigue la regla de 0003 (ver más abajo). Una captura cerrada es inmutable.
La API futura deberá comprobar revision para evitar actualizaciones
concurrentes perdidas y aplicar permisos/transiciones de negocio.

Los registros import_record y audit_event son inmutables; registrar el
resultado resuelto de una importación antes de insertar import_record.
No existen todavía endpoints de negocio ni vistas de reportes: se conserva
su configuración y los datos base para implementarlos en una fase posterior.

Los controles de auditoría no sustituyen el hardening: vinto_app conserva
por ahora los privilegios de desarrollo definidos en la Fase 1. Separación
de roles, TLS y permisos restrictivos siguen pendientes (ver más abajo
"CLOUD-01B-2: modelo de privilegios mínimos" para el diseño de esa
separación, probado en una instancia efímera, todavía no adoptado en
DEV/QA/operativo).

Consultas de inspección de tablas, claves, índices y auditoría:
backend/verification.sql. Este archivo es de solo lectura.

## 0002_auth.sql: dominio de autenticación

Crea el esquema `vinto_auth` con tres tablas: `credential` (username,
password_hash Argon2id, intentos fallidos, bloqueo), `session` (solo el
SHA-256 del token opaco, nunca el token) y `auth_event` (eventos de seguridad
append-only: login_ok, login_fail, logout, lockout, password_change).
No contiene usuarios, contraseñas, hashes ni tokens.

Reglas que deben respetar las migraciones y el código futuros:

- Ninguna tabla de `vinto_auth` lleva el trigger `vinto_audit.record_change`:
  copia la fila completa a `audit_event` y filtraría `password_hash` y
  `token_hash`. Por eso el hash no se añadió a `vinto_master."user"`, que sí
  está auditada. Los eventos de seguridad van a `auth_event`, que no tiene
  columnas secretas.
- `credential` reutiliza `touch_row` (tiene created_at/updated_at y
  created_by/updated_by); `session` y `auth_event` no, porque su dueño ya es
  `user_id` y un actor adicional sería artificial.
- El username es único sin distinguir mayúsculas mediante un índice sobre
  `lower(username)`, sin extensiones. La normalización a `[a-z0-9._-]` en
  minúsculas es responsabilidad de la aplicación.
- `auth_event` no guarda el username intentado a propósito: un usuario puede
  escribir su contraseña en ese campo. `user_id` es NULL si el usuario no existe.
- `auth_event` rechaza UPDATE, DELETE y TRUNCATE. Una sesión revocada no puede
  reactivarse y su token_hash, dueño y fecha de creación no cambian.

Se aplica a la base de pruebas con `python prepare_test_db.py` o
`python migrate.py --target test`. La base de desarrollo sigue en la
versión 1 hasta que se decida aplicarla con `python migrate.py`.

## 0003_capture_revision_semantics.sql: semántica de revision

Reemplaza únicamente la regla de `revision` de `vinto_txn.validate_capture()` (CREATE OR REPLACE FUNCTION; el
trigger sigue asociado y las demás protecciones de 0001 no cambian):

- INSERT: `revision = 1`, ignorando cualquier valor del cliente.
- Mientras `OLD.status = 'draft'`, cualquier UPDATE conserva la revisión (`draft -> draft`, `draft -> submitted`,
  `draft -> blocked`): editar un borrador no es una corrección.
- Cualquier otro UPDATE (por ejemplo `submitted -> submitted` con `correction_reason` y `vinto.reason`, o reabrir
  `submitted -> draft`): `revision + 1`.

Una captura reabierta cuenta su corrección al reabrirse (y sigue exigiendo `correction_reason` y `vinto.reason`); sus
`draft -> draft` y el `draft -> submitted` siguientes conservan esa revisión: una corrección, un incremento. No reescribe
capturas existentes: las creadas antes de 0003 conservan su revision.

## 0004_bobbin_production.sql: F3, correlativo y gramaje

Solo hacia adelante y sin borrar ni reescribir filas:

- `vinto_master.article_version_spec`: especificación estructurada por `article_version` (gramaje `grammage_g_m2`, NULL si el artículo no lo tiene).
  Tabla hermana inmutable: `article_version` no se toca. Se puebla desde el bundle (el exportador deriva el gramaje de la descripción oficial).
- `vinto_txn.management_start_year(date)`: la gestión va del 01/04 al 31/03 y se identifica por su año de inicio.
- `vinto_txn.bobbin_sequence`: contador por (máquina, gestión); solo avanza de uno en uno y no se borra.
- `vinto_txn.bobbin` (ya existía desde 0001) se amplía con `machine_id`, `management_start_year`, `sequence_number`, `start_time`, `end_time`,
  `diameter_mm`, `grammage_g_m2`, `number_of_cuts` (texto) y `notes`. Las filas históricas (todas esas columnas NULL) se conservan; los CHECK nuevos
  solo obligan a las filas con `sequence_number`. OT/PV/turno/operador no se duplican: salen de `source_capture_id -> assignment`.
- El UNIQUE global de `code` se elimina (el "1" existe en cada máquina y gestión) y se reemplaza por `UNIQUE (machine_id, management_start_year,
  sequence_number)`, `UNIQUE (source_capture_id)` para filas nuevas y la unicidad global de `code` solo entre filas históricas.
- Triggers: coherencia máquina/gestión/artículo de la bobina con su captura, identidad inmutable, y un constraint trigger diferido que exige la
  fila `quality_release` antes del COMMIT.

## 0005_quality_capture_bobbin.sql: capturas de Calidad ligadas a una Bobina

Solo hacia adelante, sin backfill: las capturas existentes (F3, F6) quedan con `bobbin_id IS NULL`.

- `vinto_txn.capture.bobbin_id` (nullable) -> `vinto_txn.bobbin(id)` ON DELETE RESTRICT, con índice normal (NO único: una
  Bobina puede tener varias capturas de Calidad; la cardinalidad no está confirmada).
- Trigger `guard_capture_bobbin`: una captura con `bobbin_id` debe usar una versión de formulario `quality` y llevar
  exactamente el contexto productivo de la F3 de origen de esa Bobina (máquina, turno, fecha operativa y asignación);
  `bobbin_id` no puede cambiar después. `validate_capture()` no se reemplaza.

## CLOUD-01B-2: modelo de privilegios mínimos

Las migraciones 0001-0006 se aplicaron y se seguirán aplicando sin modificar (no se reescribe ninguna
para no invalidar su checksum en instalaciones ya migradas). El modelo de privilegios mínimos (roles
`vinto_app`/`vinto_migrator`/`vinto_reference`/`vinto_test_admin`, ver `backend/roles/README.md`) se
provisiona como un paso **aparte**, fuera de `migrate.py`, ejecutado una sola vez por el administrador
del clúster, nunca como una migración numerada. Dos razones:

1. `CREATE ROLE` requiere `CREATEROLE`, privilegio que ningún rol de aplicación debe tener (principio 5);
   no tiene sentido que una migración —pensada para ejecutarse con el rol migrador, sin `CREATEROLE`—
   intente crear roles.
2. Los `GRANT` sobre objetos ya existentes (0001-0006) son un aprovisionamiento de infraestructura, no un
   cambio de esquema: no alteran tablas, columnas, triggers ni datos, así que no les corresponde un
   número de migración.

**Toda migración `0007` en adelante que agregue una tabla que la API (`vinto_app`) o el importador de
referencias (`vinto_reference`) deban leer o escribir DEBE incluir, al final del mismo archivo `.sql`,
sus propios `GRANT` explícitos** (por ejemplo `GRANT SELECT, INSERT, UPDATE ON vinto_txn.tabla_nueva TO
vinto_app;`). **El modelo es fail-closed: no existe ningún `GRANT`/`ALTER DEFAULT PRIVILEGES` que otorgue
nada —ni siquiera `SELECT`— sobre tablas futuras** (corregido en PG54-01 tras la auditoría del PR #54; la
versión anterior de este documento concedía `SELECT` por defecto, lo que la auditoría señaló como una
concesión automática indebida). Ver `backend/roles/05_no_default_privileges.sql`: una tabla nueva nace
completamente inaccesible para `vinto_app`/`vinto_reference` hasta que la migración que la crea declara
explícitamente, uno por uno, los privilegios exactos que necesita. Olvidar el `GRANT` no hace que la API
funcione a medias (lectura sin escritura): la hace fallar de inmediato con `insufficient_privilege` en
cualquier intento de uso, lo que se detecta en la primera prueba, no en producción.

**Caso especial: funciones invocables directamente con `SELECT` (no funciones de trigger).** A
diferencia de una tabla, PostgreSQL concede `EXECUTE` a `PUBLIC` por defecto sobre toda función nueva.
`ALTER DEFAULT PRIVILEGES ... IN SCHEMA x REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC` **no lo evita**
(verificado: con `IN SCHEMA`, un `REVOKE` sobre funciones no registra nada en `pg_default_acl`; limitación
de PostgreSQL documentada desde hace años, BUG #8685). La variante **sin** `IN SCHEMA` —
`ALTER DEFAULT PRIVILEGES FOR ROLE vinto_migrator REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC` — **sí
funciona**: verificado que protege, con alcance global por rol creador, toda función nueva que
`vinto_migrator` cree en cualquier esquema (confirmado también en un esquema sin ninguna entrada propia),
sin afectar a funciones creadas por otro rol. Ya se aplica en `backend/roles/05_no_default_privileges.sql`
y cubre automáticamente toda función invocable directamente que una migración `0007` en adelante cree
(no una función de trigger — esas devuelven el pseudotipo `trigger` y PostgreSQL rechaza invocarlas fuera
de un disparador, sin importar el `EXECUTE` que tengan). Aun así, declarar explícitamente a quién SÍ se
le concede `EXECUTE` (`GRANT EXECUTE ON FUNCTION ... TO vinto_app;`) sigue siendo buena práctica, por la
misma disciplina de privilegios explícitos que exige este modelo para tablas.

Ese default **no protege retroactivamente** una función creada antes de aplicarlo: por eso
`vinto_txn.management_start_year` (de `0004_bobbin_production.sql`, sin reescribir esa migración) sigue
necesitando su propio `REVOKE EXECUTE ON FUNCTION ... FROM PUBLIC;` explícito sobre el objeto ya
existente, en `backend/roles/04_function_grants.sql` — la única vía fiable para un objeto que ya existía
cuando se configuró el default.
