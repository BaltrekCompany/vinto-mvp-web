# VINTO RBE-04 — Backend y reservas de crías (28/11/2026)

## Alcance y separación de responsabilidades

- Repositorio: `BaltrekCompany/vinto-mvp-web`, PR [#279](https://github.com/BaltrekCompany/vinto-mvp-web/pull/279), rama `feat/rbe-04-rewinding-export-backend-2026-11-27`.
- Dependencias de diseño/interfaz: PR #274 (RBE-02) y PR #277 (RBE-03). Ninguno se fusiona como parte de RBE-04.
- RBE-04 implementa migración SQL aditiva 0032, API, historial, clasificación de OT, reservas, permisos y almacenamiento del PDF original producido posteriormente por RBE-05.
- **NO** desplegar ni aplicar migración 0032 desde GitHub; backup, QA y despliegue VPS quedan a cargo del flujo autorizado con Claude Code. No se hicieron cambios en producción durante este incremento.

## Invariantes de dominio

1. Las fuentes son capturas P1-07 de REBOBINADO, versión >=3, estado submitted/closed, madre identificada por UUID, con OT publicada/en ejecución/cerrada, no archivada ni retirada de QA y clasificación vigente `production_confirmed`.
2. Solo crías reales de esa madre, calidad `released`, posición 1–22 sin 12 y peso positivo.
3. Se crean borradores sin reservas; la selección de paquetes exige Cría A y entre una y cinco selecciones únicas. El reporte conserva contexto PV, artículo, máquina, destino y snapshots.
4. Al generar, la transacción serializa el reporte, revalida clasificación, crías, P1-07 y concesiones, conserva snapshot y PDF inmutable, y crea reservas. Índice único parcial `rewinding_export_reservation_active_bobbin_uidx` evita simultáneamente dos reservas activas de una cría.
5. Cada reserva conserva `report_id`, `package_id`, `package_child_id`, `child_bobbin_id`. Dos claves foráneas compuestas verifican la cadena de pertenencia y el bobbin seleccionado; los campos son inmutables.
6. Una anulación exige Jefatura con alcance REBOBINADO y motivo; cambia estado y libera reservas en una sola transacción, mantiene PDF y eventos. No elimina físicamente historia, reservas ni PDF.
7. GET de reporte/historial/PDF revalida permisos vivos en BD, respeta propiedad/sector y el PDF se verifica por SHA-256. Clasificación OT es append-only, con protección de Jefatura y sin depender de `work_order.read`.
8. RBE-05 es el único responsable de integrar el renderer. El PDF no se reconstruye en la descarga.

## Contrato HTTP esperado por RBE-03

Raíz: `/api/reports/rewinding-export`.

- GET `/pvs`, `/products?pv_reference=`, `/mothers?pv_reference=&article_id=`, `/mothers/{id}/children`.
- GET/POST `/drafts`, GET/PATCH `/drafts/{id}`.
- POST `/drafts/{id}/packages`, PATCH `/drafts/{id}/packages/{package_id}`, POST `/drafts/{id}/packages/{package_id}/remove`.
- POST `/drafts/{id}/preview`, POST `/drafts/{id}/discard`.
- GET `/work-orders`, GET/POST `/work-orders/{id}/classification`.

Las colecciones devuelven `{"items":[...]}`. Las escrituras de cabecera/paquetes devuelven el borrador actualizado; la clasificación no registrada devuelve sus campos nulos.

## CI, pruebas y evidencia

Workflow: `.github/workflows/rbe-04-backend-reservations.yml`, PostgreSQL 17 desechable y base `*_test`.
- Migración completa y checksum.
- Contrato de rutas, matriz de perfiles, autorización efectiva P1-07, integridad PDF y anulación.
- Esquema/triggers/regresión del alcance sectorial.
- Dos conexiones concurrentes intentan reservar una misma cría con operadores sintéticos distintos, verificando que una sola inserción prevalece en el índice parcial real. Para este ensayo se desactivan temporalmente **solo en la sesión de BD desechable** los triggers de negocio con `session_replication_role=replica`; por tanto valida **la exclusividad del índice**, no todavía el flujo transaccional HTTP íntegro.
- GitHub Actions publica artefacto `rbe04-pg17-<run_id>` con logs de migración, contratos, esquema, sector y concurrencia, retenido 14 días.

## Pendientes antes de aprobación y despliegue

- Confirmar **PASS** de la ejecución GitHub Actions del último SHA; cambios en rama no equivalen a CI aprobado.
- Ejecutar pruebas de integración verdaderas con 2 usuarios reales de prueba, motor de concesiones, clasificación, generación del renderer RBE-05 y cancelación/reintento. No confundir el test de índice aislado con esa prueba.
- Contrastar respuestas JSON con validadores estrictos del frontend en un entorno de QA que combine PR #277 y #279, y resolver cualquier incompatibilidad.
- Verificar que el artefacto del workflow actual se generó y es descargable.
- No hacer merge, aplicar migraciones, tocar VPS ni desplegar hasta aprobación explícita y procedimiento de rollback.

**Estado al redactarse:** implementación en revisión/CI, no aprobada para producción.
