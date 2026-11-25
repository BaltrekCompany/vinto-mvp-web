"""No-DB safety checks for offline operational upload and original-author proof."""
import hashlib
import unittest
import uuid
from unittest.mock import patch

from fastapi import HTTPException, Response
from app.quality.offline_capture_scope import _canonical
from app.quality.offline_sync_router import OfflineQualityCaptureIn, _validate_capture, send_offline_capture


USER = uuid.UUID("b38e5e52-5e30-4f08-ae9c-644443e6f115")
DEVICE = uuid.UUID("7ebee083-730e-4d4d-ac6c-f9ea67fabce5")
SCOPE = uuid.UUID("9807c5a8-2552-44fc-a856-e7d816487f87")


class FakeUser:
    user_id = USER


def make_request(**changes):
    payload = {"synthetic": False, "payload": {"medicion": "12.0"}}
    data = {
        "capture_id": str(uuid.uuid4()),
        "author_user_id": str(USER),
        "device_key": str(DEVICE),
        "form_code": "VINTO-P1-22",
        "form_version": 2,
        "context_version": "machine-form-v2",
        "machine_code": "MP1",
        "scope_snapshot_id": str(SCOPE),
        "payload_sha256": hashlib.sha256(_canonical(payload)).hexdigest(),
        "payload": payload,
    }
    data.update(changes)
    return OfflineQualityCaptureIn(**data)


class OfflineOperationalReceiverTests(unittest.TestCase):
    def test_original_author_and_integrity_mandatory(self):
        good = make_request()
        values, bobbin = _validate_capture(good, FakeUser())
        self.assertEqual(values, {"medicion": "12.0"})
        self.assertIsNone(bobbin)
        for modified in (
            {"author_user_id":str(uuid.uuid4())},
            {"payload_sha256":"0"*64},
            {"payload":{"synthetic": True, "payload": {"medicion":"12.0"}}},
        ):
            with self.subTest(modified=modified), self.assertRaises(HTTPException):
                _validate_capture(make_request(**modified), FakeUser())

    def test_bobbin_requires_frozen_origin_context(self):
        other = uuid.uuid4()
        data = make_request(form_code="VINTO-P1-19")
        with self.assertRaises(HTTPException):
            _validate_capture(data, FakeUser())
        body = {"synthetic":False,"payload":{"peso_humedo_comando":"12"},
                "bobbin":{"bobbin_id":str(other),"context_digest":"b"*64}}
        check = make_request(
            form_code="VINTO-P1-19",payload=body,
            payload_sha256=hashlib.sha256(_canonical(body)).hexdigest())
        values, bobbin = _validate_capture(check, FakeUser())
        self.assertEqual(bobbin,str(other))
        self.assertEqual(values["peso_humedo_comando"],"12")

    def test_upload_flag_off_never_accesses_database(self):
        request=make_request()
        with patch("app.quality.offline_sync_router.settings.offline_quality_capture_enabled",False):
            with self.assertRaises(HTTPException) as raised:
                send_offline_capture(request,Response(),FakeUser(),object())
        self.assertEqual(raised.exception.status_code,503)


if __name__=="__main__":
    unittest.main()
