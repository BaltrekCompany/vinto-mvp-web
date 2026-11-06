"""Run E1-08 READ ONLY aggregate preflight against a deliberately supplied URL.

Example, with the URL supplied securely by an operator in the environment:
    cd backend && python -m app.work_orders.preflight_cli

Never prints the URL, passwords, user IDs, OT numbers or capture values.
Exit codes: 0 = technical checks clear (NOT deployment GO);
            2 = blockers found; 3 = configuration/connectivity error.
"""
import json
import os
import sys

import psycopg

from app.work_orders.rollout_preflight import collect


def main() -> int:
    url = os.environ.get("VINTO_E108_DATABASE_URL")
    if not url:
        print("E108_PREFLIGHT_URL_NOT_CONFIGURED", file=sys.stderr)
        return 3
    try:
        # Fail closed on any accidental write. This script never calls schema
        # migration or the application write services.
        with psycopg.connect(
            url, autocommit=True, connect_timeout=5,
            options="-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=1500",
        ) as connection:
            with connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                result = collect(connection)
    except (psycopg.Error, OSError, RuntimeError):
        print("E108_PREFLIGHT_QUERY_UNAVAILABLE", file=sys.stderr)
        return 3
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["technical_preflight_clear"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
