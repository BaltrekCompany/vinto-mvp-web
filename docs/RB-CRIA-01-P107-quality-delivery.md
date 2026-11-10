# VINTO RB-CRIA-01 — Crías de P1-07 para Calidad

**Estado:** PR en borrador, exclusivamente laboratorio. **No autoriza merge, migración, importación ni despliegue.**
**Confirmación funcional:** 10 de noviembre de 2026. **Opción A** elegida por el cliente.

## Alcance funcional aprobado

1. **Origen**: captura central `VINTO-P1-07` (Registro de producción de bobinas rebobinadas) en COPASA/BELOIT/OVER, con asignación activa y autorización de Operación vigente.
2. **Madre**: `etiqueta_numero_de_bobina` es texto **declarado manualmente**. Se guarda junto a cada cría; NO se valida contra F3, NO se crea `bobbin_relation` y NO se implica genealogía física o consumo de inventario.
3. **Crías**: conservar exactamente 21 posiciones `peso_cria_1..11` y `peso_cria_13..22`. **NO** crear la posición 12. Solo `peso_cria_1` es obligatoria; otros pesos pueden omitirse. Cada peso proporcionado debe ser decimal positivo; un campo sin dato no origina cría.
4. **Identidad**: cría individual identificada por UUID y combinación única (captura P1-07, posición), con código **técnico** no industrial `CRIA-<capture_uuid_sin_guiones>-<posición>`. No gastar el correlativo oficial MP1/MP3 ni inventar identificadores oficiales.
5. **Calidad**: `quality_release = pending` al guardar cada cría en la misma transacción. La bandeja muestra origen Rebobinado, etiqueta madre, posición, peso, OT, línea/PV, fecha, máquina y artículo.
6. **Decisión**: reutilizar `POST /api/quality/bobbins/{id}/decision`, los permisos `quality.release`, la idempotencia `decision_id`, la auditoría y los cuatro atributos obligatorios de rechazo (tipo, clasificación, detalle, acción correctiva). Cada cría se decide por separado; otra cría permanece pending.
7. **Retrocompatibilidad**: las capturas P1-07 v1/v2 nunca generan crías retroactivas; la nueva v3 es aditiva. El contrato F3 numerado de MP1/MP3 conserva código, correlativo y JSON existentes.
8. **Fuera de alcance**: formato_2/3, recetas, saldos, merma, balance de masa, movimientos, homologación industrial, Calidad de maquinaria de Rebobinado, actualización retroactiva de P1-07.

## Arquitectura y controles

- **Migración 0026**: columnas nuevas nullable y restricciones solo para crías; unicidad por captura/posición; guarda de origen/contexto y de inmutabilidad; trigger diferido exigiendo `quality_release` a cada cría.
- **Servicio nuevo**: `backend/app/rewinding_children.py`, ejecutado después del envío de P1-07 v3 pero dentro de la misma transacción de captura; cualquier fallo revierte captura, crías y decisiones.
- **Sin herencia del F3**: las crías no utilizan `sequence_number` ni `bobbin_sequence`; conservan `management_start_year` solo como dato derivado de fecha operativa al consultar la bandeja.
- **Calidad**: respuesta F3 conserva estructura exacta; una cría lleva el objeto adicional `rewinding`. No ofrecer formularios F3 de humedad/propiedades físicas a crías sin contrato aprobado.
- **Concurrencia**: idempotencia por `capture_id` y `(capture_id, posición)`, transacción, permiso de captura y revisión del estado de Calidad con bloqueo.

## Puertas de QA

- Validación de bundle y checksums del P1-07 v3.
- Postgres 17 efímero con migraciones 0001–0026 y `--check`.
- Una, tres y hasta 21 crías; ausencia de 12; campos opcionales omitidos; peso 0/negativo/fuera de contrato.
- Mismo capture_id + datos idénticos = mismas crías sin duplicados; reintento diferente = 409.
- Independencia de decisión: liberar 1, rechazar 2, mantener 3 pending; 403 para Operación, 401 sin autenticación y 409 para decisiones incompatibles.
- Regresión F3 MP1/MP3, P1-07 v1/v2, Calidad, captura central, OT y grants.
- TypeScript/ESLint/build, inspección de diff y **CI completamente verde del SHA final**.

## Plan preliminar de producción (NO ejecutar todavía)

**Condiciones antes de proceder**: autorización separada del usuario para cada operación mutable; ventana controlada sin capturas P1-07 concurrentes, copia verificable de PostgreSQL y restore ensayado, release portable y `check-release` compatibles, plan rollback estudiado con migración aditiva ya aplicada.

1. Construir release nuevo sin tocar `current`, con frontend portable de SHA exacto y checksum.
2. Validar estado real del bundle actual P1-07 v2, registros históricos y ausencia de anomalías, sin exponer datos ni secretos.
3. Aplicar exclusivamente migración **0026** mediante `deploy.sh migrate-release <SHA>`, sujeto a autorización específica y respaldos; verificar esquema y D2 gate.
4. Activar el release nuevo con `deploy.sh activate <SHA>` (autorización específica y healthchecks).
5. **Solo después de activar código nuevo**, efectuar dry-run del importador versionado `deploy.sh import-reference` y, con autorización adicional, publicar P1-07 v3 con `deploy.sh import-reference-apply`. No publicar v3 contra el backend viejo: las capturas v3 quedarían sin crías. **No aceptar nuevas capturas P1-07 durante la pequeña ventana código activado + v3 sin importar.** Debe haber una pausa operacional confirmada.
6. Verificar que la versión P1-07 publicada sea v3, que F3 no haya sido modificado, que backend/frontend/db estén saludables y que el Quality inbox recoja una captura de QA controlada con crías.
7. Si falla después de importar v3, **no ejecutar rollback ciego al código anterior**, porque el backend antiguo no genera crías desde v3. Primero bloquear nuevas capturas P1-07 y planificar reversión de versión de formulario (no borrar capturas ni revertir destructivamente base).

**No** se emitieron aún comandos de producción. Actualizar esta secuencia tras CI y revisión formal antes de proceder.
