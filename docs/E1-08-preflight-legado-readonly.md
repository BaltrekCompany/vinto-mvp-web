# VINTO E1-08 — Preflight de transición de asignaciones legadas

## Objetivo y política de ejecución

Antes de habilitar `WORK_ORDER_LINE_EXECUTION_ENABLED=true`, detectar **asignaciones activas anteriores al modelo de ejecución** y OT en curso sin su fila `work_order_line_execution` correspondiente. **No hay backfill automático ni promoción de una asignación `active` al estado `in_production`**: la verdad productiva la confirma Supervisión.

El diagnóstico corre con PostgreSQL en **REPEATABLE READ + READ ONLY**, con límite de tiempo y **sin escrituras**, incluso si se conecta usando un rol que normalmente puede escribir. No usa SSH, el entorno de pruebas ni datos de una VPS por sí solo. Se debe aportar una conexión autorizada en el futuro y ejecutarlo explícitamente.

## Ejecución (E1-09, bajo sesión autorizada)

El operador configura `VINTO_E108_DATABASE_URL` por un canal seguro, sin imprimir ni introducir credenciales en tickets/PR/comandos compartidos. Desde el directorio `backend/`:

```sh
python -m app.work_orders.preflight_cli
```

Exit code `0`: ninguna inconsistencia técnica detectada (NO constituye GO). `2`: bloqueantes; `3`: error de configuración, permiso o conectividad. Se imprime exclusivamente JSON de totales por sector/máquina, nunca usuarios, OT individuales, claves, valores capturados o contraseñas.

## Señales que bloquean activar el flag

| Señal | Interpretación y acción |
|---|---|
| `MIGRATION_0013_NOT_CONFIRMED` | Falta la tabla o historial aplicado. Desplegar migración solo en E1-09, tras backup y revisión |
| `MIGRATION_0013_CHECKSUM_MISMATCH` | Historial de migración 0013 no coincide con la huella SHA-256 exacta del checkout. **No ejecutar una versión diferente sobre la base** |
| `MISSING_MACHINE_EXCLUSIVITY_INDEX` / `MISSING_EXECUTION_GUARD` | La integridad física de una sola línea en producción no está protegida |
| `APP_ROLE_WITHOUT_REQUIRED_TABLE_PRIVILEGES` | El rol aplicativo no puede leer/escribir estados aunque 0013 figure aplicada |
| `ACTIVE_ASSIGNMENTS_WITHOUT_EXECUTION` | Asignaciones creadas antes de la nueva secuencia; registrar estrategia manual de corte por máquina/turno |
| `IN_PROGRESS_ORDERS_WITHOUT_EXECUTION` | Hay líneas que impiden el cierre manual de la OT aunque no tengan asignación activa |
| `ACTIVE_ASSIGNMENTS_WITH_INCONSISTENT_EXECUTION` | Existen asignaciones activas cuyo estado lógico figura finalizado o no habilitado |
| `ACTIVE_ASSIGNMENTS_WITHOUT_BASELINE_MAPPING` | No se puede resolver la línea baseline inequívoca |
| `CLOSED_ORDERS_HAVE_ACTIVE_ASSIGNMENTS` | Contradicción entre estado OT y asignación |

`active_enabled` **no equivale** a producción: solo queda habilitada para Supervisión. `active_in_production` identifica ejecución explícitamente iniciada. Una asignación de turno vencido no se declara automáticamente «finalizada» ni se cambia de OT.

Si el resultado es `technical_preflight_clear=true`, todavía faltan confirmación funcional, permisos MF13 por cada sector y máquina, QA manual y ventana de corte. Tampoco equivale a que haya 0 operaciones activas.

## Protocolo NO-GO / GO

1. Mantener `WORK_ORDER_LINE_EXECUTION_ENABLED=false` durante la instalación de las nuevas imágenes y migración aditiva 0013. No modificar tablas de producción desde el diagnóstico.
2. Verificar backup/restauración, migración e historial, versión backend/frontend coincidentes, roles/concesiones y estado de servicios.
3. Ejecutar diagnóstico **solo lectura**, anotar agregados por máquina y bloquear habilitación si hay señales arriba.
4. Con el área funcional, programar corte: cerrar o resolver asignaciones y OT anteriores en el modelo antiguo, o documentar una transición controlada independiente. No marcar las líneas como `in_production` por deducción.
5. Una vez reconciliado el estado y validado el plan, activar compuerta en una ventana autorizada, verificar un ciclo real Habilitar → Iniciar → Capturar → Finalizar → Cerrar OT en Bobinas y en frentes habilitados.
6. Ante fallo, suspender capturas nuevas durante la evaluación de rollback. La migración 0013 es **aditiva e histórica**: no borrar la tabla ni los datos reales de ejecución como mecanismo automático de rollback. El retorno de flag o imágenes exige analizar idempotencia e integridad con el responsable técnico.

## Evidencia de QA no productiva

La suite `backend/tests/test_rollout_preflight_e108.py` construye PostgreSQL 17 efímero, detecta asignaciones legadas sin fila 0013, confirma que nuevos `enabled` no se confunden con ejecuciones iniciadas, comprueba cierres y demuestra que una transacción de escritura es rechazada.

**NO-GO para activación real hasta ejecutar este preflight en el entorno autorizado y reconciliar los registros existentes.**