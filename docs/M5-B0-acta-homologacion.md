# M5-B0 · Formato de acta y registro de aprobaciones

Plantilla para registrar las respuestas de VINTO a las decisiones de [M5-B0-decisiones-VINTO.md](M5-B0-decisiones-VINTO.md). **Todas las decisiones están hoy en «Pendiente».** Este archivo es una plantilla: no contiene respuestas ni aprobaciones.

## 1. Estados
| Estado | Significado | Qué se necesita para entrar |
|---|---|---|
| **Pendiente** | Sin respuesta | Estado inicial |
| **Respondido, sin evidencia** | VINTO contestó (p. ej. en reunión) pero no hay documento identificable | Registro de la respuesta, fecha y quién respondió |
| **En revisión** | Hay respuesta y evidencia; Baltrek/VINTO verifican que es completa y consistente (con el resto de decisiones y con el contrato técnico) | Referencia a la evidencia (§2) |
| **Aprobado** | VINTO aprueba formalmente la respuesta y la evidencia la identifica | Aprobador con autoridad + evidencia identificable (§2) + sin conflictos abiertos |
| **Rechazado / requiere rediseño** | La respuesta contradice otra decisión o requiere cambiar el diseño/alcance | Motivo, decisiones afectadas y acción de rediseño |

Transiciones permitidas: Pendiente → Respondido, sin evidencia → En revisión → Aprobado; cualquier estado → Rechazado / requiere rediseño; Rechazado → Pendiente (nueva pregunta). **Aprobado** no se retrocede sin una nueva entrada del acta que lo explique (nada se borra: se añaden filas).

## 2. Evidencia aceptable (identificable)
Cada aprobación cita **al menos una**: (a) acta firmada o aprobada por escrito (número y fecha); (b) correo con remitente, fecha y asunto; (c) archivo oficial de VINTO (nombre, versión, fecha, **SHA-256** si se incorpora al repositorio); (d) confirmación formal de la persona con autoridad (nombre, cargo, medio, fecha).
**No son evidencia:** un fixture, una prueba técnica que pasa, una definición legacy, una conversación sin registro ni la existencia de datos en el catálogo candidato. La matriz **M1-B2-c1**, si se aporta, entra como evidencia (c) y se cita por decisión; hoy es **evidencia pendiente**.

## 3. Cabecera de la sesión
| Campo | Valor |
|---|---|
| Sesión (1 H1 / 2 H2-H3 / cierre) | |
| Fecha y hora | |
| Participantes (nombre, cargo, rol en VINTO/Baltrek) | |
| Quién tiene autoridad para aprobar | |
| Facilitador / quien levanta el acta | |
| Material enviado previamente (versión del paquete) | M5-B0 (commit …) |

## 4. Registro por decisión
Una fila por cambio de estado (el historial se conserva).

| ID | Fecha | Estado | Respuesta de VINTO (literal o resumen fiel) | Alternativa elegida | Evidencia (tipo, referencia, SHA-256 si aplica) | Respondió | Aprobó (nombre, cargo) | Decisiones afectadas | Pendientes / acciones |
|---|---|---|---|---|---|---|---|---|---|
| H1-01 | | Pendiente | | | | | | | |
| *(…una fila inicial «Pendiente» por cada ID de las 47 decisiones…)* | | | | | | | | | |

## 5. Resumen de avance (se actualiza después de cada sesión)
| Fase | Decisiones mínimas requeridas | Aprobadas con evidencia | Estado |
|---|---|---|---|
| M4-B2 (promoción de maestros y contratos) | Ver §5 del paquete de decisiones | 0 | **NO GO** |
| M5-B (genealogía P1-07) | Ver §5 del paquete de decisiones | 0 | **NO GO** |
| M4-B3 (activación controlada en DEV) | M4-B2 + condiciones de §7 del paquete | 0 | **NO GO** |

## 6. Reglas de uso
- Una fase pasa a **GO** solo cuando **todas** sus decisiones requeridas están en **Aprobado** con evidencia y el checklist técnico (respaldo, dry-run, bundle promovido, `--check`) está completo.
- Si una decisión aprobada cambia otra, la afectada vuelve a **En revisión** con una fila nueva.
- Este acta **no autoriza** por sí sola activar Rebobinado, importar a DEV ni publicar P1-07: esos pasos requieren sus PR revisados y la aprobación explícita de VINTO.
