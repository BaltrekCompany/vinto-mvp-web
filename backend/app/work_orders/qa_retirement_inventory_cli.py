"""E1-10: read-only candidate inventory for a *private, closed* QA retirement manifest.

This tool cannot certify that an OT is fictitious. The operator must review
the manifest and its associated business records before running --apply.
Prints aggregate counts only; writes a private 0600 JSON manifest on demand.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import psycopg

from app.config import settings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor-display-name", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if settings.work_order_line_execution_enabled:
        print("STOP=E1_FLAG_ON", file=sys.stderr)
        return 2
    if settings.database_url is None:
        print("STOP=NO_APP_DB_URL", file=sys.stderr)
        return 2

    try:
        with psycopg.connect(
            settings.database_url.get_secret_value(), autocommit=True,
            connect_timeout=5,
            options="-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=1500",
        ) as connection:
            with connection.transaction():
                connection.execute(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                rows = connection.execute("""
                    SELECT id, number
                    FROM vinto_txn.work_order
                    WHERE status='in_progress' AND archived_at IS NULL
                    ORDER BY number
                """).fetchall()
                ids = [r[0] for r in rows]
                numbers = [r[1] for r in rows]
                if len(numbers) != 13:
                    print("STOP=EXPECTED_13_IN_PROGRESS_QA_ORDERS", file=sys.stderr)
                    return 2
                lines = connection.execute("""
                    SELECT count(*)
                    FROM vinto_txn.work_order_version v
                    JOIN vinto_txn.work_order_line l ON l.work_order_version_id=v.id
                    WHERE v.work_order_id=ANY(%s)
                      AND v.kind='baseline' AND v.version_number=1
                """, (ids,)).fetchone()[0]
                active = connection.execute("""
                    SELECT count(*) FROM vinto_txn.assignment a
                    JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id
                    JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id
                    WHERE v.work_order_id=ANY(%s) AND a.status='active'
                """, (ids,)).fetchone()[0]
                if lines != 18 or active != 9:
                    print("STOP=EXPECTED_18_LINES_9_ACTIVE_DRIFT", file=sys.stderr)
                    return 2
                actors = connection.execute("""
                    SELECT DISTINCT u.id
                    FROM vinto_master."user" u
                    JOIN vinto_master."user_profile" up ON up.user_id=u.id
                    JOIN vinto_master."profile" p ON p.id=up.profile_id
                    WHERE u.display_name=%s AND u.active
                      AND p.code='JEFATURA' AND p.active
                """, (args.actor_display_name,)).fetchall()
                if len(actors) != 1:
                    print("STOP=ACTOR_NOT_UNIQUE_JEFATURA", file=sys.stderr)
                    return 2
                document = {
                    "order_numbers": numbers,
                    "expected_orders": 13,
                    "expected_baseline_lines": 18,
                    "expected_active_assignments": 9,
                    "actor_id": str(actors[0][0]),
                    "reason": "Retiro controlado de OT ficticias de QA para habilitar E1",
                }

        # No overwrite, no follow-symlink; parent dir must already exist.
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(args.output, flags, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump(document, target, ensure_ascii=False, indent=2)
            target.write("\n")
        print(json.dumps({
            "action": "PRIVATE_MANIFEST_CREATED_READ_ONLY",
            "path": str(args.output),
            "orders": 13, "baseline_lines": 18, "active_assignments": 9,
        }))
        return 0
    except (psycopg.Error, OSError):
        print("STOP=INVENTORY_UNAVAILABLE", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
