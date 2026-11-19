# VINTO OFF-04.2 — Cola offline inmutable de laboratorio (simulación local)

**Estado:** candidato de ensayo aislado, PR Draft apilado sobre OFF-04.1 (#227, `4748eee8e270ba838cbbea1cd161d4fe1f4902a7`). Seguimiento: #228.
**NO habilita envío, sincronización, aprobación ni capturas industriales.** Sin cambios en PostgreSQL, VPS, flags de producción, permisos de Calidad, paquetes de solo lectura (`capture_eligible=false`, `captures_enabled=false` intactos), migraciones ni SEC-HOST-01.

## 1. Auditoría (Fase A)

| Hallazgo | Consecuencia |
|---|---|
| `queueSealedDraft` (OFF-02) **mueve** el borrador al almacén `outbox` de `vinto-offline-v1` con estado `queued`; `listQueuedForOwner` lo lee. Es exactamente lo que un futuro motor de sincronización consumiría. | Los pendientes sintéticos **no pueden** usar ese almacén ni ese estado. Esa API no se modifica ni se importa. |
| Los borradores de OFF-04.1 viven en `drafts` y llevan revisión monótona (CAS en una sola transacción). | La transición reutiliza esa revisión como «revisión esperada». |
| Paquetes de Calidad: `capture_eligible=false`, `captures_enabled=false`; solo definiciones `SINTÉTICO…` son editables. | No se tocan ni se reinterpretan: el pendiente simulado no es permiso de captura. |
| IndexedDB no permite una transacción entre bases distintas. | Ver §2: la atomicidad se garantiza en la creación del pendiente; el borrador queda inmutable por guarda. |

## 2. Diseño (Fase B)

### Aislamiento estructural frente a un futuro motor de sincronización
- **Base de datos distinta:** `vinto-off04lab-queue-v1`, almacén `lab_pending`. Código que abra la base de la aplicación (`vinto-offline-v1`) ni siquiera ve estos registros.
- **Vocabulario distinto:** estado `queued_local_simulation` (nunca el estado real de cola), marca `lab: true`, `syncState: "NOT_SYNCED"`. `isLabPending` rechaza cualquier otro estado.
- **Sin importaciones cruzadas:** los módulos de la cola no importan `offline-store` ni mencionan el almacén de envío. Una prueba estática verifica además que **ningún** archivo de `lib/`, `app/`, `scripts/` o `backend/app/` fuera del laboratorio hace referencia a la cola simulada.
- **Inmutable por construcción:** la única primitiva de escritura es `add` (sin `put`, `delete`, `clear` ni cursores); la UI no ofrece borrado ni limpieza.

### Transición `draft` → `queued_local_simulation` (`queueLabDraft`)
1. Valida identidad (propietario y navegador), definición **sintética** elegible, concesión firmada y que el paquete pertenece a esta identidad.
2. Si ya existe un pendiente para el borrador: devuelve ese mismo (`created:false`) sin escribir; con otra revisión esperada ⇒ `conflict`.
3. Carga y descifra el borrador (cualquier alteración ⇒ `corrupt`/`locked`), exige **revisión esperada = revisión almacenada**, misma definición (`stale_definition` si cambió) y **todos los obligatorios completos** (`incomplete` conserva el borrador).
4. Congela: `capture_id` determinista (SHA-256 de propietario+navegador+borrador, formato UUIDv4), autor, navegador, máquina, formulario, versión, checksum, contexto, revisión de origen y la copia completa del borrador, **recifrada** (AES-GCM, AAD ligada a `capture_id`, contexto, formulario y versión).
5. `add` en **una única transacción**; resuelve solo tras `oncomplete`. Fallos (cuota, escritura, fallo posterior al `add`, cifrado) abortan sin dejar estado parcial.

### Duplicados y concurrencia
- Clave primaria `capture_id` + índice **único** `(propietario, navegador, borrador)`: doble clic, reintentos y dos pestañas producen **exactamente un** pendiente; los demás reciben el mismo `capture_id` con `created:false`.
- Un `capture_id` o un borrador duplicado a nivel de almacén se rechazan con `ConstraintError`.

### Borrador de origen
Tras el pendiente, `saveQualityDraft` rechaza toda edición (`pending_local`), cerrando en fallo si no puede leer la cola. El registro del borrador **no se modifica ni se borra** (sin limpieza automática); la interfaz lo muestra de solo lectura. Condición residual de carrera: una pestaña que guarde justo antes del `add` puede dejar un borrador con revisión posterior al pendiente; el pendiente congelado sigue siendo la única copia autoritativa y la interfaz lo marca «Pendiente local — NO sincronizado».

### Interfaz de laboratorio
Botón «Marcar como pendiente local (simulación)» (deshabilitado durante la operación; protección adicional a la de la base), lista «Pendientes locales (simulación)» con el texto «Pendiente local — NO sincronizado», sin botones de enviar/sincronizar/aprobar. Se conservan todos los pendientes ante cualquier error; los dañados se listan sin modificarlos.

## 3. Pruebas (Fase C; solo datos sintéticos)

- **Node** (`off-04-queue.test.mjs`, 6): capture id determinista, forma estricta del registro, aislamiento estructural (incluido el barrido de importaciones), inmutabilidad (solo `add`), borrador de solo lectura con fallo cerrado, ausencia de red/innerHTML/cambios de indicadores.
- **Chrome IndexedDB** (`off-04-queue-browser.py`, 11): incompleto vs completo; transición, congelado, cifrado sin texto en claro y envío de la aplicación vacío; inmutabilidad e idempotencia; revisión obsoleta; doble clic (8 llamadas simultáneas) y dos pestañas; `capture_id` y borrador duplicados; alteración de cifrado/estado/revisión/borrador; otra identidad, otra clave y otro navegador; cuota, error de escritura, fallo tras el `add`, error de cifrado; reinicio; cambio de definición; definición no sintética; sin red.
- **Chrome UI** (`off-04-lab-browser-smoke.py`, 11): flujo completo, incluido doble clic real, segunda pestaña, base aislada cifrada, `outbox` vacío, reapertura **sin conexión** tras reiniciar y solo lectura.
- **Mutaciones de control:** quitar el índice único de borrador y la reutilización del pendiente existente ⇒ falla el caso de duplicados; quitar la guarda de edición ⇒ falla el caso de inmutabilidad.
- **Regresiones:** Node y Chrome de OFF-02 a OFF-04.1 y OFF-03C.4; compilación normal sin laboratorio.

## 4. Riesgos residuales

- La cola simulada es **solo local y aislada**: una futura sincronización real requerirá un contrato de captura nuevo y aprobado, una transición distinta y migración explícita; este incremento no la prepara ni la habilita.
- Sin transacción multi-base: el borrador de origen se conserva (no se borra) y se protege por guarda; carrera descrita en §2.
- Sin borrado, exportación, política de retención ni límite de pendientes; sin cuota garantizada (el navegador puede descartar datos del sitio).
- `capture_id` determinista implica **una captura por borrador**; no hay reapertura ni anulación.
- Un mismo `locked` para clave errónea y cifrado alterado (heredado de la bóveda); reversión local total de blobs antiguos no se detecta.
- Fecha local informativa; QA físico del móvil no ejecutado; datos sintéticos garantizados por convención de proceso, no criptográficamente.
- La compilación de laboratorio no debe usarse en entornos operativos (control en la CI: `test ! -e public/offline-lab.html`).

## 5. Siguiente incremento sugerido (OFF-04.3)
Revisión de seguridad y recuperación de la cola simulada (política de retención, exportación cifrada de evidencia y prueba de rollback local con anclaje externo) **antes** de diseñar cualquier envío; el contrato de captura offline aprobado (#226: OFF-04.5) y la homologación de al menos un formulario real siguen siendo prerrequisitos.
