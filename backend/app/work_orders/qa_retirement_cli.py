"""E1-10: retire an explicit manifest of historical QA work orders atomically.

This is an offline maintenance command, NOT a public API. No write happens in
dry-run mode. It preserves all work-order, assignment, capture, bobbin, quality,
and audit rows. It finishes only legacy ACTIVE SHIFT ASSIGNMENTS, without
creating any fake logical line-execution events or changing work-order status.

Requires the additive 0015_qa_legacy_retirement.sql migration to be applied.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from pathlib import Path

import psycopg

from app.assignments.service import _lock_machines
from app.config import settings

_ORDER_RE = re.compile(r"OT-[0-9]{4}-[0-9]{4}\Z")
_REASON_MIN, _REASON_MAX = 10, 300


class RetirementBlocked(Exception):
    pass


def _load_manifest(path: Path):
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or set(doc) != {
        "order_numbers", "expected_orders", "expected_baseline_lines",
        "expected_active_assignments", "actor_id", "reason"
    }:
        raise RetirementBlocked("Invalid closed manifest shape")
    numbers = doc["order_numbers"]
    if not isinstance(numbers, list) or not numbers or any(
        not isinstance(n, str) or not _ORDER_RE.fullmatch(n) for n in numbers
    ) or len(numbers) != len(set(numbers)):
        raise RetirementBlocked("Manifest requires unique canonical OT numbers")
    if sorted(numbers) != numbers:
        raise RetirementBlocked("Manifest OT numbers must be lexically sorted")
    expected = [doc["expected_orders"], doc["expected_baseline_lines"],
                doc["expected_active_assignments"]]
    if any(type(v) is not int or v < 0 for v in expected):
        raise RetirementBlocked("Manifest expected counts must be nonnegative integers")
    if len(numbers) != doc["expected_orders"]:
        raise RetirementBlocked("Number of OT does not match expected_orders")
    if not isinstance(doc["reason"], str) or not (
        _REASON_MIN <= len(doc["reason"].strip()) <= _REASON_MAX
    ):
        raise RetirementBlocked("QA retirement reason must contain 10-300 characters")
    try:
        doc["actor_id"] = uuid.UUID(str(doc["actor_id"]))
    except (TypeError, AttributeError, ValueError):
        raise RetirementBlocked("actor_id is not a valid UUID") from None
    return doc


def _scalar(connection, sql, params=()):
    return connection.execute(sql, params).fetchone()[0]


def _snapshot(connection, doc, *, lock: bool):
    numbers = doc["order_numbers"]
    rows = connection.execute(
        "SELECT id, number, status, archived_at, qa_retired "
        "FROM vinto_txn.work_order WHERE number = ANY(%s) "
        "ORDER BY id " + ("FOR UPDATE" if lock else ""),
        (numbers,),
    ).fetchall()
    if len(rows) != doc["expected_orders"] or sorted(r[1] for r in rows) != numbers:
        raise RetirementBlocked("OT manifest differs from database")
    if any(r[2] != "in_progress" or r[3] is not None or r[4] for r in rows):
        raise RetirementBlocked("OT must all be in_progress, unarchived, and not retired")
    ids = [r[0] for r in rows]
    lines = _scalar(connection, """
        SELECT count(*)
        FROM vinto_txn.work_order_version v
        JOIN vinto_txn.work_order_line bl ON bl.work_order_version_id=v.id
        WHERE v.work_order_id=ANY(%s) AND v.kind='baseline' AND v.version_number=1
    """, (ids,))
    if lines != doc["expected_baseline_lines"]:
        raise RetirementBlocked("Baseline line count changed")
    execution = _scalar(connection, """
        SELECT count(*) FROM vinto_txn.work_order_line_execution
        WHERE work_order_id=ANY(%s)
    """, (ids,))
    if execution:
        raise RetirementBlocked("Existing E1 logical execution cannot be QA-retired")

    machines = [r[0] for r in connection.execute("""
        SELECT DISTINCT machine_id FROM (
          SELECT bl.machine_id
          FROM vinto_txn.work_order_version v
          JOIN vinto_txn.work_order_line bl ON bl.work_order_version_id=v.id
          WHERE v.work_order_id=ANY(%s) AND v.kind='baseline' AND v.version_number=1
          UNION
          SELECT a.machine_id
          FROM vinto_txn.assignment a
          JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
          JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
          WHERE v.work_order_id=ANY(%s)
        ) identified_machines
    """, (ids, ids)).fetchall()]
    if lock:
        _lock_machines(connection, machines)

    assignment_rows = connection.execute("""
        SELECT a.id, a.status FROM vinto_txn.assignment a
        JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
        JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
        WHERE v.work_order_id=ANY(%s) ORDER BY a.id
    """ + (" FOR UPDATE OF a" if lock else ""), (ids,)).fetchall()
    active_ids = [r[0] for r in assignment_rows if r[1] == "active"]
    if len(active_ids) != doc["expected_active_assignments"]:
        raise RetirementBlocked("Active assignment count changed")
    if any(r[1] not in ("active", "finished") for r in assignment_rows):
        raise RetirementBlocked("Unexpected assignment state")
    return ids, active_ids, {
        "orders": len(ids),
        "baseline_lines": lines,
        "active_assignments": len(active_ids),
        "historical_finished_assignments": len(assignment_rows) - len(active_ids),
        "machines": len(machines),
        "logical_executions": execution,
    }


def _apply(connection, doc):
    if settings.work_order_line_execution_enabled is not False:
        raise RetirementBlocked("E1 feature must be OFF")
    # Mandatory: the operator explicitly attests that an up-to-date backup
    # has been verified with a separate restoration test before this write.
    if os.environ.get("VINTO_QA_RETIREMENT_CONFIRMED") != "yes":
        raise RetirementBlocked("Missing VINTO_QA_RETIREMENT_CONFIRMED=yes")
    if os.environ.get("VINTO_QA_BACKUP_VERIFIED") != "yes":
        raise RetirementBlocked("Missing VINTO_QA_BACKUP_VERIFIED=yes")
    if os.environ.get("VINTO_QA_OFFHOST_VERIFIED") != "yes":
        raise RetirementBlocked("Missing VINTO_QA_OFFHOST_VERIFIED=yes")

    with connection.transaction():
        connection.execute("SET LOCAL lock_timeout = '5000ms'")
        connection.execute("SET LOCAL statement_timeout = '60000ms'")
        if not _scalar(connection, """
            SELECT EXISTS (
                SELECT 1 FROM vinto_master."user" u
                JOIN vinto_master."user_profile" up ON up.user_id=u.id
                JOIN vinto_master."profile" p ON p.id=up.profile_id
                WHERE u.id=%s AND u.active AND p.code='JEFATURA' AND p.active
            )
        """, (doc["actor_id"],)):
            raise RetirementBlocked("Actor must be an active Jefatura user")
        ids, active_ids, snapshot = _snapshot(connection, doc, lock=True)

        request_id = f"e1-10-qa-retirement:{uuid.uuid4()}"
        connection.execute("SELECT set_config('vinto.actor_id', %s, true)",
                           (str(doc["actor_id"]),))
        connection.execute("SELECT set_config('vinto.request_id', %s, true)",
                           (request_id,))
        connection.execute("SELECT set_config('vinto.reason', %s, true)",
                           (doc["reason"],))

        if active_ids:
            finished = connection.execute("""
                UPDATE vinto_txn.assignment SET status='finished',
                     finished_at=clock_timestamp()
                WHERE id=ANY(%s) AND status='active' RETURNING id
            """, (active_ids,)).fetchall()
            if len(finished) != len(active_ids):
                raise RetirementBlocked("Concurrent change while finishing QA shift assignments")

        retired = connection.execute("""
            UPDATE vinto_txn.work_order
            SET archived_at=clock_timestamp(), archived_by=%s,
                archived_reason=%s, qa_retired=true
            WHERE id=ANY(%s) AND status='in_progress' AND archived_at IS NULL
            RETURNING id
        """, (doc["actor_id"], doc["reason"], ids)).fetchall()
        if len(retired) != len(ids):
            raise RetirementBlocked("Unexpected archived count")
        if _scalar(connection, """
            SELECT count(*) FROM vinto_txn.assignment a
            JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
            JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
            WHERE v.work_order_id=ANY(%s) AND a.status='active'
        """, (ids,)):
            raise RetirementBlocked("Active assignment remains after QA retirement")
        if _scalar(connection, """
            SELECT count(*) FROM vinto_txn.work_order
            WHERE id=ANY(%s) AND status='in_progress'
                AND qa_retired AND archived_at IS NOT NULL
        """, (ids,)) != len(ids):
            raise RetirementBlocked("QA retirement marker incomplete")

    return snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description="E1-10 historical QA retirement")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--apply", action="store_true",
                        help="Write transaction; omitted by default (dry-run)")
    args = parser.parse_args()
    try:
        if settings.work_order_line_execution_enabled:
            raise RetirementBlocked("E1 flag is ON; do not retire historical QA orders")
        doc = _load_manifest(args.manifest)
        url = settings.database_url
        if url is None:
            raise RetirementBlocked("No application DB URL configured")
        with psycopg.connect(
            url.get_secret_value(), autocommit=True, connect_timeout=5,
            options="-c statement_timeout=60000 -c lock_timeout=5000",
        ) as connection:
            if args.apply:
                result = _apply(connection, doc)
                action = "COMMITTED_QA_RETIREMENT"
            else:
                with connection.transaction():
                    connection.execute(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                    )
                    _, _, result = _snapshot(connection, doc, lock=False)
                action = "DRY_RUN_NO_WRITES"
        print(json.dumps({"action": action, "counts": result}, sort_keys=True))
        return 0
    except (RetirementBlocked, psycopg.Error, OSError, ValueError,
            json.JSONDecodeError) as error:
        # Do not serialize DB credentials, query params, UUIDs or original
        # SQL error strings into operator logs.
        reason = "MANIFEST_OR_GUARD_BLOCKED" if isinstance(
            error, RetirementBlocked
        ) else "DATABASE_OR_IO_UNAVAILABLE"
        print(f"QA_RETIREMENT_STOP={reason}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
