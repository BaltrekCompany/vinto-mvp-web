# FOFF — Decisiones aprobadas e incremento FOFF-02

**Fecha:** 2026-11-27. **Autorización del responsable:** todos los datos actuales de VINTO son ficticios; aprobadas D01–D04 y comienzo de implementación. Esto no certifica que un despliegue concreto haya ocurrido.

## Decisiones de arquitectura aprobadas

- **D01 — Capturas tardías:** preservar hora original, identidad, máquina y asignación/OT original; aceptar solo tras verificación independiente del contexto histórico y permisos. En caso de incertidumbre, revisión, nunca reasignación silenciosa. No usar el reloj del dispositivo como única prueba de turno.
- **D02 — Concesiones:** nuevo receptor offline de producción exigirá concesión máquina/formulario efectiva incluso con captura online histórica en modo `off`. Cambiar la compuerta online es incremento separado.
- **D03 — Revisiones:** conservar pendientes locales y diseñar persistencia de revisiones recibidas en PostgreSQL con migración aditiva, retención e idempotencia. Un 202 sin escritura operativa no equivale a captura registrada.
- **D04 — Duplicados:** captura idempotente por `capture_id` y regla semántica por operación; los pallets P1-12/P1-13 reciben numeración definitiva exclusivamente en backend; no usar una regla ingenua que bloquee dos operaciones verdaderamente distintas.

## FOFF-02: primera entrega de interfaz, sin captura offline

- `lib/vinto/foff-navigation.ts`: proyección read-only de `GET /api/production/machines` filtrada por `eligible === true`, con frentes CONVERSION, REBOBINADO y BOBINAS y máquinas/formularios dinámicos.
- `components/vinto/foff-module-selector.tsx`: selector de módulos/máquinas y tarjetas de formularios; advertencia explícita de que no se pueden capturar aún sin conexión.
- `app/page.tsx`: acceso desde sesión con `production.capture` y disponibilidad confirmada; cierra el selector al cambiar/cerrar sesión; no sustituye pantallas existentes ni modifica Calidad Offline.
- `tests/foff-navigation.test.ts`: filtrado de permisos, ausencia de eligibility y sectores vacíos.
- Sin endpoints nuevos, migraciones, permisos nuevos, sincronización productiva, habilitación de escritura offline ni despliegue.

## Próximos incrementos

1. Verificar CI e inspeccionar compatibilidad de UI y regresión Calidad Offline. Si hay fallos, corregir antes de merge.
2. FOFF-02B: enrolamiento de dispositivo de Operación, separación de identidades/colas y preparación autorizada, en PR propio; mantener capturas offline deshabilitadas.
3. FOFF-03: contratos y receptor de Conversión con validación D01–D04, luego pruebas de concurrencia/negativas, CI, despliegue controlado en producción y QA real móvil. Orden técnico interno: P1-16, P1-11, P1-12/P1-13. No iniciar Rebobinado hasta cierre validado de Conversión.
4. Antes de desplegar, coordinar que `main` incluye cambios de Tubetes aún no presentes en el release documentado por Claude Code, y tomar nuevo respaldo restaurable.

## Notas

- Hora oficial de planta `America/La_Paz`.
- La auditoría de Claude Code del 27-nov reportó `FOFF_01_READ_ONLY=PASS` pero señaló que NO equivalía a QA funcional ni permiso de despliegue.
- Archivo de salida temporal de Claude de ~64 MB: requiere comprobación de ruta e integridad antes de eliminación; no se toca desde este PR.
