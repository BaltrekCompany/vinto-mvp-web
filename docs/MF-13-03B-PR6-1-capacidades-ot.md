# MF13-03.B PR6.1 — endpoint de capacidades de OT y conexión con la interfaz de Jefatura

Cierra la dependencia que dejó PR6: la interfaz ofrecía la creación multimáquina solo si el servidor lo confirmaba, pero no existía cómo consultarlo. No cambia la compuerta (`WORK_ORDERS_MULTI_MACHINE_ENABLED`, apagada por defecto), ni la creación y publicación de OT, ni la activación (individual PR3, masiva PR4), ni la autorización de PR5, ni F3/F6/Calidad/Rebobinado/Conversión. Sin migraciones. **No activa nada en producción.**

## Backend: `GET /api/work-orders/capabilities`
```json
{ "multi_machine": false }
```
- **Autenticación obligatoria** (401 sin sesión válida).
- **Permiso mínimo**: `work_order.read` **y** (`work_order.manage` o `assignment.manage`): Jefatura y Supervisión. Operación, Calidad y DATA_BALTREK no necesitan esta consulta → **403**, sin revelar el valor. (`work_order.read` solo lo tienen los cinco perfiles; se eligió el mínimo apropiado, el mismo criterio `_manages` que ya usa PR2 para las OT multimáquina.)
- **Valor** = `settings.work_orders_multi_machine_enabled is True` (estrictamente el booleano `True`; cualquier otro valor es `false`). Apagado por defecto.
- **Sin caché**: `Cache-Control: private, no-store`.
- **Solo ese campo**: ni ajustes internos, ni modos AUTHZ, ni versiones, ni datos de OT.
- **El cliente no puede cambiarlo**: la ruta no lee query, cuerpo ni cabeceras; solo existe `GET` (otros métodos → 404/405). Nada se escribe en PostgreSQL ni en auditoría.
- La ruta está registrada **antes** de `/{work_order_id}` (si no, «capabilities» se resolvería como identificador de OT); una prueba fija el orden y comprueba que el detalle de OT sigue resolviendo.

## Frontend
- `lib/vinto/work-orders-api.ts#getWorkOrderCapabilities` → `GET` simple con cookie, sin cuerpo ni query. `parseCapabilitiesResponse` es **estricto**: debe ser un objeto con `multi_machine` booleano; todo lo demás (JSON inválido, forma distinta, `"true"`, `1`) es un fallo → capacidad apagada.
- `useWorkOrderCapabilities(enabled, onUnauthorized, scope)` (`use-central.ts`) usa el mismo `useResource` que el resto de recursos centrales: clave **por sesión** (`work-order-capabilities:user:<id>`), se vuelve a pedir al volver a la pestaña (la compuerta puede cambiar en el servidor), y un 401 va al manejador de sesión perdida.
- Se consulta con sesión autenticada y `work_order.manage` (`bobinas-programming-source.tsx`). **Actualización PR7:** también con `assignment.manage`, para el botón de activación masiva (cada acción sigue dependiendo solo de su permiso).
- `capabilitiesOf(view)`: solo un recurso **listo** con `true` habilita. `idle`, `loading`, `error` (401/403/404/422/5xx/red/JSON inválido) → apagado. El panel muestra un aviso según el estado (confirmando / no se pudo confirmar / no habilitado) y mantiene el flujo tradicional de una sola máquina.
- Con `true`, el permiso `work_order.manage` y más de una máquina elegible, cada fila elige su máquina (PR6). Si el servidor deja de confirmar mientras hay un borrador con varias máquinas, el borrador vuelve a una sola máquina (`normalizeForMode`) en lugar de enviar máquinas mezcladas.
- **Sesión**: la clave incluye al usuario; al cambiar de cuenta o cerrar sesión la vista anterior nunca se presenta (`deriveView`), y una respuesta tardía de otra sesión no puede habilitar la interfaz (se aborta y se ignora por clave). Nunca hay `NEXT_PUBLIC_*`, almacenamiento local ni compuerta visual; un 422 (incluido `MULTI_MACHINE_DISABLED`) no habilita nada.
- La respuesta **no es una autorización**: el `POST /api/work-orders` vuelve a validar permisos, alcance, máquinas, artículos y la compuerta.

## Compatibilidad
Con `false` (o sin respuesta) la creación es exactamente la de PR6: una sola máquina, cuerpo histórico sin `machine_code` por línea. Los componentes de PR6 y los shells de Rebobinado/Conversión no cambian. El *stub* de pruebas de página (`scripts/int-02a-stubs/use-central.ts`) ganó el nuevo hook para seguir registrando todas las claves por sesión.

## Conciliación de las «32 / 33» pruebas heredadas de PR6
No hay discrepancia de pruebas, sino de conteo: el ejecutor de Node informó `fail 32`; el filtro del informe de PR6 contó las líneas que empiezan por `✖`, y entre ellas está la cabecera `✖ failing tests:` del resumen final. Así, **32 nombres únicos de pruebas fallidas + 1 cabecera = 33 líneas**. Verificado en esta rama sobre `origin/main` (857d549): `ℹ tests 899 / pass 867 / fail 32`, 32 nombres únicos, 1 cabecera. En la rama de PR6.1: `913 / 881 / 32`, **los mismos 32 nombres** (14 pruebas nuevas, 0 regresiones). Siguen siendo ajenas a este PR y no se tocaron.

## Riesgos y pendiente
1. Activar la funcionalidad sigue siendo una decisión operativa del propietario (compuerta del servidor, nunca en la VPS sin PR3–PR5 completos y revisión visual de PR6); este PR solo la hace *consultable*.
2. Sin evidencia visual ni pruebas de clic en navegador (el entorno no los tiene): el componente se prueba por render de servidor y la lógica interactiva en módulos puros.
3. La suite completa del backend no se ejecutó: el cambio es una ruta de solo lectura y su prueba; se ejecutaron las suites focalizadas de OT, asignaciones, activación masiva, visibilidad y autorización (312 pruebas, OK).
