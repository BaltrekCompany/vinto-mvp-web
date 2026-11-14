# VINTO E1-09 — Decisión técnica preliminar: archivado funcional y transición del legado ficticio

**Fecha:** 06/nov/2026. **Estado:** PROPUESTA PARA REVISIÓN; no implementado ni desplegado.  
**Fuentes:** P2-A1, P2-A2 y P2-A3 (Codex SSH, lectura únicamente). [Resultados consolidados](E1-09-P2A-diseno-pre-migracion-readonly.md).  
**Código consultado:** `main@c64893e86a983a86d57f9a7406d0d736417f17e3`, `backend/app/work_orders/service.py`, `router.py`, `authz/visibility.py` y `rollout_preflight.py`.

## 1. Qué sabemos y qué no

- `vinto_piloto` contiene **20 OT**: 7 draft, 12 in_progress, 1 published, ninguna closed. Las 12 in_progress contienen **16 líneas baseline**, 72 asignaciones (11 active / 61 finished) y 63 capturas submitted enlazadas.
- Las 63 capturas vinculadas tienen 1.151 detalles, 19 filas de grupo, 5 bobinas con captura fuente y 5 decisiones de Calidad sobre esas bobinas. Fuera de esa cadena: 21 capturas sin assignment_id (MP1:14, MP3:7, todas submitted), 204 detalles. Las claves consultadas no agotan todas las posibles referencias semánticas.
- `vinto_audit.audit_event` y `import_record`: USAGE esquema PASS, SELECT DENIED. `vinto_meta.schema_migration`: USAGE y SELECT DENIED para `vinto_app`. Es el contrato de privilegios existente; **no cambiarlo**.
- **Visibilidad exacta por usuario NO VERIFICADA**. `service._HEADER_SQL` usa alcance sectorial y máquinas de línea; `visibility.legacy_scope` puede restringir por máquina bajo `authz_assignment_reads_mode=enforce` o compuerta multimáquina, mientras que `observe` no modifica respuesta. No asumir que el conjunto global de 20 equivale a cada lista de usuario.
- No hay actualmente columna de archivado, endpoint de borrado ni filtro nativo para ocultar OT históricas. `work_order_version` y `work_order_line` publicados, `capture` y `audit_event` tienen protecciones para borrado; las FKs hijas usan mayoritariamente ON DELETE RESTRICT.
- La migración **0013 es aditiva sin backfill**. E1-08 cuenta `in_progress` y `active` sin ejecución lógica independientemente de la vista de usuario. Por ello, ocultar OT no permite activar E1.
- P1-B verificó restauración aislada de 47 tablas y 0 discrepancias de recuentos, pero los backups viven en el mismo filesystem del VPS; copia off-host no verificada.

## 2. Alternativas

| Enfoque | Ventaja | Límite decisivo |
|---|---|---|
| Eliminar físicamente 20 OT y dependientes | Lista y universo de BD vacíos | **No-go**: se enfrenta a FKs, inmutabilidad, 63 capturas submitted, bobinas/Calidad y auditoría no inspeccionada; romper invariantes no está autorizado |
| Marcar OT históricas como archivadas, filtrar la vista operativa | No pierde capturas/Calidad/bitácora; usuario trabaja con OT nuevas | Requiere desarrollo de modelo/API/UX, seguridad y QA; no resuelve automáticamente `in_progress`/11 `active` para E1-08 |
| Entorno limpio separado | Permite QA sobre un dataset nuevo conservando el antiguo | Coste operativo adicional e identidad/permisos/configuración que han de replicarse de forma controlada; no hacer switch de DB sin autorización |
| Transición/corte explícito del legado + archivado | Conserva integridad y habilita futura activación E1 si las reglas del preflight se mantienen | La semántica de cancelación o cierre de OT ficticias **aún no está definida**, y el cierre normal exige líneas lógicas finished y ausencia de assignments active |

**Recomendación de diseño:** preferir **archivado funcional con conservación de historial** y, en una fase distinta, proponer **transición explícita y auditable del legado ficticio**. No modificar ni reinterpretar hechos de captura para forzar cierre lógico. Si las reglas de cierre/activación no permiten resolver OT legadas, evaluar un estado propio de cancelación/cuarentena **con controles y preflight diseñados expresamente**, no excluir silenciosamente filas activas del preflight.

## 3. Contrato mínimo de un eventual archivado

No es código autorizado; son requisitos sujetos a revisión:

1. **Alcance**: definir OT candidatas por conjunto exacto y condición ficticia verificable. "20 OT globales" no determina "OT visibles" de un actor. Abarcar todas sus máquinas de línea, no solo cabecera; filtros efectivos MF13.
2. **Persistencia**: nuevo atributo/evento de archivado con actor, fecha y motivo auditables, y reglas de habilitar/deshabilitar historial. No borrar ni alterar capturas, bobinas, calidad, snapshots o auditoría.
3. **Consulta**: lista operativa excluye archivadas **por defecto**; los perfiles autorizados pueden ver historial con filtro explícito. Definir comportamiento de detalle, links profundos, reportes, exportaciones y resoluciones por asignación sin leaks entre sectores.
4. **Mutaciones**: una OT archivada no debe aceptar nuevas asignaciones/capturas/activaciones ni un cierre oportunista. No basta filtrar la lista: las rutas de escritura del backend deben validar su estado explícitamente.
5. **Integridad**: si se propone archivar una OT `in_progress` que tiene asignaciones `active`, detener hasta resolver reglas de transición. Nunca convertir `finished` de asignación en ejecución lógica `finished`, falsificar `started_at` o suprimir triggers.
6. **Feature flags/QA**: despliegue con flag E1 OFF y pruebas negativas; autorización por rol/sector/máquina, historial restaurable, no regresión de Bobinas/Conversión/Rebobinado.
7. **Contingencia**: reversión de visibilidad (no rollback que borre evidencia), catálogo histórico intacto y respaldo restaurable, con riesgo de único filesystem documentado.
8. **Separación E1**: archivar/ocultar no cambia la condición lógica `orders_in_progress` ni `active_assignments`. La activación requiere un diseño separado que elimine bloqueantes **legítimamente**, y un preflight E1-08 PASS con historial de migración 0013 comprobado.

## 4. Gates próximos y autorizaciones

- **G0 — completado**: inventario real de dependencias funcionales de P2-A2/A3, **PASS**, sin otorgar SELECT de auditoría ni migraciones. Auditoría/importaciones y visibilidad por sesión siguen NO VERIFICADOS.
- **G1 — siguiente**: QA de las OT realmente visibles con una cuenta de Jefatura/Supervisión y otra de Operación, **sin imprimir usuarios ni IDs**; medir distribución por sector y detectar diferencia entre modo `observe`/`enforce` en el release. Requiere autorización para esas consultas/acciones de lectura a través de la aplicación.
- **G2 — diseño**: especificar archivado, estrategia de transición de las 11 asignaciones activas y tratamiento de las 12 OT en curso, con pruebas y rollback. Decisión funcional de Supervisión/QA y revisión de integridad. **Sin UPDATE/DELETE/ALTER** durante diseño.
- **G3 — historial de migraciones**: verificar migraciones 0001–0012 y checksum previsto de 0013 mediante **rol migrador legítimo y canal separado**, sin conceder acceso a `vinto_app` ni reutilizar arbitrariamente `docker/.env`. La consulta del migrador y P2-B (migración mutadora) exigen autorización/ventana propias.
- **G4 — implementación**: PRs independientes para archivado y, si procede, transición del legado. QA de código, inspección de SQL, rollback, deployment con flag OFF y decisión independiente para activar.
- **G5 — datos**: cualquier actualización/archivado de las OT ficticias **requiere plan exacto de filas/impacto y aprobación mutadora distinta**, idealmente copia adicional fuera del host antes del primer cambio de datos.

**NO-GO actual:** DELETE masivo de las OT, desactivar triggers, elevar permisos `vinto_app`, modificar historia, migración 0013, deploy, cambio de flag o tocar TVC.

**Resultado de la fase actual:** solo diseño e inventario respaldados por el reporte de Codex; este documento no ordena ejecutar SQL en el VPS.
