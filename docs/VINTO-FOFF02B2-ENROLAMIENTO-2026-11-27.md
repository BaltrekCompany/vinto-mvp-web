# FOFF-02B.2 — Enrolamiento de dispositivos de Operación

**Fecha:** 2026-11-27  
**Estado:** implementación en rama, CI y revisión pendientes.

## Contexto
Desarrollo apilado sobre el PR #264 (ofertas) y #263 (selector). Todos los datos actuales de VINTO son ficticios según confirmación expresa del responsable; las reglas de protección y trazabilidad siguen aplicando.

## Contrato implementado
- Nueva ruta `POST /api/offline/production/enroll` que exige sesión válida y permiso `production.capture`.
- Variable de entorno **`OFFLINE_PRODUCTION_ENROLLMENT_ENABLED=false` por defecto**. Esto permite integrar código sin habilitar el enrolamiento hasta estar listo.
- Adicionalmente exige al menos un formulario con elegibilidad efectiva (`eligible=True`) en sectores operativos, no solo el permiso amplio de perfil.
- Verifica UUIDv4 del dispositivo y emplea el registro central `vinto_master.device` mediante `capture_service._resolve_device`, como el patrón de enrolamiento de Calidad. Un dispositivo inactivo no se reactiva.
- Devuelve únicamente `device_key`, `enrolled: true` y **`captureEnabled: false`**; no emite firma, token CAPTURE, cookie ni credenciales.
- Respuesta con `Cache-Control: no-store`.

## Pruebas agregadas
Flag apagado, usuario sin grants, elegibilidad ausente, UUID no v4, enrolamiento permitido y rechazo del dispositivo inactivo.

## Límites y próximos pasos
1. Este incremento **NO** habilita capturar ni sincronizar formularios de producción offline; aún falta la autoridad firmada y las reglas D01–D04.
2. El registro de dispositivo es compartido con el motor existente; la **bóveda, el perfil, preparaciones, borradores y cola deben estar separados por módulo/autor/dispositivo antes de montar el cliente**. No reutilizar un borrador de Calidad como producción.
3. Diseñar evidencia firmada por usuario, dispositivo, `assignment_id`, máquina, formulario y versión, con contexto de receta/peso/turno y reloj calibrado; el receptor debe validar de nuevo contra el servidor.
4. No habilitar el flag en ningún entorno ni fusionar sin CI y auditoría de regresión.
5. El PR #264 tuvo un fallo en `test_sector_scope.StaticScopeTests.test_no_module_repeats_a_sector_code_literal` por constantes sectoriales repetidas en `offline_production.py`; se corrigió en la rama del PR #264 usando constantes de `app.sectors`. Validar el nuevo SHA con Actions.

**Sin migraciones, despliegues ni cambios en la VPS.**
