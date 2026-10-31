# MF-13-01B.4 · Atribución de las revocaciones de concesiones

Verificación del hallazgo sobre el guarda de la migración 0008 (`guard_user_machine_form_grant()`): exigía que `revoked_by` coincidiera con `vinto.actor_id` **solo cuando había actor**. Sin endpoints, sin pantallas, sin activar la
autorización efectiva, sin tocar P1-10, P1-31, Calidad ni perfiles. Las migraciones 0007 y 0008 no se modifican.

## 1. Reproducción (PostgreSQL 17 aislado, implementación de 0008)
| Caso | Resultado en la fila | Resultado en `vinto_audit.audit_event` |
|---|---|---|
| **S1** Propietario, **sin** actor de sesión, `revoked_by` = otro usuario | **Aceptado**: `revoked_by` = otro, `updated_by` = otro (lo fija el guarda), `created_by` intacto | `actor_id` **NULL**, `database_actor` = usuario de la sesión, `new_data.revoked_by` = otro |
| **S2** Igual, ejecutado con un rol con **exactamente** los privilegios de `vinto_app` (SELECT, INSERT, UPDATE; sin DELETE ni TRUNCATE) | **Aceptado**, mismo resultado | Igual que S1 |
| **S3** La sesión fija ella misma `vinto.actor_id` = otro usuario | Aceptado, atribuida a ese usuario | `actor_id` = ese usuario, `database_actor` = usuario real de la sesión |

Interacción con los triggers: `touch_row()` solo sobrescribe `updated_by` si hay actor, así que sin actor no corrige nada; `record_change()` lee `vinto.actor_id` tal cual (NULL si no está) y siempre registra `database_actor`
(= `session_user`). El guarda de 0008 igualaba `updated_by` a `revoked_by`, de modo que la atribución falsa quedaba en **dos** columnas. La frase del encabezado de 0008 («el SQL sin actor no puede atribuir una fila a otra persona»)
solo era cierta para el `INSERT`.

## 2. Riesgo efectivo
- **Quién puede hacerlo:** cualquier sesión con `UPDATE` sobre la tabla: `vinto_app` (la cuenta de la API) y el propietario/DBA. El servicio normal **no**: siempre fija el actor. No hay procedimiento, script ni runbook del repositorio que
  revoque sin actor (se buscó en `deploy/`, `backend/roles/`, READMEs y `backend/app/`); solo 5 `UPDATE` de pruebas propias.
- **Qué se falsea:** la **atribución** (no repudio) de una revocación, no el acceso: revocar solo *reduce* acceso y la tabla aún no participa en la autorización. Severidad actual: **baja**. Crecería cuando las concesiones se usen para
  autorizar (una revocación mal atribuida cambiaría quién perdió el acceso y a quién se le pediría cuentas).
- **Qué ya lo limitaba:** `vinto_app` no tiene DELETE/TRUNCATE; una fila revocada está congelada; la auditoría es inmutable y el caso era **detectable** (`actor_id` NULL con `revoked_by` informado).
- **Por qué no se pierde ningún uso legítimo:** el `CHECK` de 0007 `(revoked_at IS NULL) = (revoked_by IS NULL)` obliga a que toda revocación nombre a un usuario; una revocación *sin atribuir* **no es representable**. El único camino sin actor
  era «nombrar a cualquiera». (Otras tablas permiten actor ausente porque allí `created_by` puede quedar NULL; aquí no.)

## 3. Corrección: migración 0009
Solo cambia el cuerpo de `guard_user_machine_form_grant()`: **una revocación debe llevar `vinto.actor_id`** (si no, 23514) y `revoked_by` debe ser ese actor. Una prueba demuestra que el cuerpo nuevo es el de 0008 más exactamente ese
bloque. No cambia tablas, columnas, restricciones, índices, triggers, privilegios, filas ni auditoría. Efecto sobre el escenario: S1 y S2 pasan de *aceptado* a **rechazado**; el servicio, la idempotencia, la concurrencia y la auditoría
siguen igual (el servicio ya enviaba el actor).

**Procedimiento manual (operador que revoca por SQL):** en la misma transacción
```sql
SELECT set_config('vinto.actor_id',  '<id de su propio usuario VINTO>', true);
SELECT set_config('vinto.request_id', 'manual:<ticket>', true);
SELECT set_config('vinto.reason',     '<motivo y quién lo solicitó>', true);
UPDATE vinto_master.user_machine_form_grant SET revoked_at = clock_timestamp(), revoked_by = '<mismo id>' WHERE id = '<concesión>';
```
Quién *pidió* la revocación va en `reason`/`request_id`; `revoked_by` es quien la ejecuta y responde de ella.

## 4. Límite que la base de datos no puede cerrar (S3)
`vinto.actor_id` es un ajuste de sesión que escribe el cliente: una sesión con `UPDATE` puede afirmar cualquier actor y la fila y la auditoría coincidirán. Lo que sigue siendo verdad es `audit_event` (inmutable) con `database_actor` =
`session_user`, `request_id` y `reason`. Como toda la API comparte un único usuario de base de datos, `database_actor` no distingue personas. Probar **quién pidió** una revocación exige autenticación fuera de PostgreSQL: la API
administrativa futura debe tomar el actor de la sesión autenticada en el servidor, nunca de la petición. Una prueba (`test_known_limit_…`) documenta este límite para que se revise cuando exista esa capa.

## 5. Revisión de datos ya guardados
La 0009 **no reescribe historia**. Si alguna base ya tuviera una revocación hecha bajo 0008 sin actor, queda localizable con:
```sql
SELECT id, entity_key->>'id' AS grant_id, database_actor, new_data->>'revoked_by' AS revoked_by, occurred_at
FROM vinto_audit.audit_event
WHERE entity_table = 'user_machine_form_grant' AND action = 'UPDATE' AND actor_id IS NULL AND new_data->>'revoked_by' IS NOT NULL
ORDER BY id;
```
Resultado esperado: **0 filas** (la tabla no tiene consumidores; no se verificó contra ninguna base real). Cualquier fila encontrada se revisa a mano; no se corrige automáticamente.

## 6. Decisiones de gobernanza (no bloquean este PR)
1. **Revocaciones manuales:** quedan atribuidas al operador que las ejecuta, con el solicitante en `reason`. Si se quisiera atribuirlas «en nombre de» otra persona o a un principal de sistema, haría falta definirlo (hoy no existe).
2. **Revisión de eventos históricos** (consulta del §5) antes de activar la autorización efectiva.
3. **Endurecer la superficie de escritura** (opcional, futuro): quitar `UPDATE` directo a `vinto_app` y exponer la revocación solo mediante una función `SECURITY DEFINER`. No autentica a nadie por sí sola; reduce la superficie. Decidir al diseñar la API administrativa.

## 7. Despliegue y reversión (futuro, solo con autorización expresa)
`migrate.py --check` (solo la 0009 pendiente) → respaldo verificado → `migrate.py` → `--check` verde y conteos de `user_machine_form_grant` y `audit_event` sin cambios. Es compatible con el código actual en cualquier orden. Reversión: restaurar el
respaldo; si ya se usó, una migración nueva que restituya el cuerpo de 0008 (no recomendado: reabre S1/S2).
