# MF-12B · P1-04 v2 (consumo de fibra) y P1-16 v3 (control de merma)

## 1. Objetivo
Atender, con versionado aditivo y sin tocar capturas históricas, las observaciones **MD_Ejec 17 y 44** del Excel funcional `MvP (Producción + Calidad) - v2.xlsx` (hoja `MD_Ejec.`). El Excel original **no se modifica**. Base: `main` tras MF-12A (PR #81, merge `ebe9308`). Esta entrega es **solo un PR revisable**: no se despliega ni se importa nada en producción.

## 2. Observaciones atendidas
| Obs. | Formulario | Cambio |
|---|---|---|
| **17** | **P1-04 v2** (MP1 y MP3) | **Un registro por consumo**: hora de consumo, material, origen (según el material), presentación (según el material), cantidad de UM (entero), peso unitario real (decimal, kg) y observaciones. Subtotal **solo en pantalla**. |
| **44** | **P1-16 v3** (11 máquinas) | **Una pesada por captura**: horas generales (MF-11), número correlativo manual, tipo de merma (6 opciones), origen (3), peso real (decimal, kg) y observación opcional. |

## 3. Decisiones aplicadas (D3 a D7)
| ID | Decisión | Aplicación |
|---|---|---|
| **D3** | P1-04: hora de consumo obligatoria, cantidad entera, todo obligatorio salvo observaciones. | Tal cual (§4). |
| **D4** | P1-16: una pesada por registro; correlativo manual; horas generales de MF-11 sin cálculo de duración, UTC ni orden. | Tal cual (§5). |
| **D8** | El correlativo de P1-16 v3 es **único por OT + máquina** (manual, obligatorio, sin numeración automática; sin fecha ni turno en el ámbito; entre OT o máquinas distintas puede repetirse). | §8. |
| **D5** | Los valores de las listas se guardan como **texto literal**, no como claves técnicas. | `option_key` = texto visible; los valores guardados son «Fibra larga», «Hoja doble», etc. |
| **D6** | La relación Material–Origen y Material–Presentación se valida en pantalla **y en el backend**, solo en la versión nueva. | §6. |
| **D7** | Subtotal = Cantidad de UM × Peso unitario real (kg), **dos decimales**, precisión exacta, no editable y no persistido. | §7. |

## 4. P1-04 v2: campos y catálogos
| Campo (clave) | Tipo | Obligatorio | Detalle |
|---|---|---|---|
| `hora_consumo` | hora HH:MM | Sí | hora local de planta; guardada tal cual |
| `material` | lista | Sí | Fibra larga · Fibra corta · Recorte |
| `origen` | lista dependiente | Sí | Fibra larga → Laja, Susano, Dorado · Fibra corta → Laja, Cóndor · Recorte → Sauce Rancho, Máquina |
| `presentacion` | lista dependiente | Sí | Fibra larga y Fibra corta → Caja, Fardo · Recorte → Fardo |
| `cantidad_um` | entero | Sí | sin rango |
| `peso_unitario_real` | decimal, kg | Sí | sin rango ni límite de peso |
| `observaciones` | texto largo | No | conserva la clave de la v1 |

- **Seed:** `origen` publica la lista completa (Laja, Susano, Dorado, Cóndor, Sauce Rancho, Máquina) y `presentacion` (Caja, Fardo); la combinación válida la restringe la regla del §6.
- **Capturas v1:** sus ocho campos (`fibra_corta_detalle`, `fibra_larga_detalle`, `recorte_ph`, `recorte_servilleta`, `recorte_toalla`, `materia_prima_ph`, `materia_prima_servilleta`, `materia_prima_toalla`) pasan a **solo lectura** («versión anterior»); `observaciones` se conserva.
- **No hay campo de subtotal**, ni relación con genealogía, bobinas físicas, consumos efectivos o inventario.

## 5. P1-16 v3: campos y catálogos
| Campo (clave) | Tipo | Obligatorio | Detalle |
|---|---|---|---|
| `hora_inicio`, `hora_fin` | hora HH:MM | Sí | horas generales de MF-11, sin cambios |
| `numero_correlativo` | texto | Sí | **manual**, único por **OT + máquina** (§8) |
| `tipo_merma` | lista | Sí | Hoja doble · Hoja simple · Servilleta · Toalla · Cartón · Plástico |
| `origen_merma` | lista | Sí | Logs · Cola · Máquina |
| `peso_merma_kg` | decimal, kg | Sí | sin rango |
| `observacion` | texto largo | No | conserva la clave de v1 y v2 |

- Las seis cantidades en texto de v1 y v2 (`hoja_doble_kg`, `servilleta_kg`, `toalla_kg`, `carton_kg`, `hoja_simple_kg`, `plastico_kg`) pasan a **solo lectura**; **no se convierten en pesadas**.
- Las 11 máquinas de v2 se mantienen.

## 6. Validaciones frontend y backend
**Frontend** (`candidate-form.ts`: nuevo `dependsOn` de un campo lista):
- la lista de Origen y la de Presentación solo muestran las opciones del material elegido; si cambia el material y el valor ya no corresponde, se vacía;
- `normalizeDraft` rechaza una combinación inválida con «Origen: no corresponde a lo elegido en Material»;
- hora HH:MM, cantidad entera no negativa, peso decimal, obligatorios.

**Backend** (`backend/app/dependent_options.py` + un gancho en `capture_service._prepare_content`):
- las listas completas siguen validándose contra la definición publicada (cerradas y sensibles a mayúsculas: «fibra larga» se rechaza);
- **solo desde P1-04 v2** se rechaza (422) una combinación material–origen o material–presentación inválida; el mensaje nombra los campos y **nunca devuelve el valor recibido**;
- la regla no afecta a P1-04 v1, a ningún otro formulario ni al reintento idempotente (que usa la versión original de la captura).

**Por qué en código y no en `vinto_config.field_option_dependency`.** La tabla existe desde 0001 y el rol de lectura (`vinto_app`) tiene `SELECT`, pero **ni el importador la escribe ni su rol (`vinto_reference`) tiene `INSERT`** (`backend/roles/03_table_grants.sql`). Usarla exigiría cambiar privilegios de la base de producción y ampliar el importador: una modificación transversal que queda fuera de este alcance. Impedimento documentado; no se hicieron migraciones ni cambios de roles. Una prueba comprueba que las reglas del backend, las listas del seed y las de la pantalla coinciden.

## 7. Subtotal visual (P1-04)
- **Fórmula:** Subtotal (kg) = Cantidad de UM × Peso unitario real (kg).
- **Precisión:** aritmética decimal exacta con BigInt (`lib/vinto/exact-decimal.ts`, sin coma flotante), **dos decimales**, redondeo «mitad hacia arriba» (7 × 1.115 = 7.805 → **7.81**; 3 × 0.1 = **0.30**). Vacío («—») si falta un valor o no es válido.
- **Dónde:** en la pantalla de captura («Valores calculados en pantalla (no se guardan)») y como columna «Subtotal (kg)» del historial, calculada de lo guardado (la v1 no la tiene).
- **Garantías:** no es editable; no es un campo del formulario; no viaja en el payload; el backend lo rechazaría como campo desconocido; no se persiste.
- **Contrato del backend:** sin cambios para esta parte.

## 8. Correlativo de P1-16: único por OT + máquina
**Regla (D8).** El correlativo sigue siendo manual y obligatorio. Dos capturas distintas de P1-16 v3 de la **misma OT y la misma máquina** no pueden compartirlo (409 `CORRELATIVE_IN_USE`, sin dejar filas). Entre OT o máquinas distintas se permite repetirlo. No hay numeración automática y **no entran la fecha ni el turno**. La OT y la máquina salen de la **asignación central** (nunca de lo que envía el cliente). Se aplica solo a capturas **nuevas de la v3**: P1-16 v1 y v2 no se evalúan ni se reinterpretan, y un correlativo histórico no bloquea a la v3.

**Inspección previa (lo que existe).**
- OT, máquina y correlativo: la captura guarda `machine_id` y su `assignment_id`; la OT sale de la asignación (`assignment → work_order_line → work_order_version → work_order`); el correlativo es un valor de texto en `capture_detail` (campo `numero_correlativo`). Estados: la captura nace `draft` y pasa a `submitted` en la misma transacción.
- Una OT pertenece a **una sola máquina** (`work_order.machine_id`) y el trigger `validate_assignment` impide una asignación de otra máquina: hoy «la misma OT con otra máquina» **no se puede crear**; el ámbito igualmente incluye la máquina (prueba directa de la función).
- Reintentos: el mismo `capture_id` se resuelve **antes** de llegar al control (idempotencia). No existe ninguna operación que cambie los valores de una captura confirmada (no hay revisiones que editen el correlativo).
- Concurrencia: la conexión es autocommit con transacciones explícitas en READ COMMITTED, y `submit_production_capture` toma, **antes de validar**, un `pg_advisory_xact_lock` de la **máquina** de la asignación (el mismo que usan `activate` y `finish`), que se mantiene hasta el COMMIT.

**Mecanismo implementado (sin migraciones, tablas, índices, triggers ni privilegios nuevos).** `backend/app/capture_uniqueness.py` + una llamada en `capture_service`: con el lock de la máquina ya tomado y en la **misma transacción** que el INSERT, se consulta si existe una captura **confirmada** (`submitted`/`closed`) de P1-16 v3 o posterior con la misma máquina, la misma OT y el mismo texto de correlativo. La comparación es **exacta tras la normalización del motor** (sin espacios en los extremos; «10 A» y «10 a» son distintos; «010» ≠ «10»).

**Por qué es seguro ante la carrera y una consulta previa por sí sola no lo sería.** Dos solicitudes de la misma máquina (y por tanto del mismo ámbito OT + máquina) nunca ejecutan el control a la vez: la segunda espera al COMMIT de la primera y su consulta ya ve la fila. Se comprobó con un experimento descartable: **sin el lock de máquina, 4 solicitudes simultáneas con el mismo correlativo crearon 13 duplicados en 6 rondas**; con el lock, **exactamente un registro por ronda** (prueba incluida).

**Límites que debes conocer.**
1. **No es una restricción declarativa de la base**: la garantía vale para todo camino que cree capturas de producción por `submit_production_capture` (el único que crea P1-16) y toma el lock de máquina. Una inserción directa por SQL, o una ruta futura que no tome ese lock, no quedaría cubierta.
2. Una restricción declarativa (índice único) **no es posible con el esquema actual**: el valor está en `capture_detail` y la OT y la máquina en otras tablas; habría que desnormalizar columnas y/o añadir un trigger y un índice, es decir, **migración y cambios en la base que no están autorizados**. Se deja como propuesta opcional, no implementada.
3. Las solicitudes de una misma máquina se serializan un instante (ya ocurría con todas las capturas de producción).

**Respuesta al usuario.** El rechazo es `409 CORRELATIVE_IN_USE` con el mensaje «El número correlativo ya está registrado para esta OT y máquina» (no devuelve el valor); la pantalla muestra «Ese número correlativo ya está registrado para esta OT y máquina. Escribe otro número.» y desbloquea el formulario.

## 9. Comparación con el MVP anterior
**P1-04.** El componente `Fiber` de `app/page.tsx` antes de INT-02A (commit `7516e09^`) registraba por consumo: hora de consumo, material, origen, presentación, cantidad de UM, peso unitario real y un subtotal calculado (`cantidad × peso`, mostrado con `toFixed(2)`). Sus catálogos coinciden **exactamente** con los de la decisión:

| Material | Origen | Presentación |
|---|---|---|
| Fibra larga | Laja, Susano, Dorado | Caja, Fardo |
| Fibra corta | Laja, Cóndor | Caja, Fardo |
| Recorte | Sauce Rancho, Máquina | Fardo |

- **Sin discrepancias** de textos ni de relaciones respecto de lo aprobado.
- **Diferencias deliberadas:** cantidad de UM era un número libre en el MVP y ahora es **entero**; el subtotal usaba coma flotante y ahora es **exacto**; el MVP guardaba en el navegador (local) y ahora cada consumo es una captura central.
- La observación 17 **no trae imagen** en el Excel: no hay un «mockup» adjunto que contrastar; la fuente verificable es el código del MVP anterior.

**P1-16.** La hipótesis `WasteCapture` del MVP anterior (todavía en `lib/vinto/p1-16.ts`, sin conexión a la aplicación) pesaba **una merma** con tipo, origen y peso. La imagen del Excel (celda J48) muestra el desplegable de **Tipo** con Hoja doble, Hoja simple, Servilleta, Toalla, Cartón y Plástico, **en ese orden**, y «Logs» seleccionado en Origen. Las opciones de **Origen** (Logs, Cola, Máquina) se verificaron en el código del MVP anterior, no en la imagen (que solo muestra «Logs»). La tabla de insumos que aparece debajo en la imagen **no** forma parte de esta observación.

## 10. Versiones y compatibilidad histórica
| Formulario | Antes (producción) | Después | Campos | Opciones | Máquinas |
|---|---|---|---|---|---|
| VINTO-P1-04 | v1 (9 campos) | **v2** | 7 | 11 (3 + 6 + 2) | MP1, MP3 |
| VINTO-P1-16 | v1, v2 (10 campos) | **v3** | 7 | 9 (6 + 3) | las 11 de v2 |

- Versiones anteriores **publicadas e inmutables**; cada captura conserva su `form_version_id`. Los campos retirados quedan en la lista `legacy` del formulario (historial con la marca «versión anterior»); los obligatorios nuevos llevan `sinceVersion` (las capturas anteriores se leen sin exigirlos).
- Una captura nueva que envíe una clave de la versión anterior recibe 422 (campo desconocido), y una captura anterior no acepta claves nuevas.
- `manifest.json`: `form_fields` 469 → **464**, `form_options` 14 → **34**. **Sin migraciones.**

## 11. Pruebas y resultados
| Suite | Resultado |
|---|---|
| Backend nuevo `test_mf12b_fibra_merma` (PostgreSQL efímero, formularios reales; **28 pruebas**, incluida la concurrencia) | **OK** |
| Frontend nuevo `scripts/mf12b-fibra-merma.test.mjs` (9 pruebas) y `p1-04-capture` reescrito (9 pruebas; la única que falla es el «alcance: …» que ya falla en `main`) | **OK** |
| Backend: cada módulo `test_*.py` por separado | cada módulo por separado en `vinto-test-py`: **todos OK** salvo `test_db_guard` (3 fallos) y `test_capture_count_authorization` (1), que **fallan igual en `main`** (verificado en MF-12A con los cambios en espera; sin relación con esta entrega). La primera pasada mostró fallos en `test_mf07`, `test_mf08`, `test_mf09`, `test_mf11` y `test_mf12a` por los cambios intencionales (versiones y conteos del bundle, P1-04 y P1-16); se adaptaron (`test_mf11` reproduce P1-16 v2 con una copia fiel de la definición de producción, `backend/tests/mf12b_p116_v2.json`) y pasan. También se actualizaron los conteos de `test_seed_bundle`, `test_bundle_validation` (huella) y `test_import_reference` (464 campos, 34 opciones, 1946 registros) |
| Frontend suite completa | `node --test scripts/*.test.mjs`: **791 pruebas, 769 OK y 22 fallos con los mismos nombres que `main`** (baseline: 773 pruebas, 751 OK, 22 fallos). Adaptadas: `mf10`, `mf11`, `mf12a` (versiones y conteos) y `p1-04-capture` (reescrita para la v2) |
| `tsc --noEmit` / ESLint | sin errores |

Cubierto: P1-04 (las 7 combinaciones material–origen y las 6 material–presentación válidas aceptadas; todas las inválidas rechazadas por el backend sin dejar filas; listas cerradas y sensibles a mayúsculas; hora, entero y decimal; obligatorios; una captura por consumo; reintento idempotente; el subtotal rechazado como campo; v1 legible y sin las reglas nuevas; autorización sin cambios) y P1-16 (las 18 combinaciones tipo × origen, obligatorios, listas cerradas, peso decimal, horas de MF-11, unicidad del correlativo por OT + máquina (primera aceptada; duplicada rechazada; otra OT con la misma máquina aceptada; correlativos distintos aceptados; misma OT desde otra asignación rechazada; reintento idempotente intacto; **4 solicitudes simultáneas → exactamente una creada**; v1/v2 sin reinterpretar), seis cantidades antiguas rechazadas en v3, v1/v2 legibles y no convertidas, las 11 máquinas, autorización).

## 12. Importación simulada (dry-run esperado)
Sobre una base efímera con el estado de producción previo (todo el bundle vigente con P1-04 v1 y P1-16 v2) el importador informa exactamente:

| Concepto | Crear |
|---|---|
| `form_version` | **2** |
| `field` | **14** (7 + 7) |
| `form_version_machine` | **13** (2 + 11) |
| `field_group` | **0** |
| `option` | **20** (11 + 9) |
| Conflictos | **0** |

Segunda importación idempotente. Total de registros del bundle en una base vacía: **1946** (antes 1931). Sin migraciones.

## 13. Riesgos
| Riesgo | Medida |
|---|---|
| **Cambio de código de backend** (a diferencia de MF-12A): dos ganchos nuevos en la creación de capturas (listas dependientes de P1-04 v2+ y unicidad del correlativo de P1-16 v3+). | Cada gancho solo actúa en su formulario y versión; el resto queda igual (pruebas); `activate` reinicia el backend. |
| Entre importar y activar, el frontend/backend anterior no acepta las versiones nuevas (v2/v3 publicadas, claves nuevas). | Importar y activar de inmediato (patrón MF-05 a MF-12A); P1-04 y P1-16 no crean bobinas ni afectan genealogía. |
| La unicidad del correlativo no es una restricción declarativa de la base (§8). | Garantía transaccional con el lock de máquina existente (probada bajo concurrencia); un índice único exigiría migración y no está autorizado. |
| Combinaciones por API directa en P1-04 v1. | No aplica: la v1 no tiene esos campos. |
| Subtotal no consultable en reportes. | Consecuencia de la decisión de no persistirlo. |

## 14. Exclusiones
Observaciones 5 y 11 (P1-01), tanques, secciones, MF-12A, permisos, otras máquinas y formularios, numeración automática, unicidad declarativa en la base (índice), inventario y genealogía, TVC/ETL, Monday y los Excel.

## 15. Procedimiento de despliegue propuesto (NO ejecutado)
Solo con autorización expresa, como en MF-05 a MF-12A: preflight (versión activa, servicios, borradores, capturas, sin despliegues concurrentes); respaldo `backup.sh create-and-verify` con restauración aislada; artefacto de frontend desde el SHA del merge con checksum y arranque aislado; instalación sin activar; **dry-run** esperando exactamente las cifras del §12 (si difiere, detenerse); importación aditiva como `vinto-mvp`; **activación inmediata** con `deploy/mvp` (reinicia backend y frontend: esta entrega sí cambia código de backend); healthcheck; verificación de las dos versiones publicadas, sus vínculos y opciones, del historial intacto, del rechazo de combinaciones inválidas y de que `vinto-web`/TVC/ETL no se tocaron. Rollback de código con el procedimiento oficial; retirar las versiones nuevas o restaurar datos requiere autorización expresa.

## 16. Guía de QA manual (después del despliegue)
**P1-04 (QA.OPERACION, MP1 y MP3).**
1. Abrir «Registro de consumo de fibra»: campos Hora de consumo *, Material *, Origen *, Presentación *, Cantidad de UM *, Peso unitario real * (kg) y Observaciones; bloque «Valores calculados en pantalla (no se guardan)».
2. Elegir **Fibra larga**: Origen ofrece Laja, Susano, Dorado; Presentación, Caja y Fardo. **Fibra corta**: Laja y Cóndor. **Recorte**: Sauce Rancho y Máquina; Presentación solo Fardo. Cambiar el material vacía el origen o la presentación que ya no corresponda.
3. Escribir cantidad 12 y peso 25,5: el subtotal muestra **306.00 kg**; probar 7 × 1,115 (**7.81**) y borrar un valor (el subtotal vuelve a «—»). El subtotal no se puede editar.
4. Cantidad 1,5 o texto: se rechaza (entero). Hora 24:00 o vacía: se rechaza. Enviar sin cualquier campo obligatorio: se rechaza.
5. Registrar dos consumos seguidos: aparecen **dos** filas en el historial con su subtotal; las capturas anteriores (v1) muestran sus campos como «versión anterior» y sin subtotal.
**P1-16 (QA.OPERACION, p. ej. Gambini, Sincro II/III y las máquinas de servilletas).**
6. Campos: Hora inicio *, Hora fin *, Número correlativo *, Tipo de merma * (6 opciones), Origen de la merma * (Logs, Cola, Máquina), Peso real * (kg) y Observación opcional; ya no aparecen las seis cantidades.
7. Registrar una pesada por cada captura; probar 00:00, 23:59 y fin anterior a inicio (se guarda sin avisos de orden); peso con coma o texto (texto se rechaza).
8. Registrar una pesada con el correlativo 10 en una OT y repetir el 10 en la **misma OT**: se rechaza con «Ese número correlativo ya está registrado para esta OT y máquina»; con 11 se acepta; repetir el 10 en **otra OT** (misma máquina) se acepta.
9. Historial: las capturas v1 y v2 muestran sus seis cantidades como «versión anterior» y las horas solo desde v2; las v3, tipo, origen y peso.
