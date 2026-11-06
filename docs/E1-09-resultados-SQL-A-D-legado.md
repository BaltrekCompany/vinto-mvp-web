# VINTO E1-09 — Evidencia del diagnóstico real SQL-A a SQL-D

**Origen:** informes agregados de Codex Desktop ejecutados mediante conexión SSH autorizada en VPS; ChatGPT no tuvo acceso SQL directo.  
**Entorno:** PostgreSQL 17 del MVP, contenedor `vinto-mvp-postgres`, base `vinto_piloto`, rol `vinto_app`. **TVC fuera de alcance**.  
**Estado:** DIAGNÓSTICO TÉCNICO DEL LEGADO PASS; OPERACIÓN / ACTIVACIÓN NO-GO.  
**Release efectivo:** `86e4ec4fa6f6bf95c0e099279d8c51a016c7a6a4` = `main` pre-E1.

## Disciplina de ejecución confirmada

Las fases SQL-A/B/C/D reportaron transacciones `REPEATABLE READ READ ONLY`, `COMMIT` cuando correspondía, tiempos limitados y salida agregada. No se hicieron migraciones, DML, DDL, servicios, merges ni acceso a secretos. SQL-A inicial detuvo la ejecución al descubrir `permission denied for schema vinto_meta` — permiso intencionalmente restringido al rol aplicativo.

- SQL-A2 confirmó `USAGE` y `SELECT` sobre tablas funcionales de `vinto_txn` y `vinto_master`; `vinto_meta` permanece restringido.
- SQL-A3 validó **19/19** columnas previstas, todas con `SELECT`.
- `work_order_line_execution` no apareció como relación r/p/v en el catálogo; el release activo **no contiene migración 0013** ni reconoce `WORK_ORDER_LINE_EXECUTION_ENABLED`.
- El historial **real** de `vinto_meta.schema_migration` permanece **NO VERIFICADO**, no debe concederse acceso extra a `vinto_app` solo para leerlo.

## SQL-B: distribución

| Estado OT | Cantidad |
|---|---:|
| draft | 6 |
| published | 1 |
| in_progress | 12 |

| Estado asignación | Cantidad |
|---|---:|
| active | 11 |
| finished | 61 |

| Sector | Máquina | Asignaciones activas | OT distintas |
|---|---|---:|---:|
| BOBINAS | MP1 | 2 | 1 |
| BOBINAS | MP3 | 2 | 1 |
| CONVERSION | GAMBINI | 1 | 1 |
| CONVERSION | OMET_I | 1 | 1 |
| REBOBINADO | BELOIT | 1 | 1 |
| REBOBINADO | COPASA | 1 | 1 |
| REBOBINADO | OVER | 1 | 1 |
| REBOBINADO | PERICHUN | 1 | 1 |
| REBOBINADO | TUBETERA | 1 | 1 |

Controles de integridad agregada: `active` sobre OT cerrada = **0**; `active` en versión no operacional = **0**; máquinas con asignaciones activas de OT distintas = **0**.

## SQL-C: alcance para Supervisión

| Asignaciones activas por OT en progreso | OT | Líneas baseline |
|---|---:|---:|
| 0 | 4 | 5 |
| 1 | 7 | 7 |
| Varias | 1 | 4 |
| **Total** | **12** | **16** |

Todas las **11** asignaciones `active` pertenecían a OT `in_progress`. Cero en otros estados o sin OT asociada.

## SQL-D: conciliación técnica de referencias

- `line_code` existe en `vinto_txn.work_order_line`.
- **11/11** asignaciones activas tienen una sola línea baseline coincidente por OT + `line_code` + máquina.
- **0** activas sin coincidencia; **0** ambiguas; **0** líneas baseline asociadas a múltiples asignaciones activas.
- **5** líneas baseline de OT `in_progress` sin asignación activa.
- MP1: 2 asignaciones activas, 1 OT distinta, 2 mapeos únicos, 0 anomalías.
- MP3: 2 asignaciones activas, 1 OT distinta, 2 mapeos únicos, 0 anomalías.

**Alcance de PASS:** consistencia de relaciones de las asignaciones activas durante el snapshot SQL-D. No es certificado permanente ni evidencia de producción física, turno vigente, cantidades realmente producidas o historial de migraciones; repetir comprobaciones inmediatamente antes del corte.

## Decisiones y bloqueantes

1. **Cerrado — conciliación técnica de referencias legadas**: no hay que reparar mapeos para las 11 asignaciones activas medidas.
2. **Pendiente — conciliación funcional por Supervisión**: 12 OT `in_progress`, 16 líneas baseline. Revisar estado real de cada línea; prioridad MP1 y MP3 (dos líneas habilitadas cada una) y cinco líneas sin asignación activa. `assignment.active` NO significa `in_production`, tampoco `assignment.finished` equivale necesariamente a finalización de línea. No realizar backfill ni reetiquetado automático.
3. **Pendiente — operación entre turnos**: el contrato E1-01 reconoce la continuidad lógica posible tras vencimiento de la asignación, pero exige aclarar cómo Supervisión habilita/captura en nuevo turno sin pausa, cierre ficticio ni traspaso automático.
4. **Pendiente — autorización MF13 y cobertura por sectores/máquinas**, salud de versiones finales, historia SQL migratoria por mecanismo autorizado, respaldo verificable, rollback, QA manual controlado en producción, ventana de corte.
5. **Sin merge/despliegue**: PRs #118, #120, #122, #124, #126, #128 y #130 siguen DRAFT, abiertos, mergeable. Se apoyan en cadena y requieren retarget/validación secuencial. PR documental E1-09 #132 también DRAFT.

### Evaluación de puertas

| Puerta | Decisión |
|---|---|
| Diagnóstico SQL-A/B/C/D de integridad actual | PASS |
| Conciliación física con Supervisión | PENDIENTE |
| Revisión operativa de cambio de turno | PENDIENTE |
| Merge de cadena E1 | PENDIENTE APROBACIÓN Y REVISIÓN FINAL |
| Migración 0013 | NO EJECUTADA |
| Despliegue en VPS | NO EJECUTADO |
| Activar WORK_ORDER_LINE_EXECUTION_ENABLED | NO-GO |

## Próxima actuación recomendada

Preparar una matriz funcional interna por OT/línea para que Supervisión valide condiciones reales (sin publicar IDs individuales ni datos sensibles en issues públicos). Validar primero permisos y procedimiento de lectura de estos detalles; no ejecutar SQL nuevo sin autorización. Separar formalmente la decisión de **merge con flag OFF** de la decisión de **despliegue/migración** y de **activación con flag ON**.
