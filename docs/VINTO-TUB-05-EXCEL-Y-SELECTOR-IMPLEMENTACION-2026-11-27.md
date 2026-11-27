# VINTO — Mejora de vista y TUB-05: Exportación Excel de Tubetes Utilizados

**Fecha:** 27 de noviembre de 2026  
**Estado:** implementación en rama; pendiente de CI y revisión.  
**Base funcional:** especificación funcional para Data — Reporte de Tubetes Utilizados, secciones 4, 5, 6 y 7.  
**Dependencia:** API `GET /api/reports/tubetes-used`, TUB-02, y pantalla TUB-03/TUB-04.

---

## 1. Alcance de este incremento

Este PR agrupa dos cambios de la misma pantalla, sin modificar backend ni la fuente de datos:

1. Selector de visualización `Ambas / MP1 / MP3` y ajuste responsive de la tabla.
2. Exportación Excel TUB-05, recuperada del backlog #260 por autorización del usuario.

La selección cambia únicamente la máquina visible en pantalla. Las descargas PDF y Excel siguen incluyendo ambas máquinas, para respetar el reporte completo de la especificación.

## 2. Ajuste de interfaz

- Selector visible con tres opciones: Ambas, MP1 y MP3.
- Valor inicial: Ambas.
- Al elegir MP1 o MP3 se muestra únicamente la máquina seleccionada.
- No se consulta una fuente distinta ni se envían filtros a la API.
- Las tarjetas de máquina se apilan verticalmente cuando se muestran ambas.
- Tabla con ancho adaptable, columnas de código, usos y fechas; elimina el ancho mínimo de 560 px que causaba desplazamiento horizontal en la tarjeta.
- Las fechas se mantienen en chips que se ajustan a varias líneas.
- El selector no cambia el contenido de las exportaciones.

## 3. Especificación funcional Excel

La especificación funcional establece:

- Dos hojas: `MP1` y `MP3`.
- Cada código aparece una sola vez dentro de la hoja de su máquina.
- Cada uso agrega una fecha en la siguiente columna disponible: `Fecha 1`, `Fecha 2`, etc.
- Las fechas se ordenan cronológicamente.
- Si el mismo código existe en MP1 y MP3, aparece de forma independiente en ambas hojas.
- Dos utilizaciones del mismo código en el mismo día se conservan como dos columnas/valores independientes.
- El Excel puede mantener todas las fechas en columnas adicionales, sin límite de diez.
- No se agregan PV, producto, turno, operador ni otros campos.

### Estructura

Cada hoja contiene:
- Columna A: `Código`, guardado como texto para no convertir ni alterar el valor.
- Columnas siguientes: `Fecha 1` hasta `Fecha N`, donde N es la mayor cantidad de usos de un código de esa máquina.
- Una fila por código de tubete.
- Fechas reales de Excel con formato visual `dd/mm/yy`.
- Fila de encabezados congelada y autofiltro.

Si una máquina no tiene códigos, su hoja permanece disponible con el encabezado `Código` y sin filas de datos. No se inventan registros.

## 4. Fuente y consistencia

- Se usa exclusivamente la respuesta ya cargada de `GET /api/reports/tubetes-used`.
- No se vuelve a consultar otra fuente.
- No se recalculan ni se deduplican fechas.
- Se valida el contrato antes de construir el libro.
- El nombre del archivo usa la fecha de generación en `America/La_Paz`: `tubetes-utilizados-AAAA-MM-DD.xlsx`.
- El archivo se genera como Blob en el navegador y se descarga; no se guarda en el servidor.

La implementación genera un paquete OOXML/XLSX con componentes estándar del formato ZIP/XML y no añade dependencias ni modifica `package.json` o `pnpm-lock.yaml`.

## 5. Pruebas

- Dos hojas con nombres exactos MP1 y MP3.
- Una fila por código.
- Código almacenado como texto.
- Fechas como celdas numéricas de fecha con formato `dd/mm/yy`.
- Columnas dinámicas hasta el máximo de usos de cada máquina.
- Más de diez usos (23 fechas) sin truncamiento.
- Repeticiones de una misma fecha en columnas independientes.
- Hoja vacía cuando no hay códigos.
- Fila de encabezado congelada y autofiltro.
- Nombre de archivo en zona `America/La_Paz`.
- Validación del ZIP, CRC y XML OOXML mediante Node y la biblioteca estándar de Python (`zipfile`, `xml.etree`).

## 6. Límites

- No modifica backend, endpoint, P1-03, permisos, sesiones ni migraciones.
- No modifica Calidad Offline, PWA, IndexedDB, bóveda, firmas, grants, cola ni sincronización.
- No escribe ni crea datos en PostgreSQL/VPS.
- No despliega ni fusiona automáticamente.

**Siguiente puerta:** GitHub Actions PASS, revisión del PR y autorización de merge por separado.
