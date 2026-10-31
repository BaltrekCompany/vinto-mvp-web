"""Integración del motor de autorización en POST /api/bobbins (F3, VINTO-P1-03) — MF-13-01D.2B: modos off / observe / enforce INDEPENDIENTES de los de la captura central.

HTTP contra la aplicación ASGI con una base *_test efímera (como test_f3_bobbins_api) y, donde hay que controlar bloqueos, nivel de servicio con conexiones propias. El modo lo fija SOLO
el servidor (`settings.authz_bobbin_production_mode`). Nada toca una base que no sea de prueba.
"""

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

from app import capture_service as cs
from app.auth.machine_form_grants import grant_machine_form, revoke_machine_form
from app.auth.service import AuthenticatedUser, create_user
from app.authz import capture_gate
from app.authz.capture_gate import OperationGate
from app.authz.errors import PUBLIC_FORBIDDEN, PUBLIC_UNAVAILABLE, AuthorizationDenied
from app.authz.policies import Operation
from app.bobbins import service as bobbin_service
from app.config import Settings, settings
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database

try:
    import test_f3_bobbins_api as f3
except ModuleNotFoundError:
    import tests.test_f3_bobbins_api as f3
try:
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.test_assignments_api import call

BACKEND = Path(__file__).resolve().parent.parent
P103, P106 = "VINTO-P1-03", "VINTO-P1-06"
OP = Operation.BOBBIN_PRODUCTION
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_d2b_tpl")
    f3.STATE["template"] = STATE["template"]


def tearDownModule():
    drop_database(STATE["template"])


@contextmanager
def mode(value):
    with patch.object(settings, "authz_bobbin_production_mode", value):
        yield


class GateCase(f3.BobbinApiCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.operator = self.users["OPERACION"][0].user_id
        self.actor = self.users["DATA_BALTREK"][0].user_id
        self.connection.execute("SELECT set_config('vinto.actor_id', %s, false)", (str(self.actor),))
        self.connection.execute("UPDATE vinto_master.user_machine_form_grant SET revoked_at = clock_timestamp(), revoked_by = %s WHERE revoked_at IS NULL", (self.actor,))
        self.start = self.counts()

    def grant(self, machine="MP1", form=P103, user=None):
        return grant_machine_form(self.connection, user_id=user or self.operator, machine_code=machine, form_code=form, actor_id=self.actor)

    def revoke(self, machine="MP1", form=P103, user=None):
        return revoke_machine_form(self.connection, user_id=user or self.operator, machine_code=machine, form_code=form, actor_id=self.actor)

    def counts(self):
        """Todo lo que una bobina F3 escribe, más lo que NO debe moverse."""
        tables = ("vinto_txn.capture", "vinto_txn.capture_detail", "vinto_txn.bobbin", "vinto_txn.quality_release", "vinto_master.device", "vinto_txn.work_order",
                  "vinto_txn.work_order_line", "vinto_master.user_machine_form_grant")
        return [self.scalar(f"SELECT count(*) FROM {t}") for t in tables] + [self.scalar("SELECT coalesce(sum(last_value), 0) FROM vinto_txn.bobbin_sequence"),
                                                                               self.scalar("SELECT count(*) FROM vinto_txn.assignment WHERE status = 'active'")]

    def delta(self):
        return [now - before for now, before in zip(self.counts(), self.start)]

    def written(self):
        """(capturas, detalles, bobinas, liberaciones, dispositivos, OT, líneas, concesiones, contador, asignaciones activas) creados desde el inicio de la prueba."""
        return self.delta()

    async def fresh_operator(self, sectors=("BOBINAS",), profile="OPERACION"):
        password = "pw-" + uuid4().hex
        created = create_user(self.connection, username=f"d2b.{uuid4().hex[:12]}", display_name="d2b", profile_code=profile, password=password, sectors=sectors)
        reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
        self.assertEqual(reply.status, 200)
        return created.user_id, reply.set_cookie_value()

    async def submit(self, assignment, *, cookie=None, **changes):
        body = self.payload(assignment, **changes)
        return body, await call("POST", "/api/bobbins", json_body=body, cookie=cookie or await self.cookie("OPERACION"))

    def nothing_written(self):
        delta = self.delta()  # captura, detalles, bobina, liberación, dispositivo y contador de numeración (las OT y asignaciones de la propia prueba no cuentan)
        self.assertEqual(delta[:5] + [delta[8]], [0] * 6, delta)


# ---- 1. configuración ---------------------------------------------------------------------------------------------------------------------------

class ConfigurationTests(unittest.TestCase):
    def test_the_default_is_off_the_value_is_normalised_and_unknown_values_do_not_start(self):
        self.assertEqual(Settings(_env_file=None).authz_bobbin_production_mode, "off")
        self.assertEqual(Settings(_env_file=None, authz_bobbin_production_mode=" Enforce ").authz_bobbin_production_mode, "enforce")
        for bad in ("on", "true", "", "enforced"):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None, authz_bobbin_production_mode=bad)

    def test_the_two_operations_have_independent_modes(self):
        both = Settings(_env_file=None, authz_bobbin_production_mode="enforce", authz_central_captures_mode="off")
        self.assertEqual((both.authz_bobbin_production_mode, both.authz_central_captures_mode), ("enforce", "off"))
        other = Settings(_env_file=None, authz_central_captures_mode="enforce")
        self.assertEqual((other.authz_bobbin_production_mode, other.authz_central_captures_mode), ("off", "enforce"))

    def test_each_router_reads_only_its_own_mode_and_the_client_cannot_choose(self):
        bobbins = (BACKEND / "app/bobbins/router.py").read_text(encoding="utf-8")
        central = (BACKEND / "app/captures.py").read_text(encoding="utf-8")
        self.assertIn("settings.authz_bobbin_production_mode", bobbins)
        self.assertNotIn("authz_central_captures_mode", bobbins)
        self.assertNotIn("authz_bobbin_production_mode", central)
        self.assertNotRegex(bobbins, r"Header\(|Query\(|body\.mode")
        from app.bobbins.schemas import BobbinIn
        self.assertEqual(BobbinIn.model_config.get("extra"), "forbid")
        self.assertEqual(set(BobbinIn.model_fields), {"capture_id", "assignment_id", "device_key", "values"})  # sin form_code, máquina ni modo: el formulario es la constante del backend

    def test_the_operation_and_the_form_are_fixed_by_the_backend(self):
        router = (BACKEND / "app/bobbins/router.py").read_text(encoding="utf-8")
        self.assertIn("Operation.BOBBIN_PRODUCTION", router)
        self.assertNotIn("PRODUCTION_CAPTURE)", router.split("gate_for")[1].split("\n")[0])
        self.assertEqual(bobbin_service.FORM_CODE, P103)
        user = AuthenticatedUser(uuid4(), "u", "U", ("OPERACION",), frozenset(), False)
        self.assertIsNone(capture_gate.gate_for(user, "off", "r", OP))
        gate = capture_gate.gate_for(user, "enforce", "r", OP)
        self.assertEqual((gate.operation, gate.mode), (OP, "enforce"))
        self.assertEqual(capture_gate.gate_for(user, "observe", "r").operation, Operation.PRODUCTION_CAPTURE)  # el valor por defecto sigue siendo la captura central


# ---- 2. off / observe -----------------------------------------------------------------------------------------------------------------------------

class OffAndObserveTests(GateCase):
    async def test_off_keeps_f3_whole_and_never_calls_the_engine(self):
        _, assignment = await self.assignment()
        with mode("off"), patch.object(capture_gate, "authorize", side_effect=AssertionError("motor en off")), patch.object(capture_gate, "require", side_effect=AssertionError("motor en off")):
            _, reply = await self.submit(assignment)  # sin ninguna concesión
        self.assertEqual((reply.status, reply.json()["created"]), (201, True))
        self.assertEqual(self.delta()[:4], [1, 6, 1, 1])  # captura, 6 detalles, bobina y liberación pendiente
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.quality_release WHERE bobbin_id = %s", (reply.json()["bobbin"]["id"],)), "pending")

    async def test_observe_never_changes_data_or_the_response_and_logs_the_bobbin_operation(self):
        _, assignment = await self.assignment()
        with mode("observe"), self.assertLogs("vinto.authz", level="INFO") as logs:
            body, reply = await self.submit(assignment)  # sin concesión: en enforce sería 403
        self.assertEqual((reply.status, reply.json()["created"]), (201, True))
        self.assertEqual(self.delta()[:4], [1, 6, 1, 1])
        self.assertTrue(any(re.search(r"mode=observe operation=bobbin_production outcome=would_forbidden reason=GRANT_MISSING request_id=[0-9a-f-]{36}", m) for m in logs.output))

    async def test_observe_with_a_grant_responds_exactly_as_off(self):
        self.grant()
        _, first = await self.assignment()
        with mode("observe"), self.assertLogs("vinto.authz", level="INFO") as logs:
            _, observed = await self.submit(first)
        _, second = await self.assignment()
        with mode("off"):
            _, plain = await self.submit(second)
        self.assertEqual((observed.status, plain.status, set(observed.json())), (201, 201, set(plain.json())))
        self.assertEqual(int(plain.json()["bobbin"]["code"]), int(observed.json()["bobbin"]["code"]) + 1)  # numeración correlativa
        self.assertTrue(any("operation=bobbin_production outcome=allowed reason=ALLOWED" in m for m in logs.output))

    async def test_observe_ignores_any_engine_failure_including_sql_and_the_bobbin_is_still_registered(self):
        _, assignment = await self.assignment()

        def broken(connection, *args, **kwargs):
            connection.execute("SELECT * FROM vinto_master.tabla_que_no_existe")

        with mode("observe"), patch.object(capture_gate, "authorize", side_effect=broken), self.assertLogs("vinto.authz", level="ERROR") as logs:
            _, reply = await self.submit(assignment)
        self.assertEqual((reply.status, self.delta()[:4]), (201, [1, 6, 1, 1]))
        self.assertTrue(any("operation=bobbin_production outcome=observe_error" in m for m in logs.output))

    async def test_logs_never_contain_cookies_users_or_form_values(self):
        _, assignment = await self.assignment()
        cookie = await self.cookie("OPERACION")
        with mode("observe"), self.assertLogs("vinto.authz", level="INFO") as logs:
            await self.submit(assignment, cookie=cookie)
        text = "\n".join(logs.output)
        for secret in (cookie, "845.25", "1200.5", str(self.operator), "pw-"):
            self.assertNotIn(secret, text)


# ---- 3. enforce: decisiones y atomicidad -------------------------------------------------------------------------------------------------------------

class EnforceDecisionTests(GateCase):
    async def test_a_granted_p1_03_registers_the_bobbin_with_its_pending_release(self):
        self.grant()
        _, assignment = await self.assignment()
        with mode("enforce"):
            _, reply = await self.submit(assignment)
        self.assertEqual((reply.status, reply.json()["created"], reply.json()["bobbin"]["machine"]["code"]), (201, True, "MP1"))
        self.assertEqual(self.delta()[:4], [1, 6, 1, 1])
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.quality_release WHERE bobbin_id = %s", (reply.json()["bobbin"]["id"],)), "pending")

    async def test_a_pair_that_was_not_granted_is_403_with_the_fixed_body_and_nothing_at_all_is_written(self):
        _, assignment = await self.assignment()
        start = self.counts()
        with mode("enforce"), self.assertLogs("vinto.authz", level="WARNING") as logs:
            _, reply = await self.submit(assignment)
        self.assertEqual((reply.status, reply.json()), (PUBLIC_FORBIDDEN[0], PUBLIC_FORBIDDEN[1]))
        self.assertEqual(self.counts(), start)  # ni captura, ni detalles, ni bobina, ni liberación, ni dispositivo, ni número reservado
        self.assertTrue(any("mode=enforce operation=bobbin_production outcome=forbidden reason=GRANT_MISSING" in m for m in logs.output))
        for leak in ("GRANT_MISSING", "MP1", "P1-03", "vinto_", "grant"):
            self.assertNotIn(leak, reply.body.decode())

    async def test_denied_requests_leave_no_gaps_in_the_numbering(self):
        _, assignment = await self.assignment()
        with mode("enforce"):
            self.assertEqual((await self.submit(assignment))[1].status, 403)
            self.grant()
            first = (await self.submit(assignment))[1].json()["bobbin"]
            self.revoke()
            self.assertEqual((await self.submit(assignment))[1].status, 403)
            self.assertEqual((await self.submit(assignment))[1].status, 403)
            self.grant()
            second = (await self.submit(assignment))[1].json()["bobbin"]
        self.assertEqual(int(second["code"]), int(first["code"]) + 1)
        self.assertEqual(self.delta()[2], 2)

    async def test_mp1_and_mp3_are_independent(self):
        self.grant("MP1")
        _, on_mp1 = await self.assignment("MP1")
        _, on_mp3 = await self.assignment("MP3")
        with mode("enforce"):
            self.assertEqual((await self.submit(on_mp3))[1].status, 403)
            self.assertEqual((await self.submit(on_mp1))[1].status, 201)
            self.grant("MP3")
            self.assertEqual((await self.submit(on_mp3))[1].status, 201)

    async def test_the_form_and_machine_are_never_chosen_by_the_client(self):
        self.grant("MP3")
        _, on_mp1 = await self.assignment("MP1")
        with mode("enforce"):
            for extra in ({"form_code": P106}, {"machine_code": "MP3"}, {"operation": "production_capture"}):
                reply = await call("POST", "/api/bobbins", json_body=self.payload(on_mp1, **extra), cookie=await self.cookie("OPERACION"))
                self.assertEqual(reply.status, 422, extra)
            self.assertEqual((await self.submit(on_mp1))[1].status, 403)  # la asignación es de MP1 y la concesión de MP3
        self.nothing_written()

    async def test_a_profile_without_the_permission_is_rejected(self):
        _, cookie = await self.fresh_operator(profile="CALIDAD")
        _, assignment = await self.assignment()
        with mode("enforce"):
            _, reply = await self.submit(assignment, cookie=cookie)
        self.assertEqual(reply.status, 403)
        self.nothing_written()

    async def test_a_sector_not_granted_or_not_operational_is_rejected(self):
        user, cookie = await self.fresh_operator(sectors=())
        self.grant(user=user)
        _, assignment = await self.assignment()
        with mode("enforce"):
            _, reply = await self.submit(assignment, cookie=cookie)
        self.assertIn(reply.status, (403, 404))  # el alcance de sectores existente responde 404 antes que el motor
        user2, cookie2 = await self.fresh_operator()
        self.grant(user=user2)
        self.connection.execute("UPDATE vinto_master.sector SET active = false WHERE code = 'BOBINAS'")
        try:
            with mode("enforce"):
                _, reply = await self.submit(assignment, cookie=cookie2)
            self.assertIn(reply.status, (403, 404, 409))
        finally:
            self.connection.execute("UPDATE vinto_master.sector SET active = true WHERE code = 'BOBINAS'")
        self.nothing_written()

    async def test_an_inactive_user_is_rejected(self):
        user, cookie = await self.fresh_operator()
        self.grant(user=user)
        _, assignment = await self.assignment()
        self.connection.execute('UPDATE vinto_master."user" SET active = false WHERE id = %s', (user,))
        with mode("enforce"):
            _, reply = await self.submit(assignment, cookie=cookie)
        self.assertIn(reply.status, (401, 403))
        self.nothing_written()

    async def test_an_inactive_form_or_machine_is_rejected_by_the_engine_before_any_write(self):
        self.grant()
        _, assignment = await self.assignment()
        for statement in (f"UPDATE vinto_config.form SET active = false WHERE code = '{P103}'", "UPDATE vinto_master.machine SET active = false WHERE code = 'MP1'"):
            self.connection.execute(statement)
            try:
                with mode("enforce"):
                    _, reply = await self.submit(assignment)
                self.assertEqual(reply.status, 403, statement)
            finally:
                self.connection.execute(statement.replace("active = false", "active = true"))
        self.nothing_written()

    async def test_a_revocation_confirmed_before_registering_blocks_the_write(self):
        self.grant()
        self.revoke()
        _, assignment = await self.assignment()
        with mode("enforce"):
            _, reply = await self.submit(assignment)
        self.assertEqual(reply.status, 403)
        self.nothing_written()

    async def test_an_engine_failure_is_503_and_leaves_no_partial_records(self):
        self.grant()
        _, assignment = await self.assignment()
        start = self.counts()
        self.connection.execute("ALTER TABLE vinto_master.user_machine_form_grant RENAME TO grants_gone")
        try:
            with mode("enforce"), self.assertLogs("vinto.authz", level="ERROR") as logs:
                _, reply = await self.submit(assignment)
        finally:
            self.connection.execute("ALTER TABLE vinto_master.grants_gone RENAME TO user_machine_form_grant")
        self.assertEqual((reply.status, reply.json()), (PUBLIC_UNAVAILABLE[0], PUBLIC_UNAVAILABLE[1]))
        self.assertEqual(self.counts(), start)
        self.assertTrue(any("operation=bobbin_production outcome=unavailable reason=42P01" in m for m in logs.output))
        self.assertNotIn("42P01", reply.body.decode())

    async def test_a_definitive_machine_that_differs_from_the_authorised_one_fails_closed(self):
        self.grant()
        _, assignment = await self.assignment()
        real = cs.lock_active_assignment

        def other_machine(connection, assignment_id, sectors):
            context = real(connection, assignment_id, sectors)
            return type(context)(uuid4(), context.shift_schedule_id, context.operating_date, context.article_version_id, context.now)
        start = self.counts()
        with mode("enforce"), patch.object(cs, "lock_active_assignment", other_machine):
            _, reply = await self.submit(assignment)
        self.assertEqual((reply.status, self.counts()), (503, start))

    async def test_existing_f3_errors_are_unchanged_when_authorised(self):
        self.grant()
        _, assignment = await self.assignment()
        with mode("enforce"):
            self.assertEqual((await self.submit(assignment, values={**f3.VALUES, "peso_kg": "-1"}))[1].status, 422)
            self.assertEqual((await self.submit({"id": str(uuid4())}))[1].status, 404)
        self.nothing_written()


# ---- 4. enforce: idempotencia ---------------------------------------------------------------------------------------------------------------------------

class EnforceIdempotencyTests(GateCase):
    async def test_a_retry_after_a_revocation_cannot_use_the_old_grant_and_duplicates_nothing(self):
        self.grant()
        _, assignment = await self.assignment()
        with mode("enforce"):
            body, first = await self.submit(assignment)
            self.assertEqual(first.status, 201)
            after_first = self.counts()
            self.revoke()
            retry = await call("POST", "/api/bobbins", json_body=body, cookie=await self.cookie("OPERACION"))
        self.assertEqual(retry.status, 403)
        self.assertEqual(self.counts()[:5] + self.counts()[8:], after_first[:5] + after_first[8:])  # bobina, captura, detalles, liberación y contador intactos
        with mode("off"):
            again = await call("POST", "/api/bobbins", json_body=body, cookie=await self.cookie("OPERACION"))
        self.assertEqual((again.status, again.json()["already_submitted"]), (200, True))

    async def test_a_legitimate_retry_still_authorised_survives_a_finished_assignment_without_duplicating(self):
        self.grant()
        _, assignment = await self.assignment()
        with mode("enforce"):
            body, first = await self.submit(assignment)
            self.assertEqual(first.status, 201)
            sequence = self.scalar("SELECT coalesce(sum(last_value), 0) FROM vinto_txn.bobbin_sequence")
            finish = await call("POST", f"/api/assignments/{assignment['id']}/finish", cookie=await self.cookie("SUPERVISION"))
            self.assertEqual(finish.status, 200)
            retry = await call("POST", "/api/bobbins", json_body=body, cookie=await self.cookie("OPERACION"))
        self.assertEqual((retry.status, retry.json()["created"], retry.json()["already_submitted"], retry.json()["bobbin"]), (200, False, True, first.json()["bobbin"]))
        self.assertEqual((self.delta()[:4], self.scalar("SELECT coalesce(sum(last_value), 0) FROM vinto_txn.bobbin_sequence")), ([1, 6, 1, 1], sequence))  # ni captura, ni bobina, ni correlativo nuevos

    async def test_idempotency_conflicts_are_kept_for_an_authorised_user(self):
        self.grant()
        _, assignment = await self.assignment()
        with mode("enforce"):
            body, first = await self.submit(assignment)
            changed = await call("POST", "/api/bobbins", json_body={**body, "values": {**f3.VALUES, "peso_kg": "1"}}, cookie=await self.cookie("OPERACION"))
            other_device = await call("POST", "/api/bobbins", json_body={**body, "device_key": str(uuid4())}, cookie=await self.cookie("OPERACION"))
        self.assertEqual((first.status, changed.status, other_device.status), (201, 409, 409))
        self.assertEqual(self.delta()[:4], [1, 6, 1, 1])

    async def test_a_capture_id_that_belongs_to_another_operation_gains_no_access_and_is_not_reused(self):
        """Un capture_id de una captura central (P1-06) enviado a /api/bobbins: se autoriza el par PERSISTIDO (P1-06 no lo admite F3) → 403, sin reutilizarla ni crear bobina."""
        self.grant(form=P103)
        self.grant(form=P106)
        _, assignment = await self.assignment()
        central = await call("POST", "/api/captures", json_body={"capture_id": str(uuid4()), "form_code": P106, "assignment_id": assignment["id"], "device_key": str(uuid4()),
                                                                 "values": {"cantidad_fardos": 10, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "125.50", "observaciones": "ok"}},
                             cookie=await self.cookie("OPERACION"))
        self.assertEqual(central.status, 201)
        captured = central.json()["capture"]["id"]
        with mode("enforce"):
            reply = await call("POST", "/api/bobbins", json_body={"capture_id": captured, "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": dict(f3.VALUES)},
                               cookie=await self.cookie("OPERACION"))
        self.assertEqual(reply.status, 403)
        self.assertEqual(self.delta()[2:4], [0, 0])
        with mode("off"):  # sin la compuerta el comportamiento histórico es el conflicto de idempotencia
            old = await call("POST", "/api/bobbins", json_body={"capture_id": captured, "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": dict(f3.VALUES)},
                             cookie=await self.cookie("OPERACION"))
        self.assertEqual(old.status, 409)


# ---- 5. versión vigente de otra área o no ofrecida ---------------------------------------------------------------------------------------------------

class VersionTests(GateCase):
    def add_version(self, number, area, machine=None):
        c = self.connection
        c.execute("DROP TABLE IF EXISTS _fv")
        c.execute("CREATE TEMP TABLE _fv AS SELECT * FROM vinto_config.form_version WHERE form_id = (SELECT id FROM vinto_config.form WHERE code = %s) ORDER BY version_number DESC LIMIT 1", (P103,))
        c.execute("UPDATE _fv SET id = gen_random_uuid(), version_number = %s, area = %s, status = 'draft', published_at = NULL", (number, area))
        c.execute("INSERT INTO vinto_config.form_version SELECT * FROM _fv")
        if machine:
            c.execute("INSERT INTO vinto_config.form_version_machine (form_version_id, machine_id) SELECT (SELECT id FROM _fv), id FROM vinto_master.machine WHERE code = %s", (machine,))
        c.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = (SELECT id FROM _fv)")

    async def test_a_vigente_version_of_another_area_or_not_offered_denies_and_writes_nothing(self):
        self.grant()
        _, assignment = await self.assignment()
        self.add_version(2, "quality")  # vigente de OTRA área, sin vínculo
        start = self.counts()
        with mode("enforce"), self.assertLogs("vinto.authz", level="WARNING") as logs:
            _, other_area = await self.submit(assignment)
        self.assertEqual((other_area.status, self.counts()), (403, start))
        self.assertTrue(any("reason=EFFECTIVE_VERSION_OTHER_AREA" in m for m in logs.output))
        self.add_version(3, "production")  # vigente de la misma área que ya no vincula MP1
        with mode("enforce"), self.assertLogs("vinto.authz", level="WARNING") as logs:
            _, not_offered = await self.submit(assignment)
        self.assertEqual((not_offered.status, self.counts()), (403, start))
        self.assertTrue(any("reason=PAIR_NOT_OFFERED" in m for m in logs.output))


# ---- 6. bloqueos, concurrencia y rol equivalente a vinto_app --------------------------------------------------------------------------------------------

class LockingTests(GateCase):
    def principal(self):
        return AuthenticatedUser(self.operator, "u", "U", ("OPERACION",), frozenset(), False, frozenset({"BOBINAS"}))

    def run_submit(self, assignment, gate, results, connection=None):
        body = self.payload(assignment)

        def work():
            conn = connection or connect(self.database)
            try:
                results.append(bobbin_service.submit_bobbin_production(
                    conn, actor_id=self.operator, capture_id=body["capture_id"], assignment_id=body["assignment_id"], device_key=body["device_key"], values=body["values"],
                    request_id="rid", sectors=frozenset({"BOBINAS"}), gate=gate))
            except BaseException as error:  # noqa: BLE001
                results.append(error)
            finally:
                if connection is None:
                    conn.close()
        return threading.Thread(target=work)

    async def test_a_concurrent_revocation_waits_for_the_bobbin_transaction_and_the_next_one_is_denied(self):
        self.grant()
        _, assignment = await self.assignment()
        inside, release, results = threading.Event(), threading.Event(), []
        real = cs._resolve_device

        def paused(connection, device_key, machine_id):
            inside.set()  # ya autorizada y con el bloqueo de máquina: sigue dentro de la transacción que registra la bobina
            release.wait(20)
            return real(connection, device_key, machine_id)
        with patch.object(cs, "_resolve_device", paused):
            thread = self.run_submit(assignment, OperationGate(self.principal(), "enforce", "rid", OP), results)
            thread.start()
            self.assertTrue(inside.wait(20))
            revoker = connect(self.database)
            self.addCleanup(revoker.close)
            with self.assertRaises(psycopg.errors.LockNotAvailable), revoker.transaction():
                revoker.execute("SET LOCAL lock_timeout = 400")
                revoker.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(self.actor),))
                revoker.execute("UPDATE vinto_master.user_machine_form_grant SET revoked_at = clock_timestamp(), revoked_by = %s WHERE revoked_at IS NULL", (self.actor,))
            release.set()
            thread.join(30)
        self.assertTrue(results and getattr(results[0], "created", False), results)
        self.revoke()
        _, second = await self.assignment()
        with mode("enforce"):
            self.assertEqual((await self.submit(second))[1].status, 403)

    async def test_observe_holds_no_authorisation_locks(self):
        self.grant()
        _, assignment = await self.assignment()
        inside, release, results = threading.Event(), threading.Event(), []
        real = cs._resolve_device

        def paused(connection, device_key, machine_id):
            inside.set()
            release.wait(20)
            return real(connection, device_key, machine_id)
        with patch.object(cs, "_resolve_device", paused):
            thread = self.run_submit(assignment, OperationGate(self.principal(), "observe", "rid", OP), results)
            thread.start()
            self.assertTrue(inside.wait(20))
            self.revoke()  # no bloquea
            release.set()
            thread.join(30)
        self.assertTrue(results and getattr(results[0], "created", False), results)

    async def test_no_deadlocks_and_a_gapless_numbering_under_concurrent_bobbins_grants_and_revocations(self):
        self.grant()
        _, assignment = await self.assignment()
        errors, outcomes = [], []
        principal = self.principal()

        def submitter(index):
            conn = connect(self.database)
            try:
                for _ in range(5):
                    body = self.payload(assignment)
                    for attempt in range(2):  # la segunda es un reintento idéntico
                        try:
                            result = bobbin_service.submit_bobbin_production(
                                conn, actor_id=self.operator, capture_id=body["capture_id"], assignment_id=body["assignment_id"], device_key=body["device_key"],
                                values=body["values"], request_id=f"rid-{index}", sectors=frozenset({"BOBINAS"}), gate=OperationGate(principal, "enforce", f"rid-{index}", OP))
                            outcomes.append("created" if result.created else "retry")
                        except AuthorizationDenied:
                            outcomes.append("denied")
            except BaseException as error:  # noqa: BLE001 — un deadlock o AuthorizationUnavailable aparece aquí
                errors.append(repr(error))
            finally:
                conn.close()

        def toggler():
            conn = connect(self.database)
            try:
                for _ in range(10):
                    grant_machine_form(conn, user_id=self.operator, machine_code="MP1", form_code=P103, actor_id=self.actor)
                    time.sleep(0.01)
                    revoke_machine_form(conn, user_id=self.operator, machine_code="MP1", form_code=P103, actor_id=self.actor)
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
        self.assertIn("created", outcomes)
        created = outcomes.count("created")
        numbers = [r[0] for r in self.connection.execute("SELECT sequence_number FROM vinto_txn.bobbin b JOIN vinto_master.machine m ON m.id = b.machine_id WHERE m.code = 'MP1' ORDER BY 1").fetchall()]
        self.assertEqual(self.delta()[2], created)
        self.assertEqual(numbers, list(range(numbers[0], numbers[0] + len(numbers))))  # sin saltos aunque hubo solicitudes denegadas

    async def test_the_flow_runs_with_the_privileges_of_vinto_app(self):
        """Rol construido desde backend/roles/*.sql y la 0007 (sin UPDATE en user_sector ni vinto_config): bobina, reintento y denegación tras revocar."""
        role = "d2b_app_" + uuid4().hex[:8]
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

        def submit(request_id):
            return bobbin_service.submit_bobbin_production(
                app, actor_id=self.operator, capture_id=body["capture_id"], assignment_id=body["assignment_id"], device_key=body["device_key"], values=body["values"],
                request_id=request_id, sectors=frozenset({"BOBINAS"}), gate=OperationGate(self.principal(), "enforce", request_id, OP))
        self.assertTrue(submit("rid").created)
        self.assertTrue(submit("rid2").already_submitted)
        self.revoke()
        with self.assertRaises(AuthorizationDenied):
            submit("rid3")
        self.assertEqual(self.delta()[:4], [1, 6, 1, 1])


# ---- 7. la captura central y los demás flujos no se alteran -----------------------------------------------------------------------------------------------

class CoexistenceTests(GateCase):
    async def central(self, assignment):
        return await call("POST", "/api/captures", json_body={"capture_id": str(uuid4()), "form_code": P106, "assignment_id": assignment["id"], "device_key": str(uuid4()),
                                                               "values": {"cantidad_fardos": 10, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "125.50", "observaciones": "ok"}},
                          cookie=await self.cookie("OPERACION"))

    async def test_each_operation_obeys_only_its_own_mode(self):
        _, assignment = await self.assignment()
        with patch.object(settings, "authz_central_captures_mode", "off"), mode("enforce"):
            self.assertEqual((await self.submit(assignment))[1].status, 403)  # F3 en enforce
            self.assertEqual((await self.central(assignment)).status, 201)  # la central sigue en off: sin concesión pasa
        _, other = await self.assignment()
        with patch.object(settings, "authz_central_captures_mode", "enforce"), mode("off"):
            self.assertEqual((await self.central(other)).status, 403)  # la central en enforce
            self.assertEqual((await self.submit(other))[1].status, 201)  # F3 sigue en off

    async def test_the_three_central_modes_still_work_with_f3_enforcing(self):
        self.grant(form=P106)
        with mode("enforce"):
            for central_mode, expected in (("off", 201), ("observe", 201), ("enforce", 201)):
                _, assignment = await self.assignment()
                with patch.object(settings, "authz_central_captures_mode", central_mode):
                    self.assertEqual((await self.central(assignment)).status, expected, central_mode)
            self.revoke(form=P106)
            _, assignment = await self.assignment()
            with patch.object(settings, "authz_central_captures_mode", "enforce"):
                self.assertEqual((await self.central(assignment)).status, 403)

    async def test_orders_assignments_and_quality_are_untouched_by_an_enforced_bobbin(self):
        self.grant()
        _, assignment = await self.assignment()
        orders = self.scalar("SELECT count(*) FROM vinto_txn.work_order")
        quality = self.scalar("SELECT count(*) FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id = c.form_version_id WHERE fv.area = 'quality'")
        status = self.scalar("SELECT status FROM vinto_txn.assignment WHERE id = %s", (assignment["id"],))
        with mode("enforce"):
            self.assertEqual((await self.submit(assignment))[1].status, 201)
        self.assertEqual((self.scalar("SELECT count(*) FROM vinto_txn.work_order"), self.scalar("SELECT status FROM vinto_txn.assignment WHERE id = %s", (assignment["id"],)),
                          self.scalar("SELECT count(*) FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id = c.form_version_id WHERE fv.area = 'quality'")), (orders, status, quality))


if __name__ == "__main__":
    unittest.main()
