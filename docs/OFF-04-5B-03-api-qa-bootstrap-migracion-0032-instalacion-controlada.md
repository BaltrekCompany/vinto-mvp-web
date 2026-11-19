# VINTO OFF-04.5B-03 — Entrypoint QA, migración 0032 y motor authz: preparación final del código

**Estado:** candidato de desarrollo aislado, PR Draft apilado sobre #238 (`1347a2133d7d8c421ebb3c94ceee218bf5e99dba`). Seguimiento: #239.
**NO instala, NO despliega, NO aplica migraciones reales, NO crea usuarios ni concesiones, NO habilita captura industrial.** SEC-HOST-01 y OFF-04.2-R3 siguen en backlog. Este documento no contiene identificadores de infraestructura (hosts, IP, puertos, rutas, nombres de bases o de roles reales, secretos).

## 1. Qué se entrega
| Pieza | Archivo | Resumen |
|---|---|---|
| Entrypoint ASGI | `backend/app/qa_pilot_main.py` | Módulo independiente de `app.main` para uvicorn (`app.qa_pilot_main:app` o `--factory app.qa_pilot_main:create_app`). `app` se construye al primer acceso, no al importar. |
| Migración candidata | `backend/offline_capture_migration/proposed_0032_offline_capture_receipt.sql` | Compatible con `migrate.py`: sin `BEGIN`/`COMMIT`, falla si el esquema ya existe, con grants mínimos. |
| Rollback | `…rollback.sql` | Comprueba dependencias, revoca al rol de aplicación y **archiva** el esquema (`vinto_offline_archived`). Sin `DROP`, sin `CASCADE`. |
| Verificación | `…verify.sql` | Solo `SELECT`; cada fila debe ser `true`. |
| Promoción | `backend/offline_capture_migration/promote_0032.py` | Copia la propuesta a un árbol temporal y comprueba que es una migración válida. **Rechaza `backend/migrations/`.** |
| Pruebas | `backend/tests/test_off045b03_qa_bootstrap.py` | 38 pruebas sobre PostgreSQL desechable. |
| CI | `.github/workflows/off-04-5b-03-qa-bootstrap.yml` | PostgreSQL 17, pytest y controles estáticos. |

La migración **no** está en `backend/migrations/`: `migrate.py` no puede aplicarla por accidente.

## 2. Entrypoint
- **Inactivo por defecto:** con `OFFLINE_QA_PILOT_ENABLED` apagado o `APP_ENV` distinto de `qa`, construir la aplicación **no abre ninguna conexión** y no monta ninguna ruta de capturas; en QA el guard rechaza con 403 toda escritura.
- **Activo solo si** `APP_ENV=qa`, flag encendido, concesiones sintéticas válidas y la base verificada. Usa la cadena de conexión del **rol de aplicación** (`DATABASE_URL`), nunca la de identidad, migrador o administración.
- **Verificación de la base real** (respuestas de PostgreSQL, no la cadena de conexión): nombre QA/desechable, no es réplica, el rol no es superusuario ni tiene `CREATEDB`/`CREATEROLE`/`REPLICATION`/`BYPASSRLS`, no puede crear en la base ni en el esquema, no es propietario de las tablas, no tiene `DELETE`/`TRUNCATE`/`REFERENCES`/`TRIGGER`, sí tiene los privilegios mínimos, y existen los dos triggers de protección.
- **El rol de aplicación no lee el historial de migraciones** (`vinto_meta` está cerrado para él por diseño): el historial y los checksums los verifica el operador con el rol migrador.
- Cualquier fallo lanza `PilotConfigError` con un **código fijo**; nunca se incluye la cadena de conexión, el nombre de la base o del rol, ni identificadores de usuarios. El proceso no arranca a medias.
- El registro de arranque solo informa de: activo sí/no, modo `authz` y número de concesiones.

## 3. Migración 0032
- **Compatibilidad con `migrate.py`:** sin control de transacciones propio; `CREATE SCHEMA vinto_offline` sin `IF NOT EXISTS`.
- **Grants mínimos para el rol de aplicación:** `USAGE` en el esquema; `SELECT, INSERT, UPDATE` en `capture_receipt` (el `UPDATE` se limita por trigger: resultado final e identidad inmutables); `SELECT, INSERT` en `capture_event` (append-only). Sin `DELETE`, `TRUNCATE`, DDL ni permisos fuera del esquema; `PUBLIC` sin nada. Las secuencias de columnas `IDENTITY` no necesitan grant.
- **El rol debe existir:** si falta, la migración entera se revierte.
- **No altera nada más:** una prueba compara las ACL de todas las demás relaciones y esquemas antes y después: no cambia ninguna.
- **Checksums e historial:** el archivo promovido pasa `read_migrations` (versiones 1–32 consecutivas), su checksum coincide con el SHA-256 del texto, `validate_history` detecta una alteración y `apply` es idempotente.
- **Ensayo:** aplicación y rollback en bases `*_test` desechables, con el árbol promovido en un directorio temporal.

### Rollback (a mano, por el propietario del esquema; no lo ejecuta `migrate.py`)
1. Detener el servicio QA o apagar el flag.
2. Ejecutar el script de rollback: rechaza si el esquema no existe, si ya existe `vinto_offline_archived`, si quien lo ejecuta no es propietario o si algo fuera del esquema depende de él (claves foráneas, vistas, triggers). Revoca al rol de aplicación y renombra el esquema. **Todas las filas se conservan.**
3. El historial de migraciones no se modifica (es de solo añadir). El piloto no arranca sin el esquema (`receiver_schema_missing`).
4. Retirar `0032` del checkout antes de cualquier ejecución futura de `migrate.py`, o la siguiente migración la volvería a crear.
5. La eliminación definitiva del esquema archivado es un paso aparte, con autorización explícita y exportación previa de la evidencia.

## 4. Motor `authz`
- `AuthzEngineProbe` se probó contra PostgreSQL con la base de referencia real del repositorio: usuario con perfil y concesión → permite; otro usuario, sin concesión, sin permiso funcional, otra máquina, otro formulario, usuario desconocido o concesión revocada → deniega. Nunca escribe (no cambia concesiones ni auditoría).
- Modos con el piloto completo:

| Modo | Registro sintético + motor permite | Solo registro | Solo motor |
|---|---|---|---|
| `off` | 201 | 201 | 403 |
| `observe` | 201 | 201 | 403 |
| `enforce` | 201 | 403 | 403 |

- `observe` **nunca concede**: con el motor permitiendo y sin concesión del registro, el resultado es 403, y no hay efecto sobre una decisión basada en el registro.
- Una indisponibilidad del motor deniega en `enforce` y no cambia nada en `observe`; nunca es un permiso.
- Una concesión sintética del registro **no crea** ningún permiso industrial: las concesiones del motor no cambian y el motor sigue denegando a ese usuario.

## 5. Pruebas (todas sintéticas, bases desechables)
Inicio con flag apagado y fuera de QA (sin conexión a base); bloqueo de otras escrituras; sesión inválida (401); usuario incorrecto y sin concesión (403); snapshot de solo lectura (403); recepción técnica; duplicado (una fila); mismo ID con otro contenido (409); conexión con el rol restringido (19 operaciones prohibidas rechazadas, triggers de resultado final); inicio rechazado con cada forma insegura de base; fallos sin eco de detalles; migración, promoción, checksums, historial y rollback; sonda del motor en tres modos; regresiones OFF-04.4, OFF-04.5A (Chrome contra FastAPI y PostgreSQL) y OFF-04.5B-01. Ocho mutaciones del código (grant `DELETE`, `CREATE` en esquema, rollback sin comprobar dependencias, rollback que borra, bucle de privilegios, superusuario, esquema ausente, `IF NOT EXISTS`) son detectadas.

## 6. Secuencia de instalación controlada (cada paso exige autorización propia; NADA de esto se ejecutó)
0. CI verde del SHA exacto de este PR y revisión humana.
1. Integrar #219 y la cadena OFF-04 en la rama de QA y actualizar el checkout QA (cambio de código desplegado, con aprobación).
2. Respaldo QA nuevo con restauración verificada inmediatamente antes del DDL.
3. Promover `0032` a `backend/migrations/` **mediante un PR revisado** (no con el script) y aplicarla con el rol migrador (`migrate.py --check` antes y después); ejecutar el script de verificación.
4. Servicio QA propio con el flag **apagado** y comprobar el 403 de toda escritura y el 404 de las rutas de capturas.
5. Acceso privado (VPN o allowlist con rechazo por defecto, desde dos orígenes).
6. Cuenta y concesión sintéticas mínimas; `authz` en `observe` y después `enforce`.
7. Encender el flag; recorrido con dispositivo real; una sola recepción por captura.
8. Parada y reversión según §3 y el plan de OFF-04.5B-01.

## 7. Riesgos residuales y puntos abiertos
- Ejecutadas localmente con PostgreSQL 16.2; **PostgreSQL 17 se valida en Actions**.
- En QA real el rol de aplicación tiene más privilegios operativos (DML por `backend/roles/`) que los que replican las pruebas, que solo le dan lectura para el motor. La migración 0032 no añade ninguno fuera de su esquema.
- Las concesiones sintéticas viven en la configuración del servicio, no en la base.
- No hay evaluación de contexto industrial real; la homologación de P1-22 y OFF-04.2-R3 siguen pendientes para cualquier uso real.
- Los controles de red, TLS y firewall del host (incluido el PostgreSQL del piloto publicado en una interfaz pública, observado en el preflight) quedan fuera de este incremento.
