"""OFF-04.6: the DATABASE-backed bobbin context and the central validation of by-bobbin forms against a REAL F3 bobbin on a disposable PostgreSQL database.

The bobbin is created through the repository's own F3 route (work order, assignment, capture, numbered bobbin); everything else is read-only. Synthetic data only."""
import json
from contextlib import nullcontext
from types import SimpleNamespace as NS
from uuid import UUID, uuid4

import psycopg

try:
    import test_f3_bobbins_api as f3
except ModuleNotFoundError:
    import tests.test_f3_bobbins_api as f3

from app.ephemeral_db import build_reference_template, drop_database
from app.offline_quality import bobbin_context
from app.offline_quality.central import QualityPayloadValidator
from app.offline_scope.signing import sign_scope
from app.qa_pilot_auth import signer_from_seed
from tests import off045b06b_support as S
from tests import off046_support as T

SECTORS = frozenset({"BOBINAS"})


def setUpModule():
    f3.STATE["template"] = build_reference_template("vinto_off046_tpl")


def tearDownModule():
    if f3.STATE.get("template"):
        drop_database(f3.STATE.pop("template"))


class DbBobbinContextTests(f3.BobbinApiCase):
    async def real_bobbin(self):
        _, assignment = await self.assignment("MP1")
        created = await self.post(self.payload(assignment))
        self.assertEqual(created.status, 201, created.text)
        bobbin_id = created.json()["bobbin"]["id"]
        code = self.scalar("SELECT code FROM vinto_txn.bobbin WHERE id = %s", (bobbin_id,))
        return bobbin_id, code

    def validator(self):
        return QualityPayloadValidator(lambda: nullcontext(self.connection), evaluate_bobbin_context=True)

    def capture(self, form, bobbin_id, values, *, snapshot=None, context=None, version=None, machine="MP1"):
        snapshot = snapshot or str(uuid4())
        ctx = bobbin_context.load_by_id(self.connection, bobbin_id, SECTORS)
        context = context or (bobbin_context.context_version(snapshot, bobbin_id, ctx["context_digest"]) if ctx else "x" * 64)
        return NS(form_code=form, machine_code=machine, form_version=version or T.version(form), scope_snapshot_id=snapshot, context_version=context,
                  payload={"synthetic": True, "payload": values, "bobbin": {"bobbin_id": str(bobbin_id)}})

    async def test_the_context_of_a_real_bobbin_is_read_from_its_historical_chain(self):
        bobbin_id, code = await self.real_bobbin()
        ctx = bobbin_context.load_by_id(self.connection, bobbin_id, SECTORS)
        self.assertEqual((ctx["bobbin_id"], ctx["bobbin_code"], ctx["machine_code"], ctx["is_mother"]), (bobbin_id, code, "MP1", False))
        self.assertTrue(all(ctx[k] for k in ("work_order", "line_code", "pv_reference", "article_code", "shift_code", "operating_date")))
        self.assertEqual(ctx["context_digest"], bobbin_context.context_digest(ctx))
        self.assertEqual(len(ctx["context_digest"]), 64)
        self.assertEqual([c["bobbin_id"] for c in bobbin_context.load_by_code(self.connection, "MP1", code, SECTORS)], [bobbin_id])
        self.assertEqual(bobbin_context.load_by_code(self.connection, "MP3", code, SECTORS), [])               # another machine
        self.assertIsNone(bobbin_context.load_by_id(self.connection, bobbin_id, frozenset()))                    # outside the user's sectors: invisible
        self.assertIsNone(bobbin_context.load_by_id(self.connection, str(uuid4()), SECTORS))
        self.assertIsNone(bobbin_context.load_by_id(self.connection, "not-a-uuid", SECTORS))

    async def test_central_validation_of_every_by_bobbin_form_against_the_real_bobbin(self):
        bobbin_id, code = await self.real_bobbin()
        principal = NS(sectors=SECTORS)
        for form in T.BY_BOBBIN:
            values, expected = T.valid_values(form, code)
            verdict = self.validator().validate(principal, self.capture(form, bobbin_id, values))
            self.assertTrue(verdict.ok, (form, verdict.errors))
            self.assertEqual((verdict.context_kind, verdict.version_mismatch, verdict.calculated), ("same", False, expected), form)
            self.assertEqual(verdict.published_version, T.version(form), form)
            # the same content with a context digest that is not the database's: incompatible (central review), the content itself still valid
            stale = self.validator().validate(principal, self.capture(form, bobbin_id, values, context="0" * 64))
            self.assertEqual((stale.ok, stale.context_kind), (True, "incompatible_change"), form)

    async def test_unknown_bobbin_wrong_machine_and_declared_number_are_refused_by_the_database_route_rules(self):
        bobbin_id, code = await self.real_bobbin()
        principal = NS(sectors=SECTORS)
        values, _ = T.valid_values("VINTO-P1-28", code)
        unknown = self.validator().validate(principal, self.capture("VINTO-P1-28", str(uuid4()), values))
        self.assertEqual((unknown.ok, unknown.errors, unknown.context_kind), (False, (("*", "bobbin_unknown"),), "incompatible_change"))
        wrong_machine = self.validator().validate(principal, self.capture("VINTO-P1-28", bobbin_id, values, machine="MP3"))
        self.assertEqual(wrong_machine.errors, (("*", "bobbin_machine_mismatch"),))
        bad_number = self.validator().validate(principal, self.capture("VINTO-P1-28", bobbin_id, {**values, "numero_de_bobina": code + "-X"}))
        self.assertEqual(bad_number.errors, (("numero_de_bobina", "bobbin_mismatch"),))                          # the SAME online rule (_check_declared_bobbin)
        no_ref = self.validator().validate(principal, NS(**{**self.capture("VINTO-P1-28", bobbin_id, values).__dict__, "payload": {"synthetic": True, "payload": values}}))
        self.assertEqual(no_ref.errors, (("*", "bobbin_required"),))
        stale = self.validator().validate(principal, self.capture("VINTO-P1-28", bobbin_id, values, version=T.version("VINTO-P1-28") + 1))
        self.assertTrue(stale.ok and stale.version_mismatch)                                                      # a device that prepared another published version

    async def test_the_validation_is_read_only(self):
        bobbin_id, code = await self.real_bobbin()
        before = {t: self.scalar(f"SELECT count(*) FROM vinto_txn.{t}") for (t,) in self.connection.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='vinto_txn'").fetchall()}
        values, _ = T.valid_values("VINTO-P1-20", code)
        self.assertTrue(self.validator().validate(NS(sectors=SECTORS), self.capture("VINTO-P1-20", bobbin_id, values)).ok)
        after = {t: self.scalar(f"SELECT count(*) FROM vinto_txn.{t}") for t in before}
        self.assertEqual(before, after)                                                                             # no capture, no release, nothing written

    async def test_the_real_issuer_function_needs_a_signed_scope_with_a_by_bobbin_grant(self):
        bobbin_id, code = await self.real_bobbin()
        signer = signer_from_seed(S.new_seed())
        user = NS(user_id=uuid4(), must_change=False, sectors=SECTORS)
        device = uuid4()
        while device.version != 4:
            device = uuid4()
        def scope(operation, subject=None):
            return sign_scope({"schema": "vinto.offline.scope.v1", "issuer": "vinto-backend", "audience": "vinto-offline-readiness", "snapshot_id": str(uuid4()),
                               "subject_user_id": str(subject or user.user_id), "device_key": str(device), "issued_at": "2026-11-20T00:00:00Z", "kind": "scope_readiness_only",
                               "captures_enabled": False, "form_scopes": [{"machine_code": "MP1", "form_code": "VINTO-P1-20", "form_version": 1, "grant_id": str(uuid4()), "operation": operation}]}, signer=signer)
        ok = bobbin_context.issue_for_code(self.connection, user, device_key=device, machine_code="MP1", bobbin_code=code, signed_scope=scope("quality_bobbin_capture"), signer=signer)
        self.assertEqual([c["bobbin_id"] for c in ok["contexts"]], [bobbin_id])
        for bad in (scope("quality_machine_capture"), scope("quality_bobbin_capture", subject=uuid4())):
            with self.assertRaises(bobbin_context.BobbinContextDenied):
                bobbin_context.issue_for_code(self.connection, user, device_key=device, machine_code="MP1", bobbin_code=code, signed_scope=bad, signer=signer)
        with self.assertRaises(bobbin_context.BobbinContextDenied):                                                 # scope signed by another key
            bobbin_context.issue_for_code(self.connection, user, device_key=device, machine_code="MP1", bobbin_code=code, signed_scope=scope("quality_bobbin_capture"), signer=signer_from_seed(S.new_seed()))
