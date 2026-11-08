"""E2-C1: read-only notices and optional operator acknowledgement.

Only an active assignment of an ALREADY revised published OT qualifies.
Receipt is per authenticated user + assignment + exact assigned version.
No changes to captures, production state, assignment pointers or E1.
E2-D must separately design reprogramming of OTs with live assignments.
"""
import uuid

from app.assignments.errors import AssignmentNotFoundError, RevisionNoticeConflictError
from app.sectors import scoped_sector_codes


def _uuid(value):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise AssignmentNotFoundError() from None


def list_revision_notices(connection, *, user_id, sectors, machine_codes):
    """Only active assignments on machines allowed by the current MF13 engine."""
    allowed = sorted(machine_codes)
    if not allowed:
        return []
    rows = connection.execute(
        """SELECT a.id, v.id, v.version_number, w.number,
                  l.line_code, m.code, v.reprogram_reason,
                  v.created_at, receipt.acknowledged_at
           FROM vinto_txn.assignment a
           JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
           JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
           JOIN vinto_txn.work_order w ON w.id=v.work_order_id
           JOIN vinto_master.machine m ON m.id=a.machine_id
           JOIN vinto_master.sector s ON s.id=m.sector_id
           LEFT JOIN vinto_txn.work_order_revision_receipt receipt
             ON receipt.assignment_id=a.id AND receipt.version_id=v.id
             AND receipt.user_id=%s
           WHERE a.status='active' AND v.kind='operational'
             AND v.published_at IS NOT NULL AND v.reprogram_reason IS NOT NULL
             AND s.code=ANY(%s) AND m.code=ANY(%s)
           ORDER BY (receipt.acknowledged_at IS NOT NULL), v.created_at DESC, a.created_at DESC, a.id DESC
           LIMIT 200""",
        (user_id, list(scoped_sector_codes(sectors)), allowed)).fetchall()
    return [
        dict(assignment_id=r[0], version_number=r[2], work_order_number=r[3],
             line_code=r[4], machine_code=r[5], reason=r[6],
             revised_at=r[7], acknowledged_at=r[8])
        for r in rows
    ]


def acknowledge_revision(connection, *, actor_id, assignment_id, expected_version,
                         sectors, machine_codes, request_id):
    """Idempotent for this operator; never accepts client-selected user/machine."""
    assignment_id = _uuid(assignment_id)
    if not machine_codes:
        raise AssignmentNotFoundError()
    with connection.transaction():
        row = connection.execute(
            """SELECT v.id, v.version_number, v.reprogram_reason, a.id
               FROM vinto_txn.assignment a
               JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
               JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
               JOIN vinto_master.machine m ON m.id=a.machine_id
               JOIN vinto_master.sector s ON s.id=m.sector_id
               WHERE a.id=%s AND a.status='active'
                 AND s.code=ANY(%s) AND m.code=ANY(%s)
               FOR SHARE OF a""",
            (assignment_id, list(scoped_sector_codes(sectors)), sorted(machine_codes))).fetchone()
        if row is None or row[2] is None:
            # Hide existence of assignments outside authorized machine/sector.
            raise AssignmentNotFoundError()
        version_id, version_number = row[:2]
        if version_number != expected_version:
            raise RevisionNoticeConflictError()

        connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor_id),))
        connection.execute("SELECT set_config('vinto.request_id', %s, true)", (request_id,))
        connection.execute("SELECT set_config('vinto.reason', %s, true)", ("operator acknowledged assigned OT revision",))
        receipt = connection.execute(
            """INSERT INTO vinto_txn.work_order_revision_receipt
                 (assignment_id, version_id, user_id)
               VALUES (%s,%s,%s)
               ON CONFLICT (assignment_id,version_id,user_id) DO NOTHING
               RETURNING acknowledged_at""",
            (assignment_id, version_id, actor_id)).fetchone()
        if receipt is None:
            receipt = connection.execute(
                """SELECT acknowledged_at FROM vinto_txn.work_order_revision_receipt
                   WHERE assignment_id=%s AND version_id=%s AND user_id=%s""",
                (assignment_id, version_id, actor_id)).fetchone()
        return dict(assignment_id=assignment_id, version_number=version_number,
                    acknowledged_at=receipt[0])
