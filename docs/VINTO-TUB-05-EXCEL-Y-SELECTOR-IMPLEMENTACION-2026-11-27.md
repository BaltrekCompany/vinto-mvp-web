# VINTO — Mejora de vista y TUB-05: Exportación Excel de Tubetes Utilizados

**Fecha:** 27 de noviembre de 2026  
**Estado:** MERGED, desplegado en producción y QA funcional manual confirmado PASS el 27 de noviembre de 2026.  
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

### Resultado CI (27/11/2026)

Workflow [#46044107821](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/46044107821): PASS.

- 15/15 pruebas de autenticación/permisos frontend.
- 7/7 pruebas de contrato del reporte y selector de máquina.
- 8/8 pruebas del libro Excel.
- `TUBETES_XLSX_OOXML=PASS`: ZIP/CRC y todos los XML abiertos y validados con Python estándar.
- 8/8 pruebas de PDF.
- 14/14 pruebas de servicio/API en PostgreSQL 17 efímero.
- 7/7 pruebas de matriz de permisos.
- 6/6 pruebas estáticas de alcance sectorial.
- 17/17 regresiones P1-03 y Calidad.
- TypeScript, ESLint y build PASS.

Total: 82 pruebas automatizadas aprobadas, más validación independiente del paquete OOXML.

## 6. Límites

- No modifica backend, endpoint, P1-03, permisos, sesiones ni migraciones.
- No modifica Calidad Offline, PWA, IndexedDB, bóveda, firmas, grants, cola ni sincronización.
- No escribe ni crea datos en PostgreSQL/VPS.
- La generación de Excel ocurre en el navegador; el archivo no se persiste en el servidor.

## 7. Integración y despliegue productivo

- PR #269 fusionado mediante Squash and Merge.
- Commit integrado y desplegado: `35e64d0d75900d04b1fe11cb8902f6d1b3fd69c2`.
- Release anterior: `258e3b958964df44df9ddc0e165450656ea8794d`.
- Activación reportada a las 18:09:44 UTC del 27/11/2026.
- Workflow E2-D2 [#46046673557](https://github.com/BaltrekCompany/vinto-mvp-web/actions/runs/46046673557): success sobre el SHA exacto.
- Artefacto: `vinto-mvp-frontend-e2d2-35e64d0d75900d04b1fe11cb8902f6d1b3fd69c2`.
- Digest ZIP: `4ddc73c15dfad747d9222f83e391b1dfa0ba540433c10f9e47ca61daae83b5d0`.
- SHA-256 TAR/manifiesto: `169ea6b7ce0e68507b564bbf00b65a988783f75a005fee54aa0b0b73f6047a91`.
- Backup: `vinto-mvp-vinto_piloto-20261127-180817-2461791.dump`.
- SHA-256 backup: `4fa975355594900fde0610ab7b06715ea8ce59c2bbbf6fe40ba04ff6643f4ffa`.
- Restauración aislada: PASS, 53 tablas comparadas.
- Gates D2 de activación y rollback: PASS.
- Backend y frontend saludables; endpoints 200; sin nuevos 5xx en la ventana revisada.
- Nginx, Docker y PostgreSQL no se reiniciaron.
- Service worker conserva el mismo SHA-256; rutas Offline de API idénticas y configuración `backend.env` no modificada.

## 8. QA funcional en producción

**Resultado:** PASS, confirmado por el usuario el 27/11/2026.

La confirmación cubre la matriz manual entregada para:
- Selector Ambas / MP1 / MP3 y regreso a Ambas.
- Visualización de tablas sin desplazamiento horizontal indebido.
- Descarga y apertura del Excel con hojas MP1 y MP3.
- Conservación de las dos hojas Excel aunque la vista esté filtrada a una máquina.
- Fechas y repeticiones, incluido el código MP3 80 con dos usos el 27/11/2026.
- PDF que conserva MP1 y MP3 aunque la vista esté filtrada.
- Apertura del PDF mediante Imprimir y uso del visor nativo.
- Verificación funcional de Calidad Offline.

### Cobertura de más de diez utilizaciones

Los datos reales disponibles no contienen un código con más de diez usos. La cobertura se verificó sin escribir en PostgreSQL:
- Excel: 23 fechas en 23 columnas dinámicas.
- PDF: filas de 10, 10 y 3 utilizaciones con continuación.

Esta limitación de datos reales queda registrada; no se crearon registros artificiales.

## 9. Cierre

TUB-05 queda implementado, fusionado, desplegado y con QA funcional manual confirmado PASS por el usuario. La documentación técnica y el registro de despliegue/QA se conservan en GitHub.
