# VINTO — TUB-04: Generación del PDF de Tubetes Utilizados

**Fecha:** 27 de noviembre de 2026  
**Estado:** implementación completada; CI PASS; PR #261 listo para revisión, sin merge ni despliegue.  
**Dependencias:** TUB-02 (#258) y TUB-03 (#259), ambos fusionados.  
**Alcance:** descarga PDF local desde Bobinas → Seguimiento → Reportes → Tubetes utilizados.

---

## 1. Base funcional

Se utiliza la especificación funcional `Especificacion_funcional_reporte_tubetes_utilizados.pdf`, especialmente:

- Sección 4: agrupación por código, fechas cronológicas y conservación de dos usos el mismo día.
- Sección 6: Código + Fecha 1 a Fecha 10; fila de continuación `(cont.)` cuando un código supera diez usos.
- Sección 7: PDF en blanco y negro, cuadrícula compacta, título por máquina, diez columnas de fechas por bloque y paginación automática.

Decisiones aprobadas en TUB-01:
- Código original de P1-03 como texto, sin prefijo ni ceros añadidos.
- Fecha `operating_date`, zona `America/La_Paz`.
- Máquinas MP1 y MP3.
- Conservar repeticiones; no deduplicar usos del mismo día.
- El endpoint TUB-02 entrega todas las fechas para ambas máquinas en una sola respuesta.

## 2. Implementación

El PDF se genera en el navegador desde la respuesta ya cargada de:

`GET /api/reports/tubetes-used`

No se vuelve a consultar otra fuente, no se recalculan fechas y no se guarda el documento en el servidor.

### Formato del PDF

- Papel A4 vertical.
- Blanco y negro; fuente estándar Helvetica.
- Encabezado con título específico por máquina.
- Tabla compacta con 11 columnas: Código y Fecha 1 a Fecha 10.
- Fecha mostrada como `DD/MM/YY`, conforme al ejemplo de la especificación.
- MP1 y MP3 se presentan en secciones/páginas independientes.
- Pie con paginación global `PAGINA X DE Y`.
- Si una máquina no tiene usos con código, se muestra una fila informativa sin inventar datos.
- No se incorporan PV, producto, turno, operador, calidad, peso ni otros campos.

### Continuación de códigos

Cada código se divide en bloques de diez fechas:
- 1 a 10: primera fila, código original.
- 11 a 20: segunda fila, mismo código + `(cont.)`.
- 21 a 30: tercera fila, mismo código + `(cont.)`.
- Y así sucesivamente.

La continuación conserva el orden cronológico. Dos fechas iguales permanecen como dos celdas distintas porque representan dos producciones/consumos independientes.

La paginación física se aplica después de expandir los bloques de diez, repite encabezado de máquina y columnas en cada página y mantiene la marca `(cont.)` si el bloque continúa en una página posterior.

## 3. Descarga y almacenamiento

- Botón `Descargar PDF`, habilitado cuando el reporte está cargado.
- Botón `Imprimir`: abre el mismo PDF generado en una nueva pestaña para utilizar la impresión nativa del visor PDF.
- Nombre: `tubetes-utilizados-AAAA-MM-DD.pdf`, con fecha de generación en `America/La_Paz`.
- El PDF se crea como Blob en el navegador y se descarga directamente.
- No se envía el archivo al backend ni se guarda un historial de documentos.
- No se agrega dependencia externa: el PDF se construye con objetos PDF 1.4 y fuentes estándar, sin alterar `package.json` ni `pnpm-lock.yaml`.

La descarga y la acción Imprimir generan el mismo documento desde la misma respuesta del API. La acción Imprimir abre el visor PDF del navegador en una nueva pestaña; desde allí se utiliza la impresión nativa. La exportación Excel no forma parte de TUB-04.

## 4. Pruebas

La suite `scripts/tubetes-pdf.test.mjs` cubre:
- 10 usos: una sola fila.
- 11 usos: una fila normal y una de continuación.
- 23 usos: bloques de 10, 10 y 3.
- 23 usos el mismo día: no se deduplican.
- MP1/MP3 separados.
- Máquina sin registros.
- Más de 34 filas de tabla: paginación automática y numeración global.
- Estructura PDF 1.4, A4 vertical, referencias xref y etiqueta de continuación.
- Nombre de archivo con zona horaria de planta.
- Rechazo de payload inconsistente.

GitHub Actions incorpora las pruebas del generador PDF y lint sobre el componente y módulos modificados, además de TypeScript y build.

### Resultado de CI (27/11/2026)

Workflow: `VINTO Tubetes report TUB-02 (PostgreSQL 17)` — PASS.

- 14/14 pruebas de servicio/API TUB-02.
- 7/7 pruebas de matriz de permisos.
- 6/6 pruebas estáticas de alcance sectorial.
- 17/17 regresiones P1-03 y Calidad.
- 15/15 regresiones frontend de autenticación/permisos.
- 6/6 pruebas del contrato frontend del reporte.
- 8/8 pruebas del generador PDF.
- TypeScript, ESLint y build PASS.

La primera ejecución detectó la resolución del import en Node y dos reglas React Hooks en el componente; también se incorporó la acción Imprimir. Se corrigieron y la ejecución final del HEAD `2a5a842b058ac72f76004a569069b77fbb4cbd93` terminó PASS (GitHub Actions run `46036066354`).

## 5. Backlog: TUB-05 Excel

Por decisión del usuario, Excel no se implementa en este incremento.

Issue de backlog:
[#260 — TUB-05 Exportación Excel del reporte Tubetes Utilizados](https://github.com/BaltrekCompany/vinto-mvp-web/issues/260)

El issue conserva el alcance futuro:
- Hojas MP1 y MP3.
- Todas las fechas sin límite de diez.
- Repeticiones conservadas.
- Conciliación con la misma respuesta de TUB-02 y el PDF.

## 6. Límites y protección

- No se modifica backend ni el endpoint TUB-02.
- No se modifica P1-03.
- No se añaden migraciones.
- No se modifica login, sesiones ni permisos.
- No se modifica Calidad Offline, PWA, IndexedDB, bóveda, firmas, grants, cola ni sincronización.
- No se hacen escrituras ni consultas nuevas en la VPS/producción.
- No se despliega ni se fusiona mediante este incremento.

**Siguiente puerta:** CI PASS, revisión del PR TUB-04 y autorización de merge por separado.
