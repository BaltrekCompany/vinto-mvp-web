# FOFF-02B — Primera entrega: disponibilidad autorizada para preparar producción

**Fecha:** 2026-11-27  
**Estado:** API propuesta en PR independiente; **no es todavía la preparación offline completa**.

## Entrega implementada

- Ruta `GET /api/offline/production/offers` con sesión válida y `production.capture`.
- Reutiliza `production_machines(connection, user.sectors, user=user)` para no duplicar reglas de catálogo ni concesiones.
- Filtra únicamente máquinas de CONVERSION, REBOBINADO y BOBINAS, formularios con `eligible is True`, versión publicada y asociación a máquina.
- Respuesta `Cache-Control: private, no-store` y `captureEnabled: false`: **no puede habilitar envíos offline**.
- Pruebas de filtrado y ausencia de fallback ficticio.

## Pendientes de FOFF-02B antes de su cierre

1. Diseñar y desarrollar enrolamiento de dispositivo de Operación sin reutilizar el endpoint que requiere `quality.capture`; considerar controles de dispositivo activo.
2. Definir y firmar el alcance de preparación por autor/dispositivo/asignación/OT/línea/máquina/formulario/versión, con caducidad validada por servidor y zona `America/La_Paz`.
3. Preparar contexto y datos de formularios (P1-11 grupos repetibles, P1-12/13 artículos/pesos y P1-16 correlativo), almacenados cifrados y separados de los de Calidad en cliente.
4. Garantizar que los permisos y la preparación no se usen como sustituto de autorización efectiva durante sincronización.
5. Completar tests negativos y regresión Calidad, CI, revisión de PR, y luego FOFF-03 para receptor y captura reales.

**No contiene migraciones, nuevas escrituras, permisos adicionales, despliegue ni cambio de compuerta online.** El despliegue de cualquier PR deberá verificar las diferencias de release GitHub/Tubetes reportadas por auditoría y disponer de respaldo.
