"""No-DB compatibility tests for OFF-255 signed bobbin context."""
import hashlib
import unittest
from unittest.mock import MagicMock
from app.quality.offline_bobbin_context import quality_bobbin_context_digest
from app.quality.offline_capture_scope import _canonical


class OfflineMotherDigestTests(unittest.TestCase):
    def _digest(self,row):
        conn=MagicMock()
        conn.execute.return_value.fetchone.return_value=row
        return quality_bobbin_context_digest(conn,"mother-or-bobbin","COPASA",["REBOBINADO"]),conn

    def test_real_mother_without_quality_release_is_supported(self):
        row=("m25a","COPASA","origin", "assignment", "2026-11-13",
             "shift",None,"rewind-capture",None)
        digest,conn=self._digest(row)
        self.assertEqual(len(digest),64)
        self.assertIn("LEFT JOIN vinto_txn.quality_release",conn.execute.call_args.args[0])
        self.assertIn("b.rewind_child_position IS NULL",conn.execute.call_args.args[0])
        self.assertEqual(digest,hashlib.sha256(_canonical(dict(zip(
            ("bobbin_id","machine_code","source_capture_id","assignment_id",
             "operating_date","shift_schedule_id","quality_status","mother_capture_id","child_position"),
            [str(v) if v is not None else None for v in row],
        )))).hexdigest())

    def test_old_f3_digest_remains_byte_identical(self):
        row=("b4","MP3","origin","assignment","2026-11-09","shift",
             "pending",None,None)
        digest,_=self._digest(row)
        fields=("bobbin_id","machine_code","source_capture_id","assignment_id",
                "operating_date","shift_schedule_id","quality_status","mother_capture_id","child_position")
        old=hashlib.sha256(_canonical({
            k:str(v) if v is not None else None for k,v in zip(fields,row)
        })).hexdigest()
        self.assertEqual(digest,old)

    def test_no_context_does_not_sign(self):
        digest,_=self._digest(None)
        self.assertIsNone(digest)


if __name__=="__main__":
    unittest.main()
