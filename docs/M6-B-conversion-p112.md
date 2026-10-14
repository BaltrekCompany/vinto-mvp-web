# M6-B — Producción por pallet CANDIDATA (VINTO-P1-12)

> Estas decisiones están consolidadas, con su clave única `CV:`, en el paquete de homologación de Conversión: [M7-A](M7-A-conversion-decisiones-VINTO.md).

Estado: **candidato técnico, NO homologado, NO habilitado.** Conversión sigue sin ser un sector operativo y VINTO-P1-12 (como VINTO-P1-16) sigue fuera de la política de captura central. Todo funciona únicamente en una base efímera `*_test` y en un proceso de prueba que lo habilita explícitamente. Continúa a [M6-A](M6-A-conversion-central-p116.md); las decisiones C-1 a C-11 de esa matriz no se alteran.

Base: `origin/main` `5244d25` (PR #30).

## 1. Qué se entrega

| Pieza | Archivos |
|---|---|
| Contrato, API y pantalla candidatos de P1-12 (kit React y núcleo de captura existentes) | `lib/vinto/p1-12.ts`, `lib/vinto/p1-12-api.ts`, `components/vinto/p1-12-capture.tsx`, `P112History` en `central-form-history.tsx` |
| Pantalla permitida solo para CONVERSION | `lib/vinto/availability.ts` (`SECTOR_SCREENS[CONVERSION]`), `components/vinto/sector-central.tsx` (historial), `app/page.tsx` (ruta `p112` dentro del frente Conversión) |
| `TextField` admite `type="time"` | `components/vinto/capture-kit.tsx` (una palabra; sin otro cambio visual) |
| Fixtures de prueba (solo `*_test`) | `backend/tests/m6b_fixtures.py` (reutiliza el sector, las máquinas y los turnos ficticios de M6-A y deja P1-16 instalado) |
| Pruebas | backend `test_m6b_conversion_p112.py` (21); Node `p1-12-capture.test.mjs` (15) y casos cruzados ampliados en `availability.test.mjs` |
| Servidor y recorrido E2E | `backend/tests/e2e_m6a_server.py` (nueva bandera `E2E_P112`), `scripts/e2e/m6b-e2e.mjs` |

**No cambia el motor.** `capture_service`, OT, asignaciones, turnos y disponibilidad no se modificaron: un `integer` y dos `time` ya estaban soportados. No hay migraciones, ni cambios en `backend/seed_data`, `backend/app/sectors.py`, `CENTRAL_FORM_CODES`, concesiones o permisos. Las restricciones por sector de M6-A se conservan: P1-12 solo tiene pantalla en CONVERSION (`screenFor("REBOBINADO", "VINTO-P1-12")` es `null`).

## 2. Los 37 campos legacy de P1-12

Definición en `lib/vinto/form-definitions.ts` (9 automáticos, 20 manuales, 8 calculados):

| # | Campo | Tipo | Origen |
|--:|---|---|---|
| 1 | `fecha` | date | automático |
| 2 | `operador` | text | automático |
| 3 | `turno` | text | automático |
| 4 | `grupo` | text | automático |
| 5 | `maquina` | text | automático |
| 6–9 | `empaque_saldo_inicial`, `empaque_solicitado`, `empaque_utilizado` / `empaque_saldo_final` | text | manual ×3 / **calculado** |
| 10–13 | `subempaque_*` (inicial, solicitado, utilizado / saldo final) | text | manual ×3 / **calculado** |
| 14–17 | `bolsa_*` (inicial, solicitado, utilizado / saldo final) | text | manual ×3 / **calculado** |
| 18–21 | `segundas_*` (inicial, solicitado, utilizado / saldo final) | text | manual ×3 / **calculado** |
| 22–25 | `asas_*` (inicial, solicitado, utilizado / saldo final) | text | manual ×3 / **calculado** |
| 26 | `merma_maquina` | text | automático |
| 27 | `codigo_producto` | text | manual |
| 28 | `producto` | text | manual |
| 29 | `formato` | decimal | manual |
| 30 | `cantidad_producida_jabas` | text | manual |
| 31 | `cantidad_producida_segundas` | text | manual |
| 32 | `merma_logs` | decimal | **calculado** |
| 33 | `merma_cola` | decimal | **calculado** |
| 34 | `merma_maquina_kg` | text | automático |
| 35 | `total_produccion` | text | **calculado** |
| 36 | `firma_operador` | text | automático |
| 37 | `firma_encargada` | text | automático |

Total 37 = 9 automáticos + 20 manuales + 8 calculados. No hay campos de hora ni de peso.

## 3. Diferencias con `PalletProduction` (pantalla actual)

| | Definición | Pantalla actual (`PalletProduction`, `app/page.tsx`) |
|---|---|---|
| Unidad de registro | una ficha diaria con balances de insumos de empaque | **un pallet** por envío |
| Cantidad | `cantidad_producida_jabas` (texto) | `cantidad_jabas` (número) |
| Horas | no existen | `hora_inicio` y `hora_fin` |
| Peso | no existe | `peso_nominal_jaba` (del maestro `NOMINAL_WEIGHT_BY_PRODUCT`) y `peso_total_pallet = jabas × peso nominal` |
| Número de pallet | no existe | `numero_pallet = PAL-AAAAMMDD-XXXXXX`, con 6 caracteres aleatorios de un UUID generado en el navegador |
| Balances, mermas, total, firmas | sí | no |
| Producto | `codigo_producto`, `producto`, `formato` manuales | los hereda la línea de la OT |

Además la pantalla **bloquea el envío** si el producto no tiene peso nominal en el maestro legacy. La definición y la pantalla son incompatibles; esa es la decisión C-1 aplicada a P1-12 (ver §7, decisión P-1).

## 4. Contrato candidato de tres campos (hipótesis de prueba)

Se implementa exclusivamente la interpretación de la pantalla, y solo como fixture:

| Campo | Tipo en el motor | Validación |
|---|---|---|
| `cantidad_jabas` | `integer` | Entero con signo opcional (`-?\d+`, el mismo formato que acepta el backend) y dentro del rango seguro de JavaScript. Se rechazan decimales, exponenciales, texto y `+`. **Sin mínimo ni máximo** (0, 100000 y también `-5` se aceptan estructuralmente) |
| `hora_inicio` | `time` | `HH:MM` (00:00–23:59) |
| `hora_fin` | `time` | `HH:MM`. **No** se exige que sea posterior a la de inicio (un pallet puede cruzar la medianoche) |

> **Aclaración:** aceptar un entero negativo en este contrato técnico **no autoriza cantidades negativas en la operación industrial**. Solo refleja que la validación es estructural y que el motor existente ya almacena el entero tal como llega. La cantidad mínima de jabas sigue **pendiente de VINTO** (decisión P-5).

El backend deriva de la asignación y la sesión: máquina, turno, fecha operativa, OT, línea, artículo y usuario. El payload solo lleva `capture_id`, `form_code`, `assignment_id`, `device_key` y estos tres valores; cualquier otra clave (`numero_pallet`, `peso_total`, `maquina`, `turno`…) se rechaza con 422, y una prueba lo comprueba. PostgreSQL devuelve las horas con segundos (`08:15:00`); el historial las muestra sin ellos.

Nada se calcula ni se persiste de peso, ni se genera un número de pallet. No hay contador, numerador ni migración.

### Peso nominal y peso total (no se integra)

Los pesos del maestro legacy (`lib/vinto/product-weights.ts`, de `INArticulo-MFMatrialOP.xlsx`) no son un maestro homologado de Conversión, por lo que **no se usan como autoridad**; tampoco se acepta un peso nominal enviado por el navegador. La única verificación de viabilidad es una prueba pura (`p1-12-capture.test.mjs`, «synthetic feasibility only») que multiplica jabas por un peso **completamente sintético** con aritmética decimal exacta (`BigInt` escalado) y demuestra por qué: `3 × 2.1` da `6.3` exacto, mientras que en coma flotante da `6.300000000000001`. Esa función vive solo en la prueba; otra prueba asegura que ni el contrato ni la pantalla mencionan pesos, `PAL-` ni `product-weights`.

**Cómo se incorporaría un peso nominal homologado (futuro, no implementado):**
1. VINTO aprueba el peso nominal por artículo (y su unidad, decimales y vigencia) y Baltrek lo incorpora al bundle de datos maestros (hoy `nominal_weights: false`), con versión y auditoría; el artículo de la línea ya viaja con la captura.
2. El backend resuelve el peso desde la versión del artículo congelada en la línea de la OT; el cliente nunca lo envía.
3. El peso total se calcula en el servidor con `Decimal` (nunca con flotantes), o se decide expresamente calcularlo solo al consultar; en ambos casos con la regla de redondeo aprobada y el comportamiento definido cuando el artículo no tiene peso (la pantalla legacy bloquea el envío).
4. Si el total se guarda, requiere la decisión de si es un dato oficial o derivado, y probablemente un campo calculado soportado por el motor (hoy rechaza los `calculated`) o una columna nueva, es decir, una migración que **no** se hace aquí.

### Número de pallet

El código `PAL-AAAAMMDD-XXXXXX` del legacy es aleatorio, no único garantizado ni secuencial: no es un correlativo industrial y **no se replica**. La pantalla muestra «Número oficial de pallet: pendiente de definición» y el identificador técnico de la captura (`capture_id`, UUID v4 del intento, el mismo en los reintentos). Un número oficial exigiría un numerador central (migración, alcance por máquina/día/turno, formato, reinicio, huecos y correcciones), como el de bobinas (F3) o el correlativo de fardos de P1-10.

## 5. Cómo se comporta

- **Navegación:** dentro del frente Conversión, la máquina GAMBINI ofrece los formularios que el backend publica (P1-12 y P1-16); el formulario vinculado pero sin publicar no aparece, y una máquina sin relación (WALLY) no ofrece ninguno. Con la política real o sin concesión, «Conversión no está habilitado» y ningún dato demo ni legacy como respaldo.
- **Envío:** igual que P1-16: `capture_id` fijo por intento, reintento idempotente, reconciliación por `GET` tras un timeout, intento pendiente que bloquea los campos, 409 `ASSIGNMENT_STALE` / `ASSIGNMENT_NOT_ACTIVE` con mensaje claro y retorno a Ejecución, 401 que vuelve al login, historial central con parser estricto y sin mezclar formularios (Seguimiento solo pide los historiales con pantalla en el sector).
- **Registros locales:** no se escribe `vinto-p1-records`, `vinto-ot` ni `vinto-asg`; los registros legacy existentes no se borran ni se convierten (el E2E siembra uno y comprueba que se conserva).

## 6. Pruebas ejecutadas

Línea base medida en `origin/main` `5244d25`: Node 472 OK; backend 894 pruebas con 2 fallos propios del entorno (ver §9).

| Prueba | Resultado |
|---|---|
| Backend `test_m6b_conversion_p112` (focalizada) | **21 OK** |
| Backend suite completa | **915 pruebas, 913 OK**; los 2 fallos son `test_db_guard.RealConnectionTests` (requieren DEV, ver §9), idénticos a la línea base (894 pruebas, mismos 2 fallos) |
| Node completo | **487 OK** (472 + 15 nuevas) |
| `tsc --noEmit` | único error: el TS2322 heredado de `app/page.tsx` |
| `eslint .` | 0 errores; 2 avisos heredados (`m4a-e2e.mjs`, `export-seed-data.mjs`) |
| `build` (sin ruta de QA; rutas `/` y `/admin`) | OK |
| E2E P1-12 habilitado (`m6b-e2e.mjs`, Chrome real + FastAPI + PostgreSQL efímero) | **59/59** |
| E2E P1-12 con la configuración real (deshabilitado) | **12/12** |
| Regresión P1-16 (`m6a-e2e.mjs`, política sin P1-12) | **53/53** habilitado, **13/13** deshabilitado |
| Regresión M4-A Rebobinado (`m4a-e2e.mjs`, con P1-12 en la política) | **49/49** habilitado, **12/12** deshabilitado |

Ninguna prueba abre una conexión a DEV (`m4a-e2e.mjs` mantiene `E2E_DEV_READ` desactivado por defecto; `m6a`/`m6b` nunca leen DEV).

### Cobertura de los puntos del E2E solicitados

| # | Cubre |
|---|---|
| 1–2 | J1–J8, K1–K3: Jefatura crea y publica la OT de Conversión; Supervisión activa la asignación |
| 3–4 | O2–O8: Operación abre P1-12 y captura un pallet con los tres datos |
| 5 | O10–O11: PostgreSQL guarda OT, línea, máquina, artículo, turno, fecha operativa y usuario (derivados por el backend) y solo tres detalles tipados |
| 6 | O15–O17: Seguimiento recupera el pallet con el parser específico |
| 7–8 | R1–R5: reintentos idénticos sin duplicado; conflicto con otro contenido y con otro formulario |
| 9 | X2–X5: asignación vencida (con el formulario abierto y al entrar) |
| 10 | X6–X7: usuario sin concesión (interfaz y API) |
| 11 | O2, O3, X1, X1b: no vinculado y no publicado no se ofrecen ni se aceptan |
| 12 | O13–O14, O16: P1-16 sigue funcionando y sus historiales no se mezclan |
| 13 | regresión M4-A (49/49 y 12/12), L1 |
| 14 | D1–D8: Conversión deshabilitada sin datos demo ni locales |
| 15 | sin lecturas ni escrituras a DEV |

## 7. Decisiones pendientes para VINTO

Las decisiones C-1 a C-11 de M6-A **no cambian**; estas se añaden con trazabilidad a ellas.

| # | Decisión | Relacionada con | Bloquea / Afecta | Comportamiento hoy (prueba) |
|---|---|---|---|---|
| P-1 | Qué es P1-12: la ficha diaria de 37 campos (balances, mermas, total) o un pallet por envío con jabas y horas | C-1 | Bloquea | Pallet (hipótesis) |
| P-2 | Número oficial de pallet: ¿existe?, manual o central, alcance (máquina/día/turno), formato, reinicio, huecos y correcciones | C-2 | Bloquea si es central (numerador + migración) | Pendiente; solo `capture_id` |
| P-3 | Peso nominal por artículo: maestro oficial, unidad, decimales, vigencia, comportamiento si falta | C-9, C-11 | Bloquea para cualquier peso oficial | Sin peso |
| P-4 | Peso total del pallet: ¿dato oficial guardado o derivado?, redondeo, quién lo calcula (servidor) | C-3, C-5 | Afecta | No se calcula ni se guarda |
| P-5 | Cantidad de jabas: ¿mínimo, máximo, relación con la cantidad de la OT o la receta? | C-5 | Afecta | Solo entero |
| P-6 | Horas del pallet: ¿obligatorias?, ¿fin posterior a inicio?, cruce de medianoche y relación con el turno | C-7 | Afecta | Dos horas libres |
| P-7 | ¿Un pallet por ficha o varios pallets agrupados en una ficha (grupo repetible)? | C-1 | Afecta | Un pallet por captura |
| P-8 | Balances de empaque, subempaque, bolsa, segundas y asas, merma y total de producción: ¿se capturan?, ¿quién calcula los 8 campos calculados? | C-3, C-9 | Bloquea si se exigen | Fuera del contrato |
| P-9 | Firma de operador y de encargada, «grupo» y operador de la ficha | C-4 | Bloquea si exige aprobación | No se capturan |
| P-10 | Relación del pallet con inventario y con las bobinas consumidas (P1-11) y la merma (P1-16) | C-1, C-6 | Afecta | Sin relaciones |
| P-11 | Máquinas permitidas de P1-12 (legacy: Gambini, Sincro II y Sincro III) | C-6 | Bloquea | Solo GAMBINI de prueba |

## 8. Qué necesitaría una versión homologada

1. Respuesta a P-1 (ficha diaria o pallet) y, según ella, la definición publicada: campos, tipos, obligatoriedad, opciones y grupos.
2. Número de pallet oficial (P-2): numerador central con su migración, o la decisión expresa de no tenerlo.
3. Maestro de pesos nominales aprobado e incorporado al bundle (P-3), con el cálculo del total en el servidor si se decide guardarlo (P-4).
4. Los datos maestros de Conversión aprobados (máquinas, artículos, relaciones, turnos, vigencias) e importados de forma controlada, como M4-B1 para Rebobinado.
5. El formulario publicado y vinculado a sus máquinas por el importador, añadido a la política de captura central y al sector operativo mediante PRs revisados y separados (nunca en este incremento).
6. Si hay firma o aprobación, el mecanismo (hoy inexistente).
7. Nuevo E2E con datos oficiales, y confirmación de que Bobinas y Rebobinado no regresan.

## 9. Limitaciones

- Es un circuito **candidato**: el contrato, las horas, los turnos y el fixture son hipótesis de prueba. Solo se probó GAMBINI (con formularios) y WALLY (sin ellos), ficticias.
- Las dos pruebas de `test_db_guard.RealConnectionTests` (`test_dev_database_is_rejected`, `test_name_inside_connection_string_is_not_trusted`) necesitan conectarse a DEV y **no se ejecutaron**: se corrió con `DATABASE_URL` apuntando a la base de pruebas. Fallan igual en `origin/main` con esa configuración. No se modificaron.
- El TS2322 de `app/page.tsx` es heredado y no se tocó.
- P1-11 y P1-13 siguen sin implementarse.
- Las bases efímeras se crean en el mismo servidor PostgreSQL local que DEV (como en M2–M6-A); se eliminan al terminar.
