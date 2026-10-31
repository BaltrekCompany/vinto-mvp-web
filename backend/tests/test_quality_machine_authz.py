"""Integración del motor de autorización en POST /api/quality/machines/{machine_code}/captures (Calidad por máquina) — MF-13-01D.2C.2: modos off / observe / enforce INDEPENDIENTES.

HTTP contra la aplicación ASGI con una base *_test efímera y, donde hay que controlar bloqueos, nivel de servicio con conexiones propias. Se usan los formularios REALES del bundle (P1-18, P1-22,
P1-26 y P1-27, todos con la política actual de Calidad por máquina). El modo lo fija SOLO el servidor (`settings.authz_quality_machine_captures_mode`). Nada toca una base que no sea de prueba.
"""

import re
import threading
import time
import unittest
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from pydantic import ValidationError

from app import capture_service as cs
from app.auth.machine_form_grants import grant_machine_form, revoke_machine_form
from app.auth.service import AuthenticatedUser
from app.authz import authorize, capture_gate
from app.authz.capture_gate import OperationGate
from app.authz.errors import PUBLIC_FORBIDDEN, PUBLIC_UNAVAILABLE, AuthorizationDenied
from app.authz.policies import Operation, policy_for
from app.config import Settings, settings
from app.ephemeral_db import build_reference_template, connect, drop_database
from app.quality import machine_capture_service as machine_quality

try:
    import test_f3_bobbins_api as f3
    import test_quality_bobbin_authz as qb
    from test_assignments_api import call
except ModuleNotFoundError:
    import tests.test_f3_bobbins_api as f3
    import tests.test_quality_bobbin_authz as qb
    from tests.test_assignments_api import call

BACKEND = Path(__file__).resolve().parent.parent
P101, P103, P118, P119, P122, P126, P127 = "VINTO-P1-01", "VINTO-P1-03", "VINTO-P1-18", "VINTO-P1-19", "VINTO-P1-22", "VINTO-P1-26", "VINTO-P1-27"
OP = Operation.QUALITY_MACHINE_CAPTURE
P118_V2 = {"producto": "papel", "numero_de_cuba": "C-1", "hora_del_ensayo": "07:30", "masa_humeda_g": "12.5", "masa_seca_g": "4.2", "papel_filtro_g": "1.1", "papel_muestra_g": "0.9", "peso_muestra_g": "5.0"}
P122_V2 = {"numero_de_cuba": "C-2", "masa_humeda": "10.5", "grado_de_refinacion_sr": "30.5", "amperaje": "12.5"}
P126_V2 = {"punto_de_muestreo": "Fieltro I", "masa_humeda": "80", "masa_seca": "20"}
VALUES = {P118: P118_V2, P122: P122_V2, P126: P126_V2}
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)  # 12:00 La Paz
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_d2c2_tpl")
    f3.STATE["template"] = STATE["template"]


def tearDownModule():
    drop_database(STATE["template"])


@contextmanager
def mode(value):
    with patch.object(settings, "authz_quality_machine_captures_mode", value):
        yield


class GateCase(qb.GateCase):
    def grant(self, machine="MP1", form=P122, user=None):
        return grant_machine_form(self.connection, user_id=user or self.quality_user, machine_code=machine, form_code=form, actor_id=self.actor)

    def revoke(self, machine="MP1", form=P122, user=None):
        return revoke_machine_form(self.connection, user_id=user or self.quality_user, machine_code=machine, form_code=form, actor_id=self.actor)

    def body(self, form=P122, values=None, **changes):
        body = {"capture_id": str(uuid4()), "form_code": form, "device_key": str(uuid4()), "values": dict(values or VALUES.get(form, P122_V2))}
        body.update(changes)
        return body

    async def machine_submit(self, body=None, *, machine="MP1", profile="CALIDAD", cookie=None):
        body = body or self.body()
        return body, await call("POST", f"/api/quality/machines/{machine}/captures", json_body=body, cookie=cookie or await self.cookie(profile))

    def assert_only_the_capture(self, start):
        """Una captura de Calidad por máquina escribe capturas y detalles (y, si el dispositivo es nuevo, un dispositivo): nada más se mueve."""
        delta = [a - b for a, b in zip(self.counts(), start)]
        self.assertEqual((delta[0], delta[1] > 0, delta[2] in (0, 1)), (1, True, True), delta)
        self.assertEqual(delta[3:], [0] * 5, delta)  # quality_release, bobinas, OT, concesiones y asignaciones intactas

    def stored(self, capture_id):
        return dict(self.connection.execute(
            """SELECT f.key, coalesce(d.value_decimal::text, d.value_time::text, d.value_text) FROM vinto_txn.capture_detail d
               JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s""", (capture_id,)).fetchall())


# ---- 1. configuración ---------------------------------------------------------------------------------------------------------------------------------

class ConfigurationTests(unittest.TestCase):
    def test_default_off_normalised_and_unknown_values_do_not_start(self):
        self.assertEqual(Settings(_env_file=None).authz_quality_machine_captures_mode, "off")
        self.assertEqual(Settings(_env_file=None, authz_quality_machine_captures_mode=" Enforce ").authz_quality_machine_captures_mode, "enforce")
        for bad in ("on", "true", "", "enforced"):
            with self.assertRaises(ValidationError):
                Settings(_env_file=None, authz_quality_machine_captures_mode=bad)

    def test_the_four_modes_are_independent(self):
        names = ("authz_central_captures_mode", "authz_bobbin_production_mode", "authz_quality_bobbin_captures_mode", "authz_quality_machine_captures_mode")
        for chosen in names:
            built = Settings(_env_file=None, **{chosen: "enforce"})
            self.assertEqual({n: getattr(built, n) for n in names}, {n: ("enforce" if n == chosen else "off") for n in names}, chosen)

    def test_each_router_reads_only_its_own_mode_and_the_client_cannot_choose(self):
        router = (BACKEND / "app/quality/machine_router.py").read_text(encoding="utf-8")
        self.assertIn("settings.authz_quality_machine_captures_mode", router)
        self.assertIn("Operation.QUALITY_MACHINE_CAPTURE", router)
        for other in ("authz_central_captures_mode", "authz_bobbin_production_mode", "authz_quality_bobbin_captures_mode"):
            self.assertNotIn(other, router)
        for path in ("app/captures.py", "app/bobbins/router.py", "app/quality/router.py"):
            self.assertNotIn("authz_quality_machine_captures_mode", (BACKEND / path).read_text(encoding="utf-8"), path)
        self.assertNotRegex(router, r"Header\(|body\.mode")
        from app.quality.machine_capture_schemas import MachineCaptureIn
        self.assertEqual(MachineCaptureIn.model_config.get("extra"), "forbid")
        self.assertEqual(set(MachineCaptureIn.model_fields), {"capture_id", "form_code", "device_key", "values"})  # sin máquina propia: la máquina es la de la ruta


# ---- 2. política viva -----------------------------------------------------------------------------------------------------------------------------------

class LivePolicyTests(unittest.TestCase):
    def test_the_engine_policy_is_exactly_the_live_service_policy(self):
        self.assertEqual(policy_for(OP).admitted(), frozenset(machine_quality.MACHINE_QUALITY_FORM_CODES))
        self.assertEqual((policy_for(OP).permission, policy_for(OP).area), ("quality.capture", "quality"))

    def test_finding_the_four_forms_are_enabled_in_the_code_today(self):
        """HALLAZGO: el docstring del módulo habla de política «VACÍA en la configuración real», pero el código habilita hoy P1-18/22/26/27 (CLOUD-DEP G.12-C4, QA interno, sin homologar)."""
        self.assertEqual(machine_quality.MACHINE_QUALITY_FORM_CODES, frozenset({P118, P122, P126, P127}))
        self.assertEqual(policy_for(OP).admitted(), frozenset({P118, P122, P126, P127}))

    def test_the_engine_follows_the_constant_without_enabling_or_disabling_anything(self):
        with patch.object(machine_quality, "MACHINE_QUALITY_FORM_CODES", frozenset()):
            self.assertEqual(policy_for(OP).admitted(), frozenset())
        with patch.object(machine_quality, "MACHINE_QUALITY_FORM_CODES", frozenset({P126})):
            self.assertEqual(policy_for(OP).admitted(), frozenset({P126}))

    def test_forms_of_other_routes_are_not_admitted(self):
        admitted = policy_for(OP).admitted()
        for other in (P119, "VINTO-P1-20", "VINTO-P1-21", "VINTO-P1-24", "VINTO-P1-25", "VINTO-P1-28", P101, P103, "VINTO-P1-06"):
            self.assertNotIn(other, admitted)
        for bobbin_form in policy_for(Operation.QUALITY_BOBBIN_CAPTURE).admitted():
            self.assertNotIn(bobbin_form, admitted)  # conjuntos disjuntos con Calidad por bobina


# ---- 3. off / observe -----------------------------------------------------------------------------------------------------------------------------------

class OffAndObserveTests(GateCase):
    async def test_off_keeps_the_original_operation_and_never_calls_the_engine(self):
        start = self.counts()
        with mode("off"), patch.object(capture_gate, "authorize", side_effect=AssertionError("motor en off")), patch.object(capture_gate, "require", side_effect=AssertionError("motor en off")):
            _, reply = await self.machine_submit()  # sin ninguna concesión
        self.assertEqual((reply.status, reply.json()["created"]), (201, True))
        self.assert_only_the_capture(start)

    async def test_observe_never_changes_data_or_the_response_and_logs_the_operation(self):
        start = self.counts()
        with mode("observe"), self.assertLogs("vinto.authz", level="INFO") as logs:
            _, reply = await self.machine_submit()  # sin concesión: en enforce sería 403
        self.assertEqual((reply.status, reply.json()["created"]), (201, True))
        self.assert_only_the_capture(start)
        self.assertTrue(any(re.search(r"mode=observe operation=quality_machine_capture outcome=would_forbidden reason=GRANT_MISSING request_id=[0-9a-f-]{36}", m) for m in logs.output))

    async def test_observe_with_a_grant_responds_exactly_as_off(self):
        self.grant()
        with mode("observe"), self.assertLogs("vinto.authz", level="INFO") as logs:
            _, observed = await self.machine_submit()
        with mode("off"):
            _, plain = await self.machine_submit()
        self.assertEqual((observed.status, plain.status, set(observed.json())), (201, 201, set(plain.json())))
        self.assertTrue(any("operation=quality_machine_capture outcome=allowed reason=ALLOWED" in m for m in logs.output))

    async def test_observe_ignores_any_engine_failure_including_sql(self):
        def broken(connection, *args, **kwargs):
            connection.execute("SELECT * FROM vinto_master.tabla_que_no_existe")
        with mode("observe"), patch.object(capture_gate, "authorize", side_effect=broken), self.assertLogs("vinto.authz", level="ERROR") as logs:
            _, reply = await self.machine_submit()
        self.assertEqual(reply.status, 201)
        self.assertTrue(any("operation=quality_machine_capture outcome=observe_error" in m for m in logs.output))

    async def test_logs_never_contain_cookies_users_or_values(self):
        cookie = await self.cookie("CALIDAD")
        with mode("observe"), self.assertLogs("vinto.authz", level="INFO") as logs:
            await self.machine_submit(cookie=cookie)
        text = "\n".join(logs.output)
        for secret in (cookie, "30.5", "C-2", str(self.quality_user), "pw-"):
            self.assertNotIn(secret, text)


# ---- 4. enforce: decisiones ---------------------------------------------------------------------------------------------------------------------------

class EnforceDecisionTests(GateCase):
    async def test_a_granted_form_is_allowed_for_every_enabled_form_and_quality_release_is_untouched(self):
        for form in (P118, P122, P126):
            self.grant(form=form)
            start = self.counts()
            with mode("enforce"):
                _, reply = await self.machine_submit(self.body(form))
            self.assertEqual((reply.status, reply.json()["created"], reply.json()["capture"]["machine"]["code"]), (201, True, "MP1"), form)
            self.assert_only_the_capture(start)
            self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.quality_release WHERE status <> 'pending'"), 0)

    async def test_a_form_that_was_not_granted_is_403_with_the_fixed_body_and_nothing_is_written(self):
        self.grant(form=P122)
        start = self.counts()
        with mode("enforce"), self.assertLogs("vinto.authz", level="WARNING") as logs:
            _, reply = await self.machine_submit(self.body(P126))  # concedido P1-22, no P1-26
        self.assertEqual((reply.status, reply.json()), (PUBLIC_FORBIDDEN[0], PUBLIC_FORBIDDEN[1]))
        self.assertEqual(self.counts(), start)  # ni captura, ni detalles, ni dispositivo
        self.assertTrue(any("mode=enforce operation=quality_machine_capture outcome=forbidden reason=GRANT_MISSING" in m for m in logs.output))
        for leak in ("GRANT_MISSING", "MP1", "P1-26", "vinto_", "grant"):
            self.assertNotIn(leak, reply.body.decode())

    async def test_mp1_and_mp3_are_independent(self):
        self.grant("MP1")
        with mode("enforce"):
            self.assertEqual((await self.machine_submit(machine="MP3"))[1].status, 403)
            self.assertEqual((await self.machine_submit(machine="MP1"))[1].status, 201)
            self.grant("MP3")
            self.assertEqual((await self.machine_submit(machine="MP3"))[1].status, 201)

    async def test_the_machine_is_the_route_one_resolved_against_postgres_before_authorising(self):
        self.grant("MP1")
        start = self.counts()
        with mode("enforce"):
            self.assertEqual((await self.machine_submit(machine="NO-SUCH-MACHINE"))[1].status, 404)  # el recurso inexistente se resuelve antes del motor
            reply = await call("POST", "/api/quality/machines/MP1/captures", json_body={**self.body(), "machine_code": "MP3"}, cookie=await self.cookie("CALIDAD"))
            self.assertEqual(reply.status, 422)  # el cuerpo no puede traer otra máquina
            self.assertEqual((await self.machine_submit(machine="MP3"))[1].status, 403)  # la concesión es de MP1
        self.assertEqual(self.counts(), start)

    async def test_a_production_grant_is_not_a_quality_permission(self):
        self.grant("MP1", P101)
        self.grant("MP1", P103)
        start = self.counts()
        with mode("enforce"):
            self.assertEqual((await self.machine_submit())[1].status, 403)
        self.assertEqual(self.counts(), start)

    async def test_a_profile_without_quality_capture_is_rejected_even_with_a_grant(self):
        operator = self.users["OPERACION"][0].user_id
        self.grant(user=operator)
        start = self.counts()
        with mode("enforce"):
            self.assertEqual((await self.machine_submit(profile="OPERACION"))[1].status, 403)
        self.assertEqual(self.counts(), start)

    async def test_an_inactive_user_or_an_ungranted_sector_cannot_operate(self):
        user, cookie = await self.fresh_user()
        self.grant(user=user)
        start = self.counts()
        self.connection.execute('UPDATE vinto_master."user" SET active = false WHERE id = %s', (user,))
        with mode("enforce"):
            self.assertIn((await self.machine_submit(cookie=cookie))[1].status, (401, 403))
        self.assertEqual(self.counts(), start)
        no_sector, cookie2 = await self.fresh_user(sectors=())
        self.grant(user=no_sector)
        start = self.counts()
        with mode("off"):
            existing = (await self.machine_submit(cookie=cookie2))[1]
        with mode("enforce"):
            enforced = (await self.machine_submit(cookie=cookie2))[1]
        self.assertEqual((existing.status, existing.json()["code"]), (422, "MACHINE_OUTSIDE_SCOPE"))  # el alcance de sectores existente responde antes que el motor
        self.assertEqual((enforced.status, enforced.json()), (existing.status, existing.json()))
        self.assertEqual(self.counts(), start)

    async def test_an_inactive_form_is_denied_by_the_engine_and_an_inactive_machine_keeps_its_existing_error(self):
        self.grant()
        start = self.counts()
        self.connection.execute(f"UPDATE vinto_config.form SET active = false WHERE code = '{P122}'")
        try:
            with mode("enforce"):
                self.assertEqual((await self.machine_submit())[1].status, 403)
        finally:
            self.connection.execute(f"UPDATE vinto_config.form SET active = true WHERE code = '{P122}'")
        self.connection.execute("UPDATE vinto_master.machine SET active = false WHERE code = 'MP1'")
        try:
            with mode("off"):
                existing = (await self.machine_submit())[1].status
            with mode("enforce"):
                self.assertEqual((await self.machine_submit())[1].status, existing)  # la precedencia funcional existente se conserva (resolución de la máquina primero)
        finally:
            self.connection.execute("UPDATE vinto_master.machine SET active = true WHERE code = 'MP1'")
        self.assertEqual(self.counts(), start)

    async def test_forms_of_other_routes_keep_the_functional_422_before_any_authorisation(self):
        self.grant("MP1", P119)
        start = self.counts()
        with mode("enforce"), patch.object(capture_gate, "require", side_effect=AssertionError("la política funcional va primero")):
            for other in (P119, "VINTO-P1-20", "VINTO-P1-21", P101, P103, "NO-SUCH"):
                self.assertEqual((await self.machine_submit(self.body(other, values=P122_V2)))[1].status, 422, other)
        self.assertEqual(self.counts(), start)

    async def test_a_revocation_confirmed_before_the_capture_blocks_the_write(self):
        self.grant()
        self.revoke()
        start = self.counts()
        with mode("enforce"):
            self.assertEqual((await self.machine_submit())[1].status, 403)
        self.assertEqual(self.counts(), start)

    async def test_an_engine_failure_is_503_and_leaves_no_partial_records(self):
        self.grant()
        start = self.counts()
        self.connection.execute("ALTER TABLE vinto_master.user_machine_form_grant RENAME TO grants_gone")
        try:
            with mode("enforce"), self.assertLogs("vinto.authz", level="ERROR") as logs:
                _, reply = await self.machine_submit()
        finally:
            self.connection.execute("ALTER TABLE vinto_master.grants_gone RENAME TO user_machine_form_grant")
        self.assertEqual((reply.status, reply.json()), (PUBLIC_UNAVAILABLE[0], PUBLIC_UNAVAILABLE[1]))
        self.assertEqual(self.counts(), start)
        self.assertTrue(any("operation=quality_machine_capture outcome=unavailable reason=42P01" in m for m in logs.output))
        self.assertNotIn("42P01", reply.body.decode())

    async def test_a_machine_or_sector_that_changes_under_the_locks_fails_closed(self):
        self.grant()
        real = machine_quality._machine
        for shift_field in ("machine", "sector"):
            calls = []

            def shifting(connection, machine_code, sectors, _field=shift_field):
                machine_id, sector_id = real(connection, machine_code, sectors)
                calls.append(1)
                if len(calls) < 2:
                    return machine_id, sector_id
                return (uuid4(), sector_id) if _field == "machine" else (machine_id, uuid4())  # la relectura tras los bloqueos devuelve otro contexto
            start = self.counts()
            with mode("enforce"), patch.object(machine_quality, "_machine", shifting):
                _, reply = await self.machine_submit()
            self.assertEqual((reply.status, self.counts()), (503, start), shift_field)

    async def test_existing_errors_and_their_precedence_are_unchanged_when_authorised(self):
        self.grant()
        start = self.counts()
        with mode("enforce"):
            self.assertEqual((await self.machine_submit(self.body(values={**P122_V2, "amperaje": "x"})))[1].status, 422)  # valores inválidos: el 422 de siempre
            self.assertEqual((await self.machine_submit(self.body(values={**P122_V2, "porcentaje": "50"})))[1].status, 422)  # un calculado/ajeno enviado por el cliente
        self.assertEqual(self.counts(), start)


# ---- 5. versión vigente -------------------------------------------------------------------------------------------------------------------------------------

class VersionTests(GateCase):
    def add_version(self, number, area, machine=None):
        c = self.connection
        c.execute("DROP TABLE IF EXISTS _fv")
        c.execute("CREATE TEMP TABLE _fv AS SELECT * FROM vinto_config.form_version WHERE form_id = (SELECT id FROM vinto_config.form WHERE code = %s) ORDER BY version_number DESC LIMIT 1", (P122,))
        c.execute("UPDATE _fv SET id = gen_random_uuid(), version_number = %s, area = %s, status = 'draft', published_at = NULL", (number, area))
        c.execute("INSERT INTO vinto_config.form_version SELECT * FROM _fv")
        if machine:
            c.execute("INSERT INTO vinto_config.form_version_machine (form_version_id, machine_id) SELECT (SELECT id FROM _fv), id FROM vinto_master.machine WHERE code = %s", (machine,))
        c.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = (SELECT id FROM _fv)")

    async def test_a_vigente_version_of_another_area_or_not_offered_denies_and_writes_nothing(self):
        self.grant()
        start = self.counts()
        self.add_version(50, "production")  # vigente de OTRA área
        with mode("enforce"), self.assertLogs("vinto.authz", level="WARNING") as logs:
            self.assertEqual((await self.machine_submit())[1].status, 403)
        self.assertTrue(any("reason=EFFECTIVE_VERSION_OTHER_AREA" in m for m in logs.output))
        self.add_version(51, "quality")  # vigente de la misma área que no vincula MP1
        with mode("enforce"), self.assertLogs("vinto.authz", level="WARNING") as logs:
            self.assertEqual((await self.machine_submit())[1].status, 403)
        self.assertTrue(any("reason=PAIR_NOT_OFFERED" in m for m in logs.output))
        self.assertEqual(self.counts(), start)


# ---- 6. idempotencia ----------------------------------------------------------------------------------------------------------------------------------------

class EnforceIdempotencyTests(GateCase):
    async def test_an_authorised_identical_retry_is_already_submitted_and_creates_nothing(self):
        self.grant()
        with mode("enforce"):
            body, first = await self.machine_submit()
            start = self.counts()
            retry = (await self.machine_submit(body))[1]
        self.assertEqual((first.status, retry.status, retry.json()["created"], retry.json()["already_submitted"]), (201, 200, False, True))
        self.assertEqual(self.counts(), start)

    async def test_a_retry_after_a_revocation_is_denied_and_changes_nothing(self):
        self.grant()
        with mode("enforce"):
            body, first = await self.machine_submit()
            self.assertEqual(first.status, 201)
            start = self.counts()
            self.revoke()
            retry = (await self.machine_submit(body))[1]
        self.assertEqual(retry.status, 403)
        self.assertEqual(self.counts(), start)
        with mode("off"):  # off conserva la semántica histórica
            again = (await self.machine_submit(body))[1]
        self.assertEqual((again.status, again.json()["already_submitted"]), (200, True))

    async def test_contradictory_retries_keep_the_idempotency_conflict_against_the_persisted_values(self):
        self.grant("MP1", P122)
        self.grant("MP3", P122)
        self.grant("MP1", P126)
        with mode("enforce"):
            body, first = await self.machine_submit()
            self.assertEqual(first.status, 201)
            start = self.counts()
            changed = (await self.machine_submit({**body, "values": {**P122_V2, "amperaje": "99"}}))[1]
            other_device = (await self.machine_submit({**body, "device_key": str(uuid4())}))[1]
            other_form = (await self.machine_submit({**body, "form_code": P126, "values": P126_V2}))[1]
            other_machine = (await self.machine_submit(body, machine="MP3"))[1]  # misma captura reenviada por la ruta de otra máquina
        self.assertEqual([r.status for r in (changed, other_device, other_form, other_machine)], [409, 409, 409, 409])
        self.assertEqual(self.counts(), start)

    async def test_a_capture_persisted_by_another_route_gains_no_access_and_is_not_reused(self):
        """El capture_id de una bobina F3 (P1-03) reenviado a esta ruta: se autoriza el par PERSISTIDO, que esta política no admite → 403; con off sigue el 409 histórico."""
        self.grant("MP1", P122)
        self.grant("MP1", P103)
        _, assignment = await self.assignment()
        f3_body = self.payload(assignment)
        created = await self.post(f3_body)
        self.assertEqual(created.status, 201)
        start = self.counts()
        reuse = self.body(capture_id=f3_body["capture_id"])
        with mode("enforce"):
            self.assertEqual((await self.machine_submit(reuse))[1].status, 403)
        self.assertEqual(self.counts(), start)
        with mode("off"):
            self.assertEqual((await self.machine_submit(reuse))[1].status, 409)

    async def test_historical_captures_are_read_unchanged_in_every_mode(self):
        self.grant()
        with mode("enforce"):
            _, first = await self.machine_submit()
        capture = first.json()["capture"]
        stored = self.stored(capture["id"])
        for observed_mode in ("off", "observe", "enforce"):
            with mode(observed_mode):
                read = await call("GET", f"/api/quality/machine-captures/{capture['id']}", cookie=await self.cookie("CALIDAD"))
            self.assertEqual((read.status, read.json()["values"]), (200, capture["values"]))  # las lecturas no pasan por el motor
        self.assertEqual(self.stored(capture["id"]), stored)


# ---- 7. reglas de Calidad preservadas ----------------------------------------------------------------------------------------------------------------------------------

class QualityRulesTests(GateCase):
    async def test_calculations_shift_date_and_responsible_are_identical_with_off_and_enforce(self):
        self.grant(form=P126)  # P1-26 es el formulario con un campo calculado por el backend (porcentaje_cantidad_de_seco)
        results = {}
        for label, current in (("off", "off"), ("enforce", "enforce")):
            with mode(current), patch.object(cs, "_now", return_value=DAY):
                _, reply = await self.machine_submit(self.body(P126, P126_V2))
            self.assertEqual(reply.status, 201, label)
            capture = reply.json()["capture"]
            row = self.connection.execute("SELECT shift_schedule_id, operating_date, created_by, assignment_id, bobbin_id, captured_at FROM vinto_txn.capture WHERE id = %s", (capture["id"],)).fetchone()
            results[label] = (self.stored(capture["id"]), row)
        off_values, off_row = results["off"]
        enforce_values, enforce_row = results["enforce"]
        self.assertEqual(off_values, enforce_values)  # incluye el porcentaje calculado por el backend (MF-08)
        self.assertEqual(off_values["porcentaje_cantidad_de_seco"], "25.00")  # 20 / 80 × 100, dos decimales: el cálculo existente, intacto
        self.assertEqual(off_row, enforce_row)  # turno, fecha operativa, responsable y hora de registro (reloj fijado) idénticos; sin asignación ni bobina
        self.assertEqual((off_row[2], off_row[3], off_row[4]), (self.quality_user, None, None))

    async def test_p1_27_is_policy_enabled_but_a_grant_never_turns_a_capture_into_an_approval(self):
        self.assertIn(P127, policy_for(OP).admitted())
        self.grant(form=P122)
        start, releases = self.counts(), self.connection.execute("SELECT bobbin_id, status, updated_at FROM vinto_txn.quality_release ORDER BY bobbin_id").fetchall()
        with mode("enforce"):
            self.assertEqual((await self.machine_submit())[1].status, 201)
        self.assertEqual(self.connection.execute("SELECT bobbin_id, status, updated_at FROM vinto_txn.quality_release ORDER BY bobbin_id").fetchall(), releases)
        self.assert_only_the_capture(start)


# ---- 8. bloqueos, concurrencia, rol vinto_app y auditoría -----------------------------------------------------------------------------------------------------------

class LockingTests(GateCase):
    def principal(self):
        return AuthenticatedUser(self.quality_user, "u", "U", ("CALIDAD",), frozenset(), False, frozenset({"BOBINAS"}))

    def run_submit(self, gate, results, body=None):
        body = body or self.body()

        def work():
            conn = connect(self.database)
            try:
                results.append(machine_quality.submit_machine_capture(
                    conn, actor_id=self.quality_user, machine_code="MP1", capture_id=body["capture_id"], form_code=body["form_code"], device_key=body["device_key"],
                    values=body["values"], request_id="rid", sectors=frozenset({"BOBINAS"}), gate=gate))
            except BaseException as error:  # noqa: BLE001
                results.append(error)
            finally:
                conn.close()
        return threading.Thread(target=work)

    async def test_a_concurrent_revocation_waits_for_the_capture_transaction_and_the_next_one_is_denied(self):
        self.grant()
        inside, release, results = threading.Event(), threading.Event(), []
        real = cs._resolve_device

        def paused(connection, device_key, machine_id):
            inside.set()  # ya autorizada y con los bloqueos tomados: sigue dentro de la transacción de la captura
            release.wait(20)
            return real(connection, device_key, machine_id)
        with patch.object(cs, "_resolve_device", paused):
            thread = self.run_submit(OperationGate(self.principal(), "enforce", "rid", OP), results)
            thread.start()
            self.assertTrue(inside.wait(20))
            revoker = connect(self.database)
            self.addCleanup(revoker.close)
            with self.assertRaises(psycopg.errors.LockNotAvailable), revoker.transaction():
                revoker.execute("SET LOCAL lock_timeout = 400")
                revoker.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(self.actor),))
                revoker.execute("UPDATE vinto_master.user_machine_form_grant SET revoked_at = clock_timestamp(), revoked_by = %s WHERE revoked_at IS NULL", (self.actor,))
            # el cambio de sector de la máquina también espera: la autorización retiene FOR SHARE sobre la fila de la máquina y de su sector
            with self.assertRaises(psycopg.errors.LockNotAvailable), revoker.transaction():
                revoker.execute("SET LOCAL lock_timeout = 400")
                revoker.execute("UPDATE vinto_master.machine SET sector_id = sector_id WHERE code = 'MP1'")
            release.set()
            thread.join(30)
        self.assertTrue(results and getattr(results[0], "created", False), results)
        self.revoke()
        with mode("enforce"):
            self.assertEqual((await self.machine_submit())[1].status, 403)

    async def test_observe_holds_no_authorisation_locks(self):
        self.grant()
        inside, release, results = threading.Event(), threading.Event(), []
        real = cs._resolve_device

        def paused(connection, device_key, machine_id):
            inside.set()
            release.wait(20)
            return real(connection, device_key, machine_id)
        with patch.object(cs, "_resolve_device", paused):
            thread = self.run_submit(OperationGate(self.principal(), "observe", "rid", OP), results)
            thread.start()
            self.assertTrue(inside.wait(20))
            self.revoke()  # no bloquea
            release.set()
            thread.join(30)
        self.assertTrue(results and getattr(results[0], "created", False), results)

    async def test_no_deadlocks_under_mixed_captures_retries_grants_and_revocations(self):
        self.grant()
        errors, outcomes = [], []
        principal = self.principal()

        def submitter(index):
            conn = connect(self.database)
            try:
                for _ in range(5):
                    body = self.body()
                    for attempt in range(2):  # la segunda es un reintento idéntico
                        try:
                            result = machine_quality.submit_machine_capture(
                                conn, actor_id=self.quality_user, machine_code="MP1", capture_id=body["capture_id"], form_code=body["form_code"], device_key=body["device_key"],
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
                    grant_machine_form(conn, user_id=self.quality_user, machine_code="MP1", form_code=P122, actor_id=self.actor)
                    time.sleep(0.01)
                    revoke_machine_form(conn, user_id=self.quality_user, machine_code="MP1", form_code=P122, actor_id=self.actor)
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
        role = "d2c2_app_" + uuid4().hex[:8]
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
        app = connect(self.database)
        self.addCleanup(app.close)
        app.execute(f"SET ROLE {role}")
        body = self.body()

        def submit(request_id):
            return machine_quality.submit_machine_capture(
                app, actor_id=self.quality_user, machine_code="MP1", capture_id=body["capture_id"], form_code=P122, device_key=body["device_key"], values=body["values"],
                request_id=request_id, sectors=frozenset({"BOBINAS"}), gate=OperationGate(self.principal(), "enforce", request_id, OP))
        self.assertTrue(submit("rid").created)
        self.assertTrue(submit("rid2").already_submitted)
        self.revoke()
        with self.assertRaises(AuthorizationDenied):
            submit("rid3")

    async def test_enforce_leaves_the_same_audit_trail_and_attribution_as_off(self):
        self.grant()

        def shape(since):
            return sorted(self.connection.execute(
                """SELECT entity_table, action, actor_id IS NOT DISTINCT FROM %s, request_id IS NOT NULL FROM vinto_audit.audit_event WHERE occurred_at >= %s
                   AND entity_table IN ('capture','capture_detail','quality_release','bobbin') ORDER BY 1, 2""", (self.quality_user, since)).fetchall())
        started = self.scalar("SELECT clock_timestamp()")
        with mode("off"):
            await self.machine_submit()
        off_shape = shape(started)
        started = self.scalar("SELECT clock_timestamp()")
        grants_audit = self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table = 'user_machine_form_grant'")
        with mode("enforce"):
            self.assertEqual((await self.machine_submit())[1].status, 201)
        self.assertEqual(shape(started), off_shape)
        self.assertTrue(off_shape and all(row[2] for row in off_shape))
        self.assertNotIn("quality_release", {row[0] for row in off_shape})
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table = 'user_machine_form_grant'"), grants_audit)


# ---- 9. coexistencia de las cuatro operaciones --------------------------------------------------------------------------------------------------------------------------

class CoexistenceTests(GateCase):
    async def central(self, assignment):
        return await call("POST", "/api/captures", json_body={"capture_id": str(uuid4()), "form_code": "VINTO-P1-06", "assignment_id": assignment["id"], "device_key": str(uuid4()),
                                                               "values": {"cantidad_fardos": 10, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "125.50"}},
                          cookie=await self.cookie("OPERACION"))

    async def by_bobbin(self, bobbin):
        return await call("POST", f"/api/quality/bobbins/{bobbin['id']}/captures", json_body=qb.GateCase.body(self), cookie=await self.cookie("CALIDAD"))

    async def test_machine_enforce_leaves_the_other_three_operations_in_their_own_mode(self):
        bobbin = await self.bobbin()
        _, assignment = await self.assignment()
        with mode("enforce"):
            self.assertEqual((await self.machine_submit())[1].status, 403)
            self.assertEqual((await self.central(assignment)).status, 201)  # central en off
            self.assertEqual((await self.by_bobbin(bobbin)).status, 201)  # Calidad por bobina en off
            _, assignment2 = await self.assignment()
            self.assertEqual((await self.post(self.payload(assignment2))).status, 201)  # F3 en off

    async def test_each_other_operation_enforcing_does_not_touch_the_machine_route(self):
        bobbin = await self.bobbin()
        _, assignment = await self.assignment()
        with mode("off"):
            with patch.object(settings, "authz_central_captures_mode", "enforce"):
                self.assertEqual((await self.central(assignment)).status, 403)
                self.assertEqual((await self.machine_submit())[1].status, 201)
            with patch.object(settings, "authz_quality_bobbin_captures_mode", "enforce"):
                self.assertEqual((await self.by_bobbin(bobbin)).status, 403)
                self.assertEqual((await self.machine_submit())[1].status, 201)
            with patch.object(settings, "authz_bobbin_production_mode", "enforce"):
                _, other = await self.assignment()
                self.assertEqual((await self.post(self.payload(other))).status, 403)
                self.assertEqual((await self.machine_submit())[1].status, 201)

    async def test_the_three_previous_operations_still_work_in_every_one_of_their_modes(self):
        self.grant("MP1", P119)
        bobbin = await self.bobbin()
        with mode("enforce"):
            for previous_mode in ("off", "observe", "enforce"):
                with patch.object(settings, "authz_quality_bobbin_captures_mode", previous_mode):
                    self.assertEqual((await self.by_bobbin(bobbin)).status, 201, previous_mode)  # con su concesión de P1-19, en cualquiera de sus modos


if __name__ == "__main__":
    unittest.main()
