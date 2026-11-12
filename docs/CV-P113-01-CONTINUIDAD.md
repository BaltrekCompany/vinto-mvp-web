# VINTO – CV-P113-01 | Producción diaria de servilletas y especiales v3

> **Fuente de continuidad para GitHub y próximos chats.** Estado al 12/11/2026: desarrollo en rama `feat/cv-p113-servilletas-recetas-pallet-v3`; NO integrado, NO desplegado; producto actual en VPS SHA `a5c648c24e97f0ca8b74ab2adcf38e0b0b3a8e83` (P1-11 v3 PASS). No confundir desarrollo en rama con release productivo.

## Decisiones funcionales expresamente aprobadas por el usuario
- Rediseñar `VINTO-P1-13` v2 como **nueva versión v3**; mantener v1/v2 e historial; conservar OT/línea-PV/producto/máquina/turno/fecha desde la asignación.
- **Solo 2 secciones:** «1. Consumo de bobina» y «2. Producción por pallet». Eliminar por completo el bloque visual de «Sobreempaque e insumos» y campos legacy no solicitados.
- Captura de **una** bobina/material declarado **y un pallet por envío**. La etiqueta visual es **«Tipo de bobina»**. A pesar del nombre, el desplegable DEBE mostrar **TODOS** los materiales del producto en `MFRutaMaterialOP` (incluye empaque/sobreempaque, sin filtrar por `MaterialUso`). Se almacenará `Material` y se mostrará `Material · Descripcion`; backend valida el código contra la receta de producto de la OT.
- Caso de aceptación innegociable: artículo `11203` -> `BC-1229-210` (BC-REFILADO SERVILLETA G-19 CR-14% F-210 MM), `9570` (SERVILLETA PERLITA INSTITUCIONAL 200 (BOLSAS)), `9632` (AD SERVILLETA PERLA 200), exactamente esas tres opciones.
- Bobina: número libre + saldos inicial/ingreso/final en kg; consumo **solo derivado** = inicial + ingreso - final; sin mutación de inventario ni genealogía, sin confiar en un consumo enviado por el frontend.
- Pallet: un correlativo automático por OT+lÍnea, cantidad de jabas entero positivo, horas de inicio y fin HH:MM, peso nominal no editable de `INInventario.Peso` columna T por código de artículo, total = nominal × cantidad, ambos calculados y congelados en PostgreSQL. Para `11203`: **2.02 kg**. El peso depende del producto, NO del material seleccionado.
- Reutilizar cuanto sea posible el patrón y las barreras de P1-12 v4 (correlativo/atomicidad/idempotencia/snapshot/peso) y P1-11 v3 (receta y validación backend). No degradar P1-11 ni P1-12.
- Fuente entregada `INArticulo-MFMatrialOP (1)(3).xlsx`, SHA-256 `9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228`. Hojas `INInventario` / `MFRutaMaterialOP`. La copia `MFRutaMaterialOP (2)` replica rutas; tomar como autoridad la hoja sin sufijo. El usuario aprobó que este Excel sea la fuente de verdad, sin importar masivamente sus artículos.

## Resultado de la auditoría de alcance inicial
- 8 máquinas de P1-13 v2: `OMET_I`, `OMET_II`, `8_2`, `8_5`, `8002`, `SERV_4`, `WALLY`, `PANUELERA`.
- 22 artículos hoy autorizados en esas máquinas: 11102, 11103, 11104, 11110, 11202, 11203, 11204, 11205, 11206, 11307, 11308, 11309, 11313, 11314, 11316, 11317, 11318, 11319, 11320, 11321, 11502, 11503.
- 20 tienen receta; **11104 y 11202 carecen de ruta**: bloqueo de captura hasta que haya receta, nunca fallback a materiales de otros productos.
- 21 tienen unidad de inventario `Pack` y un peso en T. **11503 tiene unidad `UN` y peso 0.108486**: no inventar equivalencia con `kg/jaba`; bloquear cálculo/pallet hasta validación específica.
- Algunas filas de `Peso` valen 1. No corregirlas arbitrariamente: preservar trazabilidad del Excel y usar el valor aprobado por el maestro; documentar excepciones para revisión funcional.

## Condiciones técnicas y de aceptación
1. Nuevas definiciones v3 aditivas del formulario. No sobrescribir versiones publicadas ni romper capturas históricas.
2. En v3, selector y validación de receta se derivan **del artículo real de la asignación** (servidor); el cliente no puede cambiar producto ni enviar pesos/correlativos.
3. Correlativo pallet transaccional con protección de concurrencia; reintentos mismo `capture_id` no generan pallet duplicado.
4. Peso nominal por artículo, fuente con hash del Excel y snapshot inmutable del total al guardar; 11203 = 2.02; 11503 bloqueado hasta aclarar unidad.
5. No ejecutar cambios SQL productivos durante QA. Pruebas aisladas PostgreSQL 17, backend + frontend + regresiones P1-11/P1-12. No dar PASS antes de que corran.
6. Flujo: rama -> PR y QA -> revisión formal -> merge con autorización -> VPS: backup verificado, preparar SHA exacto y build Linux, dry-run de importación -> aplicar y activar **con autorización**, ejecutar por SSH el usuario. SSH VPS: `ssh -p 1724 ubuntu@51.79.65.225`; no incluir secretos en GitHub.
7. Las capturas actuales de VINTO son ficticias (informado por el usuario). Conservar igualmente permisos, backups y salud de PostgreSQL.

## Guía de continuidad
Si el chat termina, abrir este documento, revisar el estado real del PR y su CI, comprobar el último SHA de `main` y de la rama antes de continuar. Nunca afirmar despliegue por un merge. El usuario ejecuta manualmente los comandos de SSH/SCP (SCP utiliza `-P 1724`).

## Pendientes de cierre
- Implementación, pruebas y revisión del PR en esta rama.
- Verificación funcional de 11203 y pesos; reglas de rango, error por receta faltante y equivalencia de unidades.
- Merge y despliegue controlados cuando estén autorizados.
