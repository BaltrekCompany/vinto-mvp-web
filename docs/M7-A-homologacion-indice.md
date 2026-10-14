# M7-A · Paquete de homologación de Conversión: índice

**Estado: documental. Ninguna decisión está aprobada.** Este paquete no implementa funcionalidades industriales, no cambia el motor, las migraciones, `backend/seed_data`, las políticas, los permisos, las concesiones ni los maestros, no accede a DEV ni PROD, no habilita Conversión ni Rebobinado y no fija fechas ni promete activación. Solo ordena lo que VINTO debe responder para pasar de los circuitos técnicos **candidatos** de M6 a contratos industriales **aprobados**.
Base: `26472007d5dfed89842fa2b5ea2920cdec115d81` (PR #33). Antecedentes: [M4-B1](M4-B1-homologacion-rebobinado.md), [M5-B0](M5-B0-decisiones-VINTO.md), [M6-A](M6-A-conversion-central-p116.md), [M6-B](M6-B-conversion-p112.md), [M6-C](M6-C-conversion-p113.md), [M6-D](M6-D-conversion-p111.md).

## 1. Qué es y qué no es
- **Es** un paquete único para que VINTO valide, por bloques, las 36 decisiones pendientes de Conversión, con su clasificación, dependencias, evidencia necesaria y desarrollo que desbloquean.
- **No es** una aprobación: los circuitos E2E de M6 demuestran viabilidad técnica con datos ficticios y **no** constituyen aprobación industrial. Ninguna decisión pasa de Pendiente sin evidencia identificable (criterios del [acta de M5-B0 §2](M5-B0-acta-homologacion.md)).

## 2. Mapa del paquete
| Documento | Contenido |
|---|---|
| **este índice** | Convenciones, alcance, clasificación, dependencias entre sectores, preguntas maestras, roadmap con GO / NO GO y documentos a solicitar |
| [M7-A-conversion-decisiones-VINTO.md](M7-A-conversion-decisiones-VINTO.md) | Matriz única de las 36 decisiones de Conversión (`CV:`), con frente, clase, dependencias y vínculos con Rebobinado |
| [M7-A-agenda-y-registro-conversion.md](M7-A-agenda-y-registro-conversion.md) | Agenda de validación por bloques y formato de registro de respuestas |
| `scripts/m7a-decisions.test.mjs` | Guarda de integridad: 36 claves, estados, referencias y conteos |
| [M5-B0](M5-B0-decisiones-VINTO.md) (sin cambios de contenido) | Fuente de verdad de Rebobinado y genealogía: `RB:H1`, `RB:H2`, `RB:H3` y `RB:P-01` a `RB:P-04` (47 decisiones) |
| [M5-B0 acta](M5-B0-acta-homologacion.md) | **Estados y criterios de evidencia, reutilizados tal cual** (no se redefinen aquí) |

## 3. Convenciones
- **Clave única `(frente, ID)`.** Se conservan literalmente los IDs originales y se escriben con prefijo: `CV:C-1`, `CV:P-3`, `CV:N-5`, `CV:B-2` para Conversión; `RB:H1-01`, `RB:H2-10`, `RB:H3-03`, `RB:P-03` para M5-B0.
- **Colisiones evitadas.** Existen tres familias con aspecto parecido: `CV:P-1` a `CV:P-11` (pallet, M6-B), `RB:P-01` a `RB:P-04` (mejoras posteriores, M5-B0) y las preguntas históricas `P1` a `P20` de M4-B1 §7 (ya trazadas a `RB:H1-xx` / `RB:H2-xx`; no son decisiones de este paquete).
- **Estados y evidencia:** los de M5-B0 acta §1 (Pendiente, Respondido sin evidencia, En revisión, Aprobado, Rechazado / requiere rediseño) y §2 (acta firmada, correo con remitente y fecha, archivo oficial con SHA-256, confirmación formal; no son evidencia un fixture, una prueba que pasa, una definición legacy ni una conversación sin registro).
- **Responsables propuestos:** JP, CAL, DB, TI y DIR, como en M5-B0 (roles por confirmar por VINTO).

## 4. Alcance y conteos
- **Conversión (`CV:`): 36 decisiones = 11 C + 11 P + 8 N + 6 B**, todas **Pendiente**.
- **Rebobinado y genealogía (`RB:`): 47 decisiones = 22 H1 + 18 H2 + 3 H3 + 4 P** en M5-B0, que **no se copian**; este paquete solo las enlaza donde comparten una dependencia con Conversión.
- Formularios de Conversión y sus campos legacy: P1-16 (14 = 5 automáticos + 8 manuales + 1 calculado), P1-12 (37 = 9 + 20 + 8), P1-13 (31 = 8 + 18 + 5) y P1-11 (61 = 5 + 34 + 22, con 10 «Condicional / repetible»): 143 = 27 + 80 + 36.

## 5. Clasificación propuesta PF / OP / LT
**Es una clasificación propuesta y condicional al alcance que VINTO confirme; no es una decisión.** Se aplicó bajo el supuesto «la primera versión es el alcance de los contratos candidatos de M6». Cada decisión tiene **una sola** clase base y las condiciones que la reclasificarían están en la columna «Condición de reclasificación» de la [matriz](M7-A-conversion-decisiones-VINTO.md) §3 (no se cuentan dos veces).

| Clase | Significado |
|---|---|
| **PF** | Bloquea un **piloto funcional** en un entorno aislado con maestros y contratos aprobados |
| **OP** | No bloquea el piloto pero **bloquea el uso operativo real** |
| **LT** | Puede resolverse **después** de los dos anteriores |

| Frente | PF | OP | LT | Total |
|---|--:|--:|--:|--:|
| A · Maestros | 6 | 3 | 0 | 9 |
| B · Formularios | 7 | 6 | 5 | 18 |
| C · Cálculos | 0 | 6 | 0 | 6 |
| D · Integración | 0 | 3 | 0 | 3 |
| **Total** | **13** | **18** | **5** | **36** |

- **Una decisión LT no deja de ser bloqueante por estar clasificada como LT:** el piloto puede avanzar sin ella, pero sigue pendiente y para la activación (M7-H) requiere una **resolución formal de VINTO** (no aplicabilidad o diferimiento, con responsable, riesgo aceptado y condición de resolución posterior). Las decisiones OP aplicables al alcance operativo deben estar **Aprobadas con evidencia** antes de M7-H.

Responder las decisiones PF **no equivale por sí solo a GO** para un piloto: GO exige además los criterios del roadmap (§9).

## 6. Frentes
| Frente | Decisiones | Qué cubre |
|---|---|---|
| **A · Maestros** | CV:C-6, CV:C-7, CV:C-8, CV:C-9, CV:C-11, CV:P-3, CV:P-11, CV:N-2, CV:N-8 | Máquinas, artículos, relaciones artículo-máquina, turnos, pesos nominales y recetas |
| **B · Formularios** | CV:C-1, CV:C-2, CV:C-4, CV:C-10, CV:P-1, CV:P-2, CV:P-5, CV:P-6, CV:P-7, CV:P-9, CV:N-1, CV:N-4, CV:N-7, CV:B-1, CV:B-2, CV:B-3, CV:B-4, CV:B-5 | Unidad de registro, obligatoriedad, campos, valores, numeración y firmas |
| **C · Cálculos industriales** | CV:C-3, CV:C-5, CV:P-4, CV:P-8, CV:N-5, CV:N-6 | Pesos, consumos, balances, mermas y producción |
| **D · Integración** | CV:P-10, CV:N-3, CV:B-6 | Genealogía, Calidad, inventario y riesgo de doble conteo |

## 7. Dependencias entre Conversión, Rebobinado, Calidad y genealogía
**Cadena física [H, hipótesis no confirmada por VINTO]:** una bobina nace en Bobinas (F3, con `quality_release` en `pending`), se procesa en Rebobinado (P1-07, madre/hija) y se consume en Conversión (P1-11 y P1-13). Hoy no existe ningún servicio de consumo, de liberación de Calidad ni de genealogía productiva (M5-A).

**Decisiones transversales: una sola respuesta organizacional sirve a varios formularios y sectores.** Los estados de las decisiones `RB:` no cambian; se enlazan.
| Tema | Conversión | Rebobinado / genealogía (M5-B0) | Observación |
|---|---|---|---|
| Modelo de turnos | CV:C-7, CV:C-8, CV:P-6 | RB:H1-05, RB:H1-06, RB:H1-07, RB:H1-08, RB:H1-09 | Si el horario resulta «por máquina», cambia el modelo para ambos sectores |
| Tabla formulario × máquina | CV:C-6, CV:P-11, CV:N-8 | RB:H1-01, RB:H1-03, RB:H1-04, RB:H2-16 | Mismo formato de respuesta |
| Maestros de artículos | CV:C-9, CV:C-11, CV:N-2, CV:P-3 | RB:H1-10, RB:H1-11, RB:P-03 | Pesos nominales, recetas, unidades |
| Numeración | CV:C-2, CV:P-2 | RB:H1-13, RB:H1-14, RB:H2-13 | Un solo diseño de numerador si resulta central |
| Firma y aprobación | CV:C-4, CV:P-9 | RB:H1-16, RB:H1-21, RB:H2-17 | Un solo mecanismo |
| Peso, unidad y decimales | CV:C-5, CV:P-4, CV:N-5, CV:B-5 | RB:H1-15, RB:P-02, RB:H3-02 | Un estándar |
| Identidad de bobina y Calidad | CV:N-3, CV:B-6, CV:P-10 | RB:H2-02, RB:H2-03, RB:H2-10, RB:H2-11, RB:H2-12 | La misma respuesta («¿se exige una bobina real y liberada para consumir?») decide si P1-11 y P1-13 siguen declarando texto libre |
| Inventario y balance | CV:C-3, CV:N-5, CV:P-10 | RB:H3-01, RB:H3-03 | `RB:H3-03` decide si existen |

**Riesgos de integración.**
- **Doble conteo:** P1-11, P1-13 y P1-12 pueden registrar lo mismo (CV:B-4, CV:N-3); nada compara hoy un saldo final con el inicial siguiente ni impide declarar la misma bobina dos veces.
- **Datos declarados que parezcan existencias oficiales:** mitigados en M6 con etiquetas «declarado», advertencias y historiales sin sumas.
- **Identificación futura por UUID:** hoy solo existe `GET /api/bobbins/{id}` (sin búsqueda) y el motor no tiene tipo de campo UUID; no se implementa en este paquete.

## 8. Preguntas maestras (secuencia sugerida)
Las preguntas maestras ordenan la conversación; **no sustituyen** la aprobación de cada decisión y **responderlas no equivale por sí solo a GO**: cada decisión debe quedar Aprobada con evidencia (acta M5-B0 §2).
| # | Pregunta | Decisiones que ayuda a cerrar |
|---|---|---|
| Q1 | Alcance de la primera versión: qué formularios y máquinas de Conversión entran | CV:C-6, CV:P-11, CV:N-8; condiciona CV:B-2, CV:B-3, CV:B-4 |
| Q2 | Maestros: máquinas, artículos, relaciones y turnos (con el mismo criterio que Rebobinado) | CV:C-7, CV:C-8, CV:C-9 |
| Q3 | Unidad de registro de cada ficha | CV:C-1, CV:P-1, CV:P-7, CV:N-1, CV:N-4, CV:N-7, CV:B-1 |
| Q4 | Numeración (pallet, merma): ¿existe, manual o central? | CV:C-2, CV:P-2 |
| Q5 | Firma y aprobación: un solo mecanismo para todas las fichas | CV:C-4, CV:P-9 |
| Q6 | Estándar de peso, unidad y decimales | CV:C-5, CV:C-11, CV:P-3, CV:P-5, CV:N-6, CV:B-5 |
| Q7 | Qué se calcula, quién lo calcula y con qué fórmula | CV:C-3, CV:P-4, CV:P-8, CV:N-5 |
| Q8 | La bobina: identidad y relación con Calidad | CV:N-2, CV:N-3, CV:B-6, CV:P-10 |
| Q9 | ¿Inventario y balance de masas están en el alcance? (misma pregunta que `RB:H3-03`) | condiciona CV:C-3, CV:N-5, CV:P-10, CV:B-6 |
| Q10 | Qué hacer con los registros legacy de los navegadores | CV:C-10 |

## 9. Roadmap posterior a M6 (sin fechas ni compromisos)
**Estado actual de todos los incrementos: NO GO** (ninguna decisión aprobada). Ningún incremento se abre por el solo paso del tiempo, y ninguno activa Conversión ni Rebobinado sin aprobación expresa de VINTO y un PR revisado.
| Incremento | Equivale a | Entrega | GO solo si… | NO GO si… | Depende de |
|---|---|---|---|---|---|
| **M7-B** Homologación de maestros | M4-B2 (maestros) | Alcance aprobado del exportador y bundle promovible por PR revisado; ensayo de importación en `*_test` (nunca a DEV) | Aprobadas con evidencia CV:C-6, CV:C-7, CV:C-8, CV:C-9, CV:P-11, CV:N-8 (más CV:C-11, CV:P-3 y CV:N-2 si el peso o la receta son obligatorios) y, si se hace en conjunto, las `RB:H1` de maestros que exige M5-B0 §5 | Falta cualquiera de ellas o su evidencia | — |
| **M7-C** Homologación de contratos de captura | M4-B2 (contratos) | Definiciones publicables de las fichas aprobadas; pruebas de contrato; la política de captura **no** se toca | Aprobadas con evidencia las decisiones PF de formulario (CV:C-1, CV:P-1, CV:P-7, CV:N-1, CV:N-4, CV:N-7, CV:B-1) y las condicionales que se activen; M7-B cerrado para sus máquinas | La unidad de registro de alguna ficha sigue sin definir | M7-B |
| **M7-D** Reglas de cálculo industrial | — | Cálculos en servidor con decimales exactos; probable extensión del motor (campos calculados) y migración | Aprobadas con evidencia las fórmulas, unidades y redondeos (CV:C-3, CV:C-5, CV:P-4, CV:N-5, CV:N-6, CV:P-8, CV:B-5, CV:C-11, CV:P-3) y el alcance (`RB:H3-03`) | No hay fórmulas homologadas o los cálculos están fuera de alcance | M7-C |
| **M7-E** Integración de bobinas y genealogía | M5-B | Identidad de bobina, consumo y genealogía; migración | Aprobadas con evidencia CV:N-3, CV:B-6, CV:P-10 y las `RB:H2` que exige M5-B0 §5 (siempre `RB:H2-10`) | `RB:H2-10` sin resolver | M7-C |
| **M7-F** Calidad e inventario | H3+ | Liberación, balance e inventario, si están en alcance | `RB:H3-01` a `RB:H3-03` aprobadas con confirmación expresa del alcance | El inventario está fuera de alcance | M7-D, M7-E |
| **M7-G** Piloto en entorno aislado | — | Entorno separado de DEV con datos aprobados | M7-B y M7-C cerrados para el alcance del piloto; **todas** las decisiones PF aplicables Aprobadas con evidencia; checklist técnico (respaldo, dry-run) y aprobación explícita de VINTO. Las OP y LT que queden pendientes se listan expresamente como limitaciones del piloto | Cualquier PF aplicable pendiente | M7-B, M7-C |
| **M7-H** Activación controlada en DEV | M4-B3 | PRs de activación (sector operativo, política, concesiones), con respaldo restaurado y validado | **Todas** estas condiciones: (1) M7-G concluido y aprobado; (2) **todas** las decisiones PF **y OP** aplicables al alcance operativo Aprobadas con evidencia identificable; (3) cada decisión LT diferida con una **resolución formal de VINTO** que documente su no aplicabilidad o su diferimiento, el responsable, el riesgo aceptado y la condición de resolución posterior (clasificar una decisión como LT no la hace dejar de ser bloqueante); (4) M7-D, M7-E y M7-F concluidos cuando sean parte del alcance aprobado; (5) checklist técnico completo; (6) autorización expresa de VINTO; (7) PRs de activación revisados de forma independiente | Falta cualquiera de las siete condiciones, o hay una OP o LT aplicable sin resolver | M7-G |
- M7-D, M7-E y M7-F solo se abren si VINTO confirma que están en el alcance (Q9).
- Los GO de arriba son condiciones necesarias, no una promesa de fecha ni de activación.

**Alcance de M7-B y M7-C por sector.**
- Las decisiones `CV:` aplican a **Conversión** y a los formularios que VINTO incluya **formalmente** en su alcance; un formulario fuera de ese alcance no se promueve.
- **Rebobinado mantiene sus propias puertas de homologación**, establecidas en [M5-B0](M5-B0-decisiones-VINTO.md) §5 y en M4-B2; este paquete no las cambia ni las sustituye.
- El avance de un sector **no equivale a aprobar** el otro: el cierre de M7-B o M7-C para Conversión no aprueba nada de Rebobinado, ni al revés.
- **No se promueven maestros, contratos ni paquetes sin evidencia aprobada** (criterios del acta de M5-B0 §2).

## 10. Documentos y catálogos a solicitar al cliente
Se **solicitan**; este paquete no afirma que existan ni los incorpora.
| Documento | Decisiones que ayuda a cerrar |
|---|---|
| Lista oficial de las máquinas de Conversión (11 candidatas), con nombre y código | CV:C-6, CV:C-9 |
| Horarios y vigencias de los turnos de Conversión (documento o resolución interna) | CV:C-7, CV:C-8, CV:P-6 |
| Lista oficial de artículos y relaciones artículo-máquina (98 candidatas), unidades `Pack` y `UN` y clase `BLANCOS` | CV:C-9 |
| Maestro de pesos nominales aprobado (versión oficial de `INArticulo-MFMatrialOP`) | CV:C-11, CV:P-3 |
| Recetas con vigencia, si se usarán | CV:N-2 |
| Fichas en papel reales y llenas de P1-11, P1-12, P1-13 y P1-16 | CV:C-1, CV:P-1, CV:N-1, CV:B-1 |
| Criterio de pesaje, unidades y decimales | CV:C-5, CV:P-5, CV:N-6 |
| Política de numeración de pallets y de merma | CV:C-2, CV:P-2 |
| Política de firmas y aprobaciones | CV:C-4, CV:P-9 |
| Fórmulas vigentes de consumo, saldos, merma y producción | CV:C-3, CV:P-4, CV:P-8, CV:N-5 |
| Procedimiento actual de liberación de Calidad de bobinas | CV:B-6 |
| Cómo se mueven físicamente las bobinas entre Bobinas, Rebobinado y Conversión | CV:N-3, CV:P-10 |
| Política de inventario y balance, o confirmación de que están fuera de alcance | `RB:H3-03` |
| Decisión sobre los registros legacy de los navegadores | CV:C-10 |
| La matriz M1-B2-c1 (**evidencia pendiente**; vive fuera del repositorio, ver M5-B0 §1) | Todas las que contenga |

## 11. Límites y evidencia pendiente
- Este paquete **no inventa** respuestas, aprobaciones, fechas de cumplimiento ni documentos del cliente; los campos de respuesta del registro están vacíos.
- La matriz **M1-B2-c1** (evidencia fuera del repositorio) sigue siendo evidencia pendiente; hasta que se aporte, su contenido no cuenta como aprobación.
- Cualquier cambio posterior de estado se registra como una fila nueva (nada se borra), según el acta de M5-B0.
