# M5-A · Fundamentos de genealogía P1-07 (madre/hija)

**Estado: estudio técnico y pruebas en PostgreSQL efímero. P1-07 NO está implementado, NO está en `CENTRAL_FORM_CODES`, NO está en ningún bundle y Rebobinado sigue NO homologado y NO operativo.**
No hay migraciones, ni cambios de código de producción, ni de `backend/seed_data`, `sectors.py` o concesiones. Todo lo escrito en pruebas ocurre en bases nuevas `*_test`. Nada aquí es una regla industrial aprobada.
Base: `09fd0e5` (PR #27). Se añaden: este documento, `backend/tests/m5a_fixtures.py`, `backend/tests/test_m5a_genealogy_feasibility.py` (21 pruebas) y `scripts/p107-contract.test.mjs` (5 pruebas).

**Respuesta corta.** El esquema actual **puede guardar** una relación madre→hija entre bobinas identificadas por UUID, pero **no la protege ni la modela por completo**: no hay cardinalidad, ciclos (solo se prohíbe la autorreferencia), reglas de máquina/sector, vínculo entre la relación y la captura que origina la hija, ni cantidades consumidas/sobrantes; la relación es modificable y borrable; y **una captura solo puede originar UNA bobina numerada** (`bobbin_source_capture_uidx`), lo que impide que una captura P1-07 produzca varias hijas numeradas. Además la definición legacy de P1-07 **no contiene ningún campo que identifique la bobina madre**.

## 1. Hechos confirmados frente a hipótesis

**Confirmados por la fuente** (`lib/vinto/form-definitions.ts`; anclados en `scripts/p107-contract.test.mjs`):
- `VINTO-P1-07` «Registro de producción de bobinas refiladas», área producción, máquinas legacy `copasa`, `beloit`, `over`, workflow `production-standard`.
- 41 campos, claves únicas, `order` 1–41: **5 automáticos** (`fecha`, `hora_inicio`, `hora_final`, `turno`, `operador`), **35 manuales obligatorios** y 1 manual opcional (`observaciones`).
- `peso_cria_1`…`peso_cria_11` y `peso_cria_13`…`peso_cria_22` (**21 campos; no existe `peso_cria_12`**). Todos `decimal`, `kg`, obligatorios, clasificados «Condicional / repetible» (la propuesta legacy dice «detalle repetible o solo cuando aplique a la máquina/producto»: **contradice que sean obligatorios**).
- `formato_1/2/3` son `decimal` sin unidad, «Catálogo / selección». `tubete`, `metraje` y `tension` son texto; la fuente dice que su interpretación «debe contrastarse con el responsable del proceso».
- No existe ninguna clave que identifique una bobina madre/de entrada, ni cantidades consumidas, sobrantes o mermas.

**Hipótesis técnicas (NO confirmadas por VINTO):** que «cría» = bobina hija; que cada `peso_cria_*` corresponde a una salida física; que la numeración con salto en 12 es un error de fuente o una posición intencionalmente vacía; que `etiqueta_numero_de_bobina` identifica una salida (o la entrada); que `peso` es el peso de entrada o de salida. **No se asume que cada peso identifique automáticamente una bobina hija.**

## 2. Mapeo de los 41 campos (A–F)
Leyenda de fuente: A = automático legacy, M = manual. «Hipótesis» = interpretación técnica, sin aprobación.

| Bloque | Campos (orden) | Observaciones |
|---|---|---|
| **A. Captura operativa** | `fecha`(1,date,A), `hora_inicio`(2,time,A), `hora_final`(3,time,A), `turno`(8,A), `operador`(9,A), `auxiliar`(10,text), `velocidad_minima`(11,dec m/min), `tension`(12,text), `velocidad`(13,dec m/min), `metraje`(14,text), `diametro`(15,dec mm), `tubete`(19,text), `observaciones`(41,textarea, opcional) | Fecha/turno/operador/OT los deriva el backend de la asignación (patrón F3/P1-10). Dudas: unidad de `metraje`, significado de `tension` y `tubete`. |
| **B. Identificación del material de entrada** | **ninguno explícito.** Candidatos ambiguos: `etiqueta_numero_de_bobina`(4,text), `peso`(5,dec kg) | Hipótesis: la etiqueta podría ser de la bobina madre; la fuente solo dice «identificador para trazabilidad del material, producto o transacción». Sin decisión, **no hay forma legacy de nombrar la madre.** |
| **C. Productos de salida** | `producto_refilado`(7,text, catálogo), `destino`(6,text, catálogo), `formato_1/2/3`(16–18,dec), `tubete`(19) | `producto_refilado` es texto libre hoy; el catálogo/artículo de la línea de OT es la alternativa (decisión C de M4-B1). |
| **D. Relación madre/hija** | **ninguno.** Hipótesis: `peso_cria_*`(20–40) podrían ser el peso de cada hija | Sin identificador de hija ni de madre; los 21 pesos no bastan para crear bobinas con identidad. |
| **E. Cantidades consumidas, sobrantes y mermas** | **ninguno.** `peso`(5) y `peso_cria_*` son los únicos pesos | Un balance de masas requeriría saber qué es `peso` (entrada/salida/neto) y cómo se registran merma y sobrante: no definido. |
| **F. Reglas pendientes de Calidad** | — (no hay campos) | ¿Debe la madre estar liberada para rebobinar? ¿Qué pasa si está rechazada? ¿Las hijas heredan estado o entran pendientes? Ver §6. |

## 3. Evaluación del modelo existente (migraciones 0001–0006)

| Tabla | Lo que SÍ garantiza | Lo que NO garantiza / limitación (verificada por pruebas) |
|---|---|---|
| `bobbin` | UUID, `code` visible, correlativo F3 por (máquina, gestión), artículo/máquina/gestión coherentes con la captura (trigger 0004), identidad inmutable, `quality_release` obligatorio al confirmar (trigger diferido) | **Una bobina numerada por captura** (`bobbin_source_capture_uidx`); `code` **no** es único global (el «1» existe en cada máquina) ⇒ solo el UUID identifica; sin vínculo a sector salvo vía máquina; filas «legacy» (sin correlativo) no tienen máquina y los servicios no las ven |
| `bobbin_relation` | UUID, FK a madre, hija y captura (`ON DELETE RESTRICT`), `CHECK madre<>hija`, `UNIQUE(madre,hija)`, auditoría de alta/cambio/baja | Sin cardinalidad (una hija puede tener varias madres; una madre, cualquier número de hijas); **ciclos A→B→A permitidos**; sin regla de máquina/sector (madre MP1 e hija COPASA, y viceversa, aceptados); `capture_id` no se compara con la captura de la hija ni exige ser P1-07; **mutable y borrable** (sin trigger de inmutabilidad); sin cantidad consumida/rol/orden; sin clave de idempotencia (el reintento exacto lo frena solo el UNIQUE) |
| `quality_release` | 1 por bobina, estados `pending/released/rejected`, coherencia de `decided_*` | **Ningún servicio libera ni rechaza** (el permiso `quality.release` existe sin uso); no se relaciona con relaciones ni consumo; una fila `released` creada por SQL no es una liberación autorizada |
| `bobbin_sequence` | Contador por (máquina, gestión), solo avanza de 1 en 1, no se borra | Compartido: las hijas numeradas de una máquina consumirían el mismo correlativo que F3 |
| `capture` / grupos repetibles (M3-A) | Idempotencia por `capture_id`, `values._groups` con filas ordenadas | Los grupos son datos de captura, no crean bobinas ni relaciones |
| Permisos / sectores | `production.capture`, alcance = concedidos ∩ operativos (por máquina) | Una relación cruza máquinas: el alcance de lectura de genealogía necesita regla explícita (¿visible si se ve un extremo o los dos?) |

Compatibilidad con F3: el circuito F3 no cambia ni se ve afectado (F3 no crea relaciones). Las hijas numeradas por P1-07 compartirían correlativo y bandeja de Calidad con F3 (cada una entra `pending`).

## 4. Prueba técnica en PostgreSQL efímero
`backend/tests/test_m5a_genealogy_feasibility.py` (21 pruebas OK; base copiada de la plantilla migrada con el bundle aprobado; política y sectores parcheados **solo dentro del proceso de prueba**, la configuración real se comprueba intacta):
1. **Madre real por F3** (captura + bobina + `quality_release pending` en una transacción): identificación («1» en MP1), artículo, peso y estado inicial `pending`; F3 no crea relaciones.
2. **Escenario sintético** (`m5a_fixtures.py`, SQL directo, nunca API): captura del formulario de pruebas `VINTO-TEST-P107-SYN` en COPASA ficticia por el motor central, hijas numeradas con correlativo y `quality_release`, relaciones.
3. **Persistir y consultar:** relación guardada y leída por UUID; lectura recursiva de descendientes y ancestros con protección de ciclos (propuesta de consulta en `m5a_fixtures.py`, no es una API).
4. **Rechazos correctos:** autorreferencia (CHECK), vínculo duplicado (UNIQUE), madre/hija/captura inexistentes (FK), bobina numerada con máquina distinta de la captura (trigger), bobina numerada sin `quality_release` (trigger diferido).
5. **Limitaciones afirmadas a propósito:** varias madres por hija; ciclo A↔B aceptado; `capture_id` desligado de la hija; relación mutable/borrable (con auditoría de las tres operaciones); relación entre sectores en ambos sentidos; **2.ª bobina numerada de la misma captura rechazada**; hijas «legacy» comparten captura pero no tienen máquina y los servicios no las ven; hijas de Rebobinado consumen el mismo correlativo; toda hija numerada entra a Calidad como `pending`.
6. **Calidad pendiente/liberada/rechazada** probados como estados de prueba: la relación no depende de ninguno (no se define cuál habilita el consumo).
7. **Transaccionalidad:** un fallo revierte hijas, relaciones y contador a la vez. **Auditoría:** `bobbin`, `bobbin_relation`, `quality_release` y `bobbin_sequence` registran al actor.
8. **Regresión:** F3, F6, capturas centrales, P1-10, grupos repetibles, P1-29 y Calidad (295 pruebas) sin cambios.
Si una migración futura cierra una limitación, la prueba correspondiente debe cambiarse de forma consciente.

## 5. Contrato candidato madre/hija (propuesta; NO integrada a la política central)
Operación futura `P1-07` sobre el motor central (misma forma que P1-10/P1-29: `capture_id`, `form_code`, `assignment_id`, `device_key`, `values`) más:
- **Madres:** lista de `bobbin_id` (UUID) obtenidos por consulta, **nunca** por código visible. El backend verifica existencia, alcance de sector y estado de Calidad según la regla que VINTO decida.
- **Salidas:** grupo repetible `salidas` (M3-A) con `output_key` estable por fila (clave de idempotencia junto con `capture_id`), peso y atributos que VINTO apruebe. El backend crea las hijas (correlativo, artículo de la asignación) en la misma transacción; el cliente nunca envía ids de hija.
- **Relación:** una fila por (madre, salida) con `capture_id` = la captura P1-07 (obligatorio e igual al origen de la hija), orden estable y, **solo si VINTO lo aprueba**, cantidad consumida.
- **Idempotencia:** mismo `capture_id` ⇒ misma respuesta; mismas `output_key` ⇒ sin duplicar hijas ni relaciones; payload distinto con el mismo `capture_id` ⇒ 409.
- **Calidad:** estado de cada madre en el momento del consumo se registra/lee; las hijas nacen `pending` (comportamiento actual de toda bobina numerada).
- **Consulta:** `GET /api/bobbins/{id}/genealogy` (ancestros/descendientes con profundidad) con alcance por sector definido por VINTO; historial de la captura P1-07.
**Ya soportado:** UUID, idempotencia por captura, grupos repetibles, correlativo, auditoría, contexto de asignación. **Requiere decisión de VINTO:** todo lo de §6.

## 6. Matriz de decisiones para VINTO
| # | Decisión (pregunta cerrada cuando es posible) | Bloquea M5-B | Hoy |
|---|---|---|---|
| 1 | ¿El campo `etiqueta_numero_de_bobina` identifica la bobina de ENTRADA (madre) o una de SALIDA? (Entrada / Salida / Ninguna) | Sí | Ambiguo |
| 2 | ¿Cómo se identifica la bobina madre en la ficha? (Escaneo/selección de la bobina registrada en F3 / Texto) | Sí | No existe campo |
| 3 | ¿Cada `peso_cria_*` es una bobina hija con identidad propia? (Sí / No, es solo peso) | Sí | Hipótesis |
| 4 | ¿Cuántas hijas puede tener una ficha y son obligatorias las 21? (Mínimo/máximo; opcionales) y ¿se corrige la numeración sin `peso_cria_12`? | Sí | 21 campos obligatorios |
| 5 | ¿Una hija puede tener más de una madre? (No / Sí, hasta N) | Sí | Sin límite |
| 6 | ¿Una ficha consume una o varias madres? | Sí | Sin límite |
| 7 | ¿Se registra consumo parcial y sobrante? ¿En qué unidad y quién lo calcula? | Sí si hay inventario | No modelado |
| 8 | ¿Qué es `peso` (bruto/neto, entrada/salida)? ¿Cómo se registran mermas? | Sí si hay balance | Ambiguo |
| 9 | ¿Puede la madre estar en otra máquina/sector (Bobinas → Rebobinado)? ¿Restricciones? | Sí | Sin regla |
| 10 | Calidad: ¿la madre debe estar liberada para rebobinar? ¿Qué hacer si está rechazada o pendiente? | Sí | Sin regla |
| 11 | ¿Quién libera/rechaza y con qué flujo? (no existe operación; `quality.release` sin uso) | Sí si 10 exige liberación | Sin servicio |
| 12 | ¿Las hijas heredan estado de Calidad o entran `pending` y pasan por Calidad? | Sí | Entran `pending` |
| 13 | ¿Las hijas usan el correlativo F3 de la máquina o un correlativo propio? | Sí | Compartido |
| 14 | ¿Se corrige/anula una relación registrada? ¿Quién y cómo (versión, anulación con motivo)? | Sí | Mutable sin control |
| 15 | Alcance de lectura de la genealogía entre sectores | Sí | Sin regla |
| 16 | Máquinas de P1-07: COPASA, BELOIT y OVER (legacy) frente a la matriz de M4-B1 | Sí | Legacy sin aprobar |
| 17 | `producto_refilado`/`destino`/`formato_*`/`tubete`: catálogo o texto libre; unidad de `formato_*` y `metraje` | No (validación) | Texto/decimal |
| 18 | Firma/aprobación y responsable (mismo punto abierto que P1-10) | Según ficha | Pendiente |

## 7. Cambios mínimos para un futuro M5-B funcional (solo tras las decisiones)
1. **Migración 0007 (aditiva):** reemplazar `bobbin_source_capture_uidx` por una unicidad que permita N salidas por captura (p. ej. clave `(source_capture_id, output_key)` con `output_key` en `bobbin`) **sin tocar F3** (F3 sigue 1 por captura: restricción parcial para su forma).
2. **Guardas en `bobbin_relation`:** trigger de coherencia (la `capture_id` de la relación = `source_capture_id` de la hija; sin ciclos; reglas de máquina/sector que VINTO apruebe), inmutabilidad (o anulación con motivo), y, solo si se aprueba, columna de cantidad consumida y orden.
3. **Idempotencia propia:** índice único por (captura, `output_key`, madre).
4. **Servicio y API P1-07** (madres, grupo `salidas`, transacción única, 409 por payload distinto), permisos `production.capture` + lectura de genealogía con alcance.
5. **Calidad:** el servicio de liberación/rechazo (hoy inexistente) o, como mínimo, la regla de lectura del estado de la madre.
6. **Definición oficial de P1-07** en el exportador/bundle (con campo de madre y salidas aprobadas), versión publicada y vínculo a máquinas aprobadas.
7. **Aparte y posterior:** añadir el código a `CENTRAL_FORM_CODES`, habilitar el sector, concesiones, pantallas.
Sin inventario ni balance de masas hasta que VINTO los defina (ni en M5-B por defecto).

## 8. Evidencia y limitaciones
- 21 pruebas de factibilidad + 5 de contrato legacy nuevas; 295 de regresión (F3, F6, capturas centrales, P1-10, grupos, P1-29, Calidad) OK; sin cambios de código de producción.
- Límites del estudio: las hijas se insertan por SQL (no hay API); la «captura P1-07» usa un formulario de pruebas de 3 campos, no la ficha real; la lectura recursiva es una propuesta y no una API; no se probó concurrencia de varias fichas sobre la misma madre (depende de las decisiones 6–7); no se evaluó rendimiento.
- Sigue pendiente la homologación de Rebobinado (`docs/M4-B1-homologacion-rebobinado.md`), que precede a cualquier habilitación.
