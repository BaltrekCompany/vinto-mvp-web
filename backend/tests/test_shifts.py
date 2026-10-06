"""Shift and operating-date resolver.

Part 1 is pure time arithmetic (no database). Part 2 resolves against shift_schedule in PostgreSQL:
fixtures live in a rolled-back transaction of the isolated test database, and the real imported
Bobinas bundle is checked in an ephemeral *_test database. Everything uses connect_test_database().
"""

import contextlib
import io
import os
import time as time_module
import unittest
from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app import shifts
from app.config import settings
from app.db_guard import connect_test_database, is_test_database_name
from app.seed import reference
from app.seed.bundle import load_bundle
from app.shifts import (SHIFT_AMBIGUOUS, SHIFT_INVALID_CAPTURED_AT, SHIFT_INVALID_SCHEDULE, SHIFT_INVALID_TIMEZONE,
                        SHIFT_NOT_CONFIGURED, SHIFT_SECTOR_NOT_FOUND, ScheduleRow, ShiftResolutionError,
                        resolve_shift, resolve_shift_from_schedules)
from migrate import apply as apply_migrations
from migrate import read_migrations

LA_PAZ = ZoneInfo("America/La_Paz")
JAN_1 = date(2026, 1, 1)


def at(year, month, day, hour=0, minute=0, second=0, tz=LA_PAZ):
    return datetime(year, month, day, hour, minute, second, tzinfo=tz)


def schedule(code, start, end, *, timezone_name="America/La_Paz", valid_from=JAN_1, valid_to=None, name=None):
    return ScheduleRow(uuid4(), uuid4(), code, name or code.title(), time.fromisoformat(start), time.fromisoformat(end),
                       timezone_name, valid_from, valid_to)


def bobinas(**kwargs):
    return [schedule("DIA", "07:00", "19:00", name="Día", **kwargs), schedule("NOCHE", "19:00", "07:00", name="Noche", **kwargs)]


class PureResolutionTests(unittest.TestCase):
    def check(self, captured_at, shift_code, operating_date, schedules=None):
        resolved = resolve_shift_from_schedules(schedules or bobinas(), captured_at)
        self.assertEqual((resolved.shift_code, resolved.operating_date), (shift_code, operating_date), captured_at.isoformat())
        return resolved

    def test_boundaries_around_midnight_and_shift_changes(self):
        cases = [
            (at(2026, 10, 6, 6, 59), "NOCHE", date(2026, 10, 5)),
            (at(2026, 10, 6, 7, 0), "DIA", date(2026, 10, 6)),
            (at(2026, 10, 6, 18, 59, 59), "DIA", date(2026, 10, 6)),
            (at(2026, 10, 6, 19, 0), "NOCHE", date(2026, 10, 6)),
            (at(2026, 10, 6, 23, 59, 59), "NOCHE", date(2026, 10, 6)),
            (at(2026, 10, 7, 0, 0), "NOCHE", date(2026, 10, 6)),
            (at(2026, 10, 7, 6, 59, 59), "NOCHE", date(2026, 10, 6)),
            (at(2026, 10, 7, 7, 0), "DIA", date(2026, 10, 7)),
        ]
        for captured_at, code, operating in cases:
            with self.subTest(captured_at.isoformat()):
                self.check(captured_at, code, operating)

    def test_intervals_are_half_open(self):
        self.check(at(2026, 10, 6, 7, 0, 0), "DIA", date(2026, 10, 6))  # start belongs to the shift that starts
        self.check(at(2026, 10, 6, 19, 0, 0), "NOCHE", date(2026, 10, 6))  # end of DIA belongs to NOCHE
        resolved = resolve_shift_from_schedules(bobinas(), at(2026, 10, 6, 18, 59, 59).replace(microsecond=999999))
        self.assertEqual(resolved.shift_code, "DIA")

    def test_utc_input_is_converted_with_the_schedule_timezone(self):
        resolved = self.check(datetime(2026, 10, 7, 3, 0, tzinfo=timezone.utc), "NOCHE", date(2026, 10, 6))
        self.assertEqual(resolved.local_captured_at, at(2026, 10, 6, 23, 0))
        self.assertEqual(resolved.local_captured_at.utcoffset(), timedelta(hours=-4))
        self.assertEqual(str(resolved.local_captured_at.tzinfo), "America/La_Paz")
        self.check(datetime(2026, 10, 6, 11, 0, tzinfo=timezone.utc), "DIA", date(2026, 10, 6))  # 07:00 La Paz
        self.check(datetime(2026, 10, 6, 10, 59, 59, tzinfo=timezone.utc), "NOCHE", date(2026, 10, 5))  # 06:59:59 La Paz
        # An aware datetime with another fixed offset describes the same instant.
        self.check(datetime(2026, 10, 7, 5, 0, tzinfo=timezone(timedelta(hours=2))), "NOCHE", date(2026, 10, 6))

    def test_result_does_not_depend_on_the_operating_system_timezone(self):
        if not hasattr(time_module, "tzset"):
            self.skipTest("time.tzset no está disponible en esta plataforma")
        instant = datetime(2026, 10, 7, 3, 0, tzinfo=timezone.utc)
        results = set()
        try:
            for system_zone in ("UTC", "Asia/Tokyo", "America/Los_Angeles"):
                with patch.dict(os.environ, {"TZ": system_zone}):
                    time_module.tzset()
                    resolved = resolve_shift_from_schedules(bobinas(), instant)
                    results.add((resolved.shift_code, resolved.operating_date, resolved.local_captured_at))
        finally:
            time_module.tzset()
        self.assertEqual(len(results), 1)

    def test_resolved_shift_carries_the_schedule_identity(self):
        schedules = bobinas()
        resolved = resolve_shift_from_schedules(schedules, at(2026, 10, 6, 8, 0))
        night, day = schedules[1], schedules[0]
        self.assertEqual((resolved.shift_schedule_id, resolved.shift_id, resolved.shift_name),
                         (day.shift_schedule_id, day.shift_id, "Día"))
        self.assertNotEqual(resolved.shift_schedule_id, night.shift_schedule_id)

    def test_new_years_eve_night_belongs_to_the_previous_operating_date(self):
        self.check(at(2026, 1, 1, 3, 0), "NOCHE", date(2025, 12, 31), schedules=bobinas(valid_from=date(2025, 1, 1)))

    def test_three_shift_conversion_style_configuration(self):
        three = [schedule("MANANA", "06:00", "14:00"), schedule("TARDE", "14:00", "22:00"), schedule("NOCHE", "22:00", "06:00")]
        self.check(at(2026, 10, 6, 5, 59), "NOCHE", date(2026, 10, 5), three)
        self.check(at(2026, 10, 6, 6, 0), "MANANA", date(2026, 10, 6), three)
        self.check(at(2026, 10, 6, 14, 0), "TARDE", date(2026, 10, 6), three)
        self.check(at(2026, 10, 6, 22, 0), "NOCHE", date(2026, 10, 6), three)

    def test_each_schedule_uses_its_own_timezone(self):
        utc_day = [schedule("DIA", "07:00", "19:00", timezone_name="UTC")]
        self.check(datetime(2026, 10, 6, 8, 0, tzinfo=timezone.utc), "DIA", date(2026, 10, 6), utc_day)
        with self.assertRaises(ShiftResolutionError):  # 08:00 UTC is 04:00 in La Paz, but the schedule is defined in UTC
            resolve_shift_from_schedules(utc_day, datetime(2026, 10, 6, 20, 0, tzinfo=timezone.utc))


class PureValidityTests(unittest.TestCase):
    def resolve(self, schedules, captured_at):
        return resolve_shift_from_schedules(schedules, captured_at)

    def test_a_schedule_is_not_valid_before_valid_from_even_after_midnight_of_that_date(self):
        # 2026-10-06 06:00 is the tail of the night shift whose operating date is 2026-10-05.
        starting = bobinas(valid_from=date(2026, 10, 6))
        with self.assertRaises(ShiftResolutionError) as raised:
            self.resolve(starting, at(2026, 10, 6, 6, 0))
        self.assertEqual(raised.exception.code, SHIFT_NOT_CONFIGURED)

    def test_valid_from_date_itself_is_valid_from_the_evening(self):
        starting = bobinas(valid_from=date(2026, 10, 6))
        self.assertEqual(self.resolve(starting, at(2026, 10, 6, 19, 0)).operating_date, date(2026, 10, 6))
        self.assertEqual(self.resolve(starting, at(2026, 10, 6, 7, 0)).shift_code, "DIA")
        self.assertEqual(self.resolve(starting, at(2026, 10, 7, 2, 0)).operating_date, date(2026, 10, 6))

    def test_versions_hand_over_at_the_operating_date_not_the_calendar_date(self):
        old = [schedule("NOCHE", "19:00", "07:00", valid_to=date(2026, 10, 5), name="Noche v1")]
        new = [schedule("NOCHE", "20:00", "08:00", valid_from=date(2026, 10, 6), name="Noche v2")]
        resolved = self.resolve(old + new, at(2026, 10, 6, 6, 0))  # still operating date 10-05 -> old version
        self.assertEqual((resolved.shift_name, resolved.operating_date), ("Noche v1", date(2026, 10, 5)))
        resolved = self.resolve(old + new, at(2026, 10, 7, 7, 30))  # operating date 10-06 -> new version
        self.assertEqual((resolved.shift_name, resolved.operating_date), ("Noche v2", date(2026, 10, 6)))

    def test_valid_to_includes_the_whole_night_that_starts_on_that_date(self):
        ending = bobinas(valid_to=date(2026, 10, 6))
        self.assertEqual(self.resolve(ending, at(2026, 10, 6, 19, 0)).operating_date, date(2026, 10, 6))
        self.assertEqual(self.resolve(ending, at(2026, 10, 7, 3, 0)).operating_date, date(2026, 10, 6))  # after midnight, still valid
        self.assertEqual(self.resolve(ending, at(2026, 10, 7, 6, 59, 59)).shift_code, "NOCHE")
        for beyond in (at(2026, 10, 7, 7, 0), at(2026, 10, 7, 19, 0), at(2026, 10, 8, 1, 0)):
            with self.subTest(beyond.isoformat()), self.assertRaises(ShiftResolutionError) as raised:
                self.resolve(ending, beyond)
            self.assertEqual(raised.exception.code, SHIFT_NOT_CONFIGURED)

    def test_valid_to_on_a_day_shift_ends_with_that_operating_date(self):
        ending = [schedule("DIA", "07:00", "19:00", valid_to=date(2026, 10, 6))]
        self.assertEqual(self.resolve(ending, at(2026, 10, 6, 18, 59)).shift_code, "DIA")
        with self.assertRaises(ShiftResolutionError):
            self.resolve(ending, at(2026, 10, 7, 8, 0))


class PureInvalidConfigurationTests(unittest.TestCase):
    def code_of(self, schedules, captured_at):
        with self.assertRaises(ShiftResolutionError) as raised:
            resolve_shift_from_schedules(schedules, captured_at)
        return raised.exception.code

    def test_naive_captured_at_is_rejected(self):
        self.assertEqual(self.code_of(bobinas(), datetime(2026, 10, 6, 8, 0)), SHIFT_INVALID_CAPTURED_AT)
        self.assertEqual(self.code_of(bobinas(), "2026-10-06T08:00:00-04:00"), SHIFT_INVALID_CAPTURED_AT)

    def test_invalid_timezone_is_rejected(self):
        self.assertEqual(self.code_of([schedule("DIA", "07:00", "19:00", timezone_name="Mars/Olympus")], at(2026, 10, 6, 8)),
                         SHIFT_INVALID_TIMEZONE)
        self.assertEqual(self.code_of([schedule("DIA", "07:00", "19:00", timezone_name="")], at(2026, 10, 6, 8)),
                         SHIFT_INVALID_TIMEZONE)

    def test_no_schedules_means_not_configured(self):
        self.assertEqual(self.code_of([], at(2026, 10, 6, 8)), SHIFT_NOT_CONFIGURED)

    def test_a_gap_between_shifts_is_not_configured(self):
        gap = [schedule("DIA", "07:00", "12:00"), schedule("TARDE", "14:00", "19:00")]
        self.assertEqual(self.code_of(gap, at(2026, 10, 6, 13, 0)), SHIFT_NOT_CONFIGURED)
        self.assertEqual(resolve_shift_from_schedules(gap, at(2026, 10, 6, 14, 0)).shift_code, "TARDE")

    def test_overlapping_schedules_are_ambiguous_and_never_pick_the_first(self):
        overlap = [schedule("DIA", "07:00", "19:00"), schedule("EXTRA", "18:00", "22:00")]
        self.assertEqual(self.code_of(overlap, at(2026, 10, 6, 18, 30)), SHIFT_AMBIGUOUS)
        self.assertEqual(self.code_of(list(reversed(overlap)), at(2026, 10, 6, 18, 30)), SHIFT_AMBIGUOUS)
        self.assertEqual(resolve_shift_from_schedules(overlap, at(2026, 10, 6, 10, 0)).shift_code, "DIA")  # outside the overlap

    def test_overlap_across_midnight_is_ambiguous(self):
        overlap = [schedule("NOCHE", "19:00", "07:00"), schedule("MADRUGADA", "02:00", "05:00")]
        self.assertEqual(self.code_of(overlap, at(2026, 10, 7, 3, 0)), SHIFT_AMBIGUOUS)

    def test_equal_start_and_end_is_an_invalid_schedule(self):
        self.assertEqual(self.code_of([schedule("DIA", "07:00", "07:00")], at(2026, 10, 6, 8)), SHIFT_INVALID_SCHEDULE)

    def test_non_overlapping_versions_are_not_ambiguous(self):
        versions = [schedule("DIA", "07:00", "19:00", valid_to=date(2026, 9, 30)), schedule("DIA", "08:00", "20:00", valid_from=date(2026, 10, 1))]
        self.assertEqual(resolve_shift_from_schedules(versions, at(2026, 10, 6, 19, 30)).shift_code, "DIA")


# ---------------------------------------------------------------------------------------------------
# SQL integration
# ---------------------------------------------------------------------------------------------------

TEST_URL = settings.test_database_url.get_secret_value() if settings.test_database_url else None
STATE = {}


def _admin():
    return psycopg.connect(make_conninfo(TEST_URL, dbname="postgres"), autocommit=True, connect_timeout=5)


def setUpModule():
    """One ephemeral migrated database holding the real Bobinas bundle (independent of what vinto_test contains)."""
    name = f"vinto_shifts_{uuid4().hex[:10]}_test"
    assert is_test_database_name(name)
    with _admin() as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    STATE["database"] = name
    options = "-c statement_timeout=60000 -c lock_timeout=30000"
    with connect_test_database(make_conninfo(TEST_URL, dbname=name), autocommit=True, connect_timeout=5, options=options) as connection:
        with contextlib.redirect_stdout(io.StringIO()):
            apply_migrations(connection, read_migrations())
        reference.apply(connection, load_bundle())


def tearDownModule():
    name = STATE.get("database")
    if name:
        assert is_test_database_name(name)
        with _admin() as admin:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


class RealBobinasBundleTests(unittest.TestCase):
    """The schedules imported from backend/seed_data resolve exactly like the specification."""

    @classmethod
    def setUpClass(cls):
        cls.connection = connect_test_database(make_conninfo(TEST_URL, dbname=STATE["database"]), connect_timeout=5)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def test_specified_boundaries_resolve_from_postgresql(self):
        cases = [
            (at(2026, 10, 6, 6, 59), "NOCHE", date(2026, 10, 5)),
            (at(2026, 10, 6, 7, 0), "DIA", date(2026, 10, 6)),
            (at(2026, 10, 6, 18, 59, 59), "DIA", date(2026, 10, 6)),
            (at(2026, 10, 6, 19, 0), "NOCHE", date(2026, 10, 6)),
            (at(2026, 10, 6, 23, 59, 59), "NOCHE", date(2026, 10, 6)),
            (at(2026, 10, 7, 0, 0), "NOCHE", date(2026, 10, 6)),
            (at(2026, 10, 7, 6, 59, 59), "NOCHE", date(2026, 10, 6)),
            (at(2026, 10, 7, 7, 0), "DIA", date(2026, 10, 7)),
            (datetime(2026, 10, 7, 3, 0, tzinfo=timezone.utc), "NOCHE", date(2026, 10, 6)),
        ]
        for captured_at, code, operating in cases:
            with self.subTest(captured_at.isoformat()):
                resolved = resolve_shift(self.connection, captured_at, sector_code="BOBINAS")
                self.assertEqual((resolved.shift_code, resolved.operating_date), (code, operating))

    def test_resolved_identifiers_match_the_database_rows(self):
        resolved = resolve_shift(self.connection, at(2026, 10, 6, 8, 0), sector_code="BOBINAS")
        row = self.connection.execute(
            """SELECT sc.id,sc.shift_id,sh.code,sh.name FROM vinto_config.shift_schedule sc JOIN vinto_config.shift sh ON sh.id=sc.shift_id
               WHERE sh.code='DIA'""").fetchone()
        self.assertEqual((resolved.shift_schedule_id, resolved.shift_id, resolved.shift_code, resolved.shift_name), row)
        self.assertEqual(resolved.shift_name, "Día")
        self.assertEqual(resolved.local_captured_at, at(2026, 10, 6, 8, 0))

    def test_sector_id_and_sector_code_are_equivalent(self):
        sector_id = self.connection.execute("SELECT id FROM vinto_master.sector WHERE code='BOBINAS'").fetchone()[0]
        by_id = resolve_shift(self.connection, at(2026, 10, 6, 20, 0), sector_id=sector_id)
        by_code = resolve_shift(self.connection, at(2026, 10, 6, 20, 0), sector_code="BOBINAS")
        self.assertEqual(by_id, by_code)
        self.assertEqual(by_id.shift_code, "NOCHE")

    def test_before_the_provisional_valid_from_nothing_is_configured(self):
        with self.assertRaises(ShiftResolutionError) as raised:
            resolve_shift(self.connection, at(2026, 1, 1, 3, 0), sector_code="BOBINAS")  # night of 2025-12-31
        self.assertEqual(raised.exception.code, SHIFT_NOT_CONFIGURED)
        self.assertEqual(resolve_shift(self.connection, at(2026, 1, 1, 7, 0), sector_code="BOBINAS").operating_date, date(2026, 1, 1))

    def test_unknown_sector_is_a_clear_error(self):
        for arguments in ({"sector_code": "NO-EXISTE"}, {"sector_id": uuid4()}):
            with self.subTest(arguments), self.assertRaises(ShiftResolutionError) as raised:
                resolve_shift(self.connection, at(2026, 10, 6, 8, 0), **arguments)
            self.assertEqual(raised.exception.code, SHIFT_SECTOR_NOT_FOUND)

    def test_naive_datetime_fails_before_querying(self):
        with self.assertRaises(ShiftResolutionError) as raised:
            resolve_shift(None, datetime(2026, 10, 6, 8, 0), sector_code="BOBINAS")  # no connection needed: it never gets there
        self.assertEqual(raised.exception.code, SHIFT_INVALID_CAPTURED_AT)

    def test_exactly_one_sector_argument_is_required(self):
        with self.assertRaises(ValueError):
            resolve_shift(self.connection, at(2026, 10, 6, 8, 0))
        with self.assertRaises(ValueError):
            resolve_shift(self.connection, at(2026, 10, 6, 8, 0), sector_code="BOBINAS", sector_id=uuid4())


class FixtureSchedulesTests(unittest.TestCase):
    """Temporary sector and schedules inside a rolled-back transaction of the shared test database."""

    def setUp(self):
        self.connection = connect_test_database(connect_timeout=5, options="-c statement_timeout=10000 -c lock_timeout=3000")
        self.addCleanup(self.connection.close)
        self.addCleanup(self.connection.rollback)
        suffix = uuid4().hex[:8].upper()
        self.sector_code = f"TECH-SHIFT-{suffix}"
        self.sector_id = self.connection.execute("INSERT INTO vinto_master.sector (code,name) VALUES (%s,%s) RETURNING id",
                                                 (self.sector_code, "Technical shift fixture")).fetchone()[0]
        self.suffix = suffix

    def add(self, code, start, end, *, timezone_name="America/La_Paz", valid_from="2026-01-01", valid_to=None):
        shift_id = self.connection.execute("INSERT INTO vinto_config.shift (code,name) VALUES (%s,%s) RETURNING id",
                                           (f"{code}-{self.suffix}", f"Turno {code}")).fetchone()[0]
        return self.connection.execute(
            """INSERT INTO vinto_config.shift_schedule (shift_id,sector_id,starts_at,ends_at,timezone,valid_from,valid_to)
               VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (shift_id, self.sector_id, start, end, timezone_name, valid_from, valid_to)).fetchone()[0]

    def resolve(self, captured_at):
        return resolve_shift(self.connection, captured_at, sector_code=self.sector_code)

    def test_sector_without_schedules_is_not_configured(self):
        with self.assertRaises(ShiftResolutionError) as raised:
            self.resolve(at(2026, 10, 6, 8))
        self.assertEqual(raised.exception.code, SHIFT_NOT_CONFIGURED)

    def test_gap_between_schedules_is_not_configured(self):
        self.add("A", "07:00", "12:00")
        self.add("B", "14:00", "19:00")
        with self.assertRaises(ShiftResolutionError) as raised:
            self.resolve(at(2026, 10, 6, 13))
        self.assertEqual(raised.exception.code, SHIFT_NOT_CONFIGURED)
        self.assertTrue(self.resolve(at(2026, 10, 6, 14)).shift_code.startswith("B-"))

    def test_overlapping_schedules_are_ambiguous(self):
        self.add("A", "07:00", "19:00")
        self.add("B", "18:00", "22:00")
        with self.assertRaises(ShiftResolutionError) as raised:
            self.resolve(at(2026, 10, 6, 18, 30))
        self.assertEqual(raised.exception.code, SHIFT_AMBIGUOUS)

    def test_invalid_stored_timezone_is_rejected(self):
        self.add("A", "07:00", "19:00", timezone_name="Not/AZone")
        with self.assertRaises(ShiftResolutionError) as raised:
            self.resolve(at(2026, 10, 6, 8))
        self.assertEqual(raised.exception.code, SHIFT_INVALID_TIMEZONE)

    def test_timezone_comes_from_each_stored_schedule(self):
        self.add("A", "07:00", "19:00", timezone_name="UTC")
        resolved = self.resolve(at(2026, 10, 6, 8))  # 08:00 La Paz = 12:00 UTC: inside a schedule defined in UTC
        self.assertEqual((resolved.operating_date, resolved.local_captured_at.hour), (date(2026, 10, 6), 12))
        self.assertEqual(str(resolved.local_captured_at.tzinfo), "UTC")
        with self.assertRaises(ShiftResolutionError) as raised:
            self.resolve(at(2026, 10, 6, 21))  # 21:00 La Paz = 01:00 UTC: outside
        self.assertEqual(raised.exception.code, SHIFT_NOT_CONFIGURED)

    def test_validity_dates_are_stored_and_applied_to_the_operating_date(self):
        self.add("N", "19:00", "07:00", valid_from="2026-10-06", valid_to="2026-10-06")
        with self.assertRaises(ShiftResolutionError):
            self.resolve(at(2026, 10, 6, 6, 0))  # operating date 2026-10-05: before valid_from
        self.assertEqual(self.resolve(at(2026, 10, 6, 19, 0)).operating_date, date(2026, 10, 6))
        self.assertEqual(self.resolve(at(2026, 10, 7, 6, 59)).operating_date, date(2026, 10, 6))  # valid_to night tail
        with self.assertRaises(ShiftResolutionError):
            self.resolve(at(2026, 10, 7, 19, 0))  # operating date 2026-10-07: after valid_to

    def deactivate(self, schedule_id):
        self.connection.execute("UPDATE vinto_config.shift SET active=false WHERE id=(SELECT shift_id FROM vinto_config.shift_schedule WHERE id=%s)",
                                (schedule_id,))

    def test_inactive_shift_does_not_resolve_even_if_hour_and_validity_match(self):
        schedule_id = self.add("A", "07:00", "19:00")
        self.deactivate(schedule_id)
        with self.assertRaises(ShiftResolutionError) as raised:
            self.resolve(at(2026, 10, 6, 8))
        self.assertEqual(raised.exception.code, SHIFT_NOT_CONFIGURED)

    def test_inactive_overlapping_shift_is_ignored_instead_of_ambiguous(self):
        active_id = self.add("ACTIVO", "07:00", "19:00")
        self.deactivate(self.add("INACTIVO", "08:00", "20:00"))
        resolved = self.resolve(at(2026, 10, 6, 10))  # both would match; only the active one counts
        self.assertEqual(resolved.shift_schedule_id, active_id)
        self.assertTrue(resolved.shift_code.startswith("ACTIVO-"))
        with self.assertRaises(ShiftResolutionError) as raised:  # 19:30 is only covered by the inactive shift
            self.resolve(at(2026, 10, 6, 19, 30))
        self.assertEqual(raised.exception.code, SHIFT_NOT_CONFIGURED)

    def test_deactivating_a_shift_that_used_to_resolve_stops_it_resolving(self):
        schedule_id = self.add("A", "07:00", "19:00")
        self.assertEqual(self.resolve(at(2026, 10, 6, 8)).shift_schedule_id, schedule_id)
        self.deactivate(schedule_id)
        with self.assertRaises(ShiftResolutionError) as raised:
            self.resolve(at(2026, 10, 6, 8))
        self.assertEqual(raised.exception.code, SHIFT_NOT_CONFIGURED)
        self.connection.execute("UPDATE vinto_config.shift SET active=true WHERE id=(SELECT shift_id FROM vinto_config.shift_schedule WHERE id=%s)",
                                (schedule_id,))
        self.assertEqual(self.resolve(at(2026, 10, 6, 8)).shift_schedule_id, schedule_id)  # reactivation resolves again

    def test_resolver_only_reads(self):
        self.add("A", "07:00", "19:00")
        before = self.connection.execute("SELECT count(*) FROM vinto_audit.audit_event").fetchone()[0]
        self.resolve(at(2026, 10, 6, 8))
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_audit.audit_event").fetchone()[0], before)


if __name__ == "__main__":
    unittest.main()
