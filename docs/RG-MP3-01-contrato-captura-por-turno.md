# VINTO · RG-MP3-01 — Homologación de captura por turno (MP3)

**Fuente funcional:** fotografía «OPERACIÓN E INSPECCIÓN MÁQUINA 3», código RG-MP3-01, revisión 1, más ocho respuestas del usuario del 09/11/2026. Este documento es un contrato de desarrollo, NO una autorización de importación productiva.

## Alcance irreversible a proteger

- **MP3:** nuevo contrato `VINTO-MP3-01`; los campos, orden, tipos y unidades se inventarían del formato adjunto.
- **MP1:** `VINTO-P1-01` v4 queda intacto, sin redefinir sus campos ni afectar capturas anteriores.
- El encabezado resaltado en rojo y firma/revisión no se capturan manualmente: usuario autenticado, máquina, fecha operativa, turno, OT/producto y hora de registro son contexto derivado del servidor. La hora del servidor NO representa la hora manual de una medición.
- No se importan, migran ni reinterpretan las capturas históricas de P1-01 en MP1 ni MP3.
- Solo en **MP3**, una captura por combinación **máquina + fecha operativa de turno + turno**, independientemente de que cambien OT, asignación u operador. Suprimir duplicados también en el backend bajo el bloqueo de máquina, conservando idempotencia por capture_id.
- Las 7 lecturas de **Pulper** son obligatorias; todas las otras secciones son opcionales. Un campo vacío no es cero. Se admiten decimales con punto/coma normalizados por frontend; la API debe validar numéricamente.
- Limpieza: texto libre, no un booleano ni una lista cerrada.
- Velocidad máquina: manual, no PLC/SCADA.
- Químicos: casillas numéricas decimales independientes, sin inventar rangos, fórmulas ni fuente automática.
- Vacuómetros, caudales de sello y lecturas múltiples: keys diferentes, misma etiqueta impresa, casillas individuales sin inferir el nombre de cada sensor.
- Firma y «revisado»: excluidos; no se genera firma electrónica ni flujo de aprobación.

## Distribución

Contrato tipado fuente: `lib/vinto/mp3-operation-spec.ts`, con las secciones de la foto y sus campos en orden de lectura.
En el UI, secciones plegables, indicadores de obligatorios (solo Pulper), metadatos automáticos y grupos de casillas duplicadas con etiquetas visuales fieles, pero identificadores accesibles diferenciados.

## Estrategia de aislamiento del formulario

La v4 compartida de `VINTO-P1-01` está publicada para MP1/MP3 en PostgreSQL. Una publicación de v5 solo para MP3 rompería la oferta de MP1, por lo que NO se realizará así.

1. Introducir un código de formulario nuevo `VINTO-MP3-01`, vinculado **exclusivamente a MP3**.
2. Registrar su definición de forma reproducible e idempotente en el pipeline oficial del bundle; garantizar hashes/manifiesto coherentes. La definición nueva debe consumir exactamente el inventario tipado.
3. En el backend, aplicar una regla explícita de elegibilidad de `VINTO-P1-01` solo para MP1 en **GET /api/production/machines** y **POST /api/captures**, además del vínculo de base de datos. No alterar las filas históricas ni su consulta. En MP3, mostrar y aceptar exclusivamente el nuevo formulario para capturas nuevas.
4. Reutilizar `CandidateFormCapture` y `defineCandidateForm`, con secciones derivadas del nuevo contrato y acceso del backend. No usar almacenamiento local para el negocio.
5. Aplicar guard de captura única del nuevo código por máquina/fecha operativa/turno, bajo la misma serialización transaccional de la máquina, conservando respuesta idempotente para el mismo capture_id.
6. Desplegar con controles separados: pruebas PostgreSQL aislado; bundle reproducible; QA MP1/MP3; respaldo y dry-run import; publicación/activación; QA manual productivo.

## Criterios de aceptación

- MP1 conserva exactamente `VINTO-P1-01` v4 en disponibilidad, captura e historial.
- MP3 ofrece el nuevo `VINTO-MP3-01`; no ofrece el contrato anterior para capturas nuevas. Su historial anterior sigue legible.
- Solo MP3 con autorización puede enviar el nuevo código; cualquier otro destino obtiene el código de error oficial sin persistencia.
- Primer envío por turno permitido, incluso con campos opcionales vacíos; ausencia de cualquiera de los siete Pulper rechazada con 422.
- Segundo capture_id para misma fecha operativa/turno/MP3 obtiene conflicto 409 aun en concurrencia y aun si cambia la OT. Reintento idéntico con igual capture_id conserva 200 sin duplicar.
- Turnos distintos y fechas operativas distintas no se bloquean entre sí, incluido el turno NOCHE cruzando medianoche.
- Historial reconoce versiones y sus campos originales; no reetiqueta datos de v4 como si fueran mediciones RG-MP3-01.
- No hay cambios en OT, reprogramación, E2-D2, Calidad de bobina, ni en MP1.

## Orden de implementación

1. Contrato funcional MP3 + pruebas estructurales.
2. Nuevo formulario versionado y exportación reproducible; política de oferta y autorización por máquina.
3. Exclusividad por turno (backend, en transacción y con regresión concurrente).
4. Interfaz de captura, secciones, validación de tipos, estado vacío y consulta histórica.
5. CI completo y QA aislado, luego propuesta de despliegue separado.

**Estado en esta rama:** el contrato y las pruebas son el primer incremento. Hasta completar los pasos 2–5, la nueva ficha NO se ofrecerá ni se desplegará en producción.
