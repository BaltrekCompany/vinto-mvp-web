"""E2-D2-B1.2: publish a reserved line, then explicitly reassign.

Both actions are atomic and preserve old snapshots and assignment pointers.
The B0 guard stays effective throughout (pending/published/reassigned); B2
must add the operator acknowledgement gate before enabling this flag.
"""
import uuid

from app.assignments import service as assignments
from app.config import settings
from app.shifts import resolve_shift
from app.work_orders import service
from app.work_orders.errors import (
    InvalidWorkOrderLineError, WorkOrderNotFoundError,
    WorkOrderHandoffDisabledError, WorkOrderHandoffBlockedError,
    WorkOrderHandoffChangedError,
)


def _require(*, allow_existing_recovery=False):
    # Existing published handoffs may be completed under flag OFF, but
    # creating a NEW operational revision while OFF remains forbidden.
    if (not allow_existing_recovery and
            settings.work_order_reprogram_handoff_enabled is not True):
        raise WorkOrderHandoffDisabledError()
    if settings.work_order_line_execution_enabled is not True:
        raise WorkOrderHandoffBlockedError()


def _load_locked(connection, *, handoff_id, actor_id, sectors, request_id, reason):
    """OT -> machine -> assignment -> E1 -> handoff; no lock reversal.

    Called inside an explicit transaction by both B1.2 paths. Even a
    locator query is rechecked after locks, preventing stale read/cross-OT.
    """
    try:
        handoff_id = uuid.UUID(str(handoff_id))
    except (ValueError, TypeError, AttributeError):
        raise WorkOrderNotFoundError() from None
    locator = connection.execute(
        """SELECT work_order_id, machine_id, prior_assignment_id,
                  baseline_line_id
           FROM vinto_txn.work_order_line_reprogram_handoff WHERE id=%s""",
        (handoff_id,)).fetchone()
    if locator is None:
        raise WorkOrderNotFoundError()
    work_order_id, machine_id, assignment_id, baseline_line_id = locator
    state, _, baseline_version_id, published_at = service._lock_baseline(
        connection, work_order_id, sectors)
    if state != "in_progress" or published_at is None:
        raise WorkOrderHandoffBlockedError()
    order = connection.execute(
        "SELECT qa_retired FROM vinto_txn.work_order WHERE id=%s",
        (work_order_id,)).fetchone()
    if order is None or order[0]:
        raise WorkOrderHandoffBlockedError()
    assignments._machine_lock(connection, machine_id)
    prior = connection.execute(
        """SELECT a.status, a.machine_id, a.shift_schedule_id,
                  a.operating_date, l.line_code, v.work_order_id,
                  l.machine_id, v.kind
           FROM vinto_txn.assignment a
           JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
           JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
           WHERE a.id=%s FOR UPDATE OF a""",
        (assignment_id,)).fetchone()
    line = connection.execute(
        """SELECT id, line_code, machine_id
           FROM vinto_txn.work_order_line
           WHERE id=%s AND work_order_version_id=%s""",
        (baseline_line_id, baseline_version_id)).fetchone()
    if (prior is None or prior[0] not in ("active", "finished")
        or prior[1] != machine_id or prior[5] != work_order_id
        or prior[6] != machine_id or prior[7] != "operational"
        or line is None or line[1] != prior[4] or line[2] != machine_id):
        raise WorkOrderHandoffBlockedError()
    execution = connection.execute(
        """SELECT status, started_at, finished_at
           FROM vinto_txn.work_order_line_execution
           WHERE baseline_line_id=%s FOR UPDATE""",
        (baseline_line_id,)).fetchone()
    if execution is None or execution != ("enabled", None, None):
        raise WorkOrderHandoffBlockedError()
    h = connection.execute(
        """SELECT id, work_order_id, baseline_line_id, machine_id,
                  prior_assignment_id, expected_version_number,
                  status, published_version_id, replacement_assignment_id
           FROM vinto_txn.work_order_line_reprogram_handoff
           WHERE id=%s FOR UPDATE""", (handoff_id,)).fetchone()
    if h is None or tuple(h[1:5]) != (
        work_order_id, baseline_line_id, machine_id, assignment_id):
        raise WorkOrderHandoffChangedError()
    # A repeated reassign after the atomic transition must produce a CAS
    # conflict (409 CHANGED), not an eligibility error. Other changes to
    # the old assignment still fail closed.
    if prior[0] == "finished" and h[6] == "reassigned":
        raise WorkOrderHandoffChangedError()
    if prior[0] != "active":
        raise WorkOrderHandoffBlockedError()

    captured = connection.execute(
        """SELECT EXISTS (
             SELECT 1 FROM vinto_txn.capture c
             JOIN vinto_txn.assignment a ON a.id=c.assignment_id
             JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
             JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
             WHERE v.work_order_id=%s AND l.line_code=%s
           )""", (work_order_id, line[1])).fetchone()[0]
    if captured:
        raise WorkOrderHandoffBlockedError()
    return h, prior, line


def _latest(connection, work_order_id):
    row = connection.execute(
        """SELECT id, version_number
           FROM vinto_txn.work_order_version
           WHERE work_order_id=%s AND published_at IS NOT NULL
             AND kind='operational'
           ORDER BY version_number DESC LIMIT 1""",
        (work_order_id,)).fetchone()
    if row is None:
        raise WorkOrderHandoffChangedError()
    return row


def publish(connection, *, actor_id, handoff_id, expected,
            replacement, reason, sectors, request_id=None):
    """Jefatura: append-only vN+1 for reserved line; never touch assignment."""
    _require()
    if expected.machine_code is not None or replacement.machine_code is not None:
        raise InvalidWorkOrderLineError("La máquina no se puede cambiar")
    reason = reason.strip() if isinstance(reason, str) else ""
    if not 10 <= len(reason) <= 300:
        raise InvalidWorkOrderLineError("Se requiere motivo de 10 a 300 caracteres")
    old_fields = service.clean_line(expected)
    new_fields = service.clean_line(replacement)
    if old_fields == new_fields:
        raise InvalidWorkOrderLineError("No hay cambios que publicar")
    with connection.transaction():
        service._context(connection, actor_id, request_id,
                         "E2-D2 Jefatura publish handoff: "+reason)
        h, prior, baseline = _load_locked(
            connection, handoff_id=handoff_id, actor_id=actor_id,
            sectors=sectors, request_id=request_id, reason=reason)
        if h[6] != "pending" or h[7] is not None or h[8] is not None:
            raise WorkOrderHandoffChangedError()
        source = _latest(connection, h[1])
        if source[1] != h[5]:
            raise WorkOrderHandoffChangedError()
        old = connection.execute(
            """SELECT l.id, l.machine_id, l.pv_reference, a.code, l.quantity,
                      l.due_date, l.article_version_id, l.unit_id
               FROM vinto_txn.work_order_line l
               JOIN vinto_master.article_version av ON av.id=l.article_version_id
               JOIN vinto_master.article a ON a.id=av.article_id
               WHERE l.work_order_version_id=%s AND l.line_code=%s
               FOR UPDATE OF l""", (source[0], baseline[1])).fetchone()
        if old is None or old[1] != baseline[2]:
            raise WorkOrderHandoffBlockedError()
        if tuple(old[2:6]) != old_fields:
            raise WorkOrderHandoffChangedError()
        av, unit = ((old[6], old[7]) if old[3] == new_fields[1]
                    else service._resolve_article(
                        connection, old[1], new_fields[1]))
        new_version = connection.execute(
            """INSERT INTO vinto_txn.work_order_version
                 (work_order_id, version_number, kind, based_on_version_id,
                  reprogram_line_code, reprogram_reason)
               VALUES (%s,%s,'operational',%s,%s,%s) RETURNING id""",
            (h[1], h[5]+1, source[0], baseline[1], reason)).fetchone()[0]
        count = connection.execute(
            """INSERT INTO vinto_txn.work_order_line
                 (work_order_version_id,line_code,pv_reference,article_version_id,
                  unit_id,quantity,due_date,machine_id)
               SELECT %s,line_code,pv_reference,article_version_id,unit_id,
                      quantity,due_date,machine_id
               FROM vinto_txn.work_order_line
               WHERE work_order_version_id=%s
               ORDER BY length(line_code),line_code""",
            (new_version, source[0])).rowcount
        if count < 1:
            raise WorkOrderHandoffBlockedError()
        connection.execute(
            """UPDATE vinto_txn.work_order_line SET
                 pv_reference=%s,article_version_id=%s,unit_id=%s,
                 quantity=%s,due_date=%s
               WHERE work_order_version_id=%s AND line_code=%s""",
            (new_fields[0],av,unit,new_fields[2],new_fields[3],
             new_version,baseline[1]))
        connection.execute(
            """UPDATE vinto_txn.work_order_version
               SET published_at=clock_timestamp() WHERE id=%s""",
            (new_version,))
        connection.execute(
            """UPDATE vinto_txn.work_order_line_reprogram_handoff
               SET status='published',published_version_id=%s WHERE id=%s""",
            (new_version,h[0]))
        result = {"handoff_id":h[0], "work_order_id":h[1],
                  "line_code":baseline[1], "version_number":h[5]+1,
                  "published_version_id":new_version, "status":"published"}
    return result


def reassign(connection, *, actor_id, handoff_id, sectors, request_id=None):
    """Retry a published handoff, even with D2 flag OFF, under original locks.

    The existing published snapshot is NEVER deleted or rewritten. The prior
    assignment is retired only with the replacement in the SAME transaction.
    Operator acknowledgement is still mandatory before E1 start.
    """
    _require(allow_existing_recovery=True)
    with connection.transaction():
        service._context(connection, actor_id, request_id,
                         "E2-D2 supervision explicit reassign")
        h, prior, baseline = _load_locked(
            connection, handoff_id=handoff_id, actor_id=actor_id,
            sectors=sectors, request_id=request_id, reason="reassign")
        if h[6] != "published" or h[7] is None or h[8] is not None:
            raise WorkOrderHandoffChangedError()
        latest = _latest(connection,h[1])
        if latest != (h[7], h[5]+1):
            raise WorkOrderHandoffChangedError()
        current = connection.execute(
            """SELECT l.id, l.machine_id
               FROM vinto_txn.work_order_line l
               WHERE l.work_order_version_id=%s AND l.line_code=%s""",
            (h[7],baseline[1])).fetchone()
        if current is None or current[1] != h[3]:
            raise WorkOrderHandoffBlockedError()
        # Shift is always resolved at the moment of reassignment. A prior
        # assignment may belong to an expired shift; its historical context
        # stays immutable when marked finished.
        shift = resolve_shift(
            connection, assignments._now(connection),
            sector_id=connection.execute(
                "SELECT sector_id FROM vinto_master.machine WHERE id=%s",
                (h[3],)).fetchone()[0])
        others = connection.execute(
            """SELECT a.id, v.work_order_id, l.line_code
               FROM vinto_txn.assignment a
               JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
               JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
               WHERE a.machine_id=%s AND a.status='active'
               ORDER BY a.created_at,a.id FOR UPDATE OF a""",
            (h[3],)).fetchall()
        if not any(a[0] == h[4] for a in others):
            raise WorkOrderHandoffChangedError()
        for a in others:
            if a[0] == h[4]:
                continue
            if (not assignments._multi_machine_enabled() or
                a[1] != h[1] or a[2] == baseline[1]):
                raise WorkOrderHandoffBlockedError()
        connection.execute(
            "SELECT set_config('vinto.assignment_multi_line',%s,true)",
            ("on" if assignments._multi_machine_enabled() else "off",))
        service._context(connection, actor_id, request_id,
                         "E2-D2 supervision finish prior assignment")
        connection.execute(
            """UPDATE vinto_txn.assignment SET
                 status='finished',finished_at=clock_timestamp()
               WHERE id=%s AND status='active'""", (h[4],))
        service._context(connection, actor_id, request_id,
                         "E2-D2 supervision create replacement assignment")
        new_id = assignments._insert_assignment_record(
            connection, operational_line_id=current[0], machine_id=h[3],
            shift_schedule_id=shift.shift_schedule_id,
            operating_date=shift.operating_date, actor_id=actor_id)
        service._context(connection, actor_id, request_id,
                         "E2-D2 handoff marked reassigned")
        connection.execute(
            """UPDATE vinto_txn.work_order_line_reprogram_handoff
               SET status='reassigned',replacement_assignment_id=%s
               WHERE id=%s AND status='published'""", (new_id,h[0]))
        result={"handoff_id":h[0], "work_order_id":h[1],
                "previous_assignment_id":h[4],
                "replacement_assignment_id":new_id,
                "version_number":latest[1], "status":"reassigned"}
    return result
