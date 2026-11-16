# VINTO — Revisión parcial de excepciones D–I

**Fecha:** 16/11/2026 (Lima)  
**Repositorio:** BaltrekCompany/vinto-mvp-web  
**Base auditada en GitHub:** main, SHA `2ca165af615ad5405a526e40d73e96ff8f83b4a6`  
**Estado:** **OPEN / PARTIAL — NO PASS**  
**Alcance:** documentación de hallazgos recibidos de Codex y contraste estático con el código de la base indicada.

## 1. Alcance y límites de evidencia

El reporte de Codex recibido indica que las consultas PostgreSQL se ejecutaron en transacciones READ ONLY, con timeout de 15 segundos. No se consultaron valores individuales de capturas ni actores. Esta acta conserva esa restricción y no incorpora IDs, nombres de usuarios ni valores de captura.

El total de seis madres técnicas proviene del perfilamiento previo. La consulta inicial que intentó contar el total de madres estaba mal formulada porque contó la fila del agregado; por tanto, ese total no se presenta como resultado independiente de la consulta de capturas.

Esta revisión no modifica datos, políticas, permisos, migraciones ni registros de producción. Tampoco certifica el estado actual de la VPS.

## 2. Resultados recibidos

| Control | Evidencia recibida | Clasificación | Dictamen |
| --- | --- | --- | --- |
| Capturas sin asignación | 21 capturas distribuidas entre P1-18, P1-22, P1-26 y P1-27, en MP1 y MP3. Por formulario, conteos MP1/MP3: P1-18 (4/2), P1-22 (2/2), P1-26 (5/2), P1-27 (3/1). | COMPORTAMIENTO_ESPERADO | Cerrable como comportamiento esperado de Calidad independiente de OT. |
| Política efectiva y contradicción documental | En el SHA auditado, MACHINE_QUALITY_FORM_CODES contiene P1-18, P1-22, P1-26 y P1-27. El docstring inicial todavía afirma que la política está vacía; un comentario posterior explica la habilitación de QA interno en MP1/MP3. | COMPORTAMIENTO_ESPERADO | La constante ejecutable prevalece. Se corrige en esta rama únicamente el comentario contradictorio, sin cambiar comportamiento. |
| Madres técnicas y capturas de Calidad | El cruce reportó cero capturas de Calidad asociadas a las seis madres técnicas del perfilamiento previo. | NO_VERIFICABLE | La ausencia de capturas no demuestra un defecto: falta determinar si había controles pendientes, disponibilidad y concesiones para esas madres. |
| Asignaciones y ejecuciones | 173 asignaciones, 76 ejecuciones y 99 pares lógicos OT–máquina–línea. 99 asignaciones relacionadas y 74 sin ejecución; 76 ejecuciones relacionadas y cero sin asignación. Máximo dos asignaciones por ejecución. Las ejecuciones se limitaron a baseline v1. | COMPORTAMIENTO_ESPERADO | La conciliación de conjuntos reconcilia los totales. Conservar la limitación de baseline v1 al interpretar el resultado. |
| Duraciones prolongadas y abiertas | 16 ejecuciones finalizadas superan 24 horas. Distribución: COPASA 3, GAMBINI 3, MP1 2, MP3 1, OMET_I 3, PERICHUN 2 y TUBETERA 2. Hay 3 ejecuciones abiertas en estado in_production: COPASA, MP3 y OVER. | DIFERENCIA_FUNCIONAL | Requiere validación operativa. El tiempo calculado es transcurrido entre inicio y fin, no tiempo efectivo de producción. |

## 3. Contraste con la implementación

### 3.1 Calidad independiente de asignación

En backend/app/quality/machine_capture_service.py, la ruta de Calidad por máquina declara expresamente que no requiere bobina ni asignación. Su consulta filtra bobbin_id IS NULL y assignment_id IS NULL. Por ello, las 21 capturas descritas no son por sí mismas huérfanas ni un defecto de integridad.

La política efectiva en el SHA auditado es la lista explícita de cuatro formularios P1-18, P1-22, P1-26 y P1-27. No se infiere habilitación por el mero hecho de que un formulario esté publicado.

### 3.2 Calidad sobre madres P1-07

La implementación de Calidad sobre bobinas contempla la madre técnica P1-07 mediante bobbin.rewind_mother_capture_id:

- backend/app/quality/capture_service.py resuelve el contexto de bobina y reconoce la madre técnica.
- backend/app/quality/mother_policy.py restringe la política a COPASA, BELOIT y OVER y a P1-19, P1-20, P1-21, P1-24, P1-25 y P1-28.
- Las migraciones 0029 y 0030 incorporan la identidad técnica y la excepción acotada para capturas de Calidad sobre la madre.
- La captura de Calidad sobre la madre se vincula mediante bobbin_id a la identidad técnica; no debe confundirse con la ruta de Calidad independiente de máquina.

El cero observado debe investigarse como posible ausencia de uso, falta de elegibilidad o falta de concesión. No autoriza a crear capturas ni a modificar permisos.

### 3.3 Ciclo de vida de ejecución

En backend/app/work_orders/line_execution.py, el ciclo lógico es planned → enabled → in_production → finished. El inicio y fin se registran con started_at y finished_at. La migración 0013 impone transiciones válidas, coherencia de timestamps y exclusividad de una línea en producción por máquina.

En el código revisado no se encontró un umbral automático de 24 horas ni cierre automático por cambio de turno. Por ello:

- Una duración superior a 24 horas no prueba por sí sola una anomalía.
- Una ejecución abierta in_production no debe cerrarse automáticamente como correctivo de auditoría.
- La duración observada no debe describirse como tiempo efectivo de producción.
- La regla de negocio para continuidad entre turnos y cierre oportuno requiere confirmación funcional.

## 4. Acciones para completar la auditoría

### A. Madres técnicas — solo lectura

Solicitar a Codex una segunda consulta que, sin exponer IDs ni actores, confirme:

1. Conteo de madres técnicas por máquina usando rewind_mother_capture_id.
2. Para cada combinación máquina/formulario de la lista permitida, existencia de una versión publicada vigente y formulario activo.
3. Conteos agregados de concesiones activas pertinentes, sin mostrar usuario, actor, grant ID ni datos individuales.
4. Conteos de capturas de Calidad por madre y formulario, sin mostrar valores ni identificadores.
5. Si las seis madres tienen al menos una opción de Calidad elegible o si alguna carece de versión/grant.

No crear grants, capturas ni versiones durante esta comprobación.

### B. Ejecuciones prolongadas y abiertas — solo lectura

Solicitar a Codex que:

1. Agrupe las 16 ejecuciones finalizadas por intervalos de duración (24–48 h, 48–72 h y más de 72 h) y máquina.
2. Para cada ejecución abierta, contraste el estado de la OT y la existencia de asignación vigente OT–máquina–línea para el turno/fecha actuales.
3. Compruebe si las ejecuciones prolongadas cruzan varios registros de asignación por cambios de turno y si existen huecos o solapamientos.
4. Informe únicamente conteos agregados y clasificaciones, sin IDs, actores ni valores de captura.
5. Mantenga las consultas READ ONLY y timeout máximo de 15 segundos.

No ejecutar finish_line, UPDATE, DELETE, migraciones, reinicios ni despliegues.

## 5. Criterios de cierre

- Capturas de Calidad independientes de OT: cerrar como comportamiento esperado si se mantiene la correspondencia de los 21 registros con la ruta y política explícitas.
- Asignaciones/ejecuciones: cerrar la conciliación cuantitativa, conservando el alcance baseline v1 y sin extrapolar los pares lógicos a equivalencias uno-a-uno.
- Política de Calidad por máquina: cerrar el hallazgo funcional siguiendo la constante ejecutable; la contradicción documental queda corregida en esta rama.
- Madres técnicas: permanecer NO_VERIFICABLE hasta obtener disponibilidad y concesiones agregadas y confirmar la expectativa funcional de uso.
- Duraciones: permanecer DIFERENCIA_FUNCIONAL hasta que el responsable funcional defina si se permite continuidad entre turnos, qué constituye una ejecución abandonada y qué umbral requiere revisión.
- Solo después de la evidencia faltante podrá emitirse una conclusión global. No declarar VINTO_D_I_EXCEPTION_REVIEW=PASS antes de ello.

## 6. Estado operativo

**No se hicieron cambios en producción ni en la VPS.** Esta rama contiene documentación de auditoría y una corrección de comentario sin cambio de comportamiento. El PR debe permanecer en borrador hasta recibir y anexar la evidencia complementaria de Codex.
