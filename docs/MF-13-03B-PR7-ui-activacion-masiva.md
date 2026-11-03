# MF13-03.B PR7 — interfaz de Supervisión para la activación masiva (frontend)

Solo frontend. Consume `POST /api/work-orders/{id}/activate-all` (PR4) sobre la pantalla real de **Bobinas**. No cambia el backend, la activación individual, la creación y publicación de OT (PR6), la consulta de capacidades (PR6.1), la autorización de PR5, F3/F6, Calidad, Seguimiento ni el correlativo P1-16. Sin migraciones; 0012 no se implementa. No activa ninguna compuerta ni modo AUTHZ.

## Flujo
1. En una OT **publicada o en ejecución**, Supervisión ve **«Activar todas las líneas»**, junto a los botones individuales (que no cambian).
2. Al pulsarlo se abre un diálogo y se pide la **vista previa** (`{"dry_run": true}`, solo lectura). Muestra OT, resumen, líneas por activar / ya activas / bloqueadas (con motivo), asignaciones vencidas de la misma OT que se finalizarán y conflictos con otras OT, con máquina, producto, PV, turno y fecha operativa que **resuelve el servidor**.
3. **Confirmar** solo está habilitado si `can_confirm` es verdadero **y** hay algo que aplicar. Envía `{"dry_run": false, "plan_hash": <el hash recibido, sin tocar>}` en **una sola** solicitud (nunca una por línea).
4. «Activación» se informa solo con el éxito real del servidor: `201 applied` («Se activaron N línea(s); M ya estaban activas; se finalizaron K asignación(es) vencida(s).») o `200 already_in_effect` («El plan ya estaba aplicado…», sin segunda activación ficticia). Tras un éxito se reconcilian las listas con GET.

## Contrato y cliente (`lib/vinto/activate-all.ts`, `work-orders-api.ts`)
- Cuerpos exactos: `{"dry_run":true}` y `{"dry_run":false,"plan_hash":"<64 hex>"}`. El navegador no genera ni recalcula el hash (una prueba lo impide en el código) y no envía máquina, turno, fecha ni ids operativos. Un hash con forma inválida **no sale** del navegador.
- Parser **estricto** validado contra respuestas **reales de la API de PR4** (`scripts/fixtures/activate-all/*.json`, volcadas del backend en una base de pruebas: vista previa, `applied` 201, `already_in_effect` 200, vista previa sin nada que hacer, conflicto y el 409 `ACTIVATION_BLOCKED`). Valida `dry_run`, `outcome`, `work_order`, `status`, `plan_hash`, `can_confirm`, `summary`, `lines`, `expired`, `conflicts`, `activated`, `already_active`, `finished` y sus estructuras anidadas, **y su coherencia interna**: el resumen coincide con las listas, `can_confirm` es verdadero solo sin bloqueos ni conflictos, el motivo existe solo en líneas bloqueadas, y cada `outcome` solo trae las listas que le corresponden. Una respuesta malformada o contradictoria es un fallo, nunca una confirmación.
- La respuesta a una vista previa solo vale como vista previa; la de una confirmación solo como confirmación, **con el mismo hash enviado** y con estado HTTP coherente (201↔`applied`, 200↔`already_in_effect`).

## Errores y reconciliación (`lib/vinto/activate-all-flow.ts`)
| Respuesta | Comportamiento |
|---|---|
| 201 `applied` / 200 `already_in_effect` | resultado real; reconcilia |
| 409 `ACTIVATION_PLAN_CHANGED` (o cualquier 409 sin código conocido) | «La programación o el turno cambió; vuelve a consultar la vista previa.» Se descarta el plan y su hash; **no se reenvía** |
| 409 `ACTIVATION_BLOCKED` | «La activación está bloqueada…»; permite actualizar la vista previa; no hubo cambios |
| 401 | mecanismo existente de sesión perdida |
| 403 / 404 | «No se puede consultar esta orden de trabajo.», sin detalles de OT ni máquinas |
| 422 `MULTI_MACHINE_DISABLED` | se deshabilita la activación masiva y se vuelven a pedir las capacidades (solo se rehabilita si el servidor confirma `true` otra vez) |
| Red, 5xx, JSON inválido o respuesta contradictoria **tras confirmar** | «incierto»: **nunca se repite el POST** (el servidor pudo haberlo aplicado); solo se ofrece una vista previa de solo lectura. Si sí se aplicó, esa vista previa muestra todo activo y «no hay nada que confirmar» (sin duplicar) |
Conflicto con otra OT: «La máquina MP1 tiene líneas activas de otra OT (OT-…). Finaliza esas asignaciones desde Supervisión antes de continuar.» Confirmar queda deshabilitado; **no** se finaliza ni se sustituye nada automáticamente y no existe `replace_assignment_ids`.

## Capacidades y permisos
- `BobbinasProgrammingSource` consulta `GET /api/work-orders/capabilities` cuando el usuario tiene `work_order.manage` **o** `assignment.manage` (el endpoint admite a Jefatura y Supervisión). Cada acción depende solo de su permiso: **crear/publicar = `work_order.manage`; activar = `assignment.manage`**. Supervisión no crea, edita ni publica la línea base.
- El botón masivo exige `multi_machine: true` del servidor + `assignment.manage` + OT publicada o en ejecución; loading, error, 401/403/404/5xx, JSON inválido o `false` lo ocultan. El botón no es una autorización: el backend verifica permisos, alcance, turnos, conflictos y compuerta en cada solicitud.

## Seguridad de la interacción
Una escritura a la vez (`mutation-guard`): el doble clic envía **una** confirmación. No se confirma sin una vista previa vigente; mientras la confirmación está en vuelo no se puede cerrar, refrescar ni abandonar con Escape. El diálogo está ligado a la sesión y a la OT (`key = sesión:OT`): cambiar de OT, de usuario o terminar la sesión desmonta el diálogo, descarta el plan y ignora cualquier respuesta tardía (también un 401 tardío). El hash vive solo en memoria: sin `localStorage`, `sessionStorage`, cookies ni registros en consola (verificado por pruebas de fuente).

## Diseño y accesibilidad
Estilo Baltrek existente. Tablas de **tres columnas** (línea y máquina / producto y PV / turno y fecha; «motivo» solo en bloqueadas) que caben en móvil **sin desplazamiento horizontal**, con el resumen siempre visible arriba. Secciones separadas con encabezados `h3`, `aria-labelledby`, `caption` y `th scope="col"`; estado con `aria-live`, errores con `role="alert"`. Radix `Dialog` aporta trampa de foco y Escape (el **retorno del foco al botón NO lo daba Radix** en este diálogo, que se abre por estado sin `DialogTrigger`: DEF-1, corregido en PR-A, `docs/MF-13-03B-PRA-dialogo-foco-contraste.md`); toda acción es un `<button>`. El orden del DOM es **Cerrar → Actualizar → Confirmar**: el foco inicial nunca cae sobre la confirmación, en escritorio la acción principal queda a la derecha y en móvil arriba. Cambio colateral: el contenedor de la insignia de estado de cada OT alinea sus elementos (`flex-wrap items-center`), porque la insignia se estiraba a un círculo.

## Evidencia
- **Pruebas automáticas** (`scripts/pr7-activate-all.test.mjs`, 34): parser contra respuestas reales y ~40 variantes malformadas/contradictorias, cuerpos exactos, cliente con `fetch` simulado (una solicitud, 201/200, 401/403/404/409 con código/422/5xx/red/JSON inválido, sin reintento), máquina de estados (sin confirmar sin vista previa, doble clic, respuestas de otra OT o tardías, cierre bloqueado, fallo → plan descartado, recuperación sin duplicar), render real del panel en cada estado, botón y permisos por perfil/capacidad/estado de OT, y cableado. Mutaciones (confirmar ignorando `can_confirm`, conservar el plan tras un fallo, relajar la coherencia de `can_confirm`) rompen las pruebas esperadas.
- **Capturas** en `docs/MF-13-03B-PR7-evidencia/` (Chrome headless sobre el marcado de los componentes reales y el CSS compilado, tema claro; móvil en un iframe de 390 px): `01` programación de Supervisión con el botón nuevo, `02` vista previa, `03` conflicto (móvil), `04` vencidas por finalizar, `05` resultado (móvil), `06` respuesta perdida (móvil).
- **Límite explícito**: las capturas son una **composición estática** del marcado real, no una sesión de navegador contra la aplicación y el backend. **No hay E2E real**: no se ejercitaron clics, el diálogo Radix en vivo (foco, Escape), ni la red. Eso es lógica probada + render de servidor.

### Validación manual pendiente (con compuerta encendida solo en un entorno aislado)
1. Supervisión: botón visible en OT publicada/en ejecución y ausente en borrador; Jefatura sin `assignment.manage` y Operación no lo ven.
2. Vista previa no cambia nada (comparar asignaciones antes/después); Confirmar activa L1/L2 (MP1) y L3 (MP3) con una sola petición en la pestaña de red.
3. Doble clic rápido: una petición. Escape/clic fuera con la confirmación en vuelo: no cierra.
4. Con otra OT activa en MP1: Confirmar deshabilitado y mensaje de conflicto; la otra OT intacta.
5. Cortar la red tras pulsar Confirmar: mensaje «incierto», sin reintento; «Consultar la situación» muestra el estado real.
6. Cambiar de turno entre vista previa y confirmación: 409 y nueva vista previa. Perder la sesión: vuelve al inicio de sesión.
7. Teclado: abrir con Enter, tabular (Cerrar → Actualizar → Confirmar), Escape cierra, el foco vuelve al botón.

## Integración pendiente en otros frentes
**Rebobinado y Conversión** usan el mismo `BobbinasProgramming` a través de `sector-central.tsx`, que **no** recibe capacidades, alcance de sesión ni el callback de refresco: por eso no muestran el botón masivo (queda apagado, no roto). Habilitarlos requiere decidir esa integración (consultar capacidades dentro del shell, pasar `scope` y `onCapabilitiesStale`) y validar el alcance de sectores de la OT con el backend de PR4; no se hace ni se afirma aquí. Operación (selección de líneas y captura) es PR8.

## Riesgos
1. Activar la funcionalidad sigue dependiendo de la compuerta del servidor (no en la VPS sin decisión del propietario y validación manual de arriba).
2. Sin E2E de navegador (ver «Límite explícito»).
3. El backend no se modifica y su suite no se ejecutó; el contrato de PR4 se verificó con respuestas reales volcadas de su API.
4. Dependencias heredadas: la garantía de «una activa por máquina» con la compuerta apagada (0012) sigue sin implementar.
