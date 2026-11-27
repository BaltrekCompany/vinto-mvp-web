"""Read-only source query and aggregation for the Tubetes Utilizados report.

The report measures tubete consumption from submitted/closed P1-03 captures.
It deliberately does not join Quality decisions: a released, rejected or
pending bobbin has already consumed its tubete.
"""

from collections import defaultdict
from datetime import date, datetime, timezone
from typing import Iterable

from app.reports.tubetes_schemas import MachineTubetesOut, TubeteUsageOut, TubetesReportOut
from app.sectors import SECTOR_BOBINAS, scoped_sector_codes

FORM_CODE = "VINTO-P1-03"
FIELD_KEY = "codigo_de_tubete"
MACHINE_CODES = ("MP1", "MP3")
REPORT_TIMEZONE = "America/La_Paz"


class TubetesReportForbiddenError(Exception):
    """The authenticated user does not hold the BOBINAS sector grant."""


class TubetesReportDataError(Exception):
    """Persisted P1-03 field data no longer matches the approved integer contract."""


# One parameterized query returns one row per submitted/closed P1-03 capture.
# The LEFT JOINs preserve v1 captures whose form version predates codigo_de_tubete.
# The numbered-bobbin join confirms that the P1-03 capture produced a F3 bobbin;
# its partial unique index prevents a capture from multiplying the result.
# Do not join quality_release and do not filter archived_at: neither changes use.
TUBETES_USAGE_SQL = """
SELECT
    m.code AS machine_code,
    d.value_integer AS tubete_code,
    c.operating_date,
    c.captured_at,
    c.id AS capture_id,
    fd.value_type AS field_value_type,
    d.value_type AS detail_value_type
FROM vinto_txn.capture AS c
JOIN vinto_config.form_version AS fv
  ON fv.id = c.form_version_id
JOIN vinto_config.form AS f
  ON f.id = fv.form_id
JOIN vinto_master.machine AS m
  ON m.id = c.machine_id
JOIN vinto_master.sector AS s
  ON s.id = m.sector_id
JOIN vinto_txn.assignment AS a
  ON a.id = c.assignment_id
 AND a.machine_id = c.machine_id
 AND a.shift_schedule_id = c.shift_schedule_id
 AND a.operating_date = c.operating_date
JOIN vinto_txn.work_order_line AS wol
  ON wol.id = a.work_order_line_id
JOIN vinto_txn.work_order_version AS wov
  ON wov.id = wol.work_order_version_id
JOIN vinto_txn.work_order AS wo
  ON wo.id = wov.work_order_id
JOIN vinto_txn.bobbin AS b
  ON b.source_capture_id = c.id
 AND b.machine_id = c.machine_id
 AND b.sequence_number IS NOT NULL
LEFT JOIN vinto_config.field_definition AS fd
  ON fd.form_version_id = c.form_version_id
 AND fd.key = %s
LEFT JOIN vinto_txn.capture_detail AS d
  ON d.capture_id = c.id
 AND d.form_version_id = c.form_version_id
 AND d.field_definition_id = fd.id
 AND d.group_row_id IS NULL
WHERE f.code = %s
  AND fv.area = 'production'
  AND c.status IN ('submitted', 'closed')
  AND s.code = %s
  AND m.code = ANY(%s)
  AND wo.qa_retired IS FALSE
ORDER BY
    m.code ASC,
    d.value_integer ASC NULLS LAST,
    c.operating_date ASC,
    c.captured_at ASC,
    c.id ASC
"""


def build_tubetes_report(rows: Iterable[tuple], *, generated_at: datetime | None = None) -> TubetesReportOut:
    """Aggregate query rows without collapsing repeated uses or same-day dates.

    Row shape: machine, integer code or None, operating_date, captured_at,
    capture_id, field_definition.value_type or None, capture_detail.value_type or None.
    """
    grouped: dict[str, dict[int, list[tuple[date, datetime, str]]]] = {
        machine: defaultdict(list) for machine in MACHINE_CODES
    }
    without_code = {machine: 0 for machine in MACHINE_CODES}

    for row in rows:
        if len(row) != 7:
            raise TubetesReportDataError("Unexpected tubetes query row shape")
        machine, code, operating_date, captured_at, capture_id, field_type, detail_type = row

        if machine not in MACHINE_CODES:
            raise TubetesReportDataError("Unexpected machine in tubetes query")
        if field_type is not None and field_type != "integer":
            raise TubetesReportDataError("P1-03 tubete field is not integer")
        if detail_type is not None and detail_type != "integer":
            raise TubetesReportDataError("P1-03 tubete detail is not integer")
        if detail_type is not None and field_type is None:
            raise TubetesReportDataError("P1-03 tubete detail has no field definition")
        if code is not None and (field_type != "integer" or detail_type != "integer" or type(code) is not int):
            raise TubetesReportDataError("P1-03 tubete value does not match integer definition")
        if code is None and detail_type is not None:
            raise TubetesReportDataError("P1-03 integer detail has no stored value")
        if not isinstance(operating_date, date) or isinstance(operating_date, datetime):
            raise TubetesReportDataError("P1-03 operating_date is not a date")
        if not isinstance(captured_at, datetime) or captured_at.tzinfo is None or captured_at.utcoffset() is None:
            raise TubetesReportDataError("P1-03 captured_at is not timezone-aware")

        if code is None:
            without_code[machine] += 1
            continue

        grouped[machine][code].append((operating_date, captured_at, str(capture_id)))

    machine_results = []
    for machine in MACHINE_CODES:
        tubetes = []
        usage_total = 0
        for code in sorted(grouped[machine]):
            uses = sorted(grouped[machine][code], key=lambda item: (item[0], item[1], item[2]))
            dates = [use[0] for use in uses]
            tubetes.append(TubeteUsageOut(code=str(code), usage_count=len(uses), dates=dates))
            usage_total += len(uses)
        machine_results.append(MachineTubetesOut(
            machine=machine,
            usage_total=usage_total,
            records_without_code=without_code[machine],
            tubetes=tubetes,
        ))

    return TubetesReportOut(
        generated_at=generated_at or datetime.now(timezone.utc),
        machines=machine_results,
    )


def get_tubetes_report(connection, *, sectors) -> TubetesReportOut:
    """Read the report in an explicit PostgreSQL READ ONLY transaction.

    The endpoint never accepts client-provided sectors or machines. The
    authenticated principal's sector grants are checked again at this boundary.
    """
    if SECTOR_BOBINAS not in scoped_sector_codes(sectors):
        raise TubetesReportForbiddenError()

    with connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        rows = connection.execute(
            TUBETES_USAGE_SQL,
            (FIELD_KEY, FORM_CODE, SECTOR_BOBINAS, list(MACHINE_CODES)),
        ).fetchall()

    return build_tubetes_report(rows)
