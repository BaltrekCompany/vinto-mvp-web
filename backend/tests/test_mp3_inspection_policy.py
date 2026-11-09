"""Pruebas de política MP3: máquina autorizada y cupo por turno.
No requieren base productiva; integración PG17 completa se añadirá a la suite siguiente.
"""
import unittest
from datetime import date

from app.capture_errors import FormNotAvailableError, ShiftCaptureAlreadyExistsError
from app import mp3_inspection_policy as p


class FakeConn:
    def __init__(self, row=None):
        self.row = row
        self.calls = []

    def execute(self, query, params):
        self.calls.append((query, params))
        return self

    def fetchone(self):
        return self.row


class MP3PolicyTests(unittest.TestCase):
    def test_separates_legacy_from_rg01_without_restricting_other_forms(self):
        self.assertTrue(p.allowed_for_machine("VINTO-P1-01", "MP1"))
        self.assertFalse(p.allowed_for_machine("VINTO-P1-01", "MP3"))
        self.assertTrue(p.allowed_for_machine("VINTO-MP3-01", "MP3"))
        self.assertFalse(p.allowed_for_machine("VINTO-MP3-01", "MP1"))
        self.assertTrue(p.allowed_for_machine("VINTO-P1-06", "MP3"))

    def test_rejects_direct_api_wrong_machine(self):
        conn = FakeConn(("MP1",))
        with self.assertRaises(FormNotAvailableError):
            p.assert_form_machine(conn, p.RG_MP3_FORM_CODE, "machine-id")
        self.assertEqual(conn.calls[0][1], ("machine-id",))

        conn = FakeConn(("MP3",))
        with self.assertRaises(FormNotAvailableError):
            p.assert_form_machine(conn, p.SHARED_OLD_FORM_CODE, "machine-id")

    def test_accepts_only_matching_form_machine_pairs(self):
        for code, machine in [(p.RG_MP3_FORM_CODE, "MP3"), (p.SHARED_OLD_FORM_CODE, "MP1")]:
            p.assert_form_machine(FakeConn((machine,)), code, "m-id")

    def test_unrelated_forms_do_not_add_an_extra_db_query(self):
        c = FakeConn()
        p.assert_form_machine(c, "VINTO-P1-06", "id")
        self.assertEqual(c.calls, [])

    def test_checks_one_slot_per_machine_day_shift_and_form(self):
        c = FakeConn(None)
        p.assert_one_per_shift(c, form_code=p.RG_MP3_FORM_CODE, machine_id="machine",
                               operating_date=date(2026, 11, 9), shift_schedule_id="schedule")
        self.assertEqual(len(c.calls), 1)
        query, params = c.calls[0]
        self.assertIn("existing_schedule.shift_id = new_schedule.shift_id", query)
        self.assertIn("c.operating_date = %s", query)
        self.assertIn("c.status IN ('submitted', 'closed', 'blocked')", query)
        self.assertEqual(params, ("schedule", p.RG_MP3_FORM_CODE, "machine", date(2026, 11, 9)))

    def test_second_capture_of_the_same_shift_is_a_conflict(self):
        c = FakeConn((1,))
        with self.assertRaises(ShiftCaptureAlreadyExistsError):
            p.assert_one_per_shift(c, form_code=p.RG_MP3_FORM_CODE, machine_id="machine",
                                   operating_date=date(2026, 11, 9), shift_schedule_id="schedule")

    def test_other_forms_do_not_have_shift_limit(self):
        c = FakeConn((1,))
        p.assert_one_per_shift(c, form_code="VINTO-P1-01", machine_id="machine",
                               operating_date=date(2026, 11, 9), shift_schedule_id="schedule")
        self.assertEqual(c.calls, [])


if __name__ == "__main__":
    unittest.main()
