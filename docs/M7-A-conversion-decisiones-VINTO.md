# M7-A · Matriz única de decisiones de Conversión (36)

**Estado: documental. Ninguna decisión está aprobada.** No se implementa ninguna regla industrial; no se tocó DEV, catálogos, permisos, concesiones ni configuración; no hay migraciones. Conversión y Rebobinado siguen NO homologados y NO operativos. Una prueba E2E que pasa o un fixture que funciona **no** aprueba nada.
Consolida, sin cambiar su texto, estado ni procedencia, las decisiones de [M6-A](M6-A-conversion-central-p116.md) (`CV:C-1` a `CV:C-11`), [M6-B](M6-B-conversion-p112.md) (`CV:P-1` a `CV:P-11`), [M6-C](M6-C-conversion-p113.md) (`CV:N-1` a `CV:N-8`) y [M6-D](M6-D-conversion-p111.md) (`CV:B-1` a `CV:B-6`). Entrada del paquete: [índice M7-A](M7-A-homologacion-indice.md). Agenda y registro: [M7-A agenda y registro](M7-A-agenda-y-registro-conversion.md).
Base: `26472007d5dfed89842fa2b5ea2920cdec115d81` (PR #33).

## 1. Cómo leer este documento
- **Clave única `(frente, ID)`.** Los identificadores originales se conservan literalmente; en este paquete se escriben con prefijo: **`CV:`** = Conversión (esta matriz: 11 C + 11 P + 8 N + 6 B = **36**) y **`RB:`** = Rebobinado y genealogía ([M5-B0](M5-B0-decisiones-VINTO.md): `RB:H1`, `RB:H2`, `RB:H3` y `RB:P-01` a `RB:P-04`). `CV:P-2` (número oficial de pallet) y `RB:P-02` (tipos de datos de P1-29 y P1-10) son decisiones distintas: sin prefijo se confundirían.
- **Las preguntas históricas `P1` a `P20` de [M4-B1 §7](M4-B1-homologacion-rebobinado.md) no son decisiones de esta matriz**: ya están trazadas a `RB:H1-xx` y `RB:H2-xx` en la §4 de M5-B0.
- **Fuente de verdad de Rebobinado y genealogía: M5-B0.** Esta matriz **no copia** sus 47 decisiones: solo enlaza (`RB:…`) las que comparten una dependencia con Conversión, sin cambiar sus estados.
- **Estados y criterios de evidencia: exactamente los de [M5-B0 acta §1 y §2](M5-B0-acta-homologacion.md)** (Pendiente → Respondido, sin evidencia → En revisión → Aprobado; Rechazado / requiere rediseño). Aquí no se redefinen. **Las 36 decisiones están en Pendiente**: no hay evidencia explícita en el repositorio que apruebe ninguna.
- **Responsables propuestos** (roles por confirmar por VINTO, como en M5-B0): **JP** Jefatura de Producción, **CAL** Calidad, **DB** Data Baltrek, **TI** Baltrek TI, **DIR** Dirección/sponsor de VINTO.
- **Desbloquea:** incrementos del roadmap del [índice](M7-A-homologacion-indice.md) §9 (M7-B maestros, M7-C contratos, M7-D cálculo, M7-E bobinas y genealogía, M7-F Calidad e inventario, M7-G piloto aislado, M7-H activación controlada).
- **Frentes:** **A** Maestros (máquinas, artículos, relaciones, turnos, pesos nominales, recetas); **B** Formularios (unidad de registro, obligatoriedad, campos, firmas, numeración); **C** Cálculos industriales (pesos, consumos, balances, mermas, producción); **D** Integración (genealogía, Calidad, inventario, doble conteo).
- **Clase propuesta PF / OP / LT** (definiciones en el [índice](M7-A-homologacion-indice.md) §5): es una **clasificación propuesta, condicional al alcance que VINTO confirme**. Cada decisión tiene **una sola** clase base; las condiciones que la cambiarían se anotan aparte y **no duplican** la decisión en los conteos.

## 2. Matriz de decisiones
| ID | Formulario / sector | Pregunta que VINTO debe responder | Alternativas de respuesta | Fuente y evidencia existente | Resp. | Estado | Evidencia necesaria | Desbloquea |
|---|---|---|---|---|---|---|---|---|
| CV:C-1 | P1-16 | ¿Qué es P1-16: la ficha con una columna de kg por tipo de merma, correlativo y total (definición) o una pesada por registro (pantalla)? | Definición legacy / Una pesada por registro / Otra | M6-A §3 y §7; definición legacy (14 campos) y `WasteCapture` de `app/page.tsx`. Existente: hipótesis de prueba (la pantalla); nada aprobado | JP | Pendiente | Ficha en papel vigente de P1-16 y decisión escrita | M7-C |
| CV:C-2 | P1-16 (numeración) | ¿Existe un correlativo de merma? ¿Manual o central, con qué alcance, formato y reinicio? | No existe / Manual / Central: alcance …, formato … | M6-A §7; legacy `numero_correlativo` (texto manual). Existente: no se genera ninguno | JP, TI | Pendiente | Decisión escrita y ejemplo real de numeración | M7-C (si es central, una migración en su propio incremento) |
| CV:C-3 | P1-16 (cálculo) | ¿Cuál es la fórmula del total de merma y quién la calcula? | Suma de columnas calculada en servidor / Se registra sin calcular / Otra fórmula | M6-A §3 y §7; legacy `total_merma_kg` calculado, sin fórmula en la definición. Existente: no se calcula | JP, CAL | Pendiente | Fórmula escrita con ejemplo numérico | M7-D |
| CV:C-4 | Fichas de Conversión (firmas) | ¿Las fichas exigen firma de operador y de encargada? ¿Qué son «grupo» y «encargado de turno»? | Sí: mecanismo … / No aplica | M6-A §7; legacy campos automáticos `firma_*`, `grupo`, `encargado_de_turno`; el modelo central no los tiene. Existente: no se capturan ni se simulan | JP, DIR | Pendiente | Mecanismo definido, o «no aplica» firmado | M7-C |
| CV:C-5 | Transversal (pesos y cantidades) | ¿Qué unidad, rango y decimales tienen los pesos y las cantidades? | kg con N decimales / Otra unidad … / Rangos … | M6-A §7; legacy tipos `text` y `decimal` sin unidad homologada. Existente: solo se exige un decimal válido | JP, CAL | Pendiente | Especificación escrita (unidad, decimales, rango) | M7-D (el formato, en M7-C) |
| CV:C-6 | P1-16, P1-11, P1-12 y P1-13 (máquinas) | ¿En qué máquinas se usa cada formulario? (P1-16 dice «todas») | Tabla formulario × máquina | M6-A §7; `allowedMachineIds` legacy. Existente: fixtures ficticios GAMBINI y WALLY | JP | Pendiente | Tabla formulario × máquina aprobada | M7-B, M7-C |
| CV:C-7 | Sector Conversión (turnos) | ¿Cuáles son los horarios, la vigencia y la regla de fecha operativa de los turnos? | Mañana 06–14 / Tarde 14–22 / Noche 22–06 (hipótesis legacy) / Otros; fecha operativa del día en que empieza el turno / Otra | M6-A §7; `ctx()` de `app/page.tsx` y sector candidato del exportador. Existente: provisional, sin aprobar | JP, DB | Pendiente | Horarios y vigencia firmados | M7-B |
| CV:C-8 | Sector Conversión (turnos) | ¿El horario es por sector o por máquina? | Por sector / Por máquina | M6-A §7; el modelo actual es por sector. Existente: implementado, no aprobado | JP | Pendiente | Respuesta explícita | M7-B (si «por máquina», un incremento de modelo propio) |
| CV:C-9 | Sector Conversión (maestros) | ¿Son oficiales las 11 máquinas, los artículos y las relaciones artículo-máquina (98 candidatas, 74 artículos únicos), la unidad `Pack` y la clase `BLANCOS`? | Sí / No, con correcciones | M6-A §2 y §7; catálogos legacy (`catalogs.ts`) y exportador. Existente: candidato, sin aprobar | DB, JP | Pendiente | Listas oficiales firmadas | M7-B |
| CV:C-10 | Datos legacy de Conversión | ¿Qué se hace con los registros de Conversión que existen en los navegadores (`vinto-p1-records`)? | Descartar / Conservar / Importar | M6-A §5 y §7. Existente: se conservan intactos y no se muestran | DIR, TI | Pendiente | Decisión escrita | M7-G y M7-H (antes de cualquier uso real) |
| CV:C-11 | Maestro de pesos nominales | ¿Se usa el maestro de pesos nominales (`INArticulo-MFMatrialOP`) y cómo se convierten las cantidades? | Sí, versión … / No | M6-A §7; `product-weights.ts`. Existente: no se usa | DB, JP | Pendiente | Maestro oficial aprobado, o «no aplica» | M7-B, M7-D |
| CV:P-1 | P1-12 | ¿Qué es P1-12: la ficha diaria de 37 campos (balances, mermas, total) o un pallet por envío con jabas y horas? | Ficha diaria / Un pallet por envío / Otra | M6-B §2, §3 y §7; legacy 37 campos y `PalletProduction`. Existente: hipótesis de prueba (pallet) | JP | Pendiente | Ficha en papel vigente de P1-12 y decisión escrita | M7-C |
| CV:P-2 | P1-12 (numeración) | ¿Existe número oficial de pallet? ¿Manual o central, con alcance (máquina/día/turno), formato, reinicio, huecos y correcciones? | No existe / Manual / Central: … | M6-B §4 y §7; el `PAL-AAAAMMDD-XXXXXX` legacy es aleatorio y no es un correlativo. Existente: solo el `capture_id` técnico | JP, TI | Pendiente | Decisión escrita y formato ejemplo | M7-C (si es central, una migración en su propio incremento) |
| CV:P-3 | P1-12 (maestro de pesos) | ¿Cuál es el peso nominal oficial por artículo, su unidad, decimales y vigencia, y qué ocurre si falta? | Maestro … / Sin peso | M6-B §4 y §7; `product-weights.ts`. Existente: no se usa ni se acepta del navegador | DB, JP | Pendiente | Maestro oficial de pesos nominales | M7-B, M7-D |
| CV:P-4 | P1-12 (cálculo) | ¿El peso total del pallet es un dato oficial guardado o derivado? ¿Con qué redondeo y quién lo calcula? | Guardado / Derivado al consultar / No se calcula | M6-B §4 y §7; prueba pura con pesos sintéticos y decimales exactos. Existente: no se calcula ni se guarda | JP, CAL | Pendiente | Regla escrita | M7-D |
| CV:P-5 | P1-12 | ¿Hay mínimo o máximo de jabas, o relación con la cantidad de la OT o la receta? | Sin límites / Límites … / Relación … | M6-B §4 y §7; entero con signo, solo estructural. Existente: sin límites | JP | Pendiente | Regla escrita | M7-C |
| CV:P-6 | P1-12 | ¿Son obligatorias las horas del pallet? ¿La hora de fin debe ser posterior? ¿Cómo se relacionan con el turno y la medianoche? | Libres / Reglas … | M6-B §4 y §7. Existente: dos horas libres | JP | Pendiente | Regla escrita | M7-C |
| CV:P-7 | P1-12 | ¿Un pallet por ficha o varios pallets agrupados en una ficha (grupo repetible)? | Un pallet por ficha / Varios (grupo, cardinalidad …) | M6-B §7. Existente: un pallet por captura | JP | Pendiente | Decisión escrita | M7-C |
| CV:P-8 | P1-12 (balances) | ¿Se capturan los balances de empaque, subempaque, bolsa, segundas y asas, la merma y el total de producción? ¿Quién calcula los 8 campos calculados? | Se capturan / Fuera de alcance | M6-B §2 y §7; legacy campos 6 a 37. Existente: fuera del contrato candidato | JP | Pendiente | Decisión y fórmulas escritas | M7-C y M7-D |
| CV:P-9 | P1-12 (firmas) | ¿Se exige firma de operador y de encargada, y qué son «grupo» y operador de la ficha? | Sí: mecanismo … / No aplica | M6-B §7; legacy `firma_operador`, `firma_encargada`, `grupo`. Existente: no se capturan | JP, DIR | Pendiente | Mecanismo definido, o «no aplica» firmado | M7-C |
| CV:P-10 | P1-12, P1-11 y P1-16 (integración) | ¿Cómo se relaciona el pallet con inventario, con las bobinas consumidas (P1-11) y con la merma (P1-16)? | Sin relación / Relación … | M6-B §7. Existente: sin relaciones | JP, TI | Pendiente | Decisión escrita | M7-E y M7-F |
| CV:P-11 | P1-12 (máquinas) | ¿En qué máquinas se usa P1-12? | Gambini, Sincro II y Sincro III (legacy) / Otras | M6-B §7; `allowedMachineIds` legacy. Existente: solo GAMBINI ficticia | JP | Pendiente | Tabla formulario × máquina aprobada | M7-B, M7-C |
| CV:N-1 | P1-13 | ¿Cuál es la unidad de registro: una ficha por turno con bobina, insumos y producción, o capturas separadas? | Una ficha por turno / Capturas separadas / Otra | M6-C §3 y §10; legacy 31 campos y `NapkinSheet`. Existente: contrato candidato de 8 campos | JP | Pendiente | Ficha en papel vigente de P1-13 y decisión escrita | M7-C |
| CV:N-2 | P1-13 (receta) | ¿La receta es obligatoria? ¿Quién valida bobina e insumo contra ella? | Obligatoria / Referencia / No se usa | M6-C §7 y §10; recetas legacy (20 de 22 artículos de las máquinas de P1-13 tienen receta). Existente: no se usa | JP, DB | Pendiente | Receta homologada o decisión escrita | M7-B (maestro de recetas) y M7-C |
| CV:N-3 | P1-13 y P1-11 (bobinas) | ¿Cómo se identifica una bobina consumida (texto libre, F3, P1-11 o genealogía) y cómo se evita el doble conteo con P1-11? | Texto libre / UUID de bobina F3 / Genealogía | M6-C §7 y §10; M6-D §7. Existente: número declarado como texto, sin vínculo | JP, TI | Pendiente | Decisión escrita | M7-E |
| CV:N-4 | P1-13 | ¿Qué es «ingreso»? La pantalla lo tiene y la definición no (la definición usa `peso_bobina_consumida`). | Campo oficial / Se elimina / Equivale a `peso_bobina_consumida` | M6-C §3 y §10. Existente: `ingreso_kg` declarado en el candidato | JP | Pendiente | Aclaración escrita | M7-C |
| CV:N-5 | P1-13 y P1-11 (cálculo) | Balance de consumo: ¿quién calcula consumo y saldo final, con qué redondeo y en qué sentido? ¿Puede el saldo final superar al inicial? | Servidor / Cliente / No se calcula; … | M6-C §3 y §10; legacy: `saldo_final` calculado en la definición y entrada en la pantalla. Existente: saldos declarados, sin cálculo | JP, CAL | Pendiente | Fórmula y regla escritas | M7-D |
| CV:N-6 | P1-13 (insumos) | Insumos: ¿qué cantidades y unidades, uno o varios por ficha, y qué relación con el sobreempaque? | Uno / Varios (grupo) / Fuera de alcance | M6-C §10. Existente: fuera del contrato candidato | JP | Pendiente | Decisión escrita | M7-C y M7-D |
| CV:N-7 | P1-13 | ¿El pallet se captura en la misma ficha o aparte? (la definición no tiene jabas ni horas) | Misma ficha / Aparte | M6-C §3 y §10. Existente: pallet de P1-12 reutilizado en el candidato | JP | Pendiente | Decisión escrita | M7-C |
| CV:N-8 | P1-13 (máquinas) | ¿En qué máquinas se usa P1-13? La definición lista 8; la pantalla no filtra por máquina. | Las 8 legacy / Otras | M6-C §10; `allowedMachineIds` legacy. Existente: solo WALLY ficticia | JP | Pendiente | Tabla formulario × máquina aprobada | M7-B, M7-C |
| CV:B-1 | P1-11 | ¿Cuántas bobinas por posición y turno: filas variables o dos posiciones fijas? ¿Qué significa «No aplica»? | Filas variables / Posiciones fijas / … | M6-D §3 y §10; legacy: dos posiciones (definición) y tres filas fijas (pantalla). Existente: grupo repetible con mínimo 1 (hipótesis) | JP | Pendiente | Ficha en papel vigente de P1-11 y decisión escrita | M7-C |
| CV:B-2 | P1-11 (rodelas) | ¿Cuál es la estructura de las rodelas: grupo propio, saldo único para ambas posiciones, relación con las bobinas? | Grupo propio / Saldo único / Fuera de alcance | M6-D §6 y §10; legacy campos 47 a 56. Existente: diferido | JP | Pendiente | Decisión escrita | M7-C |
| CV:B-3 | P1-11 (insumos y cuchilla) | ¿Los insumos (fragancia, carpicola, transferencia, coleto, adhesivo LA) y la cuchilla van en la misma ficha? ¿Cómo se declaran `solicitado` y los saldos? | Misma ficha / Aparte / Fuera de alcance | M6-D §6 y §10; legacy campos 19 a 38 y 57 a 60. Existente: diferido | JP | Pendiente | Decisión escrita | M7-C y M7-D |
| CV:B-4 | P1-11 y P1-12 (producción) | ¿La producción (bandejas, columnas, rollos por log y por jaba, `peso_jaba`, `peso_acumulado`) pertenece a P1-11 o a P1-12, para no contarla dos veces? | P1-11 / P1-12 / Ambas con regla | M6-D §6 y §10; legacy campos 39 a 46. Existente: diferido | JP | Pendiente | Decisión escrita | M7-C |
| CV:B-5 | P1-11 | ¿Qué es `peso_bobina` frente al saldo y el ingreso: peso de la bobina montada, peso nuevo o saldo? | Peso montado / Peso nuevo / Saldo | M6-D §3 y §10; legacy `peso_bobina_inferior` y `peso_bobina_superior` (kg). Existente: no está en el candidato | JP | Pendiente | Definición escrita | M7-C |
| CV:B-6 | P1-11 y P1-13 (Calidad) | ¿El consumo exige que la bobina esté liberada por Calidad? ¿Cómo se trata una bobina rechazada? | Exige liberada / Permite pendiente / Bloquea rechazada | M6-D §10 y §11. Existente: sin servicio de liberación ni consumo | CAL, JP | Pendiente | Política escrita | M7-E y M7-F |

## 3. Clasificación, dependencias y vínculos
**Depende de** = prerrequisito duro dentro de Conversión. **Responder junto con** = preguntas relacionadas que conviene contestar en el mismo bloque; **no se fusionan** (cada una conserva su ID, su fuente y su estado) y la relación es simétrica. **Vínculos con Rebobinado** = solo referencias a M5-B0; no cambian sus estados.

| ID | Frente | Clase propuesta | Condición de reclasificación | Depende de | Responder junto con | Vínculos con Rebobinado (solo enlaces) |
|---|---|---|---|---|---|---|
| CV:C-1 | B · Formularios | PF | — | — | CV:P-1, CV:N-1 | — |
| CV:C-2 | B · Formularios | OP | PF si VINTO decide numeración central (requiere numerador y migración) | CV:C-1 | CV:P-2 | RB:H1-13, RB:H1-14, RB:H2-13 |
| CV:C-3 | C · Cálculos | OP | — | CV:C-1 | CV:P-4, CV:P-8, CV:N-5 | RB:H3-01 |
| CV:C-4 | B · Formularios | OP | PF si la ficha exige firma o aprobación para ser válida | — | CV:P-9 | RB:H1-16, RB:H1-21, RB:H2-17 |
| CV:C-5 | C · Cálculos | OP | — | — | CV:P-3, CV:P-4, CV:P-5, CV:N-6 | RB:H1-15, RB:P-02, RB:H3-02 |
| CV:C-6 | A · Maestros | PF | — | — | CV:P-11, CV:N-8 | RB:H1-01, RB:H1-03, RB:H1-04, RB:H2-16 |
| CV:C-7 | A · Maestros | PF | — | — | CV:C-8, CV:P-6 | RB:H1-05, RB:H1-07, RB:H1-08, RB:H1-09 |
| CV:C-8 | A · Maestros | PF | — | CV:C-7 | CV:C-7 | RB:H1-06 |
| CV:C-9 | A · Maestros | PF | — | — | CV:C-11, CV:P-3, CV:N-2 | RB:H1-10, RB:H1-11, RB:P-03 |
| CV:C-10 | B · Formularios | OP | — | — | — | — |
| CV:C-11 | A · Maestros | OP | PF si el peso es obligatorio en alguna ficha | CV:C-9 | CV:C-9, CV:P-3 | RB:P-03 |
| CV:P-1 | B · Formularios | PF | — | — | CV:C-1, CV:P-7, CV:N-1, CV:B-4 | — |
| CV:P-2 | B · Formularios | OP | PF si VINTO decide numeración central | — | CV:C-2 | RB:H1-13, RB:H1-14 |
| CV:P-3 | A · Maestros | OP | PF si el peso es obligatorio en la ficha | CV:C-9, CV:C-11 | CV:C-5, CV:C-9, CV:C-11, CV:P-4 | RB:P-03 |
| CV:P-4 | C · Cálculos | OP | — | CV:P-3, CV:C-3 | CV:C-3, CV:C-5, CV:P-3 | — |
| CV:P-5 | B · Formularios | LT | OP si VINTO exige límites en la validación | CV:C-5 | CV:C-5 | RB:P-02 |
| CV:P-6 | B · Formularios | LT | OP si VINTO exige reglas de horas | CV:C-7 | CV:C-7 | — |
| CV:P-7 | B · Formularios | PF | — | CV:P-1 | CV:P-1, CV:N-7 | — |
| CV:P-8 | C · Cálculos | OP | PF si se exigen en la primera versión | CV:P-1 | CV:C-3, CV:B-4 | — |
| CV:P-9 | B · Formularios | OP | PF si la ficha exige aprobación para ser válida | CV:C-4 | CV:C-4 | RB:H1-16, RB:H2-17 |
| CV:P-10 | D · Integración | OP | — | CV:N-3, CV:B-6 | CV:N-3, CV:B-6 | RB:H3-03 |
| CV:P-11 | A · Maestros | PF | — | CV:C-6 | CV:C-6, CV:N-8 | — |
| CV:N-1 | B · Formularios | PF | — | — | CV:C-1, CV:P-1, CV:B-1 | — |
| CV:N-2 | A · Maestros | OP | PF si la receta es obligatoria | CV:C-9 | CV:C-9 | RB:P-03 |
| CV:N-3 | D · Integración | OP | PF si VINTO exige una bobina real para el piloto | — | CV:P-10, CV:B-6 | RB:H2-02, RB:H2-03, RB:H2-10 |
| CV:N-4 | B · Formularios | PF | — | CV:N-1 | CV:B-5 | — |
| CV:N-5 | C · Cálculos | OP | — | CV:C-3 | CV:C-3 | RB:H3-01, RB:H3-03 |
| CV:N-6 | C · Cálculos | OP | — | CV:C-5 | CV:C-5, CV:B-3 | — |
| CV:N-7 | B · Formularios | PF | — | CV:P-7 | CV:P-7 | — |
| CV:N-8 | A · Maestros | PF | — | CV:C-6 | CV:C-6, CV:P-11 | — |
| CV:B-1 | B · Formularios | PF | — | — | CV:N-1, CV:B-2 | — |
| CV:B-2 | B · Formularios | LT | PF si VINTO incluye las rodelas en la primera versión | CV:B-1 | CV:B-1 | — |
| CV:B-3 | B · Formularios | LT | PF si VINTO los incluye en la primera versión | — | CV:N-6 | — |
| CV:B-4 | B · Formularios | LT | PF si VINTO incluye la producción en la primera versión | CV:P-1 | CV:P-1, CV:P-8 | — |
| CV:B-5 | B · Formularios | OP | — | CV:N-4 | CV:N-4 | RB:H3-02 |
| CV:B-6 | D · Integración | OP | PF si la política exige liberación para el piloto | CV:N-3 | CV:P-10, CV:N-3 | RB:H2-10, RB:H2-11, RB:H2-12 |

### Conteo de la clasificación propuesta (cada decisión cuenta una sola vez)
| Frente | PF | OP | LT | Total |
|---|--:|--:|--:|--:|
| A · Maestros | 6 | 3 | 0 | 9 |
| B · Formularios | 7 | 6 | 5 | 18 |
| C · Cálculos | 0 | 6 | 0 | 6 |
| D · Integración | 0 | 3 | 0 | 3 |
| **Total** | **13** | **18** | **5** | **36** |

- **PF** (13): CV:C-1, CV:C-6, CV:C-7, CV:C-8, CV:C-9, CV:P-1, CV:P-7, CV:P-11, CV:N-1, CV:N-4, CV:N-7, CV:N-8, CV:B-1.
- **OP** (18): CV:C-2, CV:C-3, CV:C-4, CV:C-5, CV:C-10, CV:C-11, CV:P-2, CV:P-3, CV:P-4, CV:P-8, CV:P-9, CV:P-10, CV:N-2, CV:N-3, CV:N-5, CV:N-6, CV:B-5, CV:B-6.
- **LT** (5): CV:P-5, CV:P-6, CV:B-2, CV:B-3, CV:B-4.
- **Frentes:** A: CV:C-6, CV:C-7, CV:C-8, CV:C-9, CV:C-11, CV:P-3, CV:P-11, CV:N-2, CV:N-8. B: CV:C-1, CV:C-2, CV:C-4, CV:C-10, CV:P-1, CV:P-2, CV:P-5, CV:P-6, CV:P-7, CV:P-9, CV:N-1, CV:N-4, CV:N-7, CV:B-1, CV:B-2, CV:B-3, CV:B-4, CV:B-5. C: CV:C-3, CV:C-5, CV:P-4, CV:P-8, CV:N-5, CV:N-6. D: CV:P-10, CV:N-3, CV:B-6.

## 4. Procedencia
| Familia | Cantidad | Documento de origen | Tabla de origen |
|---|--:|---|---|
| C | 11 | [M6-A](M6-A-conversion-central-p116.md) | §7 «Matriz inicial de decisiones industriales de Conversión» |
| P | 11 | [M6-B](M6-B-conversion-p112.md) | §7 «Decisiones pendientes para VINTO» |
| N | 8 | [M6-C](M6-C-conversion-p113.md) | §10 «Decisiones pendientes de VINTO (nuevas)» |
| B | 6 | [M6-D](M6-D-conversion-p111.md) | §10 «Decisiones pendientes de VINTO (nuevas)» |

Cada decisión conserva la redacción de su origen (aquí con la pregunta ampliada en lo mínimo necesario para ser respondible); si hubiera diferencia, prevalece el documento de origen. Las cifras de campos citadas en el paquete (P1-16: 14 = 5 + 8 + 1; P1-12: 37 = 9 + 20 + 8; P1-13: 31 = 8 + 18 + 5; P1-11: 61 = 5 + 34 + 22, con **10** «Condicional / repetible») son las de esos documentos; el 8 de M6-A §8 fue una errata corregida en M6-D §2.
