"""Copia operativa y asignaciones de Bobinas.

Flujo: Jefatura publica la baseline (v1) -> Supervisión activa una línea -> el backend garantiza una versión
`operational` publicada (copia COMPLETA de la baseline) -> la asignación apunta a la línea de esa versión operativa,
con turno y fecha operativa resueltos por el backend en el instante actual de PostgreSQL.

Garantías:
- La baseline NUNCA se modifica; las asignaciones nunca apuntan a una línea baseline.
- La primera activación de una OT crea la versión operativa (siguiente version_number): INSERT con published_at NULL,
  copia de todas las líneas y solo entonces published_at. Las siguientes activaciones reutilizan la operativa publicada
  de mayor version_number; no se crea una versión por turno ni por asignación.
- La máquina de la asignación es la de la LÍNEA baseline (0010), no la de la cabecera de la OT.
- Compuerta WORK_ORDERS_MULTI_MACHINE_ENABLED (apagada por defecto):
  * apagada = semántica histórica: una sola asignación activa por máquina; activar otra línea (o de otra OT) reemplaza la
    anterior. Si una máquina ya tiene VARIAS asignaciones activas (compuerta apagada después de usarla) no se finaliza nada
    por adivinación: 409 MULTIPLE_ACTIVE_ASSIGNMENTS hasta que se finalicen explícitamente con `finish`.
  * encendida = varias líneas de la MISMA OT activas a la vez en una máquina; otra OT en esa máquina -> 409
    MACHINE_ACTIVE_WITH_OTHER_WORK_ORDER (nunca se finaliza la ajena). La BD lo garantiza (0011: índice único por línea activa
    y trigger serializado con el mismo lock de máquina).
- Asignaciones vencidas (turno o fecha operativa distintos de los actuales): la siguiente activación en esa máquina las
  finaliza (finished_at, mismo registro, mismo contexto histórico para sus capturas) y no cuentan para el conflicto entre OT.
- Orden de locks (evita interbloqueos): work_order (FOR UPDATE) -> máquinas (advisory, ordenadas por id) -> asignaciones
  (FOR UPDATE). `finish` toma máquina -> asignación; las capturas, máquina -> asignación. `_load_target` y `_activate_target`
  están separados para que la activación masiva (PR4) valide y active varias líneas en UNA transacción con ese orden.
  Una asignación `finished` nunca se reactiva: se crea una nueva.
- Turno y fecha operativa vienen de `resolve_shift` con `clock_timestamp()` de PostgreSQL; el cliente no los envía.
- Auditoría: cada paso fija un `vinto.reason` propio; el actor y un `request_id` del servidor van en todas las filas.
"""

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime

from app.assignments.errors import (ActivationBlockedError, ActivationPlanChangedError, AssignmentNotFoundError, BaselineLineNotFoundError, InvalidAssignmentFilterError,
                                    MachineBusyWithOtherWorkOrderError, MultipleActiveAssignmentsError, OperationalVersionError,
                                    WorkOrderNotActivatableError)
from app.config import settings
from app.shifts import ResolvedShift, ShiftResolutionError, resolve_shift
from app.work_orders.errors import (MachineNotFoundError, MachineOutsideScopeError, MultiMachineDisabledError,
                                    WorkOrderNotFoundError)
from app.sectors import in_scope, scoped_sector_codes

ASSIGNMENT_STATUSES = ("active", "finished")
DEFAULT_LIST_LIMIT = 100
MAX_LIST_LIMIT = 500


@dataclass(frozen=True)
class AssignmentLineView:
    id: uuid.UUID
    line_code: str
    pv_reference: str
    article_code: str
    article_description: str
    quantity: object
    unit: str
    due_date: date


@dataclass(frozen=True)
class AssignmentView:
    id: uuid.UUID
    status: str
    operating_date: date
    created_at: datetime
    finished_at: datetime | None
    machine_code: str
    machine_name: str
    shift_code: str
    shift_name: str
    work_order_id: uuid.UUID
    work_order_number: str
    operational_version_number: int
    line: AssignmentLineView
    assigned_by_id: uuid.UUID
    assigned_by_name: str


@dataclass(frozen=True)
class ActivationResult:
    assignment: AssignmentView
    created: bool
    already_active: bool
    finished_assignment_id: uuid.UUID | None  # solo cuando se finalizó exactamente una; la lista completa va en finished_assignment_ids
    finished_assignment_ids: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True)
class ActiveItem:
    assignment: AssignmentView
    stale: bool | None  # None cuando no se puede resolver el turno actual


@dataclass(frozen=True)
class ActiveAssignment:
    assignment: AssignmentView | None
    current_shift_code: str | None
    current_shift_name: str | None
    current_operating_date: date | None
    stale: bool | None  # None cuando no se puede resolver el turno actual


@dataclass(frozen=True)
class ActiveLines:
    current_shift_code: str | None
    current_shift_name: str | None
    current_operating_date: date | None
    items: tuple[ActiveItem, ...]  # TODAS las activas de la máquina, antiguas primero


# ---------------------------------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------------------------------

def _now(connection) -> datetime:
    """Instante actual según el reloj de PostgreSQL (datetime aware). Es la única fuente de 'ahora'."""
    return connection.execute("SELECT clock_timestamp()").fetchone()[0]


def _context(connection, actor_id, request_id, reason):
    connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor_id),))
    connection.execute("SELECT set_config('vinto.request_id', %s, true)", (request_id,))
    connection.execute("SELECT set_config('vinto.reason', %s, true)", (reason,))


def _reason(connection, reason):
    connection.execute("SELECT set_config('vinto.reason', %s, true)", (reason,))


def _multi_machine_enabled() -> bool:
    return settings.work_orders_multi_machine_enabled is True  # solo configuración del servidor; el cliente no puede cambiarla


def _machine_lock(connection, machine_id):
    key = int.from_bytes(hashlib.sha256(f"vinto-assignment-machine:{machine_id}".encode()).digest()[:8], "big", signed=True)
    connection.execute("SELECT pg_advisory_xact_lock(%s)", (key,))


def _uuid(value, error):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise error() from None


def _machine_info(connection, machine_code, sectors):
    if not isinstance(machine_code, str) or not machine_code.strip():
        raise MachineNotFoundError("machine_code es obligatorio")
    row = connection.execute(
        """SELECT m.id, m.name, m.active, s.id, s.code FROM vinto_master.machine m
           JOIN vinto_master.sector s ON s.id = m.sector_id WHERE m.code = %s""", (machine_code.strip(),)).fetchone()
    if row is None:
        raise MachineNotFoundError()
    if not row[2] or not in_scope(row[4], sectors):
        raise MachineOutsideScopeError()
    return row[0], row[1], row[3]


_VIEW_SQL = """SELECT a.id, a.status, a.operating_date, a.created_at, a.finished_at, m.code, m.name, sh.code, sh.name,
                      wo.id, wo.number, v.version_number,
                      l.id, l.line_code, l.pv_reference, ar.code, av.description, l.quantity, u.code, l.due_date,
                      usr.id, usr.display_name
               FROM vinto_txn.assignment a
               JOIN vinto_master.machine m ON m.id = a.machine_id
               JOIN vinto_master.sector s ON s.id = m.sector_id
               JOIN vinto_config.shift_schedule sc ON sc.id = a.shift_schedule_id
               JOIN vinto_config.shift sh ON sh.id = sc.shift_id
               JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
               JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
               JOIN vinto_txn.work_order wo ON wo.id = v.work_order_id
               JOIN vinto_master.article_version av ON av.id = l.article_version_id
               JOIN vinto_master.article ar ON ar.id = av.article_id
               JOIN vinto_master.unit u ON u.id = l.unit_id
               JOIN vinto_master."user" usr ON usr.id = a.assigned_by
               WHERE s.code = ANY(%s)"""


def _to_view(row) -> AssignmentView:
    (a_id, status, operating_date, created_at, finished_at, m_code, m_name, sh_code, sh_name, wo_id, wo_number, version_number,
     l_id, line_code, pv, article_code, description, quantity, unit, due_date, user_id, user_name) = row
    return AssignmentView(a_id, status, operating_date, created_at, finished_at, m_code, m_name, sh_code, sh_name, wo_id, wo_number,
                          version_number, AssignmentLineView(l_id, line_code, pv, article_code, description, quantity, unit, due_date), user_id, user_name)


def get_assignment(connection, assignment_id, *, sectors) -> AssignmentView:
    assignment_id = _uuid(assignment_id, AssignmentNotFoundError)
    rows = connection.execute(_VIEW_SQL + " AND a.id = %s", (list(scoped_sector_codes(sectors)), assignment_id)).fetchall()
    if not rows:
        raise AssignmentNotFoundError()
    return _to_view(rows[0])


# ---------------------------------------------------------------------------------------------------
# operational version
# ---------------------------------------------------------------------------------------------------

def _ensure_operational(connection, work_order_id, baseline_version_id):
    """Devuelve el id de la versión operativa publicada de mayor version_number; la crea si no existe.

    Se llama con la fila de la OT bloqueada (FOR UPDATE): otro proceso que active la misma OT espera, vuelve a
    comprobar y encuentra la operativa ya publicada, así que nunca se crean v2 y v3 por accidente.
    """
    row = connection.execute(
        """SELECT id FROM vinto_txn.work_order_version
           WHERE work_order_id = %s AND kind = 'operational' AND published_at IS NOT NULL
           ORDER BY version_number DESC LIMIT 1""", (work_order_id,)).fetchone()
    if row is not None:
        return row[0]
    _reason(connection, "create operational work order version")
    version_id = connection.execute(
        """INSERT INTO vinto_txn.work_order_version (work_order_id, version_number, kind)
           SELECT %s, coalesce(max(version_number), 0) + 1, 'operational' FROM vinto_txn.work_order_version WHERE work_order_id = %s
           RETURNING id""", (work_order_id, work_order_id)).fetchone()[0]
    copied = connection.execute(
        """INSERT INTO vinto_txn.work_order_line (work_order_version_id, line_code, pv_reference, article_version_id, unit_id, quantity, due_date)
           SELECT %s, line_code, pv_reference, article_version_id, unit_id, quantity, due_date
           FROM vinto_txn.work_order_line WHERE work_order_version_id = %s ORDER BY length(line_code), line_code""",
        (version_id, baseline_version_id)).rowcount
    if copied == 0:
        raise OperationalVersionError("La baseline no tiene líneas que copiar")
    # Publicar DESPUÉS de copiar: una vez publicada, los triggers de 0001 la hacen inmutable.
    connection.execute("UPDATE vinto_txn.work_order_version SET published_at = clock_timestamp() WHERE id = %s", (version_id,))
    return version_id


# ---------------------------------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class _Target:
    """Línea baseline a activar, ya validada. La máquina es la de la LÍNEA."""
    line_code: str
    baseline_version_id: uuid.UUID
    machine_id: uuid.UUID
    sector_id: uuid.UUID


def _lock_machines(connection, machine_ids):
    """Locks de máquina en orden determinista (por id): dos activaciones multi-máquina nunca se esperan en ciclo."""
    for machine_id in sorted(set(machine_ids), key=str):
        _machine_lock(connection, machine_id)


def _load_target(connection, *, work_order_id, baseline_line_id, sectors) -> tuple[str, _Target]:
    """Bloquea la OT (FOR UPDATE) y valida todo lo que no depende del turno. Devuelve (estado de la OT, destino).

    Visibilidad: la OT es visible si la máquina de su cabecera o de alguna línea baseline está en el alcance del actor; si no, 404 como
    si no existiera. La línea cuya máquina está fuera del alcance es indistinguible de una inexistente (BASELINE_LINE_NOT_FOUND).
    """
    order = connection.execute("SELECT status, machine_id FROM vinto_txn.work_order WHERE id = %s FOR UPDATE", (work_order_id,)).fetchone()
    codes = list(scoped_sector_codes(sectors))
    if order is None or not connection.execute(
            """SELECT EXISTS (SELECT 1 FROM vinto_master.machine m JOIN vinto_master.sector s ON s.id = m.sector_id WHERE m.id = %s AND s.code = ANY(%s))
                   OR EXISTS (SELECT 1 FROM vinto_txn.work_order_line l JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
                              JOIN vinto_master.machine m ON m.id = l.machine_id JOIN vinto_master.sector s ON s.id = m.sector_id
                              WHERE v.work_order_id = %s AND v.kind = 'baseline' AND s.code = ANY(%s))""",
            (order[1], codes, work_order_id, codes)).fetchone()[0]:
        raise WorkOrderNotFoundError()
    status, header_machine_id = order
    if status not in ("published", "in_progress"):
        raise WorkOrderNotActivatableError(f"La orden está en estado {status}")
    base = connection.execute(
        """SELECT l.line_code, v.id, l.machine_id, m.active, s.id, s.code FROM vinto_txn.work_order_line l
           JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
           JOIN vinto_master.machine m ON m.id = l.machine_id JOIN vinto_master.sector s ON s.id = m.sector_id
           WHERE l.id = %s AND v.work_order_id = %s AND v.kind = 'baseline' AND v.version_number = 1 AND v.published_at IS NOT NULL""",
        (baseline_line_id, work_order_id)).fetchone()
    if base is None or base[5] not in codes:
        raise BaselineLineNotFoundError()
    line_code, baseline_version_id, machine_id, machine_active, sector_id, _ = base
    if machine_id != header_machine_id and not _multi_machine_enabled():
        raise MultiMachineDisabledError()
    if not machine_active:
        raise WorkOrderNotActivatableError("La máquina de la línea está inactiva")
    return status, _Target(line_code, baseline_version_id, machine_id, sector_id)


def _tagged(reason, tag):
    return reason if tag is None else f"{reason} [{tag}]"


def _activate_target(connection, *, actor_id, work_order_id, order_status, target: _Target, shift: ResolvedShift, sectors, batch_tag=None) -> ActivationResult:
    """Activa un destino ya validado. Exige la OT bloqueada; toma el lock de la máquina (re-entrante si el llamador ya lo tiene)."""
    multi = _multi_machine_enabled()
    _lock_machines(connection, [target.machine_id])
    # E2-D2-B0: machine lock precedes reservation row read; no D2 writers yet.
    from app.work_orders import handoff_guard
    handoff_guard.require_line_unreserved(
        connection, work_order_id=work_order_id, line_code=target.line_code)
    # A turn change may make prior assignments stale while their logical line
    # remains in production. Never activate a different OT on that machine
    # until Supervisión explicitly finishes the prior logical line.
    if settings.work_order_line_execution_enabled is True:
        producing_other_ot = connection.execute(
            """SELECT EXISTS (
                   SELECT 1 FROM vinto_txn.work_order_line_execution
                   WHERE machine_id=%s AND status='in_production' AND work_order_id<>%s
               )""", (target.machine_id, work_order_id)).fetchone()[0]
        if producing_other_ot:
            raise MachineBusyWithOtherWorkOrderError()
    # Declares the mode to trigger 0012 (the database cannot see the gate): anything but 'on' is single-assignment mode there.
    connection.execute("SELECT set_config('vinto.assignment_multi_line', %s, true)", ("on" if multi else "off",))
    operational_version_id = _ensure_operational(connection, work_order_id, target.baseline_version_id)
    operational_line = connection.execute(
        "SELECT id, machine_id FROM vinto_txn.work_order_line WHERE work_order_version_id = %s AND line_code = %s", (operational_version_id, target.line_code)).fetchone()
    if operational_line is None:
        raise OperationalVersionError(f"La versión operativa no contiene la línea {target.line_code}")
    if operational_line[1] != target.machine_id:
        raise OperationalVersionError(f"La línea operativa {target.line_code} no está en la misma máquina que su baseline")
    operational_line_id = operational_line[0]
    actives = connection.execute(
        """SELECT a.id, a.work_order_line_id, a.shift_schedule_id, a.operating_date, v.work_order_id, l.line_code
           FROM vinto_txn.assignment a JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
           JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
           WHERE a.machine_id = %s AND a.status = 'active' ORDER BY a.created_at, a.id FOR UPDATE OF a""", (target.machine_id,)).fetchall()
    context = (shift.shift_schedule_id, shift.operating_date)
    current = [row for row in actives if (row[2], row[3]) == context]
    stale = [row for row in actives if (row[2], row[3]) != context]
    for row in current:
        if row[4] == work_order_id and row[5] == target.line_code:  # logical line stable across E2-D snapshots
            if settings.work_order_line_execution_enabled is True:
                from app.work_orders.line_execution import enable_from_activation
                enable_from_activation(
                    connection, actor_id=actor_id, work_order_id=work_order_id,
                    baseline_version_id=target.baseline_version_id, line_code=target.line_code,
                    machine_id=target.machine_id, allow_create=False)
            return ActivationResult(get_assignment(connection, row[0], sectors=sectors), created=False, already_active=True, finished_assignment_id=None)
    replaced = []
    if multi:
        if any(row[4] != work_order_id for row in current):
            raise MachineBusyWithOtherWorkOrderError()
    elif len(current) > 1:
        raise MultipleActiveAssignmentsError()  # nada se ha escrito todavía; tampoco se finaliza ninguna por adivinación
    else:
        replaced = current  # semántica histórica: la anterior se sustituye
    finished = [row[0] for row in (*stale, *replaced)]
    # An unrelated activation/shift rollover must not silently finish a line
    # reserved by Supervisión (including assignments of another OT).
    affected = {(row[4], row[5]) for row in (*stale, *replaced)}
    for affected_order_id, affected_code in sorted(affected, key=lambda x: (str(x[0]), x[1])):
        handoff_guard.require_line_unreserved(
            connection, work_order_id=affected_order_id, line_code=affected_code)
    if settings.work_order_line_execution_enabled is True and finished:
        # Single-assignment mode must not silently end the shift assignment of
        # a *different logical line* that is still in production. A fresh shift
        # assignment for the SAME line is legitimate and remains allowed.
        affected_codes = sorted({
            row[5] for row in (*stale, *replaced)
            if row[4] == work_order_id and row[5] != target.line_code
        })
        if affected_codes:
            producing_to_replace = connection.execute(
                """SELECT EXISTS (
                     SELECT 1 FROM vinto_txn.work_order_line_execution e
                     JOIN vinto_txn.work_order_line baseline
                       ON baseline.id=e.baseline_line_id
                     WHERE e.work_order_id=%s AND e.machine_id=%s
                       AND e.status='in_production'
                       AND baseline.line_code=ANY(%s)
                   )""", (work_order_id, target.machine_id, affected_codes)).fetchone()[0]
            if producing_to_replace:
                from app.work_orders.line_execution import ExecutionStateConflictError
                raise ExecutionStateConflictError(
                    "Otra linea esta en produccion; finalice su ejecucion logica antes de sustituir su asignacion")
    if finished:
        _reason(connection, _tagged("finish previous assignment", batch_tag))
        for assignment_id in finished:
            connection.execute("UPDATE vinto_txn.assignment SET status = 'finished', finished_at = clock_timestamp() WHERE id = %s", (assignment_id,))
    _reason(connection, _tagged("activate assignment", batch_tag))
    new_id = connection.execute(
        """INSERT INTO vinto_txn.assignment (work_order_line_id, machine_id, shift_schedule_id, operating_date, assigned_by)
           VALUES (%s,%s,%s,%s,%s) RETURNING id""",
        (operational_line_id, target.machine_id, shift.shift_schedule_id, shift.operating_date, actor_id)).fetchone()[0]
    if settings.work_order_line_execution_enabled is True:
        from app.work_orders.line_execution import enable_from_activation
        enable_from_activation(
            connection, actor_id=actor_id, work_order_id=work_order_id,
            baseline_version_id=target.baseline_version_id, line_code=target.line_code,
            machine_id=target.machine_id, allow_create=True)
    if order_status == "published":
        connection.execute("UPDATE vinto_txn.work_order SET status = 'in_progress' WHERE id = %s", (work_order_id,))
    return ActivationResult(get_assignment(connection, new_id, sectors=sectors), created=True, already_active=False,
                            finished_assignment_id=finished[0] if len(finished) == 1 else None, finished_assignment_ids=tuple(finished))


def activate(connection, *, actor_id, work_order_id, baseline_line_id, request_id=None, sectors) -> ActivationResult:
    """Activa una línea (identificada por su línea BASE) en la máquina de ESA línea. Idempotente en el mismo turno y fecha."""
    work_order_id = _uuid(work_order_id, WorkOrderNotFoundError)
    baseline_line_id = _uuid(baseline_line_id, BaselineLineNotFoundError)
    request_id = request_id or f"assignment:{uuid.uuid4()}"
    with connection.transaction():
        _context(connection, actor_id, request_id, "create operational work order version")
        order_status, target = _load_target(connection, work_order_id=work_order_id, baseline_line_id=baseline_line_id, sectors=sectors)
        shift: ResolvedShift = resolve_shift(connection, _now(connection), sector_id=target.sector_id)  # antes de escribir: sin turno no hay nada que revertir
        return _activate_target(connection, actor_id=actor_id, work_order_id=work_order_id, order_status=order_status, target=target, shift=shift, sectors=sectors)


def finish(connection, *, actor_id, assignment_id, request_id=None, sectors) -> AssignmentView:
    """Finaliza una asignación activa. Si ya está finalizada no escribe nada (idempotente)."""
    assignment_id = _uuid(assignment_id, AssignmentNotFoundError)
    request_id = request_id or f"assignment:{uuid.uuid4()}"
    with connection.transaction():
        _context(connection, actor_id, request_id, "finish assignment")
        row = connection.execute(
            """SELECT a.machine_id FROM vinto_txn.assignment a JOIN vinto_master.machine m ON m.id = a.machine_id
               JOIN vinto_master.sector s ON s.id = m.sector_id WHERE a.id = %s AND s.code = ANY(%s)""",
            (assignment_id, list(scoped_sector_codes(sectors)))).fetchone()
        if row is None:
            raise AssignmentNotFoundError()
        _machine_lock(connection, row[0])  # mismo orden que activate: máquina -> asignación
        state = connection.execute("SELECT status FROM vinto_txn.assignment WHERE id = %s FOR UPDATE", (assignment_id,)).fetchone()
        if state is None:
            raise AssignmentNotFoundError()
        if state[0] == "active":
            from app.work_orders import handoff_guard
            handoff_guard.require_assignment_unreserved(
                connection, assignment_id=assignment_id)
            if settings.work_order_line_execution_enabled is True:
                from app.work_orders.line_execution import ExecutionStateConflictError
                producing = connection.execute(
                    """SELECT EXISTS (
                       SELECT 1 FROM vinto_txn.work_order_line_execution e
                       JOIN vinto_txn.work_order_line bl ON bl.id=e.baseline_line_id
                       JOIN vinto_txn.assignment a ON a.id=%s
                       JOIN vinto_txn.work_order_line ol ON ol.id=a.work_order_line_id
                       JOIN vinto_txn.work_order_version ov ON ov.id=ol.work_order_version_id
                       WHERE e.work_order_id=ov.work_order_id AND e.machine_id=a.machine_id
                         AND bl.line_code=ol.line_code AND e.status='in_production')""",
                    (assignment_id,)).fetchone()[0]
                if producing:
                    raise ExecutionStateConflictError(
                        "La línea está en producción; finalícela mediante el cierre lógico")
            connection.execute("UPDATE vinto_txn.assignment SET status = 'finished', finished_at = clock_timestamp() WHERE id = %s", (assignment_id,))
    return get_assignment(connection, assignment_id, sectors=sectors)


# ---------------------------------------------------------------------------------------------------
# queries
# ---------------------------------------------------------------------------------------------------

def list_assignments(connection, *, machine_code=None, status=None, operating_date=None, work_order_id=None, limit=DEFAULT_LIST_LIMIT, sectors,
                     machine_codes=None) -> list[AssignmentView]:
    """`machine_codes` (PR5): None = sin restricción por máquina (gestores); si no, SOLO esas máquinas, también con filtros por máquina/OT/fecha."""
    if status is not None and status not in ASSIGNMENT_STATUSES:
        raise InvalidAssignmentFilterError(f"status debe ser uno de {', '.join(ASSIGNMENT_STATUSES)}")
    sql, params = _VIEW_SQL, [list(scoped_sector_codes(sectors))]
    if machine_codes is not None:
        sql += " AND m.code = ANY(%s)"
        params.append(sorted(machine_codes))
    for clause, value in ((" AND m.code = %s", machine_code), (" AND a.status = %s", status), (" AND a.operating_date = %s", operating_date),
                          (" AND wo.id = %s", None if work_order_id is None else _uuid(work_order_id, WorkOrderNotFoundError))):
        if value is not None:
            sql += clause
            params.append(value)
    limit = max(1, min(int(limit), MAX_LIST_LIMIT))
    rows = connection.execute(sql + " ORDER BY a.created_at DESC, a.id DESC LIMIT %s", (*params, limit)).fetchall()
    return [_to_view(r) for r in rows]


def _active_items(connection, machine_code, sectors, machine_codes=None):
    """(items, turno actual o None) con TODAS las asignaciones activas de la máquina, antiguas primero. Con `machine_codes` (PR5) una máquina no autorizada
    se trata como fuera de alcance (misma respuesta que un sector no concedido): nunca se distingue «sin acceso» de «sin asignaciones»."""
    machine_id, _, sector_id = _machine_info(connection, machine_code, sectors)
    if machine_codes is not None and machine_code.strip() not in machine_codes:
        raise MachineOutsideScopeError()
    rows = connection.execute(_VIEW_SQL + " AND m.code = %s AND a.status = 'active' ORDER BY a.created_at, a.id", (list(scoped_sector_codes(sectors)), machine_code.strip())).fetchall()
    views = [_to_view(row) for row in rows]
    try:
        shift = resolve_shift(connection, _now(connection), sector_id=sector_id)
    except ShiftResolutionError:
        return tuple(ActiveItem(v, None) for v in views), None
    contexts = {row[0]: (row[1], row[2]) for row in connection.execute(
        "SELECT id, shift_schedule_id, operating_date FROM vinto_txn.assignment WHERE id = ANY(%s)", ([v.id for v in views],)).fetchall()}
    return tuple(ActiveItem(v, contexts[v.id] != (shift.shift_schedule_id, shift.operating_date)) for v in views), shift


def get_active(connection, *, machine_code, sectors, machine_codes=None) -> ActiveAssignment:
    """¿Qué OT/línea/producto tengo activo en esta máquina ahora? Incluye el turno actual y si la asignación quedó vencida.

    Contrato HISTÓRICO de una sola asignación. Con 2+ activas (varias líneas de la misma OT, solo con la compuerta multimáquina) no se
    elige una al azar ni se devuelve `null` (se leería como 'sin asignación'): 409 MULTIPLE_ACTIVE_ASSIGNMENTS. Las pantallas que necesiten
    varias líneas leen `get_active_lines` (GET /api/assignments/active-lines).
    """
    items, shift = _active_items(connection, machine_code, sectors, machine_codes)
    if len(items) > 1:
        raise MultipleActiveAssignmentsError()
    item = items[0] if items else None
    return ActiveAssignment(item.assignment if item else None, shift.shift_code if shift else None, shift.shift_name if shift else None,
                            shift.operating_date if shift else None, item.stale if item else None)


def get_active_lines(connection, *, machine_code, sectors, machine_codes=None) -> ActiveLines:
    """Contrato multilínea (PR5/PR8): TODAS las activas de la máquina con su 'vencida' y el turno actual. Sin selección implícita."""
    items, shift = _active_items(connection, machine_code, sectors, machine_codes)
    return ActiveLines(shift.shift_code if shift else None, shift.shift_name if shift else None, shift.operating_date if shift else None, items)


# ---------------------------------------------------------------------------------------------------
# bulk activation (PR4): preview + confirm of ALL lines of one work order in a single transaction
# ---------------------------------------------------------------------------------------------------

BULK_BATCH = "activate-all"
_PLAN_HASH = re.compile(r"^[a-f0-9]{64}$")


@dataclass(frozen=True)
class PlanLine:
    baseline_line_id: uuid.UUID
    line_code: str
    pv_reference: str
    article_code: str
    article_description: str
    machine_id: uuid.UUID
    machine_code: str
    machine_name: str
    sector_id: uuid.UUID
    baseline_version_id: uuid.UUID
    action: str  # activate | already_active | blocked
    reason: str | None  # código estable cuando action == blocked
    assignment_id: uuid.UUID | None  # asignación vigente (already_active)
    shift_code: str | None
    shift_name: str | None
    operating_date: date | None
    shift_schedule_id: uuid.UUID | None


@dataclass(frozen=True)
class PlanExpired:
    assignment_id: uuid.UUID
    machine_code: str
    machine_name: str
    line_code: str


@dataclass(frozen=True)
class PlanConflict:
    assignment_id: uuid.UUID
    machine_code: str
    machine_name: str
    work_order_id: uuid.UUID
    work_order_number: str
    line_code: str
    expired: bool | None


@dataclass(frozen=True)
class ActivationPlan:
    work_order_id: uuid.UUID
    number: str
    status: str
    lines: tuple[PlanLine, ...]
    expired: tuple[PlanExpired, ...]  # asignaciones vencidas de ESTA OT que la confirmación finalizará
    conflicts: tuple[PlanConflict, ...]  # asignaciones activas de OTRA OT: bloquean todo, nunca se finalizan
    plan_hash: str
    shifts: dict = field(compare=False, repr=False, default_factory=dict)

    @property
    def can_confirm(self) -> bool:
        return not self.conflicts and all(line.action != "blocked" for line in self.lines)

    @property
    def noop(self) -> bool:
        return self.can_confirm and not self.expired and all(line.action == "already_active" for line in self.lines)


@dataclass(frozen=True)
class BulkResult:
    plan: ActivationPlan
    outcome: str  # preview | applied | already_in_effect
    activated: tuple[AssignmentView, ...] = ()
    already_active: tuple[AssignmentView, ...] = ()
    finished: tuple[AssignmentView, ...] = ()


def _require_bulk_enabled():
    if not _multi_machine_enabled():
        raise MultiMachineDisabledError()


def _digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _plan_hash(work_order_id, lines, expired, conflicts, reprogram_version=None) -> str:
    """Retain all legacy hashes; a revised published OT binds confirmation to the CURRENT version."""
    state_data = {"v": 1, "work_order": str(work_order_id), "lines": [
        [str(l.baseline_line_id), str(l.machine_id), None if l.shift_schedule_id is None else str(l.shift_schedule_id),
         None if l.operating_date is None else l.operating_date.isoformat()] for l in lines]}
    if reprogram_version is not None:
        state_data["reprogram_version"] = reprogram_version
    state = _digest(state_data)
    actions = _digest({"v": 1, "lines": [[str(l.baseline_line_id), l.action, l.reason, None if l.assignment_id is None else str(l.assignment_id)] for l in lines],
                       "expired": sorted(str(e.assignment_id) for e in expired), "conflicts": sorted(str(c.assignment_id) for c in conflicts)})
    return state[:32] + actions[:32]


def _build_plan(connection, *, work_order_id, sectors, now, lock) -> ActivationPlan:
    """Calcula el plan completo. Con `lock` toma OT -> máquinas (por id) -> asignaciones, en ese orden; sin él es solo lectura.

    404 si la OT no existe o ALGUNA de sus máquinas (cabecera o líneas) queda fuera del alcance: nunca un resultado parcialmente autorizado.
    """
    order = connection.execute(
        "SELECT wo.number, wo.status, hs.code FROM vinto_txn.work_order wo JOIN vinto_master.machine hm ON hm.id = wo.machine_id "
        "JOIN vinto_master.sector hs ON hs.id = hm.sector_id WHERE wo.id = %s" + (" FOR UPDATE OF wo" if lock else ""), (work_order_id,)).fetchone()
    codes = set(scoped_sector_codes(sectors))
    if order is None or order[2] not in codes:
        raise WorkOrderNotFoundError()
    number, status, _ = order
    rows = connection.execute(
        """SELECT l.id, l.line_code, l.pv_reference, v.id, l.machine_id, m.code, m.name, m.active, s.id, s.code, ar.code, av.description
           FROM vinto_txn.work_order_line l JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
           JOIN vinto_master.machine m ON m.id = l.machine_id JOIN vinto_master.sector s ON s.id = m.sector_id
           JOIN vinto_master.article_version av ON av.id = l.article_version_id JOIN vinto_master.article ar ON ar.id = av.article_id
           WHERE v.work_order_id = %s AND v.kind = 'baseline' AND v.version_number = 1 AND v.published_at IS NOT NULL
           ORDER BY length(l.line_code), l.line_code""", (work_order_id,)).fetchall()
    if any(row[9] not in codes for row in rows):
        raise WorkOrderNotFoundError()
    if status not in ("published", "in_progress") or not rows:
        raise WorkOrderNotActivatableError(f"La orden está en estado {status}")
    machine_ids = sorted({row[4] for row in rows}, key=str)
    if lock:
        _lock_machines(connection, machine_ids)
    actives = connection.execute(
        """SELECT a.id, a.machine_id, a.work_order_line_id, a.shift_schedule_id, a.operating_date, v.work_order_id, wo.number, l.line_code
           FROM vinto_txn.assignment a JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
           JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id JOIN vinto_txn.work_order wo ON wo.id = v.work_order_id
           WHERE a.machine_id = ANY(%s) AND a.status = 'active' ORDER BY a.id""" + (" FOR UPDATE OF a" if lock else ""), (machine_ids,)).fetchall()
    operational_rows = connection.execute(
        """SELECT l.line_code, l.id, l.pv_reference, ar.code, av.description,
                  v.version_number, v.reprogram_reason
           FROM vinto_txn.work_order_line l
           JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
           JOIN vinto_master.article_version av ON av.id=l.article_version_id
           JOIN vinto_master.article ar ON ar.id=av.article_id
           WHERE v.id = (SELECT id FROM vinto_txn.work_order_version WHERE work_order_id = %s AND kind = 'operational' AND published_at IS NOT NULL
                         ORDER BY version_number DESC LIMIT 1)""", (work_order_id,)).fetchall()
    operational = {item[0]: item[1] for item in operational_rows}
    current_program = {item[0]: item for item in operational_rows}
    reprogram_version = next((item[5] for item in operational_rows if item[6] is not None), None)
    if reprogram_version is not None and set(current_program) != {item[1] for item in rows}:
        raise OperationalVersionError("La programación vigente no contiene las líneas de la base")
    shifts = {}
    for sector_id in {row[8] for row in rows}:
        try:
            shifts[sector_id] = resolve_shift(connection, now, sector_id=sector_id)
        except ShiftResolutionError as error:
            shifts[sector_id] = error.code
    machine_info = {row[4]: (row[5], row[6]) for row in rows}
    lines, expired, conflicts, busy = [], [], [], set()
    for a_id, machine_id, _, schedule_id, op_date, owner_id, owner_number, line_code in actives:
        shift = shifts.get(next(r[8] for r in rows if r[4] == machine_id))
        current = (schedule_id, op_date) == (shift.shift_schedule_id, shift.operating_date) if isinstance(shift, ResolvedShift) else None
        if owner_id != work_order_id:
            busy.add(machine_id)
            conflicts.append(PlanConflict(a_id, *machine_info[machine_id], owner_id, owner_number, line_code, None if current is None else not current))
        elif current is False:
            expired.append(PlanExpired(a_id, *machine_info[machine_id], line_code))
    for l_id, line_code, pv, version_id, machine_id, m_code, m_name, m_active, sector_id, _, a_code, a_desc in rows:
        if reprogram_version is not None:
            source_line = current_program[line_code]
            pv, a_code, a_desc = source_line[2], source_line[3], source_line[4]
        shift = shifts[sector_id]
        resolved = isinstance(shift, ResolvedShift)
        existing = None
        if resolved and operational.get(line_code) is not None:
            existing = next((a[0] for a in actives if a[2] == operational[line_code] and (a[3], a[4]) == (shift.shift_schedule_id, shift.operating_date)), None)
        if not m_active:
            action, reason = "blocked", "MACHINE_INACTIVE"
        elif not resolved:
            action, reason = "blocked", shift
        elif machine_id in busy:
            action, reason = "blocked", "MACHINE_ACTIVE_WITH_OTHER_WORK_ORDER"
        elif existing is not None:
            action, reason = "already_active", None
        else:
            action, reason = "activate", None
        lines.append(PlanLine(l_id, line_code, pv, a_code, a_desc, machine_id, m_code, m_name, sector_id, version_id, action, reason, existing,
                              shift.shift_code if resolved else None, shift.shift_name if resolved else None,
                              shift.operating_date if resolved else None, shift.shift_schedule_id if resolved else None))
    return ActivationPlan(work_order_id, number, status, tuple(lines), tuple(expired), tuple(conflicts),
                          _plan_hash(work_order_id, lines, expired, conflicts, reprogram_version), shifts)


def preview_activate_all(connection, *, work_order_id, sectors) -> BulkResult:
    """Vista previa: transacción REPEATABLE READ y READ ONLY (PostgreSQL rechaza cualquier escritura): sin versión operativa, sin
    asignaciones, sin auditoría de negocio, sin bloqueos de fila."""
    _require_bulk_enabled()
    work_order_id = _uuid(work_order_id, WorkOrderNotFoundError)
    with connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
        plan = _build_plan(connection, work_order_id=work_order_id, sectors=sectors, now=_now(connection), lock=False)
    return BulkResult(plan, "preview")


def _views(connection, ids, sectors):
    return tuple(get_assignment(connection, i, sectors=sectors) for i in ids)


def activate_all(connection, *, actor_id, work_order_id, plan_hash, request_id=None, sectors) -> BulkResult:
    """Confirma el plan aprobado: TODO O NADA en una sola transacción.

    Recalcula bajo bloqueo y compara con `plan_hash`:
    - mismo estado final y mismas acciones -> aplica;
    - mismo estado final y nada que hacer (reintento tras una respuesta perdida, o ya activas) -> `already_in_effect`, sin escribir;
    - cualquier otra diferencia (turno/fecha, máquinas, acciones, conflictos nuevos) -> 409 ACTIVATION_PLAN_CHANGED sin escribir;
    - plan con bloqueos -> 409 ACTIVATION_BLOCKED sin escribir.
    """
    _require_bulk_enabled()
    work_order_id = _uuid(work_order_id, WorkOrderNotFoundError)
    request_id = request_id or f"assignment:{uuid.uuid4()}"
    if not isinstance(plan_hash, str) or not _PLAN_HASH.fullmatch(plan_hash):
        raise ActivationPlanChangedError()
    with connection.transaction():
        _context(connection, actor_id, request_id, "create operational work order version")
        plan = _build_plan(connection, work_order_id=work_order_id, sectors=sectors, now=_now(connection), lock=True)
        if plan.plan_hash[:32] != plan_hash[:32]:
            raise ActivationPlanChangedError()
        if plan.plan_hash != plan_hash and not plan.noop:
            raise ActivationPlanChangedError()
        if not plan.can_confirm:
            raise ActivationBlockedError()
        if plan.noop:
            return BulkResult(plan, "already_in_effect", already_active=_views(connection, [l.assignment_id for l in plan.lines], sectors))
        tag = f"{BULK_BATCH} {plan_hash}"
        created, finished = [], []
        for line in plan.lines:
            if line.action != "activate":
                continue
            order_status, target = _load_target(connection, work_order_id=work_order_id, baseline_line_id=line.baseline_line_id, sectors=sectors)
            result = _activate_target(connection, actor_id=actor_id, work_order_id=work_order_id, order_status=order_status, target=target,
                                      shift=plan.shifts[line.sector_id], sectors=sectors, batch_tag=tag)
            if not result.created:
                raise ActivationPlanChangedError()  # imposible bajo los bloqueos; si ocurriera, se revierte todo
            created.append(result.assignment.id)
            finished.extend(result.finished_assignment_ids)
        if set(finished) != {e.assignment_id for e in plan.expired}:
            raise ActivationPlanChangedError()  # se finalizó algo distinto de lo aprobado: se revierte todo
        return BulkResult(plan, "applied", activated=_views(connection, created, sectors),
                          already_active=_views(connection, [l.assignment_id for l in plan.lines if l.action == "already_active"], sectors),
                          finished=_views(connection, finished, sectors))


@dataclass(frozen=True)
class OperationalLine:
    assignment: AssignmentView
    stale: bool | None  # None cuando no se puede resolver el turno de su sector
    shift_code: str | None  # turno ACTUAL del sector de la máquina
    shift_name: str | None
    operating_date: date | None


def list_operational_lines(connection, *, sectors, machine_codes=None) -> list[OperationalLine]:
    """Contrato operativo (PR5/PR8): TODAS las asignaciones activas de las máquinas autorizadas, de varias máquinas, sin elegir ninguna.

    `machine_codes` None = gestores (alcance por sector); un conjunto = solo esas máquinas (vacío = ninguna). Cada línea trae su `assignment` completo (id inequívoco),
    si está vencida y el turno vigente de su sector; solo una línea NO vencida admite captura. Orden estable: máquina, antigüedad, id."""
    sql, params = _VIEW_SQL + " AND a.status = 'active'", [list(scoped_sector_codes(sectors))]
    if machine_codes is not None:
        sql += " AND m.code = ANY(%s)"
        params.append(sorted(machine_codes))
    views = [_to_view(row) for row in connection.execute(sql + " ORDER BY m.code, a.created_at, a.id", params).fetchall()]
    if not views:
        return []
    contexts = {row[0]: row[1:] for row in connection.execute(
        """SELECT a.id, a.shift_schedule_id, a.operating_date, m.sector_id FROM vinto_txn.assignment a JOIN vinto_master.machine m ON m.id = a.machine_id
           WHERE a.id = ANY(%s)""", ([v.id for v in views],)).fetchall()}
    now, shifts = _now(connection), {}
    for schedule_id, operating_date, sector_id in contexts.values():
        if sector_id not in shifts:
            try:
                shifts[sector_id] = resolve_shift(connection, now, sector_id=sector_id)
            except ShiftResolutionError:
                shifts[sector_id] = None
    lines = []
    for view in views:
        schedule_id, operating_date, sector_id = contexts[view.id]
        shift = shifts[sector_id]
        lines.append(OperationalLine(view, None if shift is None else (schedule_id, operating_date) != (shift.shift_schedule_id, shift.operating_date),
                                     None if shift is None else shift.shift_code, None if shift is None else shift.shift_name, None if shift is None else shift.operating_date))
    return lines
