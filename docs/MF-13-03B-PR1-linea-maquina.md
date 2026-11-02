# MF13-03.B PR1 — máquina por línea de OT (migración 0010)

Solo esquema (paso *expand*). No cambia ningún endpoint, la activación, `assignment_one_active_machine`, F3/F6, los modos AUTHZ ni el frontend.

## Qué hace 0010
1. `vinto_txn.work_order_line.machine_id` (FK a `vinto_master.machine`, `ON DELETE RESTRICT`, índice, `NOT NULL`).
2. Backfill desde `work_order.machine_id`. Las líneas publicadas son inmutables (`guard_order_line`); solo ese trigger se desactiva, solo en esa tabla y dentro de la transacción de la migración (DDL transaccional: un fallo lo restaura). Auditoría (`z_touch`, `audit_changes`) y demás controles siguen activos; cada fila deja un evento con la razón `MF13-03B PR1 backfill ...`. Al terminar, la migración comprueba que no quedan NULL y que el guard está habilitado.
3. Trigger `validate_order_line_machine` (BEFORE INSERT/UPDATE):
   - si el INSERT omite `machine_id`, lo rellena (baseline: máquina de la OT; operativa: máquina de la línea baseline con el mismo `line_code`);
   - baseline: el artículo debe estar en `article_machine` para la máquina de la línea (misma regla que ya aplicaba el backend al crear/publicar);
   - operativa: debe coincidir con su baseline; `article_machine` no se vuelve a comprobar en copias, para que un cambio posterior de catálogo no bloquee la activación de una OT ya publicada.
4. `validate_assignment` compara con la máquina **de la línea** en vez de la de la cabecera. Idéntico para todos los datos existentes (paso 2).

`work_order.machine_id` se conserva sin cambios (máquina "principal" legada).

## Compatibilidad con el backend desplegado
| Código actual | Efecto |
|---|---|
| `INSERT INTO work_order_line (...)` sin `machine_id` (`work_orders/service.py:164`) | el trigger rellena con la máquina de la OT |
| copia a versión operativa `INSERT ... SELECT` (`assignments/service.py:183`) | hereda la máquina de cada línea baseline |
| `activate` (máquina de la cabecera) | igual en OT de una máquina; en una futura línea de otra máquina falla cerrado en `validate_assignment` |
| lecturas / vistas (`0004:144`) | no seleccionan la columna nueva; sin cambio |
| índice `assignment_one_active_machine` | intacto |

Cambio en una prueba existente: `test_schema.test_one_active_assignment_per_machine` insertaba una línea con un artículo sin fila en `article_machine`; ahora la base lo rechaza, así que el fixture añade esa fila. El backend ya imponía la regla.

## Privilegios PostgreSQL
- Sin tablas, roles ni `GRANT` nuevos: `vinto_app` ya tiene `SELECT/INSERT/UPDATE` a nivel de tabla sobre `work_order_line` (sin grants por columna), y `SELECT` sobre `work_order`, `work_order_version`, `article_version` y `article_machine`, que es lo único que lee el trigger. Corre como invocador y no lee `machine` (el FK lo comprueba el motor).
- La función es de tipo `trigger`: no es invocable directamente, no necesita `EXECUTE` (criterio de `roles/04_function_grants.sql`); además `05_no_default_privileges.sql` quita `EXECUTE` a PUBLIC por defecto.
- `ALTER TABLE ... DISABLE TRIGGER` exige ser propietario: lo ejecuta `vinto_migrator`, quien ya aplica las migraciones. `vinto_reference` no tiene acceso a `vinto_txn`.
- No toca `roles/proposals/D3B*`.

## Rollback
`backend/rollbacks/0010_work_order_line_machine_rollback.sql` (no es migración; `migrate.py` no lo lee). Una transacción, app inactiva, como propietario: restaura `validate_assignment` de 0001, elimina trigger/función/índice/FK/columna y borra la fila 10 de `schema_migration`.
- Seguro mientras ninguna línea use una máquina distinta de su OT. Si existe alguna, el script **aborta** (perdería esa información); entonces se avanza con una migración nueva.
- Antes de producción: respaldo de `vinto_txn.work_order_line` y `vinto_audit.audit_event`.

## Evidencia (solo `vinto_test`, Docker local; nada en `vinto_piloto` ni en la VPS)
- `tests/test_work_order_line_machine.py` (18): esquema, compatibilidad, coherencia, y ensayo completo en una transacción: vuelve a la forma 0009 con el rollback, carga datos legados (OT publicadas con baseline+operativa+asignación activa, borrador, línea con artículo no habilitado), aplica el archivo real 0010, y compara filas, asignación y OT sin cambios, auditoría del backfill, guard habilitado, fallo a mitad de migración (restaura el guard), y rollback refusado con líneas multimáquina.
- Suite completa: 1919 pruebas. Tras fijar el checksum de 0010 en `test_sector_scope` (único fallo causado por esta migración, ya corregido), quedan 19 fallos/errores preexistentes y ajenos: 18 `FileNotFoundError` de archivos de `docs/`, `deploy/` y `.github/` fuera del montaje `backend/` del contenedor, y `test_capture_count_authorization` (falla igual sobre `origin/main` sin 0010). Los módulos relacionados (`test_schema`, `test_sector_scope`, asignaciones, OT, APIs): 173 pruebas OK.
