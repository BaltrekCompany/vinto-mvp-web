"""Bandeja central de Calidad para Bobinas F3 (solo lectura).

La autoridad de la bandeja es vinto_txn.quality_release.status. NO depende de la asignación activa, del turno o la fecha
actuales, de la máquina seleccionada ni de la OT en ejecución: una Bobina pendiente sigue ahí aunque su asignación haya
terminado (por eso no hay filtro por a.status, ni resolve_shift, ni lock_active_assignment). La asignación solo se usa para
DERIVAR la OT/línea/PV de la Bobina (bobbin -> source_capture -> assignment -> work_order_line -> work_order_version -> work_order).

Sin truncamiento: devuelve TODAS las Bobinas del estado pedido (un LIMIT fijo haría desaparecer pendientes sin que el cliente lo sepa).
La paginación se agregará como hardening cuando exista el contrato de frontend correspondiente.

No escribe nada: ni quality_release (sin liberar/rechazar), ni bobbin, ni capturas.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time

from app.work_orders.service import ALLOWED_SECTOR_CODES

QUALITY_STATUSES = ("pending", "released", "rejected")  # CHECK de quality_release en 0001
DEFAULT_STATUS = "pending"


@dataclass(frozen=True)
class QualityBobbinView:
    bobbin_id: uuid.UUID
    code: str
    machine_code: str
    machine_name: str
    management_start_year: int
    sequence_number: int
    start_time: time
    end_time: time
    diameter_mm: str
    weight_kg: str
    grammage_g_m2: str | None
    number_of_cuts: str
    notes: str | None
    capture_id: uuid.UUID
    captured_at: datetime
    operating_date: date
    shift_code: str
    shift_name: str
    work_order_id: uuid.UUID
    work_order_number: str
    line_id: uuid.UUID
    line_code: str
    pv_reference: str
    article_code: str
    article_description: str
    quality_status: str


# Orden de presentación determinista (marca temporal estable + id). NO es una prioridad de negocio: Calidad no confirmó ninguna.
_SQL = """SELECT b.id, b.code, m.code, m.name, b.management_start_year, b.sequence_number, b.start_time, b.end_time,
                 b.diameter_mm, b.weight_kg, b.grammage_g_m2, b.number_of_cuts, b.notes,
                 c.id, c.captured_at, c.operating_date, sh.code, sh.name,
                 wo.id, wo.number, l.id, l.line_code, l.pv_reference, ar.code, av.description, q.status
          FROM vinto_txn.bobbin b
          JOIN vinto_txn.quality_release q ON q.bobbin_id = b.id
          JOIN vinto_txn.capture c ON c.id = b.source_capture_id
          JOIN vinto_master.machine m ON m.id = b.machine_id
          JOIN vinto_master.sector s ON s.id = m.sector_id
          JOIN vinto_config.shift_schedule sc ON sc.id = c.shift_schedule_id
          JOIN vinto_config.shift sh ON sh.id = sc.shift_id
          JOIN vinto_txn.assignment a ON a.id = c.assignment_id
          JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
          JOIN vinto_txn.work_order_version wov ON wov.id = l.work_order_version_id
          JOIN vinto_txn.work_order wo ON wo.id = wov.work_order_id
          JOIN vinto_master.article_version av ON av.id = b.article_version_id
          JOIN vinto_master.article ar ON ar.id = av.article_id
          WHERE b.sequence_number IS NOT NULL AND q.status = %s AND s.code = ANY(%s)
          ORDER BY c.captured_at DESC, b.id DESC"""


def _text(value):
    return None if value is None else format(value, "f")  # decimales como texto exacto, sin float


def list_quality_bobbins(connection, status: str = DEFAULT_STATUS) -> list[QualityBobbinView]:
    if status not in QUALITY_STATUSES:
        raise ValueError(f"Estado de calidad desconocido: {status!r}")
    rows = connection.execute(_SQL, (status, list(ALLOWED_SECTOR_CODES))).fetchall()
    views = []
    for row in rows:
        r = list(row)
        r[8], r[9], r[10] = _text(r[8]), _text(r[9]), _text(r[10])  # diameter_mm, weight_kg, grammage_g_m2 (puede ser NULL)
        views.append(QualityBobbinView(*r))
    return views
