# MF-08 · Calidad por máquina: P1-18, P1-22 y P1-26 (versión 2)

Observaciones MD_Ejec 31, 32, 37, 38, 39 y 40 del Excel funcional `MvP (Producción + Calidad) - v2.xlsx` (hoja `MD_Ejec.`). El Excel original **no se modifica**.

## Cambios aprobados

| Obs. | Formulario | Cambio | Detalle |
|---|---|---|---|
| 31 | P1-22 Grado de refinación Schopper (v2) | Retirar «Volumen desplazado» | Los demás campos y reglas no cambian. |
| 32 | P1-26 Medición de secos (v2) | «Punto de muestreo» pasa a lista desplegable obligatoria | Seis opciones cerradas, texto exacto = valor guardado: Caja de formación – Colador · Tela – Pick up · Fieltro I · Fieltro II · Prensa succión · Prensa ciega. Sin texto libre en capturas nuevas. |
| 37 | P1-18 Consistencia de cubas (v2) | Retirar «Punto de muestreo» | No se exige en la nueva versión. |
| 38 | P1-18 (v2) | Añadir «% Consistencia» justo después de «Masa seca g» | Decimal **digitado**, unidad visible %, **opcional** (ver «Decisiones conservadoras»). No se calcula. |
| 39 | P1-18 (v2) | Añadir «Hora» | Hora real del ensayo, digitada HH:MM (00:00–23:59), hora local de planta, **obligatoria**. Distinta de la hora automática de registro; no se convierte a UTC; no se deduce otra fecha al cruzar la medianoche (la fecha operativa sigue siendo la del registro). Se ubica tras «Número de cuba» (el Excel no indica posición). |
| 40 | P1-26 (v2) | Añadir «% Cantidad de seco» calculado | `% Cantidad de seco = masa seca / masa húmeda × 100`, dos decimales (mitad hacia arriba), solo lectura, calculado y validado en el backend. |

### Observación 40: campos usados
Los campos `masa_seca` y `masa_humeda` de **P1-26** son decimales sin unidad declarada en la definición (ninguno de los dos), del mismo formulario y de la misma naturaleza: la correspondencia es inequívoca. La fórmula del Excel `(((H−S)/H)−1)×100` daría −S/H×100; se aplica la fórmula aprobada funcionalmente. Con masa húmeda 0 **no hay resultado**: el campo no se guarda ni se muestra (no se inventa un valor ni se devuelve 0). El cliente no puede enviar el valor (422).

### Decisiones conservadoras
- **% Consistencia (38) opcional:** la obligatoriedad no se confirmó expresamente y no se infiere del símbolo %. Puede volverse obligatorio en una versión posterior.
- **Hora (39):** el Excel no indica posición; se colocó después de «Número de cuba».

## Fuera de alcance
- **MD_Ejec 33** (Absorción de humedad): pendiente de confirmar unidad y obligatoriedad. No se crea el campo.
- **MD_Ejec 51** (Crepado en %, P1-24): registrada abajo; **no se modifica P1-24**.

## Versiones

| Formulario | Antes | Ahora | Campos |
|---|---|---|---|
| VINTO-P1-18 | v1 | **v2** | 10 (v1: 9) |
| VINTO-P1-22 | v1 | **v2** | 5 (v1: 6) |
| VINTO-P1-26 | v1 | **v2** | 5 incl. 1 calculado (v1: 4) y 6 opciones |

Importación aditiva e idempotente, sin migraciones: crea 3 versiones, 20 campos, 6 vínculos de máquina y 6 opciones. Las versiones 1 y sus capturas se conservan; los campos retirados se leen como «versión anterior» y el punto de muestreo en texto libre de P1-26 v1 se muestra tal cual.

## Seguimiento: MD_Ejec 51 (nueva observación)

El Excel original tiene un renglón **sin número** (fila 25 de la hoja `MD_Ejec.`, entre las observaciones 22 y 23). Se registra formalmente como **MD_Ejec 51**:

| N.º | Origen | Módulo / perfil | Área / máquina | Formulario | Solicitud | Estado | Paquete |
|---|---|---|---|---|---|---|---|
| 51 | `MD_Ejec.`, fila 25, renglón sin número (referencia histórica: aparece tras la 22) | EJECUCION · FORMULARIO · QA.CALIDAD | BOBINAS · MP3/MP1 | PROPIEDADES FISICAS EN HUMEDAD (P1-24) | «La casilla digitable de CREPADO debe medirse como %» | **Pendiente** | Sin paquete asignado |

Requiere revisar la presentación y la unidad del campo Crepado (¿unidad «%» solo visible o cambio de medición?, ¿aplica a capturas anteriores?). No se modifica P1-24 ni sus registros.

El universo de seguimiento pasa de **50 a 51** observaciones; las 50 originales conservan su numeración y referencia. Pendiente de reflejar en el Excel de seguimiento (`VINTO_Seguimiento_Observaciones_Actualizado_2026-10-26.xlsx`), que no se modificó desde esta rama.

## Compatibilidad histórica
El backend sigue eligiendo la versión publicada más alta para capturas nuevas; cada captura conserva su `form_version_id`. Las capturas v1 de P1-18, P1-22 y P1-26 se leen con sus campos y valores de entonces; no se recalcula ni se inventa el % Cantidad de seco para registros históricos.
