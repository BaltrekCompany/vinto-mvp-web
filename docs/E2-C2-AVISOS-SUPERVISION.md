# VINTO E2-C2 - Avisos y acuses de reprogramacion para Supervision

## Objetivo y limites

E2-C1 (migracion 0017) registra lectura de Operacion por ASIGNACION + VERSION.
E2-C2 agrega un canal de lectura a Supervision por VERSION DE OT: el aviso
esta disponible apenas Jefatura publica una revision, ANTES de cualquier
asignacion. No se reutiliza el recibo operativo (no existe assignment aun).

Solo se consideran revisiones E2-B1 validas: OT publicada sin asignaciones
historicas ni ejecucion, con snapshot operativo publicado; una vez asignada,
la revision sigue visible a Supervision mientras la OT este in_progress.

## Contrato del entregable

- Bandeja en Programacion, para Supervisores autorizados de Bobinas,
  Rebobinado y Conversion (excepto Calidad).
- Se muestran OT, maquina, linea, version actual, razon del cambio,
  autor, fecha y comparacion antes/despues de PV/articulo/cantidad/entrega.
- Un aviso por OT: la ULTIMA version publicada; v3 sustituye la v2 como
  pendiente. Los recibos historicos no se pierden.
- Boton He revisado esta version: acuse inmutable por
  (version_id, usuario autenticado), sello temporal en PostgreSQL,
  auditoria con actor y request_id, reintento idempotente.
- GET /api/work-orders/supervision-revision-notices.
- POST /api/work-orders/{id}/acknowledge-supervision-revision
  con SOLO {expected_version: N}. 409 si una publicacion mas nueva
  invalido el aviso leido; 404 OT inexistente/fuera del alcance/archivada
  o si no existe revision; 401/403 sin sesion/permiso de Supervisor.
- Alcance entero de OT: todas las maquinas de la baseline y maquina
  cabecera deben estar en sectores autorizados del usuario; sin
  revelacion parcial de una OT multimaquina con sectores mezclados.
- Una revision puede ser leida por VARIOS supervisores; el acuse es
  personal, no equivale a aprobacion global del turno.

## Exclusiones y seguridad de produccion

NO hay bloqueo de asignaciones, F3/F6, E1, ni notificaciones push/email,
WhatsApp o WebSocket. La bandeja consulta al abrir/actualizar.
NO se modifica ni se reescribe la baseline, ninguna version ya publicada,
ninguna asignacion ni captura. E2-B1 sigue impidiendo cambios una vez
existio asignacion o ejecucion. Esto ultimo es exclusivo de E2-D.

## Despliegue y rollback

- Migracion aditiva 0018_supervision_revision_receipts.sql:
  tabla vacia, FK/version, UNIQUE(version,user), triggers BEFORE para
  immutabilidad y vigencia, AFTER INSERT para auditoria, grants minimos.
- No hay backfill ni alteraciones de columnas existentes.
- El codigo anterior puede restaurarse (rollback de release) sin DROP de
  0018; el esquema siempre avanza. El migrador de versiones anteriores
  puede rechazar comprobar un esquema con version mayor: NO ejecutar
  check-release del SHA anterior tras aplicar 0018, salvo comprobar que
  se trate de la ruta de rollback deliberada.
- Condiciones: CI PG17/Node22, permisos y multisector, respaldo reciente
  restaurado y verificado, 0018 unica migracion pendiente, cambio de
  release con preflight/healthcheck y QA manual con OT ficticias.
- No publicar E2-D sin definir recipient/ack por version activa, reglas
  de capturas obsoletas, cantidades acumuladas y version operativa segura.
