"""Authoritative fingerprint of a Quality bobbin's production context.

Shared by authenticated offline preparation and operational registration.
Offline client-supplied metadata is never the source of this digest.
"""
import hashlib

from app.quality.offline_capture_scope import _canonical
from app.sectors import scoped_sector_codes


def quality_bobbin_context_digest(connection, bobbin_id: str, machine_code: str, sectors) -> str | None:
    rows = connection.execute(
        """SELECT b.id, m.code, b.source_capture_id, c.assignment_id,
                  c.operating_date, c.shift_schedule_id, q.status,
                  b.rewind_mother_capture_id, b.rewind_child_position
           FROM vinto_txn.bobbin b
           JOIN vinto_master.machine m ON m.id=b.machine_id
           JOIN vinto_master.sector s ON s.id=m.sector_id
           JOIN vinto_txn.capture c ON c.id=b.source_capture_id
           JOIN vinto_txn.quality_release q ON q.bobbin_id=b.id
           WHERE b.id=%s AND m.code=%s AND m.active AND s.active
             AND s.code=ANY(%s) AND b.rewind_child_position IS NULL
             AND (b.sequence_number IS NOT NULL OR b.rewind_mother_capture_id IS NOT NULL)""",
        (bobbin_id, machine_code, list(scoped_sector_codes(sectors))),
    ).fetchone()
    if not rows:
        return None
    keys = ("bobbin_id", "machine_code", "source_capture_id", "assignment_id",
            "operating_date", "shift_schedule_id", "quality_status", "mother_capture_id",
            "child_position")
    normalized = {key: str(value) if value is not None else None
                  for key, value in zip(keys, rows)}
    return hashlib.sha256(_canonical(normalized)).hexdigest()
