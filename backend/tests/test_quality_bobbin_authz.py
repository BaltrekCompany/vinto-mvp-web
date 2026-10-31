"""Integración del motor de autorización en POST /api/quality/bobbins/{id}/captures (Calidad por bobina) — MF-13-01D.2C.1: modos off / observe / enforce INDEPENDIENTES.

HTTP contra la aplicación ASGI con una base *_test efímera (como test_quality_capture_api) y, donde hay que controlar bloqueos, nivel de servicio con conexiones propias. Se usan los formularios
REALES del bundle (P1-19, P1-20 y los candidatos por bobina). El modo lo fija SOLO el servidor (`settings.authz_quality_bobbin_captures_mode`). Nada toca una base que no sea de prueba.
"""

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
from app.authz import authorize, capture_gate
from app.authz.capture_gate import OperationGate
from app.authz.errors import PUBLIC_FORBIDDEN, PUBLIC_UNAVAILABLE, AuthorizationDenied
from app.authz.policies import Operation, policy_for
from app.config import Settings, settings
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database
from app.quality import capture_service as quality

try:
    import test_f3_bobbins_api as f3
except ModuleNotFoundError:
    import tests.test_f3_bobbins_api as f3
try:
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.test_assignments_api import call

BACKEND = Path(__file__).resolve().parent.parent
P101, P103, P118, P119, P120, P121, P124, P125, P128 = ("VINTO-P1-01", "VINTO-P1-03", "VINTO-P1-18", "VINTO-P1-19", "VINTO-P1-20", "VINTO-P1-21", "VINTO-P1-24", "VINTO-P1-25", "VINTO-P1-28")
OP = Operation.QUALITY_BOBBIN_CAPTURE
P119_VALUES = {"peso_humedo_comando": "100.50", "peso_seco_comando": "94.10", "peso_humedo_medio": "101.000", "peso_seco_medio": "95.25",
               "peso_humedo_transversal": "99.9", "peso_seco_transversal": "93.80", "observaciones": "ensayo real P1-19"}
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_d2c1_tpl")
    f3.STATE["template"] = STATE["template"]


def tearDownModule():
    drop_database(STATE["template"])


@contextmanager
def mode(value):
    with patch.object(settings, "authz_quality_bobbin_captures_mode", value):
        yield


class GateCase(f3.BobbinApiCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.quality_user = self.users["CALIDAD"][0].user_id
        self.actor = self.users["DATA_BALTREK"][0].user_id
        self.connection.execute("SELECT set_config('vinto.actor_id', %s, false)", (str(self.actor),))
        self.connection.execute("UPDATE vinto_master.user_machine_form_grant SET revoked_at = clock_timestamp(), revoked_by = %s WHERE revoked_at IS NULL", (self.actor,))

    def grant(self, machine="MP1", form=P119, user=None):
        return grant_machine_form(self.connection, user_id=user or self.quality_user, machine_code=machine, form_code=form, actor_id=self.actor)

    def revoke(self, machine="MP1", form=P119, user=None):
        return revoke_machine_form(self.connection, user_id=user or self.quality_user, machine_code=machine, form_code=form, actor_id=self.actor)

    def counts(self):
        """Lo que una captura de Calidad escribe (capturas, detalles, dispositivos) y lo que NO debe moverse (liberaciones, bobinas, OT, asignaciones, concesiones)."""
        tables = ("vinto_txn.capture", "vinto_txn.capture_detail", "vinto_master.device", "vinto_txn.quality_release", "vinto_txn.bobbin", "vinto_txn.work_order",
                  "vinto_master.user_machine_form_grant")
        return [self.scalar(f"SELECT count(*) FROM {t}") for t in tables] + [self.scalar("SELECT count(*) FROM vinto_txn.assignment WHERE status = 'active'")]

    def release(self, bobbin_id):
        return self.connection.execute("SELECT status, decided_by, decided_at, decision_reason, updated_at FROM vinto_txn.quality_release WHERE bobbin_id = %s", (bobbin_id,)).fetchone()

    async def bobbin(self, machine="MP1"):
        """Una bobina F3 real (con el modo de F3 en off, como hoy)."""
        _, assignment = await self.assignment(machine)
        reply = await self.post(self.payload(assignment))
        self.assertEqual(reply.status, 201)
        return reply.json()["bobbin"]

    def body(self, form=P119, values=None, **changes):
        body = {"capture_id": str(uuid4()), "form_code": form, "device_key": str(uuid4()), "values": dict(values or P119_VALUES)}
        body.update(changes)
        return body

    async def submit(self, bobbin, body=None, *, profile="CALIDAD", cookie=None):
        body = body or self.body()
        bobbin_id = bobbin["id"] if isinstance(bobbin, dict) else bobbin
        return body, await call("POST", f"/api/quality/bobbins/{bobbin_id}/captures", json_body=body, cookie=cookie or await self.cookie(profile))

    async def fresh_user(self, sectors=("BOBINAS",), profile="CALIDAD"):
        password = "pw-" + uuid4().hex
        created = create_user(self.connection, username=f"d2c.{uuid4().hex[:12]}", display_name="d2c", profile_code=profile, password=password, sectors=sectors)
        reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
        self.assertEqual(reply.status, 200)
        return created.user_id, reply.set_cookie_value()

    def unchanged_since(self, start, *, writes=(0, 0, 0)):
        """Compara con `start`: (capturas, detalles, dispositivos) según `writes`; el resto no se mueve nunca."""
        now = self.counts()
        delta = [a - b for a, b in zip(now, start)]
        self.assertEqual(delta[:3], list(writes), delta)
        self.assertEqual(delta[3:], [0] * 5, delta)  # quality_release, bobinas, OT, concesiones y asignaciones intactas


# ---- 1. configuración -------------------------------------------------------------------------------------------------------------------------------

class ConfigurationTests(unittest.TestCase):
    def test_default_off_normalised_and_unknown_values_do_not_start(self):
        self.assertEqual(Settings(_env_file=None).authz_quality_bobbin_captures_mode, "off")
        self.assertEqual(Settings(_env_file=None, authz_quality_bobbin_captures_mode=" OBSERVE ").authz_quality_bobbin_captures_mode, "observe")
        for bad in ("on", "true", "", "enforced"):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None, authz_quality_bobbin_captures_mode=bad)

    def test_the_three_modes_are_independent(self):
        s = Settings(_env_file=None, authz_quality_bobbin_captures_mode="enforce")
        self.assertEqual((s.authz_central_captures_mode, s.authz_bobbin_production_mode, s.authz_quality_bobbin_captures_mode), ("off", "off", "enforce"))
        s = Settings(_env_file=None, authz_central_captures_mode="enforce", authz_bobbin_production_mode="observe")
        self.assertEqual(s.authz_quality_bobbin_captures_mode, "off")

    def test_each_router_reads_only_its_own_mode_and_the_client_cannot_choose(self):
        quality_router = (BACKEND / "app/quality/router.py").read_text(encoding="utf-8")
        self.assertIn("settings.authz_quality_bobbin_captures_mode", quality_router)
        self.assertIn("Operation.QUALITY_BOBBIN_CAPTURE", quality_router)
        for other in ("authz_central_captures_mode", "authz_bobbin_production_mode"):
            self.assertNotIn(other, quality_router)
        self.assertNotIn("authz_quality_bobbin_captures_mode", (BACKEND / "app/captures.py").read_text(encoding="utf-8") + (BACKEND / "app/bobbins/router.py").read_text(encoding="utf-8"))
        self.assertNotRegex(quality_router, r"Header\(|body\.mode")
        from app.quality.capture_schemas import QualityCaptureIn
        self.assertEqual(QualityCaptureIn.model_config.get("extra"), "forbid")
        self.assertNotIn("machine_code", QualityCaptureIn.model_fields)

    def test_machine_level_quality_has_its_own_mode_and_never_reads_this_one(self):
        machine_router = (BACKEND / "app/quality/machine_router.py").read_text(encoding="utf-8")  # MF-13-01D.2C.2: Calidad por máquina se conectó con su propia configuración
        self.assertIn("settings.authz_quality_machine_captures_mode", machine_router)
        self.assertNotIn("authz_quality_bobbin_captures_mode", machine_router)


# ---- 2. política viva y hallazgo de los candidatos ---------------------------------------------------------------------------------------------------

class LivePolicyTests(unittest.TestCase):
    def test_the_engine_policy_is_exactly_the_live_service_policy(self):
        self.assertEqual(policy_for(OP).admitted(), frozenset(quality._allowed_codes()))
        self.assertEqual(policy_for(OP).permission, "quality.capture")

    def test_finding_the_four_candidates_are_enabled_in_the_code_today(self):
        """HALLAZGO para validación funcional: comentarios históricos hablan de candidatos deshabilitados/«vacío en producción», pero el código HABILITA hoy P1-21/24/25/28."""
        self.assertEqual(quality.ENABLED_BOBBIN_CANDIDATE_FORM_CODES, quality.BOBBIN_CANDIDATE_FORM_CODES)
        self.assertEqual(policy_for(OP).admitted(), frozenset({P119, P120, P121, P124, P125, P128}))

    def test_the_engine_follows_the_constants_without_enabling_or_disabling_anything(self):
        with patch.object(quality, "ENABLED_BOBBIN_CANDIDATE_FORM_CODES", frozenset()):
            self.assertEqual(policy_for(OP).admitted(), frozenset({P119, P120}))
            self.assertEqual(quality._allowed_codes(), [P119, P120])
        with patch.object(quality, "ENABLED_BOBBIN_CANDIDATE_FORM_CODES", frozenset({P128})):
            self.assertEqual(policy_for(OP).admitted(), frozenset({P119, P120, P128}))
        with patch.object(quality, "ENABLED_BOBBIN_CANDIDATE_FORM_CODES", frozenset({"VINTO-P1-99"})):  # un código no candidato no se cuela
            self.assertEqual(policy_for(OP).admitted(), frozenset({P119, P120}))

    def test_forms_of_other_routes_are_not_admitted(self):
        admitted = policy_for(OP).admitted()
        for other in (P101, P103, P118, "VINTO-P1-22", "VINTO-P1-26", "VINTO-P1-27", "VINTO-P1-06"):
            self.assertNotIn(other, admitted)


# ---- 3. off / observe ---------------------------------------------------------------------------------------------------------------------------------

class OffAndObserveTests(GateCase):
    async def test_off_keeps_the_original_operation_and_never_calls_the_engine(self):
        bobbin = await self.bobbin()
        start, release = self.counts(), self.release(bobbin["id"])
        with mode("off"), patch.object(capture_gate, "authorize", side_effect=AssertionError("motor en off")), patch.object(capture_gate, "require", side_effect=AssertionError("motor en off")):
            _, reply = await self.submit(bobbin)  # sin ninguna concesión
        self.assertEqual((reply.status, reply.json()["created"]), (201, True))
        self.unchanged_since(start, writes=(1, 7, 1))
        self.assertEqual(self.release(bobbin["id"]), release)

    async def test_observe_never_changes_data_or_the_response_and_logs_the_operation(self):
        bobbin = await self.bobbin()
        start = self.counts()
        with mode("observe"), self.assertLogs("vinto.authz", level="INFO") as logs:
            _, reply = await self.submit(bobbin)  # sin concesión: en enforce sería 403
        self.assertEqual((reply.status, reply.json()["created"]), (201, True))
        self.unchanged_since(start, writes=(1, 7, 1))
        self.assertTrue(any(re.search(r"mode=observe operation=quality_bobbin_capture outcome=would_forbidden reason=GRANT_MISSING request_id=[0-9a-f-]{36}", m) for m in logs.output))

    async def test_observe_with_a_grant_responds_exactly_as_off(self):
        self.grant()
        bobbin = await self.bobbin()
        with mode("observe"), self.assertLogs("vinto.authz", level="INFO") as logs:
            _, observed = await self.submit(bobbin)
        with mode("off"):
            _, plain = await self.submit(bobbin)
        self.assertEqual((observed.status, plain.status, set(observed.json())), (201, 201, set(plain.json())))
        self.assertTrue(any("operation=quality_bobbin_capture outcome=allowed reason=ALLOWED" in m for m in logs.output))

    async def test_observe_ignores_any_engine_failure_including_sql(self):
        bobbin = await self.bobbin()

        def broken(connection, *args, **kwargs):
            connection.execute("SELECT * FROM vinto_master.tabla_que_no_existe")
        with mode("observe"), patch.object(capture_gate, "authorize", side_effect=broken), self.assertLogs("vinto.authz", level="ERROR") as logs:
            _, reply = await self.submit(bobbin)
        self.assertEqual(reply.status, 201)
        self.assertTrue(any("operation=quality_bobbin_capture outcome=observe_error" in m for m in logs.output))

    async def test_logs_never_contain_cookies_users_or_values(self):
        bobbin = await self.bobbin()
        cookie = await self.cookie("CALIDAD")
        with mode("observe"), self.assertLogs("vinto.authz", level="INFO") as logs:
            await self.submit(bobbin, cookie=cookie)
        text = "\n".join(logs.output)
        for secret in (cookie, "100.50", "ensayo real", str(self.quality_user), "pw-"):
            self.assertNotIn(secret, text)


# ---- 4. enforce: decisiones ---------------------------------------------------------------------------------------------------------------------------

class EnforceDecisionTests(GateCase):
    async def test_a_granted_form_is_allowed_and_quality_release_is_untouched(self):
        self.grant()
        bobbin = await self.bobbin()
        start, release = self.counts(), self.release(bobbin["id"])
        with mode("enforce"):
            _, reply = await self.submit(bobbin)
        self.assertEqual((reply.status, reply.json()["created"], reply.json()["capture"]["machine"]["code"]), (201, True, "MP1"))
        self.unchanged_since(start, writes=(1, 7, 1))
        self.assertEqual(self.release(bobbin["id"]), release)  # la autorización no libera, rechaza ni aprueba nada

    async def test_a_form_that_was_not_granted_is_403_with_the_fixed_body_and_nothing_is_written(self):
        self.grant(form=P119)
        bobbin = await self.bobbin()
        start = self.counts()
        with mode("enforce"), self.assertLogs("vinto.authz", level="WARNING") as logs:
            _, reply = await self.submit(bobbin, self.body(form=P120, values=P120_VALUES))  # concedido P1-19, no P1-20
        self.assertEqual((reply.status, reply.json()), (PUBLIC_FORBIDDEN[0], PUBLIC_FORBIDDEN[1]))
        self.unchanged_since(start)  # ni captura, ni detalles, ni dispositivo
        self.assertTrue(any("mode=enforce operation=quality_bobbin_capture outcome=forbidden reason=GRANT_MISSING" in m for m in logs.output))
        for leak in ("GRANT_MISSING", "MP1", "P1-20", "vinto_", "grant"):
            self.assertNotIn(leak, reply.body.decode())

    async def test_mp1_and_mp3_are_independent(self):
        self.grant("MP1")
        on_mp1, on_mp3 = await self.bobbin("MP1"), await self.bobbin("MP3")
        with mode("enforce"):
            self.assertEqual((await self.submit(on_mp3))[1].status, 403)
            self.assertEqual((await self.submit(on_mp1))[1].status, 201)
            self.grant("MP3")
            self.assertEqual((await self.submit(on_mp3))[1].status, 201)

    async def test_the_machine_comes_from_the_persisted_bobbin_not_from_the_client(self):
        self.grant("MP3")  # concedida en MP3, pero la bobina es de MP1
        bobbin = await self.bobbin("MP1")
        start = self.counts()
        with mode("enforce"):
            for extra in ({"machine_code": "MP3"}, {"operation": "x"}, {"bobbin_id": str(uuid4())}):
                reply = await call("POST", f"/api/quality/bobbins/{bobbin['id']}/captures", json_body={**self.body(), **extra}, cookie=await self.cookie("CALIDAD"))
                self.assertEqual(reply.status, 422, extra)
            self.assertEqual((await self.submit(bobbin))[1].status, 403)
        self.unchanged_since(start)

    async def test_a_production_grant_is_not_a_quality_permission(self):
        self.grant("MP1", P101)
        self.grant("MP1", P103)
        bobbin = await self.bobbin()
        start = self.counts()
        with mode("enforce"):
            self.assertEqual((await self.submit(bobbin))[1].status, 403)  # P1-19 sin su propia concesión
        self.unchanged_since(start)

    async def test_a_profile_without_quality_capture_is_rejected_even_with_a_grant(self):
        operator = self.users["OPERACION"][0].user_id
        self.grant(user=operator)
        bobbin = await self.bobbin()
        start = self.counts()
        with mode("enforce"):
            _, reply = await self.submit(bobbin, profile="OPERACION")
        self.assertEqual(reply.status, 403)
        self.unchanged_since(start)

    async def test_an_inactive_user_or_an_ungranted_sector_cannot_operate(self):
        user, cookie = await self.fresh_user()
        self.grant(user=user)
        bobbin = await self.bobbin()
        start = self.counts()
        self.connection.execute('UPDATE vinto_master."user" SET active = false WHERE id = %s', (user,))
        with mode("enforce"):
            self.assertIn((await self.submit(bobbin, cookie=cookie))[1].status, (401, 403))
        self.unchanged_since(start)
        no_sector, cookie2 = await self.fresh_user(sectors=())
        self.grant(user=no_sector)
        start = self.counts()
        with mode("enforce"):
            self.assertIn((await self.submit(bobbin, cookie=cookie2))[1].status, (403, 404))  # el alcance de sectores existente responde 404 antes que el motor
        self.unchanged_since(start)

    async def test_an_inactive_form_or_machine_is_rejected_by_the_engine_before_any_write(self):
        self.grant()
        bobbin = await self.bobbin()
        start = self.counts()
        for statement in (f"UPDATE vinto_config.form SET active = false WHERE code = '{P119}'", "UPDATE vinto_master.machine SET active = false WHERE code = 'MP1'"):
            self.connection.execute(statement)
            try:
                with mode("enforce"):
                    self.assertEqual((await self.submit(bobbin))[1].status, 403, statement)
            finally:
                self.connection.execute(statement.replace("active = false", "active = true"))
        self.unchanged_since(start)

    async def test_forms_of_other_routes_keep_the_functional_422_before_any_authorisation(self):
        self.grant("MP1", P101)
        bobbin = await self.bobbin()
        start = self.counts()
        with mode("enforce"), patch.object(capture_gate, "require", side_effect=AssertionError("la política funcional va primero")):
            for other in (P101, P103, P118, "VINTO-P1-22", "NO-SUCH"):
                self.assertEqual((await self.submit(bobbin, self.body(form=other)))[1].status, 422, other)
        self.unchanged_since(start)

    async def test_a_revocation_confirmed_before_the_capture_blocks_the_write(self):
        self.grant()
        self.revoke()
        bobbin = await self.bobbin()
        start = self.counts()
        with mode("enforce"):
            self.assertEqual((await self.submit(bobbin))[1].status, 403)
        self.unchanged_since(start)

    async def test_an_engine_failure_is_503_and_leaves_no_partial_records(self):
        self.grant()
        bobbin = await self.bobbin()
        start = self.counts()
        self.connection.execute("ALTER TABLE vinto_master.user_machine_form_grant RENAME TO grants_gone")
        try:
            with mode("enforce"), self.assertLogs("vinto.authz", level="ERROR") as logs:
                _, reply = await self.submit(bobbin)
        finally:
            self.connection.execute("ALTER TABLE vinto_master.grants_gone RENAME TO user_machine_form_grant")
        self.assertEqual((reply.status, reply.json()), (PUBLIC_UNAVAILABLE[0], PUBLIC_UNAVAILABLE[1]))
        self.unchanged_since(start)
        self.assertTrue(any("operation=quality_bobbin_capture outcome=unavailable reason=42P01" in m for m in logs.output))
        self.assertNotIn("42P01", reply.body.decode())

    async def test_a_definitive_machine_that_differs_from_the_authorised_one_fails_closed(self):
        self.grant()
        bobbin = await self.bobbin()
        start = self.counts()
        real, calls = quality._bobbin_context, []

        def shifting(connection, bobbin_id, sectors):
            context = real(connection, bobbin_id, sectors)
            calls.append(1)
            return context if len(calls) == 1 else type(context)(context.bobbin_id, uuid4(), context.shift_schedule_id, context.operating_date, context.assignment_id)
        with mode("enforce"), patch.object(quality, "_bobbin_context", shifting):
            _, reply = await self.submit(bobbin)
        self.assertEqual(reply.status, 503)
        self.unchanged_since(start)

    async def test_existing_quality_errors_and_their_precedence_are_unchanged_when_authorised(self):
        self.grant()
        bobbin = await self.bobbin()
        start = self.counts()
        with mode("enforce"):
            self.assertEqual((await self.submit(bobbin, self.body(values={**P119_VALUES, "peso_seco_medio": "x"})))[1].status, 422)  # valores inválidos: el 422 de siempre
            self.assertEqual((await self.submit(str(uuid4())))[1].status, 404)  # bobina inexistente: 404 del servicio, antes del motor
        self.unchanged_since(start)


P120_VALUES = {"crepado": "18.50", "gramaje": "15.500", "resistencia_longitudinal_centro": "410.0", "resistencia_longitudinal_medio": "398", "resistencia_longitudinal_extremo": "402.5",
               "resistencia_transversal_centro": "200", "resistencia_transversal_medio": "199.5", "resistencia_transversal_extremo": "201", "observaciones": "ensayo real P1-20"}


# ---- 5. candidatos y P1-28 documental ---------------------------------------------------------------------------------------------------------------------

class CandidateTests(GateCase):
    def p128(self, bobbin):
        return {"numero_de_bobina": bobbin["code"], "producto": "Papel", "detalle_motivo_de_rechazo": "Mancha", "accion_correctiva": "Revisar", "peso_rechazado": "1.50", "estado_disposicion_final": "pendiente"}

    async def test_p1_28_stays_documentary_under_enforce(self):
        self.grant(form=P128)
        bobbin = await self.bobbin()
        start, release = self.counts(), self.release(bobbin["id"])
        status_before = self.scalar("SELECT status FROM vinto_txn.quality_release WHERE bobbin_id = %s", (bobbin["id"],))
        with mode("enforce"):
            _, reply = await self.submit(bobbin, self.body(form=P128, values=self.p128(bobbin)))
        self.assertEqual(reply.status, 201)
        self.unchanged_since(start, writes=(1, 6, 1))
        self.assertEqual((self.release(bobbin["id"]), status_before), (release, "pending"))  # una captura autorizada no es una aprobación ni un rechazo de Calidad
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.quality_release WHERE status <> 'pending'"), 0)

    async def test_candidates_follow_exactly_the_live_policy_in_enforce(self):
        for form in (P121, P124, P125, P128):
            self.grant(form=form)
        bobbin = await self.bobbin()
        start = self.counts()
        with mode("enforce"), patch.object(quality, "ENABLED_BOBBIN_CANDIDATE_FORM_CODES", frozenset({P128})):
            for blocked in (P121, P124, P125):  # el servicio los rechaza (422) antes que el motor: la política viva manda
                self.assertEqual((await self.submit(bobbin, self.body(form=blocked, values={})))[1].status, 422, blocked)
            ok = await self.submit(bobbin, self.body(form=P128, values=self.p128(bobbin)))
        self.assertEqual(ok[1].status, 201)
        self.unchanged_since(start, writes=(1, 6, 1))

    async def test_a_candidate_without_its_grant_is_403_when_the_policy_enables_it(self):
        bobbin = await self.bobbin()
        start = self.counts()
        with mode("enforce"):
            self.assertEqual((await self.submit(bobbin, self.body(form=P128, values=self.p128(bobbin))))[1].status, 403)
        self.unchanged_since(start)

    async def test_the_engine_denies_what_the_live_policy_does_not_admit(self):
        self.grant(form=P128)
        with patch.object(quality, "ENABLED_BOBBIN_CANDIDATE_FORM_CODES", frozenset()):
            decision = authorize(self.connection, AuthenticatedUser(self.quality_user, "u", "U", ("CALIDAD",), frozenset(), False), OP, "MP1", P128)
        self.assertEqual((decision.allowed, decision.reason), (False, "POLICY_DOES_NOT_ADMIT_FORM"))


# ---- 6. versión vigente ---------------------------------------------------------------------------------------------------------------------------------

class VersionTests(GateCase):
    def add_version(self, number, area, machine=None):
        c = self.connection
        c.execute("DROP TABLE IF EXISTS _fv")
        c.execute("CREATE TEMP TABLE _fv AS SELECT * FROM vinto_config.form_version WHERE form_id = (SELECT id FROM vinto_config.form WHERE code = %s) ORDER BY version_number DESC LIMIT 1", (P119,))
        c.execute("UPDATE _fv SET id = gen_random_uuid(), version_number = %s, area = %s, status = 'draft', published_at = NULL", (number, area))
        c.execute("INSERT INTO vinto_config.form_version SELECT * FROM _fv")
        if machine:
            c.execute("INSERT INTO vinto_config.form_version_machine (form_version_id, machine_id) SELECT (SELECT id FROM _fv), id FROM vinto_master.machine WHERE code = %s", (machine,))
        c.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = (SELECT id FROM _fv)")

    async def test_a_vigente_version_of_another_area_or_not_offered_denies_and_writes_nothing(self):
        self.grant()
        bobbin = await self.bobbin()
        start = self.counts()
        self.add_version(50, "production")  # vigente de OTRA área
        with mode("enforce"), self.assertLogs("vinto.authz", level="WARNING") as logs:
            self.assertEqual((await self.submit(bobbin))[1].status, 403)
        self.assertTrue(any("reason=EFFECTIVE_VERSION_OTHER_AREA" in m for m in logs.output))
        self.add_version(51, "quality")  # vigente de la misma área que no vincula MP1
        with mode("enforce"), self.assertLogs("vinto.authz", level="WARNING") as logs:
            self.assertEqual((await self.submit(bobbin))[1].status, 403)
        self.assertTrue(any("reason=PAIR_NOT_OFFERED" in m for m in logs.output))
        self.unchanged_since(start)


# ---- 7. idempotencia ----------------------------------------------------------------------------------------------------------------------------------------

class EnforceIdempotencyTests(GateCase):
    async def test_an_authorised_identical_retry_is_already_submitted_and_creates_nothing(self):
        self.grant()
        bobbin = await self.bobbin()
        with mode("enforce"):
            body, first = await self.submit(bobbin)
            start = self.counts()
            retry = (await self.submit(bobbin, body))[1]
        self.assertEqual((first.status, retry.status, retry.json()["created"], retry.json()["already_submitted"]), (201, 200, False, True))
        self.unchanged_since(start)

    async def test_a_retry_after_a_revocation_is_denied_and_changes_nothing(self):
        self.grant()
        bobbin = await self.bobbin()
        with mode("enforce"):
            body, first = await self.submit(bobbin)
            self.assertEqual(first.status, 201)
            start = self.counts()
            self.revoke()
            retry = (await self.submit(bobbin, body))[1]
        self.assertEqual(retry.status, 403)
        self.unchanged_since(start)
        with mode("off"):  # off conserva la semántica histórica
            again = (await self.submit(bobbin, body))[1]
        self.assertEqual((again.status, again.json()["already_submitted"]), (200, True))

    async def test_contradictory_retries_keep_the_idempotency_conflict(self):
        self.grant()
        self.grant(form=P120)
        first_bobbin, other_bobbin = await self.bobbin(), await self.bobbin()
        with mode("enforce"):
            body, first = await self.submit(first_bobbin)
            self.assertEqual(first.status, 201)
            start = self.counts()
            changed = (await self.submit(first_bobbin, {**body, "values": {**P119_VALUES, "peso_seco_medio": "1"}}))[1]
            other_device = (await self.submit(first_bobbin, {**body, "device_key": str(uuid4())}))[1]
            other_form = (await self.submit(first_bobbin, {**body, "form_code": P120, "values": P120_VALUES}))[1]
            other_bobbin_retry = (await self.submit(other_bobbin, body))[1]
        self.assertEqual([r.status for r in (changed, other_device, other_form, other_bobbin_retry)], [409, 409, 409, 409])
        self.unchanged_since(start)

    async def test_a_capture_persisted_by_another_route_gains_no_access_and_is_not_reused(self):
        """El capture_id de la bobina F3 (P1-03) enviado a la ruta de Calidad: se autoriza el par PERSISTIDO, que esta política no admite → 403; con off sigue el 409 histórico."""
        self.grant(form=P119)
        self.grant(form=P103)
        _, assignment = await self.assignment()
        f3_body = self.payload(assignment)
        created = await self.post(f3_body)
        self.assertEqual(created.status, 201)
        bobbin = created.json()["bobbin"]
        start = self.counts()
        reuse = self.body(capture_id=f3_body["capture_id"])
        with mode("enforce"):
            self.assertEqual((await self.submit(bobbin, reuse))[1].status, 403)
        self.unchanged_since(start)
        with mode("off"):
            self.assertEqual((await self.submit(bobbin, reuse))[1].status, 409)

    async def test_historical_captures_are_read_unchanged(self):
        self.grant()
        bobbin = await self.bobbin()
        with mode("enforce"):
            body, first = await self.submit(bobbin)
        capture = first.json()["capture"]
        stored = self.connection.execute("SELECT count(*), max(revision) FROM vinto_txn.capture c JOIN vinto_txn.capture_detail d ON d.capture_id = c.id WHERE c.id = %s", (capture["id"],)).fetchone()
        for observed_mode in ("off", "observe", "enforce"):
            with mode(observed_mode):
                read = await call("GET", f"/api/quality/captures/{capture['id']}", cookie=await self.cookie("CALIDAD"))
            self.assertEqual((read.status, read.json()["values"]), (200, capture["values"]))  # las lecturas no pasan por el motor
        self.assertEqual(self.connection.execute("SELECT count(*), max(revision) FROM vinto_txn.capture c JOIN vinto_txn.capture_detail d ON d.capture_id = c.id WHERE c.id = %s", (capture["id"],)).fetchone(), stored)


# ---- 8. bloqueos, concurrencia, rol vinto_app y auditoría -------------------------------------------------------------------------------------------------------------

class LockingTests(GateCase):
    def principal(self):
        return AuthenticatedUser(self.quality_user, "u", "U", ("CALIDAD",), frozenset(), False, frozenset({"BOBINAS"}))

    def run_submit(self, bobbin, gate, results, body=None):
        body = body or self.body()

        def work():
            conn = connect(self.database)
            try:
                results.append(quality.submit_quality_capture(conn, actor_id=self.quality_user, bobbin_id=bobbin["id"], capture_id=body["capture_id"], form_code=body["form_code"],
                                                              device_key=body["device_key"], values=body["values"], request_id="rid", sectors=frozenset({"BOBINAS"}), gate=gate))
            except BaseException as error:  # noqa: BLE001
                results.append(error)
            finally:
                conn.close()
        return threading.Thread(target=work)

    async def test_a_concurrent_revocation_waits_for_the_capture_transaction_and_the_next_one_is_denied(self):
        self.grant()
        bobbin = await self.bobbin()
        inside, release, results = threading.Event(), threading.Event(), []
        real = cs._resolve_device

        def paused(connection, device_key, machine_id):
            inside.set()  # ya autorizada y con los bloqueos tomados: sigue dentro de la transacción de la captura
            release.wait(20)
            return real(connection, device_key, machine_id)
        with patch.object(cs, "_resolve_device", paused):
            thread = self.run_submit(bobbin, OperationGate(self.principal(), "enforce", "rid", OP), results)
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
        with mode("enforce"):
            self.assertEqual((await self.submit(bobbin))[1].status, 403)

    async def test_observe_holds_no_authorisation_locks(self):
        self.grant()
        bobbin = await self.bobbin()
        inside, release, results = threading.Event(), threading.Event(), []
        real = cs._resolve_device

        def paused(connection, device_key, machine_id):
            inside.set()
            release.wait(20)
            return real(connection, device_key, machine_id)
        with patch.object(cs, "_resolve_device", paused):
            thread = self.run_submit(bobbin, OperationGate(self.principal(), "observe", "rid", OP), results)
            thread.start()
            self.assertTrue(inside.wait(20))
            self.revoke()  # no bloquea
            release.set()
            thread.join(30)
        self.assertTrue(results and getattr(results[0], "created", False), results)

    async def test_no_deadlocks_under_mixed_captures_retries_grants_and_revocations(self):
        self.grant()
        bobbin = await self.bobbin()
        errors, outcomes = [], []
        principal = self.principal()

        def submitter(index):
            conn = connect(self.database)
            try:
                for _ in range(5):
                    body = self.body()
                    for attempt in range(2):  # la segunda es un reintento idéntico
                        try:
                            result = quality.submit_quality_capture(
                                conn, actor_id=self.quality_user, bobbin_id=bobbin["id"], capture_id=body["capture_id"], form_code=body["form_code"], device_key=body["device_key"],
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
                    grant_machine_form(conn, user_id=self.quality_user, machine_code="MP1", form_code=P119, actor_id=self.actor)
                    time.sleep(0.01)
                    revoke_machine_form(conn, user_id=self.quality_user, machine_code="MP1", form_code=P119, actor_id=self.actor)
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
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.quality_release WHERE status <> 'pending'"), 0)

    async def test_the_flow_runs_with_the_privileges_of_vinto_app(self):
        """Rol construido desde backend/roles/*.sql y la 0007 (sin UPDATE en user_sector ni vinto_config): captura, reintento y denegación tras revocar."""
        role = "d2c_app_" + uuid4().hex[:8]
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
        bobbin = await self.bobbin()
        app = connect(self.database)
        self.addCleanup(app.close)
        app.execute(f"SET ROLE {role}")
        body = self.body()

        def submit(request_id):
            return quality.submit_quality_capture(app, actor_id=self.quality_user, bobbin_id=bobbin["id"], capture_id=body["capture_id"], form_code=P119, device_key=body["device_key"],
                                                  values=body["values"], request_id=request_id, sectors=frozenset({"BOBINAS"}), gate=OperationGate(self.principal(), "enforce", request_id, OP))
        self.assertTrue(submit("rid").created)
        self.assertTrue(submit("rid2").already_submitted)
        self.revoke()
        with self.assertRaises(AuthorizationDenied):
            submit("rid3")

    async def test_enforce_leaves_the_same_audit_trail_and_attribution_as_off(self):
        self.grant()
        first, second = await self.bobbin(), await self.bobbin()

        def shape(since):
            return sorted(self.connection.execute(
                """SELECT entity_table, action, actor_id IS NOT DISTINCT FROM %s, request_id IS NOT NULL FROM vinto_audit.audit_event WHERE occurred_at >= %s
                   AND entity_table IN ('capture','capture_detail','quality_release','bobbin') ORDER BY 1, 2""", (self.quality_user, since)).fetchall())
        started = self.scalar("SELECT clock_timestamp()")
        with mode("off"):
            await self.submit(first)
        off_shape = shape(started)
        started = self.scalar("SELECT clock_timestamp()")
        grants_audit = self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table = 'user_machine_form_grant'")
        with mode("enforce"):
            self.assertEqual((await self.submit(second))[1].status, 201)
        self.assertEqual(shape(started), off_shape)
        self.assertTrue(off_shape and all(row[2] for row in off_shape))  # todo evento de la captura atribuido al usuario de Calidad
        self.assertNotIn("quality_release", {row[0] for row in off_shape})  # y ninguno toca la liberación
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table = 'user_machine_form_grant'"), grants_audit)


# ---- 9. coexistencia ---------------------------------------------------------------------------------------------------------------------------------------------

class CoexistenceTests(GateCase):
    async def test_each_operation_obeys_only_its_own_mode(self):
        bobbin = await self.bobbin()
        with patch.object(settings, "authz_central_captures_mode", "off"), patch.object(settings, "authz_bobbin_production_mode", "off"), mode("enforce"):
            self.assertEqual((await self.submit(bobbin))[1].status, 403)  # Calidad por bobina en enforce
            _, assignment = await self.assignment()
            self.assertEqual((await self.post(self.payload(assignment))).status, 201)  # F3 sigue en off: sin concesión pasa
        with patch.object(settings, "authz_bobbin_production_mode", "enforce"), mode("off"):
            _, assignment = await self.assignment()
            self.assertEqual((await self.post(self.payload(assignment))).status, 403)  # F3 en enforce
            self.assertEqual((await self.submit(bobbin))[1].status, 201)  # Calidad por bobina sigue en off
        with patch.object(settings, "authz_central_captures_mode", "enforce"), mode("off"):
            _, assignment = await self.assignment()
            central = await call("POST", "/api/captures", json_body={"capture_id": str(uuid4()), "form_code": "VINTO-P1-06", "assignment_id": assignment["id"], "device_key": str(uuid4()),
                                                                    "values": {"cantidad_fardos": 10, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "125.50"}},
                                 cookie=await self.cookie("OPERACION"))
            self.assertEqual(central.status, 403)  # la central en enforce
            self.assertEqual((await self.submit(bobbin))[1].status, 201)

    async def test_f3_and_central_still_work_in_every_mode_while_quality_enforces(self):
        operator = self.users["OPERACION"][0].user_id
        self.grant(user=operator, form=P103)
        with mode("enforce"):
            for f3_mode in ("off", "observe", "enforce"):
                _, assignment = await self.assignment()
                with patch.object(settings, "authz_bobbin_production_mode", f3_mode):
                    self.assertEqual((await self.post(self.payload(assignment))).status, 201, f3_mode)


if __name__ == "__main__":
    unittest.main()
