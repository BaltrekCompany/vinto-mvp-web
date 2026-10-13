# M3-B · VINTO-P1-29 «Producción Tubetera»: captura central CANDIDATA (E2E en entorno aislado)

**Estado: ficha candidata, NO homologada, NO operativa.** Es técnicamente funcional de extremo a extremo (componente React → API → PostgreSQL) **solo en un entorno de prueba aislado**, con datos y configuración ficticios. P1-29 no está en `CENTRAL_FORM_CODES`, Rebobinado no es un sector operativo, `backend/seed_data` no contiene P1-29, no hay migraciones, no hay ruta ni enlace en la aplicación y DEV no se tocó.

## Qué es
Reutiliza sin duplicar: el motor multiformulario (M2-A), los grupos repetibles (M3-A, `values._groups`), el kit (`capture-kit.tsx`, `RepeatableGroup`), el núcleo (`capture-core.ts`, `capture-groups.ts`) y las operaciones HTTP genéricas (`postCaptureOf` / `getCaptureOf` / `listCapturesOf`).

| Pieza | Archivo |
|---|---|
| Contrato del cliente (especificación, validación estructural, payload, intento, parsers con `expectedFormCode = VINTO-P1-29`) | `lib/vinto/p1-29.ts` |
| Cliente HTTP | `lib/vinto/p1-29-api.ts` |
| Componente | `components/vinto/p1-29-capture.tsx` (`P129CaptureForm`) |
| Fixtures de prueba (máquina TUBETERA ficticia + definición candidata) | `backend/tests/m3b_fixtures.py` |
| Pruebas | `backend/tests/test_m3b_p129_central.py`, `scripts/p1-29-capture.test.mjs` |
| E2E aislado (harness temporal **no publicado** + driver) | `scripts/e2e/harness-p129-page.tsx.txt`, `scripts/e2e/p129-e2e.mjs` (servidor: `backend/tests/e2e_p110_server.py`) |

## Modelo candidato (propuesta técnica, no decisión industrial)
La definición legacy tiene 20 campos: **17 manuales** y 3 automáticos. Se conservan claves y tipos originales (las cantidades siguen siendo **texto**, los decimales siguen siendo decimales conservados como **texto** hasta la API). La agrupación proviene de la clasificación legacy («Detalle repetible», «Detalle repetible por formato», «dato global»).

| Bloque | Campos |
|---|---|
| Simples (6) | `fecha_de_produccion` (date, manual; **no** se sustituye por la fecha operativa), `lote_de_produccion`, `pegamento_total_kg`, `peso_fardo`, `numero_mrp_del_sistema` (text), `observaciones` (textarea, opcional) |
| Grupo `rodelas` (2) | `rodela_papel_kraft_identificacion` (text), `rodela_papel_kraft_peso_kg` (decimal) |
| Grupo `formatos` (9) | `formato_tipo_de_tubete`, `cantidad_tubetes_producidos_por_formato`, `cantidad_de_hojas_por_formato` (text), `cantidad_tubetes_observados_por_formato` (textarea, opcional), `merma_kg_por_formato`, `diametro_interno_mm_por_formato`, `diametro_externo_mm_por_formato`, `espesor_mm_por_formato`, `peso_kg_por_formato` (decimal) |
| Contexto pendiente (3) | `operador`, `turno`, `visto_bueno_responsable`: **no se almacenan como manuales simulados**; el turno lo deriva el servidor de la asignación; operador y visto bueno se muestran como «pendiente de definición» (la sesión autenticada se muestra solo como identificación) |

**Hipótesis exclusivas de prueba** (fixture y especificación del cliente): `rodelas` y `formatos` son repetibles con `min_rows = 1` y sin `max_rows` declarado (solo aplica el tope técnico de 1000 filas). No existen en la definición legacy y **no deben trasladarse a un bundle operativo sin confirmación de VINTO**.

## Discrepancias y decisiones abiertas (documentadas, NO corregidas por suposición)
1. **Nombre de la máquina:** la definición del frontend dice `tubertera`; el catálogo candidato identifica `TUBETERA`. La definición legacy no se tocó; la prueba usa una máquina ficticia `TUBETERA`.
2. **Unidad del espesor:** `espesor_mm_por_formato` se llama en mm pero la metadata legacy registra `kg`. La pantalla no muestra unidad para ese campo.
3. **Tipos de tubete:** la fuente propone un catálogo controlado que no existe; hoy es texto libre. No se creó un catálogo ficticio.
4. **Visto bueno:** hay que confirmar responsable, mecanismo y efectos sobre la aprobación; no se simula firma ni aprobación.
5. **Alcance de los grupos:** cantidad de filas de rodelas/formatos por lote/turno y si cada grupo es obligatorio.

### Matriz de decisiones para VINTO
| # | Decisión | ¿Bloquea la operación? | ¿Afecta presentación/validación? | Comportamiento hoy (aislado) |
|---|---|---|---|---|
| 1 | Agrupación definitiva (campos simples / rodelas / formatos) y su cardinalidad (`min_rows`, `max_rows`) | **Sí** (define el contrato publicado) | Sí | Hipótesis de prueba: ambos grupos repetibles, mínimo 1, sin máximo declarado |
| 2 | Datos maestros de Rebobinado: sector, máquina Tubetera (nombre real), turnos, relación artículo-máquina, habilitar el sector | **Sí** | No | Sector, máquina y turnos FICTICIOS |
| 3 | Operador y visto bueno/aprobación (quién, mecanismo, efecto) | **Sí** si la ficha exige aprobación; no para un registro técnico | Sí | Pendiente: no se capturan ni se simulan |
| 4 | Catálogo de tipos de tubete | No (puede seguir libre) | **Sí** (selector y validación) | Texto libre |
| 5 | Unidad del espesor (mm vs kg) | No | **Sí** (etiqueta, validación) | Sin unidad visible |
| 6 | Tipo definitivo de cantidades, pegamento, peso del fardo y número MRP (texto vs número), rangos | No | **Sí** | Texto tal cual declarado; decimales como texto con punto |
| 7 | Fecha de producción manual frente a fecha operativa de la asignación | No | **Sí** | Se guarda la tecleada; la operativa viene de la asignación |
| 8 | Generación/validación del número MRP | No (hoy se digita) | Sí | No se genera ni valida |

## Reproducir el E2E (solo en un worktree de QA)
1. Backend aislado: `python tests/e2e_p110_server.py` en un contenedor desechable (puerto ≠ 8000, origen ≠ 8787, `CORS_ORIGINS` = origen del frontend de QA). Crea una base `*_test` nueva con la máquina TUBETERA ficticia y la definición candidata.
2. Copiar `scripts/e2e/harness-p129-page.tsx.txt` a `app/qa-harness/page.tsx`, construir con `NEXT_PUBLIC_API_URL=http://127.0.0.1:8190` y servir en el puerto 8796.
3. `node scripts/e2e/p129-e2e.mjs <creds.json> <carpeta-de-evidencias>`.
4. Eliminar el harness y detener el contenedor (que borra las bases efímeras).
El script aborta si la API/frontend son los de DEV, si la base no es `*_test` o no coincide con `current_database()`, si el backend no sirve esa base o si el navegador llama al puerto 8000; solo lee DEV con `SELECT` para comprobar que no cambió.

## Fuera de alcance
Activar Rebobinado, importar maestros, modificar el bundle real, inventario de rodelas o consumo, generar MRP, aprobación electrónica, genealogía, recetas, eliminar formularios legacy, el hotfix de `/admin`.
