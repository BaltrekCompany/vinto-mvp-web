"""E2-D2-B0: read-only reservation guards. No reservation writers/API in this phase.

All callers MUST already hold the machine advisory lock for the affected line
(and for start_line/activate, the OT row lock first). That lock serializes future
supervised reservation creation with F3/F6 and assignment transitions without
introducing an OT lock into capture's machine -> assignment path.
"""
from app.config import settings
from app.work_orders.errors import WorkOrderHandoffPendingError

_BLOCKING = ("pending", "published", "reassigned")


def enabled() -> bool:
    return settings.work_order_reprogram_handoff_enabled is True


def require_line_unreserved(connection, *, work_order_id, line_code):
    """Read-only, fail closed on DB errors. Call after machine lock, before writes.

    Do not SELECT FOR SHARE: PostgreSQL requires UPDATE privilege even for
    shared row locking. B0 grants vinto_app SELECT only. The machine advisory
    lock serializes this read with B1's future audited reservation writer,
    which MUST acquire the same machine lock before INSERT/UPDATE.
    """
    if not enabled():
        return
    row = connection.execute(
        """SELECT h.id
           FROM vinto_txn.work_order_line_reprogram_handoff h
           JOIN vinto_txn.work_order_line bl ON bl.id=h.baseline_line_id
           JOIN vinto_txn.work_order_version bv ON bv.id=bl.work_order_version_id
           WHERE h.work_order_id=%s AND bl.line_code=%s
             AND bv.work_order_id=h.work_order_id
             AND bv.kind='baseline' AND bv.version_number=1
             AND h.status = ANY(%s)
           """,
        (work_order_id, line_code, list(_BLOCKING)),
    ).fetchone()
    if row is not None:
        raise WorkOrderHandoffPendingError()


def require_assignment_unreserved(connection, *, assignment_id):
    """Use persisted assignment to resolve logical identity, never client fields."""
    if not enabled():
        return
    row = connection.execute(
        """SELECT v.work_order_id, l.line_code
           FROM vinto_txn.assignment a
           JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
           JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
           WHERE a.id=%s AND v.kind='operational'""",
        (assignment_id,),
    ).fetchone()
    if row is not None:
        require_line_unreserved(connection, work_order_id=row[0], line_code=row[1])
