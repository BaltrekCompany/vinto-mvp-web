"""E2-D0: strictly read-only aggregate inventory before live OT reprogramming.

Never infers produced quantity from F3/F6, never returns individual IDs,
PV/article, employees, captures or credentials. No Go decision is returned.
"""
from __future__ import annotations


_SQL = """
WITH baseline AS (
    SELECT w.id AS work_order_id, w.status AS work_order_status,
           bl.id AS baseline_line_id, bl.line_code, bl.machine_id,
           e.status AS execution_status
    FROM vinto_txn.work_order w
    JOIN vinto_txn.work_order_version bv
      ON bv.work_order_id=w.id AND bv.kind='baseline' AND bv.version_number=1
    JOIN vinto_txn.work_order_line bl ON bl.work_order_version_id=bv.id
    LEFT JOIN vinto_txn.work_order_line_execution e
      ON e.baseline_line_id=bl.id
    WHERE w.archived_at IS NULL AND NOT w.qa_retired
      AND w.status IN ('published','in_progress')
),
line_evidence AS (
    SELECT b.*,
           EXISTS (
               SELECT 1 FROM vinto_txn.assignment a
               JOIN vinto_txn.work_order_line ol ON ol.id=a.work_order_line_id
               JOIN vinto_txn.work_order_version ov ON ov.id=ol.work_order_version_id
               WHERE ov.work_order_id=b.work_order_id
                 AND ol.line_code=b.line_code AND a.machine_id=b.machine_id
           ) AS has_assignment_history,
           EXISTS (
               SELECT 1 FROM vinto_txn.assignment a
               JOIN vinto_txn.work_order_line ol ON ol.id=a.work_order_line_id
               JOIN vinto_txn.work_order_version ov ON ov.id=ol.work_order_version_id
               WHERE ov.work_order_id=b.work_order_id
                 AND ol.line_code=b.line_code AND a.machine_id=b.machine_id
                 AND a.status='active'
           ) AS has_active_assignment,
           EXISTS (
               SELECT 1 FROM vinto_txn.capture c
               JOIN vinto_txn.assignment a ON a.id=c.assignment_id
               JOIN vinto_txn.work_order_line ol ON ol.id=a.work_order_line_id
               JOIN vinto_txn.work_order_version ov ON ov.id=ol.work_order_version_id
               WHERE ov.work_order_id=b.work_order_id
                 AND ol.line_code=b.line_code AND a.machine_id=b.machine_id
           ) AS has_capture_history
    FROM baseline b
),
classified AS (
    SELECT *,
        CASE
          WHEN has_capture_history OR execution_status IN ('in_production','finished')
            THEN 'PRODUCTION_OR_CAPTURE_HISTORY'
          WHEN has_active_assignment AND execution_status IS NULL
            THEN 'LEGACY_ACTIVE_UNRECONCILED'
          WHEN has_assignment_history AND execution_status IS NULL
            THEN 'LEGACY_ASSIGNMENT_UNRECONCILED'
          WHEN has_active_assignment OR execution_status='enabled'
            THEN 'ASSIGNED_OR_ENABLED_NOT_STARTED'
          WHEN has_assignment_history OR execution_status='planned'
            THEN 'HISTORICAL_ASSIGNMENT_OR_PLAN'
          ELSE 'UNASSIGNED_NO_EXECUTION_EVIDENCE'
        END AS bucket
    FROM line_evidence
)
SELECT work_order_status, bucket, count(*) AS baseline_lines,
       count(*) FILTER (WHERE has_active_assignment) AS with_active_assignments,
       count(*) FILTER (WHERE has_capture_history) AS with_any_capture,
       count(*) FILTER (WHERE execution_status='in_production') AS in_production
FROM classified
GROUP BY work_order_status, bucket ORDER BY work_order_status, bucket
"""


def collect(connection) -> dict:
    """Requires a caller-controlled REPEATABLE READ READ ONLY transaction."""
    mode = connection.execute(
        "SELECT current_setting('transaction_read_only'), current_setting('transaction_isolation')"
    ).fetchone()
    if mode != ("on", "repeatable read"):
        raise RuntimeError("E2-D0 requires REPEATABLE READ READ ONLY")

    # Fail closed when the necessary tables are absent: we must not classify
    # missing evidence as 'safe to reprogram'.
    required = (
        "vinto_txn.work_order", "vinto_txn.work_order_version",
        "vinto_txn.work_order_line", "vinto_txn.assignment",
        "vinto_txn.work_order_line_execution", "vinto_txn.capture",
        "vinto_txn.work_order_revision_receipt",
        "vinto_txn.work_order_supervision_revision_receipt",
    )
    missing = [
        name for name in required if connection.execute(
            "SELECT to_regclass(%s) IS NOT NULL", (name,)
        ).fetchone()[0] is not True
    ]
    if missing:
        raise RuntimeError("E2-D0 required schema not available")

    rows = connection.execute(_SQL).fetchall()
    groups = [
        {"order_status": status, "risk_bucket": bucket,
         "baseline_lines": int(count),
         "active_assignments": int(active),
         "lines_with_captures": int(captures),
         "lines_in_production": int(producing)}
        for status, bucket, count, active, captures, producing in rows
    ]
    totals = {
        "baseline_lines_inspected": sum(r["baseline_lines"] for r in groups),
        "unassigned_lines_of_in_progress_ots": sum(
            r["baseline_lines"] for r in groups
            if r["order_status"] == "in_progress"
            and r["risk_bucket"] == "UNASSIGNED_NO_EXECUTION_EVIDENCE"
        ),
        "with_capture_evidence": sum(r["lines_with_captures"] for r in groups),
        "currently_in_production": sum(r["lines_in_production"] for r in groups),
        "legacy_unreconciled": sum(
            r["baseline_lines"] for r in groups if r["risk_bucket"].startswith("LEGACY_")
        ),
    }
    return {
        "preflight": "VINTO_E2D0_READ_ONLY",
        "sensitive_row_level_data_returned": False,
        "groups": groups,
        "totals": totals,
        "production_write_authorized": False,
        "operational_go": False,
        "note": ("This is a classification census, not an authorization to edit active OTs; "
                 "actual production quantities, assigned-version consistency and business exceptions "
                 "require independent reconciliation before E2-D releases."),
    }
