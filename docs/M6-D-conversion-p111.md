# M6-D — Consumo declarado de bobinas CANDIDATO (VINTO-P1-11)

Estado: **candidato técnico, NO homologado, NO habilitado.** Conversión sigue sin ser un sector operativo y VINTO-P1-11 (como P1-12, P1-13 y P1-16) sigue fuera de la política de captura central. Todo funciona únicamente en una base efímera `*_test` y en un proceso de prueba que lo habilita explícitamente. Continúa a [M6-A](M6-A-conversion-central-p116.md), [M6-B](M6-B-conversion-p112.md) y [M6-C](M6-C-conversion-p113.md); las decisiones C-1 a C-11, P-1 a P-11 y N-1 a N-8 no se alteran.

Base: `origin/main` `4b29835` (PR #32).

> **Aviso que muestra la pantalla:** «Ficha candidata no homologada. Los números de bobina y los saldos son declaraciones de prueba: no generan consumo, movimientos de inventario ni vínculos de genealogía.»

## 1. Qué se entrega

| Pieza | Archivos |
|---|---|
| Contrato, API y pantalla candidatos de P1-11 (grupos repetibles M3-A, kit React y núcleo de captura existentes) | `lib/vinto/p1-11.ts`, `lib/vinto/p1-11-api.ts`, `components/vinto/p1-11-capture.tsx`, `P111History` en `central-form-history.tsx` |
| Pantalla permitida solo para CONVERSION | `lib/vinto/availability.ts` (`SECTOR_SCREENS[CONVERSION]`), `components/vinto/sector-central.tsx` (historial), `app/page.tsx` (ruta `p111`) |
| Fixtures de prueba (solo `*_test`) | `backend/tests/m6d_fixtures.py` (P1-11 vinculado **solo a GAMBINI**; reutiliza el sector, las máquinas y los turnos ficticios de M6-A) |
| Pruebas | backend `test_m6d_conversion_p111.py` (26); Node `p1-11-capture.test.mjs` (17) y casos cruzados ampliados en `availability.test.mjs` |
| Servidor y recorrido E2E | `backend/tests/e2e_m6a_server.py` (bandera `E2E_P111`, por defecto `off`), `scripts/e2e/m6d-e2e.mjs` |

**No cambia el motor.** `capture_service` (incluidos los grupos repetibles de M3-A), OT, asignaciones, turnos y disponibilidad no se modificaron. No hay migraciones, ni cambios en `backend/seed_data`, `backend/app/sectors.py`, `CENTRAL_FORM_CODES`, concesiones o permisos, ni servicios de inventario, bobinas, Calidad o genealogía.

## 2. Inventario de P1-11: 61 campos

Definición en `lib/vinto/form-definitions.ts`: **61 campos = 5 automáticos + 34 manuales + 22 calculados**. Tipos declarados: 54 `text`, 5 `decimal`, 1 `date` y 1 `textarea` (casi todo lo cuantitativo, incluso lo calculado, está declarado como texto). Máquinas legacy permitidas: `gambini`, `sincro_ii` y `sincro_iii`.

| Bloque | # | Campos | Manual / calculado |
|---|---|---|---|
| Contexto | 1–5 | `fecha`, `operador`, `turno`, `grupo`, `maquina` | 5 automáticos |
| Bobina inferior | 6–11 | `saldo_inicial_bobina_inferior`, `numero_…`, `peso_…` (kg), `tipo_…` (catálogo) | 4 manuales; `consumo_…` y `saldo_final_…` calculados |
| Bobina superior | 12–17 | los mismos seis campos | 4 manuales; 2 calculados |
| Merma | 18 | `merma_total` (decimal) | calculado |
| Insumos | 19–38 | fragancia, carpicola, transferencia, coleto y adhesivo LA: `saldo_inicial`, `solicitado`, `consumo`, `saldo_final` | 10 manuales; 10 calculados |
| Producción | 39–46 | `numero_de_bandejas`, `numero_de_columnas`, `rollos_por_log`, `rollos_por_jaba`, `peso_jaba`, `peso_acumulado` | 6 manuales; `total_rollos` y `total_jabas` calculados |
| Rodelas | 47–56 | `saldo_inicial_rodela`, `numero/peso/tipo` de la inferior y de la superior | 7 manuales; `saldo_final_rodela` y los dos `consumo_rodela_*` calculados |
| Cuchilla | 57–60 | `saldo_inicial`, `solicitado` | 2 manuales; `consumo` y `saldo_final` calculados |
| Observaciones | 61 | `observaciones` (textarea) | opcional |

Suma: automáticos 5; manuales 8 + 10 + 6 + 7 + 2 + 1 = 34; calculados 4 + 1 + 10 + 2 + 3 + 2 = 22.

### Corrección del conteo de campos «Condicional / repetible»: 10, no 8

La clasificación legacy marca **10** campos como «Condicional / repetible»: `saldo_inicial_bobina_inferior` (6), `numero_bobina_inferior` (7), `peso_bobina_inferior` (8), `saldo_inicial_bobina_superior` (12), `numero_bobina_superior` (13), `peso_bobina_superior` (14), `numero_bobina_rodela_inferior` (49), `peso_rodela_inferior` (50), `numero_bobina_rodela_superior` (53) y `peso_rodela_superior` (54). El resto de la clasificación: 22 «Calcular», 19 «Mantener», 1 «Mantener opcional», 4 «Catálogo / selección» (los cuatro `tipo_*`), 4 «Automatizar / catálogo» y 1 «Automatizar».

El §8 de M6-A decía **8**. Era un error de conteo: se contaron solo los pares número/peso de las dos bobinas y las dos rodelas (4 × 2) y **se omitieron ambos `saldo_inicial` de las bobinas** (campos 6 y 12). El número correcto es 10. No cambia ninguna otra cifra ni decisión; esta nota lo corrige sin reescribir el documento de M6-A.

## 3. Definición legacy frente a la pantalla de tres filas

La pantalla actual (`MaterialConsumption`, `app/page.tsx`) tiene **tres filas fijas** (`rows=[0,1,2]`). Cada una trae «Posición» (Superior / Inferior / No aplica), «Tipo según receta» (la receta completa), «N.º bobina», saldo inicial, ingreso, saldo final (kg) y un readout «Consumo calculado» (`inicial + ingreso − final`). Debajo se monta el panel `Recipe`, común con P1-13.

| | Definición | Pantalla |
|---|---|---|
| Estructura de bobinas | 2 posiciones con campos propios (inferior y superior) | 3 filas genéricas con «posición» como lista |
| Ingreso | no existe (usa `peso_bobina_*`) | sí |
| Saldo final y consumo | calculados | `saldo_final` es entrada; el consumo se guarda **solo** al editar `saldo_final` (queda desactualizado si se edita antes otra celda) |
| Rodelas, insumos, producción y cuchilla | 10 + 20 + 8 + 4 campos | **ausentes** (los insumos solo aparecen en el panel de receta) |
| Merma | `merma_total` calculado | «se registra por separado» |
| «No aplica» | no existe | existe (parece un artefacto de las filas fijas) |

Ninguna de las dos estructuras (61 campos o tres filas) se asume como la estructura industrial definitiva, y ninguna se implementa.

## 4. Contrato candidato (hipótesis de prueba)

**Un grupo repetible `_groups.bobinas`**, más `observaciones` fuera del grupo:

| Campo | Dónde | Tipo en el motor | Obligatorio |
|---|---|---|:-:|
| `numero_bobina` | fila | `text` | sí |
| `posicion` | fila | `text` con opciones `superior` / `inferior` | sí |
| `saldo_inicial_kg` | fila | `decimal` | sí |
| `ingreso_kg` | fila | `decimal` | sí |
| `saldo_final_kg` | fila | `decimal` | sí |
| `observaciones` | simple | `textarea` | no |

El backend deriva máquina, OT, línea, artículo/producto, turno, fecha operativa y usuario; el payload solo lleva `capture_id`, `form_code`, `assignment_id`, `device_key` y `values`. Cualquier otra clave —un consumo, un tipo, `rodelas`, un id de fila, `bobbin_id`, `maquina`…— se rechaza con 422, y las pruebas lo comprueban tanto como valor simple como dentro de una fila y como grupo no declarado.

**Cardinalidad:** `repeatable = true`, `min_rows = 1`, `max_rows = NULL`. Se permiten varias filas con la misma posición y **no se impone unicidad** al número de bobina entre filas ni entre capturas. No hay `no_aplica`.

> **Máximo funcional frente a límite técnico.** No existe ningún máximo funcional definido: `max_rows` es `NULL` y nada en el contrato dice cuántas bobinas puede tener una captura. El único tope es el **límite técnico del sistema** (`TECHNICAL_MAX_GROUP_ROWS = 1000` filas por grupo, el mismo en el backend y el cliente) que existe para evitar cargas absurdas; **no es una regla industrial** y la pantalla lo dice («no hay máximo funcional definido (solo el límite técnico del sistema)»). Una captura de 50 filas se acepta, una de 1001 se rechaza con «máximo 1000 filas». El mínimo de una fila y las dos posiciones son decisiones exclusivamente de este contrato candidato.

### Saldos declarados

Los tres saldos y el número de bobina son **declaraciones independientes**, almacenadas como se escribieron (la coma se normaliza a punto; sin redondeo ni conversión):

- No se calcula ni se guarda consumo físico, saldo disponible oficial, merma, diferencia de inventario ni balance de materiales; la fórmula `saldo inicial + ingreso − saldo final` **no existe** en el código del contrato y una prueba lo vigila.
- No se bloquea que el saldo final supere al inicial; no hay mínimos, máximos, decimales fijos ni redondeos de negocio (un negativo es estructuralmente válido). Los decimales se reutilizan de las validaciones estructurales de los grupos (`capture-groups.ts`).
- «kg» es una etiqueta de la hipótesis legacy; la unidad oficial sigue pendiente.
- El historial muestra las bobinas «tal cual se declararon», en orden, **sin sumas, totales ni columna de consumo**; «No es un libro de existencias».

## 5. Límites de trazabilidad

`numero_bobina` es **texto declarado**. Una captura P1-11 crea exactamente **una** fila `capture` y sus filas de grupo, y nada más:

- no consulta `vinto_txn.bobbin`, no crea `bobbin_relation`, no crea movimientos de inventario, no consulta ni cambia liberaciones de Calidad, no descuenta material, no crea ni numera bobinas y no crea registros P1-13 (ni P1-12 ni P1-16) automáticos.
- Una prueba usa números con forma de código F3 (`BM-2609-001`, `1`, `RP-0001`) y comprueba que no se crea bobina, relación, liberación ni secuencia, que no existe ninguna bobina con esos códigos y que `capture.bobbin_id` queda nulo. El E2E repite el control sobre las cuatro tablas (`bobbin`, `bobbin_relation`, `quality_release`, `bobbin_sequence`) antes y después de la captura y al final del recorrido completo.

## 6. Por qué se difieren las rodelas y los insumos

- **Rodelas:** el motor ya admitiría un segundo grupo (P1-29 tiene dos), pero las rodelas tienen otra estructura en la definición: un único `saldo_inicial_rodela` / `saldo_final_rodela` para ambas posiciones y atributos propios (tipo, consumo por posición). Separarlas hoy equivaldría a inventar esa estructura (decisión B-2).
- **Insumos (fragancia, carpicola, transferencia, coleto, adhesivo LA) y cuchilla:** 24 campos con `solicitado`, saldos y consumos calculados, sin equivalente en la pantalla; dependen de fórmulas y de la receta, que no están homologadas (B-3).
- **Producción** (bandejas, columnas, rollos, jabas, `peso_jaba`, `peso_acumulado`): se solapa con P1-12 y sus pesos dependen del maestro nominal, sin homologar (B-4).
- **Tipo de bobina:** catálogo o receta legacy; no se usan recetas como autoridad.

Un segundo grupo se puede añadir después sin cambiar el motor.

## 7. Riesgo de doble conteo con P1-13

P1-11 (Gambini, Sincro II, Sincro III) y P1-13 (máquinas de servilletas) piden lo mismo —bobina, saldo inicial, ingreso y saldo final— con **estructuras distintas** (P1-11: filas repetibles con posición; P1-13: una sola bobina por captura). Hoy nada impide que el mismo número de bobina se declare dos veces en una captura, en dos capturas, en dos turnos o en los dos formularios, ni se compara el saldo final de un turno con el inicial del siguiente. Esto es consecuencia deliberada de que son declaraciones y se resuelve con las decisiones N-3 (identidad de la bobina), N-5 (balance) y B-1 a B-6. Si se homologa un modelo único de consumo, ambos formularios tendrían que migrar.

## 8. Cómo se comporta

- **Navegación (fixtures):** con `E2E_P111=on`, GAMBINI ofrece P1-11, P1-12 y P1-16; WALLY ofrece solo P1-13 (si `E2E_P113=on`) y **no** ofrece P1-11; el formulario vinculado pero sin publicar no aparece. Con la política real o sin concesión: «Conversión no está habilitado», sin datos demo ni legacy como respaldo.
- **Pantalla:** una fila inicial (no tres), «Agregar fila» y «Eliminar» (no se puede eliminar la última fila: mínimo 1), errores por fila y por grupo, y el mismo bloqueo de campos y filas con un intento pendiente que P1-29.
- **Envío:** `capture_id` fijo por intento, reintento idempotente, reconciliación por `GET`, 409 `ASSIGNMENT_STALE` / `ASSIGNMENT_NOT_ACTIVE` con mensaje claro, 401, y la misma captura con las filas **reordenadas** es un conflicto (409), como define M3-A.
- **Registros locales:** no se escribe `vinto-p1-records`, `vinto-ot` ni `vinto-asg`; los registros legacy no se borran ni se convierten (el E2E siembra uno y comprueba que se conserva).
- **Bandera `E2E_P111`:** desactivada por defecto y válida solo con Conversión habilitada en el proceso. Con `off`, el servidor de prueba no instala P1-11 y los escenarios de M6-A, M6-B y M6-C se conservan exactamente.

## 9. Pruebas ejecutadas

Línea base de `origin/main` `4b29835`: Node 503 OK; backend 938 pruebas con 2 fallos propios del entorno (ver §12).

| Prueba | Resultado |
|---|---|
| Backend `test_m6d_conversion_p111` (focalizada) | **26 OK** |
| Backend suite completa | **964 pruebas, 962 OK**; los 2 fallos son `test_db_guard.RealConnectionTests` (requieren DEV, ver §12), los mismos de la línea base (938 pruebas) |
| Node completo | **520 OK** (503 + 17 nuevas) |
| `tsc --noEmit` | único error: el TS2322 heredado de `app/page.tsx` |
| `eslint .` | 0 errores; 2 avisos heredados (`m4a-e2e.mjs`, `export-seed-data.mjs`) |
| `build` (sin ruta de QA; rutas `/` y `/admin`) | OK |
| E2E P1-11 habilitado (`m6d-e2e.mjs`, Chrome real + FastAPI + PostgreSQL efímero) | **64/64** |
| E2E P1-11 con la configuración real (deshabilitado) | **12/12** |
| Regresión M6-C (`m6c-e2e.mjs`, `E2E_P111` off) | **62/62** habilitado, **12/12** deshabilitado |
| Regresión M6-B (`m6b-e2e.mjs`, `E2E_P111` off) | **59/59** habilitado, **12/12** deshabilitado |
| Regresión M6-A (`m6a-e2e.mjs`, `E2E_P111` off) | **53/53** habilitado, **13/13** deshabilitado |
| Regresión M4-A Rebobinado (`m4a-e2e.mjs`) | **49/49** habilitado, **12/12** deshabilitado |

Bobinas se cubre con las suites disponibles (backend completo y Node completo) y con los controles de Bobinas de los E2E (su programación central sigue mostrando MP1 y MP3); el repositorio no tiene un E2E de navegador propio de Bobinas. Ninguna prueba abre una conexión a DEV (`m4a-e2e.mjs` mantiene `E2E_DEV_READ` desactivado por defecto; `m6a` a `m6d` nunca leen DEV).

### Cobertura de las pruebas backend solicitadas

| # | Cubre |
|---|---|
| 1 | `test_the_shipped_configuration_is_unchanged`, `test_without_the_test_configuration_p111_is_unreachable` |
| 2 | `AvailabilityTests` (GAMBINI sí, WALLY no, sin concesión, sector no operativo, política) |
| 3–5 | `test_201_one_row…`, `test_several_rows_keep_their_order…`, `test_no_uniqueness…` |
| 6 | `test_the_group_cannot_be_empty_or_absent_min_rows_is_one` |
| 7 | `test_the_technical_cap_is_respected…` |
| 8 | `test_a_position_outside_the_catalog_is_rejected` |
| 9–10 | `test_no_industrial_rule_is_invented_on_the_balances` |
| 11 | `test_computed_or_additional_values_are_rejected`, `test_422_invalid_rows_persist_nothing` |
| 12–13 | `IdempotencyTests` (201/200, 409 por contenido, reordenado, menos filas y otro formulario; concurrencia) |
| 14 | `ShiftTests` (turnos, medianoche, asignación terminada) |
| 15–16 | `ScopeAndAvailabilityTests` |
| 17 | `test_the_capture_is_audited_with_the_actor_rows_included` |
| 18–19 | `NoInventoryNoGenealogyTests` |
| 20 | `test_p113_p112_and_p116_stay_independent_of_p111` |

## 10. Decisiones pendientes de VINTO (nuevas)

Todas **pendientes**; no repiten C-1 a C-11, P-1 a P-11 ni N-1 a N-8, a las que se refieren.

| # | Decisión | Relacionada con |
|---|---|---|
| B-1 | Cuántas bobinas por posición y turno: filas variables o dos posiciones fijas; qué significa «No aplica» | C-1, N-1 |
| B-2 | Estructura de las rodelas: grupo propio, saldo único para ambas posiciones, relación con las bobinas | C-1 |
| B-3 | Si los insumos (fragancia, carpicola, transferencia, coleto, adhesivo LA) y la cuchilla van en la misma ficha, y cómo se declaran `solicitado` y los saldos | N-6, C-9 |
| B-4 | Si la producción (bandejas, columnas, rollos por log y por jaba, `peso_jaba`, `peso_acumulado`) pertenece a P1-11 o a P1-12, para no contarla dos veces | P-1, P-8 |
| B-5 | Qué es `peso_bobina` frente al saldo y el ingreso: peso de la bobina montada, peso nuevo o saldo | N-4 |
| B-6 | Si el consumo exige que la bobina esté liberada por Calidad y cómo se trata una rechazada | N-3, P-10 |

## 11. Qué necesitaría una versión homologada

1. Respuesta a B-1 a B-4: la estructura real de la ficha (bobinas, rodelas, insumos, producción) y qué se declara y qué se calcula; la definición publicada con sus grupos, cardinalidades y opciones.
2. Fórmulas homologadas: consumo y saldo final por bobina, rodela, insumo y cuchilla; `total_rollos` [H: bandejas × columnas × rollos por log], `total_jabas` [H: total de rollos ÷ rollos por jaba], `peso_acumulado` y `merma_total`. Ninguna está en el código legacy distinta de `inicial + ingreso − final`, y con ello decidir dónde se calculan (hoy el motor rechaza los campos `calculated`).
3. Identificación de la bobina (N-3): hoy solo existe `GET /api/bobbins/{id}`; no hay búsqueda ni listado para elegir una bobina, y `bobbin.code` no es único global. Vincular por UUID exigiría un endpoint de lectura con alcance, un tipo de campo UUID (el motor no lo tiene) y posiblemente una tabla de consumo; no se implementa aquí.
4. P1-07 (genealogía) y Calidad (B-6): no hay servicio de consumo ni de liberación (M5-A).
5. Datos maestros de Conversión aprobados (GAMBINI, SINCRO II y SINCRO III y sus artículos) e importados de forma controlada; el formulario publicado, añadido a la política de captura central y al sector operativo mediante PRs revisados y separados (nunca aquí).
6. Mecanismo de firma o aprobación, si se exige.
7. Nuevo E2E con datos oficiales y confirmación de que Bobinas y Rebobinado no regresan.

## 12. Limitaciones

- Es un circuito **candidato**: el contrato, las posiciones, el mínimo de una fila, los turnos y los fixtures son hipótesis de prueba. Se usa **GAMBINI ficticia** (SINCRO II y SINCRO III no se instalan) y el artículo de Bobinas del fixture, no un artículo de Conversión.
- Un error de fila permanece visible hasta el siguiente envío (igual que en P1-29): es un comportamiento de la pantalla, no una validación pendiente.
- Las dos pruebas de `test_db_guard.RealConnectionTests` (`test_dev_database_is_rejected`, `test_name_inside_connection_string_is_not_trusted`) necesitan conectarse a DEV y **no se ejecutaron**: se corrió con `DATABASE_URL` apuntando a la base de pruebas. Fallan igual en `origin/main` con esa configuración. No se modificaron.
- El TS2322 de `app/page.tsx` es heredado y no se tocó.
- Las bases efímeras se crean en el mismo servidor PostgreSQL local que DEV (como en M2–M6-C); se eliminan al terminar.
- Rodelas, insumos, producción, cuchilla y tipos de bobina no se implementan.
