# VINTO — RBE-02
## Diseño técnico detallado: Bobinas Refiladas para Exportación

**Fecha:** 27 de noviembre de 2026  
**Estado:** diseño documentado; pendiente de revisión y aprobación.  
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
- 503: base o servicio no disponible.

Los errores públicos no deben incluir SQL, valores fuente sensibles ni razones internas del motor de autorización.

---

## 8. Persistencia propuesta

Se propone usar tablas nuevas en vinto_txn, sin alterar las tablas de Producción, P1-07 ni Calidad.

### 8.1 Cabecera: rewinding_export_report

Campos conceptuales:

- id UUID como identidad técnica del reporte; no crear código industrial.
- status: draft, generated, observed, annulled.
- pv_reference.
- article_id y snapshot de código/descrición del producto.
- machine_id.
- destination_snapshot.
- truck_number.
- order_number.
- observations.
- created_by / created_at.
- generated_by / generated_at.
- annulled_by / annulled_at / annulment_reason.
- snapshot_version.
- report_snapshot JSONB inmutable después de generar.
- idempotency_key asociado al creador.

Los campos manuales camión y orden pueden estar vacíos en un borrador, pero son obligatorios al generar.

### 8.2 Paquetes: rewinding_export_package

Una fila por paquete físico:

- id UUID.
- report_id.
- package_number, secuencial dentro del reporte.
- mother_capture_id: UUID de captura P1-07.
- mother_bobbin_id: referencia a la fila técnica de madre, si se conserva como FK adicional.
- mother_label_snapshot.
- source_capture_revision y source_form_version_id.
- article_version_id exacto de la OT.
- source_fields_snapshot JSONB con valores P1-07 relevantes.
- source_operator_user_id y operator_display_name_snapshot.

Una misma mother_capture_id puede repetirse en diferentes paquetes.

### 8.3 Crías por paquete: rewinding_export_package_child

Una fila por cría seleccionada:

- id UUID.
- report_id.
- package_id.
- child_bobbin_id.
- package_slot A–E.
- source_position.
- weight_kg_snapshot.
- reservation_active.
- reserved_at.
- released_at / released_by / release_reason.

Restricciones propuestas:
- UNIQUE(package_id, package_slot).
- UNIQUE(report_id, child_bobbin_id): una cría no se repite dentro del mismo reporte.
- UNIQUE parcial global sobre child_bobbin_id WHERE reservation_active = true: una cría no puede estar reservada por dos reportes vigentes.
- FK a bobbin con ON DELETE RESTRICT.
- Slot A–E; el servicio valida que A exista antes de generar.
- La reserva está inactiva durante Borrador y activa solo al confirmar Generado.

### 8.4 PDF inmutable: rewinding_export_pdf

Una fila por reporte generado:

- report_id.
- file_name.
- mime_type application/pdf.
- pdf_bytes BYTEA.
- sha256 del contenido.
- generated_at.
- tamaño en bytes.

Se recomienda guardar el PDF binario en PostgreSQL junto con el snapshot. No se encontró un servicio de almacenamiento de documentos existente en el backend; BYTEA evita depender de una ruta local o almacenamiento externo y permite incluir el documento en el backup de la base.

El PDF se genera en backend desde el snapshot validado. El endpoint de descarga devuelve exactamente los bytes guardados; no reconstruye el PDF con datos productivos actuales.

El backend actual no incluye una biblioteca PDF en requirements.txt. RBE-05 deberá seleccionar y fijar una dependencia de renderizado (por ejemplo ReportLab) tras validar compatibilidad, fuentes y salida A4. No se agrega ahora.

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

Los eventos no reemplazan el trigger de auditoría genérico del proyecto; agregan una cronología funcional legible.

### 8.6 Índices y reglas de integridad

- Historial por created_by + created_at.
- Historial por machine_id + generated_at.
- Historial por PV + generated_at.
- Paquetes por report_id + package_number.
- Paquetes por mother_capture_id.
- Crías por report_id.
- Índice único parcial de reserva activa por child_bobbin_id.
- Índice único de idempotencia por created_by + idempotency_key.
- FKs ON DELETE RESTRICT para conservar trazabilidad.
- Prohibir DELETE/TRUNCATE de reportes generados, PDFs y eventos.
- Snapshot y bytes PDF inmutables después de generar.

La migración será aditiva. En el main revisado el último archivo es 0031; el siguiente número se confirmará al sincronizar la rama de implementación, no se fija ahora.

---

## 9. Transacción de generación y concurrencia

La operación Generate es el punto crítico. Debe confirmar cabecera, paquetes, relación paquete-cría, snapshot, PDF y reservas en una sola transacción.

### Secuencia propuesta

1. Autenticar usuario y comprobar permiso de creación.
2. Verificar que el reporte existe y está en Borrador, pertenece al creador y está dentro del sector/máquina autorizados.
3. Leer IDs seleccionados y validar estructura: paquete, madre, Cría A, máximo cinco y no repetición.
4. Iniciar transacción READ COMMITTED.
5. Resolver y bloquear filas de quality_release de todas las crías en orden estable por bobbin_id; todas deben seguir released.
6. Bloquear las filas de bobbin correspondientes y verificar identidad, posición, peso, madre y máquina.
7. Bloquear/leer las capturas madre y relaciones de OT necesarias; verificar PV, artículo, destino, máquina, OT no archivada y no QA.
8. Bloquear el reporte Borrador.
9. Releer el estado completo y comprobar que coincide con la selección/snapshot preliminar.
10. Validar V01–V08 y reglas D01–D09.
11. Construir snapshot inmutable con valores exactos de origen, entradas manuales, usuario generador, fecha/hora y warnings.
12. Generar PDF desde ese snapshot dentro de la operación controlada.
13. Insertar report_snapshot y PDF con SHA-256.
14. Activar reservation_active para todas las crías seleccionadas.
15. Cambiar el reporte a Generado, registrar actor/fecha y evento.
16. COMMIT.

Si cualquier paso falla, toda la transacción hace ROLLBACK: no queda PDF parcial, cabecera generada ni reserva parcial.

### Protección ante concurrencia

- El índice único parcial de reserva activa es la última barrera, independiente del frontend.
- Los bloqueos de quality_release se toman en orden estable por UUID.
- Todas las rutas que generen, anulen o actualicen el estado de reservas respetan el mismo orden de bloqueos.
- Una carrera por la misma cría termina en 409.
- No se usa solo una consulta previa de disponibilidad como garantía.
- El endpoint usa idempotency_key; un reintento idéntico devuelve el reporte ya generado y el mismo PDF. Una clave repetida con payload diferente devuelve 409.

Los borradores no reservan crías. Dos borradores pueden mostrar temporalmente la misma cría; el primero que genera la reserva. El segundo recibe 409 y debe refrescar su selección.

---

## 10. Estados y ciclo de vida

| Estado | Entrada | Edición | Reserva | PDF |
|---|---|---|---|---|
| Borrador | Crear reporte parametrizable | Sí, por creador | No | No definitivo |
| Generado | Confirmación transaccional | No | Sí | Inmutable |
| Observado | Cambio de Calidad o inconsistencia posterior | No | Sí; no reutilizar crías | Se conserva |
| Anulado | Jefatura anula con motivo | No | Se libera | Se conserva |

### Transiciones

- Borrador → Generado: solo mediante la transacción de generación.
- Borrador → descarte: creador puede descartar su borrador; no hay reservas que liberar.
- Generado → Observado: evento de sistema cuando una cría vinculada deja de cumplir el estado de Calidad o se detecta una inconsistencia de origen definida como observación.
- Generado → Anulado: Jefatura con motivo obligatorio.
- Observado → Anulado: Jefatura con motivo obligatorio.
- Anulado: estado terminal; no se reactiva ni se modifica el PDF.

### Observado y Calidad

La especificación indica que si una cría pasa a Rechazada el reporte queda Observado y la cría no puede reutilizarse.

La API actual de Calidad solo permite pending → released/rejected y rechaza una segunda decisión. No se encontró una transición ordinaria released → rejected. El diseño propone un trigger de base de datos para capturar una corrección futura autorizada que cambie released a rejected y marcar los reportes vigentes como Observados. La forma autorizada de corregir una decisión ya liberada debe confirmarse con Functional/Calidad antes de implementar ese trigger.

Un reporte Observado mantiene las reservas hasta que Jefatura lo anule. La anulación libera la reserva del reporte, pero una cría cuyo estado actual sea rejected continúa excluida por D01.

---

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

## 12. Permisos y alcance

No reutilizar el permiso general report.read para ampliar acceso.

Permisos específicos propuestos:

| Permiso | OPERACION | SUPERVISION | JEFATURA |
|---|---:|---:|---:|
| rewinding_export.create | Sí | No por defecto | No por defecto |
| rewinding_export.read_own | Sí | No necesario | No necesario |
| rewinding_export.read_sector | No | Sí | Sí |
| rewinding_export.annul | No | No | Sí |

Reglas:
- OPERACION genera y consulta únicamente reportes creados por su usuario.
- OPERACION necesita sector REBOBINADO y concesión activa para la máquina + formulario P1-07.
- SUPERVISION consulta historial dentro del sector REBOBINADO.
- JEFATURA consulta historial del sector y anula reportes con motivo.
- CALIDAD no genera ni anula; sus decisiones siguen en el módulo de Calidad.
- DATA_BALTREK no recibe permisos funcionales por ser administrador técnico.
- Ningún perfil omite el alcance de sector.
- La autorización se verifica en backend en cada endpoint, no solo ocultando botones.

La implementación debe extender la matriz de permisos y el motor de autorización efectivo con una operación dedicada de exportación. No se concede report.read global ni se amplían permisos de Tubetes.

---

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

El historial se filtra en backend:

- OPERACION: solo sus propios reportes.
- SUPERVISION: reportes del sector REBOBINADO.
- JEFATURA: reportes del sector REBOBINADO y acción de anulación.

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
- PDF original y SHA-256.
- Usuario generador y fecha/hora.
- Eventos de borrador, generación, observación y anulación.

La descarga no consulta los valores productivos actuales para reconstruir el documento. Devuelve los bytes guardados.

Los endpoints de lectura y PDF usan Cache-Control: private, no-store.

---

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

### Paquetes

- Una cría.
- Cinco crías.
- Intento de seis crías.
- Cría A ausente.
- Misma madre en varias líneas.
- Cría repetida dentro de un paquete o entre paquetes.
- Cría de otra madre.
- Destinos diferentes.
- PV/productos/máquinas diferentes.
- Ayudante vacío.
- Etiquetas madre duplicadas.

### Concurrencia

- Dos operadores generan simultáneamente con la misma cría: solo uno gana.
- Reporte con varias crías y una ya reservada: ninguna reserva parcial.
- Calidad cambia antes de confirmar: 409.
- Reintento idempotente: mismo report_id y mismo PDF.
- Anulación concurrente con generación.
- Revocación de permiso o concesión antes de generar.

### PDF e historial

- A4 vertical, blanco y negro.
- Veinte paquetes en una página.
- Veintiún paquetes en dos páginas.
- Crías A–E en cada paquete.
- Observaciones una sola vez al final.
- Re-descarga byte a byte idéntica y SHA-256 coincidente.
- Snapshot inmutable después de generar.
- Observado conserva PDF y reservas.
- Anulado conserva PDF/historial y libera reservas.
- No se genera con Formato/Corte sin homologación D04.

### Regresión

- P1-07, captura de Producción, Calidad y decisiones de Calidad.
- F3 de Bobinas.
- P1-03 y Tubetes.
- Conversión.
- Permisos y concesiones.
- Calidad Offline, PWA, IndexedDB, firmas, cola y sincronización.

Las pruebas de concurrencia, cambios de estado y reservas usan PostgreSQL 17 efímero. No crear datos artificiales en la VPS productiva.

---

## 17. Migración, rollout y seguridad

- Solo migraciones aditivas.
- No modificar capturas P1-07, bobbin, quality_release ni work_order existentes.
- No backfill de madres/crías.
- No asignar crías existentes durante migración.
- No cambiar decisiones de Calidad.
- No ampliar report.read.
- Nuevas tablas con REVOKE ALL FROM PUBLIC y GRANT mínimo explícito a vinto_app según patrón de migraciones.
- Triggers de integridad y auditoría para reportes, reservas, documentos y eventos.
- No añadir flags que habiliten el sector o formularios por defecto.
- El rollout se hará en la VPS existente mediante artefacto verificado, backup, restauración aislada, gates D2 y rollback.
- No modificar Calidad Offline.
- El número de migración se seleccionará al implementar, sincronizando main; hoy main termina en 0031.

---

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
