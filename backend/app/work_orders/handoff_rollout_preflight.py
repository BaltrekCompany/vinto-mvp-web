"""E2-D2-B2-B: aggregate, read-only rollback/enable/disable preflight.

Never returns OT numbers, actor IDs, handoff IDs, credentials or captured data.
The collector REQUIRES REPEATABLE READ READ ONLY and fails closed if schema,
migration checksums or the database-level E1 trigger cannot be confirmed.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

_MIGRATION_DIR = Path(__file__).resolve().parents[2] / "migrations"
_REQUIRED = (
    (19, "0019_work_order_line_reprogram_handoff.sql"),
    (20, "0020_e2d2_supervisor_reservation.sql"),
    (21, "0021_e2d2_publish_reassign.sql"),
    (22, "0022_e2d2_operator_receipt_and_e1_barrier.sql"),
)


def collect(connection) -> dict:
    options = connection.execute(
        "SELECT current_setting('transaction_read_only'), current_setting('transaction_isolation')"
    ).fetchone()
    if options != ("on", "repeatable read"):
        raise RuntimeError("D2 preflight requires REPEATABLE READ READ ONLY")

    rows = connection.execute(
        "SELECT version, filename, checksum FROM vinto_meta.schema_migration WHERE version BETWEEN 19 AND 22"
    ).fetchall()
    installed = {int(v): (f, checksum) for v, f, checksum in rows}
    integrity = {}
    for number, filename in _REQUIRED:
        path = _MIGRATION_DIR / filename
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        integrity[filename] = installed.get(number) == (filename, digest)

    table = bool(connection.execute(
        "SELECT to_regclass('vinto_txn.work_order_line_reprogram_handoff') IS NOT NULL"
    ).fetchone()[0])
    e1_trigger = bool(connection.execute(
        """SELECT EXISTS (
             SELECT 1 FROM pg_trigger
             WHERE tgrelid='vinto_txn.work_order_line_execution'::regclass
               AND tgname='a_e2d2_execution_start_guard'
               AND tgenabled='O'
           )"""
    ).fetchone()[0]) if table else False

    counts = {"pending": 0, "published": 0, "reassigned": 0,
              "acknowledged": 0, "cancelled": 0}
    if table:
        for status, number in connection.execute(
            """SELECT status, count(*)
               FROM vinto_txn.work_order_line_reprogram_handoff
               GROUP BY status"""
        ).fetchall():
            if status not in counts:
                raise RuntimeError("D2 unknown handoff lifecycle status")
            counts[status] = int(number)
    open_count = sum(counts[x] for x in ("pending", "published", "reassigned"))
    blockers = []
    if not all(integrity.values()):
        blockers.append("D2_MIGRATIONS_NOT_VERIFIED")
    if not table:
        blockers.append("D2_HANDOFF_TABLE_MISSING")
    if not e1_trigger:
        blockers.append("D2_E1_START_BARRIER_MISSING")
    if open_count:
        blockers.append("D2_OPEN_HANDOFFS_PRESENT")
    return {
        "d2_migrations_verified": integrity,
        "d2_e1_sql_guard_enabled": e1_trigger,
        "d2_handoff_table_installed": table,
        "handoffs_by_state": counts,
        "open_handoff_count": open_count,
        "safe_to_disable_or_rollback": len(blockers) == 0,
        "technical_preflight_clear": len(blockers) == 0,
        "blockers": blockers,
        "note": "This is a necessary technical gate, NOT functional QA approval",
    }
