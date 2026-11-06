# VINTO — E1-08 Matriz de QA, integración y criterio de GO/NO-GO

**Fecha del corte técnico:** 05-06/nov/2026 (America/Lima).  
**Repositorio:** `BaltrekCompany/vinto-mvp-web`. `main` no modificada en este proceso.  
**Objetivo:** E1-02 ... E1-08 para inicio, ejecución, finalización y cierre manual de OT; no despliegue.

## Secuencia y cobertura de PR

| Entregable | PR | Dependencia | Control |
|---|---:|---|---|
| E1-02: modelo SQL 0013 | #118 | `main` | índice exclusivo/trigger/inmutabilidad; FLAG OFF |
| E1-03: API de inicio/final de línea | #120 | #118 | candados, transición y exclusividad |
| E1-04: protección de capturas | #122 | #120 | F3 y `POST /api/captures` comparten `lock_active_assignment` |
| E1-05: panel Supervisión | #124 | #122 | inicio/final con capacidad servidor |
| E1-06: pantalla Operación | #126 | #124 | selector de la línea `in_production` |
| E1-07: cierre total manual de OT | #128 | #126 | solo Supervisión, todas las líneas finalizadas |
| E1-08: compatibilidad sectores y diagnóstico legado | #130 | #128 | Rebobinado y Conversión, preflight agregado READ ONLY |

Todos los PR se mantienen **DRAFT**. Un PR apilado debe integrarse en `main` **solo tras fusionar su padre y verificar que la comparación con `main` contiene exclusivamente sus cambios**. Retarget al branch principal antes de cada merge, nunca fusionar un hijo en la rama temporal padre esperando que eso alcance automáticamente `main`. Preferir merge commit que preserve la ascendencia de los PR; si el repositorio requiere squash o rebase, recalcular/revisar cada diff y retarget antes del siguiente merge. Utilizar `expected_head_sha` como defensa contra cambios concurrentes.

## Matriz verificable

| Criterio | Evidencia | Resultado |
|---|---|---|
| Exclusividad 1 máquina / 1 línea en producción | PG17 E1-03, unique parcial 0013 | PASS en CI |
| Habilitar ≠ iniciar; finalizar no cierra OT | PG17 E1-03/E1-07 | PASS en CI |
| Cierre manual con déficit sin motivo obligatorio | PG17 E1-07 y UI | PASS en CI |
| Capturas F3/F6 protegidas transaccionalmente | PG17 E1-04 | PASS en CI |
| Rutas centrales candidatas protegidas por servicio compartido | Revisión de `CENTRAL_FORM_CODES` y `lock_active_assignment` | PASS revisión estática |
| Calidad por bobina/máquina independiente de inicio OT | Revisión de endpoints de Calidad | PASS revisión estática |
| Selector de Operación por máquina en Bobinas | Tests E1-06 | PASS en CI |
| Selector y panel de ejecución en Rebobinado/Conversión | Tests E1-08, TS y lint | PASS en CI |
| Grupos y concesiones MF13 en PostgreSQL sintético | E1-06 + E1-08 | PASS en CI |
| Identificación de asignaciones pre-0013 sin backfill | `test_rollout_preflight_e108.py` | PASS en PG17 sintético |
| Preflight `REPEATABLE READ READ ONLY` + checksum 0013 | CLI y tests E1-08 | PASS en PG17 sintético |
| Concesiones reales por máquina y sector | VPS, lectura autorizada | **PENDIENTE** |
| Asignaciones activas y OT históricas en base real | CLI E1-08 sobre VPS | **PENDIENTE / NO-GO** |
| Backup probado, versión de servidor, flags y migraciones reales | E1-09 | **PENDIENTE** |
| QA manual en producción, sin entorno QA separado | E1-09, con guion aprobado | **PENDIENTE** |

**Importante:** PASS en base efímera no prueba que las asignaciones de la VPS sean compatibles. No declarar aptitud operativa sin diagnóstico y reconciliación del entorno real.

## Criterio de corte de entrega 1

1. **NO-GO para activar la compuerta** si el diagnóstico E1-08 indica `blockers` o si la versión del frontend/backend no está alineada.
2. **NO-GO para liberar a producción** sin permisos efectivos, respaldo, rollback y validación manual.
3. Las OT parcialmente producidas pueden cerrarse tras finalizar todas sus líneas; el déficit sigue visible en indicadores, sin exigir texto libre ni crear OT automáticamente.
4. Las líneas legadas sin estado lógico **no** deben asumirse `in_production`. Resolverlas con Supervisión en un corte funcional; nunca ejecutar `UPDATE` masivo inventando inicios.
5. La anulación de una línea sin producción y la reprogramación son otras entregas. No se incluyen ni se sustituyen por un cierre ficticio.

## Merge / despliegue

No ejecutar merges sin cerrar la matriz técnica y contar con la aprobación de integración. Aun fusionada la cadena, la compuerta debe permanecer OFF hasta E1-09. La versión `main` y las imágenes instaladas en VPS son estados diferentes, y se controlan por separado.

**Evidencia:** GitHub Actions de la rama del PR #130; documento de rutas `docs/E1-08-auditoria-compatibilidad-sectores.md`; diagnóstico `docs/E1-08-preflight-legado-readonly.md`; ticket E1-08 #129.