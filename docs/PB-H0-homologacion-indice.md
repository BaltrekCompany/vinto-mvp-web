# PB-H0 · Paquete de homologación de Bobinas MP1/MP3 y Calidad: índice

**Estado: documental. Ninguna decisión está aprobada.** Este paquete no implementa funcionalidades industriales, no cambia el motor, las migraciones, `backend/seed_data`, los sectores, `CENTRAL_FORM_CODES`, las políticas, los permisos, las concesiones ni los maestros, no accede a DEV ni PROD, no corrige Seguimiento, no implementa el servicio de liberación (Q-LIB) y no fija fechas ni promete activación. **PB-H0 no equivale a una homologación industrial:** solo ordena lo que VINTO debe responder para pasar de los circuitos técnicos candidatos de Bobinas a contratos y políticas aprobadas.
Base: `51ec39be4f6b70267bf80e742b650c54d1e4d5f9` (PR #35). Antecedentes: [diagnóstico del piloto](PILOTO-BOBINAS-brechas-y-GO-NOGO.md), [M5-B0](M5-B0-decisiones-VINTO.md), [M7-A](M7-A-homologacion-indice.md).

## 1. Objetivo y alcance
- **Objetivo:** preparar las decisiones y evidencias que VINTO debe aprobar para cerrar un **piloto funcional aislado de Bobinas MP1/MP3** (flujo OT → publicación → asignación → F3 / P1-06 → Calidad P1-19 / P1-20 → liberación o rechazo → Seguimiento).
- **Alcance:** Bobinas MP1 y MP3 (sector, formularios F3, P1-06, P1-19 y P1-20, maestros, turnos, correlativo) y la política de liberación de Calidad, más las decisiones de operación del piloto (alcance, reportes, offline, Expertus, correcciones, usuarios, entorno y UAT).
- **No se autoriza** el desarrollo del servicio de liberación, modificaciones de maestros, activaciones ni la corrección de Seguimiento.

## 2. Piloto de Bobinas frente a MVP integral
| | Piloto de Bobinas (Entrega A) | MVP integral VINTO (Entrega B) |
|---|---|---|
| Alcance | Bobinas MP1 y MP3 en un entorno aislado | 25 formularios, 602 campos activos, reportes, Rebobinado, Conversión y capacidades transversales |
| Decisiones | Este paquete (`BO:`) | Además, `RB:` (47) y `CV:` (36) y las que surjan |
| Aceptación | Checklist de 18 condiciones y aprobación expresa de VINTO | Acuerdo formal de alcance y aceptación de VINTO |

Completar el piloto **no** completa el MVP integral ni sustituye el acuerdo formal sobre el alcance. Las piezas compartidas se enlazan en §8.

## 3. Las tres puertas (no se confunden)
| Puerta | Qué cierra | Condición | Qué **no** autoriza |
|---|---|---|---|
| **1 · Cierre documental PB-H0** | El paquete (índice, matriz, agenda y registro, guarda de integridad) está completo y revisado de forma independiente | Los documentos son coherentes, los tests documentales pasan, el diff no contiene cambios operativos y todas las decisiones están Pendiente | Nada operativo: no aprueba ninguna decisión ni autoriza desarrollo |
| **2 · GO de diseño / implementación de Q-LIB** | Iniciar el diseño y la implementación del servicio de liberación y rechazo | **(a)** Las decisiones `Q-LIB = B` (BO:CAL-01, BO:CAL-02, BO:CAL-03, BO:CAL-05, BO:CAL-06, BO:CAL-07, BO:CAL-08, BO:CAL-09, BO:CAL-10, BO:CAL-11, BO:CAL-12) **Aprobadas con evidencia** (acta M5-B0 §2); **(b)** las condicionales (BO:CAL-04, BO:OPS-19) Aprobadas o con una **decisión formal de no aplicabilidad con evidencia identificable** (ver la regla de aplicabilidad abajo); **(c)** autorización **expresa** de desarrollo | Activar el sistema, aprobar contratos o maestros, ni el GO del piloto |
| **3 · GO del piloto** | Operar el piloto | Cumplir el [checklist de 18 condiciones](PILOTO-BOBINAS-brechas-y-GO-NOGO.md) §10 con su regla de decisión (T, V, A y R) y la **autorización formal de VINTO** | Activar Rebobinado o Conversión |

**Regla de aplicabilidad de la puerta 2.** El software puede automatizar una regla industrial, dejarla a una comprobación manual o no aplicarla, y **eso no cambia que la regla industrial rige**. Se distinguen cuatro cosas: **(1)** la **regla industrial exigida por VINTO**; **(2)** la **validación automática** que realizará el software; **(3)** la **comprobación manual** que asumirá una persona autorizada; **(4)** la **decisión formal de no aplicabilidad**, con evidencia. Una regla **no** pasa a «no aplicable» porque el sistema no la automatice: si rige aunque su verificación sea manual, debe existir una **aprobación identificable** (incluida la persona o cargo autorizado que la comprueba) **antes de implementar el flujo que depende de ella**. Solo cabe «no aplicable» mediante la decisión formal de VINTO (punto 4). Una decisión **C** solo es condicional por una **aplicabilidad real** (por ejemplo, `BO:CAL-04` no aplica únicamente si `BO:CAL-03` aprobada establece «sin límite») o por vistas adicionales (`BO:OPS-19`), nunca por falta de automatización.

**Estado actual de las tres puertas:** puerta 1 en revisión; puerta 2 **NO GO** (11 decisiones bloqueantes en Pendiente); puerta 3 **NO GO**. **La aprobación documental nunca autoriza por sí misma la activación del sistema.**

## 4. Mapa de documentos
| Documento | Contenido |
|---|---|
| **este índice** | Objetivo, puertas, convenciones, cobertura de las 21 preguntas, dependencias con Conversión y Rebobinado, evidencias a solicitar, preguntas maestras, roadmap y condiciones GO / NO GO |
| [PB-H0-decisiones-VINTO.md](PB-H0-decisiones-VINTO.md) | Matriz única de las 52 decisiones `BO:` con alternativas, comportamiento técnico existente, evidencia, responsables, dependencias y efecto |
| [PB-H0-agenda-y-registro.md](PB-H0-agenda-y-registro.md) | Agenda de seis bloques y registro de respuestas por cambio de estado |
| `scripts/pbh0-decisions.test.mjs` | Guarda de integridad documental |
| [Diagnóstico del piloto](PILOTO-BOBINAS-brechas-y-GO-NOGO.md) | Fuente de las 21 preguntas, las brechas `PB-` y el checklist de 18 condiciones |
| [M5-B0 acta](M5-B0-acta-homologacion.md) | **Estados y criterios de evidencia, reutilizados tal cual** |

## 5. Convenciones
- **Identificadores:** `BO:CAL-xx`, `BO:CON-xx`, `BO:MAE-xx`, `BO:OPS-xx` (únicos y contiguos por familia). No colisionan con `PB-A1`–`PB-C10`, `CV:` ni `RB:`; los IDs históricos no se renumeran.
- **Estados y evidencia:** los de M5-B0 acta §1 y §2; **no son evidencia** un fixture, una prueba que pasa, una definición legacy, una conversación sin registro ni la existencia de datos en el catálogo candidato.
- **Responsables propuestos:** JP, CAL, DB, TI y DIR, como en M5-B0 y M7-A (roles por confirmar por VINTO).

## 6. Cobertura de las 21 preguntas de origen
**Son 21 preguntas de origen, no 21 decisiones**: las preguntas compuestas se dividieron para que cada parte se apruebe por separado.

| Pregunta | Tema | Decisiones |
|---|---|---|
| Q-1 | Mediciones obligatorias, cantidad y frecuencia | BO:CAL-01, BO:CAL-02 |
| Q-2 | Límites o tolerancias por magnitud y por artículo | BO:CAL-03, BO:CAL-04 |
| Q-3 | Autoridad de decisión y separación entre quien mide y quien decide | BO:CAL-05, BO:CAL-06 |
| Q-4 | Motivo obligatorio | BO:CAL-07 |
| Q-5 | Reversión o reevaluación | BO:CAL-08, BO:CAL-09 |
| Q-6 | Efecto de la decisión | BO:CAL-10 |
| Q-7 | Rechazo: destino, registro y nuevo ciclo | BO:CAL-11 |
| Q-8 | Excepciones: liberar sin medición | BO:CAL-12 |
| B-1 | Contratos de F3, P1-06, P1-19 y P1-20 (incluye unidades provisionales de P1-20) | BO:CON-01, BO:CON-02, BO:CON-03, BO:CON-04, BO:CON-05, BO:CON-06, BO:CON-07, BO:CON-08, BO:MAE-04 |
| B-2 | Máquinas, artículos, unidades, clases y peso nominal | BO:MAE-01, BO:MAE-02, BO:MAE-03, BO:MAE-04 |
| B-3 | Horarios y vigencias de los turnos | BO:MAE-05, BO:MAE-06, BO:MAE-07, BO:MAE-08 |
| B-4 | Numeración: vigencia y reinicio del correlativo | BO:MAE-09, BO:MAE-10, BO:MAE-11, BO:MAE-12 |
| B-5 | Registros históricos o heredados de navegador | BO:MAE-13 |
| O-1 | Alcance del piloto y autoridad para aprobarlo | BO:OPS-01, BO:OPS-02, BO:OPS-03 |
| O-2 | Reportes exigidos y formato | BO:OPS-04, BO:OPS-05 |
| O-3 | Operación sin conexión | BO:OPS-06, BO:OPS-07 |
| O-4 | Corrección de capturas cerradas | BO:OPS-08, BO:OPS-09 |
| O-5 | Expertus | BO:OPS-10 |
| O-6 | Usuarios nominales y quién aprueba altas y bajas | BO:OPS-11, BO:OPS-12 |
| O-7 | Entorno aislado, operador y respaldo/restauración | BO:OPS-13, BO:OPS-14 |
| O-8 | UAT: participantes, casos y criterio | BO:OPS-15, BO:OPS-16 |

Las 3 decisiones adicionales provienen de brechas del diagnóstico que también dependen de VINTO: BO:OPS-17 (PB-C1), BO:OPS-18 (PB-A9) y BO:OPS-19 (PB-A5 y PB-B8).

## 7. Frentes y conteos
| Frente | Familia | Decisiones | Qué cubre |
|---|---|--:|---|
| C · Calidad y liberación | `BO:CAL` | 12 | Mediciones, límites, autoridad, motivos, reversión, efectos, rechazo y excepciones |
| F · Contratos de formularios | `BO:CON` | 8 | F3, P1-06, P1-19 y P1-20 por separado; unidades; fórmulas derivadas; denominaciones |
| M · Maestros, turnos y correlativo | `BO:MAE` | 13 | Máquinas, artículos, pesos, gramaje, turnos, fecha operativa, correlativo, históricos |
| O · Operación y alcance | `BO:OPS` | 19 | Alcance, autoridad, reportes, offline, correcciones, Expertus, usuarios, entorno, UAT, seguridad, auditoría y Seguimiento |
| **Total** | | **52** | |

### Discrepancia registrada: correlativo de F3
**No se resuelve aquí.** La implementación vigente reinicia el correlativo por máquina y por gestión **01/04–31/03**; un antecedente de reunión de octubre menciona un **cierre anual al 31/12** que **no está documentado en el repositorio**. No se concluye que sean equivalentes ni contradictorias. VINTO debe precisar qué periodo representa cada referencia (`BO:MAE-09`), la fecha de corte y de reinicio (`BO:MAE-10`), si el reinicio es por máquina y el formato visible (`BO:MAE-11`) y el tratamiento de numeraciones históricas y cambios de gestión (`BO:MAE-12`). No se modifica código ni migraciones.

### Casos sensibles
- **Calidad.** Se distinguen mediciones obligatorias, cantidad y frecuencia, tolerancias, autoridad, separación entre quien mide y quien decide, motivos, reintentos y decisiones contradictorias, rechazo, reversión, excepciones y efectos. El permiso técnico `quality.release` existe pero **no equivale a autoridad industrial**. No se fijan tolerancias, transiciones, excepciones ni política de rechazo sin respuesta de VINTO.
- **Contratos.** Cada formulario se aprueba individualmente. Las unidades de P1-20 son **provisionales** y las fórmulas y promedios mostrados son **candidatos**, no reglas oficiales.
- **Alcance del piloto.** Reportes, offline, Expertus, correcciones, usuarios, entorno y UAT se registran por separado. Los **requisitos técnicos de seguridad, QA, auditoría, eliminación de datos ficticios y recuperación no pueden omitirse** aceptando un riesgo genérico; los reportes pueden excluirse solo por decisión formal; la ausencia de corrección exige una política temporal con responsable, procedimiento de incidencias y tratamiento de registros incorrectos.

## 8. Dependencias con Conversión y Rebobinado
**Decisiones transversales: una sola respuesta organizacional puede servir a varios sectores.** Los estados de `CV:` y `RB:` **no cambian**; se enlazan. Una respuesta de Bobinas **no aprueba** nada de Conversión ni de Rebobinado, ni al revés.
| Tema | Bobinas (`BO:`) | Conversión | Rebobinado y genealogía | Observación |
|---|---|---|---|---|
| Turnos y fecha operativa | BO:MAE-05, BO:MAE-06, BO:MAE-07, BO:MAE-08 | CV:C-7, CV:C-8 | RB:H1-05, RB:H1-06, RB:H1-07, RB:H1-08 | Mismo formato de respuesta; si el horario es «por máquina» cambia el modelo para los tres sectores |
| Máquinas | BO:MAE-01 | CV:C-6 | RB:H1-01 | Tabla formulario × máquina |
| Maestros de artículos y pesos | BO:MAE-02, BO:MAE-03 | CV:C-9, CV:C-11, CV:P-3 | RB:H1-10, RB:H1-11, RB:P-03 | Pesos nominales y unidades |
| Numeración | BO:MAE-09, BO:MAE-10, BO:MAE-11, BO:MAE-12 | CV:C-2, CV:P-2 | RB:H1-13, RB:H1-14, RB:H2-13 | `RB:H2-13` pregunta si las hijas usan el correlativo de F3: depende de lo que se decida para F3 |
| Unidades, pesos y decimales | BO:CON-01, BO:CON-02, BO:CON-05 | CV:C-5 | RB:P-02, RB:H3-02 | Un solo estándar |
| Autoridad y política de liberación de Calidad | BO:CAL-05, BO:CAL-10, BO:CAL-11 | CV:B-6, CV:P-10 | RB:H2-10, RB:H2-11 | `RB:H2-10` y `CV:B-6` preguntan si el proceso siguiente exige una bobina liberada; conviene responder `BO:CAL` antes o en el mismo bloque |
| Registros legacy de navegador | BO:MAE-13 | CV:C-10 | — | Una sola decisión organizacional |

## 9. Evidencias que VINTO debe aportar
Se **solicitan**; este paquete no afirma que existan ni las incorpora.
| Documento | Decisiones que ayuda a cerrar |
|---|---|
| Procedimiento vigente de liberación y rechazo de Calidad, con la autoridad que decide | BO:CAL-01, BO:CAL-05, BO:CAL-06, BO:CAL-07, BO:CAL-08, BO:CAL-11, BO:CAL-12 |
| Procedimiento de muestreo y especificación de laboratorio con límites y unidades | BO:CAL-02, BO:CAL-03, BO:CAL-04, BO:CON-05 |
| Fichas en papel o de laboratorio reales y llenas de F3, P1-06, P1-19 y P1-20 | BO:CON-01, BO:CON-02, BO:CON-03, BO:CON-04, BO:CON-08 |
| Fórmulas de humedad y promedios, con ejemplo numérico | BO:CON-06, BO:CON-07 |
| Lista oficial de máquinas, artículos, relaciones, unidades y clases, y maestro de pesos si aplica | BO:MAE-01, BO:MAE-02, BO:MAE-03, BO:MAE-04 |
| Horarios, vigencia y zona horaria de los turnos de Bobinas; confirmación de la fecha operativa de la noche | BO:MAE-05, BO:MAE-06, BO:MAE-07, BO:MAE-08 |
| Documento o acta que precise el periodo del correlativo (01/04–31/03 frente al cierre al 31/12), fecha de corte y reinicio, y el tratamiento de históricos | BO:MAE-09, BO:MAE-10, BO:MAE-11, BO:MAE-12 |
| Decisión sobre los registros legacy de navegador | BO:MAE-13 |
| Documento de alcance del piloto, designación de autoridad y lista nominal de usuarios | BO:OPS-01, BO:OPS-02, BO:OPS-03, BO:OPS-11, BO:OPS-12 |
| Lista de reportes exigidos y ejemplo del reporte «bobinas por camión», si entra | BO:OPS-04, BO:OPS-05 |
| Decisión sobre conectividad de planta, Expertus y política de correcciones | BO:OPS-06, BO:OPS-07, BO:OPS-08, BO:OPS-09, BO:OPS-10 |
| Decisión de alojamiento, operación, respaldo y restauración del entorno; política de seguridad | BO:OPS-13, BO:OPS-14, BO:OPS-17 |
| Plan de UAT con participantes, casos y criterio de aceptación | BO:OPS-15, BO:OPS-16 |
| Requisitos de consulta de auditoría y de vistas de Seguimiento | BO:OPS-18, BO:OPS-19 |
| La matriz M1-B2-c1 (**evidencia pendiente**; vive fuera del repositorio) | Todas las que contenga |

## 10. Preguntas maestras (secuencia sugerida)
Ordenan la conversación; **responderlas no equivale por sí solo a aprobar** las decisiones que ayudan a cerrar: cada decisión se registra y se aprueba con su evidencia.
| # | Pregunta | Decisiones |
|---|---|---|
| PM-1 | ¿Qué entra en el piloto y quién tiene autoridad para aprobarlo y aceptarlo? | BO:OPS-01, BO:OPS-02, BO:OPS-03, BO:OPS-11, BO:OPS-12 |
| PM-2 | ¿Son oficiales los contratos de los cuatro formularios y sus unidades? | BO:CON-01 a BO:CON-08 |
| PM-3 | ¿Son oficiales las máquinas, artículos, pesos y gramaje? | BO:MAE-01, BO:MAE-02, BO:MAE-03, BO:MAE-04 |
| PM-4 | ¿Cuáles son los turnos, su vigencia y la regla de fecha operativa? | BO:MAE-05, BO:MAE-06, BO:MAE-07, BO:MAE-08 |
| PM-5 | ¿Qué periodo, corte y reinicio tiene el correlativo y qué pasa con lo histórico? | BO:MAE-09, BO:MAE-10, BO:MAE-11, BO:MAE-12, BO:MAE-13 |
| PM-6 | ¿Qué mediciones, límites y excepciones condicionan una liberación? | BO:CAL-01, BO:CAL-02, BO:CAL-03, BO:CAL-04, BO:CAL-12 |
| PM-7 | ¿Quién decide, con qué motivo, y se puede revertir? | BO:CAL-05, BO:CAL-06, BO:CAL-07, BO:CAL-08, BO:CAL-09 |
| PM-8 | ¿Qué efecto tiene liberar o rechazar y qué pasa con la bobina rechazada? | BO:CAL-10, BO:CAL-11 |
| PM-9 | ¿Qué reportes, offline, Expertus y correcciones aplican al piloto? | BO:OPS-04 a BO:OPS-10 |
| PM-10 | ¿Dónde se aloja el entorno, qué seguridad, auditoría y Seguimiento se exigen y cómo se acepta? | BO:OPS-13 a BO:OPS-19 |

## 11. Roadmap específico de Bobinas y condiciones GO / NO GO
**Estado actual de todos los incrementos posteriores: NO GO.** Ningún incremento se abre por el solo paso del tiempo ni por haber fusionado PB-H0; cada uno requiere su PR revisado y la autorización expresa correspondiente. Los GO son condiciones necesarias, no una promesa de fecha.
| Incremento | Entrega | GO solo si… | NO GO si… | Depende de |
|---|---|---|---|---|
| **PB-H0** (este paquete) | Documental | Puerta 1: paquete completo y revisado | Hay incoherencias o un cambio operativo en el diff | — |
| **Homologación** (respuestas de VINTO) | Externo | Cada decisión pasa a Aprobado con evidencia identificable (acta M5-B0 §2) | Falta evidencia o autoridad | PB-H0 |
| **PB-CLEAN** | Retirar datos ficticios de Seguimiento (PB-A5, PB-C10) | Autorización expresa; **no requiere** decisiones `BO:` | Falta autorización | — |
| **Q-LIB** | Servicio y UI de liberación y rechazo | Puerta 2: BO:CAL-01, BO:CAL-02, BO:CAL-03, BO:CAL-05, BO:CAL-06, BO:CAL-07, BO:CAL-08, BO:CAL-09, BO:CAL-10, BO:CAL-11, BO:CAL-12 Aprobadas con evidencia; las condicionales (BO:CAL-04, BO:OPS-19) Aprobadas o con decisión formal de no aplicabilidad con evidencia; y autorización expresa de desarrollo | Cualquier decisión B Pendiente | Homologación |
| **E2E-B** | E2E de navegador del circuito completo | Q-LIB implementado | Q-LIB sin implementar | Q-LIB |
| **PB-MAESTROS** | Bundle de maestros de Bobinas con fuentes aprobadas e importación en `*_test` (independiente de M7-B, que pertenece a Conversión) | BO:MAE-01, BO:MAE-02, BO:MAE-05, BO:MAE-06, BO:MAE-07, BO:MAE-08 Aprobadas con evidencia y, si aplican, BO:MAE-03, BO:MAE-04, BO:OPS-01 | Falta cualquiera de ellas o su evidencia | Homologación |
| **PB-ENV** | Entorno aislado, migraciones verificadas, respaldo y restauración validados | BO:OPS-13, BO:OPS-14 Aprobadas con evidencia y, si aplican, BO:OPS-02, BO:OPS-11, BO:OPS-17 | Falta cualquiera de ellas | Homologación |
| **UAT** | Guion, ejecución y acta | BO:OPS-15 y BO:OPS-16 Aprobadas; Q-LIB, E2E-B, PB-MAESTROS y PB-ENV concluidos | Falta cualquiera | Los cuatro anteriores |
| **GO del piloto** | Operación del piloto | Puerta 3: las 18 condiciones con su regla (T, V, A, R) y autorización formal de VINTO | Cualquier condición T, V, A o R sin cumplir | Todas |

## 12. Límites
- Este paquete **no inventa** respuestas, aprobaciones, fechas, aprobadores ni documentos del cliente; los campos de respuesta del registro están vacíos.
- Cualquier cambio posterior de estado se registra como una fila nueva (nada se borra), según el acta de M5-B0.
- La matriz **M1-B2-c1** sigue siendo evidencia pendiente.
