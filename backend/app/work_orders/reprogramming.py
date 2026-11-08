"""E2-B: published-order revisions before the first assignment.

No posted baseline, previous operational snapshot, capture or assignment is
updated. A revision is a new complete operational snapshot plus its reason,
actor and timestamp. Live production reprogramming requires E2-C/E2-D.
"""
import re
import uuid

from app.work_orders import service
from app.work_orders.errors import (
    InvalidWorkOrderLineError, WorkOrderNotFoundError,
    WorkOrderReprogramConflictError, WorkOrderReprogramBlockedError,
)

_LINE_CODE = re.compile(r"^L[1-9][0-9]*$")


def reprogram_published_line(connection, *, actor_id, work_order_id, line_code,
                             expected_version, expected: service.LineInput,
                             replacement: service.LineInput, reason, request_id=None,
                             sectors) -> service.WorkOrderView:
    work_order_id = service._as_uuid(work_order_id)
    if not isinstance(line_code, str) or not _LINE_CODE.fullmatch(line_code):
        raise WorkOrderNotFoundError()
    if expected.machine_code is not None or replacement.machine_code is not None:
        raise InvalidWorkOrderLineError("La máquina es inmodificable")
    reason = reason.strip() if isinstance(reason, str) else ""
    if not 10 <= len(reason) <= 300:
        raise InvalidWorkOrderLineError("Se requiere un motivo de 10 a 300 caracteres")
    if not isinstance(expected_version, int) or isinstance(expected_version, bool) or expected_version < 1:
        raise InvalidWorkOrderLineError("La versión esperada es inválida")
    old_fields = service.clean_line(expected)
    new_fields = service.clean_line(replacement)
    if old_fields == new_fields:
        raise InvalidWorkOrderLineError("No hay diferencias para registrar")

    with connection.transaction():
        service._context(connection, actor_id, request_id, "work order reprogram published line: " + reason)
        status, _, baseline_id, baseline_published = service._lock_baseline(connection, work_order_id, sectors)
        if status != "published" or baseline_published is None:
            raise WorkOrderReprogramBlockedError()

        # All historical assignments count, even finished ones: the same OT may
        # already have captures. E1 execution rows also block this safe phase.
        has_history = connection.execute(
            """SELECT EXISTS(
                 SELECT 1 FROM vinto_txn.assignment a
                 JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
                 JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
                 WHERE v.work_order_id=%s
               ) OR EXISTS(
                 SELECT 1 FROM vinto_txn.work_order_line_execution e
                 WHERE e.work_order_id=%s
               )""", (work_order_id, work_order_id)).fetchone()[0]
        if has_history:
            raise WorkOrderReprogramBlockedError()

        # Only a published version is a source; the OT row is locked so
        # concurrent revisions and assignment activations serialize.
        source = connection.execute(
            """SELECT id, version_number FROM vinto_txn.work_order_version
               WHERE work_order_id=%s AND published_at IS NOT NULL
               ORDER BY version_number DESC LIMIT 1""", (work_order_id,)).fetchone()
        if source is None or source[1] != expected_version:
            raise WorkOrderReprogramConflictError()

        old = connection.execute(
            """SELECT l.id, l.machine_id, l.pv_reference, a.code, l.quantity,
                      l.due_date, l.article_version_id, l.unit_id
               FROM vinto_txn.work_order_line l
               JOIN vinto_master.article_version av ON av.id=l.article_version_id
               JOIN vinto_master.article a ON a.id=av.article_id
               WHERE l.work_order_version_id=%s AND l.line_code=%s
               FOR UPDATE OF l""", (source[0], line_code)).fetchone()
        if old is None:
            raise WorkOrderNotFoundError()
        if tuple(old[2:6]) != old_fields:
            raise WorkOrderReprogramConflictError()
        article_version_id, unit_id = (
            (old[6], old[7]) if new_fields[1] == old[3]
            else service._resolve_article(connection, old[1], new_fields[1])
        )

        new_version_id = connection.execute(
            """INSERT INTO vinto_txn.work_order_version
                 (work_order_id, version_number, kind, based_on_version_id,
                  reprogram_line_code, reprogram_reason)
               VALUES (%s,%s,'operational',%s,%s,%s) RETURNING id""",
            (work_order_id, expected_version + 1, source[0], line_code, reason)).fetchone()[0]
        copied = connection.execute(
            """INSERT INTO vinto_txn.work_order_line
                 (work_order_version_id,line_code,pv_reference,article_version_id,
                  unit_id,quantity,due_date,machine_id)
               SELECT %s,line_code,pv_reference,article_version_id,unit_id,
                      quantity,due_date,machine_id
               FROM vinto_txn.work_order_line
               WHERE work_order_version_id=%s
               ORDER BY length(line_code),line_code""", (new_version_id, source[0])).rowcount
        if not copied:
            raise WorkOrderReprogramBlockedError()
        connection.execute(
            """UPDATE vinto_txn.work_order_line SET
                 pv_reference=%s, article_version_id=%s, unit_id=%s,
                 quantity=%s, due_date=%s
               WHERE work_order_version_id=%s AND line_code=%s""",
            (*new_fields[:1], article_version_id, unit_id, new_fields[2], new_fields[3], new_version_id, line_code))
        # Triggers on version and lines prohibit all later edits to this snapshot.
        connection.execute(
            "UPDATE vinto_txn.work_order_version SET published_at=clock_timestamp() WHERE id=%s",
            (new_version_id,))

    return service.get_work_order(connection, work_order_id, sectors=sectors, multi_machine_visible=True)


def revision_history(connection, *, work_order_id, sectors) -> list[dict]:
    work_order_id = service._as_uuid(work_order_id)
    # Full-OT visibility before exposing any actor, reason or line content.
    service.get_work_order(connection, work_order_id, sectors=sectors, multi_machine_visible=True)
    rows = connection.execute(
        """SELECT v.version_number, prev.version_number, v.reprogram_line_code,
                  v.reprogram_reason, v.created_at, v.created_by,
                  usr.display_name,
                  oldl.pv_reference, olda.code, oldl.quantity, oldl.due_date,
                  newl.pv_reference, newa.code, newl.quantity, newl.due_date
           FROM vinto_txn.work_order_version v
           JOIN vinto_txn.work_order_version prev ON prev.id=v.based_on_version_id
             AND prev.work_order_id=v.work_order_id
           JOIN vinto_master."user" usr ON usr.id=v.created_by
           JOIN vinto_txn.work_order_line oldl
             ON oldl.work_order_version_id=prev.id AND oldl.line_code=v.reprogram_line_code
           JOIN vinto_txn.work_order_line newl
             ON newl.work_order_version_id=v.id AND newl.line_code=v.reprogram_line_code
           JOIN vinto_master.article_version oldav ON oldav.id=oldl.article_version_id
           JOIN vinto_master.article olda ON olda.id=oldav.article_id
           JOIN vinto_master.article_version newav ON newav.id=newl.article_version_id
           JOIN vinto_master.article newa ON newa.id=newav.article_id
           WHERE v.work_order_id=%s AND v.reprogram_reason IS NOT NULL
             AND v.published_at IS NOT NULL
           ORDER BY v.version_number DESC""", (work_order_id,)).fetchall()
    return [
        dict(version_number=r[0], previous_version=r[1], line_code=r[2],
             reason=r[3], changed_at=r[4], changed_by_id=r[5],
             changed_by_name=r[6],
             before=dict(pv_reference=r[7], article_code=r[8],
                         quantity=r[9], due_date=r[10]),
             after=dict(pv_reference=r[11], article_code=r[12],
                        quantity=r[13], due_date=r[14]))
        for r in rows
    ]
