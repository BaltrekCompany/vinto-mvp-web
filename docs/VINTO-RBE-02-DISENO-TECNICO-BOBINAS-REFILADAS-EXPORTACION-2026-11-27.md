# VINTO — RBE-02
## Diseño técnico detallado: Bobinas Refiladas para Exportación

**Fecha:** 27 de noviembre de 2026  
**Estado:** diseño documentado; siete observaciones de revisión técnica incorporadas el 27/11/2026; pendiente de nueva revisión y aprobación.  
**Tipo de cambio:** solo documentación. No incluye código, migraciones, permisos, escrituras en PostgreSQL ni despliegue.  
**Base de diseño:** especificación funcional de seis páginas, resultado RBE-01 y decisiones D01–D11 aprobadas por el usuario.

---

## 1. Objetivo y alcance

Definir la arquitectura funcional y técnica para implementar el Reporte de Bobinas Refiladas para Exportación reutilizando Producción de Rebobinado, Calidad, usuarios y la identidad técnica de las madres P1-07.

El reporte permite que Operación conforme paquetes físicos de una a cinco crías aceptadas, revise la información automática, introduzca camión, orden y observaciones generales, genere el PDF y consulte posteriormente el historial.

No es un formulario de producción ni de Calidad. No captura nuevamente pesos, parámetros técnicos, identidad de madres o decisiones de Calidad.

### Incluye

- Selección dependiente PV → producto → madre P1-07.
- Selección de crías liberadas por Calidad y disponibles.
- Paquetes de una a cinco crías, con Cría A obligatoria.
- Reutilización de una madre en varias líneas/paquetes.
- Autocompletado de los datos de origen.
- Borradores editables sin reserva definitiva.
- Vista previa, generación de PDF e historial.
- Snapshot inmutable y descarga idéntica del PDF generado.
- Reserva transaccional de crías al generar.
- Estados Borrador, Generado, Observado y Anulado.
- Control de permisos por perfil, sector y máquina.

### Fuera de alcance

- Nuevas capturas P1-07.
- Nuevas decisiones o evaluaciones de Calidad.
- Crear bobinas F3, códigos artificiales o genealogía industrial.
- Modificar datos fuente de Producción o Calidad.
- Recalcular pesos, diámetros, cortes, metraje o tensiones.
- Inventario, balance de masa, mermas o consumo de materiales.
- Cambios a Calidad Offline, PWA, IndexedDB, firmas, cola o sincronización.

---

## 2. Fuentes y evidencia

### 2.1 Especificación funcional

La especificación de seis páginas define:

- Secuencia PV → producto → madre → una a cinco crías → camión/orden/observación → validación y PDF.
- Campos automáticos bloqueados y campos seleccionables mediante listas.
- Una línea equivale a un paquete físico.
- Cría A obligatoria; B–E opcionales.
- La misma madre puede aparecer en varias líneas.
- No crear códigos artificiales.
- Todas las líneas comparten PV, producto, formato, destino y máquina.
- Estados mínimos Borrador, Generado, Observado y Anulado.
- Revalidación transaccional antes de generar.
- PDF A4 vertical, blanco y negro, cuadrícula delgada, veinte líneas disponibles y observaciones al final.
- El PDF histórico debe descargarse de nuevo sin reconstruirse con datos posteriores.

### 2.2 Mockup de Producción Rebobinado

El segundo PDF adjunto es un reporte distinto, con granularidad fecha + máquina + turno + producto y totales de bobinas crías y materia prima. Se conserva como referencia contextual del proceso de Producción, no como formato de salida del reporte de exportación.

El PDF de exportación seguirá la página 6 de su especificación, salvo una decisión funcional posterior.

### 2.3 Resultado RBE-01

RBE-01 terminó PASS según el informe recibido:

- PostgreSQL 17.11 y 31 migraciones aplicadas.
- Cinco máquinas activas en REBOBINADO: BELOIT, COPASA, OVER, PERICHUN y TUBETERA.
- P1-07 v1–v5 publicadas en BELOIT, COPASA y OVER.
- Once capturas submitted; seis madres P1-07 v3+ y 25 crías.
- 17 released, 3 pending y 5 rejected.
- 11/11 relaciones de captura a OT/PV/artículo completas.
- Todas las OT con crías están closed.
- Etiqueta madre 25 repetida; UUID de captura imprescindible.
- No existe reserva de crías para reportes.
- Se reportaron 54 SELECT, 53 en transacciones READ ONLY con ROLLBACK.

La auditoría encontró que el campo de producto refilado no coincide con el artículo de OT, Formato/Corte no tiene una homologación demostrada, hay inconsistencias de origen y la clasificación QA no está completa para todos los registros.

---

## 3. Decisiones D01–D11 aprobadas

Las siguientes decisiones fueron aprobadas por el usuario el 27/11/2026 y se consideran la base del diseño:

| Decisión | Regla aprobada | Traducción técnica |
|---|---|---|
| D01 | Solo released; pending y rejected, incluido reutilizable, excluidos | Elegibilidad exige quality_release.status = released y peso válido |
| D02 | OT closed permitida si no está archivada ni es QA y tiene crías released sin asignar | No exigir OT abierta; excluir archived_at y qa_retired; exigir al menos una cría elegible |
| D03 | Artículo de OT como producto principal; producto_refilado complemento opcional | La identidad de producto deriva de article/article_version; producto_refilado no es clave |
| D04 | No homologar formato_1/2/3 ni Corte hasta confirmación de Functional | Conservar valores crudos en snapshot; no concatenar ni asignar significado |
| D05 | Un destino por reporte; destinos distintos requieren reportes separados | Comparar el destino de cada madre; preservar el texto fuente |
| D06 | Madre visible por etiqueta, fecha/horas, máquina, PV y artículo; UUID interno | Todas las relaciones usan rewind_mother_capture_id/capture UUID |
| D07 | Operador desde capture.created_by; ayudante opcional | No sustituir creador original; auxiliar puede ser NULL |
| D08 | Veinte paquetes por página, con paginación | Veinte filas por página PDF; sin límite global de paquetes |
| D09 | Advertir inconsistencias sin modificar origen; Functional decide cuáles bloquean | Warnings en vista previa; no autocorregir ni ocultar valores |
| D10 | Borrador sin reserva; generación transaccional; anulación libera crías con motivo y autorización | Reserva solo al generar; anulación conserva historial y libera reservas |
| D11 | Operación genera y consulta propios; Supervisión consulta historial; Jefatura gestiona anulaciones | Permisos dedicados y scope REBOBINADO |

D04 es una decisión aprobada de no interpretar todavía los campos. No significa que la semántica de Formato/Corte ya esté resuelta.

---

## 4. Modelo de dominio y fuentes de verdad

### 4.1 Identidad de la madre

La madre del reporte es exclusivamente la madre declarada en P1-07 v3+:

- Identidad interna: UUID de la captura P1-07.
- Texto visible: capture_detail.etiqueta_numero_de_bobina.
- Fila técnica asociada: bobbin.rewind_mother_capture_id.
- No es una bobina F3 numerada.
- No usa sequence_number ni gestión industrial.
- No se crea una nueva bobbin ni relación F3.

La etiqueta puede repetirse. Está prohibido usarla como clave primaria, clave de agrupación o relación exclusiva.

### 4.2 Identidad de las crías

Cada cría se identifica por bobbin.id. La posición visible se deriva de bobbin.rewind_child_position y el peso de bobbin.weight_kg.

- La madre se resuelve por source_capture_id = mother_capture_id.
- La etiqueta de la cría debe corresponder a rewind_mother_label de su captura.
- Posiciones admitidas por el esquema: 1–11 y 13–22.
- No existe posición 12.
- El selector muestra “Cría N - peso kg”.
- El peso se lee del registro de la cría; nunca se digita.
- No se crean códigos artificiales de paquete ni de cría.

### 4.3 Relación de Producción

La consulta parte de la captura P1-07 y conserva la relación:

capture → assignment → work_order_line → work_order_version → work_order

Campos derivados:

- PV: work_order_line.pv_reference.
- Producto: article/article_version asociado a work_order_line.article_version_id.
- Máquina: capture.machine_id → machine.
- Fecha/hora de producción: capture.captured_at, capture.operating_date y valores P1-07 de hora_inicio/hora_fin.
- Madre: capture UUID + etiqueta declarada.
- Creador original: capture.created_by → vinto_master.user.display_name.

No se sustituye el creador original por el usuario que genera el reporte.

### 4.4 Campos P1-07

El servicio debe leer las definiciones de la versión exacta de formulario de cada captura y los valores tipados de capture_detail. No debe asumir que todas las versiones tienen el mismo conjunto de campos.

| Campo de salida | Fuente de autoridad | Tratamiento |
|---|---|---|
| Etiqueta madre | capture_detail.etiqueta_numero_de_bobina | Texto visible; UUID es la clave |
| Cría N | bobbin.rewind_child_position | Número real de posición |
| Peso cría | bobbin.weight_kg | Decimal exacto, solo lectura |
| PV | work_order_line.pv_reference | Snapshot de origen |
| Producto | Article y article_version de la OT | Producto principal |
| Producto refilado | capture_detail.producto_refilado | Complemento opcional, nunca clave |
| Máquina | capture.machine_id | Nombre/código del maestro |
| Destino | capture_detail.destino | Texto de origen |
| Diámetro | bobbin.diameter_mm y campo P1-07 diametro | Conservar fuente y verificar consistencia |
| Tubete | capture_detail.tubete | Texto de origen |
| Ayudante | capture_detail.auxiliar | Opcional; NULL permitido |
| Operador | capture.created_by → user.display_name | Creador original |
| Camión | Entrada del operario | Obligatorio al generar |
| N.° orden | Entrada del operario | Obligatorio al generar |
| Observaciones | Entrada del operario | Una sola observación general |
| Fecha del reporte | Reloj del servidor | Instante de generación, mostrado en America/La_Paz |

Los decimales se transportan y serializan sin convertir a float. Los valores originales se conservan en el snapshot.

---

## 5. Elegibilidad de PV, producto, madres y crías

### 5.1 PV elegible

Un PV aparece solo si tiene al menos una madre P1-07 v3+ con una cría que cumpla todas las condiciones:

1. Captura P1-07 de sector REBOBINADO.
2. Captura submitted o closed.
3. OT en estado published, in_progress o closed.
4. OT no archivada: archived_at IS NULL.
5. OT no retirada como QA: qa_retired IS FALSE.
6. Máquina activa y sector activo.
7. Existe al menos una cría con peso válido, Quality released y sin reserva activa.
8. La sesión del usuario tiene permiso y alcance para la máquina.

La OT closed se permite expresamente. La OT draft no se ofrece: no representa una OT publicada para producción.

**Límite de la auditoría:** QA-001 no estaba marcado como QA ni archivado, aunque no tenía crías. No se debe inferir QA por prefijo, nombre del usuario o similitud de datos. Antes de producción funcional debe existir un criterio verificable para que todas las OTs de prueba estén marcadas mediante qa_retired u otro mecanismo formal aprobado. Una OT de QA no marcada no puede incluirse por defecto.

### 5.2 Producto dependiente

- La lista de productos depende del PV seleccionado.
- La identidad de producto es el artículo de la línea de OT.
- producto_refilado no reemplaza el artículo.
- Se preserva article_version_id exacto por paquete para trazabilidad histórica.
- Si el mismo article_id aparece con versiones cuya descripción difiere, el backend conserva cada descripción de origen. La composición de una única etiqueta de producto en cabecera requiere resolver esa diferencia antes de generar.

### 5.3 Madres elegibles

La lista de madres se filtra por PV + producto y devuelve únicamente madres con al menos una cría elegible.

Cada opción muestra:
- Etiqueta declarada.
- Máquina.
- PV.
- Código/descrición del artículo.
- Fecha operativa.
- Hora inicio y fin.

El valor enviado por el frontend es mother_capture_id. Nunca se resuelve por etiqueta.

Una madre puede repetirse en varias líneas/paquetes del mismo reporte.

### 5.4 Crías elegibles

Una cría aparece si:

- Pertenece a la captura madre seleccionada.
- Tiene posición real válida.
- Tiene peso mayor que cero.
- quality_release.status = released.
- No tiene una reserva activa en otro reporte.
- La OT/máquina/madre sigue dentro del alcance autorizado.

Se excluyen pending, rejected, rejected + reutilizable y registros sin decisión de Calidad.

El estado de Calidad se vuelve a leer al generar; la lista del frontend no es una autorización.

---

## 6. Reglas de consistencia del reporte

Cada reporte contiene un único contexto:

- PV.
- Producto/artículo.
- Máquina.
- Destino.
- Formato, una vez que Functional homologue sus fuentes.

Cada paquete:
- Corresponde a una sola madre.
- Tiene entre una y cinco crías.
- Cría A es obligatoria.
- Crías B–E son opcionales.
- Cada cría pertenece a la madre del paquete.
- Una cría no puede repetirse en otro paquete del mismo reporte.
- La misma madre sí puede aparecer en más de un paquete.

### Destino

D05 exige un destino por reporte. El backend compara el valor de origen de cada madre. Para la comparación se propone eliminar espacios al inicio/final, sin cambiar el valor almacenado. Diferencias de texto después de ese ajuste requieren reportes separados. No convertir automáticamente mayúsculas, tildes o sinónimos.

### Formato

D04 mantiene bloqueada la homologación. Se conservan formato_1, formato_2 y formato_3 en el snapshot como valores crudos. No se concatenan ni se llaman Formato/Corte hasta recibir la definición de Functional.

La especificación exige Formato en el encabezado y Corte en el detalle. Por tanto, la generación del PDF definitivo no debe declararse cerrada hasta que Functional confirme esos dos mapeos.

---

## 7. Arquitectura propuesta

### 7.1 Backend como autoridad

El frontend nunca decide:
- PV real de una captura.
- Producto/OT.
- Máquina.
- Madre.
- Posición o peso de cría.
- Estado de Calidad.
- Disponibilidad/reserva.
- Operador original.

El frontend envía UUIDs de selección y los campos manuales camión, orden y observaciones. El backend vuelve a resolver todo desde PostgreSQL.

### 7.2 Componentes

1. Router FastAPI específico de RBE.
2. Schemas Pydantic de lectura, borrador, paquete, vista previa, generación e historial.
3. Servicio de consulta de elegibilidad.
4. Servicio de borradores.
5. Servicio de generación transaccional.
6. Servicio de historial/descarga/anulación.
7. Renderizador PDF de backend.
8. Migración aditiva con tablas, índices, FKs, triggers y grants mínimos.
9. Pruebas de servicio, API, permisos, concurrencia, snapshot y PDF.

El módulo de Tubetes permanece separado: no comparte lógica de reserva ni persistencia.

### 7.3 Endpoints propuestos

Todos bajo /api/reports/rewinding-export. Las mutaciones usan POST/PATCH para respetar los métodos CORS actuales de la aplicación.

| Método | Ruta | Función |
|---|---|---|
| GET | /pvs | PV con al menos una cría elegible |
| GET | /products?pv_reference= | Productos del PV |
| GET | /mothers?pv_reference=&article_id= | Madres elegibles |
| GET | /mothers/{mother_capture_id}/children | Crías released y disponibles |
| POST | /drafts | Crear borrador |
| GET | /drafts/{report_id} | Leer borrador propio |
| PATCH | /drafts/{report_id} | Editar camión, orden y observaciones |
| POST | /drafts/{report_id}/packages | Agregar paquete |
| PATCH | /drafts/{report_id}/packages/{package_id} | Editar paquete |
| POST | /drafts/{report_id}/packages/{package_id}/remove | Eliminar paquete no confirmado |
| POST | /drafts/{report_id}/preview | Revalidar y devolver vista previa/warnings |
| POST | /drafts/{report_id}/generate | Generar PDF, snapshot y reservas |
| GET | /history | Historial paginado según permisos |
| GET | /reports/{report_id} | Detalle y estado |
| GET | /reports/{report_id}/pdf | Descargar los bytes originales |
| POST | /reports/{report_id}/annul | Anular con motivo y autorización |
| POST | /drafts/{report_id}/discard | Descartar borrador propio sin reservar crías |

Las rutas son un contrato de diseño, no código ya implementado. Los nombres finales se fijarán en RBE-04.

### 7.4 Respuestas y errores

- 401: sesión no válida.
- 403: permiso insuficiente.
- 404: recurso inexistente o fuera del alcance; no revelar UUIDs ajenos.
- 409: cría reservada, estado de Calidad cambiado, borrador ya generado, conflicto de concurrencia o idempotencia incompatible.
- 422: campos obligatorios vacíos, paquete inválido, cría repetida, madre/cría no relacionada o contexto inconsistente.
- 413: PDF supera el límite técnico de bytes.
- 503: base o servicio no disponible o integridad del PDF no verificable.

Los errores públicos no deben incluir SQL, valores fuente sensibles ni razones internas del motor de autorización.

---

## 8. Persistencia propuesta

Se propone usar tablas nuevas en vinto_txn, sin alterar las tablas de Producción, P1-07 ni Calidad.

### 8.1 Cabecera: rewinding_export_report

Campos conceptuales:

- id UUID como identidad técnica del reporte; no crear código industrial.
- status: draft, generated, observed, annulled, discarded.
- pv_reference.
- article_id y snapshot de código del producto.
- machine_id y sector_id (REBOBINADO).
- destination_snapshot.
- truck_number.
- order_number.
- observations.
- created_by / created_at.
- generated_by / generated_at.
- annulled_by / annulled_at / annulment_reason.
- discarded_by / discarded_at / discard_reason.
- snapshot_version.
- report_snapshot JSONB, inmutable después de generar.
- draft_creation_idempotency_key, si se implementa idempotencia de creación de borrador.
- generation_idempotency_key y generation_request_sha256, persistidos al generar.

Restricciones y garantías:

- FKs explícitas: article_id → vinto_master.article(id); machine_id → vinto_master.machine(id); sector_id → vinto_master.sector(id); created_by, generated_by, annulled_by y discarded_by → vinto_master.user(id), todas con ON DELETE RESTRICT. Los actores opcionales admiten NULL antes de su transición.
- El reporte debe conservar el sector de origen, no inferirlo desde una máquina modificable posteriormente.
- UNIQUE parcial por (generated_by, generation_idempotency_key) cuando la clave no sea NULL. Esta clave está dedicada a la operación rewinding_export.generate; no se comparte con creación/edición de borradores.
- generation_request_sha256 debe ser SHA-256 hexadecimal minúsculo de 64 caracteres.
- Una cabecera descartada es terminal, no se borra y nunca tiene reservas ni PDF generado.
- El snapshot se congela al pasar a generated. Las transiciones posteriores solo pueden cambiar estado, actor/fecha/motivo y metadatos de observación/anulación; nunca el contenido de negocio ni el snapshot.

Los campos manuales camión y orden pueden estar vacíos en un borrador, pero son obligatorios al generar.

### 8.2 Paquetes: rewinding_export_package

Una fila por paquete físico:

- id UUID.
- report_id.
- package_number, secuencial dentro del reporte.
- mother_capture_id: UUID de captura P1-07.
- mother_bobbin_id: referencia opcional a la fila técnica de madre, si existe.
- mother_label_snapshot.
- source_capture_revision y source_form_version_id.
- work_order_id y work_order_line_id de la relación de origen.
- article_version_id exacto de la OT.
- source_fields_snapshot JSONB con valores P1-07 relevantes.
- source_operator_user_id y operator_display_name_snapshot.
- removed_at / removed_by para retirada lógica en Borrador.

Restricciones y garantías:

- UNIQUE(id, report_id), clave referenciada por la FK compuesta de package_child.
- UNIQUE parcial (report_id, package_number) WHERE removed_at IS NULL.
- FKs ON DELETE RESTRICT: report_id → rewinding_export_report; mother_capture_id → vinto_txn.capture; mother_bobbin_id → vinto_txn.bobbin (nullable); source_form_version_id → vinto_config.form_version; work_order_id → vinto_txn.work_order; work_order_line_id → vinto_txn.work_order_line; article_version_id → vinto_master.article_version; source_operator_user_id → vinto_master.user (nullable si capture.created_by es NULL); removed_by → vinto_master.user.
- Una misma mother_capture_id puede repetirse en diferentes paquetes.
- No se elimina físicamente un paquete. Retirarlo en Borrador fija removed_at/removed_by y conserva sus datos; el evento package_removed se inserta en la misma transacción.
- Solo se permite INSERT/UPDATE mientras el reporte esté en draft. Al pasar a generated, observed o annulled, todos los campos del paquete quedan inmutables.
- No se permite cambiar id, report_id ni mother_capture_id de una fila existente; para sustituir una madre se retira el paquete y se crea uno nuevo.

La retirada lógica permite conservar la trazabilidad de las ediciones del borrador sin mantener paquetes inactivos en la vista previa ni en el PDF.

### 8.3 Crías por paquete: rewinding_export_package_child

Una fila por selección de cría dentro de un paquete:

- id UUID.
- report_id.
- package_id.
- child_bobbin_id.
- package_slot A–E.
- source_position.
- weight_kg_snapshot.
- removed_at / removed_by para retirar una selección durante Borrador.

Restricciones:

- UNIQUE(id, child_bobbin_id): clave referenciada por la tabla de reservas.
- UNIQUE parcial (package_id, package_slot) WHERE removed_at IS NULL.
- UNIQUE parcial (report_id, child_bobbin_id) WHERE removed_at IS NULL: una cría activa no se repite en dos paquetes del mismo reporte.
- FOREIGN KEY (package_id, report_id) REFERENCES rewinding_export_package(id, report_id) ON DELETE RESTRICT: integridad compuesta paquete–reporte.
- FOREIGN KEY (child_bobbin_id) REFERENCES vinto_txn.bobbin(id) ON DELETE RESTRICT.
- removed_by REFERENCES vinto_master.user(id) ON DELETE RESTRICT.
- Slot limitado a A–E; el servicio y una validación diferida comprueban que exista Cría A entre las selecciones activas antes de generar.

No se permite DELETE físico. Una selección se puede retirar lógicamente solo mientras el reporte esté en draft; la fila retirada queda inmutable. Si la misma cría se vuelve a seleccionar en ese borrador, se crea una fila nueva y la unicidad parcial permite el nuevo vínculo activo. Al retirar un paquete, todas sus selecciones activas se retiran en la misma transacción.

Desde generated, todas las relaciones paquete–cría quedan congeladas. El PDF, snapshot, detalle y reserva se refieren a las selecciones activas exactas que existían al generar.

### 8.3.1 Reservas: rewinding_export_reservation

La reserva se modela en una tabla independiente para que exista una sola fuente de verdad y no dependa de mantener sincronizado el estado de la cabecera.

Campos:

- id UUID.
- package_child_id.
- child_bobbin_id.
- reserved_at / reserved_by.
- released_at / released_by / release_reason.

Restricciones y garantías:

- UNIQUE(package_child_id): una fila histórica de reserva por relación paquete–cría.
- FK compuesta (package_child_id, child_bobbin_id) hacia rewinding_export_package_child(id, child_bobbin_id), ON DELETE RESTRICT.
- Índice UNIQUE parcial global sobre child_bobbin_id WHERE released_at IS NULL: una cría no puede tener dos reservas activas, aunque los reportes sean distintos.
- CHECK ((released_at IS NULL) = (released_by IS NULL)).
- Si existe released_at, released_by y release_reason son obligatorios; el motivo no puede estar vacío.
- reserved_by y released_by referencian vinto_master.user(id) con ON DELETE RESTRICT.
- Una reserva se inserta únicamente dentro de la transacción que genera el reporte y solo puede referenciar una selección activa.
- La liberación se realiza una sola vez, en la misma transacción que anula el reporte; no se borra la fila.
- Un trigger impide DELETE/TRUNCATE, cambios de package_child_id, child_bobbin_id, reserved_at o reserved_by, y una segunda modificación de los campos de liberación.
- Un trigger de restricción diferible verifica al COMMIT la correspondencia entre estado y reservas: Borrador/Descartado = cero reservas; Generado/Observado = una reserva activa por cada selección activa congelada; Anulado = cero reservas activas.

La reserva activa se determina exclusivamente por la existencia de una fila con released_at IS NULL. El índice único parcial es la última barrera ante dos generaciones concurrentes.

### 8.4 PDF inmutable: rewinding_export_pdf

Una fila por reporte generado:

- report_id como PK y FK al reporte.
- file_name.
- mime_type application/pdf.
- pdf_bytes BYTEA.
- sha256 en hexadecimal minúsculo (64 caracteres).
- size_bytes.
- page_count.
- generated_at.

Integridad y límites:

- CHECK (size_bytes = octet_length(pdf_bytes)).
- CHECK (sha256 ~ '^[0-9a-f]{64}$').
- El backend calcula SHA-256 sobre los bytes exactos que almacena; antes de entregar una descarga vuelve a calcularlo y compara el resultado con el valor persistido. Una discrepancia impide entregar el archivo y se registra como incidente de integridad.
- No se fija un máximo de páginas ni de paquetes: D08 significa veinte paquetes por página con paginación, sin límite funcional global. Se mantiene un límite técnico inicial de 25 MiB por PDF para proteger memoria y almacenamiento BYTEA. Si se alcanza, la generación falla explícitamente (413), sin truncar el PDF ni dejar cabecera, reservas o eventos parciales. RBE-05 debe medir el tamaño real con fixtures de carga y revisar este umbral antes de cerrar QA; no puede introducir un límite de 100 páginas ni traducir el umbral a un máximo funcional de paquetes.
- La tabla recibe REVOKE ALL FROM PUBLIC y, si existe vinto_app, únicamente GRANT SELECT, INSERT. No recibe UPDATE ni DELETE; un trigger rechaza UPDATE/DELETE/TRUNCATE incluso ante una concesión accidental. El PDF no se reemplaza ni se sobrescribe.
- El snapshot de rewinding_export_report se congela al pasar a Generado mediante trigger. El PDF y el snapshot se insertan en la misma transacción que la generación y las reservas.

Se recomienda guardar el PDF binario en PostgreSQL junto con el snapshot. No se encontró un servicio de almacenamiento de documentos existente en el backend; BYTEA evita depender de una ruta local o almacenamiento externo y permite incluir el documento en el backup de la base.

El PDF se genera en backend desde el snapshot validado. El endpoint de descarga devuelve exactamente los bytes guardados; no reconstruye el PDF con datos productivos actuales.

El backend actual no incluye una biblioteca PDF en requirements.txt. RBE-05 deberá seleccionar y fijar una dependencia de renderizado (por ejemplo ReportLab) tras validar compatibilidad, fuentes, límites y salida A4. No se agrega ahora.

### 8.5 Eventos: rewinding_export_event

Registro inmutable de eventos:

- report_id.
- event_type.
- previous_status / new_status.
- actor_id.
- occurred_at.
- reason.
- request_id.
- metadata JSONB minimizada.

Eventos mínimos:
- draft_created.
- draft_updated.
- package_added / package_updated / package_removed.
- report_generated.
- report_observed.
- report_annulled.
- draft_discarded.

Los eventos no reemplazan el trigger de auditoría genérico del proyecto; agregan una cronología funcional legible. actor_id referencia vinto_master.user(id) ON DELETE RESTRICT (nullable solo para eventos de sistema expresamente definidos). La tabla será append-only: vinto_app tendrá INSERT/SELECT, sin UPDATE/DELETE/TRUNCATE, con trigger de inmutabilidad.

### 8.6 Índices y reglas de integridad

- Historial por created_by + created_at.
- Historial por machine_id + generated_at.
- Paquetes activos por report_id + package_number.
- Paquetes por mother_capture_id.
- Crías activas por report_id.
- Clave única compuesta (id, report_id) en paquete y FK compuesta (package_id, report_id) desde package_child.
- Índice único parcial de reservas activas por child_bobbin_id en rewinding_export_reservation.
- Índice único por package_child_id en la tabla de reservas.
- Índices parciales de package_slot y child_bobbin_id solo para filas activas (removed_at IS NULL).
- Índice único parcial de idempotencia por (generated_by, generation_idempotency_key) cuando la clave no sea NULL.
- FKs ON DELETE RESTRICT explícitas para cabecera, madre, crías, versión de formulario, OT, línea, artículo/versión, máquina, sector, operador creador, actores, eventos, reservas y PDF.
- Prohibir DELETE/TRUNCATE de reportes, paquetes, crías, reservas, PDFs y eventos.
- Triggers de retirada lógica en Borrador y de inmutabilidad de paquetes/crías desde Generado.
- Snapshot y bytes PDF inmutables después de generar.
- Restricciones diferibles para comprobar que el estado final del reporte y el conjunto de reservas coincidan al COMMIT.

La migración será aditiva. En el main revisado el último archivo es 0031; el siguiente número se confirmará al sincronizar la rama de implementación, no se fija ahora.

## 9. Transacción de generación, orden de bloqueos e idempotencia

La operación Generate confirma cabecera, paquetes, relación paquete–cría, snapshot, PDF, reservas y eventos en una sola transacción. No puede existir un reporte generado sin PDF íntegro ni reservas completas.

### 9.1 Orden global y obligatorio de bloqueos

Antes de abrir la transacción se pueden leer IDs sin bloquear para conocer OTs, crías, madres y máquina involucradas. Esa lectura es preliminar y no autoriza ni reserva nada. La operación definitiva usa PostgreSQL READ COMMITTED y respeta este orden:

1. Para generación, ejecutar la autorización efectiva de Operation.REWINDING_EXPORT_CREATE con require(..., lock=True) dentro de la misma transacción. El motor toma primero sus bloqueos propios: usuario → perfiles activos → máquina y sector → concesión exacta máquina/formulario.
2. Bloquear las filas work_order involucradas, ordenadas por UUID, con FOR SHARE. La retirada QA usa FOR UPDATE sobre las mismas filas; ambas operaciones se serializan.
3. Bloquear filas quality_release de todas las crías, ordenadas por bobbin_id.
4. Bloquear filas bobbin de las crías, ordenadas por UUID.
5. Bloquear capturas fuente P1-07 de madres, ordenadas por UUID.
6. Bloquear la fila del reporte con FOR UPDATE.
7. Bloquear paquetes activos/retirados, ordenados por package_number, id.
8. Bloquear relaciones paquete–cría, ordenadas por child_bobbin_id, id.
9. Bloquear reservas existentes, ordenadas por child_bobbin_id, id.
10. Después de cada espera, releer bajo READ COMMITTED el estado de OT/QA, Calidad, relaciones, pertenencia, permisos aplicables, estado del reporte y reservas. La lectura preliminar nunca sustituye esta revalidación.

Ninguna ruta puede invertir el orden: está prohibido bloquear primero el reporte y después work_order o quality_release. Los flujos de Calidad que en el futuro cambien una decisión ya liberada y marquen reportes Observados deben respetar el mismo orden work_order → quality_release → bobbin → capture → report → package/child/reservation. La edición de Borradores puede bloquear report/package, pero después no puede adquirir bloqueos de OT, Calidad, bobbin o captura fuente.

### 9.2 Generación

1. Autenticar usuario y comprobar rewinding_export.create, propietario del borrador y sector.
2. Validar la clave idempotente y calcular SHA-256 de la solicitud canónica normalizada.
3. Iniciar transacción READ COMMITTED y tomar un advisory lock transaccional por (actor_id, generation_idempotency_key).
4. Antes de comprobar que el reporte esté en Borrador, buscar una generación existente por actor + clave:
   - Misma clave y mismo hash: devolver el mismo report_id, estado actual y PDF original, incluso si el reporte pasó posteriormente a Observado o Anulado.
   - Misma clave y hash distinto: 409.
   - Sin resultado previo: continuar.
5. Preleer IDs de OTs, paquetes, crías, madres y máquina sin bloquear; validar estructura básica.
6. Aplicar el orden global de bloqueos anterior y revalidar que el reporte sigue en Borrador, pertenece al creador y conserva la selección enviada.
7. Comprobar que las OTs siguen elegibles, no están archivadas ni marcadas como QA y que su clasificación de datos no es desconocida; todas las crías deben seguir released, tener peso/posición válidos, pertenecer a sus madres y no tener reserva activa.
8. Verificar PV, artículo, destino, máquina, formulario P1-07 y alcance autorizado.
9. Validar V01–V08 y reglas D01–D09.
10. Construir snapshot inmutable con valores exactos de origen, entradas manuales, usuario generador, fecha/hora y warnings.
11. Renderizar el PDF desde ese snapshot en memoria; comprobar páginas, tamaño y SHA-256.
12. Cambiar el reporte a Generado, persistiendo snapshot, versión, actor, fecha, generation_idempotency_key y generation_request_sha256.
13. Insertar la fila PDF y una fila de reserva por cada selección activa paquete–cría.
14. Insertar evento report_generated y COMMIT. Las restricciones diferibles verifican que PDF y reservas estén completos y coherentes con el estado.

Si cualquier paso falla, toda la transacción hace ROLLBACK: no queda PDF parcial, cabecera generada, evento de éxito ni reserva parcial.

### 9.3 Anulación, corrección de Calidad y retirada QA

**Anulación:** antes de cambiar el estado, revalidar en la misma transacción el usuario activo, perfil JEFATURA, permiso rewinding_export.annul y concesión REBOBINADO. La revalidación toma FOR SHARE sobre la fila user, después bloquea las filas user_profile/profile activas y consulta user_sector. El bloqueo de user es obligatorio: revoke_sector toma FOR NO KEY UPDATE sobre esa misma fila antes de eliminar la concesión; por tanto, una revocación concurrente espera a la anulación o, si ya confirmó, la anulación relee el alcance y se deniega. No se exige grant máquina/formulario a Jefatura. Después se bloquean OTs → quality_release → bobbin → capture → report → package/child/reservation, se revalida estado y se anula/libera todo atómicamente.

**Corrección de Calidad:** el flujo normal actual solo permite pending → released/rejected. Una corrección posterior a released no se implementa en RBE ni se hace mediante UPDATE directo. Si Functional/Calidad aprueba en el futuro un proceso de corrección, deberá ser append-only, conservar la decisión previa, registrar actor/motivo y emitir un evento; en una sola transacción bloqueará OT → quality_release → bobbin → capture → report y marcará Observados los reportes afectados, manteniendo sus reservas y PDF. La autorización y los actores de ese futuro proceso son una decisión de Calidad separada, no se presuponen en RBE.

**Retirada QA:** la generación bloquea las filas work_order con FOR SHARE; el proceso de retirada QA las bloquea con FOR UPDATE. Si la retirada confirma primero, la generación espera y luego detecta archived_at/qa_retired y se deniega. Si la generación confirma primero, la retirada relee el historial RBE y no puede marcar la OT como QA mientras existan reportes Generados u Observados; Jefatura deberá anularlos primero. Añadir prueba generate-vs-qa-retirement con dos conexiones.

### 9.4 Idempotencia persistente de generación

La cabecera conserva:

- generation_idempotency_key: clave opaca/UUID aportada por el cliente para la operación de generación.
- generation_request_sha256: SHA-256 de la solicitud canónica normalizada.

La huella incluye como mínimo report_id, orden de paquetes activos, madres, UUIDs de crías y posiciones A–E, camión, orden, observaciones y versión del snapshot. No incluye fecha/hora de servidor ni bytes PDF, que se generan una sola vez.

Se aplica unicidad por (generated_by, generation_idempotency_key):

- Misma clave y misma huella: devolver el mismo report_id, estado actual y los mismos bytes PDF almacenados; no generar ni reservar otra vez.
- Misma clave con huella distinta: responder 409.
- La búsqueda idempotente se ejecuta antes de rechazar por estado distinto de Borrador. Si el reporte ya está Observado o Anulado, el reintento idéntico devuelve el documento original y su estado actual; no reactiva ni modifica el reporte.
- Colisión concurrente de índice único (23505): hacer ROLLBACK de la transacción perdedora, consultar el resultado confirmado en una transacción nueva y comparar la huella. Si coincide, devolver el resultado existente; si no, responder 409. Nunca repetir generación ni reservas.
- Si el PDF asociado no existe o su SHA-256 no coincide, responder 503 y registrar incidente de integridad; nunca regenerarlo silenciosamente.

La idempotencia de creación de borrador, si se mantiene, tendrá un campo separado (draft_creation_idempotency_key) y no sustituirá la clave de generación.

## 10. Estados, transiciones y coherencia de reservas

| Estado | Entrada | Edición | Reservas activas | PDF |
|---|---|---|---|---|
| Borrador | Crear reporte parametrizable | Sí, por creador | Ninguna | No definitivo |
| Generado | Confirmación transaccional | No | Una por cada selección activa | Inmutable |
| Observado | Corrección autorizada de Calidad o inconsistencia posterior | No | Se mantienen todas | Se conserva |
| Anulado | Jefatura anula con motivo | No | Ninguna; reservas históricas liberadas | Se conserva |
| Descartado | Creador descarta un borrador | No | Ninguna | No existe |

### Transiciones permitidas y guardas de base de datos

- Borrador → Generado: solo en la transacción de generación; exige snapshot, clave/huella idempotente, PDF íntegro y una reserva activa por cada selección activa al COMMIT.
- Borrador → Descartado: solo por su creador, sin reservas ni PDF; fija discarded_at/by/reason, inserta evento draft_discarded y conserva cabecera, paquetes y selecciones como historial.
- Generado → Observado: solo por el proceso autorizado de observación; conserva snapshot, PDF y todas las reservas activas.
- Generado → Anulado: Jefatura, motivo obligatorio; libera todas las reservas en la misma transacción.
- Observado → Anulado: Jefatura, motivo obligatorio; libera todas las reservas en la misma transacción.
- Anulado y Descartado: terminales; no se reactivan ni se modifican.

Un trigger de cabecera valida las transiciones y congela los campos de negocio, report_snapshot, snapshot_version, generated_by y generated_at desde Generado. Otro trigger impide insertar o modificar paquetes/crías cuando el reporte no está en Borrador. Las filas de paquete/cría retiradas lógicamente son inmutables; no existe DELETE físico. La liberación de reservas solo se permite cuando el reporte está pasando a Anulado y el actor/motivo coinciden con la anulación. Las reservas y eventos no se borran.

Una restricción diferible comprobada al COMMIT impone las invariantes cruzadas:

- Borrador/Descartado: cero reservas.
- Generado/Observado: exactamente una reserva activa por cada selección activa congelada y un PDF asociado.
- Anulado: cero reservas activas; cada reserva anterior conserva fecha, actor y motivo de liberación; el PDF permanece asociado.

La generación actualiza estado, snapshot, PDF, reservas y evento en una sola transacción; la anulación actualiza estado, reservas y evento en una sola transacción. Un fallo de cualquier guarda revierte todo.

### Retirada de paquetes y selecciones

En Borrador, eliminar un paquete significa retirada lógica: package.removed_at/by y las selecciones activas del paquete reciben removed_at/by en la misma transacción; se registra package_removed. Editar un paquete que sustituye una cría retira lógicamente la selección anterior y crea una fila nueva. Las restricciones únicas parciales consideran solo filas activas, por lo que una cría retirada puede seleccionarse de nuevo en el mismo borrador. Después de Generado no se puede agregar, retirar ni modificar ningún paquete o cría.

### Observado y Calidad

La especificación indica que si una cría pasa a Rechazada el reporte queda Observado y la cría no puede reutilizarse. El flujo normal actual solo permite pending → released/rejected y rechaza una segunda decisión. RBE no modificará la decisión ni creará una ruta de corrección de Calidad. Si se aprueba un flujo de corrección separado, este deberá emitir un evento append-only y marcar los reportes afectados como Observados en la misma transacción; hasta entonces no existe una corrección posterior a released dentro del producto.

## 11. PDF y vista previa

### 11.1 Contenido del PDF

Encabezado:
- Título “Reporte de Bobinas Refiladas para Exportación”.
- Máquina.
- N.° camión.
- N.° orden.
- Producto principal del artículo OT.
- Fecha de generación.
- Formato (pendiente D04).
- PV.
- Destino.

Detalle por paquete:
- N.° de paquete.
- Bobina madre declarada.
- Crías A–E con número real y peso.
- Diámetro.
- Corte (pendiente D04).
- Tubete.
- Ayudante (puede estar vacío).
- Operador original.

Cierre:
- Una sola sección de observaciones generales.
- Sin observación por paquete.

### 11.2 Diseño visual

- A4 vertical.
- Blanco y negro.
- Cuadrícula delgada.
- Cabecera compacta.
- Veinte paquetes por página.
- Sin tarjetas, colores ni gráficos.
- Observaciones al final del documento.

Propuesta técnica para varias páginas:
- Repetir una cabecera resumida y el encabezado de tabla en cada página.
- Numeración global “Página N de M”.
- Imprimir observaciones generales una sola vez, al final.
- No partir visualmente un paquete entre páginas.

La repetición de cabecera y la numeración global son decisiones de maquetación propuestas para hacer utilizable la paginación; se validarán contra el formato físico en RBE-05.

### 11.3 Vista previa

La vista previa muestra los mismos datos que alimentarán el snapshot:

- Contexto de reporte.
- Paquetes y crías.
- Datos automáticos de cada madre.
- Campos manuales.
- Warnings de origen.
- Errores bloqueantes.

No es una captura nueva. No modifica Producción ni Calidad.

---

## 12. Permisos, motor de autorización y concesiones

No reutilizar el permiso general report.read para ampliar acceso. Los nombres de permiso deben incorporarse expresamente a ALL_PERMISSIONS y PROFILE_PERMISSIONS en backend/app/auth/permissions.py. Hoy no existen allí; require_permission() lanza ValueError al definir una ruta si recibe un permiso desconocido.

### 12.1 Permisos específicos y perfiles

Permisos nuevos:

- rewinding_export.create.
- rewinding_export.read_own.
- rewinding_export.read_sector.
- rewinding_export.annul.

Matriz explícita:

| Permiso | OPERACION | SUPERVISION | JEFATURA | CALIDAD | DATA_BALTREK |
|---|---:|---:|---:|---:|---:|
| rewinding_export.create | Sí | No | No | No | No |
| rewinding_export.read_own | Sí | No | No | No | No |
| rewinding_export.read_sector | No | Sí | Sí | No | No |
| rewinding_export.annul | No | No | Sí | No | No |

No heredar permisos por ser administrador técnico ni ampliar permisos de Calidad, Tubetes o reportes existentes.

### 12.2 Creación: operación dedicada P1-07

Añadir Operation.REWINDING_EXPORT_CREATE y su OperationPolicy específica:

- permiso funcional: rewinding_export.create.
- área del formulario: production.
- formulario admitido: exclusivamente VINTO-P1-07.
- contexto: máquina de la captura madre, resuelta por backend.

P1-07 ya figura en capture_service.CENTRAL_FORM_CODES y sus versiones publicadas se relacionan con las máquinas elegibles. La política nueva no modifica ni amplía las políticas de captura existentes.

Los endpoints de selección de madres/crías consultan la elegibilidad con authorize(..., lock=False) para ocultar opciones que el usuario no puede utilizar. La generación final ejecuta require(..., lock=True) dentro de la misma transacción, antes de bloquear las filas de Calidad y los datos RBE. Debe comprobar perfil activo, sector concedido y operativo, máquina/formulario activos, versión publicada vigente y concesión exacta usuario–máquina–P1-07. Esta operación se exige siempre para RBE; no depende de los modos heredados off/observe/enforce de las compuertas de otras capturas.

Crear/editar un borrador exige rewinding_export.create, propiedad del borrador y alcance sectorial. La selección de madre se filtra por la operación dedicada; la confirmación vuelve a autorizar y revalidar con bloqueos.

### 12.3 Consulta y anulación: permiso + sector, sin concesión máquina/formulario

- read_own: OPERACION consulta únicamente reportes cuyo created_by = user.user_id y que pertenecen al sector REBOBINADO.
- read_sector: SUPERVISION y JEFATURA consultan el historial del sector REBOBINADO.
- annul: solo JEFATURA; exige motivo y alcance REBOBINADO.

Historial, detalle y descarga PDF aplican el mismo filtro de propietario/sector en cada endpoint, no solo en el listado. Un UUID fuera de alcance responde como recurso inexistente (404), sin revelar su existencia. La anulación verifica rewinding_export.annul y el sector, pero no exige concesión máquina/formulario P1-07: esa concesión limita la creación de Operación, no la consulta o gestión de Supervisión/Jefefatura. La comprobación se repite dentro de la transacción de anulación contra PostgreSQL, no se confía únicamente en AuthenticatedUser construido al inicio de la petición: user activo FOR SHARE → user_profile/profile activos FOR SHARE → permissions_for_profiles debe incluir rewinding_export.annul y el perfil debe incluir JEFATURA → user_sector debe contener REBOBINADO activo y operativo. El bloqueo FOR SHARE sobre user sincroniza con revoke_sector, que toma FOR NO KEY UPDATE sobre la misma fila antes de eliminar la concesión. Si la revocación confirmó primero, la anulación se deniega; si la anulación obtuvo primero el bloqueo, la revocación espera al COMMIT. No se toma ningún grant máquina/formulario para esta operación.

Para historial/detalle/PDF se usará una dependencia que acepte exactamente read_own o read_sector según el perfil, y que aplique el filtro correspondiente en SQL. No se sustituye por report.read.

### 12.4 Aprovisionamiento explícito de REBOBINADO

user_sector es una concesión explícita. Que REBOBINADO esté habilitado en operational_sector_codes() no concede acceso a ningún usuario. La migración 0006 hizo backfill de BOBINAS, no de REBOBINADO; scoped_sector_codes() devuelve alcance vacío cuando falta la concesión.

Antes del rollout debe existir una lista aprobada de usuarios y concederse REBOBINADO de forma individual y auditada mediante el mecanismo existente (grant_sector). No hacer backfill masivo por perfil.

Además, cada operador autorizado necesita una concesión activa exacta en user_machine_form_grant para su usuario, máquina y formulario VINTO-P1-07. Es una concesión independiente, explícita y revocable; no se deriva del perfil ni de la concesión de sector. No concederla masivamente a todos los usuarios OPERACION.

SUPERVISION y JEFATURA necesitan el permiso funcional correspondiente y la concesión de sector REBOBINADO; no necesitan una concesión máquina/formulario. Ningún perfil omite el alcance de sector.

## 13. Validaciones

### V01–V08 de la especificación

| Código | Validación | Resultado |
|---|---|---|
| V01 | PV o producto no seleccionado | 422 |
| V02 | Camión u orden vacío | 422 |
| V03 | Paquete sin madre o sin Cría A | 422 |
| V04 | Cría repetida en dos paquetes | 422 |
| V05 | Cría pending, rejected, sin evaluación o ya reservada | 409 si cambió/disponibilidad; 422 si payload inválido |
| V06 | Cría no pertenece a la madre del paquete | 422 |
| V07 | Mezcla de PV, producto, formato, destino o máquina | 422; Formato queda pendiente de D04 |
| V08 | Cambio de estado entre selección y generación | 409 |

### Validaciones adicionales

- La madre debe ser P1-07 v3+ y estar identificada por capture UUID.
- Solo capturas submitted/closed.
- Cría con peso válido y posición permitida.
- Máquina activa y sector REBOBINADO.
- OT no archivada ni retirada como QA.
- Una sola máquina, PV, producto y destino por reporte.
- Una madre puede repetirse; una cría no.
- El creador original se resuelve desde capture.created_by.
- Si el usuario original no existe o no puede resolverse, no inventar un nombre.
- Ayudante NULL no bloquea.
- PDF y snapshot deben tener hash verificable.
- Un reporte generado no se edita ni se reconstruye.

---

## 14. Warnings de datos de origen

RBE-01 detectó:

1. Una captura con hora fin anterior a hora inicio.
2. Una captura donde las crías suman 33,55 kg y la madre declara 25 kg.
3. Dos capturas donde “Cortes” vale 6 y 0 con tres crías cada una.
4. Producto refilado informado solo 1/6 y no equivalente al artículo de OT.
5. Ayudante informado 4/6.
6. Observaciones de origen 0/6.

D09 establece que el reporte advierte y no modifica los datos fuente. Se propone codificar warnings en la vista previa:

- SOURCE_TIME_INVERTED.
- CHILD_WEIGHT_SUM_EXCEEDS_MOTHER.
- SOURCE_CUTS_DO_NOT_MATCH_CHILD_COUNT.
- OPTIONAL_SOURCE_FIELD_MISSING.

No corregir ni reemplazar valores. Functional debe indicar cuáles warnings son informativos y cuáles bloquean la generación. Hasta esa definición no se debe introducir una regla de bloqueo nueva por intuición.

---

## 15. Historial y auditoría

El historial se filtra en backend en todas las rutas:

- OPERACION: permiso rewinding_export.read_own, created_by = user.user_id y sector REBOBINADO.
- SUPERVISION: permiso rewinding_export.read_sector y sector REBOBINADO.
- JEFATURA: permiso rewinding_export.read_sector y sector REBOBINADO; puede anular mediante rewinding_export.annul.
- CALIDAD y DATA_BALTREK: sin acceso funcional a este reporte.

El filtro se aplica en historial, detalle, descarga PDF y anulación. No basta con ocultar acciones en frontend ni con filtrar solo el listado. Los recursos fuera del alcance se tratan como inexistentes (404).

Cada fila de historial muestra:

- Fecha de generación.
- PV y producto.
- Máquina.
- Camión y orden.
- Usuario generador.
- Estado.
- Acciones permitidas según permiso.

El detalle conserva:

- Datos del origen al momento de generar.
- Paquetes y crías.
- Snapshot de todos los campos impresos.
- PDF original, tamaño y SHA-256.
- Usuario generador y fecha/hora.
- Eventos de borrador, generación, observación y anulación.
- Historial de reservas y liberaciones con actor, fecha y motivo.

La descarga no consulta los valores productivos actuales para reconstruir el documento. Devuelve los bytes guardados y verifica su SHA-256 antes de responder. Los endpoints de lectura y PDF usan Cache-Control: private, no-store.

## 16. Plan de pruebas RBE-03–RBE-06

### API y filtros

- PV con y sin crías elegibles.
- Producto dependiente del PV.
- Madres con etiqueta repetida, distinguibles por UUID.
- Solo máquinas P1-07 publicadas y dentro del alcance.
- OT published, in_progress y closed.
- OT archivada y qa_retired excluidas.
- QA no marcado: debe bloquearse hasta criterio formal.
- Crías released, pending, rejected/reutilizable y sin decisión.
- Peso, posición, madre y operador original.
- Operador sin concesión REBOBINADO: sin datos ni acceso.
- Operador con sector pero sin concesión máquina/P1-07: no puede generar.
- Supervisión/Jefatura con sector y permiso: pueden consultar sin concesión máquina/formulario.
- DATA_BALTREK y CALIDAD: denegados.

### Paquetes e integridad referencial

- Una cría.
- Cinco crías.
- Intento de seis crías.
- Cría A ausente.
- Misma madre en varias líneas.
- Cría repetida dentro de un paquete o entre paquetes.
- Cría de otra madre.
- Inserción de package_child con package_id de un reporte y report_id de otro: rechazada por FK compuesta.
- Destinos diferentes.
- PV/productos/máquinas diferentes.
- Ayudante vacío.
- Etiquetas madre duplicadas.

### Reservas, estados y concurrencia

- Borrador/Descartado sin ninguna reserva.
- Retirada de paquete y de selección en Borrador: historia conservada, disponibilidad recuperada y posibilidad de volver a seleccionar la cría.
- Intento de modificar paquete/cría después de Generado, Observado o Anulado: rechazado por trigger.
- Generado con exactamente una reserva activa por selección congelada.
- Observado conserva todas las reservas activas.
- Anulado conserva historial y no deja reservas activas.
- Intentos de falsear el estado de reserva, liberar sin anular, liberar dos veces o borrar/truncar reservas: rechazados por triggers/permisos.
- Dos operadores generan simultáneamente con la misma cría: solo uno gana.
- Reporte con varias crías y una ya reservada: ninguna reserva parcial.
- Calidad cambia antes de confirmar: 409.
- Dos conexiones para generate-vs-generate, generate-vs-annul, generate-vs-quality-correction y generate-vs-qa-retirement; sin deadlock y con revalidación después de esperar.
- Anulación con revocación concurrente de sector/perfil: se serializa; no puede anularse con concesión ya revocada.
- Revocación de permiso o concesión antes de generar.
- Reintento con misma clave/huella: mismo report_id y PDF.
- Misma clave con huella distinta: 409.
- Colisión UNIQUE concurrente 23505: recarga del resultado confirmado, sin repetir reserva.

### PDF, snapshot e historial

- A4 vertical, blanco y negro.
- Veinte paquetes en una página.
- Veintiún paquetes en dos páginas.
- Sin máximo funcional de páginas/paquetes; prueba de paginación con más de 100 páginas.
- Límite técnico de bytes; exceso falla sin truncamiento ni persistencia parcial.
- Crías A–E en cada paquete.
- Observaciones una sola vez al final.
- Re-descarga byte a byte idéntica y SHA-256 coincidente.
- Intentos de UPDATE/DELETE/TRUNCATE de PDF: rechazados por permisos y trigger.
- Intento de cambiar snapshot después de Generado: rechazado por trigger.
- PDF y snapshot conservados al pasar a Observado y Anulado.
- Restauración de backup en entorno aislado y comparación SHA-256 del PDF descargado con el hash original.
- No se genera con Formato/Corte sin homologación D04.

### Permisos

- ALL_PERMISSIONS contiene los cuatro permisos y PROFILE_PERMISSIONS asigna exactamente la matriz de D11.
- Ruta con permiso desconocido falla en pruebas de arranque; rutas RBE usan permisos registrados.
- Operación solo ve sus reportes propios.
- Supervisión/Jefatura solo ven REBOBINADO.
- Jefatura anula con motivo; Operación y Supervisión reciben 403.
- Consultar detalle/PDF por UUID ajeno no revela existencia.
- Supervisión/Jefatura no dependen de user_machine_form_grant.

### Regresión

- P1-07, captura de Producción, Calidad y decisiones de Calidad.
- F3 de Bobinas.
- P1-03 y Tubetes.
- Conversión.
- Permisos y concesiones existentes.
- Calidad Offline, PWA, IndexedDB, firmas, cola y sincronización.

Las pruebas de concurrencia, cambios de estado y reservas usan PostgreSQL 17 efímero. No crear datos artificiales en la VPS productiva.

## 17. Migración, rollout y seguridad

- Solo migraciones aditivas.
- No modificar capturas P1-07, bobbin, quality_release ni work_order existentes.
- No backfill de madres/crías.
- No asignar crías existentes durante migración.
- No cambiar decisiones de Calidad.
- No ampliar report.read.
- Registrar los cuatro permisos nuevos en ALL_PERMISSIONS y PROFILE_PERMISSIONS antes de definir rutas que los utilicen.
- Añadir Operation.REWINDING_EXPORT_CREATE y su política P1-07 sin modificar las políticas de captura existentes.
- Nuevas tablas con REVOKE ALL FROM PUBLIC y GRANT mínimo explícito a vinto_app según el patrón de migraciones.
- Cabecera: SELECT/INSERT/UPDATE para transiciones autorizadas; sin DELETE/TRUNCATE. Trigger valida estado, actor, motivo y snapshot.
- Paquetes y package_child: SELECT/INSERT/UPDATE solo en Borrador; sin DELETE/TRUNCATE. Triggers permiten retirada lógica solo en Borrador y congelan todas las filas desde Generado.
- Reservas: SELECT/INSERT/UPDATE solo para crear y liberar dentro de transacciones autorizadas; sin DELETE/TRUNCATE y con trigger de transición.
- PDF: exclusivamente SELECT/INSERT para vinto_app; nunca UPDATE/DELETE/TRUNCATE.
- Eventos: INSERT/SELECT; nunca UPDATE/DELETE/TRUNCATE.
- Triggers de integridad referencial, transiciones, retirada lógica, auditoría, inmutabilidad de snapshot/PDF y paquetes/crías, coherencia diferible de reservas y sincronización con retirada QA.
- La retirada QA debe bloquear la fila work_order y comprobar reportes RBE activos antes de archivar/marcar qa_retired; si existen Generados/Observados, debe detenerse hasta su anulación por Jefatura.
- Antes del rollout, aprobar lista nominativa de usuarios y conceder explícitamente REBOBINADO; no backfill por perfil.
- Conceder máquina + P1-07 individualmente a los operadores que deban generar; Supervisión/Jefatura no reciben estas concesiones para leer/anular.
- No añadir flags que habiliten el sector o formularios por defecto.
- El rollout se hará en la VPS existente mediante artefacto verificado, backup, restauración aislada, gates D2 y rollback.
- No modificar Calidad Offline.
- El número de migración se seleccionará al implementar, sincronizando main; hoy main termina en 0031.

Este apartado describe el diseño de seguridad. No aplica concesiones, GRANT, migraciones ni cambios de permisos en esta fase documental.

## 18. Pendientes de confirmación funcional antes de cerrar RBE-02

Las decisiones D01–D11 están aprobadas. Los siguientes puntos son definiciones adicionales que no se pueden resolver con el código ni los datos actuales:

1. **Formato/Corte (bloqueante para PDF):** significado exacto de formato_1, formato_2 y formato_3. Confirmar cuál alimenta el campo Formato del encabezado y cuál alimenta Corte por paquete.
2. **QA no marcado:** criterio verificable para identificar OTs/datos QA que no tienen qa_retired ni archived_at. No inferir por prefijo ni por nombre de usuario.
3. **Warnings bloqueantes:** cuáles de las anomalías de horas, pesos y cortes impiden generar y cuáles son solo informativas.
4. **Operador original:** las 11 capturas auditadas pertenecen a una sola cuenta OPERACION cuyo nombre empieza por Q. Confirmar si esa cuenta representa al operador real o una cuenta QA compartida; el sistema seguirá mostrando capture.created_by sin sustituirlo.
5. **Producto refilado:** confirmar si se imprime como complemento en el PDF o se conserva solo en vista previa/snapshot. Nunca reemplaza el artículo de OT.
6. **Versiones de artículo:** confirmar cómo mostrar una única descripción de producto si varias madres del mismo article_id tienen article_version.description diferente.
7. **Cambios posteriores de Calidad:** la API actual no permite released → rejected mediante operación normal. Confirmar el proceso autorizado de corrección que deberá activar Observado; el trigger propuesto no habilita una nueva decisión por sí mismo.

Hasta cerrar estos puntos, el diseño de filtros, persistencia, paquetes, permisos, reserva e historial puede avanzar, pero no debe cerrarse el contrato final del PDF ni activarse generación productiva.

---

## 19. Puertas de aprobación

| Puerta | Entregable | Estado |
|---|---|---|
| RBE-01 | Auditoría de solo lectura | PASS |
| RBE-02 | Diseño técnico detallado | Documentado; pendiente aprobación |
| Functional | Confirmaciones pendientes de sección 18 | Pendiente |
| RBE-03 | Interfaz parametrizable | No iniciado |
| RBE-04 | Backend, migración, reservas y estados | No iniciado |
| RBE-05 | PDF e historial inmutable | No iniciado |
| RBE-06 | QA, backup, gates D2 y despliegue | No iniciado |

### Límites de RBE-02

- Este documento no implementa código.
- No crea tablas ni migraciones.
- No modifica P1-07, Calidad, F3 ni permisos.
- No consulta ni escribe en la VPS.
- No modifica PostgreSQL productivo.
- No modifica Calidad Offline.
- No despliega ni fusiona código funcional.

**Siguiente acción:** revisar y aprobar el diseño RBE-02 y resolver las preguntas funcionales de la sección 18. Después se autoriza RBE-03/RBE-04 mediante PRs independientes.


---

## 20. Registro de revisión técnica — 27/11/2026

Se incorporan las siete observaciones de la revisión del PR #274, sin modificar código ni ejecutar migraciones:

| Observación | Resolución documental |
|---|---|
| 1. Integridad paquete–reporte | Clave única compuesta (id, report_id) y FK compuesta desde package_child. |
| 2. Orden de bloqueos | Orden común para generación, anulación y corrección de Calidad; READ COMMITTED y revalidación después de cada espera. |
| 3. Transiciones de reservas | Se elimina el booleano duplicado y se separa la tabla de reservas; triggers y restricciones diferibles hacen cumplir las invariantes por estado. |
| 4. Idempotencia | Clave de generación y SHA-256 persistidos; unicidad por actor; tratamiento seguro de colisión 23505. |
| 5. PDF/snapshot | PDF INSERT/SELECT, inmutabilidad por permisos y triggers, tamaño/hash, verificación de descarga y restauración de backup. |
| 6. Sector REBOBINADO | Aprovisionamiento explícito y auditado por usuario; sin backfill masivo por perfil. |
| 7. Permisos y operación | Permisos registrados en ALL_PERMISSIONS/PROFILE_PERMISSIONS; operación dedicada P1-07 solo para creación; lectura/anulación por permiso y sector, sin concesión máquina/formulario para Supervisión/Jefatura. |

### Alcance de esta revisión

- Solo se modifica este documento de diseño.
- No se modifica código, pruebas, migraciones, permisos ni datos.
- No se realizan consultas ni cambios en VPS/PostgreSQL.
- El Issue #275 conserva las siete confirmaciones funcionales pendientes.
- PR #274 permanece Draft y pendiente de nueva revisión del usuario.
- RBE-03, RBE-04, RBE-05 y RBE-06 no se inician ni se consideran autorizados.
