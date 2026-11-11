# VINTO P1-07 — Controles de Calidad propios de madre (contrato funcional confirmado 11/11/2026)

**Estado:** en desarrollo, rama aislada. No fusionar ni desplegar mientras falten las rutas de Calidad, disponibilidad, UI y QA integral.

## Contrato aprobado
- UNA madre por captura P1-07 (versión 3+), identificada por el UUID de la captura, **no por la etiqueta** declarada y sin FK a una bobina F3 de MP1/MP3.
- Mostrar a la derecha de la madre los controles de la referencia: P1-19 (humedad), P1-20 (propiedades físicas), P1-21 (perfil de gramaje y humedad), P1-24 (propiedades físicas en húmedo), P1-25 (resistencia en húmedo-curado), P1-28 (ficha documental) y **Ver controles**.
- Cada registro de Calidad pertenece a esa madre; persistir con autor, fechas, versión, valores y trazabilidad de captura. Permitir múltiples ensayos e historial; no asumir cardinalidad uno-a-uno.
- Estos controles NUNCA cambian automáticamente el estado de la madre ni el de sus crías. La madre no tendrá acciones liberar/rechazar. Las crías mantienen sus decisiones, UUID, posiciones y auditoría existentes.
- F3 MP1/MP3 y sus versiones publicadas, elegibilidad, números correlativos, endpoints e historiales permanecen sin alterarse.
- Para crías pendientes o ya decididas, la ficha madre debe poder consultarse sin depender de asignaciones activas; no esconder sus controles al cerrar la última cría.

## Auditoría de restricciones existentes
1. `vinto_txn.capture.bobbin_id` y `guard_capture_bobbin` (migración 0005) aceptan **únicamente F3 numeradas** y exigen coincidencia de contexto.
2. `quality.capture_service._bobbin_context` exige `sequence_number`; `cs.published_form_version` exige versión publicada vinculada a la máquina.
3. P1-19/20/21/24/25/28 están publicados y vinculados únicamente a MP1/MP3, no a COPASA/BELOIT/OVER.
4. Disponibilidad y autorizaciones del MF-13 consideran permiso `quality.capture`, sector, formulario publicado y concesión por usuario/máquina/formulario.
5. Las variantes candidatas P1-21/24/25/28 se conservan como `candidato`, sin homologar sus campos industriales.

## Diseño de implementación
**Fase A — Identidad (commit de fundación):** migración 0029 con `bobbin.rewind_mother_capture_id` único, código técnico `MADRE-{uuid}`, guardia de origen P1-07, retroactividad únicamente de capturas v3+ que ya generaron crías; nuevas capturas crean la madre técnica en la misma transacción que sus crías. Sin `quality_release` ni secuencia oficial.

**Fase B — Capturas Calidad (pendiente):** extender de forma ADITIVA el contrato de captura exclusivamente para madre P1-07. No quitar guardas F3 ni publicar formularios genéricamente en otras máquinas. Declarar elegibilidad real por cada máquina de Rebobinado y formulario, incluyendo concesiones compatibles con política MF-13; la interfaz sólo ofrece formularios efectivamente autorizados. Mantener bloqueo, idempotencia, valores calculados y tipados, historial y auditoría.

**Fase C — UI/QA (pendiente):** en la ficha única de madre, renderizar los 6 formularios de la referencia y `Ver controles` utilizando el identificador técnico de la madre; el texto de etiqueta continúa visible pero jamás es llave de unión. QA PG17 efímero: backfill, no mezcla entre etiquetas homónimas, permisos 401/403, candidato disabled, 6 formularios, idempotencia, historial, anulación/denegación al revocar, crías independientes, F3 original.

## Gates de despliegue
Código completo + migraciones + catálogo/elegibilidad + frontend + ensayos PG17 + CI SHA final, revisión formal, merge explícito, respaldo y ensayo de restauración, migración 0029 controlada, activación aislada y QA productivo sobre OT autorizada.
**No inferir PASS de fase A como aprobación de todo el correctivo.**
