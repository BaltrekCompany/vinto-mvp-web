"""Contract gates for default-OFF authenticated Quality authority issuance."""
import unittest
from unittest.mock import patch
from fastapi import HTTPException, Response
from app.quality.offline_router import CapturePreparationRequest, prepare_capture_authority
from app.quality.offline_capture_scope import FORM_OPERATION


class FakeUser:
    user_id = "b38e5e52-5e30-4f08-ae9c-644443e6f115"


class FakeConnection:
    def transaction(self):
        raise AssertionError("Disabled issuer must not access PostgreSQL")


class OfflineAuthorityEndpointTests(unittest.TestCase):
    def test_gate_disabled_even_for_authenticated_user_with_valid_request(self):
        body = CapturePreparationRequest(
            device_key="7ebee083-730e-4d4d-ac6c-f9ea67fabce5",
            machine_code="MP1",
            form_code="VINTO-P1-19",
        )
        with patch("app.quality.offline_router.settings.offline_quality_capture_enabled", False):
            with self.assertRaises(HTTPException) as caught:
                prepare_capture_authority(body, Response(), FakeUser(), FakeConnection())
        self.assertEqual(caught.exception.status_code, 503)

    def test_release_actions_cannot_be_signed_as_quality_capture(self):
        self.assertEqual(set(FORM_OPERATION.values()), {
            "quality_machine_capture", "quality_bobbin_capture"})
        self.assertEqual(len(FORM_OPERATION), 10)


if __name__ == "__main__":
    unittest.main()
