"""P181: baja funcional de P1-05, sin borrar definiciones ni capturas antiguas."""
import unittest
from app.capture_errors import FormNotAvailableError
from app import capture_service, mp3_inspection_policy


class Row:
    def fetchone(self):
        return ("MP3",)


class Connection:
    def execute(self, statement, arguments):
        assert "FROM vinto_master.machine" in statement
        return Row()


class P181RetirementTests(unittest.TestCase):
    def test_historical_reads_still_have_the_form_code(self):
        self.assertTrue(capture_service.is_central_form("VINTO-P1-05"))
        self.assertIn("VINTO-P1-05", capture_service.CENTRAL_FORM_CODES)

    def test_new_captures_and_offers_reject_p105_in_every_machine(self):
        for machine in ("MP1", "MP3", "COPASA"):
            self.assertFalse(mp3_inspection_policy.allowed_for_machine("VINTO-P1-05", machine))
        with self.assertRaises(FormNotAvailableError):
            mp3_inspection_policy.assert_form_machine(Connection(), "VINTO-P1-05", "ignored-id")

    def test_other_form_machine_rules_untouched(self):
        self.assertTrue(mp3_inspection_policy.allowed_for_machine("VINTO-P1-31", "MP3"))
        self.assertTrue(mp3_inspection_policy.allowed_for_machine("VINTO-P1-01", "MP1"))
        self.assertFalse(mp3_inspection_policy.allowed_for_machine("VINTO-P1-01", "MP3"))
