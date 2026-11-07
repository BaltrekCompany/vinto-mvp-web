"""E1-03: lifecycle of a logical work-order line (not the shift assignment).

Feature flag WORK_ORDER_LINE_EXECUTION_ENABLED defaults OFF. Never turn it on
until E1-04 captures and E1-05/06 interfaces are integrated and tested.
Lock order: work_order FOR UPDATE -> machine advisory -> assignment/execution.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.assignments import service as assignments
from app.config import settings
from app.sectors import scoped_sector_codes
from app.shifts import ShiftResolutionError, resolve_shift
from app.work_orders.errors import WorkOrderError, WorkOrderNotFoundError


class ExecutionDisabledError(WorkOrderError):
    http_status, code, public_message = 422, "LINE_EXECUTION_DISABLED", "El inicio y cierre de líneas no está habilitado"


class ExecutionNotReadyError(WorkOrderError):
    http_status, code, public_message = 409, "LINE_EXECUTION_NOT_READY", "La línea requiere habilitación o revisión de Supervisión"


class ExecutionStateConflictError(WorkOrderError):
    http_status, code, public_message = 409, "LINE_EXECUTION_CONFLICT", "La línea no admite la operación en su estado actual"


class ExecutionMachineBusyError(WorkOrderError):
    http_status, code, public_message = 409, "LINE_MACHINE_IN_PRODUCTION", "La máquina ya tiene una línea en producción"


class ExecutionAssignmentError(WorkOrderError):
    http_status, code, public_message = 409, "LINE_ASSIGNMENT_INVALID", "La asignación de la línea no está vigente"


@dataclass(frozen=True)
class ExecutionView:
    baseline_line_id: uuid.UUID
    work_order_id: uuid.UUID
    line_code: str
    machine_code: str
    status: str
    started_at: datetime | None
    started_by: uuid.UUID | None
    finished_at: datetime | None
    finished_by: uuid.UUID | None


def enabled() -> bool:
    return settings.work_order_line_execution_enabled is True


def require_enabled() -> None:
    if not enabled():
        raise ExecutionDisabledError()


def _uuid(value):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise WorkOrderNotFoundError() from None


def _context(connection, actor_id, reason, request_id=None):
    connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor_id),))
    connection.execute("SELECT set_config('vinto.request_id', %s, true)", (request_id or str(uuid.uuid4()),))
    connection.execute("SELECT set_config('vinto.reason', %s, true)", (reason,))


def _target(connection, work_order_id, line_code, sectors):
    """OT already locked by caller; do not leak a line of another sector."""
    if not isinstance(line_code, str) or not line_code.strip():
        raise WorkOrderNotFoundError()
    row = connection.execute(
        """SELECT l.id, l.machine_id, m.code, s.id, wo.status, m.active
           FROM vinto_txn.work_order wo
           JOIN vinto_txn.work_order_version v ON v.work_order_id = wo.id
             AND v.kind = 'baseline' AND v.version_number = 1 AND v.published_at IS NOT NULL
           JOIN vinto_txn.work_order_line l ON l.work_order_version_id = v.id
           JOIN vinto_master.machine m ON m.id = l.machine_id
           JOIN vinto_master.sector s ON s.id = m.sector_id
           WHERE wo.id = %s AND l.line_code = %s AND s.code = ANY(%s)""",
        (work_order_id, line_code.strip(), list(scoped_sector_codes(sectors)))).fetchone()
    if row is None:
        raise WorkOrderNotFoundError()
    return row


def _view(connection, baseline_line_id):
    row = connection.execute(
        """SELECT e.baseline_line_id, e.work_order_id, l.line_code, m.code,
                  e.status, e.started_at, e.started_by, e.finished_at, e.finished_by
           FROM vinto_txn.work_order_line_execution e
           JOIN vinto_txn.work_order_line l ON l.id = e.baseline_line_id
           JOIN vinto_master.machine m ON m.id = e.machine_id
           WHERE e.baseline_line_id = %s""", (baseline_line_id,)).fetchone()
    if row is None:
        raise ExecutionNotReadyError()
    return ExecutionView(*row)


def enable_from_activation(connection, *, actor_id, work_order_id, baseline_version_id,
                           line_code, machine_id, allow_create):
    """Called only inside the existing activate transaction, AFTER machine lock.

    For a newly created assignment: insert planned and then enable it.
    For a historical already-active assignment without a logical state: fail
    closed. Supervisor must reconcile the legacy record; never invent a start.
    """
    if not enabled():
        return
    row = connection.execute(
        """SELECT id FROM vinto_txn.work_order_line
           WHERE work_order_version_id = %s AND line_code = %s AND machine_id = %s""",
        (baseline_version_id, line_code, machine_id)).fetchone()
    if row is None:
        raise ExecutionNotReadyError()
    baseline_line_id = row[0]
    current = connection.execute(
        "SELECT status FROM vinto_txn.work_order_line_execution WHERE baseline_line_id = %s FOR UPDATE",
        (baseline_line_id,)).fetchone()
    if current is None:
        if not allow_create:
            raise ExecutionNotReadyError()
        connection.execute(
            """INSERT INTO vinto_txn.work_order_line_execution
               (baseline_line_id, work_order_id, machine_id) VALUES (%s,%s,%s)""",
            (baseline_line_id, work_order_id, machine_id))
        current = ("planned",)
    if current[0] == "planned":
        connection.execute(
            """UPDATE vinto_txn.work_order_line_execution SET status='enabled'
               WHERE baseline_line_id=%s""", (baseline_line_id,))
    elif current[0] == "finished":
        raise ExecutionStateConflictError()
    # enabled and in_production are idempotent; in_production can cross a
    # shift boundary only with a fresh, valid assignment. D1 is still pending.


def start_line(connection, *, actor_id, work_order_id, line_code, assignment_id,
               sectors, request_id=None):
    require_enabled()
    work_order_id, assignment_id = _uuid(work_order_id), _uuid(assignment_id)
    with connection.transaction():
        _context(connection, actor_id, "start logical work order line", request_id)
        head = connection.execute(
            "SELECT status FROM vinto_txn.work_order WHERE id=%s FOR UPDATE", (work_order_id,)).fetchone()
        if head is None:
            raise WorkOrderNotFoundError()
        baseline_id, machine_id, _, sector_id, order_status, active = _target(
            connection, work_order_id, line_code, sectors)
        if order_status != "in_progress" or not active:
            raise ExecutionStateConflictError()
        assignments._machine_lock(connection, machine_id)
        assignment = connection.execute(
            """SELECT a.status, a.shift_schedule_id, a.operating_date
               FROM vinto_txn.assignment a
               JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
               JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
               WHERE a.id=%s AND v.work_order_id=%s AND v.kind='operational'
                 AND l.line_code=%s AND a.machine_id=%s FOR UPDATE OF a""",
            (assignment_id, work_order_id, line_code, machine_id)).fetchone()
        if assignment is None or assignment[0] != "active":
            raise ExecutionAssignmentError()
        shift = resolve_shift(connection, assignments._now(connection), sector_id=sector_id)
        if (assignment[1], assignment[2]) != (shift.shift_schedule_id, shift.operating_date):
            raise ExecutionAssignmentError()
        state = connection.execute(
            "SELECT status FROM vinto_txn.work_order_line_execution WHERE baseline_line_id=%s FOR UPDATE",
            (baseline_id,)).fetchone()
        if state is None or state[0] == "planned":
            raise ExecutionNotReadyError()
        if state[0] == "in_production":
            return _view(connection, baseline_id)
        if state[0] != "enabled":
            raise ExecutionStateConflictError()
        busy = connection.execute(
            """SELECT EXISTS (SELECT 1 FROM vinto_txn.work_order_line_execution
               WHERE machine_id=%s AND status='in_production' AND baseline_line_id<>%s)""",
            (machine_id, baseline_id)).fetchone()[0]
        if busy:
            raise ExecutionMachineBusyError()
        connection.execute(
            """UPDATE vinto_txn.work_order_line_execution
               SET status='in_production', started_at=clock_timestamp(), started_by=%s
               WHERE baseline_line_id=%s""", (actor_id, baseline_id))
        return _view(connection, baseline_id)


def finish_line(connection, *, actor_id, work_order_id, line_code, sectors, request_id=None):
    require_enabled()
    work_order_id = _uuid(work_order_id)
    with connection.transaction():
        _context(connection, actor_id, "finish logical work order line", request_id)
        head = connection.execute(
            "SELECT status FROM vinto_txn.work_order WHERE id=%s FOR UPDATE", (work_order_id,)).fetchone()
        if head is None:
            raise WorkOrderNotFoundError()
        baseline_id, machine_id, _, _, _, _ = _target(connection, work_order_id, line_code, sectors)
        assignments._machine_lock(connection, machine_id)
        state = connection.execute(
            "SELECT status FROM vinto_txn.work_order_line_execution WHERE baseline_line_id=%s FOR UPDATE",
            (baseline_id,)).fetchone()
        if state is None:
            raise ExecutionNotReadyError()
        if state[0] == "finished":
            return _view(connection, baseline_id)  # idempotent, no writes
        if state[0] != "in_production":
            raise ExecutionStateConflictError()
        connection.execute(
            """UPDATE vinto_txn.work_order_line_execution
               SET status='finished', finished_at=clock_timestamp(), finished_by=%s
               WHERE baseline_line_id=%s""", (actor_id, baseline_id))
        # Closing logical line also ends current/expired shift assignment rows
        # for THIS line only. Other enabled lines on the same machine are intact.
        connection.execute(
            """UPDATE vinto_txn.assignment a
               SET status='finished', finished_at=clock_timestamp()
               FROM vinto_txn.work_order_line l
               JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
               WHERE a.work_order_line_id=l.id
                 AND v.kind='operational' AND v.work_order_id=%s
                 AND l.line_code=%s AND a.machine_id=%s AND a.status='active'""",
            (work_order_id, line_code, machine_id))
        return _view(connection, baseline_id)


def read_work_order_execution(connection, *, work_order_id, sectors):
    """Read-only Supervisor projection. Never infer production from assignment.active.

    Full baseline scope is required, even for multi-machine orders; a partial
    projection could expose machine information outside the actor's sectors.
    Only a current assignment for the same OT, line and machine enables Start.
    An old active assignment without a logical execution row is 'requires_review'.
    """
    require_enabled()
    work_order_id = _uuid(work_order_id)
    lines = connection.execute(
        """SELECT l.id, l.line_code, l.machine_id, m.code, s.id, s.code,
                  e.status, e.started_at, e.started_by, e.finished_at, e.finished_by
           FROM vinto_txn.work_order wo
           JOIN vinto_txn.work_order_version bv ON bv.work_order_id = wo.id
             AND bv.kind='baseline' AND bv.version_number=1 AND bv.published_at IS NOT NULL
           JOIN vinto_txn.work_order_line l ON l.work_order_version_id=bv.id
           JOIN vinto_master.machine m ON m.id=l.machine_id
           JOIN vinto_master.sector s ON s.id=m.sector_id
           LEFT JOIN vinto_txn.work_order_line_execution e ON e.baseline_line_id=l.id
           WHERE wo.id=%s AND wo.status IN ('published','in_progress')
             AND wo.archived_at IS NULL
           ORDER BY l.line_code, l.id""", (work_order_id,)).fetchall()
    allowed = set(scoped_sector_codes(sectors))
    if not lines or any(r[5] not in allowed for r in lines):
        raise WorkOrderNotFoundError()
    active = connection.execute(
        """SELECT a.id, l.line_code, a.machine_id, a.shift_schedule_id, a.operating_date
           FROM vinto_txn.assignment a
           JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
           JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
           WHERE v.work_order_id=%s AND v.kind='operational' AND a.status='active'
           ORDER BY a.created_at, a.id""", (work_order_id,)).fetchall()
    active_by_line = {}
    for entry in active:
        active_by_line.setdefault((entry[1], entry[2]), []).append(entry)
    now = assignments._now(connection)  # PostgreSQL clock in production; same instant source as start_line
    shifts = {}
    for row in lines:
        sector_id = row[4]
        if sector_id not in shifts:
            try:
                shifts[sector_id] = resolve_shift(connection, now, sector_id=sector_id)
            except ShiftResolutionError:
                shifts[sector_id] = None
    result = []
    for line in lines:
        baseline_id, code, machine_id, machine_code, sector_id = line[:5]
        candidates = active_by_line.get((code, machine_id), [])
        shift = shifts[sector_id]
        valid = [a for a in candidates if shift is not None
                 and (a[3], a[4]) == (shift.shift_schedule_id, shift.operating_date)]
        current_assignment = valid[0][0] if len(valid) == 1 else None
        # Missing execution + stale/live assignment needs supervisor reconciliation,
        # never an implicit promotion or a fabricated Start button.
        status = line[6] if line[6] is not None else ("requires_review" if candidates else "planned")
        result.append({
            "baseline_line_id": baseline_id, "line_code": code,
            "machine_code": machine_code, "status": status,
            "current_assignment_id": current_assignment,
            "started_at": line[7], "started_by": line[8],
            "finished_at": line[9], "finished_by": line[10],
        })
    return {"work_order_id": work_order_id, "lines": result}
