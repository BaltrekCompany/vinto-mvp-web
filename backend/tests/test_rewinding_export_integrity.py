"""The original reader rejects absent or damaged persisted PDF data."""
import hashlib
import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from fastapi import HTTPException

from app.rewinding_export.service import _original_pdf


class RewindingExportIntegrityTests(unittest.TestCase):
    def test_absent_damaged_and_mismatched_size_raise_503(self):
        document = b"%PDF-1.4\n%%EOF"
        checksum = hashlib.sha256(document).hexdigest()
        for stored in (
            None,
            ("rbe.pdf", b"corrupted", checksum, len(b"corrupted"), 1),
            ("rbe.pdf", document, checksum, len(document) + 1, 1),
        ):
            with self.subTest(stored=stored):
                connection = MagicMock()
                connection.execute.return_value.fetchone.return_value = stored
                with self.assertLogs("app.rewinding_export.service", level="ERROR"):
                    with self.assertRaises(HTTPException) as raised:
                        _original_pdf(connection, uuid4())
                self.assertEqual(raised.exception.status_code, 503)
