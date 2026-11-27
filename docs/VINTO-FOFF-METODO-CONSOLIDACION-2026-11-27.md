# FOFF — Método de entrega por fase y registro de consolidación

**Aprobado por el responsable:** 2026-11-27. No solicitar autorización para cada detalle técnico de una fase ya aprobada.

## Método obligatorio

1. **Una fase funcional completa** (FOFF-02 infraestructura común; FOFF-03 Conversión; FOFF-04 Rebobinado; FOFF-05 Bobinas; FOFF-06 prueba final), con los subtrabajos técnicos resueltos internamente sin multiplicar hitos ni pedir microaprobaciones.
2. Si aparece un subtrabajo técnico, incorporarlo a la fase existente y **comunicarlo**. Solo escalar al responsable cambios de alcance, decisiones de negocio o riesgos altos que requieran su criterio.
3. Antes de dar una fase por terminada, ejecutar tests, compilación de frontend y backend, lint, regresiones de Calidad Offline y CI de integración; reparar los fallos y repetir. Sin asumir que «PR creado» equivale a PASS.
4. Entregar un PR consolidado para la revisión de la fase; cuando existan PR apilados de exploración, no fusionar ciegamente todos. Documentar hashes, gates, pruebas y pendientes.
5. Para los despliegues productivos: respaldos restaurables, control de versión desplegada, rollback y QA móvil real. El hecho de que los datos actuales sean ficticios no elimina estos controles.

## FOFF-02: consolidación

- PR #263–#268 registran el trabajo exploratorio por subcomponentes.
- **PR #270** reúne selector, ofertas, enrolamiento, almacenamiento cifrado separado, firma de preparación y verificador navegador sobre la rama de desarrollo.
- Se creó `.github/workflows/foff02-consolidated.yml` para comprobar TypeScript, unit tests, lint/build, sintaxis/importación backend y pruebas de contratos.
- Primera ejecución del gate: 14 tests backend PASS; el job de prueba sectorial falló por falta de `TEST_ADMIN_DATABASE_URL` (no por el código). Se eliminó ese paso de este job sin PostgreSQL: esa regresión se comprueba en workflows PG17 dedicados.
- La primera ejecución TypeScript detectó una sintaxis no compatible con Node strip-only (parameter property) y un import ESM sin extensión; se corrigieron en la misma rama.
- El gate actualizado aún debe terminar antes de atribuir compilación y pruebas PASS.
- **La infraestructura todavía no está íntegramente conectada** a una preparación real en navegador: el pin autenticado, la definición versionada/recetas/pesos y el vínculo de la firma con el paquete completo deben resolverse antes de habilitar operación offline.
- Las escrituras de Conversión, reconciliación D01–D04 y prueba en producción corresponden a FOFF-03. No autorizar capturas por la simple existencia de una firma `preparation_only`.

## Estado al redactar

Sin merge ni deploy. No iniciar Rebobinado antes de desplegar y probar Conversión. Consultar CI del HEAD actual del PR #270, no ejecuciones de commits anteriores.
