"""Bobbin Quality can be submitted once per (bobbin, form), regardless of
online/offline transport. Same capture_id replay remains idempotent.
No PostgreSQL connection or write required by these contract tests.
"""
import unittest
import uuid
from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from app.capture_errors import QualityBobbinFormAlreadySubmittedError
from app.quality import capture_service


class OneQualityCapturePerBobbinTests(unittest.TestCase):
    def test_distinct_capture_id_is_rejected_when_form_already_submitted(self):
        bobbin_id=uuid.uuid4()
        capture_id=uuid.uuid4()
        device_id=uuid.uuid4()
        actor_id=uuid.uuid4()
        conn=MagicMock()
        conn.transaction.return_value=nullcontext()
        queries=[]
        def execute(query,params):
            queries.append((query,params))
            answer=MagicMock()
            # first: idempotency lookup for the incoming ID (no row);
            # second: one-per-bobbin/form check (already submitted).
            answer.fetchone.return_value=None if len(queries)==1 else (uuid.uuid4(),)
            return answer
        conn.execute.side_effect=execute
        with patch.object(capture_service,"_context"), \
             patch.object(capture_service,"_bobbin_context") as context, \
             patch.object(capture_service.cs,"_lock") as lock, \
             patch.object(capture_service.cs,"_resolve_device"), \
             patch.object(capture_service.cs,"published_form_version"), \
             patch.object(capture_service,"_prepare_values",return_value=([],[],{})), \
             patch.object(capture_service,"_check_declared_bobbin"), \
             patch.object(capture_service,"_check_minimums"):
            context.return_value=type("Ctx",(),{"machine_id":uuid.uuid4(),"is_mother":False})()
            with self.assertRaises(QualityBobbinFormAlreadySubmittedError) as raised:
                capture_service.submit_quality_capture(
                    conn,actor_id=actor_id,bobbin_id=bobbin_id,
                    capture_id=capture_id,form_code="VINTO-P1-24",
                    device_key=device_id,values={},sectors=("CALIDAD",),
                )
        self.assertEqual(raised.exception.http_status,409)
        self.assertEqual(len(queries),2)
        self.assertIn("fv.area = 'quality'",queries[1][0])
        self.assertIn("c.status IN ('submitted', 'closed')",queries[1][0])
        self.assertEqual(queries[1][1],(bobbin_id,"VINTO-P1-24"))
        self.assertTrue(any("vinto-quality-bobbin-once:" in call.args[1] for call in lock.call_args_list))
        self.assertFalse(any("INSERT" in sql for sql,_ in queries))


if __name__=="__main__":
    unittest.main()
