# VINTO E1-09 — Plan de despliegue condicionado con datos simulados

**Fecha:** 2026-11-06. **Estado:** PLAN DOCUMENTAL; no ejecutado.  
**P0 actualizado (06/nov/2026):** inspección VPS **PASS** únicamente para preparar el inventario de respaldo P1-A; [resultado y runbook P1-A](E1-09-P0-resultados-y-P1A-inventario-readonly.md). P1-A no ejecutado, P1-B (backup) no autorizado. 
**Repositorio:** BaltrekCompany/vinto-mvp-web. **Código integrado:** `main@a8a8beaf611e8d892658eeabb5a5e1b972a32316`.  
**QA de código:** GitHub Actions [#42169307786](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/42169307786) PASS diferencial frontend/backend sobre candidato `5ebae3c`; solo diferencias documentales en main; 32 FAIL frontend y 3 FAIL+102 ERROR backend históricos identificados y pendientes (#134/#135).

## 1. Decisión funcional: qué cambia por los datos simulados

El usuario confirmó que **los registros actuales del MVP VINTO son simulados**. En consecuencia, para la liberación **no es necesario acreditar una producción física industrial real** de las 16 líneas del snapshot; la validación se convierte en **QA de estados y transiciones simuladas**. Sin embargo:

- La instancia VPS sigue siendo productiva y compartida; puede tener usuarios, integraciones y datos de prueba útiles. No se debe borrar ni modificar nada sin inventario de impacto y autorización explícita.
- `assignment.active` es habilitación de turno, no ejecución física; `assignment.finished` es fin de asignación, no línea lógica finalizada.
- La migración 0013 es **aditiva y no hace backfill**. Las 12 OT `in_progress` del corte SQL-E tienen 16 líneas baseline; todas carecen de ejecución lógica 0013 pre-migración. El preflight `backend/app/work_orders/rollout_preflight.py` bloquea `IN_PROGRESS_ORDERS_WITHOUT_EXECUTION` y `ACTIVE_ASSIGNMENTS_WITHOUT_EXECUTION` después de instalar 0013 si continúan tales filas. **Que sean simuladas no desactiva los candados.**
- Dos snapshots con totales idénticos no prueban que las filas individuales sean las mismas; repetir corte antes de cualquier operación.

## 2. Estado técnico disponible y datos pendientes

| Control | Evidencia | Estado |
|---|---|---|
| E1-02 a E1-08 integrados GitHub | 7/7 PR merged en main fijo | PASS |
| QA diferencial | Run #42169307786 | PASS, deuda histórica explícita |
| SQL-A/B/C/D/E | `vinto_piloto`, `vinto_app`, PostgreSQL 17 | PASS para snapshots, sin escritura |
| Mapeo baseline | 11/11 activas, 0 ambigüedades | PASS para SQL-E |
| Historial de 5 líneas sin activa | MP1:4, MP3:1, todas con assignment.finished | PASS como historial, NO como cierre lógico |
| Release actualmente activo VPS | P0 confirmó `86e4ec4fa6f6bf95c0e099279d8c51a016c7a6a4` | PASS en P0; código anterior a E1 |
| Historial real de migraciones | P0 confirmó que el archivo 0013 y su tabla no están instalados; historial `vinto_meta` sigue restringido | NO VERIFICADO en historial |
| Flag efectivo del servicio | Release anterior sin referencia ni variable de proceso `WORK_ORDER_LINE_EXECUTION_ENABLED` en P0 | PASS para esquema antiguo; valor del nuevo release NO VERIFICADO |
| Grants reales MF13 | P0 observó grants básicos sector/máquina y usuarios/sectores activos | PASS parcial; permisos efectivos por perfil/formulario NO VERIFICADO |
| Backups verificados + restauración | P1-A inventario aún no ejecutado; no se ha certificado restauración para este corte | PENDIENTE |
| Estrategia de conservación de registros simulados | Usuario debe conocer impacto y confirmar | PENDIENTE |
| Migración 0013 / activación | No autorizadas | NO-GO |

## 3. Estrategia para la base simulada (elegir antes de flag ON)

**S1 — Conservar historial simulado:** no se modifican las 12 OT/16 líneas y se despliega eventualmente con flag OFF. Permite validar que el sistema anterior sigue funcionando. **No permite asumir GO para flag ON:** es necesario diseñar y probar conciliación funcional sin fabricar `in_production`, ni cerrar órdenes ficticiamente. Una política explícita de tratamiento de datos legados debe ser aprobada.

**S2 — Reinicio controlado del conjunto de datos de prueba:** solo si existe constancia de que TODOS los registros implicados son desechables, no hay integraciones/usuarios dependientes, y se cuenta con respaldo **creado y restaurado/verificado**. Requiere plan SQL específico auditable y autorización **separada para cualquier DELETE/TRUNCATE/recreación**. Este documento no contiene SQL destructivo y **no autoriza reset**. Con una base de prueba limpia, los nuevos casos E1 pueden crearse desde la interfaz, bajo grants y flag ON después de GO.

**S3 — Datos de prueba en una base aislada (opcional):** evita manipular el dataset actual; requiere recursos, credenciales y despliegue separados. No forma parte del despliegue actual.

**Criterio:** no resolver el bloqueo técnico falseando estados, fabricando historiales ni desactivando preflight. No confundir que los datos sean ficticios con permiso para alterarlos.

## 4. Etapas de autorización separadas

### P0 — Auditoría READ ONLY del VPS (siguiente ejecución recomendada)

Por Codex Desktop en SSH previamente autorizado, **sin cambiar archivos ni servicios**:

1. Confirmar SHA real de `/opt/vinto-mvp-web/current` como usuario de servicio autorizado (el árbol `/opt/vinto-mvp-web` tiene permisos privados); unidades `vinto-mvp-backend.service`/`vinto-mvp-frontend.service` y contenedor exacto `vinto-mvp-postgres` saludables.
2. Confirmar identidad del contenedor por nombre + imagen + etiqueta de Compose, sin imprimir `Config.Env` ni secretos.
3. Confirmar base `vinto_piloto`, presencia/ausencia de tabla `work_order_line_execution` mediante catálogos; historial `vinto_meta.schema_migration` queda NO VERIFICADO si el rol no tiene privilegios. **No conceder derechos adicionales a `vinto_app`.**
4. Con consulta segura `REPEATABLE READ READ ONLY`, contar OT, líneas, asignaciones, grants efectivos por sector/máquina y detectar nuevas capturas/actividad posterior sin imprimir registros personales o números OT. Los SQL-E anteriores son evidencia histórica, no sustituyen el corte nuevo.
5. **No invocar `deploy.sh preflight` a ciegas:** `preflight.sh infra` incluye controles de puertos 3100/8100/6544 **libres** pensados para primera instalación; un MVP ya activo utiliza esos puertos. Evaluar primero su idoneidad para actualización y registrar cualquier falso bloqueo en vez de ignorarlo.
6. No ejecutar `deploy.sh check-release` bajo una orden de cero escritura de archivos sin revisar antes el uso de helpers/archivos temporales. No inspeccionar `.env`.

**Salida P0:** SHA activo, servicios, contenedor, nombre de BD y rol, 0013 presente/ausente, resumen del corte nuevo, permisos MF13, estado efectivo del flag solo si puede comprobarse sin secretos, `PASS/NO VERIFICADO/FAIL`. Si un dato es inaccesible, no escalar privilegios; detener.

### P1 — Respaldo y recuperabilidad (acción futura)

Comprobar espacio y mecanismo del backup **antes de ejecutarlo**. `deploy/mvp/scripts/backup.sh create-and-verify` genera backup y restaura en contenedor efímero aislado; solo tras autorización específica para escribir archivos y usar Docker. No confundir `backup.sh list` con restaurabilidad comprobada.

### P2 — Preparación release / migración 0013 (acciones futuras)

SHA exacto `a8a8beaf611e8d892658eeabb5a5e1b972a32316`; artifact frontend y manifiesto deben corresponder a ese SHA. Preflight de actualización y `deploy.sh check-release` si ya está autorizado. `migrate-release <sha>` aplica migración pendiente y **cambia PostgreSQL**, aunque `current` no cambie; requiere autorización expresa tras respaldo. Validar que `WORK_ORDER_LINE_EXECUTION_ENABLED` sea efectivamente OFF antes y después del despliegue, no inferirlo solo del default en config.py.

### P3 — Despliegue con flag OFF y smoke de legado (acción futura)

Activación de nueva release **solo** con migración/esquema compatibles, backup verificado, rollback de código identificado y autorización explícita. Smoke de captura F3/F6, formularios centrales, Rebobinado/Conversión, Calidad y permisos. Prestar especial atención al componente UI nuevo: puede consultar `/api/assignments/execution-status` incluso con flag OFF, y falla cerrado ante respuesta inválida; validar que no bloquee captura legítima.

### P4 — Activación de E1 y QA funcional simulado (acción futura)

Solo después de resolver S1/S2/S3 y obtener preflight 0013 sin bloqueantes, revisar grants MF13 y habilitar flag con procedimiento revertible aprobado. La activación NO es consecuencia automática de P3.

| QA | Escenario de prueba | Resultado esperado |
|---|---|---|
| Q01 | Dos líneas habilitadas, una máquina | Solo una puede quedar `in_production` |
| Q02 | Captura sin iniciar línea | Rechazo, sin nueva captura |
| Q03 | Inicio válido por Supervisión con alcance | Estado `in_production`, captura permitida con turno/grant |
| Q04 | Inicio simultáneo de otra línea en la máquina | Conflicto, sin doble ejecución |
| Q05 | Finalización parcial vs cantidad planificada | Fin admitido sin justificación obligatoria; déficit visible, no anulación |
| Q06 | Intento de cerrar OT con línea no finalizada | Rechazo sin cierre parcial |
| Q07 | Cierre manual con todas las líneas terminadas | Éxito por Supervisión, conservando historial |
| Q08 | Cambio de turno durante ejecución lógica | No inferir pausa/finalización; nueva OT bloqueada hasta terminar línea anterior |
| Q09 | Usuario sin grant / fuera de sector | Acceso o acción denegada |
| Q10 | Calidad y reintento idempotente de captura | Calidad independiente; no duplicar captura ya confirmada |

Cada prueba debe registrar hora, acción, rol/sector (no datos personales públicos), resultado observado, PASS/FAIL, evidencia privada y cambios finales en registros simulados.

## 5. Contingencia, diferencias entre rollbacks

- `rollback.sh version <sha-anterior>` conmuta versión de aplicación y reinicia servicios. **No revierte el esquema 0013** ni restaura registros alterados por pruebas.
- La 0013 tiene `backend/rollbacks/0013_work_order_line_execution_rollback.sql` con condiciones; no aplicarla automáticamente ni asumir que sigue siendo segura después de crear datos nuevos.
- Restaurar una base implica operación separada y potencial pérdida de cambios posteriores al backup. Debe tener su propio GO.
- En un incidente de flag ON, antes de asumir un rollback de app/DB, aplicar el procedimiento de contención aprobado y evaluar compatibilidad de esquema. Evitar borrar información por tratarse de un piloto.

## 6. Decisión actual

**GO para P0, lectura no mutadora. NO-GO para reset, migración 0013, despliegue y flag ON.** Datos simulados permiten sustituir validación industrial física por QA de escenarios controlados, **no** eliminar respaldos, autorización y conciliación de modelo.

**Fuentes internas:** SQL-A/E en [PR #132](https://github.com/BaltrekCompany/vinto-mvp-web/pull/132), [Issue #131](https://github.com/BaltrekCompany/vinto-mvp-web/issues/131), `deploy/mvp/scripts/{deploy,rollback,backup,preflight}.sh`, `backend/app/work_orders/rollout_preflight.py`.
