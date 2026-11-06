# VINTO E1-09 — Evidencia del diagnóstico real SQL-A a SQL-D

**Origen:** informes agregados de Codex Desktop ejecutados mediante conexión SSH autorizada en VPS; ChatGPT no tuvo acceso SQL directo.  
**Entorno:** PostgreSQL 17 del MVP, contenedor `vinto-mvp-postgres`, base `vinto_piloto`, rol `vinto_app`. **TVC fuera de alcance**.  
**Estado:** DIAGNÓSTICO TÉCNICO DEL LEGADO PASS; OPERACIÓN / ACTIVACIÓN NO-GO.  
**Release efectivo:** `86e4ec4fa6f6bf95c0e099279d8c51a016c7a6a4` = `main` pre-E1.

**Actualización de vigencia (06/nov/2026):** esta es evidencia del *snapshot histórico* previo a la integración. Los 7 PR E1-02 a E1-08 se fusionaron posteriormente en GitHub, con `main@a8a8beaf611e8d892658eeabb5a5e1b972a32316`; ello **no actualizó automáticamente el VPS**. El release remoto citado es el último verificado por SSH, no una constatación nueva. Antes de cualquier corte, repetir lecturas con [SQL-E](E1-09-SQL-E-conciliacion-asignaciones-readonly.md) y obtener confirmación funcional de Supervisión.

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


## Actualización posterior al corte SQL-D — E1-09

- **GitHub integrado:** 7/7 PR (#118, #120, #122, #124, #126, #128, #130) fusionados. QA diferencial final [run 42169307786](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/42169307786) PASS; 0 regresiones nuevas detectadas, deuda histórica documentada en #134 y #135.
- **VPS:** no se ejecutó despliegue ni migración 0013 por esta integración. Estado actual de la VPS, datos en el momento de corte y bandera real siguen **por reconfirmar**.
- **Conciliación SQL-A/D:** 11 asignaciones activas con correspondencia única y 5 líneas baseline sin activa, **válido exclusivamente en el snapshot observado**. La nueva lectura [SQL-E](E1-09-SQL-E-conciliacion-asignaciones-readonly.md) determina cuántas de esas líneas tienen `assignment.finished` histórico, sin inferir estado físico.
- **Decisión:** GO técnico para preparar SQL-E de solo lectura; **NO-GO despliegue/migración/flag ON** hasta conciliación con Supervisión, permisos MF13, verificación de release/privilegios y respaldo/rollback. TVC queda fuera del alcance.


## SQL-E — ejecución real y conciliación histórica (06/nov/2026)

**Origen:** resultado agregado reportado por el ejecutor Codex Desktop a través de su conexión SSH ya autorizada; ChatGPT no ejecutó SQL en el VPS ni verificó personalmente los logs crudos. **Dictamen: SQL-E PASS** para el snapshot informado.

- **E0:** `vinto-mvp-postgres` saludable; conexión a `vinto_piloto` con `vinto_app`; aislamiento `REPEATABLE READ READ ONLY`; guard de esquema pre-E1 satisfecho, bloque `E0-E4` con `COMMIT`. No se consultó `vinto_meta`, no se expusieron identificadores ni se realizaron escrituras.
- **E1:** 11 asignaciones activas; 11 mapeos únicos por OT + `line_code` + máquina; 0 sin baseline, 0 ambiguas, 0 de versión no operativa.
- **E2:** 16 líneas baseline de OT `in_progress`; 11 con exactamente una asignación activa; 0 con varias activas; 5 sin asignación activa. Las **5/5** sin activa tienen al menos una asignación histórica con `status='finished'`; **0** sin historial relacionado. Total de asignaciones activas mapeadas: 11.
- **E3:** las cinco líneas sin activa están en **BOBINAS**: **MP1: 4** (las 4 con historial `assignment.finished`); **MP3: 1** (la 1 con ese historial). Sin historial de asignación: 0 en ambas.
- **E4:** 4 OT sin ninguna activa (5 líneas baseline, 0 activas); 7 OT con una activa (7 líneas, 7 activas); 1 OT con varias activas (4 líneas, 4 activas).
- **Conciliación cruzada:** E1 = E2 en activas mapeadas (11); E2 = 11+0+5 = 16; E2 sin activa = 5+0 = 5; E3 = 4+1 = 5; E4 = 12 OT, 16 líneas y 11 activas. Todas las igualdades PASS.
- **Comparación SQL-D → SQL-E:** coinciden los totales centrales (11 activas / 16 líneas / 5 sin activa); **no implica identidad de cada registro entre dos snapshots**. Los nuevos datos clasifican las cinco por historial `finished`, no por estado físico de producción.

### Puertas después de SQL-E

| Control | Estado | Alcance |
|---|---|---|
| Integridad referencial / conteos SQL-E | **PASS** | Snapshot agregado de lectura |
| Estado histórico `assignment.finished` de cinco líneas | **5/5 comprobadas** | Finalización de asignación, no de la línea lógica |
| Estado físico de las cinco líneas (MP1 4, MP3 1) | **PENDIENTE Supervisión** | Confirmar finalización real, producción actual o continuidad |
| Estado físico de las once líneas con activa | **PENDIENTE Supervisión** | Confirmar cuál está produciendo, sin deducirlo de `active` |
| Historial `vinto_meta.schema_migration` | **NO VERIFICADO** | Mantener restricciones del rol `vinto_app` |
| Migración 0013 / deploy / activación | **NO-GO** | Son decisiones independientes; no ejecutar |

**Decisión:** el bloque técnico SQL-A/B/C/D/E del legado está conciliado al nivel de agregados. No hay evidencia que exija modificar 11 asignaciones activas ni las cinco sin activa. La siguiente intervención **no es una corrección automática**: Supervisión debe revisar privadamente las 16 líneas (priorizando MP1/MP3), asignar un estado físico validado y registrar la continuidad entre turnos. No publicar números de OT, `line_code`, usuarios, capturas ni otras referencias individuales en GitHub. Repetir preflight antes del corte; no asumir que los totales siguen vigentes.
