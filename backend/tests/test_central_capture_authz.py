"""Integración del motor de autorización en POST /api/captures (MF-13-01D.2A): modos off / observe / enforce.

Se prueba por HTTP (la aplicación ASGI contra una base *_test efímera, igual que test_f6_captures_api) y, donde hace falta controlar bloqueos, a nivel de servicio con conexiones propias.
El modo lo fija SOLO el servidor (`settings.authz_central_captures_mode`); aquí se parchea como lo haría una variable de entorno. Nada toca una base que no sea de prueba.
"""

import asyncio
import logging
import re
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from pydantic import ValidationError

from app import capture_service as _capture_service
from app.auth.machine_form_grants import grant_machine_form, revoke_machine_form
from app.auth.service import AuthenticatedUser
from app.authz import capture_gate
from app.authz.capture_gate import CentralCaptureGate
from app.authz.errors import PUBLIC_FORBIDDEN, PUBLIC_UNAVAILABLE, AuthorizationDenied, AuthorizationUnavailable
from app.config import Settings, settings
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database

try:
    import test_f6_captures_api as f6
except ModuleNotFoundError:
    import tests.test_f6_captures_api as f6
try:
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.test_assignments_api import call

BACKEND = Path(__file__).resolve().parent.parent
P106, P105 = "VINTO-P1-06", "VINTO-P1-05"
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_d2a_tpl")
    f6.STATE["template"] = STATE["template"]  # el arnés HTTP de F6 copia SU plantilla: se la damos


def tearDownModule():
    drop_database(STATE["template"])


@contextmanager
def mode(value):
    with patch.object(settings, "authz_central_captures_mode", value):
        yield


class GateCase(f6.CaptureApiCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.operator = self.users["OPERACION"][0].user_id
        self.actor = self.users["DATA_BALTREK"][0].user_id
        self.sql("SELECT set_config('vinto.actor_id', %s, false)", (str(self.actor),))
        self.captures_at_start = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        self.connection.execute("UPDATE vinto_master.user_machine_form_grant SET revoked_at = clock_timestamp(), revoked_by = %s WHERE revoked_at IS NULL", (self.actor,))

    def sql(self, query, params=()):
        return self.connection.execute(query, params).fetchone()

    def grant(self, machine="MP1", form=P106, user=None):
        return grant_machine_form(self.connection, user_id=user or self.operator, machine_code=machine, form_code=form, actor_id=self.actor)

    def revoke(self, machine="MP1", form=P106, user=None):
        return revoke_machine_form(self.connection, user_id=user or self.operator, machine_code=machine, form_code=form, actor_id=self.actor)

    def captures(self):
        """Capturas creadas DURANTE esta prueba (la base se comparte entre las pruebas de la clase)."""
        return self.scalar("SELECT count(*) FROM vinto_txn.capture") - self.captures_at_start

    def snapshot(self):
        """Todo lo que NO debe moverse por una captura de F6 salvo la propia captura y su dispositivo."""
        tables = ("vinto_txn.bobbin", "vinto_txn.bobbin_relation", "vinto_txn.quality_release", "vinto_txn.work_order", "vinto_txn.work_order_line", "vinto_master.user_machine_form_grant", "vinto_master.user_sector")
        return [self.scalar(f"SELECT count(*) FROM {t}") for t in tables] + [self.scalar("SELECT count(*) FROM vinto_txn.assignment WHERE status = 'active'")]

    async def fresh_operator(self, sectors=("BOBINAS",), profile="OPERACION"):
        from app.auth.service import create_user
        password = "pw-" + uuid4().hex
        created = create_user(self.connection, username=f"d2a.{uuid4().hex[:12]}", display_name="d2a", profile_code=profile, password=password, sectors=sectors)
        reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
        self.assertEqual(reply.status, 200)
        return created.user_id, reply.set_cookie_value()

    async def submit(self, assignment, *, cookie=None, **changes):
        body = self.payload(assignment, **changes)
        reply = await call("POST", "/api/captures", json_body=body, cookie=cookie or await self.cookie("OPERACION"))
        return body, reply


# ---- 1. configuración: solo servidor, valor inicial off ------------------------------------------------------------------------------------

class ConfigurationTests(unittest.TestCase):
    def test_the_default_is_off_and_the_value_is_normalised(self):
        self.assertEqual(Settings(_env_file=None).authz_central_captures_mode, "off")
        self.assertEqual(Settings(_env_file=None, authz_central_captures_mode=" ENFORCE ").authz_central_captures_mode, "enforce")

    def test_an_unknown_mode_does_not_start_the_server_instead_of_silently_falling_back(self):
        for bad in ("on", "true", "", "enforced"):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None, authz_central_captures_mode=bad)

    def test_the_client_cannot_choose_the_mode(self):
        source = (BACKEND / "app/captures.py").read_text(encoding="utf-8")
        self.assertIn("settings.authz_central_captures_mode", source)
        self.assertNotRegex(source, r"Header\(|Query\([^)]*mode|body\.mode")  # ni cabecera, ni query, ni cuerpo
        from app.capture_schemas import CaptureIn
        self.assertNotIn("mode", CaptureIn.model_fields)
        self.assertEqual(CaptureIn.model_config.get("extra"), "forbid")

    def test_gate_for_off_returns_nothing_and_an_invalid_mode_fails_closed(self):
        user = AuthenticatedUser(uuid4(), "u", "U", ("OPERACION",), frozenset(), False)
        self.assertIsNone(capture_gate.gate_for(user, "off", "r"))
        self.assertEqual(capture_gate.gate_for(user, "observe", "r").mode, "observe")
        with self.assertRaises(AuthorizationUnavailable):
            capture_gate.gate_for(user, "weird", "r")

    def test_only_post_captures_is_wired_and_there_is_no_global_switch(self):
        consumers = sorted(str(p.relative_to(BACKEND)).replace("\\", "/") for p in (BACKEND / "app").rglob("*.py")
                           if "app/authz" not in str(p).replace("\\", "/") and re.search(r"\bapp\.authz\b", p.read_text(encoding="utf-8")))
        self.assertEqual(consumers, ["app/bobbins/router.py", "app/captures.py", "app/main.py", "app/quality/router.py"])  # main.py solo registra el manejador de errores; Calidad no lo usa (F3: MF-13-01D.2B)
        self.assertEqual([n for n in Settings.model_fields if n.startswith("authz")], ["authz_central_captures_mode", "authz_bobbin_production_mode", "authz_quality_bobbin_captures_mode"])  # un modo POR operación, nunca uno global


# ---- 2. off / observe ------------------------------------------------------------------------------------------------------------------------

class OffAndObserveTests(GateCase):
    async def test_off_keeps_the_previous_behaviour_even_without_any_grant(self):
        _, assignment = await self.assignment()
        with mode("off"), patch.object(capture_gate, "authorize", side_effect=AssertionError("el motor no debe llamarse en off")), \
                patch.object(capture_gate, "require", side_effect=AssertionError("el motor no debe llamarse en off")):
            body, reply = await self.submit(assignment)
        self.assertEqual(reply.status, 201)
        self.assertEqual((reply.json()["created"], self.captures()), (True, 1))

    async def test_observe_never_changes_data_or_the_response_and_logs_what_would_have_happened(self):
        _, assignment = await self.assignment()
        before = self.snapshot()
        with mode("observe"), self.assertLogs("vinto.authz", level="INFO") as logs:
            body, reply = await self.submit(assignment)  # sin concesión: en enforce sería 403
        self.assertEqual((reply.status, reply.json()["created"]), (201, True))
        self.assertEqual(self.snapshot(), before)  # observar no escribe concesiones ni nada de Calidad, bobinas u órdenes
        line = [m for m in logs.output if "outcome=would_forbidden" in m]
        self.assertEqual(len(line), 1)
        self.assertRegex(line[0], r"mode=observe operation=production_capture outcome=would_forbidden reason=GRANT_MISSING request_id=[0-9a-f-]{36}")

    async def test_observe_with_a_grant_logs_allowed_and_responds_exactly_as_off(self):
        self.grant()
        _, assignment = await self.assignment()
        with mode("observe"), self.assertLogs("vinto.authz", level="INFO") as logs:
            _, observed = await self.submit(assignment)
        _, second = await self.assignment()
        with mode("off"):
            _, plain = await self.submit(second)
        self.assertEqual((observed.status, plain.status), (201, 201))
        self.assertEqual(set(observed.json()), set(plain.json()))
        self.assertTrue(any("outcome=allowed reason=ALLOWED" in m for m in logs.output))

    async def test_observe_ignores_an_engine_failure_even_a_sql_one_and_the_capture_still_succeeds(self):
        _, assignment = await self.assignment()

        def broken(connection, *args, **kwargs):
            connection.execute("SELECT * FROM vinto_master.tabla_que_no_existe")  # aborta la transacción SI no hubiera savepoint

        with mode("observe"), patch.object(capture_gate, "authorize", side_effect=broken), self.assertLogs("vinto.authz", level="ERROR") as logs:
            _, reply = await self.submit(assignment)
        self.assertEqual((reply.status, self.captures()), (201, 1))
        self.assertTrue(any("outcome=observe_error" in m for m in logs.output))

    async def test_logs_never_contain_cookies_credentials_users_or_form_values(self):
        _, assignment = await self.assignment()
        cookie = await self.cookie("OPERACION")
        with mode("observe"), self.assertLogs("vinto.authz", level="INFO") as logs:
            await self.submit(assignment, cookie=cookie)
        text = "\n".join(logs.output)
        for secret in (cookie, "125.50", "recorte_maquina", str(self.operator), "pw-"):
            self.assertNotIn(secret, text)


# ---- 3. enforce: decisiones ----------------------------------------------------------------------------------------------------------------

class EnforceDecisionTests(GateCase):
    async def test_a_granted_pair_is_allowed_and_the_response_is_the_usual_one(self):
        self.grant()
        _, assignment = await self.assignment()
        with mode("enforce"):
            body, reply = await self.submit(assignment)
        self.assertEqual((reply.status, reply.json()["created"], reply.json()["capture"]["machine"]["code"]), (201, True, "MP1"))
        self.assertEqual(self.captures(), 1)

    async def test_a_pair_that_was_not_granted_is_rejected_with_the_fixed_public_403_and_nothing_is_written(self):
        _, assignment = await self.assignment()
        before, devices = self.snapshot(), self.scalar("SELECT count(*) FROM vinto_master.device")
        with mode("enforce"), self.assertLogs("vinto.authz", level="WARNING") as logs:
            _, reply = await self.submit(assignment)
        self.assertEqual((reply.status, reply.json()), (PUBLIC_FORBIDDEN[0], PUBLIC_FORBIDDEN[1]))
        self.assertEqual((self.captures(), self.snapshot(), self.scalar("SELECT count(*) FROM vinto_master.device")), (0, before, devices))  # ni capturas ni dispositivo
        self.assertTrue(any("mode=enforce operation=production_capture outcome=forbidden reason=GRANT_MISSING" in m for m in logs.output))
        for leak in ("GRANT_MISSING", "MP1", "grant", "vinto_"):
            self.assertNotIn(leak, reply.body.decode())

    async def test_mp1_and_mp3_are_independent(self):
        self.grant("MP1")
        _, on_mp1 = await self.assignment("MP1")
        _, on_mp3 = await self.assignment("MP3")
        with mode("enforce"):
            self.assertEqual((await self.submit(on_mp3))[1].status, 403)
            self.assertEqual((await self.submit(on_mp1))[1].status, 201)
            self.grant("MP3")
            self.assertEqual((await self.submit(on_mp3))[1].status, 201)

    async def test_the_machine_comes_from_the_assignment_not_from_anything_the_client_sends(self):
        self.grant("MP3")  # concedida en MP3 pero la asignación es de MP1
        _, on_mp1 = await self.assignment("MP1")
        with mode("enforce"):
            body = self.payload(on_mp1, machine_code="MP3")  # un campo extra del cliente se rechaza (cuerpo cerrado), jamás se usa
            reply = await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))
            self.assertEqual(reply.status, 422)
            self.assertEqual((await self.submit(on_mp1))[1].status, 403)

    async def test_an_inactive_user_is_rejected(self):
        user, cookie = await self.fresh_operator()
        self.grant(user=user)
        _, assignment = await self.assignment()
        self.connection.execute('UPDATE vinto_master."user" SET active = false WHERE id = %s', (user,))
        with mode("enforce"):
            _, reply = await self.submit(assignment, cookie=cookie)
        self.assertIn(reply.status, (401, 403))
        self.assertEqual(self.captures(), 0)

    async def test_a_profile_without_the_permission_is_rejected(self):
        _, cookie = await self.fresh_operator(profile="CALIDAD")
        _, assignment = await self.assignment()
        with mode("enforce"):
            _, reply = await self.submit(assignment, cookie=cookie)
        self.assertEqual(reply.status, 403)
        self.assertEqual(self.captures(), 0)

    async def test_a_sector_that_was_not_granted_or_is_not_operational_is_rejected(self):
        user, cookie = await self.fresh_operator(sectors=())
        self.grant(user=user)
        _, assignment = await self.assignment()
        with mode("enforce"):
            _, reply = await self.submit(assignment, cookie=cookie)
        self.assertIn(reply.status, (403, 404))  # el alcance de sectores existente responde 404 antes que el motor
        self.assertEqual(self.captures(), 0)
        user2, cookie2 = await self.fresh_operator()
        self.grant(user=user2)
        self.connection.execute("UPDATE vinto_master.sector SET active = false WHERE code = 'BOBINAS'")
        try:
            with mode("enforce"):
                _, reply = await self.submit(assignment, cookie=cookie2)
            self.assertIn(reply.status, (403, 404, 409))
            self.assertEqual(self.captures(), 0)
        finally:
            self.connection.execute("UPDATE vinto_master.sector SET active = true WHERE code = 'BOBINAS'")

    async def test_a_form_the_machine_does_not_offer_is_rejected_before_any_other_check(self):
        _, on_mp1 = await self.assignment("MP1")
        with mode("enforce"):
            _, reply = await self.submit(on_mp1, form_code=P105)  # P1-05 solo se vincula a MP3 y no existe concesión posible
        self.assertEqual(reply.status, 403)
        self.assertEqual(self.captures(), 0)

    async def test_a_revocation_before_the_capture_prevents_the_write(self):
        self.grant()
        self.revoke()
        _, assignment = await self.assignment()
        with mode("enforce"):
            _, reply = await self.submit(assignment)
        self.assertEqual(reply.status, 403)
        self.assertEqual(self.captures(), 0)

    async def test_an_engine_failure_is_503_and_never_an_implicit_allow(self):
        self.grant()
        _, assignment = await self.assignment()
        self.connection.execute("ALTER TABLE vinto_master.user_machine_form_grant RENAME TO grants_gone")
        try:
            with mode("enforce"), self.assertLogs("vinto.authz", level="ERROR") as logs:
                _, reply = await self.submit(assignment)
        finally:
            self.connection.execute("ALTER TABLE vinto_master.grants_gone RENAME TO user_machine_form_grant")
        self.assertEqual((reply.status, reply.json()), (PUBLIC_UNAVAILABLE[0], PUBLIC_UNAVAILABLE[1]))
        self.assertEqual(self.captures(), 0)
        self.assertTrue(any("outcome=unavailable reason=42P01" in m for m in logs.output))
        self.assertNotIn("42P01", reply.body.decode())

    async def test_a_definitive_context_that_differs_from_the_authorised_one_fails_closed(self):
        self.grant()
        _, assignment = await self.assignment()
        real = _capture_service.lock_active_assignment

        def other_machine(connection, assignment_id, sectors):
            context = real(connection, assignment_id, sectors)
            return type(context)(uuid4(), context.shift_schedule_id, context.operating_date, context.article_version_id, context.now)
        with mode("enforce"), patch.object(_capture_service, "lock_active_assignment", other_machine):
            _, reply = await self.submit(assignment)
        self.assertEqual((reply.status, self.captures()), (503, 0))

    async def test_existing_error_semantics_are_preserved_when_authorised(self):
        self.grant()
        _, assignment = await self.assignment()
        with mode("enforce"):
            self.assertEqual((await self.submit(assignment, values={"peso_kg": "x"}))[1].status, 422)  # valores inválidos: el mismo error de siempre
            self.assertEqual((await self.submit({"id": str(uuid4())}))[1].status, 404)  # asignación inexistente


# ---- 4. enforce: idempotencia ------------------------------------------------------------------------------------------------------------

class EnforceIdempotencyTests(GateCase):
    async def test_a_retry_after_a_revocation_cannot_bypass_the_control_and_creates_nothing(self):
        self.grant()
        _, assignment = await self.assignment()
        with mode("enforce"):
            body, first = await self.submit(assignment)
            self.assertEqual(first.status, 201)
            details = self.scalar("SELECT count(*) FROM vinto_txn.capture_detail")
            self.revoke()
            retry = await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))
        self.assertEqual(retry.status, 403)
        self.assertEqual((self.captures(), self.scalar("SELECT count(*) FROM vinto_txn.capture_detail")), (1, details))
        with mode("off"):  # off conserva la semántica histórica: el mismo reintento sigue siendo idempotente
            again = await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))
        self.assertEqual((again.status, again.json()["already_submitted"]), (200, True))

    async def test_a_legitimate_retry_still_authorised_survives_a_finished_assignment(self):
        self.grant()
        _, assignment = await self.assignment()
        with mode("enforce"):
            body, first = await self.submit(assignment)
            self.assertEqual(first.status, 201)
            finish = await call("POST", f"/api/assignments/{assignment['id']}/finish", cookie=await self.cookie("SUPERVISION"))
            self.assertEqual(finish.status, 200)
            retry = await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))
        self.assertEqual((retry.status, retry.json()["created"], retry.json()["already_submitted"]), (200, False, True))
        self.assertEqual(self.captures(), 1)

    async def test_conflict_detection_by_capture_id_is_kept_for_an_authorised_user(self):
        self.grant()
        _, assignment = await self.assignment()
        with mode("enforce"):
            body, first = await self.submit(assignment)
            self.assertEqual(first.status, 201)
            changed = dict(body, values=dict(body["values"], cantidad_fardos=99))
            conflict = await call("POST", "/api/captures", json_body=changed, cookie=await self.cookie("OPERACION"))
            other_device = await call("POST", "/api/captures", json_body=dict(body, device_key=str(uuid4())), cookie=await self.cookie("OPERACION"))
        self.assertEqual((conflict.status, other_device.status), (409, 409))
        self.assertEqual(self.captures(), 1)

    async def test_the_pair_of_a_retry_comes_from_the_stored_capture_not_from_the_retry(self):
        """Un reintento con otro formulario no puede autorizarse por el par del reintento: se autoriza el par PERSISTIDO."""
        self.grant()
        _, assignment = await self.assignment()
        with mode("enforce"):
            body, first = await self.submit(assignment)
            self.assertEqual(first.status, 201)
            self.revoke()
            self.grant("MP3")  # concesión de otra máquina: no sirve para el par persistido (MP1)
            retry = await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))
        self.assertEqual(retry.status, 403)


    async def test_a_retry_naming_another_form_is_authorised_by_the_stored_form_and_then_conflicts(self):
        self.grant()
        _, assignment = await self.assignment()
        with mode("enforce"):
            body, first = await self.submit(assignment)
            self.assertEqual(first.status, 201)
            retry = await call("POST", "/api/captures", json_body=dict(body, form_code="VINTO-P1-01"), cookie=await self.cookie("OPERACION"))
        self.assertEqual(retry.status, 409)  # autorizado por el par PERSISTIDO (P1-06 concedido) y rechazado por idempotencia; el formulario del reintento (sin concesión) no decide
        self.assertEqual(self.captures(), 1)


# ---- 5. bloqueos, concurrencia y rol equivalente a vinto_app ----------------------------------------------------------------------------------

class LockingTests(GateCase):
    def principal(self):
        return AuthenticatedUser(self.operator, "u", "U", ("OPERACION",), frozenset(), False, frozenset({"BOBINAS"}))

    def submit_in_thread(self, assignment, gate, results, connection=None):
        body = self.payload(assignment)

        def work():
            conn = connection or connect(self.database)
            try:
                results.append(_capture_service.submit_production_capture(conn, actor_id=self.operator, capture_id=body["capture_id"], form_code=body["form_code"],
                                                                         assignment_id=body["assignment_id"], device_key=body["device_key"], values=body["values"],
                                                                         request_id="rid", sectors=frozenset({"BOBINAS"}), gate=gate))
            except BaseException as error:  # noqa: BLE001
                results.append(error)
            finally:
                if connection is None:
                    conn.close()
        return threading.Thread(target=work)

    async def test_a_concurrent_revocation_waits_for_the_capture_transaction_and_the_next_capture_is_denied(self):
        self.grant()
        _, assignment = await self.assignment()
        inside, release, results = threading.Event(), threading.Event(), []
        real = _capture_service._resolve_device

        def paused(connection, device_key, machine_id):
            inside.set()  # ya pasó la autorización con bloqueos y el bloqueo de máquina: sigue dentro de la transacción de la captura
            release.wait(20)
            return real(connection, device_key, machine_id)
        with patch.object(_capture_service, "_resolve_device", paused):
            thread = self.submit_in_thread(assignment, CentralCaptureGate(self.principal(), "enforce", "rid"), results)
            thread.start()
            self.assertTrue(inside.wait(20))
            revoker = connect(self.database)
            self.addCleanup(revoker.close)
            with self.assertRaises(psycopg.errors.LockNotAvailable), revoker.transaction():  # la revocación NO puede colarse entre la autorización y el registro
                revoker.execute("SET LOCAL lock_timeout = 400")
                revoker.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(self.actor),))
                revoker.execute("UPDATE vinto_master.user_machine_form_grant SET revoked_at = clock_timestamp(), revoked_by = %s WHERE revoked_at IS NULL", (self.actor,))
            release.set()
            thread.join(30)
        self.assertTrue(results and results[0].created, results)
        self.revoke()
        _, second = await self.assignment()
        with mode("enforce"):
            self.assertEqual((await self.submit(second))[1].status, 403)

    async def test_observe_takes_no_authorisation_locks(self):
        self.grant()
        _, assignment = await self.assignment()
        inside, release, results = threading.Event(), threading.Event(), []
        real = _capture_service._resolve_device

        def paused(connection, device_key, machine_id):
            inside.set()
            release.wait(20)
            return real(connection, device_key, machine_id)
        with patch.object(_capture_service, "_resolve_device", paused):
            thread = self.submit_in_thread(assignment, CentralCaptureGate(self.principal(), "observe", "rid"), results)
            thread.start()
            self.assertTrue(inside.wait(20))
            self.revoke()  # no bloquea: observar no retiene el bloqueo de la concesión
            release.set()
            thread.join(30)
        self.assertTrue(results and results[0].created, results)

    async def test_no_deadlocks_under_mixed_captures_grants_revocations_and_retries(self):
        self.grant()
        _, assignment = await self.assignment()
        errors, outcomes, stop = [], [], threading.Event()
        gate_user = self.principal()

        def submitter(index):
            conn = connect(self.database)
            try:
                for _ in range(6):
                    body = self.payload(assignment)
                    for attempt in range(2):  # la segunda es un reintento idéntico
                        try:
                            result = _capture_service.submit_production_capture(
                                conn, actor_id=self.operator, capture_id=body["capture_id"], form_code=body["form_code"], assignment_id=body["assignment_id"],
                                device_key=body["device_key"], values=body["values"], request_id=f"rid-{index}", sectors=frozenset({"BOBINAS"}),
                                gate=CentralCaptureGate(gate_user, "enforce", f"rid-{index}"))
                            outcomes.append("created" if result.created else "retry")
                        except AuthorizationDenied:
                            outcomes.append("denied")
                        except _capture_service.CaptureError as error:  # errores funcionales esperables (p. ej. correlativos)
                            outcomes.append(type(error).__name__)
            except BaseException as error:  # noqa: BLE001 — un deadlock o AuthorizationUnavailable aparece aquí
                errors.append(repr(error))
            finally:
                conn.close()

        def toggler():
            conn = connect(self.database)
            try:
                for _ in range(12):
                    grant_machine_form(conn, user_id=self.operator, machine_code="MP1", form_code=P106, actor_id=self.actor)
                    time.sleep(0.01)
                    revoke_machine_form(conn, user_id=self.operator, machine_code="MP1", form_code=P106, actor_id=self.actor)
            except BaseException as error:  # noqa: BLE001
                errors.append(repr(error))
            finally:
                conn.close()
        threads = [threading.Thread(target=submitter, args=(i,)) for i in range(4)] + [threading.Thread(target=toggler) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(120)
        self.assertEqual(errors, [])
        self.assertTrue({"created", "denied"} & set(outcomes))
        self.assertEqual(self.scalar("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND datname = current_database()"), 0)

    async def test_the_flow_runs_with_the_privileges_of_vinto_app(self):
        """Replica los privilegios reales de vinto_app leyendo backend/roles/*.sql y la 0007; sin UPDATE en user_sector ni vinto_config, FOR SHARE allí fallaría."""
        role = "d2a_app_" + uuid4().hex[:8]
        self.connection.execute(f"CREATE ROLE {role} NOLOGIN")
        self.addCleanup(lambda: (self.connection.execute(f"DROP OWNED BY {role}"), self.connection.execute(f"DROP ROLE IF EXISTS {role}")))
        roles_dir = BACKEND / "roles"
        tables = (roles_dir / "03_table_grants.sql").read_text(encoding="utf-8")
        section = tables[tables.index("-- ===== vinto_app"):tables.index("-- ===== vinto_reference")]
        statements = [s for s in "\n".join(l for l in section.splitlines() if not l.lstrip().startswith(("--", "\\"))).split(";") if s.strip()]
        schema = re.search(r"GRANT USAGE ON SCHEMA [^;]+TO vinto_app;", (roles_dir / "02_schema_grants.sql").read_text(encoding="utf-8")).group(0)
        function = re.search(r"GRANT EXECUTE ON FUNCTION vinto_txn\.management_start_year\(date\) TO vinto_app;", (roles_dir / "04_function_grants.sql").read_text(encoding="utf-8")).group(0)
        grants_0007 = re.search(r'GRANT SELECT, INSERT, UPDATE ON vinto_master\."user_machine_form_grant" TO vinto_app;', (BACKEND / "migrations/0007_user_machine_form_grants.sql").read_text(encoding="utf-8")).group(0)
        for statement in [schema, function, grants_0007] + statements:
            self.connection.execute(statement.replace("vinto_app", role))
        self.grant()
        _, assignment = await self.assignment()
        app = connect(self.database)
        self.addCleanup(app.close)
        app.execute(f"SET ROLE {role}")
        body = self.payload(assignment)
        result = _capture_service.submit_production_capture(
            app, actor_id=self.operator, capture_id=body["capture_id"], form_code=P106, assignment_id=body["assignment_id"], device_key=body["device_key"], values=body["values"],
            request_id="rid", sectors=frozenset({"BOBINAS"}), gate=CentralCaptureGate(self.principal(), "enforce", "rid"))
        self.assertTrue(result.created)
        retry = _capture_service.submit_production_capture(
            app, actor_id=self.operator, capture_id=body["capture_id"], form_code=P106, assignment_id=body["assignment_id"], device_key=body["device_key"], values=body["values"],
            request_id="rid2", sectors=frozenset({"BOBINAS"}), gate=CentralCaptureGate(self.principal(), "enforce", "rid2"))
        self.assertTrue(retry.already_submitted)
        self.revoke()
        with self.assertRaises(AuthorizationDenied):
            _capture_service.submit_production_capture(
                app, actor_id=self.operator, capture_id=body["capture_id"], form_code=P106, assignment_id=body["assignment_id"], device_key=body["device_key"], values=body["values"],
                request_id="rid3", sectors=frozenset({"BOBINAS"}), gate=CentralCaptureGate(self.principal(), "enforce", "rid3"))


# ---- 6. auditoría y atribución -------------------------------------------------------------------------------------------------------------

class AuditTests(GateCase):
    def audit_shape(self, since):
        return sorted(self.connection.execute(
            """SELECT entity_table, action, actor_id IS NOT DISTINCT FROM %s, request_id IS NOT NULL FROM vinto_audit.audit_event WHERE occurred_at >= %s
               AND entity_table IN ('capture','capture_detail','device') ORDER BY 1, 2""", (self.operator, since)).fetchall())

    async def test_enforce_leaves_the_same_audit_trail_and_attribution_as_off(self):
        self.grant()
        _, first = await self.assignment()
        start_off = self.scalar("SELECT clock_timestamp()")
        with mode("off"):
            await self.submit(first)
        off_shape = self.audit_shape(start_off)
        _, second = await self.assignment()
        start_enforce = self.scalar("SELECT clock_timestamp()")
        grants_audit = self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table = 'user_machine_form_grant'")
        with mode("enforce"):
            _, reply = await self.submit(second)
        self.assertEqual(reply.status, 201)
        self.assertEqual(self.audit_shape(start_enforce), off_shape)
        self.assertTrue(all(row[2] for row in off_shape))  # todo evento de captura atribuido al operador
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table = 'user_machine_form_grant'"), grants_audit)  # la autorización no escribe


if __name__ == "__main__":
    unittest.main()
