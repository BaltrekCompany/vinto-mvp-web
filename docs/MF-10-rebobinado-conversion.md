# MF-10 · Rebobinado y Conversión (versión 2 de P1-07, P1-10, P1-29, P1-30 y P1-12)

Observaciones MD_Ejec 23, 24, 30, 34, 43 y 47 del Excel funcional `MvP (Producción + Calidad) - v2.xlsx` (hoja `MD_Ejec.`). El Excel original **no se modifica**.

## Cambios implementados

| Obs. | Formulario (máquinas) | Cambio |
|---|---|---|
| 23 | **P1-07** (Beloit, Over, Copasa) | El formulario de producción se llama «Registro de producción de bobinas **rebobinadas**» (v2). La definición legacy y el reporte conservan «refiladas»; el identificador técnico `VINTO-P1-07`, los campos y la genealogía no cambian. |
| 24 | **P1-10** (solo COPASA) | Se retiran «Código / número de producto» (el producto sale de la OT) y «Número de fardo». **No se genera ningún correlativo.** La v1 conserva sus números de fardo. |
| 30 | **P1-29** (Tubetera) | Se retiran «Peso fardo» y «Peso» por formato; «Tipo de tubete» → «**Formato de tubete**» (misma clave); espesor en **mm**; diámetro interno y externo pasan a **texto** (un campo cada uno, p. ej. `77-78`, sin interpretar ni normalizar). Las filas repetibles no cambian. |
| 34 | **P1-30** (Perichun) | Se retiran Gramaje, Número MRP, Resistencia longitudinal y Resistencia transversal; se añade «**Lote**» (texto, obligatorio) donde estaba la resistencia longitudinal. No se inventa un Lote para capturas anteriores. |
| 43 | **P1-12** (Gambini, Sincro II y III) | «Formato» pasa de decimal a **texto libre**: `4*12`, `4X12`, `4x12`, `4.12` se conservan exactamente (sin normalizar). Los valores históricos decimales se leen sin conversión. |
| 47 | **P1-07, P1-10, P1-29, P1-30** | «**Hora inicio**» y «**Hora fin**» (HH:MM, hora local de planta), obligatorias desde la v2. Se digitan: no se derivan de la hora de registro, no se convierten a UTC, no se calcula duración ni se valida que fin sea posterior a inicio ni cruce de día, y no se asume otra fecha. Se colocan al inicio del formulario (el Excel no indica posición). |

## Pendientes explícitos (no implementados)
- **Obs. 24 · numeración automática del número de fardo:** VINTO pidió que se cuente solo al ingresar el peso. No está aprobada: requiere un contador y definir su alcance (¿por OT, turno o máquina?; concurrencia). El backend no necesita un número de fardo (no es obligatorio en la v2): no se fabrica uno. Tampoco se añaden Beloit ni Over a P1-10.
- **Obs. 30 · unidad en metros (m):** VINTO no confirmó a qué campo corresponde. No se añade «m» a ningún campo ni se convierte nada.
- **Obs. 47:** cálculo de duración, orden inicio/fin, cruce de medianoche e integración con TVC/Power BI/ETL quedan fuera.

## Versiones e importación
Versionado aditivo e idempotente, sin migraciones: P1-07, P1-10, P1-12, P1-29 y P1-30 pasan de v1 a **v2** (la v1 y sus capturas se conservan). Dry-run sobre el estado de producción (base efímera): 5 versiones, 88 campos (38 + 4 + 20 + 17 + 9), 9 vínculos de máquina, 2 grupos de campos y 0 opciones, sin conflictos.

## Compatibilidad histórica
Cada captura se lee con la definición de **su** versión (`parseCaptureOf` pasa la versión del formulario a los parsers de P1-10 y P1-29; los formularios genéricos usan `sinceVersion` y campos `legacy`). Los campos retirados se muestran como «versión anterior» en el historial; no se recalcula ni se inventa ningún valor (ni horas ni Lote).
