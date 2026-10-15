# HOM-01A · Consolidación de decisiones para el GO-LIVE integral (Bobinas, Rebobinado, Conversión)

**Estado: documental. Ninguna decisión está aprobada.** Este documento no implementa nada, no cambia código, migraciones, `backend/seed_data`, sectores operativos, políticas de formularios, roles, concesiones ni `quality_release`, no activa Q-LIB y no fija fechas. **No redacta preguntas nuevas**: consolida, en una sola matriz ejecutiva, las decisiones ya formuladas en [PB-H0](PB-H0-homologacion-indice.md) (Bobinas, `BO:`), [M5-B0](M5-B0-decisiones-VINTO.md) (Rebobinado y genealogía, `RB:`) y [M7-A](M7-A-homologacion-indice.md) (Conversión, `CV:`), más el E2E técnico [QA-3F-01](QA-3F-01-integracion-tres-frentes.md) y el diagnóstico [PILOTO-BOBINAS](PILOTO-BOBINAS-brechas-y-GO-NOGO.md). **No inventa respuestas, aprobaciones ni fechas.**

Base: `main` en `ec185c036220dd788e47eb89ad936175ca65dba6` (merge del PR #51, QA-3F-01).

## 0. Qué resuelve este documento y qué no

**Resuelve:**
- Una vista única de las 135 decisiones pendientes (`52 BO: + 47 RB: + 36 CV:`) organizada por **tema ejecutivo**, sin repetir tres veces una pregunta compartida entre sectores.
- Qué está bloqueado, por qué, y con qué evidencia se desbloquea.
- Un conjunto de puertas objetivas (G1–G8) para decidir GO/NO GO del lanzamiento integral.

**No resuelve ni autoriza:**
- Ninguna decisión pasa de **Pendiente**. Una prueba E2E que pasa (incluido QA-3F-01, 75/75) o un fixture que funciona **no es evidencia** (criterio de [M5-B0 acta §2](M5-B0-acta-homologacion.md), reutilizado sin cambios por los tres paquetes).
- No activa Rebobinado ni Conversión: `backend/app/sectors.py` (`DEFAULT_OPERATIONAL_SECTORS = (SECTOR_BOBINAS,)`) y `backend/app/capture_service.py` (`CENTRAL_FORM_CODES = frozenset({"VINTO-P1-06"})`) siguen intactos, verificado contra el código en este mismo incremento.
- No activa Q-LIB (`backend/app/quality/capture_service.py`: `ENABLED_BOBBIN_CANDIDATE_FORM_CODES = frozenset()`, vacío, verificado).
- No sustituye la autorización explícita de VINTO exigida en cada uno de los tres paquetes.

## A. Alcance propuesto del primer lanzamiento conjunto

El mandato comercial es **no negociable**: el primer GO-LIVE debe permitir **Bobinas, Rebobinado y Conversión**, con **Calidad transversal**. Este documento parte de ese mandato y organiza lo que falta para cumplirlo; **no lo cuestiona ni lo reduce**.

**Lo que ya existe como evidencia técnica (no industrial):**
- 25/25 formularios con cobertura técnica nominal (INT-01, INT-02A, INT-02B).
- [QA-3F-01](QA-3F-01-integracion-tres-frentes.md) demuestra que los tres frentes y Calidad pueden operar **simultáneamente, en una misma instancia y base**, sin interferirse entre sí (75/75 comprobaciones), con la habilitación de los tres sectores **exclusiva de un proceso de prueba efímero** (`E2E_3F=on`) y una segunda fase que confirma que la configuración real —solo Bobinas— sigue intacta.
- **QA-3F-01 no es una homologación industrial.** No aprueba ningún contrato de P1-10 ni P1-16, no fija maestros, turnos, correlativos ni política de Calidad. Demuestra viabilidad técnica de que los tres sectores **pueden coexistir**, no que estén listos para operar con datos y reglas reales.

**Lo que falta para que el alcance comercial sea un alcance operativo real:**
1. VINTO debe confirmar formalmente qué formularios y qué máquinas entran por frente en el primer GO-LIVE (hoy: Bobinas MP1/MP3 con F3/P1-06/P1-19/P1-20; Rebobinado y Conversión sin ningún alcance confirmado — ver §B.1, §C.1, §D.1).
2. Las tres homologaciones (`BO:`, `RB:`, `CV:`) deben tener sus decisiones bloqueantes **Aprobadas con evidencia**, no solo «respondidas».
3. Calidad y genealogía deben resolver, como mínimo, quién libera o rechaza una bobina y si esa liberación condiciona el consumo entre sectores (§E).
4. Un entorno aislado con respaldo y restauración validados, y un UAT firmado — hoy ninguno existe para ningún frente.
5. Autorización escrita de VINTO para activar cada sector (cambio de código revisado en `sectors.py` y `capture_service.py`; nunca una variable de entorno).

**Este documento no decide el alcance; lo presenta para que VINTO lo confirme (§6, puerta G1).**

## B. Decisiones obligatorias antes de habilitar Bobinas

Fuente: [PB-H0](PB-H0-homologacion-indice.md) (52 decisiones `BO:`, todas Pendiente). La puerta 2 de PB-H0 (GO de diseño de Q-LIB) exige 11 decisiones `BO:CAL` **Aprobadas con evidencia**; la puerta 3 (GO del piloto) exige el [checklist de 18 condiciones](PILOTO-BOBINAS-brechas-y-GO-NOGO.md#10-checklist-go--no-go-del-piloto). Responsables propuestos: JP, CAL, DB, TI, DIR (roles por confirmar por VINTO, §G).

| # | Tema ejecutivo | IDs originales | Frente | Pregunta resumida | Estado real | Resp. | Evidencia requerida | Desbloquea | Prioridad | Dependencias con otros frentes |
|---|---|---|---|---|---|---|---|---|---|---|
| B1 | Calidad: mediciones obligatorias y límites | BO:CAL-01, BO:CAL-02, BO:CAL-03, BO:CAL-04, BO:CAL-12 | Bobinas | ¿Qué mediciones son obligatorias, cuántas, con qué frecuencia, qué límites por magnitud/artículo y qué excepciones existen? | Pendiente | CAL, JP | Procedimiento de liberación y de muestreo; especificación de laboratorio con límites y unidades | **Q-LIB** (bloqueante) | **Imprescindible** (no postergable: Q-LIB no se diseña sin esto) | — |
| B2 | Calidad: autoridad, separación, motivo y reversión | BO:CAL-06, BO:CAL-07, BO:CAL-08, BO:CAL-09 | Bobinas | ¿Quién mide puede decidir? ¿El motivo es obligatorio? ¿Se puede revertir una decisión y bajo qué condición? | Pendiente | CAL, DIR | Política escrita de separación de funciones, motivo y reversión | **Q-LIB** | **Imprescindible** | — |
| B3 | Contratos de captura P1-19 y P1-20 | BO:CON-03, BO:CON-04, BO:CON-06, BO:CON-07, BO:CON-08 | Bobinas | ¿Son oficiales los campos de humedad y propiedades físicas? ¿Se calcula y muestra la humedad derivada y los promedios? ¿Cuál es la denominación oficial de las posiciones? | Pendiente | CAL | Ficha de laboratorio real y llena; fórmulas con ejemplo numérico | Homologación `BO:` (condición 3 del checklist del piloto) | **Imprescindible** | — |
| B4 | Operación: alcance, autoridad y usuarios del piloto | BO:OPS-01, BO:OPS-02, BO:OPS-03, BO:OPS-11, BO:OPS-12 | Bobinas | ¿Qué máquinas y turnos entran? ¿Quién aprueba el alcance? ¿Quiénes son los usuarios nominales? | Pendiente | DIR, JP | Documento de alcance firmado; lista nominal de usuarios | Habilita el resto de las sesiones de homologación (PM-1) | **Imprescindible** (es la puerta de entrada de todo lo demás) | — |
| B5 | Operación: reportes | BO:OPS-04, BO:OPS-05 | Bobinas | ¿Qué reportes exige el piloto y cuáles se excluyen formalmente? Si «bobinas por camión» entra, ¿de dónde sale el dato? | Pendiente | DIR, JP | Lista de reportes exigidos/excluidos; ejemplo real del reporte | Condición 13 del checklist | **Condicional** (VINTO puede excluir formalmente; la exclusión no sustituye ninguna condición técnica) | — |
| B6 | Operación: conectividad y Expertus | BO:OPS-06, BO:OPS-07, BO:OPS-10 | Bobinas | ¿Se exige operación sin conexión? ¿Con qué garantías? ¿El piloto requiere Expertus? | Pendiente | DIR, JP, TI | Decisión formal de conectividad y de alcance de Expertus | Condición 1 del checklist | **Condicional** (decisión de alcance que VINTO puede excluir formalmente) | — |
| B7 | Operación: corrección de capturas cerradas | BO:OPS-08, BO:OPS-09 | Bobinas | ¿Quién corrige una captura cerrada, hasta cuándo y con qué aprobación? Si no hay corrección, ¿cuál es la política temporal? | Pendiente | JP, CAL, TI | Política escrita, o política temporal con responsable y procedimiento de incidencias | Condición 14 del checklist (riesgo operativo) | **Condicional, pero no omitible**: una aceptación genérica de riesgo no basta; exige política temporal documentada | — |
| B8 | Operación: entorno, respaldo, seguridad y auditoría | BO:OPS-13, BO:OPS-14, BO:OPS-17, BO:OPS-18 | Bobinas | ¿Dónde se aloja el entorno y quién lo opera? ¿Quién autoriza respaldo/restauración? ¿Qué política de seguridad y de consulta de auditoría exige VINTO? | Pendiente | DIR, TI, CAL | Decisión de alojamiento y operación; procedimiento de respaldo firmado; política de seguridad | **PB-ENV** (bloqueante); condiciones 10, 16 del checklist (técnicas, no omitibles) | **Imprescindible** (condición técnica/seguridad: no se omite ni se sustituye por aceptar un riesgo) | — |
| B9 | Operación: UAT y vistas de Seguimiento | BO:OPS-15, BO:OPS-16, BO:OPS-19 | Bobinas | ¿Quiénes participan en el UAT, con qué casos y criterio de aprobación? ¿Qué vistas adicionales de Seguimiento/Calidad requiere cada rol? | Pendiente | JP, CAL, DIR | Guion de UAT acordado; criterio de aceptación firmado; definición de vistas adicionales | **UAT** (bloqueante); condición 15 del checklist | **Imprescindible** (UAT); los indicadores adicionales de `BO:OPS-19` son condicionales (los controles mínimos ya se derivan de B2) | — |

**Nota de alcance.** Las 13 decisiones `BO:MAE-*` (máquinas, artículos, turnos, correlativo, registros legacy) y las 3 decisiones `BO:CON-01/02/05` (contratos F3, P1-06 y unidades) — 16 en total — **no se repiten aquí**: están en los temas transversales §E porque Rebobinado y Conversión comparten exactamente la misma pregunta (turnos, máquinas, maestros, unidades, correlativo). Las 3 decisiones `BO:CAL-05/10/11` (autoridad y efecto de la liberación) tampoco se repiten: están en §E1 porque Rebobinado y Conversión preguntan lo mismo sobre si el consumo exige una bobina liberada. En total, 19 de las 52 decisiones `BO:` están en §E; las 33 restantes están en B1–B9.

## C. Decisiones obligatorias antes de habilitar Rebobinado

Fuente: [M5-B0](M5-B0-decisiones-VINTO.md) (47 decisiones `RB:`, todas Pendiente). `M4-B2` (maestros y contratos) es un prerrequisito siempre; `M5-B` (genealogía P1-07) lo es **solo si** `RB:H2-01` —todavía sin resolver— establece que la genealogía se implementa **antes** de habilitar Rebobinado. Si `RB:H2-01` establece que se implementa **después**, `M4-B3` puede activarse sin `M5-B` concluido, siempre con el alcance transitorio y sus limitaciones registrados con autorización formal de VINTO (ver C4).

| # | Tema ejecutivo | IDs originales | Frente | Pregunta resumida | Estado real | Resp. | Evidencia requerida | Desbloquea | Prioridad | Dependencias con otros frentes |
|---|---|---|---|---|---|---|---|---|---|---|
| C1 | Máquinas específicas de Rebobinado | RB:H1-02, RB:H2-16 | Rebobinado | ¿Es oficial el nombre «Tubetera»? ¿En qué máquinas se usa P1-07? | Pendiente | JP | Nombre oficial por escrito; tabla formulario × máquina | M4-B2 | **Imprescindible** | Comparte formato con §E.2 (máquinas) |
| C2 | Contrato P1-10: coincidencia con la línea de OT | RB:H1-12 | Rebobinado | ¿El producto de P1-10 debe coincidir con el artículo de la línea de OT? | Pendiente | JP | Regla escrita | M4-B2 | **Imprescindible** | — |
| C3 | Contrato P1-29: cardinalidad, catálogo, unidad, MRP y fecha | RB:H1-17, RB:H1-18, RB:H1-19, RB:H1-20, RB:H1-22 | Rebobinado | ¿Rodelas y formatos son obligatorios y con qué máximo? ¿Catálogo de tubetes? ¿El espesor es mm o kg? ¿El MRP es digitado o generado? ¿La fecha es manual u operativa? | Pendiente | JP, CAL, TI | Cardinalidad, catálogo o aceptación de texto libre, unidad confirmada, decisión de MRP y de fecha | M4-B2 | **Imprescindible** (H1-18 puede cerrarse como «texto libre aceptado», pero debe quedar registrado) | — |
| C4 | Genealogía P1-07: orden de fases e identificación de la madre | RB:H2-01, RB:H2-02, RB:H2-03 | Rebobinado | ¿La genealogía P1-07 se implementa **antes** de habilitar Rebobinado o en una **fase posterior**? ¿Qué identifica `etiqueta_numero_de_bobina`? ¿Cómo se identifica la madre en la ficha? | Pendiente | DIR, JP, TI | Decisión de alcance y de orden de fases; aclaración escrita; método de identificación aprobado | Decide si `M5-B` es prerrequisito de `M4-B3` o puede seguirla | **`RB:H2-01` es imprescindible resolverla explícitamente — sin presumir «antes» ni «después»: es una decisión de VINTO, no de Baltrek.** Si VINTO decide «antes», `M5-B` completo (C5–C7) es prerrequisito de activar Rebobinado. Si decide «después», Rebobinado puede activarse sin genealogía implementada **solo** con el alcance transitorio, sus limitaciones y la autorización formal de esa implementación posterior registrados por escrito (nunca un diferimiento que decida Baltrek por su cuenta) | — |
| C5 | Genealogía P1-07: hijas y cardinalidad | RB:H2-04, RB:H2-05, RB:H2-06, RB:H2-18 | Rebobinado | ¿Cada `peso_cria_*` es una bobina hija con identidad propia? ¿Cuántas hijas admite una ficha? ¿Cómo se corrige la numeración sin `peso_cria_12`? ¿Cómo se identifica cada salida para reintentos? | Pendiente | JP, TI | Respuesta y cardinalidad escritas; diseño técnico aprobado (`output_key`) | M5-B | **Condicionada por `RB:H2-01` (C4):** si la genealogía entra antes de habilitar Rebobinado, esta decisión es imprescindible para `M5-B`; si entra en una fase posterior, queda pendiente de esa fase, nunca descartada ni postergada por decisión del equipo técnico | — |
| C6 | Genealogía P1-07: relación madre-hija y trazabilidad | RB:H2-07, RB:H2-08, RB:H2-09, RB:H2-14, RB:H2-15 | Rebobinado | ¿Una hija puede tener varias madres? ¿Una ficha consume una o varias? ¿La madre puede venir de otro sector/máquina? ¿Se corrige una relación? ¿Qué alcance de lectura tiene la genealogía? | Pendiente | JP, CAL, TI | Reglas escritas de cardinalidad, restricciones de sector/máquina, política de corrección y de alcance de lectura | M5-B | **Condicionada por `RB:H2-01` (C4)**, igual que C5 | Relación física con Bobinas (madre) y con Conversión (consumo, §E.1) |
| C7 | Genealogía P1-07: estado de Calidad de las hijas | RB:H2-12 | Rebobinado | ¿Las hijas heredan el estado de Calidad de la madre o nacen `pending` y pasan por Calidad propia? | Pendiente | CAL | Decisión escrita | M5-B | **Condicionada por `RB:H2-01` (C4)**, igual que C5; no se extiende la regla de F3 a P1-07 sin aprobación en ningún caso | Relacionada con §E.1 (liberación de la madre) |
| C8 | Consumo e inventario (fase posterior) | RB:H3-01, RB:H3-03 | Rebobinado | ¿Se registra consumo parcial y sobrante de la madre? ¿Inventario y balance de masas están en el alcance de VINTO? | Pendiente | JP, DIR | Decisión de alcance con evidencia | H3+ (fase posterior, sin ID) | **Condicional al alcance que confirme VINTO — no se posterga por decisión unilateral del equipo técnico** | Misma pregunta que CV:C-3 (§D1), CV:N-5 (§D3) y CV:P-10 (§E1): `RB:H3-03` decide si inventario y balance existen para los tres frentes |
| C9 | Catálogos y presentación posteriores | RB:P-01, RB:P-04 | Rebobinado | ¿Los catálogos de tubete/destino/formato son catálogo o texto libre? ¿Los reportes usan fecha operativa o de calendario? | Pendiente | JP, DB | Respuesta registrada o datos oficiales | Mejora posterior (no bloquea M4-B2 ni M5-B) | **Posible fase posterior** (clasificación ya establecida en M5-B0, no una demora introducida aquí) | — |

**Nota de alcance.** 22 de las 47 decisiones `RB:` (máquinas, turnos, maestros de artículos, numeración, peso/unidad/decimales, firmas, y la autoridad de liberación H2-10/H2-11) están en §E porque son **la misma pregunta** que Bobinas y/o Conversión formulan por separado.

## D. Decisiones obligatorias antes de habilitar Conversión

Fuente: [M7-A](M7-A-homologacion-indice.md) (36 decisiones `CV:`, todas Pendiente). La clasificación PF/OP/LT es la **propuesta condicional** de M7-A (no una decisión): **PF** bloquea el piloto; **OP** no bloquea el piloto pero bloquea el uso operativo real (`M7-H`); **LT** puede resolverse después, pero **sigue bloqueando la activación** sin una resolución formal de VINTO.

| # | Tema ejecutivo | IDs originales | Frente | Pregunta resumida | Estado real | Resp. | Evidencia requerida | Desbloquea | Prioridad | Dependencias con otros frentes |
|---|---|---|---|---|---|---|---|---|---|---|
| D1 | P1-16 (merma): unidad de registro y cálculo | CV:C-1, CV:C-3 | Conversión | ¿P1-16 es la ficha legacy con correlativo y total, o una pesada por registro? ¿Cuál es la fórmula del total y quién la calcula? | Pendiente | JP, CAL | Ficha en papel vigente; fórmula con ejemplo numérico | M7-C, M7-D | **Imprescindible** (C-1 es PF; C-3 depende de C-1) | — |
| D2 | P1-12 (pallet): unidad de registro, cardinalidad y balances | CV:P-1, CV:P-7, CV:P-8 | Conversión | ¿P1-12 es la ficha diaria de 37 campos o un pallet por envío? ¿Un pallet por ficha o varios agrupados? ¿Se capturan los balances y quién calcula los 8 campos calculados? | Pendiente | JP, CAL | Ficha en papel vigente; decisión de cardinalidad; decisión y fórmulas de balances | M7-C, M7-D | **Imprescindible** (P-1 y P-7 son PF; P-8 es PF si VINTO exige balances en la primera versión) | — |
| D3 | **P1-13 — Producción diaria de servilletas y especiales**: unidad de registro, identidad de la bobina declarada y cálculo | CV:N-1, CV:N-3, CV:N-4, CV:N-5, CV:N-7 | Conversión | ¿Una ficha por turno (con la bobina, los insumos y la producción) o capturas separadas? ¿Cómo se identifica la bobina declarada como consumida y se evita el doble conteo con P1-11 (Consumo de bobinas)? ¿Qué es «ingreso»? ¿Quién calcula el saldo? ¿El pallet va en la misma ficha? **El contrato candidato actual (8 campos) no es el contrato definitivo**; la denominación «Producción diaria de servilletas y especiales» es la del formulario legacy (31 campos), que VINTO debe homologar o corregir | Pendiente | JP, TI, CAL | Ficha en papel vigente; decisión de identidad de bobina; fórmula de saldo | M7-C, M7-D, M7-E | **Imprescindible** (N-1, N-4, N-7 son PF; N-3 es PF si VINTO exige una bobina real para el piloto; N-5 es OP) | N-3 es la misma pregunta que §E.1 (identidad de bobina y Calidad) |
| D4 | **P1-11 — Consumo de bobinas**: rodelas, insumos y producción declarados | CV:B-1, CV:B-2, CV:B-3, CV:B-4 | Conversión | ¿Cuántas bobinas por posición y turno? ¿Estructura de las rodelas declaradas? ¿Insumos y cuchilla en la misma ficha? ¿La producción (bandejas, rollos, pesos) pertenece a P1-11 o a P1-12? **El contrato candidato actual (grupo repetible mínimo 1) no es el contrato definitivo**; la denominación «Consumo de bobinas» es la del formulario legacy (61 campos), que VINTO debe homologar o corregir | Pendiente | JP | Ficha en papel vigente; decisiones escritas de estructura | M7-C | **B-1 Imprescindible (PF); B-2/B-3/B-4 posible fase posterior (LT) — clasificación de M7-A, no decisión unilateral del equipo técnico: siguen bloqueando `M7-H` sin una resolución formal de VINTO** | — |

**Nota de alcance.** 22 de las 36 decisiones `CV:` (máquinas, turnos, maestros, numeración, peso/unidad/decimales, firmas, registros legacy, y la integración con Calidad/genealogía `CV:B-6`/`CV:P-10`) están en §E.

## E. Dependencias transversales de Calidad y genealogía

**Una sola respuesta organizacional sirve a varios sectores.** Los estados de `BO:`, `RB:` y `CV:` **no cambian entre sí**: una respuesta de un sector no aprueba nada de otro. Esta sección existe para que VINTO **no responda la misma pregunta tres veces**.

| # | Tema ejecutivo | IDs originales | Frentes | Pregunta resumida | Estado real | Resp. | Evidencia requerida | Desbloquea | Prioridad |
|---|---|---|---|---|---|---|---|---|---|
| E1 | Autoridad y política de liberación/rechazo de Calidad; consumo entre sectores | BO:CAL-05, BO:CAL-10, BO:CAL-11, RB:H2-10, RB:H2-11, CV:B-6, CV:P-10 | Bobinas + Rebobinado + Conversión | ¿Quién tiene autoridad para liberar/rechazar una bobina? ¿Liberar o rechazar es solo informativo o condiciona Rebobinado/Conversión? ¿Cómo se trata una bobina rechazada? ¿El consumo (Rebobinado, Conversión) exige una bobina liberada? | Pendiente | CAL, DIR, JP | Organigrama o designación formal de la autoridad; política escrita de efectos y de tratamiento de rechazo | **Q-LIB** (bloqueante, BO), **M5-B** (siempre vía H2-10, RB), **M7-E/M7-F** (CV, si la política exige liberación) | **Imprescindible — no postergable.** `RB:H2-10` siempre debe resolverse aunque la respuesta sea «no se exige liberación»; esta decisión **no puede clasificarse como postergable por decisión unilateral del equipo técnico** |
| E2 | Máquinas y tabla formulario × máquina | BO:MAE-01, RB:H1-01, RB:H1-03, RB:H1-04, CV:C-6, CV:P-11, CV:N-8 | Bobinas + Rebobinado + Conversión | ¿Cuáles son las máquinas oficiales de cada sector y en cuáles se usa cada formulario? | Pendiente | JP, DB | Lista oficial de máquinas con código técnico y nombre visible; tabla formulario × máquina | PB-MAESTROS (BO), M4-B2 (RB), M7-B (CV) | **Imprescindible** |
| E3 | Maestros de artículos, pesos nominales y recetas | BO:MAE-02, BO:MAE-03, BO:MAE-04, RB:H1-10, RB:H1-11, RB:P-03, CV:C-9, CV:C-11, CV:P-3, CV:N-2 | Bobinas + Rebobinado + Conversión | ¿Son oficiales los artículos y sus relaciones con las máquinas? ¿Es obligatorio el peso nominal? ¿De dónde sale el gramaje? ¿Se usan recetas? | Pendiente | DB, JP | Lista oficial de artículos y relaciones; maestro de pesos nominales si aplica; recetas con vigencia si se usan | PB-MAESTROS (BO, B), M4-B2 (RB), M7-B (CV) | **Imprescindible** (la lista de máquinas y artículos bloquea; peso nominal y recetas son condicionales a si son obligatorios) |
| E4 | Turnos y fecha operativa | BO:MAE-05, BO:MAE-06, BO:MAE-07, BO:MAE-08, RB:H1-05, RB:H1-06, RB:H1-07, RB:H1-08, RB:H1-09, CV:C-7, CV:C-8, CV:P-6 | Bobinas + Rebobinado + Conversión | ¿Cuáles son los horarios de cada sector, su vigencia y zona horaria? ¿Por sector o por máquina? ¿La fecha operativa del turno nocturno es la del día en que empieza? ¿Es aceptable reactivar la asignación por turno? | Pendiente | JP, DB | Horarios firmados por Jefatura de Producción; vigencia y zona reales | PB-MAESTROS (BO), M4-B2 (RB), M7-B (CV) | **Imprescindible.** Si el horario resulta «por máquina» en cualquier sector, cambia el modelo de datos para los tres |
| E5 | Numeración / correlativo (bobinas, fardo, pallet, merma) | BO:MAE-09, BO:MAE-10, BO:MAE-11, BO:MAE-12, RB:H1-13, RB:H1-14, RB:H2-13, CV:C-2, CV:P-2 | Bobinas + Rebobinado + Conversión | ¿Qué periodo representa la gestión del correlativo de F3 (01/04–31/03 frente a un cierre al 31/12 sin documentar)? ¿Existen correlativos de fardo, pallet o merma, manuales o centrales? ¿Las hijas de genealogía usan el correlativo de F3 o uno propio? | Pendiente | JP, TI, DIR | Acta que precise el periodo del correlativo de F3; decisión escrita y ejemplo real de cada numeración nueva | GO piloto condición 4 (BO); M4-B2 si es central (RB); M7-C si es central (CV) | **Imprescindible para F3** (BO:MAE-09 a 12, con la discrepancia sin resolver sobre el periodo del correlativo); **condicional** para las numeraciones nuevas (central solo si VINTO lo decide; entonces exige migración propia) |
| E6 | Estándar de peso, unidad y decimales | BO:CON-01, BO:CON-02, BO:CON-05, RB:H1-15, RB:P-02, RB:H3-02, CV:C-5, CV:P-4, CV:P-5, CV:N-6, CV:B-5 | Bobinas + Rebobinado + Conversión | ¿Cuáles son las unidades oficiales de cada magnitud (humedad, propiedades físicas, pesos de fardo/pallet/bobina)? ¿Qué decimales y rangos? | Pendiente | CAL, DB, JP | Especificación de laboratorio o de producción con unidad, decimales y rango por magnitud | PB-MAESTROS/Q-LIB (BO), M4-B2 (RB), M7-D (CV) | **Imprescindible para los contratos ya candidatos** (BO, F3/P1-06/P1-20); **condicional** para los que aún no tienen pantalla publicada |
| E7 | Firmas y aprobación de fichas | RB:H1-16, RB:H1-21, RB:H2-17, CV:C-4, CV:P-9 | Rebobinado + Conversión | ¿Las fichas P1-10, P1-29, P1-07, P1-16 y P1-12 requieren firma u otra aprobación para ser válidas? ¿Qué son «grupo» y «encargado de turno»? | Pendiente | JP, DIR | Mecanismo definido, o «no aplica» firmado, por ficha | M4-B2 (RB), M7-C (CV) | **Condicional** (PF solo si VINTO exige firma; de lo contrario, «no aplica» firmado) |
| E8 | Registros legacy de navegador | BO:MAE-13, CV:C-10 | Bobinas + Conversión | ¿Qué se hace con los registros que quedaron en `localStorage` de los navegadores (`vinto-p1-records`)? | Pendiente | DIR, TI | Decisión escrita | GO piloto condición 12 (BO); M7-G/M7-H (CV) | **Imprescindible** (condición técnica: «ninguna pantalla del piloto muestra datos que no vengan del backend»; los datos no se borran sin decisión) |

## F. Documentos oficiales que VINTO debe proporcionar

Consolidado de [PB-H0 índice §9](PB-H0-homologacion-indice.md#9-evidencias-que-vinto-debe-aportar), la agenda de [M5-B0](M5-B0-agenda-homologacion.md) y [M7-A índice §10](M7-A-homologacion-indice.md#10-documentos-y-catálogos-a-solicitar-al-cliente), sin repetir un documento que ya sirve a varias decisiones. **Se solicitan; ninguno existe hoy en el repositorio.**

| Documento | A qué tema ejecutivo sirve |
|---|---|
| Procedimiento vigente de liberación y rechazo de Calidad, con la autoridad que decide | E1 |
| Procedimiento de muestreo y especificación de laboratorio con límites y unidades | B1 |
| Fichas en papel o de laboratorio reales y llenas de F3, P1-06, P1-19, P1-20, P1-10, P1-29, P1-07, P1-16, P1-12, P1-13 y P1-11 | B3, C2, C3, C4, C5, D1, D2, D3, D4 |
| Fórmulas de humedad, promedios, merma, pallet y consumo, con ejemplo numérico | B3, D1, D2, D3 |
| Lista oficial de máquinas de los tres sectores, con código técnico y nombre visible | E2 |
| Lista oficial de artículos, relaciones artículo-máquina, unidades, clases de material y maestro de pesos nominales (si aplica) | E3 |
| Recetas con vigencia, si se usan | E3 |
| Horarios, vigencia y zona horaria de los turnos de los tres sectores | E4 |
| Documento o acta que precise el periodo del correlativo de F3 (01/04–31/03 frente al cierre al 31/12), fecha de corte y reinicio | E5 |
| Política de numeración de fardo, pallet y merma, si existe | E5 |
| Política de firmas y aprobaciones | E7 |
| Decisión sobre los registros legacy de navegador de Bobinas y Conversión | E8 |
| Documento de alcance del piloto integral, designación de la autoridad de aprobación y lista nominal de usuarios | B4 |
| Lista de reportes exigidos y ejemplo del reporte «bobinas por camión», si entra | B5 |
| Decisión sobre conectividad de planta, Expertus y política de correcciones | B6, B7 |
| Decisión de alojamiento, operación, respaldo y restauración del entorno; política de seguridad | B8 |
| Plan de UAT con participantes, casos y criterio de aceptación | B9 |
| Procedimiento actual de liberación de Calidad de bobinas consumidas en Conversión, y cómo se mueven físicamente entre sectores | E1, D3 |
| Política de inventario y balance, o confirmación de que están fuera de alcance | C8 |
| **La matriz M1-B2-c1** (mencionada en `backend/README.md`; vive fuera del repositorio) | Todas las que contenga — sigue siendo **evidencia pendiente** |

## G. Responsables propuestos

Idénticos a los tres paquetes de origen (roles **por confirmar por VINTO**; este documento no designa personas):

| Rol | Significado | Interviene principalmente en |
|---|---|---|
| **JP** | Jefatura de Producción | Alcance, contratos, maestros, turnos, numeración (B, C, D, E2–E7) |
| **CAL** | Calidad | Mediciones, límites, autoridad de liberación, genealogía (B1, B2, B3, B9, C7, D1, D3, D4, E1, E3, E6) |
| **DB** | Data Baltrek | Catálogos, maestros, artículos, pesos (E2, E3, C9, D2) |
| **TI** | Baltrek TI | Diseño técnico, numeración central, entorno, idempotencia (B7, B8, C2, C5, C6, E5, E7) |
| **DIR** | Dirección / sponsor de VINTO | Autoridad, alcance, autorización expresa de cada puerta (B2, B4, B6, B8, C4, C8, E1, E8, y las puertas G1–G8 de §I) |

## H. Riesgos y bloqueos con impacto técnico

| # | Riesgo / bloqueo | Impacto técnico | Fuente | Mitigación propuesta |
|---|---|---|---|---|
| R1 | Interpretar la cobertura técnica 25/25 o el E2E QA-3F-01 como aprobación industrial | Se activaría un sector o un contrato sin base aprobada | §0, QA-3F-01 §1, PILOTO-BOBINAS R1 | Declarar expresamente, en toda comunicación con VINTO, que capturar/coexistir ≠ homologar; este documento lo repite en cada sección |
| R2 | Implementar Q-LIB sin política de Calidad aprobada | Un criterio de liberación inventado por el equipo técnico | PILOTO-BOBINAS R2, §E1 | Q-LIB solo tras `BO:CAL-01/02/03/05/06/07/08/09/10/11/12` Aprobadas |
| R3 | Activar Rebobinado o Conversión sin maestros, turnos y contratos aprobados | Datos candidatos (provisionales) tratados como oficiales; el bundle se promovería sin evidencia | PILOTO-BOBINAS R3, §E2–E6 | No promover ningún maestro sin evidencia aprobada (criterio del acta M5-B0 §2) |
| R4 | Doble conteo de bobinas entre P1-11, P1-12, P1-13 y la genealogía de Rebobinado | Inventario o balances inconsistentes si se implementan sin resolver identidad de bobina | M7-A índice §7 (riesgo de doble conteo), §D3, §E1 | Resolver `CV:N-3`, `CV:B-6`, `RB:H2-10` **antes** de M7-E/M5-B |
| R5 | Ningún E2E de navegador recorre el circuito completo de Bobinas/Calidad con la política real hasta E2E-B0 | Mitigado parcialmente: E2E-B0 (114/114) y QA-3F-01 (75/75) ya cubren el circuito técnico, pero **ninguno aprueba contratos ni política de Calidad** | PILOTO-BOBINAS PB-C6, QA-3F-01 | Mantener la distinción: cobertura técnica ≠ aprobación industrial |
| R6 | Confundir el piloto de Bobinas (Entrega A) con el MVP integral de los tres frentes (Entrega B) | Aceptación parcial interpretada como cumplimiento contractual completo | PILOTO-BOBINAS §5, R7 | Acuerdo formal escrito sobre qué alcance sustituye cada entrega intermedia |
| R7 | Clasificar Q-LIB, genealogía, inventario o reportes como «postergables» por decisión del equipo técnico | Se reduciría el alcance comercial sin autorización de VINTO | Restricción explícita de este incremento (§7 del encargo) | Toda decisión LT o condicional se marca «requiere resolución formal de VINTO», nunca «se posterga» por el equipo |
| R8 | Entorno sin respaldo y restauración validados para ninguno de los tres frentes | Sin marcha atrás posible ante un error en el piloto o en el GO-LIVE | PILOTO-BOBINAS R5, PB-C7 | PB-ENV como condición dura antes de cualquier activación (puerta G6) |
| R9 | Activar un sector por variable de entorno o interruptor en tiempo de ejecución en vez de un cambio de código revisado | Se eludiría la revisión independiente que exige `sectors.py` por diseño | `backend/app/sectors.py` (comentario de diseño), QA-3F-01 §3 | La activación real exige un PR revisado y la aprobación explícita de VINTO (puerta G8), nunca un flag |

## I. Condiciones objetivas de GO/NO GO

Ver también §6 (matriz de lanzamiento con las puertas G1–G8).

- El GO-LIVE integral (Bobinas + Rebobinado + Conversión) está en **NO GO** en las ocho puertas.
- El piloto aislado de Bobinas (Entrega A de PB-H0) está en **NO GO** en sus tres puertas propias.
- Ningún incremento posterior (Q-LIB, M4-B2, M4-B3, M5-B, M7-B a M7-H) puede abrirse por el solo paso del tiempo: cada uno exige su PR revisado y la autorización expresa de VINTO que su propio paquete de origen ya establece.

---

## 6. Matriz de lanzamiento (puertas G1–G8)

| Puerta | Qué cierra | Evidencia que la satisface | Estado actual | Fuente |
|---|---|---|---|---|
| **G1** | Alcance oficial del GO-LIVE (qué formularios y máquinas por frente) | Documento de alcance firmado por VINTO para los tres frentes (B4 para Bobinas; alcance de M4-B1/M5-B0 para Rebobinado; Q1 de M7-A para Conversión) | **NO GO** — ningún alcance confirmado para ningún frente | §A, B4, PB-H0 §OPS-01, M5-B0, M7-A Q1 |
| **G2** | Maestros y turnos aprobados | `BO:MAE-01/02/05-08`, `RB:H1-01/05-08/10/11`, `CV:C-6/7/8/9` Aprobadas con evidencia | **NO GO** — 0 de las decisiones de maestros/turnos aprobadas en ningún frente | §E2, E3, E4 |
| **G3** | Contratos y reglas industriales homologados | Todas las decisiones `BO:CON`, `RB:H1` de contrato, `CV:C-1/P-1/N-1/B-1` (PF) Aprobadas con evidencia | **NO GO** — 0 aprobadas | §B3, C2, C3, D1–D4 |
| **G4** | Calidad y genealogía resueltas según el alcance confirmado | `BO:CAL-01` a `12` Aprobadas; `RB:H2-10` Aprobada **siempre** (y `RB:H2-11` si `H2-10` exige liberación); `RB:H2-01` Aprobada explícitamente (sin presumir «antes» ni «después»); si `H2-01` = «antes», además `RB:H2-02` a `H2-18` Aprobadas; si `H2-01` = «después», en su lugar una **resolución formal de VINTO** que registre el alcance transitorio, sus limitaciones y la autorización de la implementación posterior; `CV:N-3/B-6/P-10` resueltas según el alcance que confirme VINTO | **NO GO** — 0 aprobadas, incluida `RB:H2-01` (ninguna de las dos alternativas está decidida); **no se extiende ninguna regla de F3 a P1-07, no se asume liberación automática y no se presume el orden de fases de la genealogía** | §B1, B2, C4–C7, D3, E1 |
| **G5** | Configuración de sectores y formularios habilitable | PRs de activación revisados (`sectors.py`, `capture_service.py`) listos tras G1–G4; **ningún cambio se hace sin G8** | **NO GO** — ningún PR de activación existe ni puede existir sin autorización previa | QA-3F-01 §3, R9 |
| **G6** | Entorno cloud seguro y recuperable | `BO:OPS-13/14` Aprobadas; respaldo y restauración validados; migraciones verificadas (`migrate.py --check`) | **NO GO** — solo existe el entorno local de desarrollo; sin procedimiento de despliegue ni restauración validada | §B8, PILOTO-BOBINAS PB-C7 |
| **G7** | QA integral y UAT aprobados | Suites backend/Node/TS/lint/build verdes (ya lo están, ver §0); E2E-B0 y QA-3F-01 ejecutados (ya lo están); **UAT firmado** (`BO:OPS-15/16` Aprobadas) pendiente para los tres frentes | **PARCIAL — NO GO** por el UAT: la cobertura técnica existe (709/709 Node, 114/114 E2E-B0, 75/75 QA-3F-01, 242/242 backend focalizado — ver INT-02B y QA-3F-01), **pero QA no sustituye UAT ni aprobación industrial** | §0, B9, QA-3F-01 §7, PILOTO-BOBINAS PB-C8 |
| **G8** | Autorización escrita de VINTO | Persona con autoridad designada (`BO:OPS-03`) firma la activación de cada sector, con evidencia identificable (acta M5-B0 §2) | **NO GO** — ninguna autorización emitida | §B4, G1 |

**Regla de decisión.** El GO-LIVE integral exige las **ocho puertas en GO simultáneamente**; ninguna puerta se omite por el avance de otra. Mientras **G1** (alcance) no esté cerrada, **G2 a G4 no pueden evaluarse con precisión** porque dependen de qué máquinas y formularios confirme VINTO. **G5** nunca se abre sin **G8**. La cobertura técnica (25/25 formularios, QA-3F-01, E2E-B0, suites verdes) **no mueve ninguna puerta por sí sola**: son evidencia de viabilidad técnica, no de homologación industrial ni de autorización comercial.

## Procedencia

Este documento no redefine estados, evidencia aceptable ni IDs: usa exactamente los de [M5-B0 acta §1 y §2](M5-B0-acta-homologacion.md), reutilizados sin cambios por PB-H0 y M7-A. Las 135 decisiones (`52 BO: + 47 RB: + 36 CV:`) se referencian **cada una exactamente una vez** en §B a §E; la trazabilidad completa de cada ID a su documento de origen está en [PB-H0 §6](PB-H0-homologacion-indice.md#6-cobertura-de-las-21-preguntas-de-origen), [M5-B0 §4](M5-B0-decisiones-VINTO.md#4-trazabilidad-de-las-38-preguntas-de-origen-ninguna-perdida) y [M7-A §4](M7-A-conversion-decisiones-VINTO.md#4-procedencia).
