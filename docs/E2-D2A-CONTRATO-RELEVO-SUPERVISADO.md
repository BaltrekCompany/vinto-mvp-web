# VINTO E2-D2-A — contrato de relevo supervisado de línea habilitada sin inicio

**Estado:** propuesta de diseño y puertas de seguridad. **No implementa endpoints, migraciones, cambios de datos, nuevas banderas ni modificación de producción.** Rama separada de E2-D1. No autoriza merge productivo ni habilitación. Vinculado a #147.

## 1. Base confirmada en `main` (`7aa4b8decf0e187cd73247ee633d5a4a6be840e5`)

- E2-D1 cubre **solo líneas que nunca tuvieron asignación ni ejecución** y exige otra línea activa de la misma OT. No relajar ese contrato para D2.
- Una `assignment` representa el **turno**, mientras `work_order_line_execution` representa el **estado lógico** por línea baseline: `planned / enabled / in_production / finished`; no existe `paused`.
- `assignments.finish` puede finalizar una asignación no productiva sin cerrar E1, pero por sí sola **no congela** la línea: otra asignación o `start_line` puede ocurrir después.
- `start_line` bloquea OT -> máquina -> asignación -> ejecución; las capturas F3/F6 tienen su propio orden de máquina/asignación. Diseñar D2 para no introducir el orden inverso ni un hueco TOCTOU.
- E2-C1 acusa por (asignación, versión, usuario) mientras la asignación está activa. E2-C2 acusa por (versión OT, usuario de Supervisión). **Hoy esos acuses son informativos y no detienen el inicio/captura.**
- No se puede usar `assignment.active` como prueba de producción cero. El inventario E2-D0 es agregado y explícitamente NO es una autorización de escritura.

## 2. Alcance propuesto para D2

Reprogramar **PV / artículo / cantidad / fecha**, nunca máquina ni `line_code`, en una **OT `in_progress`**, sobre una **línea habilitada pero aún no iniciada**, con al menos una asignación histórica, después de un relevo explícito de Supervisión y antes de asignar la nueva versión a Operación.

**Exclusiones bloqueantes:** cualquier `started_at`, E1 `in_production` o `finished`, capturas F3/F6 o evidencia histórica de producción, estado legacy indeterminado, OT cerrada/archivada/retirada QA, asignación conflictiva, alcance parcial de sectores/máquinas, falta de versión esperada, ausencia de confirmación de Supervisión. D3 se reserva para líneas ya produciendo o con evidencia de producción.

## 3. Propuesta de flujo — con congelación transaccional

| Fase | Responsable | Acción | Condición de avance |
| --- | --- | --- | --- |
| D2-01 | Supervisión (`assignment.manage`) | Previsualiza línea + asignación exacta, última versión, estado E1 y evidencia histórica | Solo lectura; `eligible` nunca implica permiso |
| D2-02 | Supervisión | Solicita y confirma **relevo / reserva de reprogramación** para `work_order_id + line_code + expected_assignment_id + expected_version` | Operación atómica, auditable, bajo locks; marca persistente `pending` |
| D2-03 | Backend | Bloquea `start_line`, nuevas asignaciones y todas las capturas relevantes de esa línea mientras el relevo está pendiente; evita terminar otra línea | Barrera real en todos los write paths; no solo aviso/UI |
| D2-04 | Jefatura (`work_order.manage`) | Confirma campos anteriores, motivo y versión; publica snapshot operativo append-only | CAS 409 si cambió línea, asignación, E1 o versión; no mueve punteros históricos |
| D2-05 | Supervisión | Valida la revisión, acuse E2-C2 y asigna explícitamente la nueva versión a la línea | Sin reasignación silenciosa ni reutilización del ID de asignación anterior |
| D2-06 | Operación | Ve la asignación nueva y acusa su **versión efectiva** mediante E2-C1 | Decisión sobre acuse bloqueante de inicio debe aprobarse antes del desarrollo |
| D2-07 | Sistema | Registra cierre del relevo, usuario/instantes, referencias de versiones, asignación vieja/nueva | Historial inmutable y observabilidad sin secretos |

**Importante:** una llamada a `assignments.finish` seguida por otra llamada a reprogramación **no es suficiente**; existe una carrera entre ambas llamadas. Si no se implementa congelación/guardas en todas las escrituras afectadas, D2 debe seguir NO-GO. `pending` es una nueva entidad de control propuesta; no se debe reinterpretar el estado `enabled` ni el estado `assignment.finished` como congelación.

## 4. Diseño de persistencia por resolver en D2-B

Se recomienda una entidad transaccional separada de E1, por ejemplo `vinto_txn.work_order_line_reprogram_handoff`, con:
- Identidad del relevo y de la línea baseline, OT, máquina y `line_code`.
- Versión esperada, asignación anterior exacta, actor de Supervisión, marca temporal y motivo.
- Estado de ciclo `pending -> published -> reassigned -> acknowledged`, además de `cancelled/expired` con auditoría.
- Referencia al snapshot publicado y a la asignación nueva, cuando existan.
- Restricción de **a lo sumo un relevo no terminal** por línea lógica y unicidad/idempotencia de cada paso.
- Datos de permisos/actor obtenidos del backend, nunca del cliente. Sin borrar ni reescribir historiales antiguos.
- Migración nueva aditiva **solo después de revisar el SQL, pruebas PG17 y autorización de release**.

El diseño deberá definir qué hacer con reintentos, asignaciones caducadas por cambio de turno y cancelaciones parciales. No crear tablas ni migraciones desde esta fase A.

## 5. Concurrencia y orden de locks

1. Serializar revisiones y cambios E1 de la misma OT comenzando por `work_order FOR UPDATE`, como `start_line` y `activate`.
2. Tomar advisory locks de **máquinas en orden determinista** antes de filas de asignaciones/E1; no tomar asignación -> máquina.
3. Revisar y bloquear la asignación exacta, relevo y E1; comprobar **ausencia de capturas** con las rutas reales de F3/F6, no solo con `vinto_txn.capture` si existen otros registros.
4. Para `assignments.finish` (actualmente máquina -> asignación), diseñar la interoperabilidad sin invertir locks; posiblemente una operación nueva de Supervisión que siempre comienza por OT. Auditar previamente los caminos de captura (no asumir orden).
5. CAS sobre `expected_version` más imagen anterior y referencia de asignación. Si hay cambio de turno, inicio concurrente, dos Jefaturas, cancelación o captura, devolver conflicto y **cero escrituras de negocio**.

## 6. Acuses: decisión pendiente, sin inferencias

- Supervisión: se propone confirmación explícita del relevo, además del aviso E2-C2 de la nueva versión; **E2-C2 por sí solo no autoriza reprogramar**.
- Operación: se propone acuse obligatorio de la **asignación nueva + versión nueva** antes de `start_line` en los casos D2 (sin imponerlo globalmente a E2-C1). Requiere guarda nueva para D2; actualmente E2-C1 no bloquea inicio/captura.
- Operadores activos en otras líneas conservan su propia versión histórica; no se redirigen acuses ni asignaciones. El aviso global a otras líneas es una política pendiente, no un comportamiento que deba agregarse en silencio.

## 7. Matriz de pruebas obligatorias antes de merge de D2-B

1. Línea `enabled` no iniciada + asignación activa de versión vN -> relevo Supervisión -> snapshot vN+1 -> nueva asignación -> acuse de Operación. Todas las referencias deben ser exactas.
2. Relevo pendiente bloquea `start_line`, nueva `activate` y capturas relevantes; cancelación segura restaura la posibilidad de operación.
3. Race `start_line` vs relevo; captura vs relevo; cambio de turno vs relevo; doble petición simultánea; revisión vs revisión. Sin deadlock ni transacciones parciales.
4. Cualquier captura, `started_at`, estado `in_production/finished`, historia legacy sin E1, OT cerrada/archivada/retirada -> 409, cero escritura.
5. Pruebas 401/403/404/409/422 (Jefatura, Supervisión, Operación, permisos multisección) y filtrado de información entre sectores.
6. Reasignación nunca modifica asignación anterior ni pointers F3/F6; no crea dos asignaciones activas no permitidas por máquina.
7. Avisos E2-C1/C2: versión correcta, acuse idempotente, comportamiento con dos usuarios, reintentos y operación en diferentes turnos.
8. Revisión por PG17 real en DB efímera; regresiones E1, E2-B/C/D1; bandera D2 OFF por defecto; rollback ensayado.
9. Despliegue primero con bandera OFF, backup restaurado y health PASS; habilitación posterior con QA manual aprobado.

## 8. Decisiones de negocio aún abiertas — recomendación inicial

| Tema | Recomendación para contrato mínimo D2 | Estado |
| --- | --- | --- |
| Quién autoriza relevo | Solo Supervisión; Jefatura no puede autoaprobarlo | **Pendiente aprobación** |
| Qué campos se modifican | PV / artículo / cantidad / entrega, máquina y línea prohibidas; si se cambia artículo validar compatibilidad | **Pendiente aprobación** |
| Acuse Operación | Obligatorio y bloqueante **solo antes de empezar la línea reasignada en D2** | **Pendiente aprobación** |
| Cancelación | Solo Supervisión, con motivo; si ya se publicó revisión, no borrar la versión | **Pendiente aprobación** |
| Relevo sin asignación activa | No inferir elegibilidad; exigir evidencia de última asignación terminada + E1 y aprobación explícita | **Pendiente aprobación** |
| Expiración | No liberar automáticamente una reserva sin reconciliar asignaciones y versión; alerta a Supervisión | **Pendiente aprobación** |
| E2-C1 operadores de otras líneas | No avisarles por defecto si su versión efectiva no cambió; E2-C2 sí muestra la última revisión | **Pendiente aprobación** |

## 9. Puerta de avance

- **GO ahora:** preparar contrato, inventario de rutas y diseño de test PG17 sin modificar producción.
- **NO-GO ahora:** agregar una operación D2 que cambie OT/asignaciones; no hay política aprobada ni congelación transaccional implementada.
- La implementación se separará en PR(s) pequeños: **D2-B0** persistencia y guardas (flag OFF); **D2-B1** relevo y revisión; **D2-B2** acuses, QA, despliegue y habilitación independiente.
- **E2-D1 no debe modificarse ni deshabilitarse** por el trabajo de D2.

Evidencia de aceptación D1 al 08/11/2026: el responsable comunicó que la QA funcional terminó; la evidencia de ejecución manual caso por caso **no se adjunta a esta rama**. No elevar ese reporte a validación independiente de los casos.
