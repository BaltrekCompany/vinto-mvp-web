"""Unit tests for Tubetes Utilizados aggregation and SQL read-only boundary."""

import unittest
from contextlib import nullcontext
from datetime import date, datetime, timezone
from uuid import UUID

from app.reports.tubetes_service import (
    MACHINE_CODES,
    TUBETES_USAGE_SQL,
    TubetesReportDataError,
    TubetesReportForbiddenError,
    build_tubetes_report,
    get_tubetes_report,
)


CAPTURE_A = UUID("00000000-0000-4000-8000-000000000001")
CAPTURE_B = UUID("00000000-0000-4000-8000-000000000002")
CAPTURE_C = UUID("00000000-0000-4000-8000-000000000003")
NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)


def row(machine, code, day, captured_at, capture_id, field_type="integer", detail_type="integer"):
    return (machine, code, day, captured_at, capture_id, field_type, detail_type)


class Result:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def fetchall(self):
        return self._rows


class FakeConnection:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.statements = []
        self.params = []

    def transaction(self):
        return nullcontext()

    def execute(self, statement, params=None):
        self.statements.append(statement)
        self.params.append(params)
        return Result(self.rows if statement == TUBETES_USAGE_SQL else ())


class TubetesAggregationTests(unittest.TestCase):
    def test_both_machines_are_always_present_even_when_empty(self):
        report = build_tubetes_report([], generated_at=NOW)
        self.assertEqual([item.machine for item in report.machines], ["MP1", "MP3"])
        self.assertEqual([item.usage_total for item in report.machines], [0, 0])
        self.assertEqual([item.records_without_code for item in report.machines], [0, 0])
        self.assertEqual([item.tubetes for item in report.machines], [[], []])
        self.assertEqual(report.generated_at, NOW)
        self.assertEqual((report.source_form, report.date_basis, report.timezone),
                         ("VINTO-P1-03", "operating_date", "America/La_Paz"))

    def test_codes_sort_numerically_and_dates_sort_by_operating_day_then_capture_time(self):
        day_27 = date(2026, 11, 27)
        day_28 = date(2026, 11, 28)
        rows = [
            row("MP1", 10, day_27, datetime(2026, 11, 27, 10, tzinfo=timezone.utc), CAPTURE_A),
            row("MP1", 2, day_28, datetime(2026, 11, 28, 8, tzinfo=timezone.utc), CAPTURE_C),
            row("MP1", 2, day_27, datetime(2026, 11, 27, 11, tzinfo=timezone.utc), CAPTURE_B),
            row("MP1", 2, day_27, datetime(2026, 11, 27, 7, tzinfo=timezone.utc), CAPTURE_A),
            row("MP3", 1, day_27, datetime(2026, 11, 27, 9, tzinfo=timezone.utc), CAPTURE_C),
        ]
        report = build_tubetes_report(rows, generated_at=NOW)
        mp1 = report.machines[0]
        self.assertEqual([item.code for item in mp1.tubetes], ["2", "10"])
        self.assertEqual(mp1.usage_total, 4)
        self.assertEqual(mp1.tubetes[0].usage_count, 3)
        self.assertEqual(mp1.tubetes[0].dates, [day_27, day_27, day_28])
        self.assertEqual(report.machines[1].tubetes[0].code, "1")

    def test_same_day_repetitions_and_more_than_ten_uses_are_preserved(self):
        day = date(2026, 11, 27)
        rows = [
            row("MP3", 7, day, datetime(2026, 11, 27, 8, minute=index, tzinfo=timezone.utc), UUID(int=index + 1))
            for index in range(23)
        ]
        report = build_tubetes_report(rows, generated_at=NOW)
        tubete = report.machines[1].tubetes[0]
        self.assertEqual(tubete.code, "7")
        self.assertEqual(tubete.usage_count, 23)
        self.assertEqual(len(tubete.dates), 23)
        self.assertEqual(set(tubete.dates), {day})
        self.assertEqual(report.machines[1].usage_total, 23)

    def test_missing_field_value_is_diagnostic_not_a_tubete_use(self):
        rows = [
            row("MP1", None, date(2026, 11, 27), NOW, CAPTURE_A, field_type=None, detail_type=None),
            row("MP1", 0, date(2026, 11, 27), NOW, CAPTURE_B),
        ]
        report = build_tubetes_report(rows, generated_at=NOW)
        mp1 = report.machines[0]
        self.assertEqual(mp1.records_without_code, 1)
        self.assertEqual(mp1.usage_total, 1)
        self.assertEqual([item.code for item in mp1.tubetes], ["0"])

    def test_field_type_drift_fails_closed_without_coercion(self):
        invalid = [
            row("MP1", 7, date(2026, 11, 27), NOW, CAPTURE_A, field_type="text", detail_type="text"),
            row("MP1", 7, date(2026, 11, 27), NOW, CAPTURE_A, field_type="integer", detail_type="text"),
            row("MP1", "007", date(2026, 11, 27), NOW, CAPTURE_A),
            row("MP1", True, date(2026, 11, 27), NOW, CAPTURE_A),
            row("MP1", 7, date(2026, 11, 27), NOW, CAPTURE_A, field_type=None, detail_type="integer"),
            row("MP1", None, date(2026, 11, 27), NOW, CAPTURE_A, field_type="integer", detail_type="integer"),
        ]
        for item in invalid:
            with self.subTest(row=item), self.assertRaises(TubetesReportDataError):
                build_tubetes_report([item])


class TubetesReadOnlyBoundaryTests(unittest.TestCase):
    def test_query_is_scoped_to_p103_bobinas_mp1_mp3_and_never_filters_quality_or_normal_archive(self):
        sql = TUBETES_USAGE_SQL.lower()
        self.assertIn("f.code = %s", sql)
        self.assertIn("fv.area = 'production'", sql)
        self.assertIn("c.status in ('submitted', 'closed')", sql)
        self.assertIn("s.code = %s", sql)
        self.assertIn("m.code = any(%s)", sql)
        self.assertIn("wo.qa_retired is false", sql)
        self.assertIn("b.sequence_number is not null", sql)
        self.assertIn("fd.key = %s", sql)
        self.assertNotIn("quality_release", sql)
        self.assertNotIn("archived_at", sql)
        self.assertNotIn("distinct", sql)
        self.assertNotIn("limit", sql)

    def test_service_starts_explicit_read_only_transaction_and_uses_server_owned_scope(self):
        connection = FakeConnection([
            row("MP1", 1, date(2026, 11, 27), NOW, CAPTURE_A),
        ])
        report = get_tubetes_report(connection, sectors=("BOBINAS",))
        self.assertEqual(connection.statements[0], "SET TRANSACTION READ ONLY")
        self.assertEqual(connection.statements[1], TUBETES_USAGE_SQL)
        self.assertEqual(connection.params[1], ("codigo_de_tubete", "VINTO-P1-03", "BOBINAS", list(MACHINE_CODES)))
        self.assertEqual(report.machines[0].usage_total, 1)

    def test_service_refuses_missing_sector_before_querying(self):
        connection = FakeConnection()
        with self.assertRaises(TubetesReportForbiddenError):
            get_tubetes_report(connection, sectors=())
        self.assertEqual(connection.statements, [])


if __name__ == "__main__":
    unittest.main()
