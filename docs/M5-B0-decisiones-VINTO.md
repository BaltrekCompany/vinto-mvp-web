# M5-B0 · Paquete único de decisiones para VINTO (Rebobinado, P1-10, P1-29, P1-07 y genealogía)

**Estado: documental. Ninguna decisión está aprobada.** No se implementa ninguna regla industrial, no se tocó DEV, catálogos, permisos ni configuración, no hay migraciones, Rebobinado sigue NO homologado y NO operativo y P1-07 no está publicado.
Consolida `docs/M4-B1-homologacion-rebobinado.md` (20 preguntas) y `docs/M5-A-p107-genealogia.md` (18 decisiones). Complementos: [agenda](M5-B0-agenda-homologacion.md) y [acta](M5-B0-acta-homologacion.md).
Base: `08fd3f3` (PR #28).

## 1. Cómo leer este documento
- **Base actual** (columna «Base»): qué respalda hoy lo que existe, sin convertirlo en decisión:
  **I** = implementado y probado en el repositorio; **L** = documentado en un formulario legacy (`lib/vinto/form-definitions.ts`); **F** = hipótesis de un fixture de prueba; **A** = aprobada expresamente por VINTO (hoy: **ninguna** en este paquete); **O** = abierta, sin base.
- **Estado de homologación:** todas las decisiones están en **Pendiente** (ver [acta](M5-B0-acta-homologacion.md) para los estados y la evidencia exigida). Un fixture o una prueba que funciona **no** aprueba nada.
- **Bloquea:** fases que no pueden cerrarse sin la decisión. **M4-B2** = promoción de maestros y contratos aprobados; **M5-B** = modelo y servicio de genealogía P1-07; **M4-B3** = activación controlada de Rebobinado en DEV; **H3+** = fase posterior de consumo/inventario (sin ID aún).
- **Clases:** **H1** habilitar P1-10/P1-29; **H2** implementar P1-07 y genealogía; **H3** circuito industrial completo (solo si VINTO confirma ese alcance); **P** mejoras posteriores que no bloquean lo anterior. Una decisión puede bloquear varias fases.
- Responsables propuestos (roles por confirmar por VINTO): **JP** Jefatura de Producción, **CAL** Calidad, **DB** Data Baltrek, **TI** Baltrek TI, **DIR** Dirección/sponsor de VINTO.
- IDs estables: no se reutilizan ni se renumeran aunque cambie la clase. Las decisiones que no tenían pregunta numerada en las fuentes están marcadas «derivada».

### Evidencia pendiente
La **matriz de homologación M1-B2-c1** (mencionada en `backend/README.md`: «vive fuera del repositorio») **no está disponible** en este repositorio y su contenido no se conoce ni se infiere. Es **evidencia pendiente**: si contiene respuestas, deben aportarse como evidencia en el acta; hasta entonces no cuenta como aprobación de nada.

## 2. Verificación contra las fuentes (esta revisión)
| Afirmación del paquete | Fuente verificada |
|---|---|
| Solo `VINTO-P1-06` es central en producción; Rebobinado no es operativo | `backend/app/capture_service.py` (`CENTRAL_FORM_CODES = frozenset({FORM_CODE})`); `backend/app/sectors.py` (`DEFAULT_OPERATIONAL_SECTORS = (SECTOR_BOBINAS,)`) |
| El bundle aprobado tiene 4 formularios (P1-03, 06, 19, 20), sector BOBINAS, MP1/MP3 y ningún P1-07/P1-10/P1-29 | `backend/seed_data/manifest.json` (`scope.forms`, `files[]`) |
| P1-07 legacy: 41 campos, 5 automáticos, `peso_cria_1..11` y `13..22`, máquinas `copasa/beloit/over`, sin campo de madre | `lib/vinto/form-definitions.ts` (anclado en `scripts/p107-contract.test.mjs`) |
| P1-10 legacy solo `copasa`; P1-29 legacy `tubertera` (sic) | `lib/vinto/form-definitions.ts` |
| Una captura origina como máximo UNA bobina numerada; el código visible no es único global; el correlativo es por (máquina, gestión) | `backend/migrations/0004_bobbin_production.sql` (`bobbin_source_capture_uidx`, `bobbin_legacy_code_uidx`, `bobbin_sequence`); `backend/app/bobbins/service.py` |
| Toda bobina numerada nace con `quality_release 'pending'`; ningún servicio libera o rechaza (el permiso `quality.release` existe sin uso) | `backend/app/bobbins/service.py`; `backend/app/quality/service.py` y `capture_service.py` (solo lectura / «NUNCA toca quality_release») |
| `bobbin_relation` sin cardinalidad, ciclos, reglas de máquina/sector ni inmutabilidad | pruebas `backend/tests/test_m5a_genealogy_feasibility.py` |

## 3. Matriz única de decisiones

### H1 · Habilitar P1-10 y P1-29
| ID | Tema | Pregunta de negocio | Alternativas | Origen | Base | Estado | Resp. | Evidencia necesaria | Impacto técnico | Bloquea | Criterio de aceptación |
|---|---|---|---|---|---|---|---|---|---|---|---|
| H1-01 | Máquinas | ¿Las máquinas de Rebobinado son exactamente COPASA, BELOIT, OVER, PERICHUN y TUBETERA? | Sí / No, lista corregida | M4-B1 P1 | F/L (candidato exportador) | Pendiente | JP | Lista firmada con código técnico y nombre visible | `machine` del bundle; alcance de OT/asignación | M4-B2, M4-B3, M5-B | Lista aprobada con códigos y nombres |
| H1-02 | Máquinas | ¿El nombre oficial de la tubetera es «Tubetera»? (legacy: `tubertera`) | Sí / No, otro nombre | M4-B1 P2 | L/F | Pendiente | JP | Nombre oficial por escrito | Código de máquina y vínculo formulario-máquina | M4-B2 | Código único confirmado |
| H1-03 | Alcance P1-10 | ¿P1-10 se usa solo en COPASA o en todas las rebobinadoras? | Solo COPASA / Todas / Otras: … | M4-B1 P3 | L (copasa)/F | Pendiente | JP | Tabla formulario × máquina | `form_version_machine` | M4-B2, M4-B3 | Tabla aprobada |
| H1-04 | Alcance P1-29 | ¿P1-29 se usa solo en TUBETERA? | Sí / No | M4-B1 P4 | L/F | Pendiente | JP | Tabla formulario × máquina | `form_version_machine` | M4-B2, M4-B3 | Tabla aprobada |
| H1-05 | Turnos | ¿Rebobinado trabaja dos turnos, DIA 06:00–18:00 y NOCHE 18:00–06:00? | Sí / No, horarios: … | M4-B1 P5 | F (provisional) | Pendiente | JP | Horarios firmados | `shift_schedule`; sin turno no hay asignación | M4-B2, M4-B3, M5-B | Horarios aprobados |
| H1-06 | Turnos | ¿Todas las máquinas del sector comparten esos horarios? | Sí / No (por máquina) | M4-B1 P6 | I (modelo por sector) | Pendiente | JP | Respuesta explícita | Si «por máquina»: cambio de modelo (incremento aparte) | M4-B2, M4-B3 | Respuesta registrada |
| H1-07 | Turnos | ¿Desde qué fecha rige el horario y cuál es la zona horaria? | Fecha …; zona … | M4-B1 P7 + matriz §1.B (zona, sin pregunta propia) | F (2026-01-01, America/La_Paz, técnicos) | Pendiente | JP, DB | Vigencia y zona reales | `valid_from`, `timezone` | M4-B2, M4-B3 | Valores reales aprobados |
| H1-08 | Turnos | ¿La fecha operativa del turno de noche es la del día en que empieza? | Sí / No | M4-B1 P8 | I (regla Bobinas) | Pendiente | JP | Confirmación para Rebobinado | Fecha operativa de capturas y asignaciones | M4-B2, M4-B3, M5-B | Regla confirmada |
| H1-09 | Turnos | ¿Es aceptable que Supervisión reactive la asignación en cada turno/día (asignación vencida bloquea capturas)? **derivada** | Sí / No, otra regla | M4-B1 matriz §1.B | I | Pendiente | JP | Confirmación del flujo | Comportamiento de `stale` | M4-B3 | Flujo aceptado |
| H1-10 | Artículos | ¿Los 241 artículos y su relación con las máquinas son los oficiales? | Sí / No, correcciones | M4-B1 P9 | F (candidato) | Pendiente | DB, JP | Lista oficial aprobada | `article`, `article_machine` | M4-B2, M4-B3, M5-B | Lista aprobada |
| H1-11 | Artículos | ¿`TB-4001` es el mismo artículo para Bobinas (MP3) y Tubetera? | Sí / No (separar) | M4-B1 P10 | F | Pendiente | JP | Confirmación | Relación en dos sectores | M4-B2 | Respuesta registrada |
| H1-12 | Contrato P1-10 | ¿El producto de P1-10 debe coincidir con el artículo de la línea de OT? **derivada** | Coincide / catálogo / libre | M2-B2 #3 (sin pregunta M4-B1) | F (texto libre) | Pendiente | JP | Regla escrita | Validación y selector | M4-B2 | Regla aprobada |
| H1-13 | Contrato P1-10 | ¿El número de fardo lo digita el operador o lo genera el sistema? | Manual / Central | M4-B1 P11 | F (manual libre) | Pendiente | JP, TI | Decisión escrita | Central = numerador + migración | M4-B2, M4-B3 | Decisión aprobada |
| H1-14 | Contrato P1-10 | ¿Tiene formato o unicidad el número de fardo (si central: alcance y reinicio)? | Libre / Formato … / Único por … | M4-B1 P12 | F | Pendiente | JP | Regla escrita | Validación/índice único | M4-B2 | Regla aprobada |
| H1-15 | Contrato P1-10 | ¿El peso del fardo es bruto o neto, con qué decimales y unidad? | … | M4-B1 P13 | F (texto) | Pendiente | JP, CAL | Especificación | Tipo y validación | M4-B2 | Especificación aprobada |
| H1-16 | Firmas | ¿P1-10 requiere firma/aprobación para ser válida (quién, cómo)? | Sí: … / No | M4-B1 P14 | O (no se captura) | Pendiente | JP, DIR | Mecanismo definido | Si exige aprobación, bloquea; modelo de firma | M4-B2, M4-B3 | Mecanismo aprobado o «no aplica» |
| H1-17 | Contrato P1-29 | ¿Rodelas y formatos son obligatorios y cuántas filas máximo? | Ambos / Solo uno / Ninguno; máx … | M4-B1 P15 | F (min 1, sin máx) | Pendiente | JP | Cardinalidad escrita | `min_rows`/`max_rows` del contrato publicado | M4-B2, M4-B3 | Cardinalidad aprobada |
| H1-18 | Contrato P1-29 | ¿Los tipos de tubete salen de un catálogo? | Catálogo: … / Texto libre | M4-B1 P16 | L (propone catálogo)/F (texto) | Pendiente | JP | Catálogo o aceptación de texto libre | Selector y validación (texto libre no bloquea) | — (puede aceptarse libre) | Respuesta registrada |
| H1-19 | Contrato P1-29 | ¿El espesor se mide en mm o en kg? | mm / kg | M4-B1 P17 | L (conflicto nombre/unidad) | Pendiente | JP, CAL | Unidad confirmada | Etiqueta y validación | M4-B2 | Unidad aprobada |
| H1-20 | Contrato P1-29 | ¿El número MRP lo digita el operador o lo genera el sistema? | Digitado / Generado | M4-B1 P18 | F (digitado) | Pendiente | JP, TI | Decisión | Integración/generación | M4-B2 | Decisión aprobada |
| H1-21 | Firmas | ¿P1-29 requiere operador y visto bueno de responsable (quién, cómo)? | Sí: … / No | M4-B1 P19 | O/F (no se almacenan) | Pendiente | JP, DIR | Mecanismo definido | Aprobación con efecto o registro simple | M4-B2, M4-B3 | Mecanismo aprobado o «no aplica» |
| H1-22 | Contrato P1-29 | ¿La fecha de producción es manual o la operativa de la asignación? **derivada** | Manual / Operativa | M3-B #7 | F (manual) | Pendiente | JP | Decisión | Campo y reportes | M4-B2 | Decisión aprobada |

### H2 · Implementar P1-07 y genealogía
| ID | Tema | Pregunta de negocio | Alternativas | Origen | Base | Estado | Resp. | Evidencia necesaria | Impacto técnico | Bloquea | Criterio de aceptación |
|---|---|---|---|---|---|---|---|---|---|---|---|
| H2-01 | Alcance de fases | ¿Genealogía madre/hija se implementa antes de habilitar Rebobinado o en una fase posterior? | Antes / Después | M4-B1 P20 (parte 2) | O | Pendiente | DIR, JP | Decisión de alcance | Orden M5-B vs M4-B3 | M4-B3, M5-B | Orden de fases aprobado |
| H2-02 | Identificación | ¿`etiqueta_numero_de_bobina` identifica la bobina de ENTRADA (madre) o de SALIDA? | Entrada / Salida / Ninguna | M5-A #1 | L (ambiguo) | Pendiente | JP | Aclaración escrita | Mapeo del campo | M5-B | Respuesta aprobada |
| H2-03 | Identificación | ¿Cómo se identifica la bobina madre en la ficha? | Selección de la bobina registrada en F3 / Escaneo / Texto | M5-A #2 | O (no hay campo) | Pendiente | JP, TI | Método elegido | Nuevo campo de madre (UUID) | M5-B | Método aprobado |
| H2-04 | Salidas | ¿Cada `peso_cria_*` es una bobina hija con identidad propia? | Sí / No, solo peso | M5-A #3 | F (hipótesis) | Pendiente | JP | Respuesta escrita | Crear bobinas vs registrar pesos | M5-B | Respuesta aprobada |
| H2-05 | Salidas | ¿Cuántas hijas admite una ficha y son obligatorias? | Mín … máx …; opcionales | M5-A #4 (parte 1) | L (21 obligatorios) | Pendiente | JP | Cardinalidad escrita | Grupo repetible `salidas` | M5-B | Cardinalidad aprobada |
| H2-06 | Salidas | ¿Se corrige la numeración sin `peso_cria_12`? | Error de fuente / posición vacía intencional | M5-A #4 (parte 2) | L | Pendiente | JP | Aclaración | Mapeo/migración de datos legacy | M5-B | Respuesta aprobada |
| H2-07 | Relación | ¿Una hija puede tener más de una madre? | No / Sí, hasta N | M5-A #5 | I (permitido sin control) | Pendiente | JP | Decisión | Restricción de unicidad | M5-B | Regla aprobada |
| H2-08 | Relación | ¿Una ficha consume una o varias madres? | Una / Varias | M5-A #6 | O | Pendiente | JP | Decisión | Contrato de madres | M5-B | Regla aprobada |
| H2-09 | Relación | ¿Puede la madre estar en otra máquina/sector (Bobinas → Rebobinado)? ¿Restricciones? | Libre / Solo … | M5-A #9 | I (sin regla) | Pendiente | JP | Reglas por sector/máquina | Trigger de coherencia | M5-B | Regla aprobada |
| H2-10 | Calidad | ¿Debe la madre estar liberada por Calidad para rebobinar? ¿Qué pasa si está pendiente o rechazada? | Exige liberada / permite pendiente / bloquea rechazada | M4-B1 P20 (parte 1) + M5-A #10 | O | Pendiente | CAL, JP | Política escrita | Validación de estado de madre | M5-B, M4-B3 si se exige | Política aprobada |
| H2-11 | Calidad | ¿Quién libera/rechaza una bobina y con qué flujo? | Rol: … | M5-A #11 | I (`quality.release` sin servicio) | Pendiente | CAL | Flujo | Servicio de liberación (no existe) | M5-B si H2-10 exige liberación | Flujo aprobado |
| H2-12 | Calidad | ¿Las hijas heredan el estado de Calidad o entran `pending` y pasan por Calidad? | Heredan / Pendiente | M5-A #12 | I (F3: nace pendiente) — **no se extiende a P1-07 sin aprobación** | Pendiente | CAL | Decisión | Estado inicial y bandeja | M5-B | Regla aprobada |
| H2-13 | Correlativo | ¿Las hijas usan el correlativo F3 de su máquina o uno propio? | F3 / Propio | M5-A #13 | I (compartiría el de F3) — **no se asume** | Pendiente | JP, TI | Decisión | Contador y unicidad | M5-B | Regla aprobada |
| H2-14 | Trazabilidad | ¿Se corrige o anula una relación registrada, quién y cómo? | Sin cambios / anulación con motivo / versión | M5-A #14 | I (mutable sin control) | Pendiente | JP, CAL | Política | Inmutabilidad/anulación | M5-B | Política aprobada |
| H2-15 | Trazabilidad | ¿Qué alcance de lectura tiene la genealogía entre sectores? | Si se ve un extremo / los dos / otro | M5-A #15 | O | Pendiente | JP, TI | Regla | Alcance de la consulta | M5-B | Regla aprobada |
| H2-16 | Máquinas P1-07 | ¿P1-07 se usa en COPASA, BELOIT y OVER (legacy) o en otras? | Esas tres / Otras: … | M5-A #16 | L | Pendiente | JP | Tabla formulario × máquina | `form_version_machine` | M5-B, M4-B2 | Tabla aprobada |
| H2-17 | Firmas | ¿P1-07 exige firma/responsable? | Sí: … / No | M5-A #18 | O | Pendiente | JP, DIR | Mecanismo | Modelo de firma | M5-B | Mecanismo aprobado o «no aplica» |
| H2-18 | Idempotencia | ¿Cómo se identifica de forma estable cada salida para reintentos? **derivada** (propuesta técnica: `output_key` por fila) | Propuesta TI aprobada / otra | M5-A §5 (sin pregunta) | I (propuesta) | Pendiente | TI | Aprobación del diseño | Índice único por (captura, `output_key`) | M5-B | Diseño aprobado |

### H3 · Circuito industrial completo (solo si VINTO confirma el alcance)
| ID | Tema | Pregunta de negocio | Alternativas | Origen | Base | Estado | Resp. | Evidencia necesaria | Impacto técnico | Bloquea | Criterio de aceptación |
|---|---|---|---|---|---|---|---|---|---|---|---|
| H3-01 | Consumo | ¿Se registra consumo parcial y sobrante de la madre? ¿En qué unidad y quién lo calcula? | Sí: … / No | M5-A #7 | O (sin cantidad en `bobbin_relation`) | Pendiente | JP | Decisión | Columnas de cantidad | H3+ | Decisión aprobada |
| H3-02 | Pesos | ¿Qué es `peso` (bruto/neto, entrada/salida) y cómo se registran mermas? | … | M5-A #8 | L (ambiguo) | Pendiente | JP, CAL | Definición | Balance de masas | H3+ | Definición aprobada |
| H3-03 | Alcance | ¿Inventario y balance de masas forman parte del alcance de VINTO y en qué fase? **derivada** | Sí, fase … / No | M4-B1 matriz §1.F, M5-A §7 | O | Pendiente | DIR | Decisión de alcance | Inventario no existe | H3+ | Alcance aprobado |

### P · Mejoras posteriores (no bloquean las fases anteriores)
| ID | Tema | Pregunta | Alternativas | Origen | Base | Estado | Resp. | Evidencia | Impacto | Bloquea | Criterio |
|---|---|---|---|---|---|---|---|---|---|---|---|
| P-01 | Catálogos | `producto_refilado`, `destino`, `formato_*`, `tubete`: ¿catálogo o texto libre? ¿Unidad de `formato_*` y `metraje`? | Catálogo / libre | M5-A #17 | L | Pendiente | JP, DB | Respuesta | Validación y selectores | — | Respuesta registrada |
| P-02 | Tipos de datos | Tipo definitivo de cantidades, pegamento y rangos de P1-29/P1-10 **derivada** | Texto / número; rangos … | M3-B #6, M2-B2 #2 | F | Pendiente | JP, CAL | Especificación | Validación | — | Especificación aprobada |
| P-03 | Maestros | Etiquetas reales de unidad, pesos nominales y recetas **derivada** | Incluir / no | M4-B1 matriz §1.C | O (`UNIT_LABEL_PLACEHOLDER`, sin pesos) | Pendiente | DB | Datos oficiales | Reportes | — | Datos aprobados o «no aplica» |
| P-04 | Presentación | Fecha operativa frente a calendario en reportes **derivada** | Operativa / calendario | M2-B2 #6 | I (operativa) | Pendiente | JP | Decisión | Reportes | — | Decisión registrada |

## 4. Trazabilidad de las 38 preguntas de origen (ninguna perdida)
**M4-B1 §7** → decisión: P1→H1-01 · P2→H1-02 · P3→H1-03 · P4→H1-04 · P5→H1-05 · P6→H1-06 · P7→H1-07 · P8→H1-08 · P9→H1-10 · P10→H1-11 · P11→H1-13 · P12→H1-14 · P13→H1-15 · P14→H1-16 · P15→H1-17 · P16→H1-18 · P17→H1-19 · P18→H1-20 · P19→H1-21 · P20→H2-10 y H2-01 (se divide: liberación de Calidad / genealogía desde el inicio).
**M5-A §6** → decisión: #1→H2-02 · #2→H2-03 · #3→H2-04 · #4→H2-05 y H2-06 · #5→H2-07 · #6→H2-08 · #7→H3-01 · #8→H3-02 · #9→H2-09 · #10→H2-10 (se fusiona con M4-B1 P20: misma pregunta de Calidad) · #11→H2-11 · #12→H2-12 · #13→H2-13 · #14→H2-14 · #15→H2-15 · #16→H2-16 · #17→P-01 · #18→H2-17.
Total: 20 + 18 = 38 preguntas de origen → **47 decisiones** (H1 22, H2 18, H3 3, P 4). Hay 2 divisiones (M4-B1 P20 y M5-A #4), 1 fusión (M4-B1 P20 ↔ M5-A #10, misma pregunta de Calidad) y 8 decisiones **derivadas** sin pregunta numerada (H1-09, H1-12, H1-22, H2-18, H3-03, P-02, P-03, P-04; H1-07 añade además la zona horaria de la matriz). Cobertura verificada por `scripts/m5b0-decisions.test.mjs`.

## 5. Dependencias entre fases
| Fase | Decisiones necesarias | Notas |
|---|---|---|
| **M4-B2** promoción de maestros y contratos | **Maestros:** H1-01, H1-02, H1-05…H1-08, H1-10, H1-11, H1-07. **Vínculos:** H1-03, H1-04 (+ H2-16 si P1-07 entra). **P1-10:** H1-12…H1-16. **P1-29:** H1-17, H1-19…H1-22 (H1-18 puede quedar texto libre) | Sin H1-13 «central» no hay migración; con «central» se añade un numerador (migración) |
| **M5-B** genealogía P1-07 | H2-01…H2-18 (H2-10/H2-11 solo si se exige liberación), más H1-01, H1-05…H1-08, H1-10 y H2-16 (maestros de P1-07). H3-* solo si consumo entra en esta fase | Requiere migración (0007+) según M5-A §7 |
| **M4-B3** activación controlada en DEV | M4-B2 completado; H1-09 y H1-16/H1-21 resueltos; H2-01 define si M5-B va antes; H2-10 si Calidad condiciona | Procedimiento: `docs/M4-B1-homologacion-rebobinado.md` §5 |
| **H3+** consumo/inventario | H3-01…H3-03 | Fase posterior sin ID |

## 6. Contrato técnico derivado (qué se hace y cuándo puede definirse)
**M4-B2 — Promoción de maestros y contratos aprobados** (tras las respuestas H1):
- Extender `scripts/export-seed-data.mjs` con las definiciones aprobadas de P1-10 y P1-29 (hoy solo emite P1-03/06/19/20) y promover el bundle por PR revisado; `--check` y pruebas de contrato.
- **Pendiente conservado:** mejorar las huellas de importación del ensayo (`backend/tests/rehearse_candidate_import.py`) para incorporar `article_version_spec` (gramaje estructurado) **antes de promover maestros reales**; hoy esas huellas no lo cubren aunque `candidate_report.py` compare el gramaje del bundle.
- Vincular formularios a las máquinas aprobadas; migración de numerador solo si H1-13 = central.
- Solo pueden definirse tras las respuestas: códigos y nombres de máquina, horarios y vigencia, lista de artículos, cardinalidad de grupos, unidades, tipos y mecanismo de firma.

**M5-B — Modelo y servicio de genealogía P1-07** (tras las respuestas H2):
- Migración aditiva (según M5-A §7): unicidad que admita N salidas por captura sin tocar F3, guardas de `bobbin_relation` (coherencia con la captura, sin ciclos, reglas de máquina/sector, inmutabilidad o anulación), idempotencia por `output_key`, definición oficial de P1-07, servicio/API y lectura de genealogía.
- Solo pueden definirse tras las respuestas: identificación de la madre, cardinalidades, estado de Calidad requerido, correlativo de hijas, política de corrección y alcance de lectura. **No se extienden a las hijas las reglas de F3 ni se interpreta `peso_cria_*` como bobinas hasta que VINTO lo apruebe.**

**M4-B3 — Activación controlada de Rebobinado en DEV:** respaldo y restauración validada, dry-run, importación aprobada, publicación de formularios homologados, cambio revisado de sector operativo, concesiones y smoke tests (procedimiento M4-B1 §5). Depende de M4-B2 y, según H2-01, de M5-B.

## 7. Checklist GO / NO GO actualizado
| # | Condición | Estado |
|---|---|---|
| 1 | Decisiones H1 aprobadas con evidencia (maestros, vínculos, contratos P1-10/P1-29) | **NO GO** (0 de 22 aprobadas) |
| 2 | Evidencia M1-B2-c1 aportada (si existe) | **Pendiente** |
| 3 | Bundle aprobado promovido por PR y `--check` OK | **NO GO** (no existe) |
| 4 | Huellas de importación incluyen `article_version_spec` | **NO GO** (pendiente) |
| 5 | Respaldo de DEV y restauración validada; dry-run sin conflictos | Pendiente (no ejecutado) |
| 6 | Decisiones H2 aprobadas (si H2-01 exige genealogía antes de habilitar) | **NO GO** |
| 7 | M5-B implementado y probado (si aplica) | **NO GO** (no existe) |
| 8 | Aprobación explícita de VINTO para activar Rebobinado | **NO GO** |
| 9 | Ensayo de importación idempotente, barreras DEV, E2E aislado, Bobinas/Calidad sin regresiones | GO (M4-A, M4-B1, M5-A) |
**Decisión actual: NO GO** para M4-B2 funcional, M5-B, M4-B3 y cualquier activación. Este paquete no cambia ese estado: solo permite resolverlo.
