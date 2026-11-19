"""OFF-04.5B-03 — controlled promotion of the proposed 0032 migration into a migrations directory.

The proposal lives OUTSIDE `backend/migrations/` so `migrate.py` never applies it by accident. This helper copies it into a numbered migration file
in a directory you name (a temporary tree in tests) after checking that it is a valid `migrate.py` migration. It REFUSES the operational
`backend/migrations/` directory: promoting there is a reviewed git change in a later, explicitly authorised increment, never a script run.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROPOSED = HERE / "proposed_0032_offline_capture_receipt.sql"
OPERATIONAL = (HERE.parent / "migrations").resolve()
TARGET_NAME = "0032_offline_capture_receipt.sql"
_TX = re.compile(r"^\s*(BEGIN|COMMIT|END|ROLLBACK|START\s+TRANSACTION)\s*;", re.IGNORECASE | re.MULTILINE)


class PromotionError(Exception):
    pass


def check_proposal(sql: str) -> None:
    if _TX.search(sql):
        raise PromotionError("the migration must not open or close transactions: migrate.py wraps each migration in one")
    if re.search(r"^\s*\\", sql, re.MULTILINE):
        raise PromotionError("psql meta-commands are not allowed in a migrate.py migration")
    if not re.search(r"^CREATE SCHEMA vinto_offline;", sql, re.MULTILINE):
        raise PromotionError("the migration must create vinto_offline without IF NOT EXISTS (it must fail on a pre-existing schema)")
    if re.search(r"^\s*(DROP|TRUNCATE)\b", sql, re.IGNORECASE | re.MULTILINE):
        raise PromotionError("destructive statements are not allowed")
    if re.search(r"\bvinto_(master|config|txn|auth|audit|meta|identity)\b", sql):
        raise PromotionError("the migration must not reference another module's schema")


def promote(dest_dir: Path, *, source: Path = PROPOSED) -> Path:
    dest_dir = Path(dest_dir).resolve()
    if dest_dir == OPERATIONAL or OPERATIONAL in dest_dir.parents:
        raise PromotionError("refusing the operational migrations directory: promotion there needs a reviewed, authorised change")
    if not dest_dir.is_dir():
        raise PromotionError("destination directory does not exist")
    sql = source.read_text(encoding="utf-8").replace("\r\n", "\n")
    check_proposal(sql)
    numbers = sorted(int(m[1]) for p in dest_dir.glob("*.sql") if (m := re.fullmatch(r"([0-9]{4})_[a-z0-9_]+\.sql", p.name)))
    if numbers != list(range(1, len(numbers) + 1)) or len(numbers) != 31:
        raise PromotionError("the destination must hold exactly migrations 0001..0031 in sequence")
    target = dest_dir / TARGET_NAME
    if target.exists():
        raise PromotionError("destination already holds 0032")
    target.write_text(sql, encoding="utf-8", newline="\n")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", required=True, type=Path, help="a directory holding a COPY of migrations 0001..0031 (never backend/migrations)")
    args = parser.parse_args(argv)
    try:
        print(f"promoted: {promote(args.dest).name}")
        return 0
    except PromotionError as error:
        print(f"promotion refused: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
