# VINTO OFF-04.2-R2 — Consistencia y recuperación del laboratorio sintético

**Estado:** candidato de ensayo aislado, apilado sobre OFF-04.2 (#229, `db101f812affc6ef54a33accb4320854f8736834`). Seguimiento: #230.
**Solo laboratorio sintético.** No hay sincronización, envío, eliminación (automática ni manual), exportación operativa, anclaje externo ni capturas industriales. Sin cambios en PostgreSQL, VPS, permisos de Calidad, paquetes de solo lectura ni SEC-HOST-01.

## 1. Hallazgos corregidos (OFF-04.3-PRE)

| # | Hallazgo | Reproducción previa (código de #229) | Resultado |
|---|---|---|---|
| H1 | Carrera guardar/convertir entre dos bases: revisiones divergentes sin salida | R1: el guardado de la revisión 2 confirma mientras se sella la 1 ⇒ pendiente de la 1 y borrador en la 2. R2: el pendiente confirma durante un guardado ⇒ borrador en revisión 2 tras el pendiente. | **Corregido**: R1 ⇒ `conflict` sin pendiente; R2 ⇒ `pending_local`; el borrador sigue editable (R1) o congelado e íntegro (R2) |
| H2 | Pendiente malformado bloquea el borrador sin explicación (`storage`) y, si se rompía la asociación, lo desbloqueaba en silencio | S1: error `storage`; con `draft_id` alterado el borrador quedaba editable | **Corregido**: `quarantined`, evidencia visible y el borrador permanece bloqueado |
| H3 | Pérdida de solo la base de la cola reabría el borrador y regeneraba el mismo `capture_id` con otro contenido | S2 | **Corregido**: `lab_lost`, nada se recrea ni se reactiva |
| H4 | La interfaz mostraba el contenido del borrador como si fuera el del pendiente | revisión de código (el borrador podía ser posterior al pendiente) | **Corregido**: se muestra siempre el contenido congelado del pendiente |

Los cuatro casos se escribieron **antes** de modificar código y fallaron contra #229 (evidencia: `phaseA-negative.log`, fuera del repositorio); ahora son `R1`, `R2`, `S1`, `S2` de `off-04-consistency-browser.py`.

## 2. Diseño definitivo (opción C)

**Una sola base de laboratorio** `vinto-off04lab-v2` con almacenes `lab_drafts`, `lab_pending`, `lab_quarantine` y `lab_meta`. Aislada de la base operativa `vinto-offline-v1` y de su cola real: otro nombre, otros almacenes, otro vocabulario de estado (`queued_local_simulation`), sin importar `offline-store` (salvo el módulo de migración, que solo **lee**). Una prueba estática barre `lib/`, `app/`, `scripts/` y `backend/app/` y falla si código operativo la referencia; incluye un control negativo.

- **Atomicidad:** guardar y convertir son **una transacción** sobre `lab_drafts` + `lab_pending` (revisión y texto cifrado comparados dentro de la transacción). Resuelven solo tras `oncomplete`.
- **Congelado doble:** al crear el pendiente, **en la misma transacción**, el borrador recibe un marcador `frozenBy`. Alterar el pendiente *o* el marcador no desbloquea: cualquier discrepancia ⇒ `quarantined`.
- **Identificadores:** `capture_id` determinista + índice único por borrador (sin reutilización accidental); repetir la conversión es idempotente.
- **Inmutabilidad:** sobre `lab_pending` solo existe `add`; no hay primitiva de borrado en todo el módulo.
- **Pérdida o reemplazo de la base:** una época fuera de la base (`localStorage`) se compara con el identificador interno. Base ausente con época presente ⇒ **se aborta su creación** (`lab_lost`); época distinta ⇒ `lab_mismatch`. Borrar solo la época no es pérdida (la base íntegra la restituye).
- **Cuarentena visible:** pendientes malformados, borradores congelados sin pendiente íntegro y evidencia de migración. Nunca se eliminan ni desbloquean.

## 3. Migración no destructiva de datos anteriores

Datos anteriores: borradores en el almacén `drafts` de la base operativa y pendientes en la base de cola de #229. **Fases:** PREPARAR (solo lectura; descifra y verifica cada fila) → VERIFICAR (consistencia del plan) → CONFIRMAR (una transacción *solo-añadir*, con marcador) → VERIFICAR-CONFIRMADO (relee ambos lados). Los blobs cifrados se copian **idénticos** (su AAD no depende de la base). Los datos anteriores no se escriben, modifican ni borran (se compara una huella antes y después). Un fallo en cualquier punto deja el laboratorio intacto y la migración se repite. Filas ilegibles ⇒ cuarentena; si **nada** descifra y la clave no está probada, se aborta (`locked`): no se confunde un error de frase con daño. La interfaz prueba la clave (alcance firmado descifrado) y migra al desbloquear. Una vez migrado, un borrador anterior que aparezca después **no** se importa en silencio. Estados divergentes heredados (borrador posterior al pendiente) se migran **congelados** y quedan marcados.

## 4. Pruebas (solo datos sintéticos)

- **Node** (`off-04-queue.test.mjs`, 9): formas estrictas, aislamiento y barrido de importaciones con control negativo, inmutabilidad y atomicidad estáticas, pérdida/reemplazo fail-closed, migración solo-lectura sobre datos anteriores, interfaz con contenido congelado.
- **Chrome IndexedDB:** `off-04-consistency-browser.py` (8: R1, R2, S1, S2 y M1–M4: migración verificada e idempotente, fallo/cuota/fallo tras el `add`/clave errónea/daño aislado, pérdida tras migrar, dos pestañas, otro navegador), `off-04-queue-browser.py` (11) y `off-04-drafts-browser.py` (11), todos sobre la base consolidada; ausencia de red y de escrituras al `outbox` real.
- **Chrome UI** (`off-04-lab-browser-smoke.py`, 12): incluye contenido congelado, reinicio sin conexión, base borrada ⇒ bloqueo y sin recreación.
- **Mutaciones de control (detectadas):** quitar la comparación de revisión/cifrado ⇒ falla R1; ignorar el congelado en guardados ⇒ R1, R2, S1 y M1; no congelar al convertir ⇒ R1, R2 y S1; permitir recrear la base ⇒ falla M3 (y el caso de interfaz); migrar sin congelar ⇒ M1.
- **Regresiones** OFF-02 a OFF-04.2 y OFF-03C.4, `tsc`, ESLint y compilación normal sin laboratorio.

## 5. Riesgos residuales y límites

- Recuperación tras `lab_lost`/`lab_mismatch`: **no automática** (se bloquea); requiere una decisión explícita fuera de este incremento.
- La época en `localStorage` detecta la pérdida de **solo** la base; la limpieza del sitio completo (ambas) o una restauración coherente de todo el origen siguen sin detectarse sin anclaje externo.
- Los registros malformados **no atribuibles** (sin identidad válida) se muestran a cualquier usuario del navegador; no hay depuración ni eliminación.
- Sin retención, borrado, exportación ni límite de pendientes; sin cuota garantizada.
- `capture_id` determinista ⇒ una captura por borrador.
- Con clave no probada, un único dato anterior dañado se trata como clave errónea (la interfaz sí prueba la clave).
- Un mismo `locked` para clave errónea y cifrado alterado (heredado de la bóveda); fecha local informativa; QA físico del móvil no ejecutado.
- La base anterior de cola y los borradores anteriores se **conservan** (no se borran): ocupan espacio y quedan inertes tras migrar.

## 6. Siguiente sublote sugerido (OFF-04.3)
Política explícita de retención y eliminación con lápidas, exportación cifrada de evidencia de laboratorio (sin importación) y diseño del anclaje externo; requieren decisiones previas sobre OFF-04.4/04.5 (contrato de captura offline y homologación de un formulario real).
