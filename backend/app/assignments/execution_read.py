"""E1-06: read-only execution state of authorized active assignments for Operación.

The historical /active and /active-lines contracts are unchanged. This query
may only be called with the effective machine scope for the current user.
An assignment's state is resolved from the immutable baseline line of its OT,
not from assignment.status ('active' is a shift habilitation, not production).
"""
from app.assignments import service as assignment_service
from app.config import settings


def read_machine_execution(connection, *, machine_code, sectors, machine_codes):
    # Check scope and existence with the same well-tested, MF13 protected query
    # used by /active-lines, regardless of the flag, to avoid leaking machines.
    active = assignment_service.get_active_lines(
        connection, machine_code=machine_code, sectors=sectors, machine_codes=machine_codes)
    if settings.work_order_line_execution_enabled is not True:
        # Old production behavior: no query against migration 0013.
        return {"line_execution": False, "assignments": []}

    ids = [item.assignment.id for item in active.items]
    if not ids:
        return {"line_execution": True, "assignments": []}
    rows = connection.execute(
        """SELECT a.id, e.status
           FROM vinto_txn.assignment a
           JOIN vinto_txn.work_order_line ol ON ol.id = a.work_order_line_id
           JOIN vinto_txn.work_order_version ov ON ov.id = ol.work_order_version_id
             AND ov.kind='operational'
           JOIN vinto_txn.work_order_version bv ON bv.work_order_id=ov.work_order_id
             AND bv.kind='baseline' AND bv.version_number=1
           JOIN vinto_txn.work_order_line bl ON bl.work_order_version_id=bv.id
             AND bl.machine_id=a.machine_id AND bl.line_code=ol.line_code
           LEFT JOIN vinto_txn.work_order_line_execution e ON e.baseline_line_id=bl.id
           WHERE a.id=ANY(%s) AND a.status='active'
           ORDER BY a.id""", (ids,)).fetchall()
    statuses = {assignment_id: status for assignment_id, status in rows}
    # Any missing or unresolvable baseline line must fail closed. This is also
    # the reconciliation state for legacy active assignments with no E1-02 row.
    return {
        "line_execution": True,
        "assignments": [
            {"assignment_id": assignment_id,
             "status": statuses.get(assignment_id) or "requires_review"}
            for assignment_id in ids
        ],
    }
