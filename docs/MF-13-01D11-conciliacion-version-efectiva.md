# MF-13-01D.1.1 — Conciliación de la versión efectiva

Estado: **divergencia de seguridad confirmada y corregida en el motor** (que sigue sin estar conectado a endpoints). No se modificó la captura, la disponibilidad, el catálogo, las versiones ni los vínculos.

## 1. Qué decía cada pieza

| Pieza | Criterio de «versión vigente» |
|-------|-------------------------------|
| `machine_form_grants._require_offered` (concesiones) | Publicada de **mayor número, de cualquier área** |
| `admin/catalog.py` (`offered`, API administrativa) | Publicada de **mayor número, de cualquier área** |
| `authz/engine.py` (antes) y `authz/readiness.py` (antes) | Publicada de mayor número **dentro del área de la operación** |
| `capture_service.published_form_version` | Mayor número **dentro del área** pedida (production por defecto; Calidad pasa `quality`) |
| `production_access.production_machines` | Mayor número dentro del área `production` |
| `quality/form_availability.py` | Mayor número dentro del área `quality` |

El modelo **no impide** versiones de un mismo formulario en áreas distintas: `form_version.area` es por versión y la única unicidad es `(form_id, version_number)`; ningún trigger ni restricción lo evita (una versión nueva se puede publicar en otra área). El bundle real **no** tiene ningún formulario con más de un área (comprobado), así que hoy no hay datos afectados; un import futuro podría crearlos.

## 2. Reproducción (PostgreSQL 17 aislado)

Las versiones mixtas se construyen por la vía legal (borrador → vínculo → publicar; la base rechaza vincular una versión ya publicada, `23514`).

| Escenario | Catálogo / API admin | Servicio de concesiones | Motor (antes) | Captura (área) | Disponibilidad | `authz_readiness` (antes) |
|-----------|----------------------|-------------------------|---------------|----------------|----------------|----------------------------|
| **S1** P1-01: v4 *production* vinculada a MP1 + v5 *quality* publicada sin vínculo; concesión antigua activa | `offered=False` (vigente v5) | rechaza | **ALLOWED** | production disponible | lista P1-01 en MP1 | **ofrecido** |
| **S2** (inverso) P1-05: v2 *production* solo MP3 + v3 *quality* vinculada a MP1 | `offered=True` | concede | denegado | production **no** disponible | no lista | no ofrecido |
| **S3** P1-05 (una sola área): v2 vigente solo MP3 + v1 histórica vinculada a MP1 | `offered=False` | rechaza | denegado | no disponible | no lista | no ofrecido |
| **S4** P1-01 (una sola área): v5 vigente sin vínculo a MP1 | `offered=False` | rechaza | denegado | no disponible | no lista | no ofrecido |

- **S1 es el hallazgo de seguridad**: una concesión que el catálogo considera inerte porque el par dejó de ofrecerse quedaba autorizada por el motor gracias a una versión *histórica de otra área*.
- S2 no abre acceso: el catálogo ofrece un par que no es utilizable por la ruta de Producción (concesión posible pero sin efecto). Es una incoherencia de la interfaz, no un riesgo.
- S3 y S4 (una sola área) ya eran coherentes en todas las piezas.

## 3. Política adoptada (en el motor)

La versión efectiva es la **publicada de mayor número de cualquier área** —la misma definición que el catálogo y el servicio de concesiones—, y el motor exige además que **esa versión sea del área de la operación** y esté vinculada a la máquina. Razón nueva de denegación: `EFFECTIVE_VERSION_OTHER_AREA`.

Consecuencias:

- El motor **nunca es más laxo que el catálogo**: `autorizado ⇒ catálogo ofrece el par`.
- Con una sola área por formulario (todos los datos reales) el comportamiento es idéntico al anterior; la equivalencia se comprueba para P1-01, P1-03, P1-10, P1-19 y P1-31 en **todas** las máquinas del bundle (concesible ⇔ ofrecido ⇔ motor abierto ⇔ captura disponible).
- `authz_readiness.py` usa la misma definición, de modo que no informa como «bloqueado» un par que el motor nunca autorizaría.
- La captura y la disponibilidad **no cambian**: en versiones mixtas siguen resolviendo por área. Al integrarse, el motor será una barrera adicional más estricta, no un cambio de su comportamiento.

## 4. Decisión funcional pendiente (no se tomó)

Qué debe significar «ofrecido» si en el futuro un formulario tiene versiones vigentes en dos áreas:

| Alternativa | Efecto | Coste |
|-------------|--------|-------|
| **A. Catálogo y concesiones por área** (la «vigente» se calcula por área de la ruta) | S1 y S2 se vuelven coherentes en el sentido de la captura | Cambia la API administrativa y la política de concesiones; exige definir a qué área pertenece cada formulario |
| **B. Motor más estricto (adoptada)** | Cierra S1; deja S2 como incoherencia de interfaz | Ninguno con los datos actuales |
| **C. Prohibir áreas mixtas** (validación del importador o restricción en una migración futura) | Elimina la clase de problema | Migración/validación nueva; no se hizo aquí (sin migraciones ni imports) |

Recomendación: mantener B y evaluar C como validación del importador antes de que exista un formulario multiárea. Mientras tanto la regla es conservadora: ante la duda, no se concede.

## 5. Pruebas

`tests/test_authz_version_equivalence.py` (nuevo): demostración de que la base permite áreas mixtas, que el bundle real no las tiene, los escenarios S1–S4 y dos variantes (versión nueva de la misma área que mantiene / que retira la máquina; versión de otra área sobre un formulario de Calidad), y el barrido de equivalencia sobre el bundle real. `tests/test_authz_engine.py` conserva las pruebas de bloqueo, concurrencia y rol equivalente a `vinto_app`; se ajustó la prueba de «versión de otra área» a la razón nueva. Se verificó que los mutantes «sin chequeo de área» (motor) y «readiness por área» fallan.
