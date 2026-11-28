# FOFF-03 — Conversión Offline: contrato de entrega integral

**Estado:** fase iniciada; trabajo de implementación pendiente. **Base:** squash FOFF-02 PR #270, `64359c4d5414027b8078c7dccec233f78b08e9e3`.  
**Fecha:** 2026-11-27. **Regla de proyecto:** sin micro-PR ni aprobaciones por cada ajuste interno; presentar una entrega funcional unificada y verificar compilación/CI antes de cerrar. Datos actuales de VINTO confirmados ficticios por el responsable.

## Alcance invariable

Cubrir P1-16 (merma), P1-11 (consumo), P1-12/P1-13 (producción y pallets), exclusivamente cuando el backend los publique y conceda para máquina, usuario, OT y línea vigentes. Integrar en pantalla de Conversión existente y selector común FOFF-02; mantener Calidad Offline intacta. Preparación online, captura local cifrada, autoguardado, cierre/reapertura sin conexión, cola, reintento con idempotencia, servidor que valida autorización vigente, conciliación y revisión. **Ninguna habilitación de producción hasta tests y QA móvil completos.**

## Dependencias técnicas ya verificadas

- `backend/app/capture_service.py`: `submit_production_capture` registra transaccionalmente, `_existing_matches` verifica reintentos, `lock_active_assignment` exige turno/fecha vigentes y control de ejecución, `load_fields`/`load_groups` consultan definiciones publicadas.
- `backend/app/p111_recipe_policy.py` y `p113_recipe_policy.py`: las recetas por artículo vienen de `p111_material_codes.json` y deben respetar la línea de la OT. No tomar catálogos globales del navegador ni ignorar la validación del servidor.
- `backend/app/production_pallets.py`: `pallet_nominal_weight` contiene peso nominal versionado; correlativo de pallet **solo se genera en servidor** con lock y unicidad.
- `backend/app/quality/offline_sync_router.py`: patrón de identidad original, ACK y reconciliación, **no endpoint reutilizable directamente**.
- `backend/app/offline_production.py`: ofrece disponibilidad, enrolamiento y firma `preparation_only` bajo flags OFF, todavía **sin autorización de captura ni paquete industrial completo**.
- `lib/vinto/foff-production-preparation-store.ts` y `foff-conversion-preparation-verify.ts`: bases para bóveda y pin, no editor online/offline integrado todavía.

## Trabajos a completar dentro de la única fase FOFF-03

1. Paquete verificable de definición publicada (campos, opciones, grupos), receta autorizada y peso nominal para el artículo de la asignación; hash/firma cubre el conjunto. Obtener pin del dispositivo solo por sesión HTTPS autenticada, no desde sobre no confiable.
2. Extender la bóveda y cola de **Conversión** con vínculo entre captura, asignación, versión, contexto firmado, dispositivo y usuario; no compartir borradores ni colas con Calidad.
3. Contrato CAPTURE específico y firma separada, receptor transaccional y conciliación por `capture_id`; revalidar permisos con `authorize(...,lock=True)` dentro de la transacción y contexto original. No usar `preparation_only` como autorización.
4. D01: conservar hora original; si turno/OT/línea cambió y no se puede comprobar contexto histórico autorizado, persistir revisión en servidor (D03), sin reasignación silenciosa.
5. D04: reintentos idempotentes; proteger pallets y consumos, no impedir entradas legítimamente distintas ni generar números de pallet localmente.
6. UI integrada con estados de pendiente, sincronizado y requiere revisión, más mensajes de reconexión y permisos.
7. Pruebas unitarias, integración PG17, navegadores reales, permisos/revocación, cambio de OT/turno, capturas duplicadas, fallo de ACK, regresión de Calidad Offline, TypeScript, lint, build.
8. PR **único de entrega funcional** contra main, CI verde, revisión, respaldo VPS restaurable, despliegue controlado y ensayo presencial móvil en producción; no avanzar a Rebobinado sin aprobación funcional posterior.

## Puertas críticas

- Ningún endpoint nuevo deberá admitir escrituras sin identidad/autorización efectiva en servidor; nunca falsear el reloj de turno.
- Un 202 requiere revisión y no equivale a registro en Producción. Un 201/ACK debe poder reconciliarse con la BD.
- Mantener los flags OFF hasta aprobar despliegue y disponer de rollback.
- Para D01 (tardías) no crear excepción al control actual de turno sin transacción y evidencia histórica verificable.
- Un CI verde de FOFF-02 **no acredita** FOFF-03.

**Estado del despliegue:** sin migraciones, cambios VPS ni activación de Conversión Offline en esta fase.
