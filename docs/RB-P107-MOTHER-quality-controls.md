# RB-P107-MQ — Calidad propia de la madre P1-07

**Contrato aprobado:** 11/11/2026. **Estado:** implementación en PR #176 DRAFT; sin merge ni despliegue.

## Contrato funcional
- Cada captura P1-07 v3+ genera UNA identidad de madre basada en el UUID de captura, aunque la etiqueta se repita. No es bobina F3 numerada.
- Sus controles: P1-19 Humedad; P1-20 Propiedades físicas; P1-21 Perfil gramaje y humedad (candidato); P1-24 Propiedades físicas en húmedo (candidato); P1-25 Resistencia en húmedo-curado (candidato); P1-28 Ficha documental (candidato), con `Ver controles` e historial.
- Las decisiones liberar/rechazar y sus estados se conservan por cría, nunca en la madre. Capturar un control NO modifica `quality_release`.
- El panel de F3 MP1/MP3 y sus formularios publicables originales quedan iguales.
- Consulta opcional de madres con todas las crías ya decididas mediante "Ver madres finalizadas".

## Modelo y migraciones
- `0029_p107_rewinding_mother_identity.sql`: `bobbin.rewind_mother_capture_id` único y FK al origen P1-07, código técnico `MADRE-{uuid}`, guardia de captura/máquina/artículo y backfill únicamente de madres con crías existentes. Nuevas capturas crean madre en la misma transacción que las crías. Sin correlativo ni `quality_release`.
- `0030_p107_mother_quality_forms.sql`: **NO ALTERA `form_version_machine`**. La definición de formulario publicada es inmutable (`guard_form_child` de 0001). Reemplaza únicamente las guardias de `capture` y `capture.bobbin_id` para aceptar la captura de Calidad sobre una madre P1-07. La excepción está acotada a COPASA/BELOIT/OVER y a los seis códigos aprobados. F3 y crías siguen sus reglas previas. El bundle de referencia y sus checksums no se modifican; un dry-run posterior no debe presentar drift.
- `app/quality/mother_policy.py`: política whitelist (3 máquinas y 6 formularios); otros formularios o máquinas nunca se admiten por excepción. Se selecciona la versión más reciente PUBLICADA de área Calidad para la madre; F3 sigue exigiendo versión vinculada a la máquina.

## Seguridad y autorización
- Para la NUEVA ruta madre se exige MF-13 `enforce` en todos los POST aun si F3 usa flag `off` u `observe`: permiso `quality.capture`, sector REBOBINADO, máquina/formulario activos, versión publicada vigente, concesión activa `user_machine_form_grant`. Reintentos también se reautorizan y una revocación los bloquea. La concesión se puede dar/revocar desde el servicio existente de administración, gracias a la política acotada de oferta madre.
- El módulo de disponibilidad marca formularios madre como elegibles únicamente si el motor MF13 los permite. Sin grant se presenta mensaje, no botones de escritura. El backend no convierte una elegibilidad visual en autorización.
- GET conserva la política histórica de permiso `quality.capture` y alcance por sector. Capturas e historial pertenecen exclusivamente al UUID de madre, no al texto ni al UUID de cría.

## Identidad en las pantallas
- La bandeja de crías incluye el `mother_bobbin_id` derivado del JOIN a la madre única de la misma captura P1-07.
- La interfaz transforma únicamente los callbacks de formularios e historial al contexto sintético de esa madre: `bobbin.id = mother_bobbin_id`, `bobbin.code = mother_label` (visual), nunca `child.id`.
- El backend devuelve la misma etiqueta humana al listar capturas de la madre (CASE de origen), pero conserva en SQL el código técnico estable `MADRE-{uuid}`.
- P1-28 no debe etiquetar un estado oficial de liberación en la madre, porque ese estado no existe. Los formularios candidatos siguen sin homologarse.

## QA / puertas de control
- PG17 real aislado: madre nueva + backfill antiguo, seis formularios, 401/403/404/409, calidad sin grants, grants individuales, revocación posterior, reintento idéntico, valores calculados, historial por UUID, madres completamente decididas, F3/Crías sin cambios, no drift del catálogo.
- Frontend: parser estricto de mother UUID y de crías, acciones a identidad madre (no cría), controles sólo elegibles, estado de madre "no aplica", historial por UUID, cierre de sesión, TypeScript/ESLint/build.
- Revisión SHA final y todos los CI PASS antes de poner PR listo; merge requiere autorización explícita, y cualquier despliegue requiere preflight, backup/restauración verificado y activación controlada.
