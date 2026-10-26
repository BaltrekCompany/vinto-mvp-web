# MF-07 · Calidad: P1-21 (tabla de 27 posiciones), P1-24 y P1-25 (posiciones y promedios)

Observaciones MD_Ejec 21, 25 y 26 del Excel funcional `MvP (Producción + Calidad) - v2.xlsx` (hoja `MD_Ejec.`). El Excel original **no se modifica**.

## Corrección de correspondencia (decisión funcional P1)

El Excel asignó las observaciones 25 y 26 al formulario equivocado. El texto de cada una describe los campos del otro:

| Obs. | Nombre en el Excel | Formulario real | Evidencia |
|---|---|---|---|
| 21 | Perfil de gramaje y humedad | **P1-21** | Coincide. |
| 25 | «Propiedades físicas en humedad» | **P1-25** Resistencia en húmedo-curado | Pide renombrar resistencias longitudinales secas y húmedas (3 posiciones cada una) y habla de las elongaciones longitudinal y transversal: son los campos de P1-25. |
| 26 | «Resistencia en húmedo-curado» | **P1-24** Propiedades físicas en húmedo | Pide renombrar resistencias longitudinal y transversal en húmedo (3 posiciones cada una): son los campos de P1-24. |

Las dos elongaciones que la observación 25 dice que «faltan» ya existen en P1-25 (no se duplican).

## Decisiones funcionales aplicadas

- **Posiciones:** Comando, Medio y **Transversal** (la tercera se llama exactamente así). Reemplazan a centro / medio / extremo. Se mantienen el orden y las **claves técnicas**; solo cambian las etiquetas. La dirección de medición (longitudinal / transversal) va en la etiqueta aparte de la posición, separada por « – ».
- **Promedios:** media aritmética simple de las tres posiciones, dos decimales (mitad hacia arriba), solo lectura. El backend es la fuente de verdad: calcula y guarda; el cliente no puede enviarlos (422). Las capturas anteriores no se recalculan ni se alteran.
- **P1-21:** el % de humedad se digita en cada posición (no se calcula). Tabla de 27 posiciones numeradas; al menos una fila completa (Gramaje, Peso seco en kg y % Humedad); una fila a medias se rechaza; las filas vacías no se rellenan y un 0 es un valor. Tres promedios con solo las filas completas y cuántas posiciones se usaron.

## Versiones

| Formulario | Antes | Ahora | Cambio |
|---|---|---|---|
| VINTO-P1-21 | v1 (una posición por captura) | **v2** | Sin «Número de bobina» ni «Posición de perfil»; 81 campos decimales opcionales (`gramaje_NN`, `peso_seco_NN`, `humedad_NN`, NN = 01 a 27), `observaciones`, 4 calculados (`promedio_gramaje`, `promedio_peso_seco`, `promedio_humedad`, `posiciones_utilizadas`). |
| VINTO-P1-24 | v1, v2 | **v3** | Etiquetas de las 6 resistencias húmedas; calculados `promedio_longitudinal_humedo` y `promedio_transversal_humedo`. |
| VINTO-P1-25 | v1, v2 | **v3** | Etiquetas de las 6 resistencias longitudinales (secas y húmedas); calculados `promedio_resistencia_longitudinal_kgf` y `promedio_resistencia_longitudinal_humeda_kgf`. Caudal RH y # Cortes (MF-06) intactos. El «% de resistencia húmeda» no se pidió y no se calcula. |

## Implementación

- **Importador:** el paquete admite campos con origen `calculated` (nunca obligatorios); los automáticos siguen sin importarse. Importación aditiva e idempotente: solo se crean las 3 versiones nuevas (113 campos, 6 vínculos de máquina). Sin migraciones.
- **Backend (`backend/app/quality/capture_service.py`):** `_prepare_values` separa campos manuales y calculados, rechaza calculados enviados por el cliente, valida las filas de P1-21 y calcula los promedios solo si la versión publicada los declara. El reintento idempotente compara contra los mismos valores calculados.
- **Frontend:** `FieldSpec.renamedAt` (etiqueta por versión), campos `calculated` de solo lectura y `completeRows` (regla de filas completas) en `candidate-form.ts`; tabla editable de P1-21 y vista previa de promedios en `candidate-form-capture.tsx`; el historial muestra cada captura con las etiquetas y campos de su versión.

## Compatibilidad histórica

El backend sigue eligiendo la versión publicada más alta para capturas nuevas; cada captura conserva su `form_version_id`. Las capturas v1 (P1-21) y v1/v2 (P1-24, P1-25) se leen con sus campos y etiquetas de entonces; los campos retirados aparecen como «versión anterior» y no se inventan promedios.
