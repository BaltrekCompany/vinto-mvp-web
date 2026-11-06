"""E1-07: manual, audited closing of an entire work order by Supervisión.

Only after every immutable baseline line is logically finished. Completion
does not imply that the produced quantity equals the originally planned one.
Order lock -> sorted machine locks -> line execution locks. E1-03 start/finish
and assignment activation lock the OT before touching machine assignments.
"""
from app.assignments import service as assignments
from app.work_orders import line_execution, service
from app.work_orders.errors import WorkOrderError


class WorkOrderCloseInvalidStateError(WorkOrderError):
    http_status, code, public_message = (
        409, "WORK_ORDER_CLOSE_INVALID_STATE",
        "La OT no está en ejecución y no se puede cerrar",
    )


class WorkOrderCloseBlockedError(WorkOrderError):
    http_status, code, public_message = (
        409, "WORK_ORDER_CLOSE_PENDING_LINES",
        "No se puede cerrar la OT: existen líneas sin finalizar o asignaciones activas",
    )

    def __init__(self, pending_lines):
        self.pending_lines = tuple(sorted(set(pending_lines)))
        super().__init__()


def close_work_order(connection, *, actor_id, work_order_id, sectors, request_id=None):
    line_execution.require_enabled()
    work_order_id = service._as_uuid(work_order_id)
    with connection.transaction():
        service._context(connection, actor_id, request_id, "manual close work order by supervision")
        # The same full baseline sector scope check as create/publish/list. No
        # partial OT visibility or side channel for another sector's line.
        status, _, baseline_version_id, published_at = service._lock_baseline(
            connection, work_order_id, sectors)
        if status == "closed":
            return service.get_work_order(
                connection, work_order_id, sectors=sectors, multi_machine_visible=True)
        if status != "in_progress" or published_at is None:
            raise WorkOrderCloseInvalidStateError()

        baseline = connection.execute(
            """SELECT id, line_code, machine_id FROM vinto_txn.work_order_line
               WHERE work_order_version_id=%s ORDER BY machine_id, line_code, id""",
            (baseline_version_id,)).fetchall()
        if not baseline:
            raise WorkOrderCloseBlockedError(("SIN_LINEAS",))

        # Consistent lock order with activation/start/finish: OT first,
        # advisory locks for all machines second, individual rows third.
        assignments._lock_machines(connection, [row[2] for row in baseline])
        ids = [row[0] for row in baseline]
        execution_rows = connection.execute(
            """SELECT baseline_line_id, status
               FROM vinto_txn.work_order_line_execution
               WHERE work_order_id=%s AND baseline_line_id=ANY(%s)
               ORDER BY baseline_line_id FOR UPDATE""",
            (work_order_id, ids)).fetchall()
        states = {line_id: state for line_id, state in execution_rows}
        pending = [line_code for line_id, line_code, _ in baseline
                   if states.get(line_id) != "finished"]

        # Defensive check: a historically active assignment must not be left
        # hanging after logical close, including one from an old turn.
        active = connection.execute(
            """SELECT DISTINCT ol.line_code
               FROM vinto_txn.assignment a
               JOIN vinto_txn.work_order_line ol ON ol.id=a.work_order_line_id
               JOIN vinto_txn.work_order_version ov ON ov.id=ol.work_order_version_id
               WHERE ov.kind='operational' AND ov.work_order_id=%s
                 AND a.status='active'""",
            (work_order_id,)).fetchall()
        pending.extend(row[0] for row in active)
        if pending:
            raise WorkOrderCloseBlockedError(pending)

        connection.execute(
            "UPDATE vinto_txn.work_order SET status='closed' WHERE id=%s AND status='in_progress'",
            (work_order_id,))
        return service.get_work_order(
            connection, work_order_id, sectors=sectors, multi_machine_visible=True)
