# VINTO E2-D0 - Diagnostico previo a reprogramar OT asignadas/en produccion

**Estado:** diseno + lectura solamente. **No habilita E2-D**. No es una
solicitud de ejecutar cambios productivos y no se crean migraciones.

## Evidencia de base

- E2-B1 conserva la baseline inmutable; la ultima version operativa publicada
  sirve para asignaciones futuras. El servicio de reprogramacion rechaza una OT
  que no esta publicada o tuvo CUALQUIER asignacion historica o ejecucion E1.
- E2-C1: acuse de Operacion por (asignacion, version, usuario) y unicamente
  mientras esa asignacion esta activa. No cambia, bloquea ni reubica capturas.
- E2-C2: acuse de Supervision por (version de OT, usuario). No certifica que
  cada operador haya recibido una nueva asignacion.
- La ejecucion E1 es una entidad por LINEA BASE, con estados planned,
  enabled, in_production y finished. No existe actualmente un estado paused.
- F3/F6 guardan captures ligadas a la asignacion historica; el flujo de captura
  toma bloqueo de maquina, valida asignacion y E1 antes de confirmar.

## Riesgos y etapas propuestos

| Categoria | Lectura del diagnostico D0 | Tratamiento antes de mutar |
| --- | --- | --- |
| OT publicada sin asignaciones ni E1 | UNASSIGNED_NO_EXECUTION_EVIDENCE | Ya cubierta por E2-B1, sin ampliar su contrato |
| OT in_progress, linea sin asignaciones, captura ni E1 | UNASSIGNED_NO_EXECUTION_EVIDENCE | Candidata D1 *solo tras* pruebas de versiones mezcladas; no tocar otras lineas activas |
| Linea habilitada/asignada sin inicio productivo | ASSIGNED_OR_ENABLED_NOT_STARTED | D2: requiere plan de desasignacion/reasignacion con version exacta y acuses, sin reinterpretar historia |
| Linea con captura o E1 in_production / finished | PRODUCTION_OR_CAPTURE_HISTORY | D3: bloquear por defecto; requiere reconciliacion de cantidades y autorizacion de excepcion |
| Historial de asignaciones sin E1 comprobable | LEGACY_* | NO-GO: conciliacion manual; no inferir produccion a partir de assignment.active |
| Plan E1 sin assignment | HISTORICAL_ASSIGNMENT_OR_PLAN | Revisar con Supervision; nunca autorizar por heuristica |

La columna de numero de capturas no equivale a cantidad producida:
ni F3 ni F6 proporcionan una magnitud de produccion acumulada normalizada
para todas las maquinas/productos en este contrato. No se puede fijar
el limite inferior de una nueva cantidad sin definir la fuente y la unidad.

## Invariantes bloqueantes para todo E2-D futuro

1. No se reescriben snapshots publicados, baseline, asignaciones, capturas
   F3/F6, bobinas, lecturas E2-C1 ni E2-C2; no hay backfill retroactivo.
2. Una asignacion HISTORICA sigue apuntando a la version exacta sobre
   la que se capturo, aunque se publique otra para asignaciones futuras.
3. No se cambia maquina ni identidad logica de linea; cualquier cambio
   de producto/PV con produccion exige una decision funcional explicita.
4. Serializar con el bloqueo de OT y maquinas, y evitar deadlocks con
   capturas F3/F6 que toman maquina -> asignacion. No tomar locks
   en orden invertido ni terminar/reasignar silenciosamente.
5. No convertir un acuse de lectura en una autorizacion para escribir.
   La nueva version requerira destinatarios y acuses segun contexto.
6. Una actualizacion desde vN debe usar expected_version + imagen
   anterior de campos, y retornar 409 si otro usuario modifico la OT.
7. Impedir cambios a OT cerradas/archivadas o fuera del alcance
   funcional completo del usuario, incluidas OT multimaquina.
8. Nunca sustituir una asignacion en ejecucion ni generar otra activa
   sobre la misma maquina sin los controles E1/MF-13 existentes.
9. Falta de datos, errores o registros legacy no equivalen a cero
   produccion: el backend debe fallar cerrado.

## Decisiones de negocio por resolver antes de D2/D3

- Si una OT esta en produccion en MP1 y la linea L2 aun no fue asignada,
  puede Jefatura cambiar cantidad/entrega/PV/articulo de L2 mientras L1
  conserva su asignacion en la version anterior? (Recomendacion inicial:
  D1 puede admitirlo solo para L2 con historia cero y sin tocar L1.)
- Cuando L2 ya fue habilitada pero no iniciada, quien la deshabilita,
  y quien autoriza crear otra asignacion de la nueva version?
- Para una linea iniciada, que captura representa la cantidad buena
  acumulada y cual es la unidad homologada? Que ocurre con merma,
  bobinas hijas, rechazos de Calidad y produccion pendiente?
- Que cambios quedan prohibidos (producto, PV, maquina) y cuales
  podrian admitirse por excepcion (fecha/cantidad mayor al ejecutado)?
- El acuse pendiente debe bloquear el inicio/reinicio/captura?
  E2-C1 y E2-C2 NO bloquean esas operaciones hoy.
- Se requiere aprobacion de Supervision antes de notificar Operacion
  y quien puede revisar/autorizar una excepcion con produccion?

## E2-D0: inventario read-only, no-identificable

La funcion de lectura exige PostgreSQL REPEATABLE READ READ ONLY y devuelve
SOLO conteos por estado/riesgo, sin numeros de OT, lineas, usuarios,
maquinas, PV, capturas ni credenciales.
Cualquier tabla obligatoria ausente produce error, no cero.

CLI de uso una vez que el checkout de la rama sea accesible, bajo usuario
de servicio de VINTO y solo para la base correcta:

    cd /ruta/al/release/backend
    VINTO_E2D_EXPECTED_DATABASE=vinto_piloto \
      .venv/bin/python -m app.work_orders.e2d_readiness_cli

La CLI carga la URL de BD desde la configuracion existente del release;
nunca la imprime y comprueba current_database() antes de consultar.
No usar otra VPS, DB031, puerto 6543, ni credenciales de sistemas ajenos.
No introducir passwords en este chat, prompts ni comandos compartidos.

La lectura es un censo, NO un GO para D1. Se deben contrastar sus conteos
con produccion y validar reglas funcionales antes de habilitar escritura.

## Entregables

- **D0 (este cambio):** reporte agregado read-only, PG17 tests, documento.
- **D1:** revision segura de una linea SIN asignacion/ejecucion/captura de
  una OT in_progress; snapshot versionado + compatibilidad de asignaciones
  existentes; flag nuevo OFF; QA aislado antes de autorizacion productiva.
- **D2:** cambios de linea habilitada no iniciada, flujo supervisado de
  reemplazo de asignacion, version y acuses obligatorios.
- **D3:** reprogramacion de linea ya produciendo, solo despues de
  conciliacion F3/F6, reglas de cantidad y excepciones auditables.

**Regla de avance:** D0 no requiere migracion ni despliegue productivo;
D1-D3 seran PRs separados y no podran activarse con banderas por defecto.
