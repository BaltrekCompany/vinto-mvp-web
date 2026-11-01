"""MF-13-01D.3A: la revocación administrativa de un sector se sincroniza con las capturas autorizadas por el motor `app/authz`.

`revoke_sector` toma `FOR NO KEY UPDATE` sobre la fila del usuario antes de borrar de `user_sector`; el motor mantiene `FOR SHARE` sobre esa fila durante toda la transacción de captura. Aquí se demuestra, en
PostgreSQL 17 y con un rol construido desde `backend/roles/*.sql` (los privilegios reales de `vinto_app`): la semántica de los bloqueos, ambas carreras en las CUATRO operaciones, que el bloqueo es posible con esos
privilegios, la concurrencia mixta sin interbloqueos y que la idempotencia, la auditoría y los contratos siguen igual. Las capturas se ejecutan con el alcance de sectores que la sesión ya había leído (`sectors`
obsoleto a propósito): es exactamente la carrera, y debe decidirla el motor.
"""

import re
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg

from app import capture_service as cs
from app.auth.grants import grant_sector, revoke_sector
from app.auth.machine_form_grants import grant_machine_form, revoke_machine_form
from app.auth.service import AuthenticatedUser
from app.authz.capture_gate import OperationGate
from app.authz.errors import AuthorizationDenied
from app.authz.policies import Operation
from app.bobbins import service as bobbin_service
from app.ephemeral_db import build_reference_template, connect, drop_database
from app.quality import capture_service as quality
from app.quality import machine_capture_service as machine_quality

try:
    import test_f3_bobbins_api as f3
    import test_f6_captures_api as f6
    import test_quality_bobbin_authz as qb
    import test_quality_machine_authz as qm
except ModuleNotFoundError:
    import tests.test_f3_bobbins_api as f3
    import tests.test_f6_captures_api as f6
    import tests.test_quality_bobbin_authz as qb
    import tests.test_quality_machine_authz as qm

BACKEND = Path(__file__).resolve().parent.parent
P103, P106, P119, P122 = "VINTO-P1-03", "VINTO-P1-06", "VINTO-P1-19", "VINTO-P1-22"
STALE = frozenset({"BOBINAS"})  # el alcance que la sesión ya había leído antes de la revocación
OPERATIONS = ("central", "f3", "quality_bobbin", "quality_machine")
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_d3a_tpl")
    f3.STATE["template"] = STATE["template"]


def tearDownModule():
    drop_database(STATE["template"])


class SyncCase(f3.BobbinApiCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.operator = self.users["OPERACION"][0].user_id
        self.quality_user = self.users["CALIDAD"][0].user_id
        self.admin = self.users["DATA_BALTREK"][0].user_id
        self.connection.execute("SELECT set_config('vinto.actor_id', %s, false)", (str(self.admin),))
        self.connection.execute("UPDATE vinto_master.user_machine_form_grant SET revoked_at = clock_timestamp(), revoked_by = %s WHERE revoked_at IS NULL", (self.admin,))
        for user in (self.operator, self.quality_user):
            grant_sector(self.connection, user_id=user, sector_code="BOBINAS", actor_id=self.admin)  # cada prueba parte con el sector concedido
        for user, form in ((self.operator, P106), (self.operator, P103), (self.quality_user, P119), (self.quality_user, P122)):
            grant_machine_form(self.connection, user_id=user, machine_code="MP1", form_code=form, actor_id=self.admin)

    def principal(self, user, profile):
        return AuthenticatedUser(user, "u", "U", (profile,), frozenset(), False, STALE)

    def written(self):
        return [self.scalar(f"SELECT count(*) FROM {t}") for t in ("vinto_txn.capture", "vinto_txn.capture_detail", "vinto_master.device", "vinto_txn.bobbin", "vinto_txn.quality_release")]

    async def target(self, op, shared=None):
        """(usuario, ejecutar(conn) → resultado de la captura con el motor en enforce y el alcance obsoleto, petición HTTP equivalente)."""
        rid = "rid"

        async def assignment_for_this_target():
            return shared if shared is not None else (await self.assignment())[1]  # en MP1 solo hay UNA asignación activa: las pruebas mixtas comparten la suya
        if op == "central":
            user, _ = self.operator, None
            assignment = await assignment_for_this_target()

            def body():
                return {"capture_id": str(uuid4()), "form_code": P106, "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": dict(f6.VALUES)}

            def run(conn):
                b = body()
                return cs.submit_production_capture(conn, actor_id=user, capture_id=b["capture_id"], form_code=P106, assignment_id=b["assignment_id"], device_key=b["device_key"], values=b["values"],
                                                    request_id=rid, sectors=STALE, gate=OperationGate(self.principal(user, "OPERACION"), "enforce", rid, Operation.PRODUCTION_CAPTURE))
            return user, run, ("/api/captures", body, "OPERACION")
        if op == "f3":
            user = self.operator
            assignment = await assignment_for_this_target()

            def body():
                return self.payload(assignment)

            def run(conn):
                b = body()
                return bobbin_service.submit_bobbin_production(conn, actor_id=user, capture_id=b["capture_id"], assignment_id=b["assignment_id"], device_key=b["device_key"], values=b["values"],
                                                               request_id=rid, sectors=STALE, gate=OperationGate(self.principal(user, "OPERACION"), "enforce", rid, Operation.BOBBIN_PRODUCTION))
            return user, run, ("/api/bobbins", body, "OPERACION")
        if op == "quality_bobbin":
            user = self.quality_user
            assignment = await assignment_for_this_target()
            bobbin = (await self.post(self.payload(assignment))).json()["bobbin"]  # con el modo de F3 en off, como hoy

            def body():
                return {"capture_id": str(uuid4()), "form_code": P119, "device_key": str(uuid4()), "values": dict(qb.P119_VALUES)}

            def run(conn):
                b = body()
                return quality.submit_quality_capture(conn, actor_id=user, bobbin_id=bobbin["id"], capture_id=b["capture_id"], form_code=P119, device_key=b["device_key"], values=b["values"],
                                                      request_id=rid, sectors=STALE, gate=OperationGate(self.principal(user, "CALIDAD"), "enforce", rid, Operation.QUALITY_BOBBIN_CAPTURE))
            return user, run, (f"/api/quality/bobbins/{bobbin['id']}/captures", body, "CALIDAD")
        user = self.quality_user

        def body():
            return {"capture_id": str(uuid4()), "form_code": P122, "device_key": str(uuid4()), "values": dict(qm.P122_V2)}

        def run(conn):
            b = body()
            return machine_quality.submit_machine_capture(conn, actor_id=user, machine_code="MP1", capture_id=b["capture_id"], form_code=P122, device_key=b["device_key"], values=b["values"],
                                                          request_id=rid, sectors=STALE, gate=OperationGate(self.principal(user, "CALIDAD"), "enforce", rid, Operation.QUALITY_MACHINE_CAPTURE))
        return user, run, ("/api/quality/machines/MP1/captures", body, "CALIDAD")

    def threaded(self, fn, results, role=None):
        def work():
            conn = connect(self.database)
            try:
                if role:
                    conn.execute(f"SET ROLE {role}")
                results.append(fn(conn))
            except BaseException as error:  # noqa: BLE001
                results.append(error)
            finally:
                conn.close()
        return threading.Thread(target=work)

    def app_role(self):
        """Rol con los privilegios REALES de vinto_app (backend/roles/*.sql + la 0007): sin UPDATE en user_sector ni vinto_config."""
        role = "d3a_app_" + uuid4().hex[:8]
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
        return role

    def revoke(self, user, role=None):
        def fn(conn):
            return revoke_sector(conn, user_id=user, sector_code="BOBINAS", actor_id=self.admin)
        results = []
        return self.threaded(fn, results, role), results


# ---- 1. semántica de bloqueos en PostgreSQL 17 (con los privilegios de vinto_app) ------------------------------------------------------------------------------

class LockSemanticsTests(SyncCase):
    def other(self):
        connection = connect(self.database)
        self.addCleanup(connection.close)
        return connection

    def blocked(self, holder_sql, contender_sql, user, role=None):
        """¿`contender_sql` espera a `holder_sql`? (lock_timeout corto; ambos sobre la fila del usuario)."""
        contender = self.other()
        with self.connection.transaction():
            if role:
                self.connection.execute(f"SET LOCAL ROLE {role}")
            self.connection.execute(holder_sql, (user,))
            try:
                with contender.transaction():
                    contender.execute("SET LOCAL lock_timeout = 300")
                    contender.execute(contender_sql, (user,))
            except psycopg.errors.LockNotAvailable:
                return True
        return False

    USER = 'SELECT 1 FROM vinto_master."user" WHERE id = %s'

    async def test_no_key_update_conflicts_with_the_engines_for_share(self):
        self.assertTrue(self.blocked(self.USER + " FOR SHARE", self.USER + " FOR NO KEY UPDATE", self.operator))  # captura en curso → la revocación espera
        self.assertTrue(self.blocked(self.USER + " FOR NO KEY UPDATE", self.USER + " FOR SHARE", self.operator))  # revocación en curso → la captura espera

    async def test_no_key_update_does_not_block_foreign_key_checks_but_for_update_would(self):
        self.assertFalse(self.blocked(self.USER + " FOR NO KEY UPDATE", self.USER + " FOR KEY SHARE", self.operator))  # las comprobaciones de clave foránea ajenas no esperan
        self.assertTrue(self.blocked(self.USER + " FOR UPDATE", self.USER + " FOR KEY SHARE", self.operator))  # FOR UPDATE sí las bloquearía: por eso no se usa

    async def test_it_is_possible_with_the_privileges_of_vinto_app_and_user_sector_still_is_not(self):
        role = self.app_role()
        self.assertTrue(self.blocked(self.USER + " FOR NO KEY UPDATE", self.USER + " FOR SHARE", self.operator, role=role))  # el rol puede tomar el bloqueo y entra en conflicto con el del motor
        with self.assertRaises(psycopg.errors.InsufficientPrivilege), self.connection.transaction():
            self.connection.execute(f"SET LOCAL ROLE {role}")
            self.connection.execute("SELECT 1 FROM vinto_master.user_sector LIMIT 1 FOR NO KEY UPDATE")  # la premisa original: sobre user_sector no se puede (42501)

    async def test_the_lock_order_is_user_then_user_sector_and_the_grant_side_takes_no_lock(self):
        source = (BACKEND / "app/auth/grants.py").read_text(encoding="utf-8")
        revoke = source[source.index("def revoke_sector"):]
        code = revoke[revoke.index("with connection.transaction():"):]  # solo el código, no el docstring que explica el bloqueo
        self.assertLess(code.index("FOR NO KEY UPDATE"), code.index("DELETE FROM vinto_master.user_sector"))
        self.assertNotIn("FOR UPDATE", code.replace("FOR NO KEY UPDATE", ""))
        self.assertNotIn("FOR NO KEY UPDATE", source[source.index("def grant_sector"):source.index("def revoke_sector")])

    async def test_a_revocation_in_progress_does_not_block_foreign_key_checks_that_only_reference_the_user(self):
        """El efecto observable de elegir NO KEY UPDATE (y no UPDATE): mientras una revocación está abierta, una escritura ajena que solo REFERENCIA al usuario no espera."""
        holder, other = connect(self.database), self.other()
        self.addCleanup(holder.close)
        with holder.transaction():
            self.assertTrue(revoke_sector(holder, user_id=self.operator, sector_code="BOBINAS", actor_id=self.admin))  # revocación abierta, sin confirmar
            with other.transaction():
                other.execute("SET LOCAL lock_timeout = 500")
                self.assertTrue(grant_sector(other, user_id=self.operator, sector_code="REBOBINADO", actor_id=self.admin))  # INSERT con clave foránea al usuario: toma KEY SHARE sobre su fila


# ---- 2. las dos carreras, en las cuatro operaciones --------------------------------------------------------------------------------------------------------------

class RaceTests(SyncCase):
    async def test_race_1_an_authorised_capture_in_progress_makes_the_revocation_wait_for_its_commit(self):
        for op in OPERATIONS:
            with self.subTest(operation=op):
                grant_sector(self.connection, user_id=self.operator, sector_code="BOBINAS", actor_id=self.admin)
                grant_sector(self.connection, user_id=self.quality_user, sector_code="BOBINAS", actor_id=self.admin)
                user, run, _ = await self.target(op)
                inside, release, captured = threading.Event(), threading.Event(), []
                real = cs._resolve_device

                def paused(connection, device_key, machine_id, _real=real):
                    inside.set()  # ya autorizada y con los bloqueos tomados: sigue dentro de la transacción de la captura
                    release.wait(30)
                    return _real(connection, device_key, machine_id)
                with patch.object(cs, "_resolve_device", paused):
                    capture = self.threaded(run, captured)
                    capture.start()
                    self.assertTrue(inside.wait(20))
                    revoker, revoked = self.revoke(user)
                    revoker.start()
                    revoker.join(1.0)
                    self.assertTrue(revoker.is_alive(), "la revocación debe esperar al COMMIT de la captura")  # sincronizada
                    release.set()
                    capture.join(30)
                    revoker.join(30)
                self.assertTrue(captured and getattr(captured[0], "created", False), captured)  # la captura en curso se completó con el sector que tenía al autorizarse
                self.assertEqual(revoked, [True])  # y la revocación terminó después
                before = self.written()
                with self.assertRaises(AuthorizationDenied) as denied:  # las posteriores se deniegan (aunque lleguen con el alcance obsoleto)
                    run(self.connection)
                self.assertEqual(denied.exception.decision.reason, "SECTOR_NOT_GRANTED")
                self.assertEqual(self.written(), before)

    async def test_race_2_a_revocation_in_progress_makes_the_capture_wait_and_then_denies_it(self):
        for op in OPERATIONS:
            with self.subTest(operation=op):
                grant_sector(self.connection, user_id=self.operator, sector_code="BOBINAS", actor_id=self.admin)
                grant_sector(self.connection, user_id=self.quality_user, sector_code="BOBINAS", actor_id=self.admin)
                user, run, _ = await self.target(op)
                before = self.written()
                holder, captured = connect(self.database), []
                self.addCleanup(holder.close)
                with holder.transaction():
                    self.assertTrue(revoke_sector(holder, user_id=user, sector_code="BOBINAS", actor_id=self.admin))  # revocación hecha pero SIN confirmar
                    capture = self.threaded(run, captured)
                    capture.start()
                    capture.join(1.0)
                    self.assertTrue(capture.is_alive(), "la captura debe esperar a la revocación en curso")
                capture.join(30)  # se confirma la revocación
                self.assertEqual(len(captured), 1)
                self.assertIsInstance(captured[0], AuthorizationDenied, captured)
                self.assertEqual(captured[0].decision.reason, "SECTOR_NOT_GRANTED")
                self.assertEqual(self.written(), before)  # sin capturas, detalles, dispositivos, bobinas ni liberaciones

    async def test_after_the_revocation_commits_a_new_http_request_is_rejected_and_writes_nothing(self):
        for op in OPERATIONS:
            with self.subTest(operation=op):
                grant_sector(self.connection, user_id=self.operator, sector_code="BOBINAS", actor_id=self.admin)
                grant_sector(self.connection, user_id=self.quality_user, sector_code="BOBINAS", actor_id=self.admin)
                user, _, (path, body, profile) = await self.target(op)
                cookie = await self.cookie(profile)
                revoke_sector(self.connection, user_id=user, sector_code="BOBINAS", actor_id=self.admin)
                before = self.written()
                from tests.test_assignments_api import call  # noqa: F401  (importación perezosa: solo para esta prueba)
                reply = await call("POST", path, json_body=body(), cookie=cookie)
                self.assertIn(reply.status, (403, 404, 422), (op, reply.status))  # el alcance de sectores relee la base: ya no hay sector
                self.assertEqual(self.written(), before)

    async def test_running_the_revocation_with_the_privileges_of_vinto_app(self):
        role = self.app_role()
        for op in OPERATIONS:
            with self.subTest(operation=op):
                grant_sector(self.connection, user_id=self.operator, sector_code="BOBINAS", actor_id=self.admin)
                grant_sector(self.connection, user_id=self.quality_user, sector_code="BOBINAS", actor_id=self.admin)
                user, run, _ = await self.target(op)
                inside, release, captured = threading.Event(), threading.Event(), []
                real = cs._resolve_device

                def paused(connection, device_key, machine_id, _real=real):
                    inside.set()
                    release.wait(30)
                    return _real(connection, device_key, machine_id)
                with patch.object(cs, "_resolve_device", paused):
                    capture = self.threaded(run, captured, role=role)  # la captura TAMBIÉN con el rol de la aplicación
                    capture.start()
                    self.assertTrue(inside.wait(20))
                    revoker, revoked = self.revoke(user, role=role)  # y la revocación
                    revoker.start()
                    revoker.join(1.0)
                    self.assertTrue(revoker.is_alive())
                    release.set()
                    capture.join(30)
                    revoker.join(30)
                self.assertTrue(captured and getattr(captured[0], "created", False), captured)
                self.assertEqual(revoked, [True])


# ---- 3. concurrencia mixta -------------------------------------------------------------------------------------------------------------------------------------------

class MixedConcurrencyTests(SyncCase):
    async def test_no_deadlocks_under_captures_of_the_four_operations_sector_and_machine_form_toggles(self):
        runs = []
        _, shared = await self.assignment()
        for op in OPERATIONS:
            _, run, _ = await self.target(op, shared)
            runs.append((op, run))
        errors, outcomes = [], []

        def submitter(index, op, run):
            conn = connect(self.database)
            try:
                for _ in range(5):
                    try:
                        result = run(conn)
                        outcomes.append((op, "created" if result.created else "retry"))
                    except AuthorizationDenied as denied:
                        outcomes.append((op, "denied:" + denied.decision.reason))
            except BaseException as error:  # noqa: BLE001 — un deadlock o AuthorizationUnavailable aparece aquí
                errors.append(f"{op}: {error!r}")
            finally:
                conn.close()

        def sector_toggler(user):
            conn = connect(self.database)
            try:
                for _ in range(12):
                    revoke_sector(conn, user_id=user, sector_code="BOBINAS", actor_id=self.admin)
                    time.sleep(0.01)
                    grant_sector(conn, user_id=user, sector_code="BOBINAS", actor_id=self.admin)
            except BaseException as error:  # noqa: BLE001
                errors.append(f"sector: {error!r}")
            finally:
                conn.close()

        def grant_toggler(user, form):
            conn = connect(self.database)
            try:
                for _ in range(8):
                    revoke_machine_form(conn, user_id=user, machine_code="MP1", form_code=form, actor_id=self.admin)
                    time.sleep(0.01)
                    grant_machine_form(conn, user_id=user, machine_code="MP1", form_code=form, actor_id=self.admin)
            except BaseException as error:  # noqa: BLE001
                errors.append(f"grant: {error!r}")
            finally:
                conn.close()
        threads = [threading.Thread(target=submitter, args=(i, op, run)) for i, (op, run) in enumerate(runs * 2)]
        threads += [threading.Thread(target=sector_toggler, args=(u,)) for u in (self.operator, self.quality_user)]
        threads += [threading.Thread(target=grant_toggler, args=(self.operator, P106)), threading.Thread(target=grant_toggler, args=(self.quality_user, P122))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(180)
        self.assertEqual(errors, [])
        kinds = {o[1].split(":")[0] for o in outcomes}
        self.assertIn("created", kinds)
        self.assertTrue({o[1] for o in outcomes if o[1].startswith("denied")} <= {"denied:SECTOR_NOT_GRANTED", "denied:GRANT_MISSING"}, outcomes)
        self.assertEqual({o[0] for o in outcomes}, set(OPERATIONS))  # las cuatro operaciones participaron


# ---- 4. contratos existentes y caminos que tocan user_sector ------------------------------------------------------------------------------------------------------

class UnchangedBehaviourTests(SyncCase):
    async def test_revocation_is_idempotent_audited_and_reports_unknown_users_and_sectors_as_before(self):
        user = self.operator
        self.assertTrue(revoke_sector(self.connection, user_id=user, sector_code="BOBINAS", actor_id=self.admin, request_id="rev-1"))
        self.assertFalse(revoke_sector(self.connection, user_id=user, sector_code="BOBINAS", actor_id=self.admin))  # idempotente
        event = self.connection.execute("SELECT actor_id, request_id, reason FROM vinto_audit.audit_event WHERE entity_table = 'user_sector' AND action = 'DELETE' ORDER BY occurred_at DESC LIMIT 1").fetchone()
        self.assertEqual((event[0], event[1], event[2]), (self.admin, "rev-1", "sector revoke"))
        from app.auth.errors import SectorNotFoundError, UserNotFoundError
        with self.assertRaises(UserNotFoundError):
            revoke_sector(self.connection, user_id=uuid4(), sector_code="BOBINAS", actor_id=self.admin)
        with self.assertRaises(SectorNotFoundError):
            revoke_sector(self.connection, user_id=user, sector_code="NO-SUCH", actor_id=self.admin)

    async def test_granting_a_sector_is_not_blocked_by_a_running_capture_and_never_over_authorises(self):
        grant_sector(self.connection, user_id=self.quality_user, sector_code="BOBINAS", actor_id=self.admin)
        user, run, _ = await self.target("central")
        inside, release, captured = threading.Event(), threading.Event(), []
        real = cs._resolve_device

        def paused(connection, device_key, machine_id):
            inside.set()
            release.wait(30)
            return real(connection, device_key, machine_id)
        with patch.object(cs, "_resolve_device", paused):
            capture = self.threaded(run, captured)
            capture.start()
            self.assertTrue(inside.wait(20))
            started = time.monotonic()
            grant_sector(self.connection, user_id=user, sector_code="REBOBINADO", actor_id=self.admin)  # conceder otro sector no espera a la captura
            self.assertLess(time.monotonic() - started, 1.0)
            release.set()
            capture.join(30)
        self.assertTrue(getattr(captured[0], "created", False))

    async def test_the_only_code_that_deletes_or_inserts_user_sector_is_grants_py(self):
        statements = {}
        for path in (BACKEND / "app").rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for sql in re.findall(r"(?:INSERT INTO|DELETE FROM|UPDATE)\s+vinto_master\.user_sector", text):
                statements.setdefault(str(path.relative_to(BACKEND)).replace("\\", "/"), []).append(sql.split()[0])
        self.assertEqual(statements, {"app/auth/grants.py": ["INSERT", "DELETE"]})  # grant_sector y revoke_sector; create_user concede a través de grant_sector
        self.assertEqual([p for p in (BACKEND / "app").rglob("*.py") if "revoke_sector(" in p.read_text(encoding="utf-8") and p.name not in ("grants.py", "service.py")], [])

    async def test_the_admin_endpoint_contract_is_unchanged(self):
        from tests.test_assignments_api import call  # noqa: F401
        admin_cookie = await self.cookie("DATA_BALTREK")
        path = f"/api/admin/users/{self.operator}/sectors/revoke"
        headers = [("origin", "http://127.0.0.1:8787")]
        first = await call("POST", path, json_body={"sector_code": "BOBINAS"}, cookie=admin_cookie, extra_headers=headers)
        second = await call("POST", path, json_body={"sector_code": "BOBINAS"}, cookie=admin_cookie, extra_headers=headers)
        self.assertEqual((first.status, first.json()["changed"], second.status, second.json()["changed"]), (200, True, 200, False))


if __name__ == "__main__":
    unittest.main()
