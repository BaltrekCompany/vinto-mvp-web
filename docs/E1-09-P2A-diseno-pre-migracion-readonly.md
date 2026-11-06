# VINTO E1-09 — P2-A: diagnóstico previo a migración 0013 (SOLO LECTURA)

**Fecha:** 2026-11-06. **Estado:** DOCUMENTADO, **NO EJECUTADO**.  
**Fuente:** P1-B verificado en VPS por Codex Desktop: `create-and-verify` una sola vez, exit 0, nuevo `.verified`, restauración temporal sin red, 47 tablas / 0 discrepancias, 18 respaldos anteriores intactos. Ver [P1-B](E1-09-P1B-respaldo-verificable-GO-condicionado.md).  
**Repositorio de referencia:** `BaltrekCompany/vinto-mvp-web`, `main@c64893e86a983a86d57f9a7406d0d736417f17e3`.  
**Alcance de P2-A:** análisis documental y, con SSH autorizado aparte, inspección **READ ONLY**, sin cambio de servicios ni datos. **P2-B (aplicar 0013) NO AUTORIZADO**.

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
