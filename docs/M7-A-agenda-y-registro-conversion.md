# M7-A · Agenda de validación y formato de registro (Conversión)

**Estado: plantilla. No contiene respuestas, aprobaciones ni fechas.** Las decisiones y sus claves `CV:` están en la [matriz M7-A](M7-A-conversion-decisiones-VINTO.md); el contexto, las dependencias con Rebobinado y las preguntas maestras, en el [índice](M7-A-homologacion-indice.md). Los **estados** y los **criterios de evidencia** son exactamente los de [M5-B0 acta §1 y §2](M5-B0-acta-homologacion.md) y no se redefinen aquí.
Base: `26472007d5dfed89842fa2b5ea2920cdec115d81` (PR #33).

## 1. Reglas de la reunión
- Se pide primero la **respuesta mínima suficiente** de cada bloque; no se leen las 36 decisiones una por una.
- Una respuesta verbal se registra como **Respondido, sin evidencia** hasta que exista el documento, correo o acta identificable (M5-B0 acta §2).
- **No se aprueba algo porque «ya funciona en la prueba»** ni porque el formulario legacy lo dice: los fixtures y los E2E de M6 solo demuestran viabilidad técnica con datos ficticios.
- Responder una **pregunta maestra** (Q1 a Q10) **no equivale por sí solo a aprobar** las decisiones que ayuda a cerrar ni a un GO de piloto: cada decisión se registra y se aprueba con su evidencia.
- No se extienden a Conversión reglas de Rebobinado ni de F3 sin aprobación expresa, ni se interpretan los campos «declarados» de M6 como existencias o consumos oficiales.
- Las duraciones son orientativas; este documento no fija fechas.

## 2. Agenda por bloques
### Sesión 0 · Alcance y estándares transversales (≈ 45 min)
- **Participantes recomendados:** Dirección de VINTO, Jefatura de Producción de Conversión y Rebobinado, Calidad, Baltrek TI y un facilitador que levanta el acta.
- **Preguntas maestras:** Q1, Q4, Q5, Q9.
- **Decisiones:** CV:C-2, CV:C-4, CV:P-2, CV:P-9 (y confirmar `RB:H3-03`).
- **Pregunta imprescindible:** ¿Qué entra en la primera versión? ¿Hay numeración central? ¿Un solo mecanismo de firma? ¿Inventario y balance están en el alcance?
- **Material que VINTO debe llevar:** Política de numeración, política de firmas, definición de alcance.

### Sesión A · Maestros de Conversión (en paralelo con la sesión 1 de Rebobinado) (≈ 90 min)
- **Participantes recomendados:** Jefatura de Producción de Conversión, Supervisión, Data Baltrek (catálogos), Baltrek TI y el facilitador.
- **Preguntas maestras:** Q1, Q2.
- **Decisiones:** CV:C-6, CV:C-7, CV:C-8, CV:C-9, CV:P-11, CV:N-8, CV:N-2.
- **Pregunta imprescindible:** ¿Qué máquinas existen oficialmente y en cuáles se usa cada formulario? ¿Qué turnos, desde cuándo y por sector o por máquina? ¿Son oficiales los artículos y sus relaciones?
- **Material que VINTO debe llevar:** Lista de máquinas, horarios de turnos, lista de artículos y relaciones, recetas si aplican.

### Sesión B · Contratos por formulario (≈ 90 min)
- **Participantes recomendados:** Jefatura de Producción, un operador y un supervisor de cada familia de máquinas, Calidad, Baltrek TI y el facilitador.
- **Preguntas maestras:** Q3, Q4, Q5.
- **Decisiones:** P1-16: CV:C-1. P1-12: CV:P-1, CV:P-5, CV:P-6, CV:P-7. P1-13: CV:N-1, CV:N-4, CV:N-7. P1-11: CV:B-1, CV:B-2, CV:B-3, CV:B-4.
- **Pregunta imprescindible:** Para cada ficha: ¿cuál es la unidad de registro, qué campos y qué obligatoriedad? ¿Qué parte de P1-11 entra en la primera versión?
- **Material que VINTO debe llevar:** Fichas en papel reales y llenas de P1-11, P1-12, P1-13 y P1-16.

### Sesión C · Cálculos y pesos (≈ 60 min)
- **Participantes recomendados:** Jefatura de Producción, Calidad, Data Baltrek y el facilitador.
- **Preguntas maestras:** Q6, Q7.
- **Decisiones:** CV:C-3, CV:C-5, CV:C-11, CV:P-3, CV:P-4, CV:P-8, CV:N-5, CV:N-6, CV:B-5.
- **Pregunta imprescindible:** ¿Qué se calcula, quién lo calcula y con qué fórmula, unidad, decimales y redondeo?
- **Material que VINTO debe llevar:** Fórmulas vigentes, maestro de pesos nominales, criterio de pesaje.

### Sesión D · Integración: bobinas, Calidad y genealogía (conjunta con la sesión 2 de Rebobinado) (≈ 60 min)
- **Participantes recomendados:** Jefatura de Producción de Bobinas, Rebobinado y Conversión, Calidad, Baltrek TI y el facilitador.
- **Preguntas maestras:** Q8.
- **Decisiones:** CV:N-3, CV:B-6, CV:P-10 (con `RB:H2-02`, `RB:H2-03`, `RB:H2-10`, `RB:H2-11`, `RB:H2-12`).
- **Pregunta imprescindible:** ¿Se exige una bobina real y liberada para consumir? ¿Cómo se identifica y qué pasa con una rechazada?
- **Material que VINTO debe llevar:** Procedimiento de liberación de Calidad, flujo físico de bobinas.

### Sesión Cierre · Revisión y firma del acta (opcional) (≈ 30 min)
- **Participantes recomendados:** Quienes aprueban por VINTO y el facilitador.
- **Preguntas maestras:** Q10.
- **Decisiones:** CV:C-10 y todas las decisiones En revisión o Rechazadas.
- **Pregunta imprescindible:** Confirmar evidencias, resolver decisiones En revisión o Rechazadas y firmar el acta
- **Material que VINTO debe llevar:** —.

Las sesiones 0 y A destraban la mayor cantidad de decisiones PF; las sesiones B a D, el resto. El orden puede ajustarse si VINTO responde varias preguntas maestras en un mismo bloque.

## 3. Formato breve de registro
Una fila por **cambio de estado** (el historial se conserva; no se borran filas). Los estados son los de M5-B0 acta §1: Pendiente, Respondido sin evidencia, En revisión, Aprobado, Rechazado / requiere rediseño.

**Cabecera de cada sesión:** sesión, fecha y hora, participantes (nombre, cargo, rol), quién tiene autoridad para aprobar, facilitador, y versión del material enviado previamente (commit del paquete).

| ID | Estado | Respuesta de VINTO (literal o resumen fiel) | Alternativa elegida | Responsable que respondió | Fecha | Evidencia (tipo, referencia, SHA-256 si aplica) | Aprobó (nombre y cargo) | Decisiones afectadas | Pendientes / acciones |
|---|---|---|---|---|---|---|---|---|---|
| CV:C-1 | Pendiente | | | | | | | | |
| CV:C-2 | Pendiente | | | | | | | | |
| CV:C-3 | Pendiente | | | | | | | | |
| CV:C-4 | Pendiente | | | | | | | | |
| CV:C-5 | Pendiente | | | | | | | | |
| CV:C-6 | Pendiente | | | | | | | | |
| CV:C-7 | Pendiente | | | | | | | | |
| CV:C-8 | Pendiente | | | | | | | | |
| CV:C-9 | Pendiente | | | | | | | | |
| CV:C-10 | Pendiente | | | | | | | | |
| CV:C-11 | Pendiente | | | | | | | | |
| CV:P-1 | Pendiente | | | | | | | | |
| CV:P-2 | Pendiente | | | | | | | | |
| CV:P-3 | Pendiente | | | | | | | | |
| CV:P-4 | Pendiente | | | | | | | | |
| CV:P-5 | Pendiente | | | | | | | | |
| CV:P-6 | Pendiente | | | | | | | | |
| CV:P-7 | Pendiente | | | | | | | | |
| CV:P-8 | Pendiente | | | | | | | | |
| CV:P-9 | Pendiente | | | | | | | | |
| CV:P-10 | Pendiente | | | | | | | | |
| CV:P-11 | Pendiente | | | | | | | | |
| CV:N-1 | Pendiente | | | | | | | | |
| CV:N-2 | Pendiente | | | | | | | | |
| CV:N-3 | Pendiente | | | | | | | | |
| CV:N-4 | Pendiente | | | | | | | | |
| CV:N-5 | Pendiente | | | | | | | | |
| CV:N-6 | Pendiente | | | | | | | | |
| CV:N-7 | Pendiente | | | | | | | | |
| CV:N-8 | Pendiente | | | | | | | | |
| CV:B-1 | Pendiente | | | | | | | | |
| CV:B-2 | Pendiente | | | | | | | | |
| CV:B-3 | Pendiente | | | | | | | | |
| CV:B-4 | Pendiente | | | | | | | | |
| CV:B-5 | Pendiente | | | | | | | | |
| CV:B-6 | Pendiente | | | | | | | | |

## 4. Resumen de avance (se actualiza después de cada sesión)
| Incremento | Decisiones requeridas (ver índice §9) | Aprobadas con evidencia | Estado |
|---|---|--:|---|
| M7-B Maestros | CV:C-6, CV:C-7, CV:C-8, CV:C-9, CV:P-11, CV:N-8 (+ condicionales) | 0 | **NO GO** |
| M7-C Contratos de captura | CV:C-1, CV:P-1, CV:P-7, CV:N-1, CV:N-4, CV:N-7, CV:B-1 (+ condicionales) | 0 | **NO GO** |
| M7-D Reglas de cálculo | CV:C-3, CV:C-5, CV:P-4, CV:N-5, CV:N-6, CV:P-8, CV:B-5, CV:C-11, CV:P-3 | 0 | **NO GO** |
| M7-E Bobinas y genealogía | CV:N-3, CV:B-6, CV:P-10 + `RB:H2` requeridas | 0 | **NO GO** |
| M7-F Calidad e inventario | `RB:H3-01` a `RB:H3-03` | 0 | **NO GO** |
| M7-G Piloto aislado | Todas las PF aplicables + checklist + aprobación explícita | 0 | **NO GO** |
| M7-H Activación controlada en DEV | M7-G aprobado; todas las PF **y OP** aplicables; resolución formal de VINTO para cada LT diferida; M7-D / M7-E / M7-F si están en alcance; checklist técnico; autorización expresa; PRs de activación revisados | 0 | **NO GO** |

## 5. Documentos y catálogos solicitados
La lista está en el [índice §10](M7-A-homologacion-indice.md). Se registra aquí su estado de entrega **solo cuando VINTO los aporte**; hoy todos están **por solicitar**.

## 6. Reglas de uso
- Una fase pasa a **GO** solo cuando **todas** sus decisiones requeridas están **Aprobadas con evidencia** y el checklist técnico correspondiente está completo. Para M7-H se exigen además las OP aplicables y, por cada decisión LT diferida, una **resolución formal de VINTO** (no aplicabilidad o diferimiento, responsable, riesgo aceptado y condición de resolución posterior): estar clasificada como LT no la hace dejar de ser bloqueante.
- La columna «Decisiones afectadas» registra qué otras decisiones se ven afectadas por una respuesta (si cambia otra, la afectada vuelve a **En revisión**) y «Pendientes / acciones» las tareas abiertas; en la plantilla ambas están **vacías**.
- Si una decisión aprobada cambia otra, la afectada vuelve a **En revisión** con una fila nueva.
- Este registro **no autoriza** por sí solo activar Conversión o Rebobinado, importar a DEV ni publicar formularios: esos pasos requieren sus PR revisados y la aprobación explícita de VINTO.
