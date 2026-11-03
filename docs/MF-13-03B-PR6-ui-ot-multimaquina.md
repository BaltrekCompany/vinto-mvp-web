# MF13-03.B PR6 — interfaz de Jefatura para crear OT multimáquina (frontend)

Solo frontend. Consume los contratos de PR2 (`machine_code` por línea, `machine` en cada línea de la respuesta) y deja la creación multimáquina **apagada hasta que el servidor la confirme**. No cambia el backend, ni la activación (individual o masiva), ni la captura, ni F3/F6/Calidad/Seguimiento.

## Qué hace
- **Creación (Jefatura, `work_order.manage`)**: tabla editable de líneas locales con máquina, PV, producto, cantidad y entrega por fila; agregar y retirar filas del borrador (nunca toca lo persistido; siempre queda una fila; máximo 200 como el backend); resumen previo (`N línea(s) · M máquina(s): … · K producto(s)`); **una sola** `POST /api/work-orders` con todas las líneas. La máquina de cabecera es la de la primera fila y cada línea envía su `machine_code`. El número de OT y los `line_code` los devuelve el servidor y son los que se muestran (`OT … creada`); React no inventa ninguno.
- **Cambio de máquina en una fila**: se invalida el producto si ya no pertenece a esa máquina.
- **OT en borrador ya persistidas**: «Añadir una línea» por el endpoint existente (`POST /{id}/lines`); no hay edición ni retiro de líneas persistidas porque el backend no tiene ese contrato.
- **Consulta**: la tabla de cada OT muestra la **máquina de cada línea**, las máquinas de la OT y su máquina principal.
- **Publicación**: `POST /{id}/publish` existente, ahora tras una confirmación que indica el número de líneas y máquinas y que **la línea base publicada es inmutable**. Si el backend rechaza, se muestra el error y el borrador/pantalla se conservan.
- Sin botón de activación masiva; el botón individual «Activar» de Supervisión no cambia.

## Disponibilidad: la interfaz no tiene compuerta propia
La creación multimáquina solo se ofrece si **el servidor lo confirma** (`WorkOrderCapabilities.multiMachine`, `lib/vinto/work-order-capabilities.ts`), hay permiso de gestión y hay más de una máquina elegible. Hoy **no existe un contrato para consultarlo**, así que la aplicación pasa `NO_CAPABILITIES` y la creación queda en el flujo tradicional. No se usa `NEXT_PUBLIC_*` (se compila en el navegador y no garantiza lo que el servidor autoriza) y **ningún error enciende nada** (un 422 `MULTI_MACHINE_DISABLED` es solo un error; probado). Lo ausente o mal formado es «apagado»; solo `{"multi_machine": true}` estricto enciende.

### Endpoint de capacidades propuesto (para revisión; NO implementado aquí)
`GET /api/work-orders/capabilities` — autenticado, solo lectura, alcance mínimo:
- Permiso: cualquier sesión válida con `work_order.read` (o `assignment.read`); 401/403 como el resto.
- Respuesta: `{"multi_machine": <bool>}` con `settings.work_orders_multi_machine_enabled` (variable de servidor, sin cambios). Nada más (ni límites, ni versiones, ni datos de OT).
- `Cache-Control: no-store`; sin parámetros; el cliente no puede influir en el valor.
- Cuando exista: el contenedor de Programación lo consulta con el mismo patrón de recursos (`useResource`, clave por sesión), pasa `parseCapabilities(respuesta)` y trata cualquier error o 404 como apagado. Es un cambio de backend con sus pruebas, en un PR aparte.

## Máquinas y productos
- Existe un catálogo backend adecuado: `GET /api/production/machines?articles=true` (sectores concedidos y operativos, máquinas activas y los artículos de la relación artículo-máquina que el backend valida al crear). Rebobinado y Conversión ya lo usaban; **Bobinas ahora también** (`bobinas-programming-source.tsx`), por lo que `PRODUCTS_BY_MACHINE` deja de alimentar la creación. Solo queda como valor por defecto de `BobbinasProgramming` para llamadores que no entreguen catálogo (ninguno en la aplicación actual) y nunca es autorización: el backend valida igualmente.
- Si el catálogo está cargando o falla, la creación no se ofrece (las OT existentes siguen visibles). Antes, Bobinas ofrecía la lista estática aun sin backend.
- Evolución a varios sectores: `creation.machines` es una lista plana; basta que el contenedor concatene las máquinas de los sectores autorizados de la misma respuesta. Hoy cada pantalla de sector pasa solo las suyas (y filtra las OT por máquina de cabecera); abrir máquinas de otros sectores requiere decidir esa navegación y no se hace aquí. Nunca se ofrece una máquina que el backend no devuelva para la sesión.
- Falta (propuesta, sin implementar): el catálogo no distingue «máquinas que Jefatura puede programar» de «máquinas que la sesión puede operar»; hoy coinciden (alcance por sector). Si se separan, hará falta un campo o endpoint específico.

## Contratos TypeScript
- `WorkOrderLine.machine {code,name}` (parseo de PR2). Una respuesta **sin** `machine` en la línea (OT antigua / servidor anterior a PR2) toma la máquina de la cabecera; una `machine` presente pero inválida invalida la respuesta (nunca se descarta ni se sustituye). La línea de una asignación toma la máquina de la asignación.
- `LineDraft.machineCode?` opcional: ausente = cuerpo histórico idéntico (también para servidores anteriores a PR2, que rechazarían `machine_code`). `createWorkOrderLinesPayload` / `createWorkOrderWithLines` envían todas las líneas en una solicitud; `createWorkOrder` y `addWorkOrderLine` no cambian.
- El adaptador de Seguimiento (`toDisplayOt`) conserva exactamente su forma.

## Compuerta apagada (comportamiento por defecto)
| Aspecto | Resultado |
|---|---|
| Creación | Flujo tradicional: una máquina; se pueden preparar varias filas de esa máquina y se envían en una sola solicitud **sin** `machine_code` por línea (cuerpo histórico). |
| Selector de máquina | Solo la primera fila elige máquina; las demás la comparten (deshabilitado). Se avisa «Las OT con líneas en varias máquinas no están habilitadas por el servidor». |
| OT multimáquina ya existentes | Se muestran con la máquina por línea si el backend las devuelve a la sesión; el 404 por alcance no se interpreta ni se rellena. |
| Servidor con compuerta apagada y UI que la creyera encendida | No ocurre: la UI no envía `machine_code` distinto del de cabecera sin confirmación del servidor; si el servidor respondiera 422 se muestra el error genérico y el borrador se conserva. |

## Roles
Solo `work_order.manage` ve el borrador, publica y añade líneas. Supervisión y Operación ven «Solo lectura»; Supervisión conserva «Activar» por línea. La UI no expone nada de una OT que el backend no devuelva (PR2/PR5).

## Pruebas (ver el PR para los resultados)
- `scripts/pr6-order-draft.test.mjs` (22): parseo por línea y compatibilidad con OT antiguas, payload de una sola solicitud, borrador (3 filas MP1/MP1/MP3, retirar, cambiar máquina/producto, cantidades/fechas/PV/máximo 200), capacidades estrictas, doble envío, respuestas tardías y fallos.
- `scripts/pr6-programming-ui.test.mjs` (20): render real del componente en cada estado (compuerta apagada/encendida, una sola máquina, catálogo cargando/no disponible, OT existentes, borrador/publicada/antigua, roles, sin activación masiva) y cliente HTTP con `fetch` simulado (una solicitud, 401/403/404/409/422/5xx sin reintento, cuerpo malformado).
- Las interacciones (clics, diálogo) no se ejecutan en el render de servidor y el entorno no tiene DOM ni navegador: la lógica interactiva vive en módulos puros usados por el componente (`order-draft.ts`, `mutation-guard.ts#runGuarded`) y se prueba ahí; el cableado se fija con pruebas de fuente (diálogo de confirmación, sin almacenamiento local, sin `NEXT_PUBLIC`).
- Prueba existente modificada: `pb-clean-tracking.test.mjs` fijaba `<BobbinasProgramming ` en la página; ahora la página renderiza el contenedor `<BobbinasProgrammingSource ` (que renderiza el mismo componente con el catálogo del backend).

## Riesgos
1. Sin el endpoint de capacidades la creación multimáquina es inalcanzable por diseño; PR6 deja listo el cliente, el parser y las pruebas. Activarla exige el PR de backend, la compuerta del servidor (nunca en la VPS sin PR3–PR5 completos y decisión del propietario) y revisión visual.
2. La creación en Bobinas depende ahora de `GET /api/production/machines`; si falla no se ofrece crear (más seguro que mostrar una lista estática, pero es un cambio de comportamiento).
3. Evidencia visual: el entorno de desarrollo no dispone de navegador; la verificación de pantalla (jerarquía, ancho móvil de la tabla de 7 columnas, diálogo) queda pendiente de una revisión humana sobre la vista previa. La tabla usa desplazamiento horizontal como la existente.
4. Las 32 pruebas del frontend que ya fallan en `origin/main` siguen fallando igual (mismos nombres); no se tocaron.
