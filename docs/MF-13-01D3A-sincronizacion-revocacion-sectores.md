# MF-13-01D.3A — Sincronizar la revocación de sectores con las capturas autorizadas

Estado: **implementado y probado**. Cambio de código acotado a `revoke_sector` (`backend/app/auth/grants.py`); no se modificó el motor ni el orden de bloqueos de las cuatro capturas, ni privilegios, migraciones, frontend, catálogos, formularios o perfiles. No se activó `enforce`.

## 1. La carrera

El motor `app/authz` toma `FOR SHARE` sobre la fila del **usuario** durante toda la transacción de una captura (`lock=True`) y lee `user_sector` **sin bloquear**, porque `vinto_app` no tiene `UPDATE` sobre esa tabla (solo `SELECT, INSERT, DELETE`) y PostgreSQL exige `UPDATE` para cualquier bloqueo de fila. `revoke_sector` borraba la fila de `user_sector` sin tocar la del usuario, así que una revocación podía confirmarse entre la autorización y el registro de una captura (o la captura leer un `user_sector` ya borrado sin esperar), y el motor no tenía forma de sincronizarse.

## 2. Inspección de caminos que conceden o retiran sectores

| Camino | Qué hace | ¿Requiere sincronizarse? |
|--------|----------|--------------------------|
| `auth/grants.py::revoke_sector` | `DELETE FROM vinto_master.user_sector` — **único** borrado en el código de la aplicación | **Sí** (este cambio) |
| `auth/grants.py::grant_sector` | `INSERT … ON CONFLICT DO NOTHING` | No: añadir un sector solo puede hacer que una captura concurrente se deniegue de más (falla cerrado), nunca de menos |
| `admin/service.py::change_grant` (API `POST /api/admin/users/{id}/sectors/{grant,revoke}`) | delega en `grant_sector` / `revoke_sector` | Cubierto por `revoke_sector` |
| `auth/service.py::create_user(sectors=…)` | concede a través de `grant_sector` a un usuario recién creado, en su misma transacción | No: el usuario aún no existe para ninguna captura |
| Desactivar/reactivar usuario | no toca `user_sector` (documentado en el servicio) | — |
| Scripts del backend (`manage_user.py`, `create_user.py`) | usan `create_user`/servicios; ninguno ejecuta SQL propio sobre `user_sector` | Cubiertos |
| Migraciones (0006 y relleno) | DDL/datos de una sola vez, fuera de la operación | No aplica |
| SQL directo de un rol con privilegios | no pasa por la aplicación | **No cubierto**: MF-13-01D.3B |

Una prueba estática fija que el único código de la aplicación que inserta o borra en `user_sector` es `grants.py` y que nadie más llama a `revoke_sector`.

## 3. Implementación

En `revoke_sector`, dentro de la misma transacción y antes del `DELETE`:

```sql
SELECT 1 FROM vinto_master."user" WHERE id = %s FOR NO KEY UPDATE
```

Se **evaluó `FOR UPDATE` y se eligió `FOR NO KEY UPDATE`**:

| Bloqueo del revocador | ¿Choca con el `FOR SHARE` del motor? | ¿Bloquea `FOR KEY SHARE` (comprobaciones de clave foránea de otras transacciones que referencian al usuario)? |
|-----------------------|---------------------------------------|----------------------------------------------------------------------------------------------------------|
| `FOR UPDATE` (**descartado**) | sí | **sí** (bloquearía capturas, sesiones o auditoría ajenas que solo referencian al usuario) |
| **`FOR NO KEY UPDATE`** | **sí** | **no** |
| `FOR SHARE` / `FOR KEY SHARE` | no / no | — (no sincronizan: son compatibles con el `FOR SHARE` del motor) |

Todo lo anterior está demostrado en PostgreSQL 17 con dos conexiones (`LockSemanticsTests`), incluido que el **rol equivalente a `vinto_app`** (construido desde `backend/roles/*.sql` y la 0007) **puede** tomar el bloqueo sobre `user` (tiene `UPDATE` ahí) y que sobre `user_sector` sigue sin poder (`42501`: la premisa original).

Se mantienen idempotencia (`True` solo si esa llamada borró; la segunda devuelve `False`), auditoría (evento `DELETE` con actor, `request_id` y motivo `sector revoke`), errores (`UserNotFoundError`, `SectorNotFoundError`), el contrato HTTP de la administración y los controles de sesión.

### Orden de bloqueos y deadlocks
Revocación: **usuario → fila de `user_sector`**. Motor: **usuario → perfiles → máquina+sector → concesión**. El revocador solo toma el bloqueo del usuario y después borra su fila de `user_sector`, que ninguna captura bloquea; las capturas no esperan nada que sostenga el revocador salvo la propia fila del usuario. Sin ciclo posible. Concurrencia mixta de las cuatro operaciones con revocaciones/concesiones de sector y de formulario: sin interbloqueos ni `AuthorizationUnavailable`.

## 4. Las dos carreras (probadas en las cuatro operaciones, con el alcance de sectores obsoleto a propósito)

1. **Captura autorizada en curso → la revocación espera su COMMIT.** La captura se completa con el sector que tenía al autorizarse; la revocación termina después; las capturas posteriores se deniegan (`SECTOR_NOT_GRANTED`) sin escribir nada. Probado con la captura y la revocación ejecutadas con el rol de `vinto_app`.
2. **Revocación en curso → la captura espera.** Al confirmarse la revocación, la captura relee `user_sector` y se deniega (`SECTOR_NOT_GRANTED`), sin capturas, detalles, dispositivos, bobinas ni liberaciones.
3. Una petición HTTP posterior a la revocación se rechaza (el alcance de sectores existente relee la base: 404/422/403 según la ruta) y no escribe nada.

## 5. Riesgos y límites

- **Solo cubre la ruta de la aplicación.** Un `DELETE` directo sobre `user_sector` ejecutado por un rol con privilegios suficientes se salta este bloqueo: **MF-13-01D.3B** (endurecimiento de privilegios / funciones `SECURITY DEFINER`), que esta tarea no toca.
- El motor sigue sin bloquear `user_sector` (no puede con los privilegios actuales): la sincronización depende de que **toda** revocación de sectores pase por `revoke_sector`; la prueba estática lo vigila.
- La revocación puede esperar a una captura en curso; el `statement_timeout` de la aplicación convierte una espera larga en el error de base de datos ya existente (503), nunca en acceso.
- El resto de riesgos de activación de MF-13-01D.2x (escritura directa de concesiones de formulario, concesiones de usuarios reales, frontend) sigue como estaba documentado.
