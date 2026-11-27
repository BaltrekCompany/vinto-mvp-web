# FOFF-02B.5 — Verificador navegador de la preparación firmada de Conversión

**Fecha:** 2026-11-27 · **Estado:** implementación candidata; CI pendiente.

## Entrega

- `lib/vinto/foff-conversion-preparation-verify.ts` valida estrictamente el sobre Ed25519 emitido por FOFF-02B.4 (PR #267), usando clave **previamente anclada por enrolamiento autenticado HTTPS**, nunca la clave incrustada como autoridad de confianza.
- Valida esquema y audiencia `vinto.foff.conversion_preparation.v1`, `preparation_only`, destinatario y dispositivo originales, snapshot, OT/línea/máquina, asignación, formulario, versión, turno, fecha operativa, duración de 12 h y firma.
- Recalcula el SHA-256 del contexto canónico, comparándolo con el digest firmado.
- Las pruebas construyen firmas reales de prueba Ed25519 con Node y cubren firma auténtica, clave no anclada, asignación ajena, alteración, caducidad y rechazo de un esquema de Calidad.
- La salida obliga a `captureEnabled: false`.

## Riesgos y faltantes antes de permitir formularios offline

1. El enrolamiento de Operación (#265) **no devuelve ni ancla aún una clave pública de firma de preparación**. El verificador requiere un pin de confianza obtenido y conservado durante una sesión autenticada, mediante protocolo diseñado y auditado; no aceptar TOFU desde el sobre.
2. El endpoint firmado de #267 **todavía NO incluye todas las definiciones de campos, grupos repetibles, recetas y pesos nominales**. No interpolar catálogos históricos del frontend. Validar fuentes de verdad y reunir un paquete por asignación y formulario, firmado o con hash cubierto por la firma.
3. `lib/vinto/foff-production-preparation-store.ts` (#266) es una primitiva de almacenamiento; no hay integración en el selector ni flujo de edición.
4. FOFF-03 continúa bloqueada por falta de receptor que revalide concesiones y OT, capture time D01, revisiones servidor D03 e idempotencia semántica D04.
5. El backend original de #267 valida la línea iniciada por Supervisión solo cuando su flag de ejecución por línea está activo. Antes de autorizar preparación real, se debe verificar que producción opera con esa compuerta habilitada y que el paquete describe explícitamente el estado.
6. Para P1-12/P1-13, el peso nominal proviene de `vinto_master.pallet_nominal_weight` (`backend/app/production_pallets.py`), y se asigna el número de pallet únicamente en el servidor. La preparación no debe reservar ni simular correlativos.

## Evidencia de CI

- Head #267 consultado: cuatro workflows vistos en `success`; eso no acredita toda la matriz.
- #266: la consulta a commits previos no devolvió runs; verificar nuevamente.
- Ningún cambio fue aplicado en VPS/producción.

## Próximo incremento recomendado

FOFF-02B.6: paquete de referencias servido por API con definición publicada y datos dependientes, incluidas recetas / pesos por artículo y contexto de línea. Debe ser verificable con la firma de preparación y contar con pruebas negativas. Integrar pin y almacenamiento solo cuando ese contrato esté completo.

**Sin merge, migraciones ni despliegue.**
