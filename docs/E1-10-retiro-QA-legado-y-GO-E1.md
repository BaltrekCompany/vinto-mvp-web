# VINTO E1-10 — Retiro auditado de OT ficticias heredadas para habilitar E1

**Fecha:** 2026-11-07  
**Base congelada:** `d5bc472b831eae8abd60899296ce8c146c119a5a`  
**Estado:** IMPLEMENTACIÓN CANDIDATA EN PR #139 DRAFT (migración, CLI, preflight, tests); **NO MERGEADO / NO APLICADO A PRODUCCIÓN**  
**Autorización:** el usuario confirma que las OT activas observadas son exclusivamente de QA y autoriza preparar el método para limpiar las OT ficticias y desbloquear rápidamente E1. **No equivale a autorización para omitir validaciones de integridad, fabricar ejecución productiva ni borrar auditoría.**

## Resultado del preflight E1-08 en producción

El CLI oficial `python -m app.work_orders.preflight_cli` se ejecutó vía PowerShell/SSH en transacción `REPEATABLE READ READ ONLY`; `E108_PREFLIGHT_EXIT=2`, `technical_preflight_clear=false`, bloqueantes:

- `IN_PROGRESS_ORDERS_WITHOUT_EXECUTION`: **13 OT en progreso**, **18 líneas baseline** sin fila lógica E1.
- `ACTIVE_ASSIGNMENTS_WITHOUT_EXECUTION`: **9 asignaciones activas** sin fila lógica E1, distribuidas en **MP1, MP3, GAMBINI, OMET_I, BELOIT, COPASA, OVER, PERICHUN y TUBETERA**.
- `active_in_production=0`, `active_enabled=0`.
- Migración 0013 e índice/trigger de exclusividad y `vinto_app_privileges` PASS; `active_assignments_on_closed_orders=0`, `active_assignments_unmapped_to_baseline=0`.

**E1 sigue OFF**: `WORK_ORDER_LINE_EXECUTION_ENABLED=false`. G4 (migraciones 0013/0014) y G5 (release productivo) PASS. **No** repetir migraciones existentes ni rollback SQL.

## Decisión de dominio

1. `assignment.status='finished'` significa **asignación de turno terminada**. No equivale a línea E1 `finished` ni a OT `closed`.
2. `work_order.status='in_progress'` sigue describiendo el estado histórico original de la OT. No convertir a `draft` ni a `closed` por SQL; ambos tergiversarían la historia. No crear filas E1 `in_production/finished` ficticias para evitar el preflight.
3. El archivado ordinario 0014 sólo acepta `draft/published` **sin asignaciones jamás**. Las 13 legadas requieren una vía **excepcional, explícita y auditable** de retiro QA. Conservar la restricción ordinaria.
4. El retiro debe ser **reversible únicamente por un procedimiento autorizado independiente**, nunca por el botón normal «Restaurar» mientras E1 está ON: restaurar una OT `in_progress` sin ejecución haría reaparecer la incompatibilidad. Debe preservarse visibilidad histórica para personal gestor autorizado, no para operación.
5. No borrar ninguna OT, versión, línea, asignación, captura, bobina, control de Calidad ni evento de auditoría; no cambiar importes, cantidades o identificadores.

## Diseño mínimo propuesto: retiro QA con marca inequívoca

**Esquema aditivo 0015** (código posterior al 0014 y sin modificar 0013/0014):

- Introducir una marca exclusiva `work_order.qa_retired_at` (timestamp) y `qa_retired_by` / `qa_retired_reason` o equivalente con FK y CHECK, vinculada a `archived_at` para reutilizar el filtro de visibilidad y el historial de Jefatura.
- Sólo permitir `qa_retired` cuando la OT estaba `in_progress`, se confirmó su identidad en un manifiesto **cerrado de OT QA**, E1 está OFF, no tiene ejecuciones lógicas `in_production`, y **no existen asignaciones activas al confirmar el retiro**. Conservar `status='in_progress'` como estado histórico.
- En el trigger 0014, mantener la regla ordinaria `draft/published` sin asignaciones, y abrir el caso especial **sólo** con marca QA, actor/autorización, motivo y ausencia verificada de asignaciones activas; sin bypass de UPDATE de identidad ni saltarse trigger/auditoría.
- Evitar `restore` ordinario de OT QA retirada (409/acción oculta), y proteger escrituras de asignaciones nuevas sobre OT archivada mediante el trigger actual de archivo. Evitar que el usuario pueda cambiar la marca QA para eludir preflight.
- Restringir la operación a un comando de mantenimiento de identidad privilegiada / operador que exija `--manifest` de OT exactas, `--dry-run` y `--apply`, identificador de actor válido y motivo claro. **Ningún endpoint público genérico que permita archivar cualquier OT `in_progress`.**

**Transacción de retiro** (preferible todo o nada para las 13 OT, en ventana de mantenimiento):

1. Validación read-only del manifiesto exacto (OT IDs/números y controles de ownership) y sus relaciones: estados, líneas, asignaciones históricas activas/finalizadas, capturas, bobinas, Calidad, ejecuciones lógicas, visibilidad por sector; rechazar OT que no se confirmaron como QA. Comparar conteos esperados **13 / 18 / 9** con el corte inmediatamente previo; si hubo drift, STOP y volver a auditar, no modificar el manifiesto silenciosamente.
2. Verificar respaldos **actuales** de PostgreSQL MVP con restore de prueba e integridad, preferiblemente copia **fuera de la VPS**; el P1-B del 06/nov es anterior a estas pruebas y no protege todos los cambios actuales. TVC fuera de alcance.
3. Bloquear nuevas capturas/activaciones de las OT QA durante ventana; comprobar ausencia de escrituras concurrentes en MVP.
4. En **una transacción** con locks en orden OT → máquinas ordenadas → asignaciones, registrar actor/request_id/motivo, y marcar las 9 asignaciones QA `active` como `finished` usando las mismas reglas de fin de turno, sin inventar estados de línea. Verificar 0 activas para cada OT del manifiesto.
5. Retirar excepcionalmente las 13 OT con `archived_at` y marca QA explícita. Verificar filas afectadas exactas y conservar status y referencias; si una condición falla, ROLLBACK completo, sin reintentos automáticos. Evitar loops de servicio que abran una transacción por OT y dejen avance parcial.
6. Validar conteos: 13 QA retiradas, 0 asignaciones activas del grupo, 18 líneas preservadas, histórico de asignaciones/capturas/bobinas/Calidad sin pérdidas, 0 OT no incluidas alteradas, backend/DB sanos.
7. Ajustar `rollout_preflight` **solo para excluir OT formalmente retiradas** en los conteos de bloqueo de órdenes `in_progress` y líneas correspondientes; añadir una guarda que sea **NO-GO si cualquier asignación `active` pertenece a una OT retirada**, o si algún registro no retirado carece de fila de ejecución. **Nunca** filtrar genéricamente todo `in_progress`, ni declarar PASS simplemente por poner un booleano.
8. Reejecutar `E108_PREFLIGHT` con el release nuevo: exit 0 y `technical_preflight_clear=true` **solo si no quedan bloqueantes en OT no retiradas**.

**UI y API:** excluir OT retiradas de consultas operativas por defecto; listado histórico sólo para personal gestor, con distintivo **«Retirada de QA · histórica»**, estado original en lectura, acción Restaurar deshabilitada para estas OT; los permisos `work_order.manage`, `assignment.manage` y MF13 conservan sus contratos. Revisar todas las proyecciones de Seguimiento, asignaciones, F3 y F6 para que las OT QA retiradas no sean seleccionables ni capturables. Evitar revivirlas si se cambia turno.

## Condiciones de seguridad y pruebas obligatorias antes de liberar

- Modo ON **no se toca** hasta que 0015 esté desplegada, migraciones verificadas, retiro QA completado y preflight E1-08 PASS.
- QA con PostgreSQL 17 aislado: archivo normal 0014 sigue rechazando `in_progress` con asignaciones; retiro QA exige manifiesto/actor/motivo; transacción atómica y locks; rechazo por captura concurrente, OT ajena, drift, falta de backup, permisos o ejecuciones lógicas existentes; no pérdida de capturas/Calidad/auditoría; trigger impide nuevas asignaciones; intento de restauración ordinaria falla; permisos de rol / HTTP. Verificar que 13/18/9 cambian exactamente como se planeó en QA de prueba.
- Pruebas de reversión: **apagado del flag** y rollback binario seguro no revierten automáticamente el esquema ni retiran registros auditados. Definir procedimiento separado para revertir un retiro erróneo, sin restauración casual de legados.
- QA del flujo E1 tras GO: Supervisión habilita/inicia líneas, exclusividad por máquina, Operación F3/F6, finalización, bloqueo de nuevas capturas, cierre manual de OT; cubrir Bobinas, Conversión y Rebobinado antes de considerar la compuerta global estable.
- Salud: backend/frontend/API HTTP 200, E1 nuevo OFF durante transición, sin incidentes en otros servicios ni TVC.

## STOP / NO-GO

Abortar si no existe backup actual verificable; si el manifiesto no identifica sin ambigüedad las 13 OT QA; si existen actividades productivas o escrituras simultáneas; si aparece una asignación o captura inesperada; si algún registro es real; si la transacción no es atómica; si varían conteos o falla una prueba. **No** ejecutar `UPDATE work_order SET status='draft'`, `DELETE`, `TRUNCATE`, falsificar `in_production/finished`, modificar migraciones antiguas ni encender E1 global para «probar y ver».

## Estado de ejecución

La rama de PR #139 incluye **código candidato** para la migración 0015, el CLI atómico `app.work_orders.qa_retirement_cli`, un generador read-only de manifiesto `app.work_orders.qa_retirement_inventory_cli`, cambios de preflight, protecciones de restauración y tests en base efímera. **NO está mergeado ni desplegado ni se ha aplicado retiro alguno.** Las pruebas CI deben pasar y el código requiere revisión técnica antes de autorizar un merge.

### Contrato de operación del código candidato (solo tras PR aprobado, backup nuevo y despliegue)

1. Ejecutar primero el CLI de inventario **de solo lectura** desde el backend del release aprobado usando la identidad de servicio, `--actor-display-name "QA Jefatura" --output <archivo_privado_nuevo.json>`. El generador es conservador: exige exactamente **13 OT in_progress, 18 líneas baseline, 9 asignaciones activas**, busca un actor Jefatura activo único, y crea un JSON privado con modo 0600. Si el corte difiere, STOP. No asumir que el conteo certifica el carácter ficticio: revisar el manifiesto con el responsable QA.
2. Ejecutar `python -m app.work_orders.qa_retirement_cli --manifest <archivo_privado.json>` **sin `--apply`** para el DRY RUN, validar todos los conteos y revisar asociaciones sin capturas simultáneas.
3. El comando `--apply` requiere respaldo actual verificado (incluida copia fuera del host y prueba de restauración), E1 OFF, manifiesto exacto y confirmaciones de operador vía variables `VINTO_QA_RETIREMENT_CONFIRMED=yes`, `VINTO_QA_BACKUP_VERIFIED=yes`, `VINTO_QA_OFFHOST_VERIFIED=yes`. Las variables son **atestaciones adicionales**, no comprobación autónoma de integridad del backup.
4. La operación en una transacción toma locks en orden OT → máquinas → asignaciones, finaliza solo las asignaciones activas del manifiesto, marca QA-retirada cada OT y verifica que no queden activas; ante cualquier condición inesperada hace ROLLBACK total.
5. Revalidar el esquema, `check-release`, salud, invariantes y preflight E1-08; luego proceder a evaluación de habilitación del flag ON con QA funcional por sectores, bajo ventana y plan de retorno.

**Importante:** no ejecutar este código directamente desde la rama DRAFT ni sobre el release activo actual `d5bc472b...` porque no incorpora 0015; tampoco copiar archivos aislados al VPS para eludir la instalación por SHA. Mantener `main` y `current` productivos sin cambios hasta revisión, CI y nueva liberación controlada.
