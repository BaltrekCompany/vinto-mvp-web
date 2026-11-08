"""Run E2-D0 with the existing release settings; prints only aggregate counts.

Invocation (VPS, service user, correct release):
  VINTO_E2D_EXPECTED_DATABASE=vinto_piloto python -m app.work_orders.e2d_readiness_cli

No direct SQL writes, migrations, cache, HTTP endpoints or secrets in output.
"""
import json
import os
import sys

import psycopg

from app.config import settings
from app.work_orders.e2d_readiness import collect


def main() -> int:
    expected = os.environ.get("VINTO_E2D_EXPECTED_DATABASE", "").strip()
    if expected != "vinto_piloto" and not expected.endswith("_test"):
        print("E2D0_DATABASE_TARGET_NOT_APPROVED", file=sys.stderr)
        return 3
    url = settings.database_url
    if url is None or not url.get_secret_value():
        print("E2D0_DATABASE_URL_UNAVAILABLE", file=sys.stderr)
        return 3
    try:
        with psycopg.connect(
            url.get_secret_value(), autocommit=True, connect_timeout=5,
            options="-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=1500",
        ) as connection:
            actual = connection.execute("SELECT current_database()").fetchone()[0]
            if actual != expected:
                print("E2D0_DATABASE_MISMATCH", file=sys.stderr)
                return 3
            with connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                report = collect(connection)
    except (psycopg.Error, OSError, RuntimeError):
        print("E2D0_READ_ONLY_UNAVAILABLE", file=sys.stderr)
        return 3
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
