# FOFF-02B.3 — Preparación cifrada y aislada de producción

**27 de noviembre de 2026** · PR apilado sobre FOFF-02B.2 (#265).

## Alcance construido

- Módulo `lib/vinto/foff-production-preparation-store.ts` con base IndexedDB **`vinto-production-offline-preparations-v1`**, independiente de `vinto-quality-offline-preparations-v1` y del almacén operacional de Calidad.
- `sealLocalDraft` / `openLocalDraft` de la bóveda existente: AES-GCM y AAD de usuario+dispositivo+ID de preparación+snapshot+formulario+versión.
- Contexto de preparación ligado a `assignmentId`, sector, máquina, formulario, versión, `contextDigest` SHA256 y marca de tiempo original.
- Payload cifrado extensible con `workOrderId`, `lineId`, artículo, estado de asignación, fecha operativa, turno, definición y referencias (incluidos grupos).
- Escritura sin sobreescritura mediante `IndexedDB.add()`; lista particionada por autor/dispositivo; lectura exige identidad coincidente.
- Pruebas estáticas de validación y aislamiento. Las pruebas E2E con IndexedDB real, WebCrypto y recarga de navegador siguen pendientes.

## Limitaciones importantes

**Esto es una primitiva de almacenamiento, NO preparación industrial habilitada.** Todavía no existe un flujo completo que expida/valide la autoridad firmada de producción ni un editor offline de Conversión. El estado de enrolamiento es `captureEnabled:false`.

- No se aceptan horas de dispositivo como evidencia suficiente de turno (D01).
- La idempotencia de pallet y las revisiones servidor (D03/D04) se diseñarán en FOFF-03.
- Nunca utilizar los datos IndexedDB como prueba de permiso: el receptor debe verificar sesión del autor, concesiones, versión y contexto en la transacción.
- No hacer fallback a datos ficticios cuando no hay IndexedDB, conexión o autoridad.
- **No se integró el nuevo store a la UI** hasta contar con contratos de preparación verificados; Calidad Offline no se modificó.
- Todos los datos actuales de VINTO son ficticios según el responsable, pero siguen siendo obligatorios backups y gates de despliegue.

## Controles de integración

1. Ejecutar CI de esta rama, revisar TypeScript y pruebas.
2. Completar el contrato de preparación firmada para Conversión (usuario, dispositivo, máquina, OT, asignación, línea, versión, receta/peso/turno); emitir exclusivamente con backend autorizado.
3. Integrar el guardado tras verificación de datos auténticos del servidor, nunca desde un formulario inventado.
4. Probar IndexedDB real: no cruce de perfiles, cierre/reapertura, cifrado, pérdida de navegador, colisión de pestañas, corrupción y revocación.
5. Solo entonces permitir edición offline; el envío sigue apagado hasta el receptor FOFF-03 y sus controles D01–D04.

**Sin migraciones, merge, cambios de VPS ni despliegue.**
