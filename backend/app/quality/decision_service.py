"""Decision atomica, auditable y limitada a una bobina de Bobinas/Rebobinado.

No interviene sobre OT, lineas, capturas, turnos o asignaciones.
La unica transicion autorizada es pending -> released/rejected.
"""
from fastapi import HTTPException

from app.sectors import scoped_sector_codes
from app.quality.decision_schemas import QualityDecisionIn

DECISION_SECTORS = frozenset({"BOBINAS", "REBOBINADO"})


def decide_bobbin(connection, *, bobbin_id, actor_id, sectors, request_id, body: QualityDecisionIn):
    allowed = list(DECISION_SECTORS.intersection(scoped_sector_codes(sectors)))
    # Sin contexto autorizado no se revela la existencia de ninguna bobina.
    if not allowed:
        raise HTTPException(status_code=404, detail="Bobina no encontrada")
    desired = "released" if body.action == "release" else "rejected"
    with connection.transaction():
        row = connection.execute(
            """SELECT q.status, q.decision_request_id
               FROM vinto_txn.quality_release q
               JOIN vinto_txn.bobbin b ON b.id=q.bobbin_id
               JOIN vinto_master.machine m ON m.id=b.machine_id
               JOIN vinto_master.sector s ON s.id=m.sector_id
               WHERE q.bobbin_id=%s AND b.sequence_number IS NOT NULL
                 AND s.code=ANY(%s)
               FOR UPDATE OF q""",
            (bobbin_id, allowed),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Bobina no encontrada")
        status, previous_id = row
        if status != "pending":
            if status == desired and previous_id is not None and str(previous_id) == str(body.decision_id):
                return {"bobbin_id": bobbin_id, "status": desired, "already_decided": True}
            raise HTTPException(status_code=409, detail="La bobina ya tiene una decision de Calidad")

        connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor_id),))
        connection.execute("SELECT set_config('vinto.request_id', %s, true)", (str(request_id),))
        connection.execute("SELECT set_config('vinto.reason', %s, true)", ("quality release" if desired == "released" else "quality rejection",))
        updated = connection.execute(
            """UPDATE vinto_txn.quality_release
               SET status=%s, decided_by=%s, decided_at=clock_timestamp(),
                   decision_request_id=%s, decision_reason=%s,
                   rejection_type=%s, rejection_classification=%s,
                   rejection_detail=%s, corrective_action=%s
               WHERE bobbin_id=%s AND status='pending'
               RETURNING bobbin_id""",
            (desired, actor_id, body.decision_id,
             "Liberada por Calidad" if desired == "released" else "Rechazada por Calidad",
             body.rejection_type, body.classification, body.detail, body.corrective_action, bobbin_id),
        ).fetchone()
        if updated is None:
            raise HTTPException(status_code=409, detail="La bobina ya tiene una decision de Calidad")
    return {"bobbin_id": bobbin_id, "status": desired, "already_decided": False}
