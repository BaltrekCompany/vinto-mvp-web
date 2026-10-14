# M6-C — Producción diaria de servilletas y especiales CANDIDATA (VINTO-P1-13)

Estado: **candidato técnico, NO homologado, NO habilitado.** Conversión sigue sin ser un sector operativo y VINTO-P1-13 (como P1-12 y P1-16) sigue fuera de la política de captura central. Todo funciona únicamente en una base efímera `*_test` y en un proceso de prueba que lo habilita explícitamente. Continúa a [M6-A](M6-A-conversion-central-p116.md) y [M6-B](M6-B-conversion-p112.md); las decisiones C-1 a C-11 y P-1 a P-11 no se alteran.

Base: `origin/main` `0150a03` (PR #31).

> **Aviso que muestra la pantalla:** «Ficha candidata no homologada. Los saldos y el número de bobina son declaraciones de prueba: no generan consumo ni modifican inventario.»

## 1. Qué se entrega

| Pieza | Archivos |
|---|---|
| Contrato, API y pantalla candidatos de P1-13 (kit React y núcleo de captura existentes) | `lib/vinto/p1-13.ts`, `lib/vinto/p1-13-api.ts`, `components/vinto/p1-13-capture.tsx`, `P113History` en `central-form-history.tsx` |
| Pantalla permitida solo para CONVERSION | `lib/vinto/availability.ts` (`SECTOR_SCREENS[CONVERSION]`), `components/vinto/sector-central.tsx` (historial), `app/page.tsx` (ruta `p113`) |
| Reutilización del pallet de P1-12 | `lib/vinto/p1-12.ts`: **una línea** (`export const parsePalletValues = parseValues`). El comportamiento de P1-12 no cambia; P1-13 valida el pallet llamando a `normalizeP112Draft` |
| Fixtures de prueba (solo `*_test`) | `backend/tests/m6c_fixtures.py` (P1-13 vinculado **solo a WALLY**; reutiliza el sector, las máquinas y los turnos ficticios de M6-A) |
| Pruebas | backend `test_m6c_conversion_p113.py` (22); Node `p1-13-capture.test.mjs` (16) y casos cruzados ampliados en `availability.test.mjs` |
| Servidor y recorrido E2E | `backend/tests/e2e_m6a_server.py` (bandera `E2E_P113`, por defecto `off`), `scripts/e2e/m6c-e2e.mjs` |

**No cambia el motor.** `capture_service`, OT, asignaciones, turnos y disponibilidad no se modificaron: `text`, `decimal`, `integer`, `time` y `textarea` ya estaban soportados. No hay migraciones, ni cambios en `backend/seed_data`, `backend/app/sectors.py`, `CENTRAL_FORM_CODES`, concesiones o permisos, ni servicios de inventario o genealogía.

## 2. Los 31 campos legacy de P1-13

Definición en `lib/vinto/form-definitions.ts`: 8 automáticos, 18 manuales y 5 calculados. Máquinas legacy permitidas: OMET I, OMET II, 8.2, 8.5, 8002, Serv 4, Wally y Pañuelera. **GAMBINI no pertenece a su alcance.**

| # | Campo | Tipo | Origen | Equivalente en `NapkinSheet` |
|--:|---|---|---|---|
| 1 | `operador` | text | automático | sesión |
| 2 | `firma` | text | automático | no existe |
| 3 | `fecha` | date | automático | asignación |
| 4 | `hora` | time | automático | no existe (la pantalla pide hora de inicio y de fin del pallet) |
| 5 | `turno` | text | automático | asignación |
| 6 | `grupo` | text | automático | no existe |
| 7 | `maquina` | text | automático | asignación |
| 8 | `saldo_inicial` | text | manual | «Saldo inicial» (kg, número) |
| 9 | `numero_bobina_consumida` | text | manual | «N.º bobina» |
| 10 | `peso_bobina_consumida` (kg) | text | manual | **sin equivalente** (la pantalla usa «Ingreso») |
| 11 | `formato_bobina_consumida` | catálogo | manual | «Tipo de bobina» (lista de la receta) |
| 12 | `merma_bobina` | text | **calculado** | no existe |
| 13 | `observacion` | textarea | manual opcional | no existe |
| 14 | `saldo_final` | text | **calculado** | **entrada manual** |
| 15 | `encargado_de_turno` | text | automático | no existe |
| 16–18 | `codigo_producto`, `producto`, `formato_producto` | catálogo | manual | los hereda la línea de la OT |
| 19 | `cantidad_producida` | text | manual | no existe (la pantalla usa jabas del pallet) |
| 20–22 | `empaque_saldo_inicial`, `empaque_solicitado`, `empaque_utilizado` | text | manual | **sin equivalente** |
| 23 | `empaque_saldo_final` | text | **calculado** | no existe |
| 24 | `merma_empaque` | decimal | **calculado** | no existe |
| 25–26 | `insumo_codigo`, `insumo_nombre` | catálogo/text | manual | «Insumo» (un solo selector «código · nombre») |
| 27–29 | `insumo_saldo_inicial`, `insumo_solicitado`, `insumo_utilizado` | text | manual | «Cantidad consumida» (un único valor) |
| 30 | `insumo_saldo_final` | text | **calculado** | no existe |
| 31 | `observaciones` | textarea | manual opcional | no existe |

Total 31 = 8 automáticos + 18 manuales + 5 calculados (`merma_bobina`, `saldo_final`, `empaque_saldo_final`, `merma_empaque`, `insumo_saldo_final`).

## 3. Diferencias con `NapkinSheet`

`NapkinSheet` (`app/page.tsx`) tiene tres secciones: «1. Consumo de bobina» (tipo, N.º, saldo inicial, ingreso, saldo final y un readout «Consumo»), «2. Sobreempaque e insumos» (un insumo y una cantidad) y la producción por pallet de P1-12 (`PalletProduction`). Incoherencias del legacy, que **no son reglas aprobadas**:

1. La definición declara `saldo_final` como **calculado**; la pantalla lo pide como **entrada** y calcula el consumo (`inicial + ingreso − final`).
2. `consumo_bobina` solo se actualiza al editar `saldo_final`: si se edita antes `saldo_inicial` o `ingreso`, el valor guardado queda desactualizado aunque el readout mostrado cambie.
3. «Tipo de bobina» e «Insumo» usan la **misma lista** (toda la receta del producto), sin filtrar por uso.
4. `submit()` no exige ningún campo manual; solo bloquea si el producto no tiene peso nominal en el maestro legacy.
5. La definición no tiene jabas ni horas ni pesos, pero la pantalla los pide, y genera `numero_pallet` (`PAL-AAAAMMDD-XXXXXX`, aleatorio) y `peso_total_pallet`.
6. «Ingreso» no existe en la definición (que usa `peso_bobina_consumida`).
7. Las claves de la pantalla (`tipo_bobina`, `numero_bobina`…) no coinciden con las de la definición.

## 4. Contrato candidato de 8 campos (hipótesis de prueba)

| Campo | Tipo en el motor | Obligatorio | Validación estructural |
|---|---|:-:|---|
| `numero_bobina` | `text` | sí | Texto no vacío (recortado), máx. 10 000 caracteres. **Texto libre declarado** |
| `saldo_inicial_kg` | `decimal` | sí | Decimal (`-?\d+(\.\d+)?`, coma o punto en pantalla, enviado con punto), ≤ 40 caracteres. **Declarado** |
| `ingreso_kg` | `decimal` | sí | Ídem. **Declarado** |
| `saldo_final_kg` | `decimal` | sí | Ídem. **Declarado** |
| `cantidad_jabas` | `integer` | sí | Los validadores de P1-12 (entero con signo opcional, rango seguro) |
| `hora_inicio` | `time` | sí | Los validadores de P1-12 (`HH:MM`) |
| `hora_fin` | `time` | sí | Los validadores de P1-12 (`HH:MM`; sin exigir orden) |
| `observaciones` | `textarea` | no | Texto opcional |

El backend deriva de la asignación y la sesión: máquina, OT, línea, artículo/producto, turno, fecha operativa y usuario. El payload solo lleva `capture_id`, `form_code`, `assignment_id`, `device_key` y estos ocho valores; cualquier otra clave (`consumo`, `peso_total_pallet`, `numero_pallet`, `insumo`, `maquina`, `turno`…) se rechaza con 422, y una prueba lo comprueba. PostgreSQL devuelve las horas con segundos (`08:15:00`); el historial las muestra sin ellos.

Los sufijos «kg» son etiquetas de la hipótesis legacy; **la unidad oficial sigue pendiente de VINTO.**

## 5. Declaraciones de saldo frente a inventario real

Los tres saldos y el número de bobina son **declaraciones del operador**, almacenadas tal cual (sin redondeo ni conversión). Por diseño:

- No se calcula ni se guarda **consumo**, balance oficial, merma, saldo disponible ni ajuste de existencias; la fórmula `saldo inicial + ingreso − saldo final` **no existe** en el código del contrato (una prueba lo vigila).
- No se impide que el saldo final sea **mayor** que el inicial (no hay regla homologada); tampoco hay mínimos, máximos, precisión ni redondeos. Un negativo es estructuralmente válido, como el entero negativo de P1-12, y **eso no autoriza cantidades negativas en operación**.
- `numero_bobina` **no se consulta** ni se valida contra `vinto_txn.bobbin`, ni se relaciona con F3, Rebobinado, P1-11 o genealogía; no se afirma que la bobina exista. Aunque el texto tenga la forma de un código F3 (`BM-2609-001`), se almacena como texto (una prueba lo verifica).
- Una captura P1-13 crea **exactamente una** fila `capture` y **no** crea un P1-12 ni un P1-16 automático; no crea bobinas, relaciones, liberaciones de Calidad ni numeración (comprobado en backend y en el E2E sobre las tablas `bobbin`, `bobbin_relation`, `quality_release` y `bobbin_sequence`).
- No se genera número oficial de pallet ni se calcula peso nominal o total; la pantalla muestra «pendiente de definición» y el identificador técnico (`capture_id`).

## 6. Exclusiones y motivos

| Excluido | Motivo |
|---|---|
| `tipo_bobina`, `insumo`, `cantidad_insumo` | Dependen de recetas legacy sin homologar; además el motor solo admite opciones **estáticas** por versión (`field_option`), no por artículo. Un grupo repetible de insumos en texto libre parecería consumo |
| `consumo_bobina` y mermas | Cálculo legacy con defectos (§3) y tratarlo como oficial convertiría declaraciones en movimientos |
| `numero_pallet`, `peso_nominal_jaba`, `peso_total_pallet` | El número es aleatorio y los pesos nominales no están homologados (M6-B) |
| `peso_bobina_consumida`, balances de empaque e insumo | Son de la definición legacy, que la pantalla no implementa |
| `codigo_producto`, `producto`, `formato_producto` | Los hereda la línea de la OT |
| Firmas, grupo, encargado de turno | El modelo central no los tiene |

## 7. Dependencias de recetas y genealogía

- **Recetas (legacy):** 22 artículos únicos en las 8 máquinas de P1-13; 20 tienen receta y 2 (`11104`, `11202`, de 8.2 y 8002) no. Las cantidades son por unidad de producto, en KG, y no están homologadas. La receta no interviene en este contrato.
- **Genealogía:** P1-07 no tiene servicio productivo (M5-A) y no hay servicio de consumo de bobinas. Cualquier vínculo entre `numero_bobina` y una bobina real exigiría esas decisiones y desarrollos; aquí **no existe**.
- **P1-11:** también declara consumo de bobinas, pero solo para Gambini y Sincro II/III; P1-13 declara su propio consumo en las máquinas de servilletas. Si ambos se homologan, hay riesgo de **doble conteo** de la misma bobina (decisión N-3).

## 8. Cómo se comporta

- **Navegación (fixtures):** WALLY ofrece únicamente P1-13; GAMBINI conserva P1-12 y P1-16; el formulario vinculado a WALLY pero sin publicar no aparece. P1-13 no está vinculado a GAMBINI y P1-12 / P1-16 no lo están a WALLY. Con la política real o sin concesión: «Conversión no está habilitado», sin datos demo ni legacy como respaldo.
- **Envío:** igual que P1-12 y P1-16: `capture_id` fijo por intento, reintento idempotente, reconciliación por `GET`, intento pendiente que bloquea los campos, 409 `ASSIGNMENT_STALE` / `ASSIGNMENT_NOT_ACTIVE`, 401, historial con parser estricto sin mezclar formularios.
- **Registros locales:** no se escribe `vinto-p1-records`, `vinto-ot` ni `vinto-asg`; los registros legacy no se borran ni se convierten (el E2E siembra uno y comprueba que se conserva).
- **Bandera `E2E_P113`:** desactivada por defecto. Con `off` el servidor de prueba no instala P1-13 y WALLY sigue **sin formularios**, exactamente como en M6-A y M6-B. Con `on` solo se instala y se habilita con Conversión habilitada (con Conversión deshabilitada no entra en la política).

## 9. Pruebas ejecutadas

Línea base de `origin/main` `0150a03`: Node 487 OK; backend 916 pruebas con 2 fallos propios del entorno (ver §12).

| Prueba | Resultado |
|---|---|
| Backend `test_m6c_conversion_p113` (focalizada) | **22 OK** |
| Backend suite completa | **938 pruebas, 936 OK**; los 2 fallos son `test_db_guard.RealConnectionTests` (requieren DEV, ver §12), los mismos de la línea base (916 pruebas) |
| Node completo | **503 OK** (487 + 16 nuevas) |
| `tsc --noEmit` | único error: el TS2322 heredado de `app/page.tsx` |
| `eslint .` | 0 errores; 2 avisos heredados (`m4a-e2e.mjs`, `export-seed-data.mjs`) |
| `build` (sin ruta de QA; rutas `/` y `/admin`) | OK |
| E2E P1-13 habilitado (`m6c-e2e.mjs`, Chrome real + FastAPI + PostgreSQL efímero) | **62/62** |
| E2E P1-13 con la configuración real (deshabilitado) | **12/12** |
| Regresión M6-B (`m6b-e2e.mjs`, `E2E_P113` off) | **59/59** habilitado, **12/12** deshabilitado |
| Regresión M6-A (`m6a-e2e.mjs`, `E2E_P112` y `E2E_P113` off) | **53/53** habilitado, **13/13** deshabilitado |
| Regresión M4-A Rebobinado (`m4a-e2e.mjs`) | **49/49** habilitado, **12/12** deshabilitado |

Ninguna prueba abre una conexión a DEV (`m4a-e2e.mjs` mantiene `E2E_DEV_READ` desactivado por defecto; `m6a`/`m6b`/`m6c` nunca leen DEV).

### Cobertura de lo solicitado en el E2E

| Requisito | Cubre |
|---|---|
| Jefatura crea y publica la OT en WALLY; Supervisión activa | J1–J8, K1–K3 |
| Operación abre P1-13 y registra los ocho campos | O2–O7 |
| Detalles tipados, contexto y auditoría | O9, O10, O12 |
| Seguimiento recupera la captura | O17–O19 |
| Reintento sin duplicado; respuesta perdida y reconciliación; conflicto | R1–R5 |
| Asignación vencida | X2–X5 |
| Sin concesión | X6, X7 |
| Formulario sin publicar; P1-13 no disponible en GAMBINI | O1, O2, X1, X1b, L1 |
| P1-12 y P1-16 disponibles y funcionando en GAMBINI | O1, O13–O16, O18 |
| Un P1-13 no genera un P1-12 | O11, O14, O16, Z2 |
| Conversión deshabilitada sin datos demo ni legacy | D1–D8 |
| Sin movimientos de inventario ni vínculos de bobinas | O11, Z3 |
| Sin lecturas de DEV | ninguna prueba conecta a DEV |

## 10. Decisiones pendientes de VINTO (nuevas)

Todas **pendientes**; no repiten C-1 a C-11 ni P-1 a P-11, a las que se refieren.

| # | Decisión | Relacionada con |
|---|---|---|
| N-1 | Unidad de registro de P1-13: una ficha por turno con bobina, insumos y producción, o capturas separadas | C-1, P-1 |
| N-2 | ¿Receta obligatoria? ¿Quién valida bobina e insumo contra ella? La receta no está homologada | C-9 |
| N-3 | Cómo se identifica una bobina consumida: texto libre, F3, P1-11 o genealogía; y cómo se evita el doble conteo con P1-11 | P-10, C-6 |
| N-4 | Qué es «ingreso» y por qué la pantalla lo tiene y la definición no (la definición usa `peso_bobina_consumida`) | C-1 |
| N-5 | Balance de consumo: quién calcula `consumo` y `saldo_final`, con qué redondeo y en qué sentido (entrada o calculado); ¿puede el saldo final superar al inicial? | C-3 |
| N-6 | Insumos: cantidades y unidades, uno o varios por ficha, relación con el sobreempaque | C-5 |
| N-7 | Si el pallet se captura en la misma ficha o aparte (la definición no tiene jabas ni horas) | P-7 |
| N-8 | Máquinas habilitadas: la definición lista 8; la pantalla no filtra por máquina | C-6, P-11 |

## 11. Qué necesitaría una versión homologada

1. Respuesta a N-1 y N-7 (qué es la ficha y dónde va el pallet) y, según ella, la definición publicada: campos, tipos, obligatoriedad, opciones y grupos.
2. Receta homologada (N-2) y, si se exige, una forma de expresar listas de insumos por artículo (hoy el motor solo admite opciones estáticas).
3. Decisión sobre bobinas e identidad (N-3) y, si se vinculan, el servicio de consumo y de genealogía (P1-07), que no existen.
4. Fórmulas, unidades, decimales y redondeos (N-5, N-6, C-3, C-5), con el cálculo en el servidor si se decide guardarlo.
5. Número de pallet y pesos nominales (P-2 a P-4).
6. Datos maestros de Conversión aprobados e importados de forma controlada, y el formulario publicado, añadido a la política de captura central y al sector operativo mediante PRs revisados y separados (nunca aquí).
7. Mecanismo de firma o aprobación, si se exige.
8. Nuevo E2E con datos oficiales y confirmación de que Bobinas y Rebobinado no regresan.

## 12. Limitaciones

- Es un circuito **candidato**: el contrato, las horas, los turnos y los fixtures son hipótesis de prueba. Se usa **WALLY ficticia** (la misma máquina que en M6-A y M6-B es el caso sin formularios; solo con `E2E_P113=on` o con este módulo de pruebas ofrece P1-13) y el artículo de Bobinas del fixture, no un artículo de Conversión.
- Las dos pruebas de `test_db_guard.RealConnectionTests` (`test_dev_database_is_rejected`, `test_name_inside_connection_string_is_not_trusted`) necesitan conectarse a DEV y **no se ejecutaron**: se corrió con `DATABASE_URL` apuntando a la base de pruebas. Fallan igual en `origin/main` con esa configuración. No se modificaron.
- El TS2322 de `app/page.tsx` es heredado y no se tocó.
- Las bases efímeras se crean en el mismo servidor PostgreSQL local que DEV (como en M2–M6-B); se eliminan al terminar.
- En una corrida de regresión (`m6b-e2e` habilitado, tras reiniciar el servidor de prueba) el script no emitió ninguna línea de resultado; al repetirlo con el servidor ya listo pasó 59/59. No se identificó la causa; se atribuye a haberlo lanzado antes de que el servidor estuviera listo.
- P1-11 sigue sin implementarse.
