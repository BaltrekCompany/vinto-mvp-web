"""B3: listado recuperable de relevos abiertos, acotado por sectores y rol.

No expone identificadores de usuarios ni modifica la BD. La autorización por
perfil la hace el router; la consulta exige visibilidad sobre TODA la baseline.
"""
from app.sectors import scoped_sector_codes
from app.work_orders import service


def list_open_handoffs(connection, *, sectors):
    allowed = sorted(scoped_sector_codes(sectors))
    if not allowed:
        return []
    rows = connection.execute(
        """SELECT h.id, h.work_order_id, wo.number, bl.line_code,
                  lm.code, h.status, h.expected_version_number,
                  pv.version_number, h.prior_assignment_id,
                  h.replacement_assignment_id, h.reason, h.created_at
           FROM vinto_txn.work_order_line_reprogram_handoff h
           JOIN vinto_txn.work_order wo ON wo.id=h.work_order_id
           JOIN vinto_txn.work_order_version v ON v.work_order_id=wo.id
             AND v.kind='baseline' AND v.version_number=1
             AND v.published_at IS NOT NULL
           JOIN vinto_txn.work_order_line bl ON bl.id=h.baseline_line_id
             AND bl.work_order_version_id=v.id
           JOIN vinto_master.machine hm ON hm.id=wo.machine_id
           JOIN vinto_master.sector hs ON hs.id=hm.sector_id
           JOIN vinto_master.machine lm ON lm.id=h.machine_id
           LEFT JOIN vinto_txn.work_order_version pv ON pv.id=h.published_version_id
           WHERE wo.archived_at IS NULL
             AND h.status IN ('pending','published','reassigned')
             AND hs.code=ANY(%s)
             AND NOT EXISTS (""" + service._OUT_OF_SCOPE_LINE + """)
           ORDER BY h.created_at DESC, h.id DESC LIMIT 100""",
        (allowed, allowed)).fetchall()
    return [
        dict(
            handoff_id=r[0], work_order_id=r[1],
            work_order_number=r[2], line_code=r[3],
            machine_code=r[4], status=r[5],
            expected_version=r[6], published_version=r[7],
            prior_assignment_id=r[8],
            replacement_assignment_id=r[9],
            reason=r[10], created_at=r[11],
        )
        for r in rows
    ]
