# VINTO E1-09 — P2-A: diagnóstico previo a migración 0013 (SOLO LECTURA)

**Fecha:** 2026-11-06. **Estado actual:** P2-A1 PARCIAL por H (corregida en GitHub), **P2-A2 PASS y P2-A3 PASS por Codex SSH**, inventario de dependencias funcionales obtenido sin escritura; visibilidad efectiva por cuenta, historial migraciones y auditoría/importaciones NO VERIFICADOS.  
**Fuente:** P1-B verificado en VPS por Codex Desktop: `create-and-verify` una sola vez, exit 0, nuevo `.verified`, restauración temporal sin red, 47 tablas / 0 discrepancias, 18 respaldos anteriores intactos. Ver [P1-B](E1-09-P1B-respaldo-verificable-GO-condicionado.md).  
**Repositorio de referencia:** `BaltrekCompany/vinto-mvp-web`, `main@c64893e86a983a86d57f9a7406d0d736417f17e3`.  
**Alcance de P2-A:** análisis documental y, con SSH autorizado aparte, inspección **READ ONLY**, sin cambio de servicios ni datos. **P2-B (aplicar 0013) NO AUTORIZADO**.

## Cierre funcional P2-A2/P2-A3 — PASS (06/nov/2026)

**Fuente:** resultados del operador Codex Desktop en conexión SSH autorizada, no ejecución de SQL por ChatGPT. P2-A2 y P2-A3: guard=1, transacciones `REPEATABLE READ READ ONLY`, `COMMIT`, rol `vinto_app`, DB `vinto_piloto`; sin cambios, escalamiento de privilegios ni acceso TVC. Auditoría/importaciones NO consultadas.

### Permisos efectivos

| Objetos | USAGE | SELECT | Lectura efectiva |
|---|---|---|---|
| `vinto_txn.bobbin`, `bobbin_relation`, `capture_detail`, `capture_group_row`, `quality_release` | Sí | Sí | Sí |
| `vinto_audit.audit_event`, `import_record` | Sí | No | **No** |
| `vinto_meta.schema_migration` | No | No | **No** |

P2-A3 guardó exitosamente sus requisitos de lectura de tablas funcionales. **No intentar `GRANT` ni forzar otra identidad** para inspeccionar auditoría o migraciones: dejar NO VERIFICADO hasta autorizar un mecanismo legítimo de inspección.

### Distribución de las 20 OT por sector y máquina de cabecera

| Sector | Máquina | Draft | In progress | Published |
|---|---|---:|---:|---:|
| BOBINAS | MP1 | 5 | 4 | 1 |
| BOBINAS | MP3 | 1 | 1 | 0 |
| CONVERSION | GAMBINI | 0 | 1 | 0 |
| CONVERSION | OMET_I | 0 | 1 | 0 |
| REBOBINADO | BELOIT | 1 | 1 | 0 |
| REBOBINADO | COPASA | 0 | 1 | 0 |
| REBOBINADO | OVER | 0 | 1 | 0 |
| REBOBINADO | PERICHUN | 0 | 1 | 0 |
| REBOBINADO | TUBETERA | 0 | 1 | 0 |
| **Total** | | **7** | **12** | **1** |

Esta tabla agrupa por **cabecera**, no por todas las máquinas de línea ni por visibilidad efectiva de una sesión. Las consultas previas daban 12 OT en progreso, 16 líneas baseline y 11 asignaciones activas; **la distribución de 5 líneas sin asignación activa no se revalidó en P2-A2/A3**.

### Dependencias reales (filas vinculadas, no únicamente constraints)

| Tipo | Vinculadas a asignaciones de OT in_progress | Capturas sin assignment_id |
|---|---:|---:|
| Capturas submitted | 63 | 21 |
| `capture_detail` | 1.151 | 204 |
| `capture_group_row` | 19 | 0 |
| `bobbin` por `source_capture_id` | 5 | 0 |
| `bobbin_relation` por `capture_id` | 0 | 0 |
| `quality_release` sobre bobinas con captura fuente | 5 | 0 |

Las **21 capturas sin asignación** están en BOBINAS: MP1 (14) y MP3 (7), todas `submitted`. No se les puede atribuir una OT solo por máquina o fecha. Las 5 bobinas y sus decisiones de Calidad forman parte de dependencias directas; ausencia de otra relación por una clave analizada **no prueba inexistencia semántica**. No se inspeccionaron eventos de auditoría ni referencias importadas `import_record.target_id`.

### Decisión del diagnóstico

- **P2-A2/P2-A3 PASS**; se obtuvo evidencia suficiente para **rechazar un borrado directo/masivo de OT** en la VPS activa. No se ejecutó eliminación, archivado, migración, deploy o flag.
- La función de listado actual `work_orders.service.list_work_orders()` filtra sector, baseline de máquina y alcance de permisos; no dispone de `archived_at` ni permite borrar OT mediante la API. Para no exponer OT ficticias se necesita una funcionalidad de visibilidad nueva, no `DELETE`.
- **Separar dos objetivos:** (A) retirar OT de la vista operativa, conservando capturas/Calidad/auditoría; (B) resolver las OT `in_progress` y asignaciones `active` legadas para que el preflight E1-08 quede limpio. Archivar/ocultar sin abordar (B) **no** habilita E1.
- Antes de ejecutar cambios: identificar el universo de OT visibles por actor/sector y estado del modo `authz_assignment_reads_mode`; aprobar semántica de histórico/archivo, efecto sobre nuevas capturas y asignaciones, prueba de autorización MF13, y rollback. Auditoría/importaciones y historial migrador deben revisarse mediante su canal ya autorizado, nunca dando privilegios extra a `vinto_app`.
- **GO para diseño**, no para ejecutar la migración 0013, borrar las 20 OT, reescribir historial, cambiar flags o tocar TVC.

Para las alternativas y criterios técnicos consultar [decisión provisional de archivado/legado](E1-09-P2A4-decision-archivo-legado.md). La documentación previa de P2-A1 se conserva debajo como historial.

## Resultado remoto P2-A — inspección parcial por permisos (06/nov/2026)

**Fuente:** informe del operador Codex Desktop SSH. ChatGPT no ha ejecutado SQL en el VPS. Revalidación: release activo `86e4ec4fa6f6bf95c0e099279d8c51a016c7a6a4`, tabla 0013 ausente, backend/frontend activos, contenedor MVP PostgreSQL healthy, respaldo P1-B nuevo con marcador y checksums PASS. Consulta por stdin al contenedor `vinto-mvp-postgres`, BD `vinto_piloto`, rol `vinto_app`, transacción `REPEATABLE READ READ ONLY` con guard 1, timeouts y corte 2026-11-06 12:01:58 (Bolivia).

| Estado de OT | OT | Versiones | Líneas | Baseline | Asignaciones | Activas | Finished (turno) |
|---|---:|---:|---:|---:|---:|---:|---:|
| `draft` | 7 | 7 | 11 | 11 | 0 | 0 | 0 |
| `in_progress` | 12 | 24 | 32 | 16 | 72 | 11 | 61 |
| `published` | 1 | 1 | 2 | 2 | 0 | 0 | 0 |
| `closed` | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| **Total** | **20** | **32** | **45** | **29** | **72** | **11** | **61** |

- **Capturas:** **63 `submitted`** relacionadas por `capture.assignment_id` con OT `in_progress`. **21 capturas sin `assignment_id`** en toda la tabla: su vínculo semántico con OT no está verificado. No se obtuvieron conteos de bobinas, Calidad, detalles ni eventos de auditoría; las FKs y triggers observadas son metadatos, no volúmenes de dependientes.
- **Fallo exacto:** consulta H intentó `to_regclass('vinto_meta.schema_migration')` y terminó `permission denied for schema vinto_meta`; `ON_ERROR_STOP=1` abortó antes del `COMMIT`. Sin escritura, sin bypass de rol, sin cambios ni lectura de secretos. El error es esperable por la restricción del rol `vinto_app`; **NO justifica `GRANT` ni acceder como superusuario**.
- **Comparación con SQL-E:** 12 OT en curso, 16 baseline y 11 asignaciones activas coinciden con el último corte; NO se repitió la conciliación de 5 líneas sin activa. No confundir `assignment.finished` (61 asignaciones de turno) con ejecución lógica `finished`.
- **Interpretación:** las 20 OT pertenecen al universo de base, no necesariamente a las que ve un usuario, pues la API filtra por rol y sector. Las 63 capturas asociadas son historial de pruebas que el borrado físico debería preservar o tratar con política explícita; no están autorizadas como filas eliminables.

**Corrección documental GitHub:** en [consulta P2-A original](E1-09-P2A-ot-ficticias-diagnostico.sql), H fue reemplazada por una consulta a `pg_catalog.pg_class` y `pg_namespace` por **OID**, reportando `has_schema_privilege` y `has_table_privilege` sin resolver el nombre restringido `vinto_meta.schema_migration`. **El SQL corregido NO se ha ejecutado en VPS.**

**Continuación recomendada, con autorización de diagnóstico READ ONLY ya otorgada:**

1. Ejecutar únicamente [P2-A2 — H por catálogo y distribución sector/máquina](E1-09-P2A2-continuacion-readonly.sql) por stdin, con la misma identidad y garantías `REPEATABLE READ READ ONLY`. No repetir A–G sin motivo. Reportar los permisos efectivos `USAGE && SELECT`, agregados por sector y 21 capturas sin asignación por estado/sector. Si aparece migración 0013, otra identidad o falla autenticación: detener.
2. **Solo cuando P2-A2 confirme `lectura_efectiva=true`** para todas las tablas implicadas, ejecutar [P2-A3 — dependientes directos de captura, bobina y Calidad](E1-09-P2A3-dependientes-opcional-readonly.sql). Si falta algún permiso, omitir íntegramente P2-A3 y marcar `NO VERIFICADO`; **no ampliar privilegios**. Estas consultas no incluyen vínculos JSON de auditoría/importaciones.
3. El historial real `vinto_meta.schema_migration` permanece **NO VERIFICADO** mediante `vinto_app`. No usar credenciales del backup para migraciones ni ejecutar `migrate.py` sin aprobación y canal migrador legítimo.
4. Definir el conjunto de OT **visibles en la aplicación** por rol/sector; no deducirlo de los 20 registros. Eliminar o archivar físicamente **no forma parte de P2-A**. Retirar OT de la lista sin cambiar sus estados **no elimina** los bloqueos E1-08 de OT `in_progress` sin ejecución.

**Decisión actual:** P1-B PASS; P2-A **PARCIAL**, lectura corregida pendiente; P2-B/0013, borrado/archivo, despliegue, flag ON y TVC **NO EJECUTADOS**.

## Actualización: usuario autoriza retirar las OT ficticias visibles

El usuario autorizó **aplicar el diagnóstico P2-A** y señaló que **las OT mostradas en la aplicación son ficticias y se pueden retirar**. Se registra esa intención para la fase de saneamiento; **no se interpreta como permiso para eliminar masivamente todas las OT de la base, desactivar triggers, truncar tablas, borrar eventos de auditoría o introducir permisos de superusuario**. El conjunto exacto de "visibles" depende de la cuenta y del filtro de sector/rol en la API, no es equivalente automáticamente a `WHERE status='in_progress'` ni a todas las filas de `work_order`.

**Diagnóstico estático confirmado en GitHub `main@c64893e86a983a86d57f9a7406d0d736417f17e3` (no consulta remota):**

- `vinto_txn.work_order` tiene estados `draft/published/in_progress/closed`, **sin columna de archivado o eliminación lógica** en el esquema actual; `backend/app/work_orders/router.py` no ofrece endpoint normal de borrar OT. La lista del usuario filtra visibilidad por sector/permisos.
- `vinto_txn.work_order_version.work_order_id`, `work_order_line.work_order_version_id`, `assignment.work_order_line_id` y `capture.assignment_id` usan **FK `ON DELETE RESTRICT`**. También las tablas hijas de captura/bobina/Calidad tienen relaciones restrictivas.
- Los triggers `guard_order_version` y `guard_order_line` **rechazan DELETE de versiones/líneas publicadas**. `prevent_capture_delete` rechaza DELETE de una captura. `vinto_audit.audit_event` rechaza UPDATE/DELETE/TRUNCATE. El audit trigger `record_change` añade eventos para cambios válidos de tablas del dominio. **No desactivar ninguna de estas protecciones para "limpiar pruebas".**
- `capture.assignment_id` admite NULL; por tanto la ausencia de capturas enlazadas por FK no prueba que no haya capturas históricas de la misma máquina/fecha o bobinas/Calidad vinculadas por otro camino. Las referencias de auditoría JSON e importaciones pueden no tener FK directa.
- La migración 0013 también crea referencias con `ON DELETE RESTRICT` y una guarda que prohíbe DELETE de ejecuciones lógicas, si ya estuviese instalada.

**Primera conclusión:** un borrado por `DELETE FROM vinto_txn.work_order` es inadecuado. Para retirar OT visibles, determinar primero si es viable un reinicio controlado de datos, preservación y transición o implementar ocultamiento por interfaz/estado sin suprimir historial. El permiso para eliminar datos ficticios **no hace seguro saltarse restricciones de integridad**.

**Consulta de diagnóstico P2-A lista para Codex Desktop (no ejecutada):**
[E1-09-P2A-ot-ficticias-diagnostico.sql](E1-09-P2A-ot-ficticias-diagnostico.sql). Exige `vinto_app`, `vinto_piloto`, `REPEATABLE READ READ ONLY`, `statement_timeout=10s`, `lock_timeout=1s`, solo devuelve agregados y catálogo de FKs/triggers. Cuenta OT de **todos** los estados, líneas, asignaciones, capturas con FK y capturas sin FK a asignación; no publica números ni UUID.

**Ejecución solicitada para el operador SSH autorizado:** utilizar exclusivamente el SQL versionado de este PR por stdin contra **`vinto-mvp-postgres`** y devolver agregados. Si falla el guard/permiso o se detecta 0013 inesperadamente, **NO-GO**, no recurrir a superusuario. Repetir SQL-E solo con esquema anterior, manteniendo sus guardas. A continuación informar qué cuentas/sectores ven las OT ficticias **sin publicar filas individuales** y qué referencias impiden saneamiento. No alterar datos, permisos, `.env`, flags, servicios o TVC. **Prohibidos `DELETE`, `TRUNCATE`, `ALTER`, `DROP`, desactivar triggers y ejecutar `migrate.py`.**

## 1. Dependencias verificadas y límites

- Release activo en P0: `86e4ec4fa6f6bf95c0e099279d8c51a016c7a6a4` (anterior a E1). Backend/frontend en servicio; PostgreSQL MVP en `vinto-mvp-postgres` (imagen postgres:17, Compose `vinto-mvp`, base `vinto_piloto`). Confirmar de nuevo antes de cualquier decisión.
- Datos históricos observados por SQL-E/P0: **12 OT `in_progress`, 16 líneas baseline, 11 asignaciones `active` con mapping único, y 5 líneas sin activa (4 MP1 / 1 MP3), todas con historial de `assignment.finished`**. Esos valores son **snapshots**, no supuestos permanentes.
- Los datos se describieron como **simulados**, pero siguen alojados en la VPS activa y pueden referenciar capturas, pruebas, auditoría o integraciones.
- Migración `backend/migrations/0013_work_order_line_execution.sql` es **aditiva, sin backfill**. Su ejecución **no inicia, cierra ni repara** líneas históricas. Si continúan 16 líneas de OT `in_progress` sin `work_order_line_execution`, el diagnóstico E1-08 post-migración producirá el bloqueo `IN_PROGRESS_ORDERS_WITHOUT_EXECUTION`; las asignaciones `active` sin ejecución producirán `ACTIVE_ASSIGNMENTS_WITHOUT_EXECUTION`. **Bloquean activar el flag, no necesariamente crear la tabla mediante la migración aditiva con flag OFF.**
- **No deducir producción** de `assignment.active` ni **fin de línea** de `assignment.finished`.
- `vinto_app` **NO tiene SELECT en `vinto_meta.schema_migration`**; no concederle más privilegios para conveniencia. El diagnóstico `backend/app/work_orders/rollout_preflight.py::collect` intenta consultar esa tabla y no funcionará íntegro como `vinto_app` bajo el estado actual; debe usarse un mecanismo/rol autorizado y *solamente lectura*, o marcar **NO VERIFICADO**. La autorización de lectura interna de `docker/.env` se concedió **a `backup.sh` para P1-B**, no a cualquier comando o cliente de BD.
- El backup P1-B reside en el filesystem compartido del VPS según P1-A: comprobación de restaurabilidad PASS, pero **copia off-host NO VERIFICADA**. Antes de cambios irreversibles definir si se necesita réplica externa. No mover backups ni modificar retención desde P2-A.

## 2. P2-A — inventario remoto READ ONLY (solo con orden específica para Codex)

**No ejecutar todavía por la presente documentación.** Un operador SSH autorizado deberá:

1. Reconfirmar `current` SHA y salud de `vinto-mvp-backend.service`, `vinto-mvp-frontend.service` y contenedor correcto `vinto-mvp-postgres`. Confirmar ausencia de la tabla 0013 en catálogo o, si aparece, registrar cambio inesperado; no corregir.
2. Confirmar que el respaldo P1-B nuevo y su marcador de verificación siguen presentes y que sus checksums resultan válidos mediante **lectura**; no volver a restaurar ni crear respaldo.
3. Repetir el snapshot [SQL-E READ ONLY](E1-09-SQL-E-conciliacion-asignaciones-readonly.md) **solo si el guard previo aún corresponde al esquema anterior**, con `BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY`, `statement_timeout=10s`, `lock_timeout=1s`, únicamente `vinto_piloto` como `vinto_app`, y `COMMIT`. No publicar OT/usuarios/IDs, ni tocar TVC.
4. Revisar en catálogos `pg_constraint` y `pg_class` las dependencias FK **hacia** OT, versiones, líneas y asignaciones. Solo devolver **esquema/tabla y número de relaciones**, no contenido. Identificar qué tablas requieren una revisión de integridad si se eligiera limpiar datos simulados, antes de diseñar CUALQUIER SQL. No ejecutar borrado, actualizaciones, `TRUNCATE`, ni crear staging de datos.
5. Identificar qué métricas agregadas de capturas, Calidad, auditoría y canales integrados se pueden obtener con privilegios ya existentes; no inventar relaciones. Solo tras inventario de esquema, proponer consultas de conteo que respeten permisos.
6. Documentar estado de permisos **efectivos** MF13 por operación/sector/formulario (Bobinas, Rebobinado, Conversión), no solo suma de concesiones activas. Si el acceso no alcanza, marcar NO VERIFICADO en vez de otorgar permisos.
7. Planificar **sin ejecutar** el método autorizado de verificación del historial de migraciones 0001-0012 y checksum esperado de 0013. `migrate.py --status` del checkout nuevo puede hacer lectura pero requiere credenciales del migrador legítimo: no reutilizar permisos de `backup.sh`; no ejecutar ni abrir `.env` sin mandato independiente.
8. Validar que el flag `WORK_ORDER_LINE_EXECUTION_ENABLED` se mantendrá **OFF en el release nuevo** antes de cualquier activación; configuración del código por defecto no demuestra la efectiva de un proceso futuro. No modificar flags.
9. Registrar si existen usuarios activos, operaciones o integraciones que dependan de las 12 OT simuladas; si la información no está disponible, **NO VERIFICADO**. Un dataset simulado no equivale a dataset desechable.

### Consulta opcional de metadatos FK (NO ejecutada)

Es consulta de catálogo y **no muestra filas de datos**; solamente bajo identidad de DB/rol validada y transacción de solo lectura preautorizada:

```sql
BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY;
SET LOCAL statement_timeout = '10000ms';
SET LOCAL lock_timeout = '1000ms';
SELECT 1 / CASE WHEN current_database() = 'vinto_piloto'
                 AND current_user = 'vinto_app'
                 AND current_setting('transaction_read_only') = 'on'
                 AND current_setting('transaction_isolation') = 'repeatable read'
                THEN 1 ELSE 0 END AS guard;
SELECT c.confrelid::regclass::text AS tabla_referenciada,
       c.conrelid::regclass::text AS tabla_dependiente,
       count(*)::bigint AS fk_definidas
FROM pg_constraint c
WHERE c.contype = 'f'
  AND c.confrelid IN (
    'vinto_txn.work_order'::regclass,
    'vinto_txn.work_order_version'::regclass,
    'vinto_txn.work_order_line'::regclass,
    'vinto_txn.assignment'::regclass
  )
GROUP BY 1,2
ORDER BY 1,2;
COMMIT;
```

No intentar proyectar `pg_constraint` como si fuera el conteo de filas relacionadas: **cuenta claves foráneas definidas**, no el volumen de datos. Si el esquema cambia o la lectura falla, detener y reclasificar.

## 3. Decisión sobre datos simulados

| Ruta | Ventaja | Limitación / condición |
|---|---|---|
| **S1 Conservar y conciliar** | Preserva historial, capturas/auditoría y permite transición por escenario | La reconciliación debe decidirse por Supervisión/QA, sin inferir estados ni falsificar inicios/cierres |
| **S2 Reinicio controlado de datos simulados** | Facilita QA E1 desde cero y elimina bloqueos de legado, **si realmente no hay dependencias** | Requiere inventario de referencias, política de conservación, confirmación de descartabilidad de todas las filas afectadas, SQL específico auditado, respaldo verificable y **GO distinto** para cada mutación |
| **S3 Datos de prueba aislados** | Conserva la VPS actual y evita contaminar el historial | Necesita entorno/recursos aislados y credenciales nuevas, no forma parte de este despliegue |

**Recomendación preliminar:** si las 12 OT y todas sus relaciones son inequívocamente desechables, **evaluar S2**, nunca ejecutarlo por conveniencia. Si no se demuestra, mantener S1 y preparar un plan de transición funcional. No hacer `UPDATE` masivos de `in_production` ni asumir `assignment.finished` = línea lógica `finished`.

## 4. Gates de liberación posteriores (por separado)

1. **P2-A — lectura e inventario:** obtener reporte de release, SQL-E actualizado, FK, permisos MF13, historial migraciones comprobado por canal autorizado, banderas y tratamiento de registros simulados. **Sin SQL mutador, sin ejecutar migrate.py, sin escritura.**
2. **P2-B — migración 0013 aditiva:** solo con autorización explícita, SHA fijo, respaldo intacto, versión y migrador correctos, esquema validado, flag OFF y ruta de contingencia. La reversión del código **no revierte** automáticamente 0013.
3. **P3 — despliegue con flag OFF y smoke legado:** autorización independiente después de P2-B. El preflight clásico de primera instalación puede exigir puertos libres y no debe ejecutarse ciegamente sobre servicio activo.
4. **P4 — resolver dataset simulado y activar E1:** requiere preflight E1-08 sin blockers, matriz MF13 real, QA de escenarios, rollback documentado y aprobación específica. Se prohíbe activar con bloqueantes históricos.

**Dictamen actual:** P1-B PASS; **GO solo para preparar P2-A READ ONLY**. P2-B, P3 y P4 permanecen **NO-GO**.
