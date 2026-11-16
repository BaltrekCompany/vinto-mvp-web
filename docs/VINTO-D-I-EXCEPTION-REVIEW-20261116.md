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


## 7. Segunda revisión D–I — evidencia recibida de Codex (16/11/2026)

**Resultado informado:** `VINTO_D_I_SECOND_REVIEW=PARTIAL`. Las consultas se ejecutaron en transacción `READ ONLY` con `statement_timeout=15s`. No se expusieron IDs, usuarios, actores ni valores individuales. No se ejecutaron escrituras, cambios de permisos, `finish_line`, reinicios ni despliegues.

Esta sección complementa y, cuando corresponda, precisa las clasificaciones preliminares de la sección 2.

| Control | Resultado de segunda revisión | Clasificación | Dictamen actualizado |
| --- | --- | --- | --- |
| Capturas de Calidad por máquina | Se reportan las mismas 21 capturas, distribuidas entre P1-18, P1-22, P1-26 y P1-27 en MP1/MP3, con conteos idénticos a la primera revisión. | COMPORTAMIENTO_ESPERADO | La correspondencia es coherente con la política y con el servicio de Calidad independiente de OT. Para reproducibilidad estricta, repetir el agregado con ambos filtros `assignment_id IS NULL` y `bobbin_id IS NULL`; la consulta resumida recibida solo incluyó el primero. |
| Contradicción de política | La constante ejecutable enumera los cuatro formularios y el diff del PR #185 corrige el docstring contradictorio. | COMPORTAMIENTO_ESPERADO | Corrección textual sin cambio de comportamiento; queda documentada en esta rama. |
| Madres técnicas | Se confirma el perfilamiento previo: seis madres, una BELOIT y cinco COPASA. No se encontraron capturas de Calidad asociadas. | NO_VERIFICABLE | La ausencia de captura no demuestra defecto ni falta de uso. Sigue pendiente determinar disponibilidad y concesiones. |
| Disponibilidad de Calidad para madres | La consulta de elegibilidad no devolvió combinaciones. El acceso directo a `user_machine_form_grant` respondió `permission denied`; no se solicitaron permisos adicionales. | NO_VERIFICABLE | No se puede concluir que falten grants ni que no haya formularios disponibles. Revisar con una fuente autorizada y con el modelo correcto de elegibilidad de madre. |
| Asignaciones y ejecuciones | Se reconfirman 173 asignaciones, 76 ejecuciones y 99 pares lógicos; 99 asignaciones relacionadas, 74 sin ejecución; 76 ejecuciones relacionadas y cero sin asignación. Máximo dos asignaciones por ejecución. | COMPORTAMIENTO_ESPERADO | Mantener relación potencial 1:N y la comparación por OT–máquina–línea baseline v1. No equiparar directamente los IDs de línea operativa y baseline. |
| Ejecuciones finalizadas prolongadas | Las 16 superan 24 h y están entre 24–72 h; no hay casos >72 h. Distribución por máquina y banda: COPASA 3 (48–72); GAMBINI 1 (24–48), 2 (48–72); MP1 1 (24–48), 1 (48–72); MP3 1 (24–48); OMET_I 1 (24–48), 2 (48–72); PERICHUN 2 (48–72); TUBETERA 2 (48–72). | DIFERENCIA_FUNCIONAL | Se confirma duración transcurrida, no tiempo efectivo. Aún falta validar continuidad temporal entre asignaciones, huecos y solapamientos. |
| Ejecuciones abiertas | Tres ejecuciones `in_production`; cada una corresponde a una asignación activa por OT–máquina–línea. Las OTs están `in_progress` y la fecha operativa reportada es 2026-11-16. | COMPORTAMIENTO_ESPERADO (consistencia del snapshot) | Los estados son coherentes con una operación vigente al momento de la consulta. Esto no demuestra actividad física ni justifica cierre automático. |
| Huecos y solapamientos | No calculados en esta ronda. | NO_VERIFICABLE | Sigue pendiente si se necesita demostrar continuidad entre turnos en las duraciones prolongadas. |

### 7.1 Precisión sobre capturas independientes de máquina

El servicio `backend/app/quality/machine_capture_service.py` consulta expresamente capturas con `bobbin_id IS NULL` y `assignment_id IS NULL`. La consulta resumida de la segunda revisión para reproducir las 21 capturas solo filtró `assignment_id IS NULL`.

Por tanto, el resultado informado es coherente con la implementación y con la lista de formularios, pero la evidencia SQL reproducible debe incorporar ambos predicados y el alcance de formularios/máquinas:

```sql
SELECT f.code, m.code, count(*)
FROM vinto_txn.capture c
JOIN vinto_config.form_version fv ON fv.id = c.form_version_id
JOIN vinto_config.form f ON f.id = fv.form_id
JOIN vinto_master.machine m ON m.id = c.machine_id
WHERE fv.area = 'quality'
  AND f.code IN ('VINTO-P1-18','VINTO-P1-22','VINTO-P1-26','VINTO-P1-27')
  AND m.code IN ('MP1','MP3')
  AND c.assignment_id IS NULL
  AND c.bobbin_id IS NULL
GROUP BY f.code, m.code
ORDER BY f.code, m.code;
```

Esta precisión no implica que el conteo 21 sea incorrecto; señala que la consulta resumida entregada no demuestra por sí sola la condición completa de la ruta.

### 7.2 Precisión sobre elegibilidad de madres

La elegibilidad de madres P1-07 no es equivalente a la de bobinas F3:

- `backend/app/quality/mother_policy.py` permite seis formularios (`P1-19`, `P1-20`, `P1-21`, `P1-24`, `P1-25`, `P1-28`) en COPASA, BELOIT y OVER.
- `_published_mother_form_version` en `backend/app/quality/capture_service.py` selecciona la última versión publicada de área `quality` de un formulario activo permitido.
- La excepción de las migraciones 0029/0030 permite la captura de Calidad sobre la madre sin insertar ni exigir una fila en `form_version_machine`; ese catálogo publicado permanece inmutable.
- La autorización de escritura requiere además permiso `quality.capture`, alcance de sector y concesión individual MF-13 activa.

En consecuencia, una consulta que busque exclusivamente vínculos `form_version_machine` puede devolver cero combinaciones sin probar falta de versión elegible para una madre. La comprobación correcta debe considerar el modelo especial de `available_quality_forms` y el motor `app/authz/engine.py`: para Calidad sobre madre se admite la ausencia del vínculo F3 solo si la operación es `QUALITY_BOBBIN_CAPTURE` y `allows_mother_form(machine_code, form_code)`; además, el motor exige que la última versión publicada vigente del formulario (la de mayor versión, de cualquier área) sea de área `quality`, y que exista la concesión activa exacta usuario–máquina–formulario.

La fuente de aplicación de solo lectura es `GET /api/quality/bobbin-forms`, que requiere una sesión autorizada con `quality.capture` y sector concedido. Debe revisarse la respuesta de BELOIT/COPASA sin imprimir tokens ni datos de usuario: `forms[].eligible` cubre los candidatos P1-21/P1-24/P1-25/P1-28 y `bobbin_forms[].eligible` cubre P1-19/P1-20. En conjunto permite comprobar los seis formularios de la política de madre. La función `available_quality_forms` calcula esa disponibilidad y `is_eligible` ejecuta el motor MF-13 real, que verifica permiso, sector, máquina/formulario activos, última versión publicada vigente, excepción de madre y concesión activa exacta. Esto evita consultar directamente `user_machine_form_grant`. Si no hay una sesión autorizada disponible, mantener el resultado `NO_VERIFICABLE`; no solicitar ni aplicar elevación de privilegios a `vinto_app`.

### 7.3 Ejecuciones abiertas y duración

La coincidencia de cada ejecución abierta con una asignación activa y una OT `in_progress`, junto con fecha operativa 2026-11-16, acredita consistencia referencial/operativa del snapshot. No acredita por sí sola que la máquina siga produciendo en el instante posterior ni que la ejecución se deba mantener abierta indefinidamente.

Las 16 ejecuciones finalizadas no superan 72 horas. El dato sigue midiendo tiempo calendario entre `started_at` y `finished_at`. La consulta de intervalos adyacentes de asignación no se ejecutó, por lo que no se puede afirmar que no existan huecos o solapamientos.

## 8. Pendientes exactos para cierre

1. **Reproducir las 21 capturas** con `bobbin_id IS NULL` además de `assignment_id IS NULL`; conservar solo conteos por formulario/máquina.
2. **Madres:** comprobar formularios activos y última versión publicada de área Calidad para las seis combinaciones de máquina/formulario pertinentes, sin exigir `form_version_machine` para la excepción de madre.
3. **Concesiones:** verificar conteos agregados mediante fuente autorizada. El error de permisos sobre `user_machine_form_grant` se registra como límite de acceso; no se elude ni se corrige elevando privilegios.
4. **Continuidad:** calcular huecos/solapamientos entre asignaciones adyacentes OT–máquina–línea para las 16 ejecuciones largas. Informar agregados, sin IDs ni actores.
5. **Regla funcional:** confirmar si la ejecución lógica puede continuar entre turnos, qué condición exige revisión de Supervisión y qué umbral se adopta. No inferir cierre automático por duración.
6. Mantener las tres ejecuciones abiertas sin cambios mientras no exista decisión operativa autorizada.

**Dictamen actualizado:** se pueden dar por conciliados los controles de capturas independientes de OT (sujeto a reproducir el filtro completo), política efectiva y conciliación de asignaciones. Las tres ejecuciones abiertas son consistentes con el snapshot de OTs/asignaciones activas. La auditoría global permanece **OPEN / PARTIAL — NO PASS** por elegibilidad/concesiones de madres y continuidad temporal de las ejecuciones prolongadas.

**Estado operativo:** sin cambios en PostgreSQL, permisos, VPS, servicios o release.
