# VINTO · RBE-03 — Interfaz parametrizable del Reporte de Bobinas Refiladas para Exportación

**Fecha:** 27/11/2026  
**Estado:** implementación frontend en PR independiente  
**Base:** RBE-02 (PR #274, documento de diseño)

## 1. Alcance de RBE-03

RBE-03 implementa la interfaz de usuario de Operación para conformar el reporte parametrizable. No crea nuevas capturas P1-07, no modifica Calidad, no modifica F3 y no reserva crías. El backend de RBE-04 será la única autoridad de elegibilidad, permisos, disponibilidad, persistencia y concurrencia. RBE-05 será responsable del PDF original y su descarga.

Incluye:
- Filtro dependiente PV → producto/artículo → bobina madre.
- Consulta de crías de la madre y selección por posiciones A–E.
- Cría A obligatoria; máximo cinco por paquete.
- La misma madre puede repetirse en paquetes distintos; una cría no puede repetirse dentro del reporte.
- Alta, edición y retirada lógica de paquetes mientras el reporte sea Borrador.
- Camión, orden y observaciones generales.
- Fecha automática de creación del borrador, en modo solo lectura.
- Presentación de Formato/Cortes con los valores originales de P1-07.
- Vista previa de validaciones, warnings y errores bloqueantes devueltos por el backend.
- Recuperación de borradores propios desde el servidor después de recargar.
- Panel de Jefatura para consultar y registrar clasificación append-only de OTs.

## 2. Ubicación y permisos

- La interfaz de creación se muestra dentro de Rebobinado → Ejecución solo cuando el servidor devuelve "rewinding_export.create" o "rewinding_export.read_own".
- La lista de borradores se consulta con "rewinding_export.read_own".
- El panel de clasificación se muestra dentro de Rebobinado → Programación solo cuando el servidor devuelve "rewinding_export.classify_source".
- La interfaz no deduce permisos por el nombre del perfil ni sustituye la autorización backend.
- Los componentes quedan ocultos cuando la sesión no tiene los permisos correspondientes.

## 3. Reglas de presentación y selección

- Formato: "formato_1" y, si existe, "formato_2", unidos por " + ".
- Cortes: "formato_3" literal.
- No se convierten decimales, no se agregan unidades y no se genera un código como "0-C".
- Cada selector muestra "Cría N - peso kg" usando posición y peso fuente.
- La selección de interfaz evita repetir crías en paquetes activos del mismo borrador, pero el servidor vuelve a validar Calidad, pertenencia, disponibilidad y reservas.
- La interfaz compara PV, artículo, máquina, destino, Formato y Cortes entre las madres de un mismo reporte.
- Si el operador fuente no se puede resolver, se muestra la incidencia y no se promete que el reporte pueda generarse; el backend aplica la regla bloqueante.
- Los cuatro warnings de origen definidos en RBE-02 se presentan como informativos; V01–V08 siguen siendo bloqueantes.

## 4. Contratos API consumidos (RBE-04)

Raíz: /api/reports/rewinding-export.

| Método | Ruta | Uso en RBE-03 |
|---|---|---|
| GET | /pvs | PV con madres que tienen crías elegibles |
| GET | /products?pv_reference= | Productos asociados al PV |
| GET | /mothers?pv_reference=&article_id= | Madres elegibles |
| GET | /mothers/{mother_capture_id}/children | Crías released y disponibles |
| GET | /drafts | Borradores propios para recuperación |
| POST | /drafts | Crear borrador |
| GET/PATCH | /drafts/{report_id} | Recuperar/editar cabecera |
| POST | /drafts/{report_id}/packages | Agregar paquete |
| PATCH | /drafts/{report_id}/packages/{package_id} | Editar paquete |
| POST | /drafts/{report_id}/packages/{package_id}/remove | Retirar paquete |
| POST | /drafts/{report_id}/preview | Validar y devolver warnings/bloqueantes |
| GET | /work-orders | Listar OTs clasificables en REBOBINADO; incluye published, in_progress y closed, excluye archived/qa_retired |
| GET | /work-orders/{work_order_id}/classification | Consultar última clasificación de OT |
| POST | /work-orders/{work_order_id}/classification | Registrar nueva decisión append-only |

RBE-02 ya proponía POST de clasificación. RBE-03 necesita además una lectura de la última decisión para que Jefatura no clasifique a ciegas. RBE-04 debe implementar GET y POST con el mismo permiso, alcance REBOBINADO y revalidación transaccional.

La lectura GET /drafts es necesaria para recuperar borradores tras recargar el navegador. RBE-04 debe devolver solo borradores del usuario autenticado cuando se usa "rewinding_export.read_own".

La interfaz no invoca /generate ni /pdf en RBE-03. El botón Generar PDF permanece deshabilitado hasta completar RBE-04 y RBE-05.

## 5. Contrato de datos de frontend

- IDs de madre y crías son UUIDs fuente; no se construyen códigos artificiales.
- formato_1, formato_2, formato_3, peso y posición se reciben como valores fuente.
- El cliente envía mother_capture_id y UUIDs de crías ordenados por slot A–E; nunca envía valores técnicos como autoridad.
- La respuesta del borrador incluye paquetes, madre fuente y snapshots de crías para reabrir y editar.
- Los parsers rechazan respuestas incompletas, crías no released, posición 12 y valores decimales mal formados.
- Las claves de recursos incluyen el identificador de sesión para evitar reutilización de respuestas entre cuentas.

## 6. Seguridad y límites

- No hay localStorage, sessionStorage, IndexedDB ni cola offline.
- No hay datos de demostración ni fallback local.
- No hay generación PDF, reservas ni confirmación simulada.
- No se modifican P1-07, Calidad, F3, Calidad Offline ni registros productivos.
- El endpoint de preview es solo una revalidación; no reserva crías.
- Una mutación fallida no se representa como exitosa; los datos se refrescan desde el servidor.

## 7. Verificación

El workflow .github/workflows/rbe03-frontend.yml ejecuta:
1. ESLint.
2. TypeScript tsc --noEmit.
3. Pruebas puras de reglas y parsers.
4. Render SSR de estados iniciales y visibilidad por permiso.
5. Build de producción.

Las pruebas de integración con PostgreSQL, concurrencia, permisos reales y PDF pertenecen a RBE-04/RBE-05.

## 8. Puertas siguientes

- RBE-03: cerrar interfaz y CI frontend.
- RBE-04: implementar los contratos API, migraciones, permisos, reservas, idempotencia y clasificación.
- RBE-05: generar y conservar el PDF original, snapshot e historial.
- RBE-06: QA, backup, gates D2 y despliegue controlado.

No se fusiona RBE-03 ni se despliega hasta que los incrementos dependientes estén implementados y superen sus pruebas.
