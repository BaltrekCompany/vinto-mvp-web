"""End-to-end RBE on PostgreSQL 17 with the application role and all business triggers."""
import asyncio
import hashlib
import json
import os
import secrets
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import SecretStr

from app import capture_service
from app.assignments import service as assignments_service
from app.auth.machine_form_grants import grant_machine_form, revoke_machine_form
from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, create_database, database_url, drop_database
from app.rewinding_export import service
from app.rewinding_export.pdf_renderer import PDFTooLarge
from test_assignments_api import call
from test_rb_crias_quality_api import ARTICLE, DAY, P107

ROOT = "/api/reports/rewinding-export"
ROLES = Path(__file__).resolve().parents[2] / "roles"
MACHINE = "COPASA"
FORM = "VINTO-P1-07"
REASON = "Revisión del ensayo sintético."
EVIDENCE = os.environ.get("RBE05_EVIDENCE_DIR")


def evidence(name, data):
    if EVIDENCE:
        (Path(EVIDENCE) / name).write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def pg_connection(dsn):
    values = conninfo_to_dict(dsn)
    password = values.pop("password", None)
    env = os.environ.copy()
    if password is not None:
        env["PGPASSWORD"] = password
    return make_conninfo(**values), env


def run_pg(tool, dsn, *args):
    dsn, env = pg_connection(dsn)
    result = subprocess.run([tool, "--dbname", dsn, *args], env=env, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise AssertionError(f"{tool} falló con código {result.returncode}: {result.stderr}")
    return result.stdout


class RewindingExportApiTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = build_reference_template("vinto_rbe05_ref")
        cls.addClassCleanup(drop_database, cls.template)
        cls.password = secrets.token_urlsafe(24)
        admin_dsn = database_url(cls.template)
        sanitized, env = pg_connection(admin_dsn)
        env.update(APP_PASSWORD=cls.password, MIGRATOR_PASSWORD=secrets.token_urlsafe(24),
                   REFERENCE_PASSWORD=secrets.token_urlsafe(24))
        subprocess.run(["psql", "--dbname", sanitized, "-q", "-f", str(ROLES / "00_create_roles.sql")],
                       env=env, capture_output=True, check=True, timeout=30)
        for filename in ("02_schema_grants.sql", "03_table_grants.sql",
                         "03b_d3b1_restrict_catalog_writes.sql", "04_function_grants.sql"):
            run_pg("psql", admin_dsn, "-q", "-f", str(ROLES / filename))

    async def asyncSetUp(self):
        self.database = copy_database(self.template, "vinto_rbe05_api")
        self.addCleanup(drop_database, self.database)
        self.connection = connect(self.database)
        self.addCleanup(self.connection.close)
        self.assertEqual(self.connection.info.server_version // 10000, 17)
        self.assertEqual(self.connection.execute("SHOW session_replication_role").fetchone()[0], "origin")
        app_dsn = make_conninfo(database_url(self.database), user="vinto_app", password=self.password)
        self.app_dsn = app_dsn
        for target, attr, value in (
            (settings, "database_url", SecretStr(app_dsn)),
            (capture_service, "_now", lambda *args: DAY),
            (assignments_service, "_now", lambda *args: DAY),
        ):
            mocked = patch.object(target, attr, value)
            mocked.start()
            self.addCleanup(mocked.stop)
        profiles = {"lead": "JEFATURA", "super": "SUPERVISION", "operator": "OPERACION",
                    "other": "OPERACION", "ungranted": "OPERACION", "quality": "CALIDAD"}
        self.users = {}
        self.cookies = {}
        for alias, profile in profiles.items():
            password = secrets.token_urlsafe(24)
            user = create_user(self.connection, username=f"rbeqa.{alias}", display_name=f"Ensayo {alias}",
                               profile_code=profile, password=password, sectors=("BOBINAS", "REBOBINADO"))
            self.users[alias] = user.user_id
            login = await self.checked("POST", "/api/auth/login", 200, body={"username": user.username, "password": password})
            self.cookies[alias] = login.set_cookie_value()
        for alias in ("operator", "other"):
            self.assertTrue(grant_machine_form(self.connection, user_id=self.users[alias], machine_code=MACHINE,
                                              form_code=FORM, actor_id=self.users["lead"]))
        self.pv = "PV-SINTETICO-RBE"
        order = await self.checked("POST", "/api/work-orders", 201, "lead", {
            "machine_code": MACHINE, "lines": [{"pv_reference": self.pv, "article_code": ARTICLE,
                                               "quantity": 10, "due_date": "2026-11-01"}],
        })
        self.order_id = order.json()["id"]
        published = (await self.checked("POST", f"/api/work-orders/{self.order_id}/publish", 200, "lead")).json()
        self.assignment = (await self.checked("POST", "/api/assignments/activate", 201, "super", {
            "work_order_id": self.order_id, "baseline_line_id": published["baseline"]["lines"][0]["id"],
        })).json()["assignment"]["id"]
        self.article = str(self.connection.execute("SELECT id FROM vinto_master.article WHERE code=%s", (ARTICLE,)).fetchone()[0])

    async def checked(self, method, path, status, alias=None, body=None):
        result = await call(method, path, cookie=self.cookies.get(alias), json_body=body)
        # Never print session headers or binary bodies in evidence.
        self.assertEqual(result.status, status, f"{method} {path}: {result.body[:700]!r}")
        return result

    async def classify(self, value="production_confirmed", alias="lead", status=201):
        return await self.checked("POST", f"{ROOT}/work-orders/{self.order_id}/classification", status, alias,
                                  {"classification": value, "reason": REASON})

    async def mother(self, label, **items):
        values = {
            item["key"]: {"time": "06:30", "decimal": "1.50"}.get(item["value_type"], "Ensayo")
            for item in P107["fields"] if item["required"]
        }
        values.update(etiqueta_numero_de_bobina=label, peso_cria_1="12.50", diametro="1200",
                      formato_1="120.00", formato_2="98.0", formato_3="0.00", destino="Perú",
                      hora_inicio="06:30", hora_fin="05:45", producto_refilado="EXCLUIR-DEL-PDF")
        values.update(items)
        capture_id = str(uuid4())
        await self.checked("POST", "/api/captures", 201, "operator", {
            "capture_id": capture_id, "form_code": FORM, "assignment_id": self.assignment,
            "device_key": str(uuid4()), "values": values,
        })
        rows = self.connection.execute("""
            SELECT rewind_child_position,id FROM vinto_txn.bobbin
            WHERE source_capture_id=%s AND rewind_child_position IS NOT NULL
        """, (capture_id,)).fetchall()
        return capture_id, {position: str(bobbin_id) for position, bobbin_id in rows}

    async def decide(self, child, action="release"):
        fields = {} if action == "release" else {
            "rejection_type": "rechazado", "classification": "defecto_visible",
            "detail": "Rechazo sintético", "corrective_action": "Segregar cría",
        }
        await self.checked("POST", f"/api/quality/bobbins/{child}/decision", 200, "quality",
                           {"decision_id": str(uuid4()), "action": action, **fields})

    async def draft(self, alias="operator", *, status=201):
        result = await self.checked("POST", ROOT + "/drafts", status, alias, {
            "pv_reference": self.pv, "article_id": self.article, "truck_number": "CAMIÓN-01",
            "order_number": "ORD-ENSAYO", "observations": "Observación sintética.",
        })
        return result.json().get("id")

    async def package(self, draft, mother, child, *, alias="operator", status=201):
        return (await self.checked("POST", f"{ROOT}/drafts/{draft}/packages", status, alias, {
            "mother_capture_id": mother, "children": [{"package_slot": "A", "child_bobbin_id": child}],
        })).json()

    async def generate(self, draft, key, alias="operator"):
        return await call("POST", f"{ROOT}/drafts/{draft}/generate", cookie=self.cookies.get(alias),
                          json_body={"idempotency_key": key})

    def counts(self, report):
        return self.connection.execute("""
            SELECT r.status,
              (SELECT count(*) FROM vinto_txn.rewinding_export_pdf WHERE report_id=r.id),
              (SELECT count(*) FROM vinto_txn.rewinding_export_reservation WHERE report_id=r.id AND released_at IS NULL),
              (SELECT count(*) FROM vinto_txn.rewinding_export_report_event WHERE report_id=r.id AND event_type='report_generated'),
              (SELECT count(*) FROM vinto_txn.rewinding_export_report_event WHERE report_id=r.id AND event_type='reservation_created')
            FROM vinto_txn.rewinding_export_report r WHERE r.id=%s
        """, (report,)).fetchone()

    async def test_eligible_sources_and_live_profiles(self):
        mother, children = await self.mother("Ensayo A", peso_cria_2="8.00", peso_cria_3="9.00")
        other_mother, other_children = await self.mother("Ensayo B")
        await self.decide(children[1])
        await self.decide(children[3], "reject")
        await self.decide(other_children[1])
        draft = await self.draft()
        self.assertEqual(self.counts(draft), ("draft", 0, 0, 0, 0))
        self.assertEqual((await self.checked("GET", ROOT + "/pvs", 200, "operator")).json(), {"items": []})
        await self.package(draft, mother, children[1], status=409)
        await self.classify("qa")
        await self.package(draft, mother, children[1], status=409)
        await self.classify(alias="super", status=403)
        await self.classify()
        await self.draft("super", status=403)
        ungranted = await self.draft("ungranted")
        await self.package(ungranted, mother, children[1], alias="ungranted", status=403)
        for child in (children[2], children[3], other_children[1]):
            await self.package(draft, mother, child, status=409)
        available = (await self.checked("GET", f"{ROOT}/mothers/{mother}/children", 200, "operator")).json()
        self.assertEqual([item["bobbin_id"] for item in available["items"]], [children[1]])
        product = (await self.checked("GET", ROOT + f"/products?pv_reference={self.pv}", 200, "operator")).json()
        self.assertEqual(product["items"][0]["article_id"], self.article)
        result = await self.package(draft, other_mother, other_children[1])
        self.assertEqual(result["packages"][0]["mother"]["work_order"]["id"], self.order_id)
        await self.package(draft, mother, children[1])
        preview = (await self.checked("POST", f"{ROOT}/drafts/{draft}/preview", 200, "operator")).json()
        self.assertTrue(preview["valid"], preview)
        self.assertIn("SOURCE_TIME_INVERTED", {warning["code"] for warning in preview["warnings"]})
        self.assertEqual(self.counts(draft), ("draft", 0, 0, 0, 0))

    async def test_concurrency_annulment_replay_and_restore(self):
        await self.classify()
        mother, children = await self.mother("Ensayo simultáneo")
        child = children[1]
        await self.decide(child)
        drafts, keys = {}, {}
        for alias in ("operator", "other"):
            drafts[alias], keys[alias] = await self.draft(alias), str(uuid4())
            await self.package(drafts[alias], mother, child, alias=alias)

        barrier = threading.Barrier(2)
        true_render = service.render_pdf

        def synchronized_render(snapshot):
            barrier.wait(timeout=10)
            return true_render(snapshot)

        with patch.object(service, "render_pdf", side_effect=synchronized_render):
            responses = dict(zip(drafts, await asyncio.gather(*(
                self.generate(drafts[alias], keys[alias], alias) for alias in drafts
            )), strict=True))
        self.assertEqual(sorted(reply.status for reply in responses.values()), [200, 409],
                         {alias: reply.body[:300] for alias, reply in responses.items() if reply.status != 200})
        winner = next(alias for alias, reply in responses.items() if reply.status == 200)
        loser = next(alias for alias in drafts if alias != winner)
        report, failed = drafts[winner], drafts[loser]
        self.assertEqual(self.counts(report), ("generated", 1, 1, 1, 1))
        self.assertEqual(self.counts(failed), ("draft", 0, 0, 0, 0))
        evidence("concurrencia.json", {"statuses": [200, 409], "winner": self.counts(report), "loser": self.counts(failed),
                                      "postgres_major": 17, "triggers": "origin", "role": "vinto_app"})

        original = responses[winner].body
        sha = hashlib.sha256(original).hexdigest()
        self.assertTrue(original.startswith(b"%PDF-"))
        self.assertEqual(dict(responses[winner].headers)[b"etag"].decode(), f'"{sha}"')
        self.assertEqual(dict(responses[winner].headers)[b"cache-control"], b"private, no-store")
        with patch.object(service, "render_pdf", side_effect=AssertionError("Unexpected regeneration")):
            replay = await self.generate(report, keys[winner], winner)
        self.assertEqual((replay.status, replay.body), (200, original))
        another = await self.draft(winner)
        self.assertEqual((await self.generate(another, keys[winner], winner)).status, 409)
        self.assertEqual(self.counts(another), ("draft", 0, 0, 0, 0))
        self.assertEqual((await self.generate(report, str(uuid4()), winner)).status, 409)
        await self.checked("GET", f"{ROOT}/reports/{report}", 404, loser)
        await self.checked("GET", f"{ROOT}/reports/{report}/pdf", 404, loser)
        await self.checked("GET", ROOT + "/history", 403, "quality")
        self.assertEqual((await self.checked("GET", ROOT + "/history", 200, loser)).json(), [])
        detail = (await self.checked("GET", f"{ROOT}/reports/{report}", 200, "super")).json()
        self.assertEqual(detail["packages"][0]["weight_kg_snapshot"], "12.50")
        self.assertEqual(detail["report"]["report_snapshot"]["packages"][0]["operator"], "Ensayo operator")
        self.assertIn(report, [item["id"] for item in (await self.checked("GET", ROOT + "/history", 200, "super")).json()])

        # Emit a synthetic observation through the guarded transition reserved for a future Quality workflow.
        with self.connection.transaction():
            service._context(self.connection, self.users["quality"], uuid4(), REASON)
            self.connection.execute("SELECT set_config('vinto.rewinding_export_observe','approved',true)")
            self.connection.execute("UPDATE vinto_txn.rewinding_export_report SET status='observed' WHERE id=%s", (report,))
        observed = await self.generate(report, keys[winner], winner)
        self.assertEqual((observed.status, observed.body), (200, original))
        self.assertEqual(dict(observed.headers)[b"x-rbe-report-status"], b"observed")

        for alias in ("operator", "super"):
            await self.checked("POST", f"{ROOT}/reports/{report}/annul", 403, alias, {"reason": REASON})
        await self.checked("POST", f"{ROOT}/reports/{report}/annul", 422, "lead", {"reason": "corto"})
        annulled = await self.checked("POST", f"{ROOT}/reports/{report}/annul", 200, "lead", {"reason": REASON})
        self.assertEqual(annulled.json()["released_reservations"], 1)
        self.assertEqual(self.counts(report), ("annulled", 1, 0, 1, 1))
        self.assertEqual((await self.checked("GET", f"{ROOT}/mothers/{mother}/children", 200, loser)).json()["items"][0]["bobbin_id"], child)
        replay = await self.generate(report, keys[winner], winner)
        self.assertEqual((replay.status, replay.body, dict(replay.headers)[b"x-rbe-report-status"]), (200, original, b"annulled"))
        after = await self.checked("GET", f"{ROOT}/reports/{report}/pdf", 200, "lead")
        self.assertEqual(after.body, original)
        self.assertEqual((await self.generate(failed, keys[loser], loser)).status, 200)

        for operation in ("UPDATE vinto_txn.rewinding_export_pdf SET file_name='otro'",
                          "DELETE FROM vinto_txn.rewinding_export_pdf", "TRUNCATE vinto_txn.rewinding_export_pdf"):
            with self.assertRaises(psycopg.errors.CheckViolation):
                self.connection.execute(operation)
            with psycopg.connect(self.app_dsn, autocommit=True) as app:
                with self.assertRaises(psycopg.errors.InsufficientPrivilege):
                    app.execute(operation)

        restore = f"vinto_rbe05_restore_{uuid4().hex[:10]}_test"
        create_database(restore)
        self.addCleanup(drop_database, restore)
        with tempfile.TemporaryDirectory() as tmp:
            archive = str(Path(tmp) / "rbe.dump")
            run_pg("pg_dump", database_url(self.database), "--format=custom", "--file", archive)
            run_pg("pg_restore", database_url(restore), "--exit-on-error", archive)
        with connect(restore) as restored:
            stored = restored.execute("""
                SELECT r.status,p.pdf_bytes,p.sha256 FROM vinto_txn.rewinding_export_report r
                JOIN vinto_txn.rewinding_export_pdf p ON p.report_id=r.id WHERE r.id=%s
            """, (report,)).fetchone()
        self.assertEqual((stored[0], stored[2], hashlib.sha256(stored[1]).hexdigest()), ("annulled", sha, sha))
        evidence("conservacion.json", {"sha256": sha, "download_unchanged": True, "restored_unchanged": True,
                                       "released": 1, "pdf_mutations_denied": True})
        if EVIDENCE:
            (Path(EVIDENCE) / "sintetico-conservado.pdf").write_bytes(original)

    async def test_generation_rollback_and_revocation(self):
        await self.classify()
        mother, children = await self.mother("Ensayo revocación")
        await self.decide(children[1])
        draft = await self.draft()
        await self.package(draft, mother, children[1])
        key = str(uuid4())
        forbidden_payload = await self.checked("POST", f"{ROOT}/drafts/{draft}/generate", 422, "operator",
                                               {"idempotency_key": key, "pdf_bytes": "arbitrario"})
        self.assertTrue(forbidden_payload.json())
        with patch.object(service, "render_pdf", side_effect=PDFTooLarge("PDF excedido")):
            self.assertEqual((await self.generate(draft, key)).status, 413)
        self.assertEqual(self.counts(draft), ("draft", 0, 0, 0, 0))

        with connect(self.database) as revoker:
            with revoker.transaction():
                self.assertTrue(revoke_machine_form(revoker, user_id=self.users["operator"], machine_code=MACHINE,
                                                   form_code=FORM, actor_id=self.users["lead"]))
                pending = asyncio.create_task(self.generate(draft, key))
                for _ in range(100):
                    waiting = self.connection.execute("""
                        SELECT EXISTS (
                            SELECT 1 FROM pg_stat_activity
                            WHERE datname=current_database() AND %s=ANY(pg_blocking_pids(pid))
                        )
                    """, (revoker.info.backend_pid,)).fetchone()[0]
                    if waiting or pending.done():
                        break
                    await asyncio.sleep(0.025)
                self.assertTrue(waiting, "PostgreSQL must observe generation waiting for the pending revocation")
                self.assertFalse(pending.done())
            denied = await pending
        self.assertEqual(denied.status, 403)
        self.assertEqual(self.counts(draft), ("draft", 0, 0, 0, 0))
        self.assertTrue(grant_machine_form(self.connection, user_id=self.users["operator"], machine_code=MACHINE,
                                          form_code=FORM, actor_id=self.users["lead"]))
        twin = await asyncio.gather(self.generate(draft, key), self.generate(draft, key))
        self.assertEqual([reply.status for reply in twin], [200, 200])
        self.assertEqual(twin[0].body, twin[1].body)
        self.assertTrue(revoke_machine_form(self.connection, user_id=self.users["operator"], machine_code=MACHINE,
                                           form_code=FORM, actor_id=self.users["lead"]))
        self.assertEqual((await self.generate(draft, key)).status, 403)
        self.assertEqual(self.counts(draft), ("generated", 1, 1, 1, 1))
        self.assertEqual((await self.generate(draft, key, alias=None)).status, 401)
        evidence("revocacion.json", {"generation_waited": True, "revoked_status": 403, "rollback_status": 413})
