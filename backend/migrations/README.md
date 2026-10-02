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
se incrementa al cambiar la cabecera. Una captura cerrada es inmutable.
La API futura deberá comprobar revision para evitar actualizaciones
concurrentes perdidas y aplicar permisos/transiciones de negocio.

Los registros import_record y audit_event son inmutables; registrar el
resultado resuelto de una importación antes de insertar import_record.
No existen todavía endpoints de negocio ni vistas de reportes: se conserva
su configuración y los datos base para implementarlos en una fase posterior.

Los controles de auditoría no sustituyen el hardening: vinto_app conserva
por ahora los privilegios de desarrollo definidos en la Fase 1. Separación
de roles, TLS y permisos restrictivos siguen pendientes.

Consultas de inspección de tablas, claves, índices y auditoría:
backend/verification.sql. Este archivo es de solo lectura.
