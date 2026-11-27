# VINTO — Plan de desarrollo: Reporte de Tubetes Utilizados

**Fecha de actualización:** 27 de noviembre de 2026  
**Proyecto:** VINTO MVP Web  
**Repositorio:** [BaltrekCompany/vinto-mvp-web](https://github.com/BaltrekCompany/vinto-mvp-web)  
**Estado:** planificación aprobada para iniciar TUB-01; implementación todavía no iniciada.  
**Alcance vigente:** exclusivamente el Reporte de Tubetes Utilizados (MP1 y MP3).

---

## 1. Decisión de alcance

Se acuerda desarrollar los entregables de reportería de manera secuencial, un reporte a la vez. Para esta etapa se trabajará **únicamente en el Reporte de Tubetes Utilizados**.

Quedan fuera del alcance de esta planificación y no deben incorporarse a sus PR:

- Reporte de bobinas refiladas para exportación.
- Reporte de producción para carga de Expertus.
- Cualquier otro reporte o consolidado no descrito en la especificación de Tubetes.

Los reportes excluidos podrán planificarse posteriormente como entregas independientes. No son dependencias de TUB-01 a TUB-06.

## 2. Fuente funcional

Documento de referencia: **Especificación funcional — Reporte de Tubetes Utilizados**, de tres páginas, entregada para el proyecto.

### Objetivo

Reemplazar la hoja física de control mediante un reporte automático que consolide cada uso de tubete registrado en **Producción de Bobinas**. El usuario no vuelve a digitar códigos ni fechas.

### Datos de origen y tratamiento

| Dato del reporte | Fuente definida | Tratamiento |
|---|---|---|
| Código de tubete | Producción de Bobinas, campo «Código tubete» | Identifica el tubete y agrupa sus utilizaciones |
| Fecha de utilización | Fecha del registro de Producción de Bobinas | Se incorpora cronológicamente al código |
| Máquina | Máquina del registro de Producción de Bobinas | Separa MP1 y MP3 |

### Reglas funcionales

1. Cada código aparece una sola vez dentro de la hoja de su máquina.
2. Cada utilización agrega una fecha en la siguiente columna disponible: Fecha 1, Fecha 2, Fecha 3, etc.
3. Las fechas se ordenan de la más antigua a la más reciente.
4. La máquina se obtiene del registro; no se digita ni se selecciona manualmente.
5. Si un código se utiliza en MP1 y MP3, aparece independientemente en ambas hojas.
6. Dos producciones válidas del mismo código en el mismo día se conservan como dos utilizaciones.
7. El reporte refleja nuevas producciones registradas con código de tubete al actualizar la consulta.
8. No se agregan PV, producto, turno, operador ni otros campos.

### Presentación y exportación

- Ubicación: **Seguimiento → Reportes → Tubetes utilizados**.
- Dos pestañas: MP1 y MP3.
- Acciones: Descargar PDF, Descargar Excel e Imprimir.
- PDF: blanco y negro, cuadrícula compacta, título por máquina, Código + Fecha 1 a Fecha 10 y paginación automática.
- Si un código supera diez utilizaciones, el PDF crea una fila de continuación con el mismo código e indicación «(cont.)».
- Excel conserva todas las fechas en columnas adicionales.
- PDF y Excel deben representar exactamente el mismo conjunto de utilizaciones.

## 3. Auditoría del código existente

La auditoría inicial de `main` identificó:

- La definición publicada de P1-03 es `VINTO-P1-03`, «Registro de producción de bobinas», vinculada a las máquinas MP1 y MP3.
- Su definición de referencia contiene el campo `codigo_de_tubete`, con etiqueta «Código de tubete», declarado como tipo `integer` y obligatorio.
- El servicio especializado de bobinas registra la captura y sus detalles en PostgreSQL. El valor del código debe recuperarse desde los detalles persistidos de la captura, no desde una tabla duplicada.
- La vista de captura central distingue `captured_at` (momento de captura) y `operating_date` (fecha operativa derivada de la asignación).
- El listado actual `GET /api/captures` exige `production.capture` y su servicio histórico no es la ruta especializada de P1-03. No se debe asumir que sirve directamente para este reporte.
- En Seguimiento ya existe un panel «Reportes» que presenta reportes pendientes. El reporte de tubetes se incorporará en ese espacio, sin crear otra navegación.

Referencias técnicas de partida:

- [P1-03 — definición de formulario](../backend/seed_data/forms/VINTO-P1-03.json)
- [Servicio de producción de bobinas](../backend/app/bobbins/service.py)
- [Esquema de captura de bobinas](../backend/app/bobbins/schemas.py)
- [Servicio central de capturas](../backend/app/capture_service.py)
- [Rutas de capturas](../backend/app/captures.py)
- [Pantalla principal y Seguimiento](../app/page.tsx)
- [Permisos por perfil](../backend/app/auth/permissions.py)
- [Visibilidad por máquina y sector](../backend/app/authz/visibility.py)

### Discrepancias que TUB-01 debe resolver

**A. Tipo real del código.** La definición de P1-03 declara el código como entero, mientras que el ejemplo visual de la especificación utiliza valores como `TUB-001`. Se debe consultar el dato persistido y confirmar el formato real. No se añadirá prefijo, padding, conversión ni normalización sin una regla funcional aprobada.

**B. Fecha de utilización y zona horaria.** La especificación dice «fecha del registro de Producción de Bobinas», mientras que el modelo distingue `captured_at` y `operating_date`. La auditoría recomienda `operating_date`, pero el código actual usa `America/La_Paz`; Functional debe confirmar que esa es la zona horaria real de la planta o si corresponde `America/Lima`. No se cambiará la zona horaria por inferencia.

**C. Permisos de consulta.** Se evaluará el acceso de Jefatura y Supervisión al reporte sin concederles permiso de captura. Se propone una autorización de lectura específica y de mínimo privilegio (por ejemplo, `report.read`), limitada al sector y máquinas correspondientes. El nombre, perfiles y alcance final se validarán antes de implementar; no se ampliará `production.capture` como atajo.

## 4. Decisión sobre el entorno de pruebas

El usuario confirma que los datos actualmente presentes en la VPS/instalación de producción son ficticios y que se puede utilizar el **entorno de producción actual para realizar pruebas** de este entregable.

Esta autorización permite planificar validaciones funcionales sobre la instalación real, no únicamente en bases efímeras o simuladores.

### Ejecución de consultas VPS mediante Claude Code

Las consultas de TUB-01 a la VPS se ejecutarán mediante **Claude Code**, utilizando la conexión SSH ya configurada en ese entorno. ChatGPT/GitHub MCP se utilizará para revisar el repositorio y documentar resultados; no se asumirá acceso SSH directo desde esta conversación.

Para TUB-01, Claude Code deberá:

- Ejecutar únicamente inspección y consultas de solo lectura.
- Preferir consultas SQL dentro de una transacción explícitamente `READ ONLY` cuando corresponda.
- No ejecutar `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, DDL, migraciones ni scripts de aplicación.
- No reiniciar servicios, reconstruir contenedores, desplegar, cambiar configuración, permisos, firewall o Nginx.
- No leer ni mostrar secretos, contraseñas, tokens, claves privadas, archivos `.env` ni credenciales.
- No copiar dumps ni datos personales a la conversación. Entregar conteos, muestras mínimas anonimizadas y resultados sanitizados.
- Registrar comandos, destino confirmado, hora, alcance y resultado para que la auditoría sea reproducible.

Si una consulta necesita permisos adicionales, revela un esquema distinto del esperado o no puede garantizarse que sea de solo lectura, Claude Code debe detenerse y solicitar revisión antes de continuar.

Debe aplicarse de forma controlada:

1. Identificar y documentar los datos de prueba para distinguirlos de los registros ficticios preexistentes.
2. Para TUB-01, comenzar con consultas de solo lectura y no modificar datos.
3. En incrementos posteriores, usar registros de prueba identificables y de alcance limitado cuando la prueba requiera escrituras.
4. No borrar registros preexistentes ni ejecutar limpiezas destructivas como parte de una prueba ordinaria.
5. No enviar comunicaciones, integraciones externas ni cargas a Expertus; no forman parte de este reporte.
6. Antes de cualquier cambio persistente, verificar destino, respaldo/recuperación aplicable, alcance y resultado esperado.
7. No ejecutar migraciones, cambios de configuración de VPS, Nginx, servicios, credenciales o permisos productivos sin revisión y autorización específica.
8. La autorización para probar en el entorno productivo no equivale a autorización automática para fusionar PR, desplegar nuevos cambios o realizar operaciones destructivas.

El uso de datos ficticios reduce el riesgo de contaminar información industrial real, pero no elimina el riesgo técnico sobre la aplicación, la base de datos, los servicios compartidos o la disponibilidad. Se mantienen controles de reversibilidad y mínimo impacto.

## 5. Protección de Calidad Offline

La memoria integral de Calidad Offline del 26 de noviembre es una referencia obligatoria de arquitectura y operación:

[VINTO-CALIDAD-OFFLINE-MEMORIA-INTEGRAL-2026-11-26.md](./VINTO-CALIDAD-OFFLINE-MEMORIA-INTEGRAL-2026-11-26.md)

Calidad Offline se encuentra cerrado funcionalmente, integrado y desplegado. Este trabajo de reportería no debe reabrir ni alterar esa entrega.

### Límites obligatorios

No modificar como parte de TUB-01 a TUB-06:

- Login principal, sesiones, cookies, CSRF ni identidad del usuario.
- Bóveda cifrada, IndexedDB, Service Worker, PWA ni cachés existentes de Offline.
- Firmas Ed25519, grants, enrolamiento ni autoridades de captura Offline.
- Cola, autoguardado, conciliación, idempotencia ni sincronización de Calidad.
- Formularios, decisiones, estados o endpoints de Calidad.
- Digest de bobinas/madres o las reglas de unicidad de Calidad.

La reportería será una capacidad independiente, de consulta y exportación. No utilizará la cola Offline para guardar reportes ni creará una segunda fuente de verdad.

Cualquier necesidad futura de disponer del reporte sin Internet deberá evaluarse como una ampliación separada, sin reutilizar ni modificar por defecto los mecanismos de Calidad Offline.

## 6. Arquitectura propuesta

Flujo previsto:

```text
Seguimiento → Reportes → Tubetes utilizados
                  |
                  v
       API de reporte (solo lectura)
                  |
                  v
       PostgreSQL / capturas P1-03
                  |
          +-------+-------+
          |               |
          v               v
       MP1 / MP3     Agrupar por código
                          |
                   Ordenar utilizaciones
                          |
                +---------+---------+
                |                   |
                v                   v
             PDF local          Excel local
```

Principios:

- Fuente única: capturas de Producción de Bobinas P1-03.
- Consulta de solo lectura; sin alterar capturas ni detalles originales.
- Agrupación independiente por máquina y código.
- Conservar multiplicidad de utilizaciones, incluso el mismo código y día.
- Respetar autenticación, permiso de lectura y alcance de sector/máquina.
- Respuestas de API sin caché HTTP compartida; el cliente controlará la actualización y la identidad de sesión.
- Generación de PDF y Excel en el dispositivo, con descarga directa.
- No persistir el PDF/Excel ni mantener historial de documentos en el servidor.
- No añadir migraciones si el modelo actual permite resolver el reporte mediante consulta. Cualquier necesidad de esquema deberá justificarse y revisarse por separado.

## 7. Plan incremental

| Incremento | Alcance | Entregable y puerta de salida |
|---|---|---|
| **TUB-01** | Auditoría de datos y contrato | Consulta read-only en VPS; muestra de datos anonimizados/sanitizados; confirmación del código, fecha, duplicados y volumen; contrato de respuesta aprobado |
| **TUB-02** | Backend de consulta | Endpoint read-only, agrupación por máquina/código, orden cronológico, permisos mínimos y pruebas automatizadas |
| **TUB-03** | Interfaz | Opción en Seguimiento → Reportes, pestañas MP1/MP3, tabla, estados de carga/error y actualización |
| **TUB-04** | PDF | Formato físico, diez fechas por bloque, continuación y paginación |
| **TUB-05** | Excel e impresión | Dos hojas, todas las fechas, impresión y conciliación exacta con PDF |
| **TUB-06** | QA y cierre | Matriz funcional, permisos, integridad, regresión, CI, revisión de PR y evidencia de aceptación |

Cada incremento se revisa antes de avanzar. No se implementarán TUB-02 a TUB-06 en bloque ni se mezclará trabajo de otros reportes.

## 8. Criterios de aceptación

El reporte se considera terminado cuando:

1. El código de tubete coincide exactamente con el dato de P1-03.
2. La fecha utilizada corresponde a la regla confirmada por Functional.
3. MP1 y MP3 se separan correctamente.
4. Cada código aparece una sola vez por máquina, salvo filas de continuación necesarias en PDF.
5. Las fechas se ordenan de más antigua a más reciente.
6. Dos usos válidos del mismo código en un día se conservan ambos.
7. Una nueva producción aparece al actualizar el reporte.
8. PDF y Excel contienen el mismo universo de utilizaciones.
9. PDF mantiene diez fechas por bloque y continúa correctamente al superar diez.
10. El usuario no vuelve a digitar códigos ni fechas.
11. La consulta no modifica registros originales.
12. Usuarios sin permiso o fuera del alcance no pueden consultar datos.
13. Las pruebas no introducen regresiones en Calidad Offline ni en los formularios originales.

## 9. GitHub, CI y despliegue

- TUB-02 se implementó en la rama independiente `feat/tubetes-utilizados-report`, creada desde `main` (`b84562d9`).
- PR de implementación: [#258](https://github.com/BaltrekCompany/vinto-mvp-web/pull/258), separado del PR documental y de Calidad Offline.
- La batería TUB-02 y la matriz de regresión de GitHub Actions terminaron PASS.
- PR #258 fue aprobado y fusionado mediante squash el 27/11/2026. Commit de integración: `5f66f6001d670b30fff99b44a08aa3286703dd81`.
- TUB-03 está en implementación en la rama `feat/tubetes-report-ui`, PR #259 (Draft) con la pantalla en Bobinas → Seguimiento → Reportes.
- TUB-03 consume la API TUB-02, conserva todas las fechas/repeticiones y no incorpora exportaciones.
- TUB-04 (PDF) y TUB-05 (Excel) se desarrollarán como incrementos posteriores y PR independientes, usando el mismo contrato/API.
- Despliegue controlado y validación posterior requieren autorización independiente.

La documentación de este plan se mantiene en un PR documental independiente. Este PR no incorpora código funcional, migraciones, cambios de VPS ni despliegues.

## 10. Estado y próximo paso

**Estado:** TUB-01 ejecutado el 27 de noviembre de 2026 con resultado `TUB01_AUDIT=PARTIAL` como auditoría de la muestra productiva. Las decisiones funcionales D01-D05 y la estrategia D06 de pruebas sintéticas quedaron aprobadas. La muestra real sigue sin contener MP1 con código, reutilizaciones, más de diez usos ni repeticiones en el mismo día; esos escenarios ya se demostraron con fixtures sintéticos PG17 durante TUB-02.

**Informe de auditoría y decisiones aprobadas:** [VINTO-TUB-01-AUDITORIA-TUBETES-2026-11-27.md](./VINTO-TUB-01-AUDITORIA-TUBETES-2026-11-27.md).

**Diseño técnico y resultado de implementación TUB-02:** [VINTO-TUB-02-DISENO-TECNICO-2026-11-27.md](./VINTO-TUB-02-DISENO-TECNICO-2026-11-27.md).

**PR de implementación TUB-02:** [#258 — Backend de Tubetes](https://github.com/BaltrekCompany/vinto-mvp-web/pull/258). Aprobado y fusionado el 27/11/2026. Squash commit: `5f66f6001d670b30fff99b44a08aa3286703dd81`. Sin despliegue.

**TUB-03:** [PR #259 — Pantalla Seguimiento → Reportes](https://github.com/BaltrekCompany/vinto-mvp-web/pull/259). En desarrollo/CI; muestra MP1 y MP3, código, cantidad de usos y todas las fechas con repetición preservada. No incluye PDF/Excel.

**Reglas aprobadas:** código entero original sin prefijo/ceros; fecha `operating_date` en `America/La_Paz`; incluir consumos con Calidad liberada, rechazada o pendiente y excluir borradores, bloqueadas y órdenes `qa_retired`; permiso `report.read` para Jefatura/Supervisión con alcance BOBINAS/MP1/MP3; API con ambas máquinas en una respuesta y todas las fechas/repeticiones conservadas.

**Estrategia de pruebas:** fixtures sintéticos en PostgreSQL efímero PG17, sin capturas artificiales ni escrituras de prueba en la VPS. La matriz de casos de TUB-02 ya pasó.

**Siguiente acción:** completar CI y revisión del PR #259 (TUB-03), aprobar y fusionar por separado. Luego iniciar TUB-04 (PDF con bloques de diez fechas y continuación) y TUB-05 (Excel con dos hojas, todas las fechas), cada uno con su PR. El despliegue productivo requiere autorización separada.

**Fuera de alcance:** cualquier implementación de bobinas refiladas para exportación o de producción para Expertus hasta que se abra una planificación independiente.
