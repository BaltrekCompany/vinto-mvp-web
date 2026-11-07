"""VINTO E1-08: aggregate, read-only preflight for enabling logical line execution.

The collector REFUSES to run unless the current PostgreSQL transaction is
READ ONLY. It never returns OT numbers, user IDs, assignment IDs, customer
data, captured values, connection parameters or credentials.

Run this only after a pre-approved, read-only connection has been established.
No backfill, data repair, schema changes or feature activation are performed.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

_MIGRATION_PATH = Path(__file__).resolve().parents[2] / "migrations" / "0013_work_order_line_execution.sql"


def _one(connection, sql: str) -> int:
    return int(connection.execute(sql).fetchone()[0])


def collect(connection) -> dict:
    config = connection.execute(
        "SELECT current_setting('transaction_read_only'), current_setting('transaction_isolation')"
    ).fetchone()
    if config != ("on", "repeatable read"):
        raise RuntimeError("E1-08 requires a REPEATABLE READ, READ ONLY PostgreSQL transaction")

    # Installed objects and migration history are checked separately, to avoid
    # assuming that a manually created table means migration 0013 is applied.
    installed = bool(connection.execute(
        "SELECT to_regclass('vinto_txn.work_order_line_execution') IS NOT NULL"
    ).fetchone()[0])
    applied = connection.execute(
        "SELECT filename, checksum FROM vinto_meta.schema_migration WHERE version=13"
    ).fetchone()
    migration_0013 = applied is not None
    try:
        local_sql = _MIGRATION_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
        expected_digest = hashlib.sha256(local_sql.encode("utf-8")).hexdigest()
        migration_checksum_ok = bool(
            applied is not None and applied[0] == _MIGRATION_PATH.name
            and applied[1] == expected_digest
        )
    except OSError:
        migration_checksum_ok = False
    # Every scalar read is independent, allowing safe targeted diagnostics
    # without fetching even one assignment/OT record.
    counts = {
        "orders_in_progress": _one(connection,
            "SELECT count(*) FROM vinto_txn.work_order WHERE status='in_progress' AND archived_at IS NULL"),
        "assignments_active": _one(connection,
            "SELECT count(*) FROM vinto_txn.assignment WHERE status='active'"),
        "qa_retired_orders": _one(connection,
            "SELECT count(*) FROM vinto_txn.work_order WHERE qa_retired AND archived_at IS NOT NULL"),
        "qa_retired_active_assignments": _one(connection,
            """SELECT count(*) FROM vinto_txn.assignment a
               JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
               JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
               JOIN vinto_txn.work_order wo ON wo.id=v.work_order_id
               WHERE a.status='active' AND wo.qa_retired"""),
        "baseline_lines_in_progress": _one(connection,
            """SELECT count(*) FROM vinto_txn.work_order_line bl
               JOIN vinto_txn.work_order_version bv ON bv.id=bl.work_order_version_id
               JOIN vinto_txn.work_order wo ON wo.id=bv.work_order_id
               WHERE bv.kind='baseline' AND bv.version_number=1 AND wo.status='in_progress' AND wo.archived_at IS NULL"""),
        "active_assignments_on_closed_orders": _one(connection,
            """SELECT count(*) FROM vinto_txn.assignment a
               JOIN vinto_txn.work_order_line ol ON ol.id=a.work_order_line_id
               JOIN vinto_txn.work_order_version ov ON ov.id=ol.work_order_version_id
               JOIN vinto_txn.work_order wo ON wo.id=ov.work_order_id
               WHERE a.status='active' AND wo.status='closed'"""),
        "active_assignments_unmapped_to_baseline": _one(connection,
            """SELECT count(*) FROM vinto_txn.assignment a
               JOIN vinto_txn.work_order_line ol ON ol.id=a.work_order_line_id
               JOIN vinto_txn.work_order_version ov ON ov.id=ol.work_order_version_id
               LEFT JOIN vinto_txn.work_order_version bv ON bv.work_order_id=ov.work_order_id
                  AND bv.kind='baseline' AND bv.version_number=1
               LEFT JOIN vinto_txn.work_order_line bl ON bl.work_order_version_id=bv.id
                  AND bl.line_code=ol.line_code AND bl.machine_id=a.machine_id
               WHERE a.status='active' AND (ov.kind<>'operational' OR bl.id IS NULL)"""),
    }

    machine_rows = connection.execute(
        """SELECT s.code, m.code, count(*) AS active, count(DISTINCT ov.work_order_id) AS orders
           FROM vinto_txn.assignment a
           JOIN vinto_master.machine m ON m.id=a.machine_id
           JOIN vinto_master.sector s ON s.id=m.sector_id
           JOIN vinto_txn.work_order_line ol ON ol.id=a.work_order_line_id
           JOIN vinto_txn.work_order_version ov ON ov.id=ol.work_order_version_id
           WHERE a.status='active'
           GROUP BY s.code, m.code ORDER BY s.code, m.code"""
    ).fetchall()
    # Aggregate by machine, not by user, assignment or individual OT.
    by_machine = [
        {"sector": str(sector), "machine": str(machine),
         "active_assignments": int(active), "distinct_orders": int(orders)}
        for sector, machine, active, orders in machine_rows
    ]
    rollout = {
        "migration_0013_recorded": migration_0013,
        "migration_0013_checksum_matches_checkout": migration_checksum_ok,
        "execution_table_installed": installed,
        "execution_unique_machine_index": False,
        "execution_guard_trigger_enabled": False,
        "vinto_app_privileges": "not_checked",
        "lines_in_progress_without_execution": None,
        "active_without_execution": None,
        "active_with_finished_execution": None,
        "active_with_planned_execution": None,
        "active_in_production": None,
        "active_enabled": None,
    }
    if installed:
        rollout["execution_unique_machine_index"] = bool(connection.execute(
            "SELECT to_regclass('vinto_txn.work_order_line_execution_one_producing_machine') IS NOT NULL"
        ).fetchone()[0])
        rollout["execution_guard_trigger_enabled"] = bool(connection.execute(
            """SELECT EXISTS(SELECT 1 FROM pg_trigger
               WHERE tgrelid='vinto_txn.work_order_line_execution'::regclass
                 AND tgname='a_guard_work_order_line_execution' AND tgenabled='O')"""
        ).fetchone()[0])
        role_exists = bool(connection.execute(
            "SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='vinto_app')"
        ).fetchone()[0])
        if role_exists:
            rollout["vinto_app_privileges"] = bool(connection.execute(
                """SELECT has_table_privilege('vinto_app',
                   'vinto_txn.work_order_line_execution', 'SELECT')
                   AND has_table_privilege('vinto_app',
                   'vinto_txn.work_order_line_execution', 'INSERT')
                   AND has_table_privilege('vinto_app',
                   'vinto_txn.work_order_line_execution', 'UPDATE')"""
            ).fetchone()[0])
        else:
            rollout["vinto_app_privileges"] = "role_absent"

        rollout["lines_in_progress_without_execution"] = _one(connection,
            """SELECT count(*) FROM vinto_txn.work_order_line bl
               JOIN vinto_txn.work_order_version bv ON bv.id=bl.work_order_version_id
               JOIN vinto_txn.work_order wo ON wo.id=bv.work_order_id
               LEFT JOIN vinto_txn.work_order_line_execution e ON e.baseline_line_id=bl.id
               WHERE bv.kind='baseline' AND bv.version_number=1
                 AND wo.status='in_progress' AND wo.archived_at IS NULL AND e.baseline_line_id IS NULL""")
        statuses = connection.execute(
            """SELECT
                count(*) FILTER (WHERE e.baseline_line_id IS NULL),
                count(*) FILTER (WHERE e.status='finished'),
                count(*) FILTER (WHERE e.status='planned'),
                count(*) FILTER (WHERE e.status='in_production'),
                count(*) FILTER (WHERE e.status='enabled')
               FROM vinto_txn.assignment a
               JOIN vinto_txn.work_order_line ol ON ol.id=a.work_order_line_id
               JOIN vinto_txn.work_order_version ov ON ov.id=ol.work_order_version_id
               JOIN vinto_txn.work_order wo ON wo.id=ov.work_order_id
               LEFT JOIN vinto_txn.work_order_version bv ON bv.work_order_id=ov.work_order_id
                 AND bv.kind='baseline' AND bv.version_number=1
               LEFT JOIN vinto_txn.work_order_line bl ON bl.work_order_version_id=bv.id
                 AND bl.line_code=ol.line_code AND bl.machine_id=a.machine_id
               LEFT JOIN vinto_txn.work_order_line_execution e ON e.baseline_line_id=bl.id
               WHERE a.status='active' AND ov.kind='operational' AND wo.archived_at IS NULL"""
        ).fetchone()
        for key, value in zip(("active_without_execution", "active_with_finished_execution",
                               "active_with_planned_execution", "active_in_production",
                               "active_enabled"), statuses):
            rollout[key] = int(value)

    blockers = []
    if not installed or not migration_0013:
        blockers.append("MIGRATION_0013_NOT_CONFIRMED")
    if migration_0013 and not migration_checksum_ok:
        blockers.append("MIGRATION_0013_CHECKSUM_MISMATCH")
    if installed and not rollout["execution_unique_machine_index"]:
        blockers.append("MISSING_MACHINE_EXCLUSIVITY_INDEX")
    if installed and not rollout["execution_guard_trigger_enabled"]:
        blockers.append("MISSING_EXECUTION_GUARD")
    if installed and rollout["vinto_app_privileges"] is False:
        blockers.append("APP_ROLE_WITHOUT_REQUIRED_TABLE_PRIVILEGES")
    if counts["qa_retired_active_assignments"]:
        blockers.append("QA_RETIRED_HAS_ACTIVE_ASSIGNMENTS")
    if counts["active_assignments_on_closed_orders"]:
        blockers.append("CLOSED_ORDERS_HAVE_ACTIVE_ASSIGNMENTS")
    if counts["active_assignments_unmapped_to_baseline"]:
        blockers.append("ACTIVE_ASSIGNMENTS_WITHOUT_BASELINE_MAPPING")
    if installed:
        if rollout["lines_in_progress_without_execution"]:
            blockers.append("IN_PROGRESS_ORDERS_WITHOUT_EXECUTION")
        if rollout["active_without_execution"]:
            blockers.append("ACTIVE_ASSIGNMENTS_WITHOUT_EXECUTION")
        if rollout["active_with_finished_execution"] or rollout["active_with_planned_execution"]:
            blockers.append("ACTIVE_ASSIGNMENTS_WITH_INCONSISTENT_EXECUTION")
    elif counts["orders_in_progress"] or counts["assignments_active"]:
        blockers.append("LEGACY_STATE_MUST_BE_REVIEWED_BEFORE_0013")

    return {
        "preflight": "VINTO_E1_08_READ_ONLY",
        "sensitive_row_level_data_returned": False,
        "schema": rollout,
        "totals": counts,
        "active_by_sector_machine": by_machine,
        "blockers": blockers,
        "technical_preflight_clear": not blockers,
        "note": "No GO de despliegue: requiere aprobación, QA manual y plan de rollback incluso si no hay bloqueantes.",
    }
