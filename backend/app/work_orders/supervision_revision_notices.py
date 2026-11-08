"""E2-C2: Supervisión sees and acknowledges the current published OT revision.

Source of truth: immutable work_order_version snapshots from E2-B1 (0016).
Only the latest published revision of each whole OT is actionable. A newer
revision supersedes an earlier receipt without deleting the audit history.
No assignment, E1 execution, F3/F6 capture or operational data is changed.
"""
import uuid

from app.sectors import scoped_sector_codes
from app.work_orders.errors import WorkOrderNotFoundError, SupervisionRevisionConflictError


def _as_uuid(value):
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        raise WorkOrderNotFoundError() from None


def list_supervision_notices(connection, *, user_id, sectors):
    allowed = list(scoped_sector_codes(sectors))
    rows = connection.execute(
        """SELECT w.id, w.number, w.status, v.version_number, v.reprogram_line_code,
                  v.reprogram_reason, v.created_at, changed_by.display_name,
                  new_m.code, oldl.pv_reference, olda.code, oldl.quantity, oldl.due_date,
                  newl.pv_reference, newa.code, newl.quantity, newl.due_date,
                  receipt.acknowledged_at
           FROM vinto_txn.work_order w
           JOIN vinto_txn.work_order_version v
             ON v.work_order_id=w.id AND v.kind='operational'
             AND v.published_at IS NOT NULL AND v.reprogram_reason IS NOT NULL
           JOIN vinto_txn.work_order_version prev ON prev.id=v.based_on_version_id
           JOIN vinto_txn.work_order_line oldl
             ON oldl.work_order_version_id=prev.id AND oldl.line_code=v.reprogram_line_code
           JOIN vinto_txn.work_order_line newl
             ON newl.work_order_version_id=v.id AND newl.line_code=v.reprogram_line_code
           JOIN vinto_master.machine new_m ON new_m.id=newl.machine_id
           JOIN vinto_master.article_version oldav ON oldav.id=oldl.article_version_id
           JOIN vinto_master.article olda ON olda.id=oldav.article_id
           JOIN vinto_master.article_version newav ON newav.id=newl.article_version_id
           JOIN vinto_master.article newa ON newa.id=newav.article_id
           LEFT JOIN vinto_master."user" changed_by ON changed_by.id=v.created_by
           LEFT JOIN vinto_txn.work_order_supervision_revision_receipt receipt
             ON receipt.version_id=v.id AND receipt.user_id=%s
           JOIN vinto_master.machine header_machine ON header_machine.id=w.machine_id
           JOIN vinto_master.sector header_sector ON header_sector.id=header_machine.sector_id
           WHERE w.archived_at IS NULL AND w.status IN ('published','in_progress')
             AND header_sector.code=ANY(%s)
             AND NOT EXISTS (
               SELECT 1 FROM vinto_txn.work_order_version baseline
               JOIN vinto_txn.work_order_line bl ON bl.work_order_version_id=baseline.id
               JOIN vinto_master.machine bm ON bm.id=bl.machine_id
               JOIN vinto_master.sector bs ON bs.id=bm.sector_id
               WHERE baseline.work_order_id=w.id AND baseline.version_number=1
                 AND NOT (bs.code=ANY(%s))
             )
             AND NOT EXISTS (
               SELECT 1 FROM vinto_txn.work_order_version newer
               WHERE newer.work_order_id=w.id AND newer.published_at IS NOT NULL
                 AND newer.version_number>v.version_number
             )
           ORDER BY (receipt.acknowledged_at IS NOT NULL), v.created_at DESC, w.id DESC
           LIMIT 200""",
        (user_id, allowed, allowed)).fetchall()
    return [
        dict(work_order_id=r[0], work_order_number=r[1], status=r[2],
             version_number=r[3], line_code=r[4], reason=r[5],
             revised_at=r[6], changed_by=r[7], machine_code=r[8],
             before=dict(pv_reference=r[9], article_code=r[10],
                         quantity=str(r[11]), due_date=r[12]),
             after=dict(pv_reference=r[13], article_code=r[14],
                        quantity=str(r[15]), due_date=r[16]),
             acknowledged_at=r[17])
        for r in rows
    ]


def acknowledge_supervision_revision(connection, *, actor_id, work_order_id,
                                    expected_version, sectors, request_id):
    """Exact-version, session-bound acknowledgement; 404 out of whole-OT scope."""
    work_order_id = _as_uuid(work_order_id)
    allowed = list(scoped_sector_codes(sectors))
    with connection.transaction():
        # FOR SHARE on the work order serializes with Jefatura's FOR UPDATE
        # during reprogramming; no stale-version read can be committed.
        row = connection.execute(
            """SELECT w.id FROM vinto_txn.work_order w
               JOIN vinto_master.machine header_machine ON header_machine.id=w.machine_id
               JOIN vinto_master.sector header_sector ON header_sector.id=header_machine.sector_id
               WHERE w.id=%s AND w.archived_at IS NULL
                 AND w.status IN ('published','in_progress')
                 AND header_sector.code=ANY(%s)
                 AND NOT EXISTS (
                   SELECT 1 FROM vinto_txn.work_order_version baseline
                   JOIN vinto_txn.work_order_line bl ON bl.work_order_version_id=baseline.id
                   JOIN vinto_master.machine bm ON bm.id=bl.machine_id
                   JOIN vinto_master.sector bs ON bs.id=bm.sector_id
                   WHERE baseline.work_order_id=w.id AND baseline.version_number=1
                     AND NOT (bs.code=ANY(%s))
                 )
               FOR SHARE OF w""",
            (work_order_id, allowed, allowed)).fetchone()
        if row is None:
            raise WorkOrderNotFoundError()
        version = connection.execute(
            """SELECT id, version_number, reprogram_reason
               FROM vinto_txn.work_order_version
               WHERE work_order_id=%s AND published_at IS NOT NULL
               ORDER BY version_number DESC LIMIT 1""",
            (work_order_id,)).fetchone()
        if version is None or version[2] is None:
            raise WorkOrderNotFoundError()
        if version[1] != expected_version:
            raise SupervisionRevisionConflictError()

        connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor_id),))
        connection.execute("SELECT set_config('vinto.request_id', %s, true)", (request_id,))
        connection.execute("SELECT set_config('vinto.reason', %s, true)",
                           ("supervisor acknowledged current published OT revision",))
        receipt = connection.execute(
            """INSERT INTO vinto_txn.work_order_supervision_revision_receipt
                 (version_id, user_id) VALUES (%s,%s)
               ON CONFLICT (version_id,user_id) DO NOTHING
               RETURNING acknowledged_at""",
            (version[0], actor_id)).fetchone()
        if receipt is None:
            receipt = connection.execute(
                """SELECT acknowledged_at
                   FROM vinto_txn.work_order_supervision_revision_receipt
                   WHERE version_id=%s AND user_id=%s""",
                (version[0], actor_id)).fetchone()
        return dict(work_order_id=work_order_id, version_number=version[1],
                    acknowledged_at=receipt[0])
