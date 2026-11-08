# VINTO E2-C1 — Aviso de programación asignada y acuse de lectura

## Límite funcional

E2-B1 (9554cd04; migración 0016) permite reprogramar OT publicadas
únicamente ANTES de la primera asignación y sin ejecución E1.
E2-C1 NO habilita modificaciones durante la producción: es un primer corte
para avisar y reconocer la versión reprogramada que Supervisión asignó.

## Contrato

1. La bandeja de Ejecución de Bobinas, Rebobinado y Conversión lista versiones
   revisadas de asignaciones ACTIVAS para máquinas cuyo permiso efectivo
   MF-13 de producción reconoce al usuario.
2. El aviso presenta OT, línea, máquina, versión, motivo, fecha, PV, artículo,
   cantidad y vencimiento de la programación efectivamente asignada.
3. He leído registra confirmación del usuario AUTENTICADO para la combinación
   (asignación, versión, usuario); doble envío es idempotente y auditable.
4. Un usuario sin sesión obtiene 401, sin permiso 403, y sin autorización
   de máquina o asignación activa obtiene 404. Versión incorrecta da 409.
5. Sin persistencia local ni polling; error de red NO se confunde con 0 avisos.
6. NO se toca historial, asignaciones, capturas, línea base ni permisos.
7. En E2-C1 ninguna captura queda bloqueada por acuse pendiente. Esta
   protección debe evaluarse antes de permitir cambios activos.
8. Los avisos son dentro de VINTO, no push/email/WhatsApp ni entrega en vivo.
9. Acuses pertenecen a Operación; la distribución formal a Supervisión
   queda en E2-C2.

## Base de datos y operación

La migración aditiva 0017 crea work_order_revision_receipt. Tabla vacía,
sin backfill ni DML sobre las existentes. Checksum fijado en pruebas.
El rollback de código a 9554cd04 NO deshace 0017 (no ejecutar DROP).

El despliegue requiere CI PostgreSQL 17, pruebas de revocación MF-13, historial
inmutable, chequeos de frontend, respaldo restaurado, migración 0017 verificada
y activación por el mismo procedimiento de E2-B1.

## Dependencia E2-C2 / E2-D

No levantar el bloqueo de E2-B1 sin versionado asociado a asignaciones
activas, destinatarios y acuse correcto para cada cambio, reconciliación
de instrucciones anteriores, y restricciones según producción acumulada.
Una lectura de E2-C1 NO autoriza cambiar retroactivamente una captura
ni una asignación.
