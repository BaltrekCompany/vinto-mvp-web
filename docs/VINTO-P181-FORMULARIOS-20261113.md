# VINTO P181 — Ajustes definitivos de formularios (13/11/2026)

## Alcance autorizado
- P1-25 V4: corregir seis títulos y retirar notas de prototipo; la semántica y los valores históricos se conservan.
- P1-16 V4: retirar hora inicio / fin, sección de horas y textos explicativos de captura; mantener una pesada por registro.
- P1-07 V5: cambiar **únicamente** el título de `formato_3` a «Cortes»; clave, decimal, obligatoriedad, crías y genealogía igual que en V4. En historial V4 sigue «Formato 3».
- P1-10 V4: retirar horas manuales y añadir **Tipo** (selección única y obligatoria: Papel Higiénico, Toalla, Servilleta). Mantener peso, observaciones y contexto de OT. El historial V1-V3 conserva sus campos.
- P1-05: baja funcional de «Registro de tubetes». No se ofrece en Producción, no es elegible, no permite nuevas concesiones de máquina/formulario ni nuevas capturas, aunque se invoque el POST directamente. **No** se borran las versiones, capturas, definiciones ni concesiones históricas.

## Seguridad y arquitectura
El rechazo P1-05 reside en `mp3_inspection_policy.allowed_for_machine` (compartido por disponibilidad, autorización y concesiones) y `assert_form_machine` (captura de producción, incluso si la compuerta de autorización no está en `enforce`). Se conserva en `CENTRAL_FORM_CODES` para lectura histórica filtrada, sin reabrir el POST nuevo.

## Contrato de catálogo
Versiones publicadas aditivamente: P1-07 V5 y P1-10 V4. La definición histórica publicada no se edita en PostgreSQL. Los nuevos formularios deben importarse por el flujo `import_reference.py` previo a la activación de la nueva versión del frontend, tras respaldo restaurable y dry-run sin conflictos.

## QA y condiciones de salida
- Integridad SHA-256 de definiciones, manifest y sus fuentes.
- V4 de P1-10 sin horas y con opciones cerradas; V2/V3 legibles con horas; V1 con código/número históricos.
- P1-07 histórico conserva `formato_3` y sus 21 posiciones de crías, sin inventar posición 12.
- P1-05: nuevas concesiones y nuevas capturas denegadas con independencia del navegador; lectura histórica conservada.
- Todos los gates existentes CI y PostgreSQL17 deben aprobarse; no modificar las expectativas de una prueba cuando oculten una regresión real.
- No fusionar ni desplegar hasta QA integral PASS y autorización de cambio productivo.
