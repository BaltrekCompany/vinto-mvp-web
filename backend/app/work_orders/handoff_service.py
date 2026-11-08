"""E2-D2-B1.1: supervised reserve/cancel of a never-started enabled line.

No change to work-order versions or assignments. The reservation is the
persistent barrier installed by B0. D2 remains OFF on every deployed server
until the complete B1/B2 handoff flow is implemented and separately approved.
"""
import re
import uuid

from app.assignments import service as assignments
from app.config import settings
from app.shifts import resolve_shift
from app.work_orders import handoff_guard, service
from app.work_orders.errors import (
    WorkOrderNotFoundError, WorkOrderHandoffPendingError,
    WorkOrderHandoffDisabledError, WorkOrderHandoffBlockedError,
    WorkOrderHandoffChangedError,
)

_LINE = re.compile(r"^L[1-9][0-9]*$")


def _validate(reason, version):
    if settings.work_order_reprogram_handoff_enabled is not True:
        raise WorkOrderHandoffDisabledError()
    if settings.work_order_line_execution_enabled is not True:
        raise WorkOrderHandoffBlockedError()
    if not isinstance(reason, str) or not 10 <= len(reason.strip()) <= 300:
        raise WorkOrderHandoffBlockedError()
    if version is not None and (isinstance(version, bool) or
                                not isinstance(version, int) or version < 2):
        raise WorkOrderHandoffBlockedError()
    return reason.strip()


def _result(row):
    return {
        "handoff_id": row[0], "work_order_id": row[1],
        "line_code": row[2], "prior_assignment_id": row[3],
        "expected_version": row[4], "status": row[5],
        "requested_by": row[6], "created_at": row[7],
        "completed_at": row[8],
    }


_RESULT = """
 SELECT h.id, h.work_order_id, bl.line_code, h.prior_assignment_id,
        h.expected_version_number, h.status, h.requested_by,
        h.created_at, h.completed_at
 FROM vinto_txn.work_order_line_reprogram_handoff h
 JOIN vinto_txn.work_order_line bl ON bl.id=h.baseline_line_id
 WHERE h.id=%s
"""


def reserve(connection, *, actor_id, work_order_id, line_code,
            assignment_id, expected_version, reason, sectors,
            request_id=None):
    """Atomic OT -> machine -> active assignment -> E1 -> handoff insert."""
    reason = _validate(reason, expected_version)
    work_order_id = service._as_uuid(work_order_id)
    if not isinstance(line_code, str) or not _LINE.fullmatch(line_code):
        raise WorkOrderNotFoundError()
    try:
        assignment_id = uuid.UUID(str(assignment_id))
    except (TypeError, ValueError, AttributeError):
        raise WorkOrderHandoffBlockedError() from None

    with connection.transaction():
        service._context(connection, actor_id, request_id,
                         "E2-D2 supervised reserve: " + reason)
        status, _, baseline_version_id, baseline_published = service._lock_baseline(
            connection, work_order_id, sectors)
        if status != "in_progress" or baseline_published is None:
            raise WorkOrderHandoffBlockedError()
        row = connection.execute(
            """SELECT l.id, l.machine_id, m.sector_id, m.active
               FROM vinto_txn.work_order_line l
               JOIN vinto_master.machine m ON m.id=l.machine_id
               WHERE l.work_order_version_id=%s AND l.line_code=%s""",
            (baseline_version_id, line_code)).fetchone()
        if row is None:
            raise WorkOrderNotFoundError()
        baseline_line_id, machine_id, sector_id, machine_active = row
        if not machine_active:
            raise WorkOrderHandoffBlockedError()

        # MUST take machine lock before any assignment or E1 row lock:
        # capture F3/F6 use machine -> assignment and never lock OT first.
        assignments._machine_lock(connection, machine_id)
        handoff_guard.require_line_unreserved(
            connection, work_order_id=work_order_id, line_code=line_code)

        prior = connection.execute(
            """SELECT a.status, a.machine_id, a.shift_schedule_id,
                      a.operating_date, v.work_order_id, v.kind, l.line_code
               FROM vinto_txn.assignment a
               JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
               JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
               WHERE a.id=%s FOR UPDATE OF a""",
            (assignment_id,)).fetchone()
        if (prior is None or prior[0] != "active" or
            prior[1] != machine_id or prior[4] != work_order_id or
            prior[5] != "operational" or prior[6] != line_code):
            raise WorkOrderHandoffBlockedError()

        shift = resolve_shift(connection, assignments._now(connection),
                              sector_id=sector_id)
        if (prior[2], prior[3]) != (shift.shift_schedule_id, shift.operating_date):
            raise WorkOrderHandoffBlockedError()

        execution = connection.execute(
            """SELECT status, started_at, finished_at
               FROM vinto_txn.work_order_line_execution
               WHERE baseline_line_id=%s FOR UPDATE""",
            (baseline_line_id,)).fetchone()
        if execution is None or execution != ("enabled", None, None):
            raise WorkOrderHandoffBlockedError()

        source = connection.execute(
            """SELECT id, version_number
               FROM vinto_txn.work_order_version
               WHERE work_order_id=%s AND kind='operational'
                 AND published_at IS NOT NULL
               ORDER BY version_number DESC LIMIT 1""",
            (work_order_id,)).fetchone()
        if source is None or source[1] != expected_version:
            raise WorkOrderHandoffChangedError()

        current_line = connection.execute(
            """SELECT 1
               FROM vinto_txn.work_order_line l
               WHERE l.work_order_version_id=%s AND l.line_code=%s
                 AND l.machine_id=%s""",
            (source[0], line_code, machine_id)).fetchone()
        if current_line is None:
            raise WorkOrderHandoffChangedError()

        history = connection.execute(
            """SELECT EXISTS (
                SELECT 1 FROM vinto_txn.capture c
                JOIN vinto_txn.assignment ca ON ca.id=c.assignment_id
                JOIN vinto_txn.work_order_line cl ON cl.id=ca.work_order_line_id
                JOIN vinto_txn.work_order_version cv ON cv.id=cl.work_order_version_id
                WHERE cv.work_order_id=%s AND cl.line_code=%s
               )""", (work_order_id, line_code)).fetchone()[0]
        if history:
            raise WorkOrderHandoffBlockedError()

        reservation = connection.execute(
            """INSERT INTO vinto_txn.work_order_line_reprogram_handoff
               (work_order_id,baseline_line_id,machine_id,
                prior_assignment_id,expected_version_number,
                requested_by,reason)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               RETURNING id""",
            (work_order_id, baseline_line_id, machine_id,
             assignment_id, expected_version, actor_id, reason)).fetchone()[0]
        result = _result(connection.execute(_RESULT, (reservation,)).fetchone())

    return result


def cancel(connection, *, actor_id, handoff_id, reason, sectors,
           request_id=None):
    """Cancel only pending reservation. No finishing, reassignment, or OT edit."""
    reason = _validate(reason, None)
    try:
        handoff_id = uuid.UUID(str(handoff_id))
    except (TypeError, ValueError, AttributeError):
        raise WorkOrderNotFoundError() from None

    with connection.transaction():
        service._context(connection, actor_id, request_id,
                         "E2-D2 supervised cancel: " + reason)
        locator = connection.execute(
            """SELECT work_order_id, machine_id, baseline_line_id
               FROM vinto_txn.work_order_line_reprogram_handoff
               WHERE id=%s""", (handoff_id,)).fetchone()
        if locator is None:
            raise WorkOrderNotFoundError()
        work_order_id, machine_id, baseline_line_id = locator
        # Scope must include every sector in the OT (no partial read/leak).
        service._lock_baseline(connection, work_order_id, sectors)
        assignments._machine_lock(connection, machine_id)

        state = connection.execute(
            """SELECT status, work_order_id, machine_id, baseline_line_id
               FROM vinto_txn.work_order_line_reprogram_handoff
               WHERE id=%s FOR UPDATE""", (handoff_id,)).fetchone()
        if state is None or state[1:] != locator:
            raise WorkOrderHandoffChangedError()
        if state[0] == "cancelled":
            return _result(connection.execute(_RESULT, (handoff_id,)).fetchone())
        if state[0] != "pending":
            raise WorkOrderHandoffBlockedError()

        connection.execute(
            """UPDATE vinto_txn.work_order_line_reprogram_handoff
               SET status='cancelled', completed_at=clock_timestamp()
               WHERE id=%s AND status='pending'""", (handoff_id,))
        result = _result(connection.execute(_RESULT, (handoff_id,)).fetchone())
    return result
