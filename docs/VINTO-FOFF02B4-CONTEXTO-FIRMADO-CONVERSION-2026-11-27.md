# FOFF-02B.4 — Contexto firmado de preparación de Conversión

**Fecha:** 2026-11-27  
**Estado:** Implementación candidata en PR apilado; NO desplegada ni habilitada.

## Contrato implementado

- `POST /api/offline/production/conversion/prepare` recibe `device_key`, `assignment_id`, `form_code`; exige sesión con `production.capture`.
- Solo P1-11, P1-12, P1-13, P1-16. Rechaza dispositivo inactivo, falta de concesión efectiva, asignación no activa/vencida y línea no iniciada cuando E1 está habilitado. La máquina, OT, línea, turno, fecha operativa, artículo y versión vienen exclusivamente de la base de datos.
- `offline_conversion_preparation_enabled=false` por defecto, con semilla separada `offline_conversion_preparation_signing_seed_hex`.
- Firma Ed25519 con dominio `VINTO-FOFF-CONVERSION-PREPARATION-V1`, esquema `vinto.foff.conversion_preparation.v1`, audiencia `vinto-foff-conversion-preparation`, identidad del usuario y dispositivo, snapshot, contexto y caducidad de 12 horas.
- La respuesta siempre incluye `captureEnabled:false`. **No es autoridad de CAPTURE**; por diseño una firma de preparación no debe ser aceptada por el receptor de Calidad ni por el futuro receptor de Conversión.
- Hash del contexto calculado desde atributos confirmados de servidor; evita atribuir silenciosamente una preparación a otra asignación. Hora de emisión UTC; el turno/fecha vienen del servidor (la planta opera en `America/La_Paz`).
- No hay migración ni escritura industrial; la consulta de contexto opera en transacción `READ ONLY`.

## Límites explícitos: aún no es FOFF-03

- La firma no incluye todavía paquete completo de receta, pesos nominales ni definiciones de campos versionadas. Deben agregarse mediante consultas verificadas a sus respectivas fuentes, con hashes de contenido y ensayos negativos, antes de permitir edición real offline.
- Tampoco hay verificador navegador/pin de esta nueva firma, conexión con IndexedDB de FOFF-02B.3 ni interfaz offline de producción.
- D01 (capturas tardías), D03 (persistencia de revisiones) y D04 (duplicidad semántica/pallet) requieren receptor/almacenamiento transaccional propio y pruebas antes de desplegar FOFF-03.
- El enrolamiento de Operación sigue condicionado por su flag independiente. **No habilitar ninguno de los flags nuevos.**
- Durante la revisión, validar el comportamiento real de `list_operational_lines`, permisos, superposición de turnos, E1, versión y línea en una base de datos efímera; las pruebas criptográficas de esta entrega no sustituyen E2E.

## Dependencias y verificaciones

PR #263 → #264 → #265 → #266 → FOFF-02B.4.

La consulta de GitHub Actions del SHA `63bdf46e` de #266 no mostraba ejecuciones todavía. Antes de integrar, consultar CI del HEAD más reciente y reparar cualquier fallo. Conservar pruebas de regresión de Calidad Offline, ingreso/salida de sesión y Tubetes.

**No se ejecutó merge, migración, VPS ni despliegue.**
