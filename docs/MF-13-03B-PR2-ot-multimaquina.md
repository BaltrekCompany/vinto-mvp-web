# MF13-03.B PR2 — crear, publicar y leer OT multimáquina (backend)

Solo servicios y contrato HTTP de `/api/work-orders`. No cambia la migración 0010, `assignment_one_active_machine`, `POST /api/assignments/activate`, los modos `AUTHZ_*`, F3/F6 ni el frontend.

## Compuerta de servidor
`WORK_ORDERS_MULTI_MACHINE_ENABLED` → `settings.work_orders_multi_machine_enabled` (`app/config.py`), **apagada por defecto**. Sigue el patrón de los `AUTHZ_*` (variable de entorno del servidor, sin interruptor global ni parámetro HTTP). Un valor no booleano impide arrancar.
- Apagada: crear, añadir línea o publicar con alguna línea en una máquina distinta de la de cabecera responde `422 MULTI_MACHINE_DISABLED`, sin escribir nada. Nunca se reasigna en silencio a la cabecera.
- Una línea con `machine_code` igual al de cabecera es el flujo de una sola máquina y no requiere la compuerta.
- **No activar en la VPS** hasta tener PR3 (índice y activación por línea), PR4 (activación masiva) y PR5 (listados y capturas filtrados por máquina autorizada). Con la compuerta encendida hoy, el `activate` actual solo sabe activar líneas de la máquina de cabecera; las de otra máquina fallan cerradas por `validate_assignment` (probado), y los operarios no ven aún solo sus máquinas.

## Contrato HTTP
Entrada de línea (`POST /api/work-orders`, `POST /api/work-orders/{id}/lines`): `pv_reference`, `article_code`, `quantity`, `due_date` y **`machine_code` opcional** (1–64 caracteres). Sin él rige la máquina de cabecera. Cualquier otro campo (`machine_id`, ids de versión, la propia compuerta) → `422` (`extra="forbid"`).

Salida: `machine` de la OT se conserva; cada línea añade `machine: {code, name}` (la de la línea; en OT antiguas coincide con la cabecera). Los clientes que ignoran campos desconocidos no cambian (el parser de `lib/vinto/orders.ts` arma sus objetos campo a campo).

Validación por línea (antes de escribir; todo o nada): máquina existente (404 `MACHINE_NOT_FOUND`), activa y en el alcance de sectores del actor (422 `MACHINE_OUTSIDE_SCOPE`), artículo activo, producto y permitido para **esa** máquina (422 `ARTICLE_NOT_ALLOWED_FOR_MACHINE`), y las reglas actuales de cantidad, PV y fecha. Se mantiene el límite de 200 líneas y los bloqueos. La publicación comprueba cada línea contra su propia máquina; sigue siendo inmutable e idempotente.

## Aislamiento de información
Regla en SQL (no en React), aplicada en listado, detalle, añadir línea y publicar:
1. Una OT solo es visible/modificable si **todas** sus máquinas (cabecera y líneas) están en el alcance de sectores del actor. Si no, es indistinguible de una inexistente (404); nunca se devuelve una OT parcial ni se filtran sus líneas.
2. Una OT con líneas en más de una máquina solo la leen quienes tienen `work_order.manage` (Jefatura) o `assignment.manage` (Supervisión). Operación, Calidad y DATA_BALTREK la reciben como inexistente (en detalle y en listados, también con `?machine_code=`). Las OT de una sola máquina se comportan como antes para todos.
3. El filtro `machine_code` del listado coincide con la máquina de cabecera o de cualquier línea.

Esto es deliberadamente conservador: las vistas parciales por línea/máquina (Supervisión con solo parte de los sectores, Operación solo con sus máquinas concedidas) quedan para PR5; hasta entonces la compuerta apagada mantiene cerrada la creación operativa. Por eso `multi_machine_visible` del servicio es `False` por defecto (falla cerrado) y el router lo calcula por permisos.

## Compatibilidad con clientes y datos anteriores
- Solicitudes antiguas (sin `machine_code`) y OT existentes: mismo resultado; la respuesta solo añade `machine` en cada línea.
- Inserciones: el servicio escribe `machine_id` explícito; el trigger de 0010 sigue cubriendo a cualquier escritor antiguo.
- Activación y copia operativa sin cambios: la copia conserva la máquina de cada línea baseline (trigger 0010).
- `LineInput` gana `machine_code=None` al final: las llamadas posicionales existentes (≈20 en pruebas) no cambian.

## Riesgos y dependencias
- Con la compuerta encendida y antes de PR3–PR5: activación solo en la máquina de cabecera; la visibilidad de OT multimáquina es todo-o-nada por sectores y por perfil, y no hay filtrado por concesión de máquina dentro de un mismo sector.
- La regla 2 oculta estas OT a Operación aunque tenga concesión de la máquina; PR5 la sustituye por el filtro por concesión.
- Asignaciones y capturas no se tocaron: sus pruebas se ejecutan sin cambios.
