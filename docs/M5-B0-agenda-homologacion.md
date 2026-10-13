# M5-B0 · Agenda de sesiones de homologación con VINTO

Las decisiones y sus IDs están en [M5-B0-decisiones-VINTO.md](M5-B0-decisiones-VINTO.md); las respuestas se registran en el [acta](M5-B0-acta-homologacion.md). **No se leen las 47 decisiones una por una:** cada sesión agrupa por tema, se pide primero la **respuesta mínima suficiente** (la que desbloquea el desarrollo) y lo demás queda en seguimiento.
## Alcance de las decisiones «mínimas» de cada sesión
Los **mínimos** de cada sesión (lo que conviene lograr en la reunión de 90 min) permiten iniciar **análisis y preparación técnica no operativa** (borradores de diseño, extensión del exportador en rama de trabajo, planificación de migraciones, pruebas sobre fixtures). **NO autorizan** implementar contratos definitivos, promover catálogos al bundle aprobado, importar a DEV, publicar formularios ni activar Rebobinado.
La implementación completa de **M4-B2** y de **M5-B** exige las **condiciones explícitas de la §5 de la [matriz](M5-B0-decisiones-VINTO.md)** con cada decisión **Aprobada con evidencia** (ver [acta](M5-B0-acta-homologacion.md)). Para M5-B, **H2-10 (liberación de Calidad de la madre) siempre debe resolverse**; solo **H2-11 (flujo de liberación)** depende de lo que H2-10 determine.

Estado de partida: ninguna decisión aprobada. Antes de cada sesión se envía el material con una semana de antelación para que VINTO lleve respuestas y archivos oficiales.

## Sesión 1 · Habilitar P1-10 y P1-29 (clase H1) — 90 min
**Objetivo.** Cerrar lo necesario para promover maestros y contratos (M4-B2) y planificar la activación (M4-B3).
**Participantes recomendados.** Jefatura de Producción de Rebobinado (decide), Supervisión de Rebobinado, un operador de COPASA y uno de TUBETERA, Calidad, Data Baltrek (catálogos), Baltrek TI y un facilitador que registra el acta. Dirección de VINTO solo para firmas/aprobaciones (bloque 5).

| Bloque | Min | Decisiones | Pregunta imprescindible (respuesta mínima suficiente) |
|---|---|---|---|
| 1. Máquinas y alcance | 15 | H1-01, H1-02, H1-03, H1-04 | ¿Qué máquinas existen oficialmente, con qué nombre, y en cuáles se usa P1-10 y P1-29? |
| 2. Turnos | 20 | H1-05…H1-09 | ¿Cuántos turnos, qué horas, desde cuándo, por sector o por máquina, y qué fecha operativa tiene el turno nocturno? ¿Es aceptable reactivar la asignación por turno? |
| 3. Artículos | 15 | H1-10, H1-11, H1-12 | ¿Es oficial la lista de 241 artículos y su relación con máquinas? ¿Es `TB-4001` el mismo ítem en Bobinas y Tubetera? ¿El producto de P1-10 debe coincidir con la línea de OT? |
| 4. P1-10 y P1-29: datos | 25 | H1-13…H1-15, H1-17…H1-20, H1-22 | Número de fardo (manual/central), peso, cardinalidad de rodelas/formatos, unidad del espesor, MRP, fecha de producción |
| 5. Firmas y aprobación | 15 | H1-16, H1-21 | ¿Estas fichas requieren firma/visto bueno para ser válidas? ¿Quién y con qué efecto? |

**Información que VINTO debe llevar:** listado oficial de máquinas y nombres; horarios vigentes de Rebobinado (documento interno o resolución); lista oficial de artículos y su máquina; ejemplos reales de fardo (formato de numeración) y de la ficha P1-29 llena; criterio de pesaje; política de firmas vigente; si existe, la matriz **M1-B2-c1** (evidencia pendiente).
**Decisiones esperadas.**
- *Mínimo de la reunión (análisis/preparación, no autoriza implementar):* H1-01…H1-08, H1-10, H1-11; P1-10: H1-13, H1-15, H1-16; P1-29: H1-17, H1-19, H1-21.
- *Conjunto completo para iniciar M4-B2 (§5 de la matriz):* H1-01, H1-02, H1-03, H1-04, H1-05, H1-06, H1-07, H1-08, H1-10, H1-11 (maestros y vínculos); P1-10: H1-12, H1-13, H1-14, H1-15, H1-16; P1-29: H1-17, H1-19, H1-20, H1-21, H1-22 (más H2-16 si P1-07 entra). H1-18 puede cerrarse como «texto libre aceptado», pero la respuesta debe quedar registrada. H1-09 se necesita para M4-B3.
**Seguimiento posible:** catálogo de tubetes (H1-18/P-01), formato de numeración si «central» (migración), documentos oficiales que VINTO deba ubicar, firma de Dirección.
**Salida:** acta de la sesión. Con los mínimos aprobados se puede preparar M4-B2 (sin implementar contratos definitivos ni promover catálogos); **M4-B2 completo solo inicia cuando el conjunto completo anterior está Aprobado con evidencia.**

## Sesión 2 · Genealogía P1-07, Calidad y consumo (clases H2 y H3) — 90 min
**Objetivo.** Definir qué es la relación madre/hija y las reglas de Calidad antes de diseñar M5-B; confirmar si consumo/inventario están en alcance.
**Participantes recomendados.** Jefatura de Producción (Rebobinado y Bobinas, porque la madre nace en Bobinas), Calidad (decisiones de liberación), operadores/supervisión que llenan P1-07 en COPASA/BELOIT/OVER, Baltrek TI, Dirección para el alcance (H2-01, H3-03).

| Bloque | Min | Decisiones | Pregunta imprescindible |
|---|---|---|---|
| 1. Alcance y orden de fases | 10 | H2-01, H3-03 | ¿Se necesita la genealogía antes de habilitar Rebobinado o después? ¿Inventario y balance de masas están en alcance? |
| 2. La ficha en papel | 25 | H2-02…H2-06, H2-16 | ¿Qué identifica `etiqueta_numero_de_bobina`? ¿Cómo se nombra la bobina madre? ¿Qué es cada `peso_cria_*` y por qué falta el 12? ¿Cuántas hijas puede tener una ficha? ¿En qué máquinas se usa? |
| 3. Madres y relación | 20 | H2-07, H2-08, H2-09, H2-14, H2-15 | ¿Una hija puede tener varias madres? ¿Una ficha consume varias? ¿La madre puede venir de otra máquina/sector? ¿Se corrige una relación? ¿Quién puede ver la genealogía? |
| 4. Calidad | 20 | H2-10, H2-11, H2-12 | ¿Debe estar liberada la madre para rebobinar? ¿Quién libera o rechaza y con qué flujo? ¿Las hijas nacen pendientes? |
| 5. Correlativo y firma | 10 | H2-13, H2-17, H2-18 | ¿Las hijas usan el correlativo de la máquina o uno propio? ¿La ficha requiere firma? |
| 6. Consumo (solo si H3-03 = sí) | 5 | H3-01, H3-02 | Consumo parcial, sobrantes, mermas y qué es `peso` |

**Información que VINTO debe llevar:** fichas P1-07 reales llenas (con y sin «crías»), el procedimiento actual de liberación de Calidad, un ejemplo de bobina madre y sus hijas con etiquetas, y la política de trazabilidad/recall si existe.
**Decisiones esperadas.**
- *Mínimo de la reunión (análisis/preparación, no autoriza implementar):* H2-01…H2-05, H2-07, H2-08, H2-10, H2-12, H2-13.
- *Conjunto completo para iniciar M5-B (§5 de la matriz):* H2-01, H2-02, H2-03, H2-04, H2-05, H2-06, H2-07, H2-08, H2-09, H2-10, H2-12, H2-13, H2-14, H2-15, H2-16, H2-17, H2-18, más los maestros H1-01, H1-05, H1-06, H1-07, H1-08 y H1-10. **H2-10 siempre se resuelve** (aunque la respuesta sea «no se exige liberación»); **H2-11 solo** si H2-10 exige liberación de Calidad, en cuyo caso se aprueba el flujo; si no, se registra «no aplica». H3 puede cerrarse como «fuera de alcance por ahora» (H3-03 debe quedar registrado).
**Seguimiento posible:** flujo de liberación de Calidad (si no existe, es un desarrollo aparte), corrección de relaciones, mermas/inventario, catálogos de producto refilado/destino/formato (P-01).
**Salida:** acta. Con los mínimos aprobados se puede preparar M5-B (diseño, borradores de migración, pruebas sobre fixtures); **M5-B completo solo inicia con el conjunto completo anterior Aprobado con evidencia.**

## Sesión de cierre (opcional, 30 min)
Revisar decisiones **En revisión** o **Rechazadas / requiere rediseño**, confirmar evidencias y firmar el acta consolidada. Solo entonces se actualiza el checklist GO/NO GO (que sigue en **NO GO** hasta que haya aprobaciones).

## Reglas de la reunión
- Una respuesta verbal se registra como **Respondido, sin evidencia** hasta que exista el documento, correo o acta identificable.
- No se aprueba algo porque «ya funciona en la prueba» o porque el formulario legacy lo dice: las pruebas y fixtures solo demuestran viabilidad técnica.
- No se extienden reglas de F3 (correlativo, estado de Calidad inicial) a P1-07 sin aprobación expresa; no se interpretan los `peso_cria_*` como bobinas hijas ni se supone que Calidad liberará las madres.
