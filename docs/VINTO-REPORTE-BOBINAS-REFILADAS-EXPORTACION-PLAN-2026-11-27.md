# VINTO — Reporte de Bobinas Refiladas para Exportación
## Plan funcional y técnico previo al desarrollo

**Fecha:** 27 de noviembre de 2026  
**Estado:** planificación documentada; pendiente de revisión y decisiones funcionales.  
**Tipo de cambio de este PR:** solo documentación. No incluye código, migraciones, cambios de VPS ni despliegue.

## 1. Fuentes revisadas

1. **`Especificacion_funcional_reporte_bobinas_exportacion(1).pdf`** — documento funcional de seis páginas, indicado como especificación cerrada para construcción.
2. **`Reporte_Produccion_Rebobinado_Mockup(1).pdf`** — ejemplo titulado “Reporte de Producción Rebobinado”, con granularidad fecha + máquina + turno + producto.

### Distinción entre los dos PDF

El segundo archivo no es el formato de salida de “Bobinas Refiladas para Exportación”: muestra un reporte de producción por fecha, máquina, turno y producto, con totales de bobinas crías y materia prima/insumos. Se puede utilizar como referencia contextual del circuito de Producción de Rebobinado, pero no sustituye el diseño de exportación.

El formato de salida para exportación está incluido dentro de la propia especificación funcional, página 6: A4 vertical, blanco y negro, cuadrícula delgada, cabecera compacta, veinte líneas disponibles y observaciones al final.

**Pendiente de confirmar:** si el segundo PDF fue adjuntado únicamente como referencia de los datos de Producción de Rebobinado o si Functional espera que alguna parte de ese diseño también se reutilice en el reporte de exportación.

## 2. Objetivo funcional

Construir un reporte parametrizable para que el operario de máquina de Rebobinado seleccione PV, producto, bobina madre y crías aceptadas por Calidad; conforme paquetes físicos de hasta cinco crías; complete número de camión, número de orden y observación general; revise una vista previa y genere el PDF.

No se construirá un formulario para volver a capturar datos de Producción o Calidad. La información técnica debe recuperarse de los registros ya existentes.

### Incluye

- Selección dependiente PV activo → producto → bobina madre.
- Selección de una a cinco crías aceptadas y disponibles por paquete.
- Una línea del reporte equivale a un paquete físico.
- Una misma madre puede aparecer en varias líneas si sus crías se distribuyen en paquetes distintos.
- Autocompletado de máquina, formato, destino, fecha, diámetro, corte, tubete, ayudante y operador original.
- Número de camión, número de orden y una observación general.
- Agregar, editar y eliminar paquetes.
- Vista previa, generación PDF e historial.
- Revalidación transaccional antes de confirmar.

### Fuera de alcance

- Nueva captura de producción.
- Nueva evaluación o decisión de Calidad.
- Redigitación de pesos o parámetros técnicos.
- Creación de códigos artificiales de paquetes o crías.
- Cambios a la captura P1-07, a los controles de Calidad o al circuito F3 de Bobinas.
- Consumo de inventario, balance de masa, mermas o genealogía industrial nueva.

## 3. Secuencia de uso propuesta

1. Seleccionar PV activo.
2. Seleccionar producto asociado al PV.
3. Seleccionar bobina madre del PV + producto.
4. Seleccionar Cría A obligatoria y Crías B–E opcionales, todas aceptadas y disponibles.
5. Agregar el paquete; repetir para conformar otras líneas.
6. Completar número de camión, número de orden y observaciones generales.
7. Revisar vista previa y generar el PDF.

La primera madre seleccionada fija máquina, formato y destino del reporte. Todas las líneas deben mantener PV, producto, formato, destino y máquina consistentes.

## 4. Matriz funcional que debe implementarse

| Dato | Comportamiento | Fuente / regla |
|---|---|---|
| PV | Seleccionable | PV activos presentes en Producción de Rebobinado |
| Producto | Seleccionable y dependiente | Solo productos asociados al PV elegido |
| Bobina madre | Seleccionable | Madres del PV + producto; la primera fija el contexto del reporte |
| Cría A | Obligatoria | Cría de la madre, con peso, Calidad Aceptada y no asignada a otro reporte vigente |
| Crías B–E | Opcionales | Mismo filtro; máximo cinco crías por paquete |
| Formato | Automático | Producción de Rebobinado de la madre |
| Destino | Automático | Producción de Rebobinado de la madre |
| Máquina | Automático | Máquina que produjo la madre |
| Fecha | Automático | Fecha/hora de generación del reporte |
| N.° camión | Digitado | Obligatorio |
| N.° orden | Digitado | Obligatorio |
| Diámetro / Corte / Tubete | Automático | Registro productivo de origen |
| Ayudante | Automático | Registro productivo de origen |
| Operador | Automático | Usuario que creó el registro productivo de origen; no el generador del reporte |
| Observaciones | Digitado | Opcional; una sola sección general al final |

El selector de crías debe mostrar exactamente el patrón “Cría N - peso kg”. El número N se deriva de la posición real del campo de origen; no se digita.

## 5. Hallazgos técnicos del repositorio

Esta sección distingue lo que el código actual garantiza de las decisiones que aún requieren validación.

### 5.1 Captura P1-07 y crías

- El formulario técnico de origen es `VINTO-P1-07` (“Registro de producción de bobinas rebobinadas”; el nombre del reporte conserva “refiladas”).
- `backend/app/rewinding_children.py` crea crías para capturas P1-07 desde versión 3 en adelante. Las capturas v1/v2 no generan crías retroactivamente.
- Las posiciones admitidas son 1–11 y 13–22. No existe posición 12.
- Cada peso informado crea una unidad técnica de cría con UUID y `rewind_child_position`; el peso se guarda en `weight_kg`.
- Cada cría nace con `quality_release.status = 'pending'` dentro de la misma transacción de la captura.
- La decisión de Calidad se guarda por cría y los estados técnicos actuales son `pending`, `released` y `rejected`.

**Mapeo propuesto, pendiente de homologación funcional:** “Aceptada” en el reporte equivale a `quality_release.status = 'released'`. `pending` y `rejected` se excluyen.

### 5.2 Identidad de la madre: diferencia importante frente al lenguaje funcional

El modelo P1-07 vigente no identifica una bobina madre como una bobina F3 real:

- `etiqueta_numero_de_bobina` es texto declarado por Operación.
- La madre técnica se identifica internamente mediante `rewind_mother_capture_id` (UUID de la captura P1-07).
- La fila técnica de madre no consume correlativo F3, no tiene `quality_release`, no referencia una bobina F3 y no crea `bobbin_relation`.
- Las crías guardan `rewind_mother_label` y su posición real.

Por ello, el reporte puede utilizar la etiqueta declarada para mostrar “Bobina madre” y el UUID de captura como clave interna estable, sin mostrar códigos técnicos `MADRE-...` o `CRIA-...` al operario. No debe presentarse como genealogía física F3 ni validar contra una bobina MP1/MP3, salvo que Functional cambie expresamente la decisión existente.

**Decisión CONFIRMADA por el usuario (27/11/2026):** “bobina madre” en este reporte significa la madre declarada de P1-07 identificada internamente por el UUID de su captura. No se buscará ni exigirá una bobina F3 real. No se crea genealogía industrial nueva.

### 5.3 Relaciones de origen

El código actual permite derivar el contexto de producción desde:

`capture → assignment → work_order_line → work_order_version → work_order`

- PV: `work_order_line.pv_reference`.
- Artículo asociado: `work_order_line.article_version_id` → artículo y descripción.
- Máquina y fecha operativa: captura y máquina de origen.
- Valores manuales P1-07: `capture_detail`, asociados a las claves de campo de la versión de formulario.
- Usuario creador original: `capture.created_by`.

La consulta definitiva debe conservar el UUID de captura como identidad de madre. No debe agrupar madres únicamente por la etiqueta, porque una etiqueta declarada puede repetirse.

### 5.4 Campos que requieren mapeo exacto

P1-07 contiene campos como `destino`, `producto_refilado`, `formato_1`, `formato_2`, `formato_3` (actualmente rotulado “Cortes”), `diametro`, `tubete`, `auxiliar` y pesos de crías.

Antes de codificar se debe comparar el valor del artículo de la línea de OT con `producto_refilado`, y definir cómo se compone el campo de salida “Formato” y cómo se presenta “Corte”. No se deben concatenar ni reinterpretar campos sin aprobación de Functional.

### 5.5 Disponibilidad real y documentación histórica

El código actual incluye REBOBINADO en `DEFAULT_OPERATIONAL_SECTORS` y P1-07 en `CENTRAL_FORM_CODES`. Sin embargo, algunos documentos históricos de M4-A/M4-B1 y comentarios de P1-07 conservan estados anteriores de “no habilitado”, “candidato” o “solo prueba”.

La disponibilidad efectiva no se inferirá solo de esos documentos ni del código: RBE-01 verificará en la VPS, en modo de solo lectura, las máquinas, versiones P1-07 publicadas, capturas v3+, PV, artículos, valores, usuarios creadores y estados de Calidad realmente presentes.

## 6. Persistencia, estados y concurrencia

A diferencia del reporte de Tubetes, esta especificación exige guardar el reporte y mantener un historial. No debe implementarse como una descarga efímera.

La solución técnica deberá persistir, como mínimo:

- Cabecera: PV, producto, máquina, formato, destino, camión, orden, observaciones, usuario generador, fecha/hora y estado.
- Líneas de paquete, con orden.
- Relación de cada paquete con los UUID de las crías seleccionadas, conservando posición real y peso de origen.
- Snapshot inmutable de los datos usados para generar el PDF.
- PDF emitido o representación inmutable suficiente para volver a descargar exactamente el mismo documento, sin reconstruirlo con datos productivos posteriores.
- Integridad/auditoría de creación, generación, observación y anulación.

### Estados funcionales

| Estado | Comportamiento especificado |
|---|---|
| Borrador | Editable; no reserva definitivamente las crías |
| Generado | PDF emitido; crías asignadas y bloqueadas |
| Observado | Una cría cambió de estado o existe una inconsistencia |
| Anulado | Registro histórico conservado sin efecto; requiere motivo |

### Confirmación transaccional

Al generar, el backend debe volver a validar en una única transacción:

- PV/producto/madre y pertenencia de cada cría.
- Estado de Calidad aceptado.
- Ausencia de asignación a otro reporte vigente.
- No repetición de una cría dentro del reporte ni entre paquetes.
- Consistencia de PV, producto, formato, destino y máquina.
- Que el estado no haya cambiado desde la selección.

La transacción debe bloquear o serializar la asignación de crías para impedir que dos operarios generen simultáneamente reportes con la misma cría. Una colisión debe terminar en conflicto controlado (409), sin generar PDF ni reservar parcialmente.

**Diseño pendiente:** definir la persistencia del borrador, el almacenamiento del PDF/snapshot, el efecto de anular un reporte sobre la disponibilidad de sus crías y el tratamiento exacto de un reporte observado.

## 7. PDF de salida

La página 6 de la especificación es la referencia visual:

- A4 vertical.
- Blanco y negro, sin tarjetas, colores ni gráficos.
- Cuadrícula delgada y cabecera compacta.
- Veinte líneas disponibles.
- Observaciones generales al final, no por paquete.

### Encabezado

Título, máquina, camión, orden, producto, fecha, formato, PV y destino.

### Detalle por paquete

N.°, bobina madre, Crías A–E con número/peso, diámetro, corte, tubete, ayudante y operador.

### Cierre

Una única sección general de observaciones.

**Decisión pendiente:** confirmar si veinte líneas es un máximo de veinte paquetes por reporte o veinte líneas por página con paginación para reportes mayores. La especificación no declara un máximo total de paquetes.

## 8. Validaciones bloqueantes de la especificación

| Código | Condición |
|---|---|
| V01 | PV o producto sin seleccionar |
| V02 | N.° de camión o N.° de orden vacío |
| V03 | Línea sin bobina madre o sin Cría A |
| V04 | Cría repetida en dos paquetes |
| V05 | Cría pendiente, rechazada, sin evaluación o ya utilizada |
| V06 | Cría que no pertenece a la madre seleccionada |
| V07 | Mezcla de PV, producto, formato, destino o máquina en un reporte |
| V08 | Cambio de estado de una cría entre selección y confirmación |

## 9. Permisos propuestos

El responsable funcional indicado es el operario de máquina. El perfil OPERACION actual tiene `production.capture`, pero no `report.read`; JEFATURA y SUPERVISION tienen `report.read`.

No se debe ampliar globalmente `report.read` para resolver el acceso. Se diseñará un permiso específico para generar el reporte de exportación en REBOBINADO, con alcance por sector/máquina y reglas de historial.

Propuesta para aprobar:
- OPERACION: crear/generar reportes dentro de su alcance autorizado y consultar los propios.
- SUPERVISION/JEFATURA: consultar historial dentro del alcance autorizado; definir quién puede anular y con qué motivo.
- Backend como autoridad; la visibilidad del botón no sustituye autorización.

## 10. Plan incremental

| Fase | Objetivo | Entregable |
|---|---|---|
| RBE-01 | Auditoría de fuentes en VPS, solo lectura | Matriz real de PV, productos, madres, crías, versiones, estados de Calidad, campos y usuarios |
| RBE-02 | Diseño técnico y cierre de decisiones | Contratos API, mapeo campo a campo, modelo de persistencia, permisos, estados, concurrencia y snapshot |
| RBE-03 | Interfaz parametrizable | Filtros PV → producto → madre, selección de crías, paquetes, edición/eliminación y vista previa |
| RBE-04 | Backend, reglas y persistencia | Cabecera, paquetes, crías asociadas, reserva transaccional, historial y estados |
| RBE-05 | PDF e historial descargable | PDF fiel a la página 6, snapshot inmutable y re-descarga |
| RBE-06 | QA y despliegue | Matriz funcional, regresión, CI, respaldo, gates D2 y QA en la VPS existente |

Cada fase de código tendrá PR independiente, CI verde y revisión antes de merge. El despliegue se realizará en la VPS existente, siguiendo el procedimiento de respaldo, restauración aislada, gates D2 y rollback que ya utilizamos para Tubetes.

## 11. QA previsto

- Filtro dependiente PV → producto → madre.
- Solo madres del PV/producto elegidos.
- Solo crías released/Aceptadas, con peso y disponibles.
- Posiciones reales 1–11 y 13–22; nunca crear posición 12.
- Selector “Cría N - peso kg”.
- Una a cinco crías por paquete; Cría A obligatoria.
- Una madre en varios paquetes.
- Ninguna cría repetida.
- Dos operadores intentando reservar la misma cría en paralelo.
- Cambio de estado Calidad entre selección y confirmación.
- Consistencia de los campos automáticos y del operador original.
- Veinte líneas, y paginación si se aprueba.
- PDF descargado, historial y re-descarga idéntica.
- Cambios a Calidad posteriores y estado Observado.
- Anulación con motivo y disponibilidad resultante de las crías.
- Permisos de Operación, Supervisión y Jefatura.
- Regresión de Producción, Calidad, P1-07, F3 y Calidad Offline.

Las pruebas de concurrencia y de cambios de estado usarán PostgreSQL 17 efímero y fixtures sintéticos. La auditoría inicial de la VPS será de solo lectura. Cualquier prueba que genere registros persistentes en la VPS requerirá autorización específica.

## 12. Decisiones que deben cerrarse antes de desarrollar

1. **Identidad de madre — CONFIRMADA (27/11/2026):** usar etiqueta declarada P1-07 + UUID de captura; no bobina F3.
2. **Producto:** confirmar si se muestra el artículo de la OT, `producto_refilado` o ambos; definir prioridad si difieren.
3. **Formato y corte:** confirmar el mapeo de `formato_1`, `formato_2` y `formato_3` al encabezado “Formato” y detalle “Corte”.
4. **Segundo PDF adjunto:** confirmar si es solo referencia del origen de Producción de Rebobinado; el formato exportación seguirá la página 6 de la especificación salvo decisión distinta.
5. **Veinte líneas:** máximo total o líneas por página con paginación.
6. **Permisos e historial:** quién genera, consulta todos/propios y anula.
7. **Estados y reserva:** cuándo se persiste un borrador, cómo libera crías una anulación y cómo se mantiene Observado.
8. **Fecha de reporte — CONFIRMADA:** utilizar la zona horaria operativa de planta `America/La_Paz`.

## 13. Límites de este incremento documental

- Este documento no implementa el reporte.
- No modifica P1-07, F3, formularios de Calidad, decisiones de Calidad ni catálogos.
- No añade migraciones ni tablas.
- No modifica permisos.
- No ejecuta consultas ni escrituras en la VPS.
- No modifica Calidad Offline, PWA, IndexedDB, firmas, grants, cola ni sincronización.
- No despliega ni fusiona código funcional.

**Siguiente acción:** ejecutar RBE-01, auditoría de solo lectura en la VPS, con la identidad de madre ya confirmada. Las demás decisiones funcionales siguen abiertas y se cerrarán con la evidencia de RBE-01 y Functional antes de implementar.


## 14. RBE-01 — Primera pasada de auditoría (27/11/2026)

**Resultado: `RBE01_READ_ONLY=BLOCKED`.** Esta pasada no consultó PostgreSQL. No debe interpretarse como auditoría de datos productivos ni como validación de disponibilidad real.

### Entorno y alcance comprobados

- Host reportado: `vps-14d8e0ce`.
- Backend en release `35e64d0d75900d04b1fe11cb8902f6d1b3fd69c2`.
- Backend/frontend activos, sin reinicios reportados; health endpoints 200 y base disponible.
- PostgreSQL 17.11; contenedor healthy, sin reinicios reportados.
- `main` de GitHub se encontraba en `64359c4` (FOFF-02), diferente del release productivo. La auditoría de código debe referirse al SHA activo, no asumir equivalencia con `main`.
- No se encontraron credenciales dedicadas de lectura disponibles para Claude sin elevar privilegios.
- SQL preparado en scratchpad, no ejecutado ni validado.

### Hallazgos de código solamente

- REBOBINADO figura entre los sectores operativos y P1-07 entre los formularios centrales.
- La semilla declara P1-07 v5 para BELOIT, OVER y COPASA; no demuestra que esas versiones estén publicadas o vinculadas en producción.
- P1-07 v3+ genera crías técnicas; v1/v2 no las generan retroactivamente.
- La etiqueta madre se obtiene de `capture_detail.etiqueta_numero_de_bobina`; la identidad interna es el UUID de la captura.
- Las posiciones de cría son 1–11 y 13–22.
- Las crías nacen en `pending`; los estados técnicos son `pending/released/rejected`.
- `released` se describe como “Liberada por Calidad”; equivalencia con “Aceptada” sigue pendiente de Functional.
- El creador original se obtiene mediante `capture.created_by`, que admite nulos.
- No se identificó reserva actual de crías para reportes; el control contra doble asignación se deberá diseñar para RBE-04.
- PV activo, producto definitivo, composición Formato/Corte y cobertura real de campos requieren consultas de datos.

### Sin ejecución de consultas ni cambios

- Consultas SQL: 0.
- Tablas consultadas: 0.
- Registros contabilizados: 0.
- Sin conexión a PostgreSQL, sin escrituras, migraciones, cambios de permisos, reinicios o despliegues.
- El checkout quedó limpio según el informe recibido.

### Observación independiente de red

Se reportó que el contenedor `postgres-vinto` publica `6543` en `0.0.0.0`. No se comprobó firewall ni accesibilidad externa y no se modificó configuración. Requiere una revisión separada; no se debe cerrar ni alterar el puerto sin diagnóstico y autorización.

### Condición para desbloquear RBE-01

No utilizar Docker/superusuario como vía de auditoría. El grupo Docker puede otorgar control privilegiado del host y una transacción `READ ONLY` no convierte una sesión superusuario en una identidad con privilegios de solo lectura.

Un DBA/administrador autorizado deberá provisionar una identidad no superusuario, sin `CREATEDB`, `CREATEROLE`, `REPLICATION`, `BYPASSRLS` ni membresía en roles de escritura, con `USAGE` y `SELECT` solo sobre las tablas/vistas necesarias. Preferir vistas de auditoría con datos personales minimizados. La contraseña debe entregarse al entorno de ejecución por canal seguro, nunca por el chat. Los grants SELECT son la barrera real; `default_transaction_read_only=on` y `SET TRANSACTION READ ONLY` son defensas adicionales.

Una vez verificados los grants, repetir las consultas de RBE-01. Hasta entonces, RBE-02 y el desarrollo funcional permanecen sin iniciar.


## 15. RBE-01 — Auditoría de datos productivos completada (27/11/2026)

**Resultado reportado: `RBE01_READ_ONLY=PASS`.** Se realizaron 54 consultas SELECT: 53 dentro de transacciones `READ ONLY` terminadas con `ROLLBACK`, y una consulta de roles con lectura por defecto. No se reportaron escrituras, cambios de permisos, servicios ni checkout.

### 15.1 Entorno y configuración real

- Backend activo: `35e64d0d75900d04b1fe11cb8902f6d1b3fd69c2`.
- PostgreSQL 17.11; 31 migraciones aplicadas, última `0031`.
- Máquinas activas de REBOBINADO: BELOIT, COPASA, OVER, PERICHUN y TUBETERA.
- P1-07 v1–v5 publicadas en BELOIT, COPASA y OVER.
- Concesiones vigentes: BELOIT 4 (4 usuarios), COPASA 4 (4 usuarios; 1 revocada), OVER 3 (3 usuarios).
- 11 capturas P1-07 en estado `submitted`, del 20/10 al 16/11/2026: v1=1, v2=4, v3=1, v4=4, v5=1.
- Turnos configurados con `America/La_Paz`; ninguna de las 11 capturas fue corregida.

### 15.2 Madres y crías

Se identificaron 6 madres P1-07 v3+ y 25 crías:

| Estado técnico | Cantidad | Peso agregado |
|---|---:|---:|
| `released` | 17 | 2.288,55 kg |
| `pending` | 3 | 75 kg |
| `rejected` | 5 | 275 kg |

En las 5 rechazadas: 4 tienen clasificación `rechazado` y 1 `reutilizable`.

- Las posiciones observadas son 1–6; no hay posición 12, duplicados de posición, huérfanos ni discrepancias de peso entre las crías y su fuente.
- La relación cría → captura → asignación → línea de OT → PV/artículo está completa en 11/11 capturas.
- Todas las OT asociadas a las crías están `closed`.
- La etiqueta madre `25` aparece en tres capturas; dos son P1-07 v3+ con igual máquina, PV, artículo, fecha y peso de madre. El UUID de captura es obligatorio como clave; la etiqueta es solo texto visible.
- La etiqueta de las crías coincide con la etiqueta declarada en su captura.

### 15.3 Campos de salida

Cobertura en las seis capturas v3+:

| Campo | Disponibilidad | Observación |
|---|---:|---|
| Etiqueta de madre | 6/6 | 5 etiquetas distintas |
| Destino | 6/6 | 3 valores |
| `producto_refilado` | 1/6 | No coincide con el artículo de OT |
| Ayudante (`auxiliar`) | 4/6 | 3 valores |
| Tubete | 6/6 | Valores 1, 25, 105 |
| Metraje | 6/6 | 5 valores |
| Tensión | 6/6 | Valores 25, 5, 2.1 |
| `formato_1` | 6/6 | Valores observados entre 1 y 2700 |
| `formato_2` | 1/6 | No se infiere su semántica |
| `formato_3` / “Cortes” | 2/6 | No coincide con la cantidad de crías |
| Diámetro | 6/6 | Coincide con el dato copiado a las crías |
| Peso madre y horas | 6/6 | Hay una inconsistencia horaria y una de pesos |
| Observaciones | 0/6 | Sin datos |
| Crías 1–3 | 6/6 | — |
| Crías 4–5 | 3/6 | — |
| Cría 6 | 1/6 | — |
| Crías 7–22 | 0/6 | — |
| PV y artículo de OT | 6/6 | Relación completa |

El artículo de la OT no coincide con `producto_refilado`; dos supuestas coincidencias por dígitos en la descripción son casuales y no constituyen equivalencia.

### 15.4 Operador creador

- `capture.created_by` resuelve a un usuario activo con nombre en 11/11 capturas.
- Las 11 capturas pertenecen a una sola cuenta con perfil `OPERACION`; el nombre empieza por “Q”. Podría ser una cuenta de QA, pero no está confirmado.
- No hay coincidencia entre creador y ayudante.
- El reporte deberá conservar el creador original de P1-07, no sustituirlo por el usuario que genera el reporte.

### 15.5 Inconsistencias de origen

1. Captura `58f229d4`: hora de inicio 11:50 y fin 11:25 en turno de día.
2. Captura `0845b52e`: suma de pesos de crías 33,55 kg frente a peso declarado de madre 25 kg.
3. Campo “Cortes” = 6 y 0 en dos capturas con tres crías cada una.
4. OT `QA-001` no está marcada como QA ni archivada; no tiene crías.
5. La finalidad de la decisión de Calidad está impuesta por API; no se identificó un trigger equivalente en la base.

Estas inconsistencias no deben corregirse ni reinterpretarse desde el reporte. Se mostrarán los datos de origen conforme a un mapeo aprobado y se conservará trazabilidad.

### 15.6 Reserva y concurrencia

No existe una reserva/asignación actual de crías a reportes de exportación.

RBE-04 deberá implementar:
- Tabla persistente de asignación entre reporte y cría.
- Restricción única parcial por cría mientras el reporte tenga estado vigente.
- Revalidación de estado de Calidad y pertenencia en la transacción de generación.
- Bloqueo en orden estable para evitar carreras.
- Conflicto HTTP 409 sin reserva parcial cuando una cría ya fue asignada o cambió de estado.

### 15.7 Observación sobre la identidad usada en la auditoría

El informe indica uso de la cuenta `vinto_audit_ro` y, para consultas pendientes, `vinto_mvp_root` con cambio a `pg_read_all_data`. Los nombres no coinciden con los roles previstos en el script de aprovisionamiento (`vinto_rbe_audit` y `vinto_rbe_view_owner`). Antes de reutilizar credenciales o conceder acceso permanente, verificar `session_user`, `current_user`, atributos, membresías y grants efectivos. No inferir que las siete vistas previstas se instalaron si el informe no lo acredita.

### 15.8 Decisiones para RBE-02

1. Homologación de `released` con “Aceptada”; excluir `pending` y `rejected`. Confirmar expresamente si `reutilizable` continúa excluida mientras su estado técnico sea `rejected`.
2. Definir elegibilidad de PV: todas las OT con crías están `closed`; decidir si una OT cerrada puede seguir siendo elegible cuando tiene crías `released` y sin asignar. Excluir OTs archivadas y QA mediante criterio verificable, no por suposición.
3. Usar el artículo de la OT como producto principal; decidir si `producto_refilado` se muestra como complemento opcional, ya que no equivale al artículo.
4. Homologar `formato_1`, `formato_2` y `formato_3` con Functional. No llamar “Corte” a `formato_3` ni combinar formatos hasta confirmar su semántica.
5. Definir si el destino libre se copia como snapshot de cada madre o debe ser uniforme dentro de un reporte. La regla de consistencia no puede asumir igualdad sin resolver casos reales.
6. Mantener madre seleccionable por etiqueta + fecha/horas/máquina/PV/artículo; usar siempre UUID como valor interno.
7. Permitir ayudante vacío, sujeto a la especificación, sin inventar un valor.
8. Definir tratamiento de inconsistencias históricas: horas invertidas, peso de crías superior al de madre y valores de “Cortes” que no corresponden a cantidad de crías.
9. Definir criterio de exclusión QA, dado que `QA-001` no tiene flag ni está archivada, aunque no contiene crías.
10. Confirmar permisos para generar, consultar historial y anular.

### 15.9 Próxima fase

RBE-01 queda completado. RBE-02 será exclusivamente diseño técnico y cierre de decisiones funcionales; no implica aún crear tablas, permisos, API ni código. El desarrollo comenzará solo después de aprobar el diseño.
