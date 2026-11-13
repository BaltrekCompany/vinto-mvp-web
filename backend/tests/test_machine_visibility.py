"""MF13-03.B PR5: visibilidad por máquina (lecturas) y autorización de capturas con varias líneas activas de una misma OT.

Nivel de dominio sobre bases *_test efímeras (arnés de PR3/PR4). OT: L1/MP1, L2/MP1, L3/MP3 activadas con la activación masiva de PR4. Nada toca vinto,
vinto_piloto ni servidores. Las concesiones, sectores y modos de autorización se manejan solo en la base/ajustes de prueba.
"""

import logging
import secrets
import threading
import unittest
from datetime import date
from unittest.mock import patch
from uuid import uuid4

import psycopg

from app import capture_service as _capture_service
from app.assignments import service as _assignments
from app.assignments.errors import MultipleActiveAssignmentsError
from app.auth import permissions
from app.auth.grants import grant_sector, revoke_sector
from app.auth.machine_form_grants import grant_machine_form, revoke_machine_form
from app.auth.service import AuthenticatedUser, create_user
from app.authz import visibility
from app.authz.capture_gate import ENFORCE, OBSERVE, OFF, OperationGate
from app.authz.engine import require
from app.authz.errors import AuthorizationDenied
from app.authz.policies import Operation
from app.bobbins import service as _bobbins
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, drop_database
from app.quality import machine_capture_service
from app.work_orders import service as _work_orders
from app.work_orders.errors import MachineOutsideScopeError, WorkOrderNotFoundError

try:
    import test_assignment_same_work_order as base
except ModuleNotFoundError:
    from tests import test_assignment_same_work_order as base

service, line, internal = base.service, base.line, base.internal
bobbins, work_orders = internal(_bobbins), internal(_work_orders)
P103, P106 = "VINTO-P1-03", "VINTO-P1-06"
VALUES = {"hora_inicio": "07:15", "hora_fin": "08:40", "diametro": "1200.5", "peso_kg": "845.25", "numero_de_cortes": "3", "metraje": 1000, "codigo_de_tubete": 37, "observaciones": "ok"}
ARTICLES = {a["code"]: a["version"] for a in base.BUNDLE.articles}
WITH_GRAMMAGE = [c for c in base.MP1_CODES if ARTICLES[c]["grammage_g_m2"] is not None]
WITH_GRAMMAGE_MP3 = [c for c in base.MP3_ONLY if ARTICLES[c]["grammage_g_m2"] is not None]


def setUpModule():
    base.STATE["template"] = build_reference_template("vinto_mv_tpl")


def tearDownModule():
    if base.STATE.get("template"):
        drop_database(base.STATE["template"])


def principal(created, profile, sectors=("BOBINAS",)) -> AuthenticatedUser:
    return AuthenticatedUser(created.user_id, created.username, "Fixture", (profile,), permissions.permissions_for_profiles([profile]), False, frozenset(sectors))


class VisibilityCase(base.SameOrderCase):
    def setUp(self):
        super().setUp()
        self.gate(True)
        self.actor = self.supervisor
        # L1 (MP1), L2 (MP1) y L3 (MP3) de la misma OT, activadas con la activación masiva de PR4 (el turno vigente es el de la hora parcheada).
        self.mixed = self.order3 = self.order_with_grammage()
        plan = service.preview_activate_all(self.connection, work_order_id=self.mixed.id).plan
        service.activate_all(self.connection, actor_id=self.supervisor, work_order_id=self.mixed.id, plan_hash=plan.plan_hash)

    def order_with_grammage(self):
        return self.order([line(WITH_GRAMMAGE[0], "MP1", "PV-1"), line(WITH_GRAMMAGE[1], "MP1", "PV-2"), line(WITH_GRAMMAGE_MP3[0], "MP3", "PV-3")])

    def user(self, profile="OPERACION", sectors=("BOBINAS",)):
        created = create_user(self.connection, username=f"mv.{uuid4().hex[:10]}", display_name=f"{profile.title()} Fixture", profile_code=profile,
                              password="pw-" + secrets.token_urlsafe(18), sectors=sectors)
        return principal(created, profile, sectors)

    def grant(self, user, machine, form=P103):
        return grant_machine_form(self.connection, user_id=user.user_id, machine_code=machine, form_code=form, actor_id=self.actor)

    def revoke(self, user, machine, form=P103):
        return revoke_machine_form(self.connection, user_id=user.user_id, machine_code=machine, form_code=form, actor_id=self.actor)

    def operator(self, *machines, form=P103):
        user = self.user()
        for machine in machines:
            self.grant(user, machine, form)
        return user

    def lines_of(self, user):
        scope = visibility.operational_scope(self.connection, user)
        return [l.assignment.line.line_code for l in service.list_operational_lines(self.connection, sectors=user.sectors, machine_codes=scope)]

    def quality_form(self, machine):
        for code in sorted(machine_capture_service.MACHINE_QUALITY_FORM_CODES):
            try:
                with self.connection.transaction():
                    grant_machine_form(self.connection, user_id=self.supervisor, machine_code=machine, form_code=code, actor_id=self.actor)
            except Exception:  # noqa: BLE001 — el par no se ofrece en esta máquina; el de prueba se desecha de todos modos
                continue
            return code
        self.skipTest(f"ningún formulario de Calidad por máquina se ofrece en {machine}")


class OperationalLinesTests(VisibilityCase):
    def test_each_operator_sees_only_the_lines_of_their_authorized_machines(self):
        self.assertEqual(self.lines_of(self.operator("MP1")), ["L1", "L2"])
        self.assertEqual(self.lines_of(self.operator("MP3")), ["L3"])
        self.assertEqual(self.lines_of(self.operator("MP1", "MP3")), ["L1", "L2", "L3"])

    def test_an_operator_without_grants_sees_nothing_even_with_the_sector(self):
        self.assertEqual(self.lines_of(self.user()), [])

    def test_a_revoked_grant_hides_the_lines_and_a_new_grant_shows_them_again(self):
        user = self.operator("MP1", "MP3")
        self.revoke(user, "MP3")
        self.assertEqual(self.lines_of(user), ["L1", "L2"])
        self.grant(user, "MP3")
        self.assertEqual(self.lines_of(user), ["L1", "L2", "L3"])

    def test_a_grant_without_the_sector_shows_nothing(self):
        user = self.user(sectors=())
        self.grant(user, "MP1")
        self.assertEqual(self.lines_of(user), [])
        self.assertEqual(visibility.authorized_machine_codes(self.connection, user), frozenset())  # el motor también lo niega (SECTOR_NOT_GRANTED)

    def test_revoking_the_sector_after_the_grant_hides_the_lines(self):
        user = self.operator("MP1")
        self.assertEqual(self.lines_of(user), ["L1", "L2"])
        revoke_sector(self.connection, user_id=user.user_id, sector_code="BOBINAS", actor_id=self.actor)
        self.assertEqual(visibility.authorized_machine_codes(self.connection, user), frozenset())  # la fuente de verdad es la base, no la sesión
        self.assertEqual(self.lines_of(user), [])

    def test_a_sector_without_any_form_grant_never_exposes_a_machine(self):
        user = self.user()
        grant_sector(self.connection, user_id=user.user_id, sector_code="REBOBINADO", actor_id=self.actor)
        self.assertEqual(visibility.authorized_machine_codes(self.connection, user), frozenset())

    def test_an_inactive_machine_or_form_hides_the_lines(self):
        user = self.operator("MP1", "MP3")
        self.connection.execute("UPDATE vinto_master.machine SET active=false WHERE code='MP3'")
        self.assertEqual(self.lines_of(user), ["L1", "L2"])
        self.connection.execute("UPDATE vinto_master.machine SET active=true WHERE code='MP3'")
        self.connection.execute("UPDATE vinto_config.form SET active=false WHERE code=%s", (P103,))
        self.assertEqual(self.lines_of(user), [])

    def test_a_quality_form_grant_never_opens_production(self):
        form = self.quality_form("MP1")
        production_user = self.user("OPERACION")
        self.grant(production_user, "MP1", form)  # OPERACION sin permiso de Calidad: la operación de Calidad ni se evalúa
        self.assertEqual(self.lines_of(production_user), [])
        quality_user = self.user("CALIDAD")
        self.grant(quality_user, "MP1", form)
        self.assertEqual(self.lines_of(quality_user), ["L1", "L2"])  # Calidad ve las líneas de SUS máquinas (política de su propia ruta)
        wrong_way = self.user("CALIDAD")
        self.grant(wrong_way, "MP1", P103)  # un formulario de producción para un perfil de Calidad no concede nada
        self.assertEqual(self.lines_of(wrong_way), [])

    def test_managers_keep_their_sector_scope_and_data_analysts_see_no_lines(self):
        for profile in ("JEFATURA", "SUPERVISION"):
            self.assertIsNone(visibility.operational_scope(self.connection, self.user(profile)), profile)
        manager = self.user("SUPERVISION")
        self.assertEqual(self.lines_of(manager), ["L1", "L2", "L3"])
        self.assertEqual(self.lines_of(self.user("DATA_BALTREK")), [])

    def test_each_line_carries_its_unambiguous_assignment_and_selectability(self):
        user = self.operator("MP1", "MP3")
        scope = visibility.operational_scope(self.connection, user)
        lines = service.list_operational_lines(self.connection, sectors=user.sectors, machine_codes=scope)
        self.assertEqual([(l.assignment.machine_code, l.assignment.line.line_code, l.stale) for l in lines], [("MP1", "L1", False), ("MP1", "L2", False), ("MP3", "L3", False)])
        self.assertEqual(len({l.assignment.id for l in lines}), 3)
        self.patch_now(base.NIGHT)  # otro turno: siguen activas pero vencidas y no seleccionables
        stale = service.list_operational_lines(self.connection, sectors=user.sectors, machine_codes=scope)
        self.assertEqual([l.stale for l in stale], [True, True, True])
        self.assertEqual({l.shift_code for l in stale}, {"NOCHE"})


class AssignmentQueryTests(VisibilityCase):
    def test_active_and_active_lines_refuse_an_unauthorized_machine_like_an_out_of_scope_one(self):
        user = self.operator("MP1")
        scope = visibility.operational_scope(self.connection, user)
        for call in (service.get_active, service.get_active_lines):
            with self.assertRaises(MachineOutsideScopeError):
                call(self.connection, machine_code="MP3", sectors=user.sectors, machine_codes=scope)
        listed = service.get_active_lines(self.connection, machine_code="MP1", sectors=user.sectors, machine_codes=scope)
        self.assertEqual([i.assignment.line.line_code for i in listed.items], ["L1", "L2"])
        with self.assertRaises(MultipleActiveAssignmentsError):  # el contrato histórico no elige entre dos (PR3)
            service.get_active(self.connection, machine_code="MP1", sectors=user.sectors, machine_codes=scope)

    def test_listings_cannot_be_widened_with_filters_or_history(self):
        other = self.same_machine_order(1, machine="MP3")
        self.gate(True)
        user = self.operator("MP1")
        scope = visibility.operational_scope(self.connection, user)
        everything = service.list_assignments(self.connection, sectors=user.sectors, machine_codes=scope)
        self.assertEqual({a.machine_code for a in everything}, {"MP1"})
        probes = [dict(machine_code="MP3"), dict(work_order_id=other.id), dict(status="finished"), dict(operating_date=date(2026, 10, 6), machine_code="MP3"),
                  dict(work_order_id=self.mixed.id, machine_code="MP3")]
        for probe in probes:
            self.assertEqual([a for a in service.list_assignments(self.connection, sectors=user.sectors, machine_codes=scope, **probe) if a.machine_code != "MP1"], [], probe)
        history = service.list_assignments(self.connection, sectors=user.sectors, machine_codes=scope, status="active", work_order_id=self.mixed.id)
        self.assertEqual(sorted(a.line.line_code for a in history), ["L1", "L2"])

    def test_managers_see_every_line_through_every_query(self):
        manager = self.user("SUPERVISION")
        self.assertEqual(len(service.list_assignments(self.connection, sectors=manager.sectors, machine_codes=visibility.legacy_scope(self.connection, manager, "t"))), 3)


class ReadModeTests(VisibilityCase):
    def test_the_historical_routes_filter_when_the_gate_is_on_or_the_reads_mode_is_enforce(self):
        user = self.operator("MP1")
        self.assertEqual(visibility.legacy_scope(self.connection, user, "t"), frozenset({"MP1"}))  # compuerta multimáquina encendida (setUp)
        self.gate(False)
        self.assertIsNone(visibility.legacy_scope(self.connection, user, "t"))  # apagada y modo off: comportamiento anterior (brecha documentada)
        with patch.object(settings, "authz_assignment_reads_mode", ENFORCE):
            self.assertEqual(visibility.legacy_scope(self.connection, user, "t"), frozenset({"MP1"}))
        with patch.object(settings, "authz_assignment_reads_mode", OBSERVE):
            with self.assertLogs("vinto.authz", level=logging.INFO) as logs:
                self.assertIsNone(visibility.legacy_scope(self.connection, user, "assignments.list"))  # observa: registra, no cambia la respuesta
            self.assertIn("mode=observe route=assignments.list machines_visible=1", "\n".join(logs.output))

    def test_the_new_operational_contract_filters_in_every_mode(self):
        user = self.operator("MP1")
        for gate in (True, False):
            self.gate(gate)
            for mode in (OFF, OBSERVE, ENFORCE):
                with patch.object(settings, "authz_assignment_reads_mode", mode):
                    self.assertEqual(visibility.operational_scope(self.connection, user), frozenset({"MP1"}), (gate, mode))

    def test_the_default_mode_is_off_and_cannot_be_set_by_the_client(self):
        self.assertEqual(type(settings).model_fields["authz_assignment_reads_mode"].default, "off")
        from app.config import Settings
        self.assertEqual(Settings(_env_file=None, authz_assignment_reads_mode=" Enforce ").authz_assignment_reads_mode, "enforce")
        with self.assertRaises(Exception):
            Settings(_env_file=None, authz_assignment_reads_mode="on")


class WorkOrderReadTests(VisibilityCase):
    def test_an_operator_with_partial_authorization_never_gets_a_partial_work_order(self):
        for machines, visible in ((("MP1",), False), (("MP3",), False), (("MP1", "MP3"), True)):
            user = self.operator(*machines)
            scope = visibility.legacy_scope(self.connection, user, "t")
            numbers = {v.number for v in work_orders.list_work_orders(self.connection, sectors=user.sectors, multi_machine_visible=True, machine_codes=scope)}
            self.assertEqual(self.mixed.number in numbers, visible, machines)
            if visible:
                detail = work_orders.get_work_order(self.connection, self.mixed.id, sectors=user.sectors, multi_machine_visible=True, machine_codes=scope)
                self.assertEqual([(l.line_code, l.machine_code) for l in detail.baseline.lines], [("L1", "MP1"), ("L2", "MP1"), ("L3", "MP3")])
            else:
                with self.assertRaises(WorkOrderNotFoundError):
                    work_orders.get_work_order(self.connection, self.mixed.id, sectors=user.sectors, multi_machine_visible=True, machine_codes=scope)

    def test_single_machine_orders_follow_the_machine_authorization(self):
        single = self.same_machine_order(1, machine="MP3")
        mp1, mp3 = self.operator("MP1"), self.operator("MP3")
        for user, expected in ((mp1, False), (mp3, True)):
            scope = visibility.legacy_scope(self.connection, user, "t")
            self.assertEqual(single.number in {v.number for v in work_orders.list_work_orders(self.connection, sectors=user.sectors, machine_codes=scope)}, expected)

    def test_managers_still_work_with_the_whole_order(self):
        manager = self.user("JEFATURA")
        self.assertIsNone(visibility.legacy_scope(self.connection, manager, "t"))
        detail = work_orders.get_work_order(self.connection, self.mixed.id, sectors=manager.sectors, multi_machine_visible=True)
        self.assertEqual(len(detail.baseline.lines), 3)


class CaptureAuthorizationTests(VisibilityCase):
    """Escrituras: el `assignment_id` fija la máquina; bajo `enforce` una captura sin la concesión de ESA máquina se rechaza."""

    def setUp(self):
        super().setUp()
        self._now_patch.stop()  # las capturas usan el reloj real; las activaciones también
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        plan = service.preview_activate_all(self.connection, work_order_id=self.mixed.id).plan
        service.activate_all(self.connection, actor_id=self.supervisor, work_order_id=self.mixed.id, plan_hash=plan.plan_hash)
        self.by_line = {a.line.line_code: a for a in service.list_assignments(self.connection, sectors=("BOBINAS",), status="active", work_order_id=self.mixed.id)}
        self.counts_at_start = self.captures()

    def captures(self):
        return self.scalar("SELECT count(*) FROM vinto_txn.capture")

    def submit(self, user, line_code, mode=ENFORCE, op=Operation.BOBBIN_PRODUCTION, **kwargs):
        gate = None if mode == OFF else OperationGate(user, mode, "pr5-test", op)
        return bobbins.submit_bobbin_production(self.connection, actor_id=user.user_id, capture_id=uuid4(), assignment_id=self.by_line[line_code].id,
                                                device_key=str(uuid4()), values=VALUES, gate=gate, sectors=user.sectors, **kwargs)

    def test_enforce_allows_each_line_of_an_authorized_machine_and_binds_the_capture_to_its_assignment(self):
        user = self.operator("MP1")
        for code in ("L1", "L2", "L1"):
            result = self.submit(user, code)
            self.assertEqual(self.scalar("SELECT assignment_id FROM vinto_txn.capture WHERE id=%s", (result.capture.id,)), self.by_line[code].id)
        self.assertEqual(self.captures(), self.counts_at_start + 3)

    def test_enforce_rejects_a_foreign_assignment_id_without_writing_anything(self):
        user = self.operator("MP1")
        before = [self.scalar(f"SELECT count(*) FROM {t}") for t in ("vinto_txn.capture", "vinto_txn.capture_detail", "vinto_txn.bobbin", "vinto_master.device")]
        with self.assertRaises(AuthorizationDenied):
            self.submit(user, "L3")  # la línea de MP3: el cliente cambió el assignment_id
        self.assertEqual([self.scalar(f"SELECT count(*) FROM {t}") for t in ("vinto_txn.capture", "vinto_txn.capture_detail", "vinto_txn.bobbin", "vinto_master.device")], before)

    def test_enforce_rejects_users_without_the_machine_grant_revoked_or_with_a_quality_only_grant(self):
        self.quality_form("MP1")
        for user in (self.user(), self.operator("MP3")):
            with self.assertRaises(AuthorizationDenied):
                self.submit(user, "L1")
        revoked = self.operator("MP1")
        self.revoke(revoked, "MP1")
        with self.assertRaises(AuthorizationDenied):
            self.submit(revoked, "L1")
        quality_only = self.user("OPERACION")
        self.grant(quality_only, "MP1", self.quality_form("MP1"))
        with self.assertRaises(AuthorizationDenied):
            self.submit(quality_only, "L2")
        self.assertEqual(self.captures(), self.counts_at_start)

    def test_a_grant_of_another_production_form_does_not_authorize_f3(self):
        user = self.operator("MP1", form=P106)  # F6 en MP1, pero la ruta F3 exige la concesión de F3
        with self.assertRaises(AuthorizationDenied):
            self.submit(user, "L1")

    def test_with_off_and_observe_the_old_behaviour_remains_documented_gap(self):
        """off/observe NO protegen: documentado en PR5. Una captura sobre la línea de una máquina sin concesión pasa si el modo de ESA ruta no es `enforce`."""
        stranger = self.operator("MP1")
        self.submit(stranger, "L3", mode=OFF)
        with self.assertLogs("vinto.authz", level=logging.WARNING) as logs:
            self.submit(stranger, "L3", mode=OBSERVE)
        self.assertIn("would_forbidden", "\n".join(logs.output))
        self.assertEqual(self.captures(), self.counts_at_start + 2)

    def test_each_capture_route_builds_its_gate_from_its_own_setting_and_operation(self):
        from pathlib import Path
        backend = Path(__file__).resolve().parent.parent / "app"
        expected = {"captures.py": ("authz_central_captures_mode", None), "bobbins/router.py": ("authz_bobbin_production_mode", "BOBBIN_PRODUCTION"),
                    "quality/router.py": ("authz_quality_bobbin_captures_mode", "QUALITY_BOBBIN_CAPTURE"), "quality/machine_router.py": ("authz_quality_machine_captures_mode", "QUALITY_MACHINE_CAPTURE")}
        for path, (setting, operation) in expected.items():
            text = (backend / path).read_text(encoding="utf-8")
            self.assertIn(f"settings.{setting}", text, path)
            if operation:
                self.assertIn(f"Operation.{operation}", text, path)

    def test_a_concurrent_revocation_cannot_slip_between_authorization_and_the_capture(self):
        user = self.operator("MP1")
        holder = connect(self.database)
        self.addCleanup(holder.close)
        with holder.transaction():
            require(holder, user, Operation.BOBBIN_PRODUCTION, "MP1", P103, lock=True)  # la captura ya autorizó y sigue en su transacción
            revoker = connect(self.database)
            self.addCleanup(revoker.close)
            revoker.execute("SET lock_timeout = '400ms'")  # solo detecta que la revocación está bloqueada; la sincronización es el bloqueo de PostgreSQL
            with self.assertRaises(psycopg.errors.LockNotAvailable):
                revoke_machine_form(revoker, user_id=user.user_id, machine_code="MP1", form_code=P103, actor_id=self.actor)
        revoker.execute("RESET lock_timeout")
        self.assertTrue(revoke_machine_form(revoker, user_id=user.user_id, machine_code="MP1", form_code=P103, actor_id=self.actor))  # una vez terminada, sí revoca
        with self.assertRaises(AuthorizationDenied):
            self.submit(user, "L1")

    def test_assignments_and_audit_are_untouched_by_captures_and_denials(self):
        user = self.operator("MP1")
        before = self.connection.execute("SELECT to_jsonb(a) FROM vinto_txn.assignment a ORDER BY id").fetchall()
        self.submit(user, "L1")
        with self.assertRaises(AuthorizationDenied):
            self.submit(user, "L3")
        self.assertEqual(self.connection.execute("SELECT to_jsonb(a) FROM vinto_txn.assignment a ORDER BY id").fetchall(), before)
        events = self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table='capture' AND actor_id=%s", (user.user_id,))
        self.assertGreater(events, 0)  # la captura autorizada quedó auditada con su actor
        with self.assertRaises(AuthorizationDenied):
            self.submit(user, "L3")
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event WHERE entity_table='capture' AND actor_id=%s", (user.user_id,)), events)  # la denegada no deja nada


if __name__ == "__main__":
    unittest.main()
