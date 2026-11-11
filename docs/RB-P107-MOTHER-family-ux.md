# VINTO RB-P107-MOTHER — Madre como ficha principal y crías con decisión independiente

**Ámbito limitado:** P1-07 (Registro de producción de bobinas rebobinadas), no P1-12, no F3 MP1/MP3.
**Estado:** corrección de aplicación en rama, QA aislado; **sin autorización para despliegue a producción**.

## Confirmación funcional 11/11/2026
- Cada captura P1-07 define UNA ficha madre con `etiqueta_numero_de_bobina` como etiqueta declarada y un identificador técnico estable (`capture_id`).
- Las crías son parte de esa ficha: 21 posiciones existentes (1–11, 13–22), con solo la primera obligatoria; no duplicar madres por cada cría.
- Cada cría conserva UUID, posición, peso y `quality_release` independientes. Mostrar estado por cría. Liberar/rechazar no debe aparecer en la cabecera de la madre.
- Rechazar una cría abre pop-up con tipo, clasificación, detalle y acción correctiva, más revisión previa y confirmación final; la operación sigue sobre el **UUID de esa cría**, nunca sobre etiqueta o UUID de captura madre.
- Con crías aún pendientes, la misma ficha muestra también crías liberadas/rechazadas para que el operador vea el conjunto de decisiones. Al decidir la última, la ficha desaparece de **pendientes** pero persiste en base de datos e historiales existentes.
- Conservar exactamente los controles de Calidad ligados a bobinas F3 existentes, sin promoverlos a crías P1-07 por analogía.

## Decisión de modelo (protección de F3)
El esquema `0026_rewinding_child_quality.sql` y servicio `rewinding_children.py` identifican la madre mediante etiqueta **declarada** por el operador; no existe FK desde P1-07 a bobinas F3. Por ello no es seguro vincular formularios físicos F3 a una etiqueta o reutilizar su panel como si identificara la misma bobina física. La sección **Controles e historial** de la ficha madre explica el alcance y mantiene los controles F3 en sus fichas reales. Conexión física con F3 requiere contrato funcional adicional (fuera de este correctivo).

## Diseño técnico
- Sin migraciones ni escrituras nuevas; se reutiliza `source_capture_id`, `rewind_child_position`, `rewind_mother_label` y `quality_release`.
- `GET /api/quality/bobbins` conserva su respuesta/filtro histórico cuando no se envía `include_rewinding_family`.
- Con `include_rewinding_family=true` y estado por defecto `pending`, la consulta incluye crías hermanas decididas solo de capturas que aún tengan alguna cría pending. Nunca agrega bobinas F3 decididas ni grupos totalmente completados.
- La agrupación cliente usa **`production.capture_id`**, no el texto madre (puede repetirse entre capturas). Comprueba invariantes: misma etiqueta, OT, línea y máquina; rechaza posiciones duplicadas y nunca muestra un grupo parcial si hay incoherencias.
- La autorización de lectura mantiene `quality.capture` y alcance por sector; las decisiones mantienen `quality.release`, idempotencia `decision_id`, bloqueo SQL y auditoría.
- Para una cría ya decidida, la vista bloquea visualmente Liberar/Rechazar. El servidor sigue siendo la autoridad de la transición y devuelve 409 en caso de conflicto.
- El diálogo de rechazo específico de cría es modal; F3 conserva su flujo de decisión y formularios físicos sin cambios.

## QA exigido
1. PostgreSQL 17 efímero: P1-07 v4, 21 posiciones, idempotencia y permisos.
2. Liberar una cría, rechazar otra, mantener tercera pendiente: legado pending devuelve solo tercera; opt-in devuelve las tres con sus estados, sin alterar F3.
3. Resolver última cría: grupo deja de aparecer en pendientes; historial base persiste.
4. Frontend: agrupación por captura y no por etiqueta; F3 separado; pop-up/4 campos/revisión; TypeScript, ESLint, build, regresión histórica.
5. CI SHA final todo PASS; revisión formal y autorización explícita antes de merge y cualquier despliegue.
