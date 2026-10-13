# M2-B · VINTO-P1-10 «Registro de fardos»: contrato técnico previo

Estado: **borrador para decisión**. Preparado en M2-A tras inspeccionar `lib/vinto/form-definitions.ts` (`form_10_registro_de_fardos`). No inventa numeración, firmas, reglas de producto ni validaciones industriales: lo no confirmado queda como pregunta. P1-10 **no** está en el bundle de producción ni en `CENTRAL_FORM_CODES`, y Rebobinado sigue deshabilitado.

## Definición actual
`area: production` · `sector: rebobinado` · `machineLabel: "Todas las rebobinadoras"` · `allowedMachineIds: ["copasa"]` · `workflowId: production-standard` · versión 1 · 8 campos.

| # | key | tipo declarado | origen | obligatorio | unidad |
|---|---|---|---|---|---|
| 1 | `codigo_numero_de_producto` | text | manual | sí | – |
| 2 | `numero_de_fardo` | text | manual | sí | – |
| 3 | `peso_fardo` | text | manual | sí | kg |
| 4 | `fecha` | date | automatic | sí | – |
| 5 | `maquina` | text | automatic | sí | – |
| 6 | `responsable` | text | automatic | sí | – |
| 7 | `firma` | text | automatic | sí | – |
| 8 | `observaciones` | textarea | manual | no | – |

## A. Manuales, automáticos y opcionales
- **Manuales obligatorios:** `codigo_numero_de_producto`, `numero_de_fardo`, `peso_fardo`.
- **Manual opcional:** `observaciones`.
- **Automáticos obligatorios (4):** `fecha`, `maquina`, `responsable`, `firma`.
- Observación: `numero_de_fardo` y `peso_fardo` están declarados como `text` aunque semánticamente son número y peso (la propuesta del propio campo dice «dato de captura con unidad y validación de rango»). Hay que decidir el tipo almacenado (p. ej. `integer`/`text` y `decimal` en kg) **antes** de publicar.

## B. Qué puede heredar del contexto central (sin que lo envíe el cliente)
| Campo | Fuente propuesta | Estado |
|---|---|---|
| `maquina` | máquina de la asignación (`capture.machine_id`) | directo |
| `fecha` | fecha operativa de la asignación (`capture.operating_date`) | confirmar si es fecha operativa o fecha calendario de captura |
| `responsable` | usuario autenticado que captura (`created_by`) | confirmar si «responsable» = operador o el supervisor/jefe del turno |
| `firma` | la propuesta del campo dice «reemplazar firma manual por usuario, fecha/hora y estado de aprobación» | **sin definir**: qué es una firma digital válida y quién aprueba |
| `codigo_numero_de_producto` | candidato: artículo de la línea de la OT/asignación; el campo dice «catálogo / selección» | confirmar si debe ser **igual** al artículo de la línea o puede diferir (varios productos por turno) |

## C. Correlativo central de fardo
`numero_de_fardo` es hoy **manual**. Si se quiere un correlativo central hay que decidir (y hoy nada está confirmado): alcance de la secuencia (por máquina, sector, día/turno, global), formato y prefijo, reinicio (nunca / diario / por OT), huecos permitidos, tratamiento de reintentos (no deben consumir números: el número debe asignarse **dentro** de la transacción idempotente), anulaciones/correcciones y concurrencia (lock por secuencia). El proyecto ya tiene un numerador propio para bobinas (`bobbin_sequence`, P1-03) que sirve de referencia de patrón, **no** de regla. Un numerador nuevo requiere migración (excluida de M2-A).
Alternativa sin numerador: mantener entrada manual con validación de unicidad (también requiere una regla de unicidad confirmada).

## D. «Todas las rebobinadoras» frente a COPASA
La etiqueta dice todas las rebobinadoras; `allowedMachineIds` solo `copasa`. El catálogo candidato de Rebobinado (`candidate-rebobinado`, no aprobado) conoce cinco máquinas: BELOIT, OVER, COPASA, PERICHUN, TUBETERA; P1-07 usa copasa/beloit/over. **Decidir** cuál es la verdad: (a) solo COPASA, (b) las cinco, (c) un subconjunto. La relación formulario-máquina (`form_version_machine`) del bundle debe reflejar la decisión.

## E. Reglas de negocio por confirmar
1. Tipo, rango, decimales y unidad de `peso_fardo`; ¿peso bruto o neto?; tolerancias o alertas.
2. Formato y unicidad de `numero_de_fardo` (ver C).
3. ¿`codigo_numero_de_producto` debe existir en el catálogo de artículos de la máquina (hay relación artículo-máquina) o puede ser libre?
4. ¿Un fardo por captura, o puede haber varios por asignación y turno? (afecta idempotencia: `capture_id` por fardo).
5. Firma/aprobación: ¿quién firma, cuándo, y se puede corregir?
6. Correcciones y anulaciones de un fardo ya enviado (revisión, `capture.revision`).
7. Relación con la genealogía/consumo de bobinas (P1-11) y con el stock de producto terminado: fuera de M2-B salvo decisión.
8. Turnos de Rebobinado: los turnos candidatos son **provisionales** (no confirmados por VINTO); sin ellos no hay fecha operativa.

## F. Cambios necesarios para incorporarlo al motor (M2-B)
1. **Datos aprobados:** definición de P1-10 en el bundle de referencia (hoy `backend/seed_data` solo trae los 4 formularios de Bobinas) por el camino de importación aprobado; sector REBOBINADO, máquinas, turnos con vigencia, relaciones artículo-máquina y `form_version_machine`. El import de los alcances candidatos está bloqueado a propósito para DEV.
2. **Campos automáticos:** `load_fields` rechaza hoy cualquier campo con `source != 'manual'` (`UnsupportedFormDefinitionError`), de modo que P1-10 **no** puede publicarse tal cual. Opciones: (i) el motor trata `source = 'automatic'` como propiedad del servidor (no se aceptan del cliente, se derivan del contexto y se exponen en la vista), o (ii) versión 2 del formulario sin esos cuatro campos, porque ya son contexto de la captura. Recomendación a confirmar: (ii) + exponer el contexto, o (i) con una lista cerrada de fuentes automáticas.
3. **Tipos:** corregir `numero_de_fardo` y `peso_fardo` (ver A).
4. **Política:** añadir `VINTO-P1-10` a `CENTRAL_FORM_CODES` (una línea) cuando el sector esté operativo.
5. **Numerador** si se decide el correlativo central (migración + pruebas de concurrencia/idempotencia).
6. **Sector:** habilitar REBOBINADO en `app/sectors.py` es un cambio de código revisado y aparte; sin él, P1-10 se comporta como inexistente (404) para todos.
7. **Pruebas:** repetir el patrón de M2-A con la definición real (no sintética) en bases efímeras: 201/200/409/422, alcance, máquina no permitida, y lecturas por `form_code`.
8. **Sin cambios** en idempotencia, locks, auditoría, contexto de asignación ni autorización.

## G. Reutilización del frontend F6
- **Reutilizable:** `central-http` (`requestJson`), `captures-api.ts` (`submitCapture`, `getCapture`, `listCaptures`), reconciliación tras timeout/incertidumbre, `createAttempt`/`submitAttempt`/`reconcile`, mensajes y mapeo de errores (`rejectionFor`), `newCaptureId` y `device_key`.
- **A generalizar:** `CapturePayload.form_code` es el literal `"VINTO-P1-06"` y `F6Values`/`F6Draft`/`normalizeDraft` son específicos; hay que parametrizar por definición del formulario (campos, tipos, opciones). `listCaptures` necesita el parámetro opcional `form_code` (ya soportado por el backend). La pantalla `f6-capture.tsx` y la tarjeta de contexto se pueden reutilizar como esqueleto de un formulario manual simple.
- **No reutilizable tal cual:** el flujo del frente Bobinas en `app/page.tsx` (selección de asignación de Bobinas); Rebobinado necesitaría su propio contexto de asignación cuando el sector sea operativo.

## Fuera de alcance de este contrato
Frontend de P1-10, numerador, grupos repetibles, genealogía, consumo de bobinas, recetas y habilitar Rebobinado.
