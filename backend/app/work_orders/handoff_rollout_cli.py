"""Read-only E2-D2 safety gate for controlled rollback / disable / rollout.

Run as the VINTO service user from the exact deployed release. Uses the
existing backend/.env through Settings: never expose DATABASE_URL in argv,
logs, output or generated files. It only performs a read-only DB transaction.

Examples:
    python -m app.work_orders.handoff_rollout_cli rollback
    python -m app.work_orders.handoff_rollout_cli disable
    python -m app.work_orders.handoff_rollout_cli enable

Exit: 0 = technical gate clear (not approval to deploy);
      2 = active handoffs/invariant blocker; 3 = missing/inaccessible DB.
"""
import json
import sys

import psycopg

from app.config import settings
from app.work_orders.handoff_rollout_preflight import collect

_MODES = {"rollback", "disable", "enable"}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1 or argv[0] not in _MODES:
        print("D2_PREFLIGHT_USAGE: rollback|disable|enable", file=sys.stderr)
        return 3
    secret = settings.database_url
    if secret is None or not secret.get_secret_value():
        print("D2_DATABASE_UNAVAILABLE", file=sys.stderr)
        return 3
    try:
        with psycopg.connect(
            secret.get_secret_value(), autocommit=True, connect_timeout=5,
            options=("-c default_transaction_read_only=on "
                     "-c statement_timeout=15000 -c lock_timeout=1500"),
        ) as connection:
            with connection.transaction():
                connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                result = collect(connection)
    except (psycopg.Error, OSError, ValueError, RuntimeError):
        print("D2_PREFLIGHT_QUERY_UNAVAILABLE", file=sys.stderr)
        return 3
    print(json.dumps(
        {"operation": argv[0], **result}, sort_keys=True,
        ensure_ascii=False))
    return 0 if result["technical_preflight_clear"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
