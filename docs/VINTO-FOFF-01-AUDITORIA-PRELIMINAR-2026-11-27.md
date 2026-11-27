# FOFF-01 — Auditoría preliminar de código GitHub (solo lectura)

**Fecha:** 2026-11-27  
**Repositorio/ref consultado:** BaltrekCompany/vinto-mvp-web, rama por defecto (main).  
**Estado:** PARCIAL — lectura de código completada para rutas esenciales; **pendiente VPS, DB efectiva, permisos reales y validaciones E2E**. No se realizaron cambios de código, migraciones ni despliegues.

## Hallazgos sustentados en código

1. **Tres sectores operativos en el código:** `backend/app/sectors.py` define BOBINAS, REBOBINADO y CONVERSION, sujetos a la intersección de sectores concedidos y operativos. La etiqueta operativa de piloto **no implica homologación industrial**.
2. **Disponibilidad dinámica:** `backend/app/production_access.py` expone `GET /api/production/machines` para máquinas activas, sector, formulario publicado, versión y `eligible` según usuario. Para el selector offline, filtrado de ejecución por elegibilidad efectiva en `components/vinto/sector-central.tsx`.
3. **Conversión y Rebobinado comparten shell:** `components/vinto/conversion-central.tsx` y `rebobinado-central.tsx` delegan en `sector-central.tsx`. El selector de líneas y validación de ejecución dependen de asignaciones activas y estado de ejecución, no de valores locales.
4. **Conversión: cuatro códigos de captura central conocidos:** `backend/app/capture_service.py` permite P1-11, P1-12, P1-13 y P1-16, solo cuando la versión publicada, máquina y grants lo permitan. Las capturas centrales usan `POST /api/captures` y `assignment_id`; no deducir que estos cuatro figuren en todas las máquinas.
5. **Producción central es transaccional:** `backend/app/capture_service.py` valida asignación vigente, máquina, turno, versión, dispositivo, campos y `capture_id` idempotente; `backend/app/capture_schemas.py` recibe capture_id, form_code, assignment_id, device_key, values y calcula OT/turno/fecha/artículo en el servidor.
6. **Calidad Offline NO es receptor universal:** `backend/app/quality/offline_router.py` y `offline_sync_router.py` están limitados a operaciones/códigos de Calidad y su modelo de contexto. Reutilizar infraestructura y patrones, no suponer reutilización directa de endpoint.
7. **Bobinas tiene regla especialmente sensible:** `backend/app/bobbins/service.py` P1-03 registra captura + bobina + quality_release pendiente + correlativo, en una sola transacción. Reintento mismo ID es idempotente. El tratamiento offline debe conservar el diseño transaccional; no emitir correlativos locales definitivos.
8. **Decisiones industriales pendientes:** `docs/M7-A-conversion-decisiones-VINTO.md` documenta 36 decisiones de homologación sin aprobación. `backend/app/sectors.py` y `capture_service.py` indican que los formularios de Conversión están habilitados como candidatos para pilotos sintéticos, no que sus reglas industriales estén homologadas.
9. **Datos históricos de navegador:** `conversion-central.tsx` señala que no lee ni elimina registros legacy locales. No migrarlos automáticamente al nuevo offline.
10. **Memoria histórica:** `docs/VINTO-CALIDAD-OFFLINE-MEMORIA-INTEGRAL-2026-11-26.md` documenta PWA, bóveda cifrada, autorización firmada y sync revalidada. Su cierre QA no equivale a validar nuevos frentes.

## Evaluación inicial y propuesta FOFF-03

- Primer alcance: **los formularios P1-11/P1-12/P1-13/P1-16 efectivamente publicados y elegibles en las máquinas autorizadas**, con preparaciones asociadas a `assignment_id` y snapshot verificable. Los códigos no publicados para la máquina no se muestran.
- Construir endpoints de preparación/autoridad y recepción offline de **producción** (no modificar/ensanchar ciegamente receptor de Calidad), apoyados en `submit_production_capture` y sus reglas transaccionales vigentes.
- En reconexión revalidar usuario original, grant/versión, máquina, asignación/OT/línea, estado de ejecución y campos. Ante asignación vencida, reprogramada o terminada: conservar borrador y mostrar *Requiere revisión*, sin registrar contra otra OT.
- Investigar P1-12/P1-13 (pallet y datos calculados) y P1-11 (grupos repetibles) antes de codificar serialización y firmas de definición; evitar snapshot incompleto.
- En el piloto de producción con datos ficticios: respaldo restaurable, plan rollback, CI, pruebas negativas y verificación de ausencia de usuarios/datos reales antes de habilitar. Sin esos controles, no desplegar.

## Pendientes para cerrar FOFF-01

1. Claude Code en VPS **solo lectura**: commit/release desplegado; configuración y salud PWA/API; tabla de sector/máquina/form_version_machine y grants efectivos con datos no sensibles; OT/líneas/asignaciones de prueba; esquema y migraciones; métricas de solicitudes de captura; diferencia GitHub vs release.
2. Inspección adicional de componentes `p1-11-v3-capture`, `p1-13-v3-capture`, P1-12, P1-16 y `conversion-candidates`; `lib/vinto/quality-offline*`; frontend de preparación.
3. Precisar contrato de firma temporal/snapshot y reconciliación para producción, incluyendo zona horaria operativa de planta **America/La_Paz**, sin confundir fecha operativa con reloj del dispositivo.
4. Matriz definitiva de combinaciones máquina × formulario realmente publicadas y elegibles. Los nombres GAMBINI/OMET_I/OMET_II provienen de captura de pantalla, **no son lista exhaustiva**.
5. Evidencia y aprobación del usuario del informe completo antes de implementar FOFF-02/03.

**Conclusión preliminar:** arquitectura existente favorable a un selector común y a un motor de producción offline especializado. **No declarar FOFF-01 PASS ni desplegar aún**.
