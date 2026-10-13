# M4-A — Integración del circuito central de Rebobinado

Estado: **preparado para homologación, NO habilitado para operación real, NO homologado.** P1-10 y P1-29 siguen siendo fichas candidatas.

## Qué cambia
- **Disponibilidad verificada por el backend:** `GET /api/production/machines[?articles=true]` (solo lectura, `SET TRANSACTION READ ONLY`). Devuelve, para los sectores concedidos **y** operativos de la sesión, sus máquinas activas y los formularios publicados (área producción, política `CENTRAL_FORM_CODES`, vinculados a la máquina). Exige `work_order.read`, `assignment.read` o `production.capture`. No usa variables de entorno ni banderas.
- **Frontend:** `RebobinadoCentral` (Programación / Ejecución / Seguimiento) se muestra en Home cuando el front es Rebobinado. Sin disponibilidad del backend muestra «Rebobinado no está habilitado»: no crea OT, no abre capturas, no usa localStorage ni datos demo/legacy como respaldo.
- **Programación:** reutiliza `BobbinasProgramming` con props opcionales (`catalog`, `sectorLabel`); Bobinas no cambia.
- **Ejecución:** máquinas y formularios los publica el backend; la captura solo abre con asignación activa vigente (OT, turno y fecha operativa los resuelve el backend).
- **Seguimiento:** OT, asignaciones e historial central de P1-10 y P1-29 con sus parsers específicos.
- Los módulos legacy no se eliminan; no son respaldo de la ruta central.

## Configuración productiva
Sin cambios: `DEFAULT_OPERATIONAL_SECTORS = (BOBINAS,)` y `CENTRAL_FORM_CODES = {VINTO-P1-06}`. Con ella Rebobinado aparece como no habilitado aunque el usuario tenga la concesión.

## Pruebas
- Backend: 833 (suite principal) + 10 (`test_db_guard`, `test_capture_api` con DEV en solo lectura) OK; incluye 9 de `test_production_access`.
- Node: 436 OK. Lint de archivos tocados sin errores; `tsc`: único error heredado TS2322 en `app/page.tsx`. Build limpio, 31 archivos cliente, sin rutas de QA.
- E2E real (navegador + FastAPI + PostgreSQL efímero `*_test`, datos ficticios, aplicación normal):
  `scripts/e2e/m4a-e2e.mjs` — fase `enabled` 50/50 (Jefatura crea/publica OT COPASA y TUBETERA → Supervisión activa → Operación P1-10 y P1-29 con 2 rodelas y 2 formatos → PostgreSQL + auditoría → historial; reintentos sin duplicar; asignación vencida; formulario no vinculado; sin concesión; móvil 390 px); fase `disabled` 13/13 (configuración real). DEV comparado antes/después sin cambios.

## Requisitos pendientes antes de habilitar Rebobinado
1. Maestros reales aprobados (máquinas, artículos, turnos, líneas) y su importación controlada.
2. Homologación de P1-10 y P1-29 por VINTO y su alta en la política productiva (`CENTRAL_FORM_CODES`).
3. Cambio revisado de `DEFAULT_OPERATIONAL_SECTORS` en el backend y concesiones de usuarios por sector.
4. Decisiones industriales pendientes de P1-29 (catálogo de tubetes, unidad del espesor, visto bueno, alcance de grupos).
5. Firma/aprobación y correlativos, si VINTO los requiere.
