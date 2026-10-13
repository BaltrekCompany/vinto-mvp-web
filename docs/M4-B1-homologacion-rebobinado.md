# M4-B1 · Preparación de homologación y habilitación de Rebobinado

**Estado: preparación documental y de verificación. Rebobinado NO está homologado, NO está habilitado y NO se tocó DEV.** Nada de lo que sigue autoriza importar, promover ni activar.
Base: `2ca1924` (PR #26). Se añaden: este documento, `backend/candidate_report.py` (informe de solo lectura) y `backend/tests/rehearse_candidate_import.py` (ensayo manual en bases `*_test`).

Convenciones. **H** = imprescindible para habilitar P1-10/P1-29 con datos reales. **C** = necesario para cerrar el circuito industrial completo de Rebobinado (no bloquea el registro técnico de P1-10/P1-29).
«Sin evidencia» significa que el repositorio no contiene una aprobación explícita de VINTO; **no se asume aprobada ninguna decisión**. La matriz de homologación previa (M1-B2-c1) vive fuera del repositorio y no pudo revisarse aquí: si contiene aprobaciones, deben aportarse como evidencia.
Responsables: roles propuestos, por confirmar por VINTO (Jefatura de Producción VINTO, Calidad VINTO, Data Baltrek, Baltrek TI).

## 1. Matriz de homologación

### A. Máquinas oficiales
| Decisión | Fuente actual | Evidencia | Responsable | Impacto | Bloqueo | Criterio de aceptación |
|---|---|---|---|---|---|---|
| Lista oficial de máquinas de Rebobinado: COPASA, BELOIT, OVER, PERICHUN, TUBETERA | `REBOBINADO_SECTOR` en `scripts/export-seed-data.mjs` (derivada de `GROUPS` y `PRODUCTS_BY_MACHINE` legacy); manifest: `SCOPE_PENDING_APPROVAL`, `MACHINE_NAME_FROM_CODE` | Candidatas técnicas; **sin aprobación** | Jefatura de Producción VINTO | Define `machine`, el alcance de OT/asignaciones y quién captura | H | Lista firmada con código técnico y nombre visible por máquina |
| Nombre real de la tubetera (`tubertera` en la definición legacy de P1-29 vs `TUBETERA`) | `allowedMachineIds: ["tubertera"]` en `form-definitions.ts` | Discrepancia documentada (M3-B) | Jefatura de Producción VINTO | Vínculo formulario–máquina | H | Código único confirmado |
| Máquinas de cada formulario: P1-10 (legacy: solo `copasa`) y P1-29 (solo tubetera) | `allowedMachineIds` legacy; fixtures usan COPASA / TUBETERA | Decisión #4 de M2-B2 abierta | Jefatura de Producción VINTO | `form_version_machine` = quién puede capturar | H | Tabla formulario × máquina aprobada |

Efectivamente aprobadas hoy: **ninguna** máquina de Rebobinado. Solo MP1 y MP3 (Bobinas) están en el bundle aprobado.

### B. Turnos
| Decisión | Fuente actual | Evidencia | Responsable | Impacto | Bloqueo | Criterio |
|---|---|---|---|---|---|---|
| Horarios de Rebobinado (candidato: DIA 06:00–18:00, NOCHE 18:00–06:00) | `REBOBINADO_SECTOR.shifts`; `SHIFT_VALIDITY_PROVISIONAL` | Provisional. Bobinas aprobado: 07:00–19:00 / 19:00–07:00 | Jefatura de Producción VINTO | Sin turno resoluble no hay asignación ni captura | H | Horarios por sector (o por máquina) firmados |
| ¿Horario por sector o por máquina? (el modelo actual es por sector) | `shift_schedule(shift, sector)` | Sin evidencia de que todas las máquinas compartan horario | Jefatura de Producción VINTO | Si difiere por máquina, requiere cambio de modelo | H | Respuesta explícita; si «por máquina», incremento aparte |
| Zona horaria y vigencia | `America/La_Paz`, `valid_from 2026-01-01` (técnicos) | Provisionales | Data Baltrek + VINTO | Fecha operativa y cierre de turno | H | Zona y vigencia reales; `valid_to` si aplica |
| Fecha operativa del turno nocturno (candidato: día en que EMPIEZA) | Regla `shift_night_rule` del exportador | Igual que Bobinas; sin confirmación para Rebobinado | Jefatura de Producción VINTO | Agrupa capturas y asignaciones vencidas | H | Confirmación de la regla |
| Cambio de día con asignación activa | Backend marca `stale` y bloquea capturas (M2-A) | Comportamiento verificado en E2E (M4-A) | Jefatura de Producción VINTO | Operación debe reactivar la asignación en cada turno | C | Confirmar que el flujo «reasignar por turno» es aceptable |

### C. Artículos
| Decisión | Fuente actual | Evidencia | Responsable | Impacto | Bloqueo | Criterio |
|---|---|---|---|---|---|---|
| Códigos y descripciones oficiales | `PRODUCTS_BY_MACHINE` / `MATERIALS` legacy (241 artículos en el candidato) | Candidatos; **sin aprobación** | Data Baltrek + VINTO | Catálogo de OT | H | Lista oficial aprobada |
| Relación artículo–máquina (242 relaciones; COPASA 72, OVER 53, BELOIT 20, PERICHUN 2, TUBETERA 2) | Derivada de `PRODUCTS_BY_MACHINE` | Candidata | Jefatura de Producción VINTO | Una OT solo admite artículos vinculados a su máquina | H | Relación aprobada por máquina |
| Unidad: 237 en KG y 4 en UN (rollos de PERICHUN y tubetes de TUBETERA); etiquetas de unidad = código (`UNIT_LABEL_PLACEHOLDER`) | Catálogo legacy | Placeholder | Data Baltrek | Presentación y reportes | C | Etiquetas reales |
| Artículo `TB-4001` vinculado a MP3 (Bobinas) y a TUBETERA | Catálogo legacy | Único artículo en dos sectores | Jefatura de Producción VINTO | ¿Es el mismo ítem? Afecta OT de ambos sectores | H | Confirmar o separar |
| Correspondencia artículo–OT | OT de Rebobinado se crean con artículos del backend (M4-A) | Verificado en E2E ficticio | VINTO | Ninguno si lo anterior se aprueba | H | Prueba con artículos oficiales |
| Pesos nominales y recetas | `nominal_weights: false`; fuera de alcance | No existen en el candidato | VINTO | Solo reportes de rendimiento | C | Decisión de incluirlos o no |

### D. P1-10 «Registro de fardos»
| Decisión | Fuente actual | Evidencia | Responsable | Impacto | Bloqueo | Criterio |
|---|---|---|---|---|---|---|
| Alcance por máquina (legacy: COPASA; candidato conoce 5 máquinas) | Ver A | #4 de M2-B2 abierta | Jefatura de Producción VINTO | Vínculo `form_version_machine` | H | Ver A |
| Número de fardo: manual (texto libre hoy) o correlativo central | Fixture: texto sin formato ni unicidad | #1 abierta | Jefatura de Producción VINTO + Baltrek TI | Correlativo central **requiere migración y numerador** | H si central; C si manual | Decisión; si central, diseño aprobado |
| Peso del fardo: tipo, decimales, unidad, rango | Fixture: texto tal cual | #2 abierta | Calidad/Producción VINTO | Validación y agregados | C | Especificación |
| Relación producto ↔ línea de OT | Fixture: texto libre; la línea se muestra como contexto | #3 abierta | VINTO | Validación | C | Regla aprobada |
| Responsable y firma/aprobación | No se capturan | #5 abierta | VINTO | Si la ficha exige aprobación para ser válida, bloquea | H si exige aprobación | Mecanismo definido |

### E. P1-29 «Producción Tubetera»
| Decisión | Fuente actual | Evidencia | Responsable | Impacto | Bloqueo | Criterio |
|---|---|---|---|---|---|---|
| Grupos `rodelas` / `formatos` y cardinalidad (hipótesis de prueba: repetibles, mínimo 1, sin máximo) | Fixture `m3b_fixtures`; **no existen en la definición legacy** | #1 de M3-B abierta | Jefatura de Producción VINTO | Define el contrato publicado | H | Agrupación y `min_rows`/`max_rows` aprobados |
| Tipo de tubete: catálogo controlado o texto libre | Texto libre | #4 abierta | VINTO | Selector y validación | C | Catálogo o aceptación de texto libre |
| Cantidades (producidos, observados, hojas): texto hoy | Texto | #6 abierta | VINTO | Validación y reportes | C | Tipo definitivo |
| Unidad del espesor (campo `…_mm…`, metadata legacy `kg`) | Discrepancia | #5 abierta | Calidad/Producción VINTO | Etiqueta y validación | C | Unidad confirmada |
| Número MRP: digitado o generado/validado | Digitado | #8 abierta | VINTO + Baltrek TI | Integración | C | Decisión |
| Operador y visto bueno | No se almacenan | #3 abierta | VINTO | Si la ficha exige visto bueno, bloquea | H si lo exige | Mecanismo definido |
| Fecha de producción manual vs fecha operativa | Manual | #7 abierta | VINTO | Reportes | C | Decisión |

### F. Dependencias del circuito industrial completo
| Decisión | Fuente actual | Evidencia | Responsable | Impacto | Bloqueo | Criterio |
|---|---|---|---|---|---|---|
| P1-07 y genealogía bobina madre/hija | Fuera de alcance de M1–M4-A | No implementado | VINTO + Baltrek TI | Trazabilidad entre Bobinas y Rebobinado | C (no bloquea P1-10/P1-29) | Alcance y diseño aprobados |
| Consumo parcial de bobinas | Sin modelo | No implementado | VINTO | Inventario | C | Regla aprobada |
| Liberación por Calidad antes de rebobinar | El inbox de Calidad existe para Bobinas | Sin vínculo con Rebobinado | Calidad VINTO | ¿Se exige liberación para consumir? | C | Regla aprobada |

**Para habilitar P1-10/P1-29 (H)**: máquinas aprobadas (A), horarios/vigencia/regla de fecha operativa (B), artículos y relaciones aprobados incl. `TB-4001` (C), alcance por máquina y decisión de correlativo/firma de P1-10 (D), cardinalidad de grupos y visto bueno de P1-29 (E).
**Para cerrar el circuito (C)**: todo lo marcado C, incluida la sección F.

## 2. Catálogo candidato `candidate-rebobinado`
Generado con `node scripts/export-seed-data.mjs --scope candidate-rebobinado --out <dir nuevo>` (no modifica `backend/seed_data`; `git status` limpio). Se revisó con `python candidate_report.py <dir>` (solo lectura; usa `load_bundle`, así que valida manifest, SHA-256, tamaños, conteos y referencias; resultado: **íntegro**).

| Categoría | Resultado |
|---|---|
| Coincide con lo aprobado | Sector, máquinas, horarios, relaciones artículo-máquina y los 4 formularios de Bobinas, perfiles y unidades son **idénticos** al bundle aprobado |
| Candidato pendiente de aprobación | Sector REBOBINADO; 5 máquinas; 2 horarios (DIA 06–18, NOCHE 18–06); 148 artículos relacionados solo con máquinas candidatas; 242 relaciones en total (241 artículos) |
| Conflictos / alertas | `TB-4001` en dos sectores (MP3 y TUBETERA); DIA/NOCHE comparten código entre sectores con horas distintas (diseño previsto: horario por sector); etiquetas de unidad = código; `MACHINE_NAME_FROM_CODE`, `P1_20_PROVISIONAL_CONTRACT`, `WORKFLOW_NAME_PLACEHOLDER`, `SHIFT_VALIDITY_PROVISIONAL`, `SCOPE_PENDING_APPROVAL`; PERICHUN y TUBETERA tienen solo 2 artículos cada una |
| Faltantes | Formularios P1-10 y P1-29 (no existen en el bundle); ningún formulario vinculado a máquinas de Rebobinado; pesos nominales y recetas |
| Impacto si se importara | Se crearían un sector, 5 máquinas, 148 artículos nuevos y 149 relaciones nuevas con datos **sin aprobar**; sin formularios ni concesiones no habría operación, pero el catálogo de OT mostraría datos no validados y quedaría auditado como importación de DEV |

No se editó nada para que «pase»: las inconsistencias se reportan tal cual.

## 3. Ensayo de importación en PostgreSQL efímero
`backend/tests/rehearse_candidate_import.py <dir candidato>` (bases nuevas `*_test`, eliminadas al terminar; nunca usa `DATABASE_URL`). Resultado real (ver `vinto-backups/m4b1/ensayo.txt`):

| Escenario | Dry-run | Apply | Segundo apply | Verificación |
|---|---|---|---|---|
| A · base migrada vacía | pending, 0 conflictos, 1045 filas; no escribe | `applied`, 1045 filas | `noop` (sin batch nuevo), 1 batch completado | 2 sectores, 7 máquinas, 241 artículos, 242 relaciones, 4 horarios; 0 formularios vinculados a Rebobinado; 0 concesiones; 0 capturas; dry-run final `consistent` |
| B · base con bundle aprobado (estado de DEV) | pending, 0 conflictos, 601 filas | `applied`, 601 filas | `noop` | Mismas cardinalidades; **máquinas y relaciones de Bobinas idénticas** (hash antes/después) |

Barreras hacia DEV (sin abrir conexión): `assert_dev_apply_allowed` rechaza un directorio candidato y `assert_bundle_not_candidate_for_dev` rechaza el manifest candidato; `reference.apply` además rechaza un candidato en cualquier base que no termine en `_test`. No se ejecutó `--target dev --apply`.
Lectura única de DEV (solo `SELECT`, transacción de solo lectura) para describir el punto de partida: sector BOBINAS, 2 máquinas, 93 artículos, 8 vínculos formulario–máquina, migraciones 0001–0006, 13 capturas, 5 concesiones (todas BOBINAS).

## 4. Plan de promoción de P1-10 y P1-29 (futuro, no ejecutado)
Hoy ambos existen solo como fixtures de prueba (`tests/m2b2_fixtures.py`, `m3b_fixtures.py`) instalados en bases efímeras. **No** se copian al bundle oficial.

| Aspecto | P1-10 | P1-29 |
|---|---|---|
| Campos (fixture) | 4 manuales, todos texto/textarea | 6 simples + grupo `rodelas` (2) + grupo `formatos` (9) |
| Contexto no almacenado | fecha, máquina, responsable, firma | operador, turno, visto bueno |
| Máquinas | fixture: COPASA | fixture: TUBETERA (ficticia) |
| Reglas ya soportadas por el motor | idempotencia, texto sin conversión, asignación vigente | idem + grupos repetibles (M3-A) |
| Requiere migración | Solo si el correlativo es central (numerador) | Solo si se exige visto bueno con efecto de aprobación o catálogo de tubetes como tabla |
| No promovible aún | Sin decisión de correlativo/firma, máquinas ni formato | Grupos y cardinalidad son **hipótesis de prueba**; unidad del espesor sin confirmar |

Pasos futuros: (1) decisiones aprobadas (sección 1); (2) extender `scripts/export-seed-data.mjs` con las definiciones aprobadas (el exportador hoy solo emite P1-03/06/19/20 y verifica contra `form-definitions.ts`; el bloque `groups` ya existe en el esquema del bundle) mediante PR revisado; (3) `--check` y pruebas de contrato; (4) publicar versión por el importador; (5) recién entonces añadir el código a `CENTRAL_FORM_CODES` (cambio de código separado). Los `allowedMachineIds` legacy (`copasa`, `tubertera`) no deben usarse tal cual.

## 5. Procedimiento de despliegue en DEV (SOLO tras aprobación; no ejecutado)
1. **Git y checkout**: `git status` limpio, rama = `main` en el commit aprobado, sin cambios locales; sin mezclar con trabajo en curso.
2. **Respaldo**: `pg_dump -Fc` de la base DEV (desde el contenedor de PostgreSQL) a un archivo fuera del repositorio; **validar la restauración** en una base nueva `*_test` (`pg_restore`) y comparar conteos de capturas, auditoría, sesiones, concesiones y maestros.
3. **Migraciones**: `python migrate.py --status` y `--check` (solo lectura); DEV está en 0006.
4. **Promoción revisada del bundle aprobado**: PR que actualiza `backend/seed_data` con datos aprobados; `node scripts/export-seed-data.mjs --check`; tests de backend y del exportador.
5. **Dry-run contra DEV**: `python import_reference.py --target dev` (sin `--apply`); conflicto/drift = detener.
6. **Importación aprobada**: `python import_reference.py --target dev --apply` (solo bundle oficial; la barrera rechaza candidatos).
7. **Validaciones posteriores**: conteos de sector/máquinas/artículos/relaciones/turnos; Bobinas (MP1/MP3, relaciones, 8 vínculos) sin cambios; segundo dry-run `consistent`; resolución de turnos para fechas de borde.
8. **Formularios homologados**: publicar versiones y vínculos (incremento aparte); añadir códigos a `CENTRAL_FORM_CODES` en un PR revisado.
9. **Sector operativo**: PR que añade `REBOBINADO` a `DEFAULT_OPERATIONAL_SECTORS`; reinicio del backend.
10. **Concesiones**: alta por usuario mediante la API administrativa por personas autorizadas (grant ≠ operativo).
11. **Smoke tests** (con usuarios reales de prueba): Bobinas (OT, F3/F6), Calidad (humedad/propiedades), Rebobinado (`/api/production/machines`, OT → asignación → P1-10/P1-29 → historial); `E2E_REBOBINADO` solo en entorno de prueba.
12. **Reversión** (tres niveles distintos):
    - *Código*: revertir el PR / volver al commit anterior y reiniciar el backend. No deshace datos.
    - *Bloqueo del sector*: quitar `REBOBINADO` de `DEFAULT_OPERATIONAL_SECTORS` (y/o los códigos de `CENTRAL_FORM_CODES`): la API deja de exponerlo y rechaza capturas (422). **No revierte la importación**: maestros, auditoría y concesiones permanecen.
    - *Datos*: la importación no tiene operación inversa (`ON DELETE RESTRICT`, auditoría inmutable). La única reversión completa es restaurar el respaldo, lo que **descarta todo lo escrito después** (también capturas de Bobinas); por eso el respaldo se toma justo antes y la importación se hace en ventana tranquila. Alternativa lógica: desactivar máquinas (`active = false`, no se ofrecen), mediante SQL revisado, sin borrar.

## 6. Checklist GO / NO GO (activación de Rebobinado en DEV)
| # | Condición | Estado hoy |
|---|---|---|
| 1 | Máquinas, nombres y vínculos formulario–máquina aprobados | **NO GO** |
| 2 | Turnos, zona, vigencia y regla de fecha operativa aprobados | **NO GO** |
| 3 | Artículos y relaciones aprobados (incl. `TB-4001`) | **NO GO** |
| 4 | P1-10: correlativo/firma decididos | **NO GO** |
| 5 | P1-29: grupos, cardinalidad y visto bueno decididos | **NO GO** |
| 6 | Bundle aprobado promovido por PR y `--check` OK | **NO GO** (no existe) |
| 7 | Respaldo de DEV tomado y restauración validada | Pendiente (no ejecutado) |
| 8 | Dry-run contra DEV sin conflictos | Pendiente |
| 9 | Ensayo de importación + idempotencia en `*_test` | **GO** (sección 3) |
| 10 | Barreras del importador/DEV y sector operativo verificadas | **GO** (pruebas existentes + este ensayo) |
| 11 | E2E real del circuito en entorno aislado | **GO** (M4-A: 50/50 y 13/13) |
| 12 | Bobinas/Calidad sin regresiones | **GO** (suites) |
| 13 | Aprobación explícita de VINTO para activar | **NO GO** |
Decisión actual: **NO GO** (1–8 y 13 abiertos).

## 7. Preguntas para VINTO (cerradas cuando es posible)
1. ¿Las máquinas de Rebobinado son exactamente COPASA, BELOIT, OVER, PERICHUN y TUBETERA? (Sí / No, lista corregida)
2. ¿El nombre oficial de la tubetera es «Tubetera»? (Sí / No)
3. ¿P1-10 se usa solo en COPASA o en todas las rebobinadoras? (Solo COPASA / Todas / Otras: …)
4. ¿P1-29 se usa solo en TUBETERA? (Sí / No)
5. ¿Rebobinado trabaja dos turnos, DIA 06:00–18:00 y NOCHE 18:00–06:00? (Sí / No, horarios: …)
6. ¿Todas las máquinas del sector comparten esos horarios? (Sí / No)
7. ¿Desde qué fecha rige este horario? (fecha)
8. ¿La fecha operativa del turno de noche es la del día en que empieza? (Sí / No)
9. ¿La lista de 241 artículos y su relación con las máquinas es la oficial? (Sí / No, correcciones)
10. ¿`TB-4001` es el mismo artículo para Bobinas (MP3) y Tubetera? (Sí / No)
11. ¿El número de fardo lo digita el operador o lo genera el sistema? (Manual / Central)
12. Si es manual, ¿tiene formato o unicidad? (Libre / Formato: … / Único por: …). Si es central, ¿alcance y reinicio?
13. ¿El peso del fardo es bruto o neto, y con cuántos decimales y en qué unidad? (…)
14. ¿La ficha P1-10 requiere firma/aprobación para ser válida? (Sí / No); si sí, ¿quién y cómo?
15. ¿En P1-29, rodelas y formatos son obligatorios? (Ambos / Solo uno / Ninguno) y ¿cuántas filas máximo? (…)
16. ¿Los tipos de tubete salen de un catálogo? (Sí, lista: … / Texto libre)
17. ¿El espesor se mide en mm o en kg? (mm / kg)
18. ¿El número MRP lo digita el operador? (Sí / Lo genera el sistema)
19. ¿P1-29 requiere operador y visto bueno de responsable? (Sí: quién y cómo / No)
20. ¿Rebobinar exige liberación previa de Calidad y genealogía madre/hija desde el inicio? (Sí / No, fase posterior)

## 8. Verificación realizada
- `python candidate_report.py` sobre el candidato: íntegro; diferencias detalladas en §2.
- Ensayo de importación e idempotencia en bases efímeras: §3 (TODO OK).
- Pruebas: `tests/test_candidate_report.py` (3) y las suites existentes (backend, Node, exportador, barreras de importación, sector operativo, disponibilidad y coherencia de formularios y máquinas) sin regresiones.
- Reproducir: exportar el candidato a un directorio nuevo; `python candidate_report.py <dir>`; `python tests/rehearse_candidate_import.py <dir>` (requiere `TEST_DATABASE_URL`).
