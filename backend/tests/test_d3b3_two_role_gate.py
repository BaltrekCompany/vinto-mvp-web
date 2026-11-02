"""MF-13-01D.3B.3 — puerta de verificación con DOS roles, y MF-13-01D.3B.4 — scripts del corte y su reversión.

Recorre la secuencia completa con los scripts REALES de backend/roles (roles LOGIN con los GRANT reales de 02/03):

    S0 estado inicial → S1 D.3B.1 (03b) → S2 D.3B.2 (00c/03c) → S3 D.3B.4 (03d, el corte) → S4 ROLLBACK_D3B4 → S5 ROLLBACK_D3B2 → S6 ROLLBACK_D3B1 (= S0)

y ejecuta en cada estado la matriz que corresponde: login/logout//api/auth/me, administración de usuarios/sectores/concesiones, CLI, las cuatro capturas con `enforce`, auditoría y atribución del
actor, revocaciones concurrentes, `current_user` distinto entre conexiones y, tras el corte, que el rol de negocio no puede modificar identidad. El resultado se acumula en un informe de
EVIDENCIA (JSON + Markdown, sin URLs ni contraseñas) con veredicto APROBADA/RECHAZADA; con D3B3_EVIDENCE_DIR lo escribe en disco y con D3B3_REQUIRE_PG17=1 exige PostgreSQL 17.

Solo corre en bases efímeras *_test: NADA de esto se ejecuta contra una base persistente. Los roles son temporales y se eliminan al terminar.
"""

import contextlib
import io
import json
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from pydantic import SecretStr

from app import capture_service as cs
from app.admin import service as admin_service
from app.admin.actor import require_actor_authorized
from app.admin.errors import ActorNotAuthorized
from app.auth.grants import grant_sector
from app.auth.service import create_user, deactivate_user
from app.authz.errors import AuthorizationDenied
from app.config import settings
from app.database import get_identity_connection
from app.ephemeral_db import build_reference_template, connect, database_url, drop_database
from app.main import app

try:
    import create_user as create_user_cli
    import manage_user as manage_user_cli
    import test_assignments_api as asg
    import test_d3b1_privilege_hardening as d1
    import test_d3b2_identity_role as d2
    import test_f3_bobbins_api as f3
    import test_grants_hardening_design as d3b
    import test_sector_revocation_sync as sync
except ModuleNotFoundError:
    import create_user as create_user_cli
    import manage_user as manage_user_cli
    import tests.test_assignments_api as asg
    import tests.test_d3b1_privilege_hardening as d1
    import tests.test_d3b2_identity_role as d2
    import tests.test_f3_bobbins_api as f3
    import tests.test_grants_hardening_design as d3b
    import tests.test_sector_revocation_sync as sync

BACKEND = Path(__file__).resolve().parent.parent
ROLES = BACKEND / "roles"
CUT = ROLES / "03d_d3b4_cut_identity_dml.sql"
CUT_ROLLBACK = ROLES / "rollback/ROLLBACK_D3B4.sql"
PREFLIGHT = ROLES / "08_release_preflight.sql"
APPROVAL = "CUT-IDENTITY-DML-APPROVED"
ORIGIN = settings.cors_origins[0]
STATE = {}
CONTRACT = "mf-13-01d3b3-gate/v1"


def setUpModule():
    STATE["template"] = build_reference_template("vinto_d3b3_tpl")
    for module in (f3, d3b, d1, d2):
        module.STATE["template"] = STATE["template"]


def tearDownModule():
    drop_database(STATE["template"])


# ---- informe de evidencia --------------------------------------------------------------------------------------------------------------------------------

class Report:
    """Acumula comprobaciones por estado. El veredicto es APROBADA solo si TODAS pasan; una excepción dentro de una comprobación la deja como fallida (nunca se pierde en silencio)."""

    def __init__(self):
        self.checks = []

    def check(self, state, name, condition, detail=""):
        self.checks.append({"state": state, "check": name, "ok": bool(condition), "detail": "" if condition else str(detail)[:300]})
        return bool(condition)

    @contextlib.contextmanager
    def guard(self, state, name):
        try:
            yield
        except BaseException as error:  # noqa: BLE001
            self.checks.append({"state": state, "check": name, "ok": False, "detail": f"{type(error).__name__}: {error}"[:300]})

    @property
    def verdict(self):
        return "APROBADA" if self.checks and all(c["ok"] for c in self.checks) else "RECHAZADA"

    def document(self, server_version_num, server_version, commit):
        failed = [c for c in self.checks if not c["ok"]]
        pg17 = server_version_num // 10000 == 17
        return {"contract": CONTRACT, "verdict": self.verdict, "postgres_17_verified": pg17,
                "valid_as_gate_approval": self.verdict == "APROBADA" and pg17, "server_version": server_version, "commit": commit,
                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "checks_total": len(self.checks), "checks_failed": len(failed), "checks": self.checks}

    @staticmethod
    def markdown(document):
        lines = [f"# D.3B.3 — puerta de verificación con dos roles: {document['verdict']}", "",
                 f"- Contrato: `{document['contract']}`", f"- PostgreSQL: {document['server_version']} (17 verificado: {document['postgres_17_verified']})",
                 f"- Válida como aprobación de la puerta: **{document['valid_as_gate_approval']}**" + ("" if document["postgres_17_verified"] else " (la aprobación exige PostgreSQL 17)"),
                 f"- Commit: `{document['commit']}`", f"- Comprobaciones: {document['checks_total']} (fallidas: {document['checks_failed']})", "",
                 "| Estado | Comprobación | Resultado |", "|---|---|---|"]
        lines += [f"| {c['state']} | {c['check']} | {'OK' if c['ok'] else 'FALLO: ' + c['detail']} |" for c in document["checks"]]
        return "\n".join(lines) + "\n"


class ReportTests(unittest.TestCase):
    def test_the_verdict_is_approved_only_when_every_check_passes(self):
        report = Report()
        report.check("S0", "a", True)
        report.check("S3", "b", True)
        self.assertEqual(report.verdict, "APROBADA")
        report.check("S3", "c", False, "boom")
        self.assertEqual(report.verdict, "RECHAZADA")
        self.assertEqual(Report().verdict, "RECHAZADA")  # sin comprobaciones no hay aprobación

    def test_an_exception_inside_a_check_is_a_recorded_failure(self):
        report = Report()
        with report.guard("S3", "explota"):
            raise RuntimeError("fallo inesperado")
        self.assertEqual((report.verdict, report.checks[0]["ok"]), ("RECHAZADA", False))
        self.assertIn("fallo inesperado", report.checks[0]["detail"])

    def test_approval_is_only_valid_on_postgresql_17_and_the_evidence_has_no_secrets(self):
        report = Report()
        report.check("S0", "a", True)
        on16 = report.document(160015, "16.15", "abc")
        on17 = report.document(170011, "17.11", "abc")
        self.assertEqual((on16["verdict"], on16["valid_as_gate_approval"]), ("APROBADA", False))
        self.assertTrue(on17["valid_as_gate_approval"])
        text = json.dumps(on17) + Report.markdown(on17)
        self.assertNotRegex(text, r"(?i)postgresql://|password|pw-")

# ---- auditoría de rutas: recorrer de verdad TODAS las rutas HTTP ---------------------------------------------------------------------------------------------

HTTP_METHODS = ("get", "post", "put", "patch", "delete")
EXPECTED_ADMIN_OPERATIONS = {("GET", "/api/admin/catalog"), ("GET", "/api/admin/catalog/forms"), ("GET", "/api/admin/sectors"), ("GET", "/api/admin/users"), ("GET", "/api/admin/users/{user_id}"),
                             ("GET", "/api/admin/users/{user_id}/grants"), ("POST", "/api/admin/users/{user_id}/grants/grant"), ("GET", "/api/admin/users/{user_id}/grants/history"),
                             ("POST", "/api/admin/users/{user_id}/grants/revoke"), ("GET", "/api/admin/users/{user_id}/sectors"), ("POST", "/api/admin/users/{user_id}/sectors/grant"),
                             ("POST", "/api/admin/users/{user_id}/sectors/revoke")}
EXPECTED_OPERATIONS = EXPECTED_ADMIN_OPERATIONS | {("POST", "/api/auth/login"), ("POST", "/api/auth/logout"), ("GET", "/api/auth/me"), ("POST", "/api/captures"), ("POST", "/api/bobbins"),
                                                   ("GET", "/api/production/machines"), ("GET", "/api/quality/machine-forms"), ("GET", "/api/quality/bobbin-forms"),
                                                   ("POST", "/api/assignments/activate"), ("POST", "/api/work-orders")}


def flat_routes(routes):
    """Rutas HTTP planas (con `dependant`) recorriendo los routers incluidos. Desde FastAPI 0.142 `app.routes` contiene objetos `_IncludedRouter` SIN `dependant` (el router real está en
    `original_router`): iterar solo `app.routes` inspecciona únicamente las rutas definidas directamente en la aplicación (aquí, /health y /api/health)."""
    for route in routes:
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from flat_routes(inner.routes)
        elif hasattr(route, "dependant"):
            yield route
        elif getattr(route, "routes", None):
            yield from flat_routes(route.routes)


def inspected_operations(routes):
    return {(method, route.path) for route in routes for method in route.methods if method not in ("HEAD", "OPTIONS")}


def openapi_operations(application):
    return {(method.upper(), path) for path, operations in application.openapi()["paths"].items() for method in operations if method in HTTP_METHODS}


def assert_audit_is_complete(routes, application):
    """Falla si la auditoría NO inspeccionó todas las operaciones publicadas en OpenAPI y las rutas esperadas: una auditoría que recorre menos rutas de las que existen no demuestra nada."""
    inspected = inspected_operations(routes)
    missing = sorted(openapi_operations(application) - inspected)
    if missing:
        raise AssertionError(f"la auditoría no inspeccionó {len(missing)} operaciones de OpenAPI, p. ej. {missing[:3]}")
    absent = sorted(EXPECTED_OPERATIONS - inspected)
    if absent:
        raise AssertionError(f"la auditoría no inspeccionó rutas esperadas: {absent[:3]}")
    if len(inspected) < 38:
        raise AssertionError(f"la auditoría solo inspeccionó {len(inspected)} operaciones")


def connection_kinds(dependant):
    found = set()
    for dependency in dependant.dependencies:
        if getattr(dependency.call, "__name__", "") in ("get_connection", "get_identity_connection"):
            found.add(dependency.call.__name__)
        found |= connection_kinds(dependency)
    return found


def connection_problems(routes):
    """Reglas de MF-13-01D.3B.2: las rutas de administración usan la conexión de identidad (además de la de negocio para resolver la sesión); login SOLO la de identidad; `/auth/me` y el resto
    del negocio SOLO la de negocio; ninguna otra ruta pide la de identidad."""
    problems = []
    for route in routes:
        path, used = route.path, connection_kinds(route.dependant)
        if path.startswith("/api/admin") and used != {"get_identity_connection", "get_connection"}:
            problems.append((path, "administración: se esperaba identidad + sesión de negocio", sorted(used)))
        elif path == "/api/auth/login" and used != {"get_identity_connection"}:
            problems.append((path, "login: solo identidad", sorted(used)))
        elif path not in ("/api/auth/login",) and not path.startswith("/api/admin") and "get_identity_connection" in used:
            problems.append((path, "una ruta de negocio pide la conexión de identidad", sorted(used)))
        elif path == "/api/auth/me" and used != {"get_connection"}:
            problems.append((path, "/auth/me: solo negocio", sorted(used)))
    return problems


class RouteAuditCoverageTests(unittest.TestCase):
    def test_the_audit_inspects_every_published_operation_and_the_expected_routes(self):
        routes = list(flat_routes(app.routes))
        assert_audit_is_complete(routes, app)
        inspected = inspected_operations(routes)
        self.assertTrue(EXPECTED_ADMIN_OPERATIONS <= inspected)
        self.assertGreaterEqual(len(inspected), 38)

    def test_the_audit_fails_when_it_walks_fewer_routes_than_exist(self):
        """Regresión del defecto: iterar solo `app.routes` ve únicamente las rutas directas de la aplicación."""
        naive = [route for route in app.routes if hasattr(route, "dependant")]
        self.assertLess(len(inspected_operations(naive)), 5)
        with self.assertRaisesRegex(AssertionError, "no inspeccionó"):
            assert_audit_is_complete(naive, app)
        without_admin = [route for route in flat_routes(app.routes) if not route.path.startswith("/api/admin")]
        with self.assertRaisesRegex(AssertionError, "no inspeccionó"):
            assert_audit_is_complete(without_admin, app)

    def test_the_connection_rules_hold_for_every_real_route_and_detect_a_wrong_wiring(self):
        routes = list(flat_routes(app.routes))
        self.assertEqual(connection_problems(routes), [])
        by_path = {route.path: connection_kinds(route.dependant) for route in routes}
        self.assertEqual(by_path["/api/auth/login"], {"get_identity_connection"})
        self.assertEqual(by_path["/api/auth/me"], {"get_connection"})
        self.assertEqual(by_path["/api/admin/users"], {"get_identity_connection", "get_connection"})
        self.assertEqual(by_path["/api/captures"], {"get_connection"})

        class Fake:  # una ruta de negocio cableada por error a la conexión de identidad
            path = "/api/captures"
            methods = {"POST"}

            class dependant:  # noqa: N801
                class _Dep:
                    call = get_identity_connection
                    dependencies = []
                dependencies = [_Dep]
        self.assertTrue(connection_problems([Fake]))



# ---- scripts del corte: archivos ---------------------------------------------------------------------------------------------------------------------------
RUNBOOK = BACKEND.parent / "docs/MF-13-RELEASE-unico-procedimiento.md"
FIRST_INSTALL_ORDER = ("user-and-dirs", "preflight-build-deps", "install-node-runtime", "checkout", "python-venv", "install-frontend-artifact", "preflight-startup", "activate",
                       "postgres-up", "postgres-bootstrap-db", "postgres-roles", "migrate", "postgres-grants", "import-reference", "import-reference-apply", "systemd-install", "healthcheck")


def runbook_rows(heading):
    text = RUNBOOK.read_text(encoding="utf-8")
    start = text.index(heading)
    end = text.find("\n## ", start + 5)
    rows = {}
    for line in text[start:end if end > 0 else None].splitlines():
        if line.startswith("|") and not re.match(r"^\|[\s:|-]+\|$", line):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            key = cells[0].strip("* ")
            if re.fullmatch(r"[AB][0-9]+", key):
                rows[key] = cells
    return rows


def first_positions(text, names):
    positions = []
    for name in names:
        match = re.search(rf"`{re.escape(name)}(?:[ `<])", text)
        positions.append(match.start() if match else -1)
    return positions


class ReleaseProcedureOrderTests(unittest.TestCase):
    """El procedimiento del release distingue la primera instalación (los recursos del MVP aún no existen) de la actualización, con un orden ejecutable para cada una."""

    def test_the_first_installation_follows_the_real_phase_order_of_deploy_sh(self):
        rows = runbook_rows("## 5.")
        self.assertEqual(sorted(rows, key=lambda k: int(k[1:])), [f"A{i}" for i in range(11)])
        steps = " ".join(rows[f"A{i}"][1] for i in range(11))
        positions = first_positions(steps, FIRST_INSTALL_ORDER)
        self.assertNotIn(-1, positions, dict(zip(FIRST_INSTALL_ORDER, positions)))
        self.assertEqual(positions, sorted(positions))  # el orden de README/deploy.sh: código, luego PostgreSQL, luego roles, esquema, privilegios, servicios y salud
        deploy = (BACKEND.parent / "deploy/mvp/scripts/deploy.sh").read_text(encoding="utf-8")
        labels = set(re.findall(r"^  ([a-z][a-z-]+)\)", deploy, re.M))
        self.assertTrue(set(FIRST_INSTALL_ORDER) <= labels, set(FIRST_INSTALL_ORDER) - labels)  # todas las fases nombradas existen de verdad

    def test_the_first_installation_asks_for_nothing_that_does_not_exist_yet(self):
        rows = runbook_rows("## 5.")
        for key in ("A0", "A1"):  # aún no hay contenedor, base ni roles, ni servicios que comprobar
            joined = " ".join(rows[key])
            self.assertNotIn("08_release_preflight", joined, key)
            self.assertNotIn("backup.sh", joined, key)
        self.assertNotIn("healthcheck", rows["A1"][1] + rows["A2"][1] + rows["A3"][1])  # la primera salud es DESPUÉS de systemd-install
        self.assertLess(" ".join(rows[f"A{i}"][1] for i in range(11)).index("`systemd-install`"), " ".join(rows[f"A{i}"][1] for i in range(11)).index("`healthcheck`"))
        self.assertIn("08_release_preflight", " ".join(rows["A2"]))  # primer momento en que existen los roles
        self.assertIn("TVC_BACKUP_CONFIRMED", " ".join(rows["A0"]) + " ".join(rows["A2"]))
        self.assertIn("backup.sh create-and-verify", " ".join(rows["A3"]))  # recién entonces hay datos del MVP que respaldar

    def test_the_update_requires_the_baseline_health_and_backup_before_changing_anything(self):
        rows = runbook_rows("## 6.")
        self.assertEqual(sorted(rows, key=lambda k: int(k[1:])), [f"B{i}" for i in range(9)])
        b0 = " ".join(rows["B0"])
        for required in ("backup.sh create-and-verify", "healthcheck", "08_release_preflight", "preflight", "TVC"):
            self.assertIn(required, b0)
        self.assertIn("checkout", rows["B1"][1])  # el código nuevo va DESPUÉS del punto de partida
        self.assertIn("rollback.sh version", rows["B1"][3])

    def test_both_scenarios_keep_the_independent_approval_the_rollback_order_and_the_tvc_protection(self):
        for heading, cut, approval, backup_before_cut in (("## 5.", "A8", "A7", "A6"), ("## 6.", "B6", "B5", "B4")):
            rows = runbook_rows(heading)
            self.assertIn("aprobación independiente", " ".join(rows[approval]).lower())
            self.assertIn("03d_d3b4_cut_identity_dml.sql", " ".join(rows[cut]))
            self.assertIn("ANTES de tocar `IDENTITY_DATABASE_URL`", rows[cut][3])  # ROLLBACK_D3B4 antes de quitar la variable
            self.assertIn("respaldo", " ".join(rows[backup_before_cut]).lower())  # punto de restauración previo al corte
            self.assertLess(int(approval[1:]), int(cut[1:]))  # la aprobación va antes del corte
            for key, cells in rows.items():
                self.assertTrue(cells[-1].strip(), f"{key}: falta la reversión")
        text = RUNBOOK.read_text(encoding="utf-8")
        for required in ("Estado mixto", "postgres-vinto", "assert_container_is_ours", "TVC_BACKUP_CONFIRMED"):
            self.assertIn(required, text)
        self.assertIn("No existe un entorno QA persistente separado", text)
        self.assertNotRegex(text, r"\bC[0-9]\b")  # sin restos de la numeración antigua de puntos de control


class CutScriptFilesTests(unittest.TestCase):
    def test_the_cut_statements_are_exactly_the_approved_prototype_phase(self):
        prototype = [re.sub(r"\s+", " ", s.replace("__BUSINESS__", "vinto_app").replace("__IDENTITY__", "vinto_identity")) for s in d3b.proposal_phases()["D3B4"] if not s.startswith("DO")]
        script = [re.sub(r"\s+", " ", s) for s in d1.sql_statements(CUT) if re.match(r"(REVOKE|GRANT)\b", s)]
        self.assertEqual(script, prototype)

    def test_the_rollback_statements_are_the_approved_rollback_plus_the_exact_column_cleanup(self):
        prototype = [re.sub(r"\s+", " ", s.replace("__BUSINESS__", "vinto_app")) for s in d3b.proposal_phases()["ROLLBACK_D3B4"]]
        script = [re.sub(r"\s+", " ", s) for s in d1.sql_statements(CUT_ROLLBACK) if re.match(r"GRANT\b", s)]
        self.assertEqual(script, prototype)
        revokes = [s for s in d1.sql_statements(CUT_ROLLBACK) if s.upper().startswith("REVOKE")]
        self.assertTrue(revokes and all("(" in s for s in revokes))  # solo retira los privilegios de COLUMNA que concedió el corte

    def test_the_scripts_are_transactional_guarded_and_touch_nothing_but_privileges(self):
        for path in (CUT, CUT_ROLLBACK, PREFLIGHT):
            text = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("--"))
            with self.subTest(script=path.name):
                self.assertNotRegex(text, r"(?i)\b(DROP\s|TRUNCATE|DELETE\s+FROM|INSERT\s+INTO|UPDATE\s+vinto_|ALTER\s+TABLE|ALTER\s+ROLE|CREATE\s+ROLE)")
                if path is not PREFLIGHT:
                    self.assertRegex(text, r"(?m)^BEGIN;$")
                    self.assertRegex(text, r"(?m)^COMMIT;$")
                    self.assertIn("lock_timeout", text)
                self.assertIn("ON_ERROR_STOP", text)
        self.assertNotRegex("\n".join(l for l in PREFLIGHT.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("--")), r"(?i)\b(GRANT|REVOKE)\b")  # solo lectura

    def test_membership_checks_never_rely_on_usage_alone(self):
        """pg_has_role(..., 'USAGE') no ve una membresía INHERIT FALSE, SET TRUE (SET ROLE sí funciona). Cada guarda usa MEMBER; el corte además comprueba USAGE y SET de forma explícita."""
        for path in (ROLES / "03b_d3b1_restrict_catalog_writes.sql", ROLES / "03c_d3b2_identity_role_grants.sql", PREFLIGHT):
            code = "\n".join(l for l in path.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("--"))
            with self.subTest(script=path.name):
                self.assertNotIn("'USAGE'", code.replace("GRANT USAGE", ""))  # (los GRANT USAGE ON SCHEMA son privilegios de esquema, no membresías)
                self.assertIn("'MEMBER'", code)
        cut = "\n".join(l for l in CUT.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("--"))
        for required in ("'MEMBER'", "'SET'", "server_version_num", "pg_auth_members", "member of other roles", "CREATEROLE"):
            self.assertIn(required, cut)

    def test_the_cut_requires_the_independent_approval_and_the_rollback_does_not(self):
        self.assertIn("vinto.d3b4_approval", CUT.read_text(encoding="utf-8"))
        self.assertIn(APPROVAL, CUT.read_text(encoding="utf-8"))
        self.assertNotIn("d3b4_approval", CUT_ROLLBACK.read_text(encoding="utf-8"))

    def test_the_deployment_never_executes_the_cut_its_rollback_or_the_preflight(self):
        deploy = (BACKEND.parent / "deploy/mvp/scripts/deploy.sh").read_text(encoding="utf-8")
        for line in deploy.splitlines():
            if ("pg_run_sql_" in line or "for step in" in line) and not line.lstrip().startswith("#"):
                self.assertNotRegex(line, r"(?i)03d|ROLLBACK_D3B4|08_release|d3b4")

    def test_the_readme_orders_03d_after_03c_and_documents_the_gate(self):
        readme = (ROLES / "README.md").read_text(encoding="utf-8")
        names = [m.group(2) for m in re.finditer(r"^\| ([0-9]+[a-z]?) \| `([^`]+)`", readme, re.M)]
        self.assertEqual(names[names.index("03c_d3b2_identity_role_grants.sql") + 1], "03d_d3b4_cut_identity_dml.sql")
        for required in ("ROLLBACK_D3B4", "d3b4_compliant", "08_release_preflight.sql", "vinto.d3b4_approval", "ANTES de quitar `IDENTITY_DATABASE_URL`"):
            self.assertIn(required, readme)


# ---- la puerta ---------------------------------------------------------------------------------------------------------------------------------------------

class TwoRoleGateTests(d1.D3B1Case):
    """Una sola prueba larga con la secuencia completa: el informe de evidencia necesita todos los estados."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.passwords = {role: "pw-" + secrets.token_urlsafe(12) for role in (self.business, self.identity)}
        for role, password in self.passwords.items():
            self.connection.execute(f"ALTER ROLE {role} LOGIN PASSWORD '{password}'")
        self.url = {role: make_conninfo(database_url(self.database), user=role, password=password) for role, password in self.passwords.items()}
        self.log = []
        real = psycopg.connect

        def recording(conninfo="", *args, **kwargs):
            self.log.append(conninfo_to_dict(conninfo).get("user") if isinstance(conninfo, str) else None)
            return real(conninfo, *args, **kwargs)
        recorder = patch.object(psycopg, "connect", recording)
        recorder.start()
        self.addCleanup(recorder.stop)
        self.report = Report()
        self.ctx = {}

    # ---- aplicar los scripts reales (como superusuario, equivalente al propietario) ----
    def run_script(self, path, **extra):
        d1.run(self.connection, d1.sql_statements(path, app=self.business, identity=self.identity, reference=self.reference))

    def cut(self, approval=APPROVAL):
        self.connection.execute(f"SET vinto.d3b4_approval = '{approval}'")
        try:
            self.run_script(CUT)
        finally:
            self.connection.execute("RESET vinto.d3b4_approval")

    def acls(self):
        return {role: d1.acl_snapshot(self.connection, role) for role in (self.business, self.identity, self.reference)}

    def blocked(self, state, name, function, pattern):
        before = self.acls()
        with self.report.guard(state, name):
            try:
                function()
            except psycopg.errors.RaiseException as error:
                self.report.check(state, name, re.search(pattern, str(error)) and self.acls() == before, f"mensaje inesperado o cambios: {error}")
            else:
                self.report.check(state, name, False, "el script no abortó")

    # ---- modos de configuración de la aplicación ----
    @contextlib.contextmanager
    def mode(self, dedicated):
        patches = [patch.object(settings, "database_url", SecretStr(self.url[self.business])),
                   patch.object(settings, "identity_database_url", SecretStr(self.url[self.identity]) if dedicated else None),
                   patch.object(settings, "test_database_url", SecretStr(self.url[self.business])),
                   patch.object(settings, "identity_test_database_url", SecretStr(self.url[self.identity]) if dedicated else None)]
        with contextlib.ExitStack() as stack:
            for item in patches:
                stack.enter_context(item)
            yield

    def used_since(self, mark):
        return {user for user in self.log[mark:] if user in (self.business, self.identity)}

    def actors_since(self, since, tables):
        return {r[0] for r in self.connection.execute(
            "SELECT DISTINCT database_actor FROM vinto_audit.audit_event WHERE entity_table = ANY(%s) AND occurred_at >= %s", (list(tables), since)).fetchall()}

    def new_user(self, profile, prefix, sectors=("BOBINAS",)):
        password = "pw-" + secrets.token_urlsafe(12)
        created = create_user(self.connection, username=f"{prefix}.{uuid4().hex[:8]}", display_name=prefix, profile_code=profile, password=password, sectors=sectors)
        return created, password

    # ---- comprobaciones ----
    async def api_matrix(self, state, dedicated):
        identity_role = self.identity if dedicated else self.business
        with self.mode(dedicated):
            admin, admin_password = self.new_user("DATA_BALTREK", "gate.admin")
            operator, operator_password = self.new_user("OPERACION", "gate.op")
            target = self.new_user("OPERACION", "gate.target")[0].user_id
            with self.report.guard(state, "login/me/logout y rol usado por cada ruta"):
                mark = len(self.log)
                login = await asg.call("POST", "/api/auth/login", json_body={"username": admin.username, "password": admin_password})
                cookie = login.set_cookie_value()
                self.report.check(state, "login 200 con la conexión esperada", login.status == 200 and cookie and self.used_since(mark) == {identity_role}, (login.status, self.used_since(mark)))
                mark = len(self.log)
                me = await asg.call("GET", "/api/auth/me", cookie=cookie)
                self.report.check(state, "/api/auth/me 200 siempre con el rol de negocio", me.status == 200 and self.used_since(mark) == {self.business}, (me.status, self.used_since(mark)))
                since = self.connection.execute("SELECT clock_timestamp()").fetchone()[0]
                headers = [("origin", ORIGIN)]
                statuses = []
                for path, body in (("sectors/grant", {"sector_code": "REBOBINADO"}), ("sectors/revoke", {"sector_code": "REBOBINADO"}),
                                   ("grants/grant", {"machine_code": "MP1", "form_code": "VINTO-P1-03"}), ("grants/revoke", {"machine_code": "MP1", "form_code": "VINTO-P1-03"})):
                    reply = await asg.call("POST", f"/api/admin/users/{target}/{path}", json_body=body, cookie=cookie, extra_headers=headers)
                    statuses.append((path, reply.status))
                detail = await asg.call("GET", f"/api/admin/users/{target}/grants", cookie=cookie)
                self.report.check(state, "administración: conceder y revocar sector y máquina-formulario (200)", all(s == 200 for _, s in statuses) and detail.status == 200, statuses)
                self.report.check(state, "auditoría: la escritura administrativa la hizo el rol esperado",
                                  self.actors_since(since, ("user_sector", "user_machine_form_grant")) == {identity_role}, self.actors_since(since, ("user_sector", "user_machine_form_grant")))
                operator_cookie = (await asg.call("POST", "/api/auth/login", json_body={"username": operator.username, "password": operator_password})).set_cookie_value()
                no_session = await asg.call("POST", f"/api/admin/users/{target}/sectors/grant", json_body={"sector_code": "REBOBINADO"}, extra_headers=headers)
                no_permission = await asg.call("POST", f"/api/admin/users/{target}/sectors/grant", json_body={"sector_code": "REBOBINADO"}, cookie=operator_cookie, extra_headers=headers)
                self.report.check(state, "la administración sigue exigiendo sesión (401) y user.manage (403)", (no_session.status, no_permission.status) == (401, 403), (no_session.status, no_permission.status))
                mark = len(self.log)
                logout = await asg.call("POST", "/api/auth/logout", cookie=cookie, extra_headers=headers)
                used_by_logout = self.used_since(mark)  # ANTES de la comprobación posterior con /me, que usa el rol de negocio
                after = await asg.call("GET", "/api/auth/me", cookie=cookie)
                self.report.check(state, "logout 204 con la conexión esperada y la sesión queda revocada", (logout.status, after.status) == (204, 401) and used_by_logout == {identity_role}, (logout.status, after.status, used_by_logout))

    def cli_matrix(self, state, dedicated):
        identity_role = self.identity if dedicated else self.business
        with self.mode(dedicated), self.report.guard(state, "CLI create_user y manage_user"):
            actor, actor_password = self.new_user("DATA_BALTREK", "gate.cliadmin")  # creado por el superusuario de la prueba: ANTES de medir la atribución
            since = self.connection.execute("SELECT clock_timestamp()").fetchone()[0]
            username = f"gate.cli.{uuid4().hex[:8]}"
            out = io.StringIO()
            with patch.dict(os.environ, {"GATE_CLI_PW": "pw-" + uuid4().hex}), contextlib.redirect_stdout(out):
                code = create_user_cli.main(["--target", "test", "--username", username, "--display-name", "CLI", "--profile", "OPERACION", "--sector", "BOBINAS", "--password-env", "GATE_CLI_PW"])
            self.report.check(state, "CLI create_user (exit 0)", code == 0, out.getvalue())
            with patch.dict(os.environ, {"GATE_ACTOR_PW": actor_password}), contextlib.redirect_stdout(out):
                code = manage_user_cli.main(["--target", "test", "--action", "deactivate", "--username", username, "--actor-username", actor.username,
                                             "--actor-password-env", "GATE_ACTOR_PW", "--reason", "d3b3 gate", "--yes"])
            active = self.connection.execute('SELECT active FROM vinto_master."user" u JOIN vinto_auth.credential c ON c.user_id = u.id WHERE lower(c.username) = %s', (username.lower(),)).fetchone()
            self.report.check(state, "CLI manage_user desactiva al usuario (exit 0)", code == 0 and active == (False,), out.getvalue())
            actors = self.actors_since(since, ("user", "user_profile", "user_sector"))
            self.report.check(state, "auditoría: ambos CLI escriben con el rol esperado", actors == {identity_role}, actors)

    async def captures(self, state, operations):
        for user in (self.operator, self.quality_user):  # las comprobaciones de concurrencia revocan el sector a propósito: cada ronda de capturas parte con el sector concedido
            grant_sector(self.connection, user_id=user, sector_code="BOBINAS", actor_id=self.admin)
        for op in operations:
            with self.report.guard(state, f"captura {op} en enforce con el rol de negocio"):
                user, runner, _ = await self.target(op)
                results = []
                thread = self.threaded(runner, results, role=self.business)
                thread.start()
                thread.join(60)
                self.report.check(state, f"captura {op} en enforce con el rol de negocio", results and getattr(results[0], "created", False), results)

    async def concurrency(self, state, operations):
        for op in operations:
            with self.report.guard(state, f"revocación de sector espera a la captura {op} (identidad vs negocio)"):
                grant_sector(self.connection, user_id=self.operator, sector_code="BOBINAS", actor_id=self.admin)
                grant_sector(self.connection, user_id=self.quality_user, sector_code="BOBINAS", actor_id=self.admin)
                user, runner, _ = await self.target(op)
                inside, release, captured = threading.Event(), threading.Event(), []
                real = cs._resolve_device

                def paused(connection, device_key, machine_id, _real=real):
                    inside.set()
                    release.wait(30)
                    return _real(connection, device_key, machine_id)
                with patch.object(cs, "_resolve_device", paused):
                    capture = self.threaded(runner, captured, role=self.business)
                    capture.start()
                    self.assertTrue(inside.wait(20))
                    revoker, revoked = self.revoke(user, role=self.identity)
                    revoker.start()
                    revoker.join(1.0)
                    waited = revoker.is_alive()
                    release.set()
                    capture.join(30)
                    revoker.join(30)
                denied = False
                try:
                    runner(self.connection)
                except AuthorizationDenied:
                    denied = True
                self.report.check(state, f"revocación de sector espera a la captura {op} (identidad vs negocio) y la siguiente se deniega",
                                  waited and captured and getattr(captured[0], "created", False) and revoked == [True] and denied, (waited, captured, revoked, denied))
        with self.report.guard(state, "administrador desactivado/revocado concurrentemente"):
            admin1 = self.users["DATA_BALTREK"][0]
            admin2, _ = self.new_user("DATA_BALTREK", "gate.admin2")
            target = self.new_user("OPERACION", "gate.t")[0].user_id
            inside, release, outcome = threading.Event(), threading.Event(), []

            def in_flight():
                conn = connect(self.database)
                try:
                    conn.execute(f"SET ROLE {self.identity}")
                    with conn.transaction():
                        require_actor_authorized(conn, admin2.user_id)
                        inside.set()
                        release.wait(30)
                finally:
                    conn.close()

            def deactivation():
                conn = connect(self.database)
                try:
                    conn.execute(f"SET ROLE {self.identity}")
                    outcome.append(deactivate_user(conn, username=admin2.username, actor_username=admin1.username, reason="d3b3 gate").changed)
                finally:
                    conn.close()
            writer, deactivator = threading.Thread(target=in_flight), threading.Thread(target=deactivation)
            writer.start()
            self.assertTrue(inside.wait(20))
            deactivator.start()
            deactivator.join(1.5)
            waited = deactivator.is_alive()
            release.set()
            writer.join(30)
            deactivator.join(30)
            conn = connect(self.database)
            try:
                conn.execute(f"SET ROLE {self.identity}")
                try:
                    admin_service.change_grant(conn, operation="grant", user_id=target, sector_code="REBOBINADO", actor_id=admin2.user_id)
                    rejected = False
                except ActorNotAuthorized:
                    rejected = True
            finally:
                conn.close()
            self.report.check(state, "una desactivación espera a la escritura administrativa en curso y la siguiente se rechaza", waited and outcome == [True] and rejected, (waited, outcome, rejected))

    def separation(self, state):
        with self.report.guard(state, "current_user distinto entre las conexiones de negocio e identidad"):
            seen = {}
            for role in (self.business, self.identity):
                with psycopg.connect(self.url[role]) as conn:
                    seen[role] = conn.execute("SELECT current_user, session_user").fetchone()
            self.report.check(state, "current_user distinto entre las conexiones de negocio e identidad",
                              seen[self.business] == (self.business, self.business) and seen[self.identity] == (self.identity, self.identity) and self.business != self.identity, seen)

    def business_identity_writes(self, state, expect_denied):
        with self.report.guard(state, "el rol de negocio frente a escrituras de identidad"):
            results = {name: self.try_as(self.business, sql) for name, sql in self.ATTACKS.items()}
            identity_attacks = ("grant", "sector", "admin_profile", "password_hash", "forged_session", "user_active", "sector_delete")
            denied = all(results[name] == "privilege" for name in identity_attacks)
            allowed = all(results[name] == "allowed" for name in identity_attacks)
            self.report.check(state, "el rol de negocio no puede modificar identidad (42501)" if expect_denied else "antes del corte el rol de negocio conserva el DML de identidad (comportamiento anterior)",
                              denied if expect_denied else allowed, results)
            hash_read = self.try_as(self.business, "SELECT password_hash FROM vinto_auth.credential")
            self.report.check(state, "el rol de negocio no lee el hash de contraseña tras el corte" if expect_denied else "antes del corte el hash es legible por el rol de negocio",
                              (hash_read == "privilege") if expect_denied else (hash_read == "allowed"), hash_read)

    def route_audit(self):
        state = "S0"
        with self.report.guard(state, "auditoría de rutas: inspecciona todas las operaciones publicadas"):
            routes = list(flat_routes(app.routes))
            assert_audit_is_complete(routes, app)  # falla si la auditoría no recorre de verdad las rutas esperadas
            self.report.check(state, "auditoría de rutas: inspecciona todas las operaciones publicadas", True, len(inspected_operations(routes)))
            problems = connection_problems(routes)
            self.report.check(state, "auditoría estática de rutas: qué conexión usa cada ruta", not problems, problems)
            writers = d2.WiringTests("test_identity_connections_are_only_requested_from_the_identity_entry_points")
            self.report.check(state, "solo las rutas de identidad piden la conexión de identidad", writers.run().wasSuccessful())

    def preflight(self):
        statement = next(s for s in d1.sql_statements(PREFLIGHT, app=self.business, identity=self.identity) if "ready_for_d3b4" in s)
        cursor = self.connection.execute(statement)
        return dict(zip([d.name for d in cursor.description], cursor.fetchone()))

    # ---- la secuencia ----
    async def test_the_full_two_role_gate(self):
        """Una excepción no controlada en cualquier paso NO pierde la evidencia: se registra como comprobación fallida (RECHAZADA) y el informe se escribe siempre."""
        try:
            await self.sequence()
        except BaseException as error:  # noqa: BLE001
            self.report.check("GATE", "la secuencia terminó sin una excepción no controlada", False, f"{type(error).__name__}: {error}")
        self.finish()

    async def sequence(self):
        r, state_acls = self.report, {}
        self.route_audit()

        # S0 · estado inicial (solo 02/03 reales): comportamiento anterior, sin la variable
        state_acls["S0"] = self.acls()
        flags = self.preflight()
        r.check("S0", "preflight: nada aplicado, vinto_app ni superusuario ni propietario", flags["vinto_app_no_es_superusuario_ni_propietario"] and not flags["d3b1_aplicado"] and not flags["d3b4_aplicado"]
                and flags["ready_for_d3b1"] and not flags["ready_for_d3b4"], flags)
        self.blocked("S0", "el corte aborta si D.3B.1 y D.3B.2 no están aplicados", self.cut, r"D\.3B\.1 is not applied")
        await self.api_matrix("S0", dedicated=False)
        self.cli_matrix("S0", dedicated=False)
        await self.captures("S0", sync.OPERATIONS)
        self.business_identity_writes("S0", expect_denied=False)

        # S1 · D.3B.1
        self.run_script(d1.APPLY)
        flags = self.preflight()
        r.check("S1", "preflight tras D.3B.1", flags["d3b1_aplicado"] and not flags["ready_for_d3b1"] and not flags["ready_for_d3b4"], flags)
        self.blocked("S1", "el corte aborta mientras el rol de identidad no tiene sus privilegios", self.cut, r"vinto_identity cannot connect|identity role lacks")
        await self.api_matrix("S1", dedicated=False)
        await self.captures("S1", ("central",))

        # S2 · D.3B.2
        self.run_script(d2.GRANTS)
        state_acls["S2"] = self.acls()
        flags = self.preflight()
        r.check("S2", "preflight tras D.3B.2: listo para el corte", flags["d3b2_privilegios_completos"] and flags["ready_for_d3b4"] and not flags["d3b4_aplicado"], flags)
        self.blocked("S2", "el corte aborta sin la aprobación independiente", lambda: self.cut(approval="yes"), r"independent approval missing")
        if int(self.connection.execute("SHOW server_version_num").fetchone()[0]) >= 160000:
            self.connection.execute(f"GRANT {self.identity} TO {self.business} WITH INHERIT FALSE, SET TRUE")
            checks = self.connection.execute("SELECT pg_has_role(%(a)s, %(i)s, 'USAGE'), pg_has_role(%(a)s, %(i)s, 'MEMBER'), pg_has_role(%(a)s, %(i)s, 'SET')", {"a": self.business, "i": self.identity}).fetchone()
            r.check("S2", "premisa: con INHERIT FALSE, SET TRUE la comprobación USAGE no ve la membresía pero MEMBER y SET sí", checks == (False, True, True), checks)
            self.blocked("S2", "el corte aborta con una membresía INHERIT FALSE, SET TRUE de vinto_app en vinto_identity (ACL intactas)", self.cut, r"member of other roles")
            flags = self.preflight()
            r.check("S2", "preflight: con esa membresía no está listo para el corte", not flags["ready_for_d3b4"] and not flags["vinto_app_sin_membresias_ni_atributos_peligrosos"], flags)
            self.connection.execute(f"REVOKE {self.identity} FROM {self.business}")
            flags = self.preflight()
            r.check("S2", "preflight: retirada la membresía vuelve a estar listo", flags["ready_for_d3b4"] and flags["vinto_app_sin_membresias_ni_atributos_peligrosos"], flags)
        for dedicated in (False, True):
            await self.api_matrix("S2", dedicated=dedicated)
        self.cli_matrix("S2", dedicated=True)
        self.separation("S2")
        await self.captures("S2", sync.OPERATIONS)
        await self.concurrency("S2", ("central",))
        self.business_identity_writes("S2", expect_denied=False)

        # S3 · D.3B.4, el corte (solo en esta base efímera)
        before_cut = self.acls()
        with r.guard("S3", "aplicar el corte con aprobación"):
            self.cut()
        after_first_cut = self.acls()
        with r.guard("S3", "el corte es idempotente (misma ACL tras repetirlo)"):
            self.cut()
            r.check("S3", "el corte es idempotente (misma ACL tras repetirlo)", self.acls() == after_first_cut)
        state_acls["S3"] = self.acls()
        r.check("S3", "el corte no cambia nada al rol de identidad ni al de referencia", state_acls["S3"][self.identity] == before_cut[self.identity] and state_acls["S3"][self.reference] == before_cut[self.reference])
        with r.guard("S3", "matriz de privilegios del rol de negocio tras el corte = la aprobada"):
            matrix = d3b.matrix(self.connection, self.business)
            r.check("S3", "matriz de privilegios del rol de negocio tras el corte = la aprobada", matrix["vinto_auth.credential"] == ";s=(user_id,username,must_change)" and matrix["vinto_auth.session"] == "S;u=(last_seen_at)"
                    and matrix["vinto_master.user_sector"] == "S" and matrix["vinto_auth.auth_event"] == "" and matrix["vinto_master.user"] == "S;u=(updated_at)"
                    and matrix["vinto_master.user_machine_form_grant"] == "S;u=(updated_at)" and matrix["vinto_audit.audit_event"] == "I", matrix)
        flags = self.preflight()
        r.check("S3", "preflight tras el corte", flags["d3b4_aplicado"] and flags["d3b1_aplicado"] and not flags["ready_for_d3b4"], flags)
        drift = self.drift_d3b4()
        r.check("S3", "07: d3b4_compliant = true en las 7 tablas", len(drift) == 7 and all(drift.values()), drift)
        self.separation("S3")
        self.business_identity_writes("S3", expect_denied=True)
        await self.api_matrix("S3", dedicated=True)
        self.cli_matrix("S3", dedicated=True)
        await self.captures("S3", sync.OPERATIONS)
        await self.concurrency("S3", sync.OPERATIONS)
        with r.guard("S3", "orden prohibido: sin IDENTITY_DATABASE_URL el login falla tras el corte"):
            with self.mode(dedicated=False):
                created, password = self.new_user("OPERACION", "gate.noidn")
                sessions = self.connection.execute("SELECT count(*) FROM vinto_auth.session").fetchone()[0]
                login = await asg.call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
                r.check("S3", "orden prohibido: sin IDENTITY_DATABASE_URL el login falla tras el corte (sin crear sesión)",
                        login.status >= 500 and self.connection.execute("SELECT count(*) FROM vinto_auth.session").fetchone()[0] == sessions, login.status)

        # S4 · ROLLBACK_D3B4: restaura el acceso ANTES de quitar IDENTITY_DATABASE_URL
        self.run_script(CUT_ROLLBACK)
        state_acls["S4"] = self.acls()
        r.check("S4", "ROLLBACK_D3B4 restaura la ACL EXACTA anterior al corte", state_acls["S4"][self.business] == before_cut[self.business] and state_acls["S4"][self.identity] == before_cut[self.identity], "ACL distinta")
        with r.guard("S4", "ROLLBACK_D3B4 es idempotente"):
            self.run_script(CUT_ROLLBACK)
            r.check("S4", "ROLLBACK_D3B4 es idempotente", self.acls() == state_acls["S4"])
        drift = self.drift_d3b4()
        r.check("S4", "07: d3b4_compliant = false en todas tras la reversión", len(drift) == 7 and not any(drift.values()), drift)
        self.business_identity_writes("S4", expect_denied=False)
        for dedicated in (True, False):  # primero con la variable (ambos roles administran) y DESPUÉS sin ella (rol único)
            await self.api_matrix("S4", dedicated=dedicated)
        self.cli_matrix("S4", dedicated=False)
        await self.captures("S4", ("central", "quality_machine"))

        # S5 · ROLLBACK_D3B2 y S6 · ROLLBACK_D3B1: vuelta al estado inicial
        self.run_script(d2.ROLLBACK)
        r.check("S5", "ROLLBACK_D3B2 deja a vinto_identity sin privilegios", d1.acl_snapshot(self.connection, self.identity) == set())
        await self.api_matrix("S5", dedicated=False)
        self.run_script(d1.ROLLBACK)
        r.check("S6", "ROLLBACK_D3B1: la ACL de negocio, identidad y referencia vuelve EXACTAMENTE al estado inicial", self.acls() == state_acls["S0"], "ACL distinta del estado inicial")
        await self.api_matrix("S6", dedicated=False)
        self.business_identity_writes("S6", expect_denied=False)

    def drift_d3b4(self):
        statement = next(s for s in d1.sql_statements(d1.VERIFICATION, app=self.business) if "d3b4_compliant" in s)
        cursor = self.connection.execute(statement)
        return {row[0]: row[-1] for row in cursor.fetchall()}

    def finish(self):
        number = int(self.connection.execute("SHOW server_version_num").fetchone()[0])
        version = self.connection.execute("SHOW server_version").fetchone()[0]
        commit = os.environ.get("GITHUB_SHA") or "local"
        document = self.report.document(number, version, commit)
        directory = os.environ.get("D3B3_EVIDENCE_DIR")
        if directory:
            Path(directory).mkdir(parents=True, exist_ok=True)
            (Path(directory) / "d3b3-gate-evidence.json").write_text(json.dumps(document, indent=2, ensure_ascii=False), encoding="utf-8")
            (Path(directory) / "d3b3-gate-evidence.md").write_text(Report.markdown(document), encoding="utf-8")
        text = json.dumps(document) + Report.markdown(document)
        for secret in list(self.passwords.values()) + list(self.url.values()):
            self.assertNotIn(secret, text)
        if os.environ.get("D3B3_REQUIRE_PG17") == "1":
            self.assertEqual(number // 10000, 17, "la puerta D.3B.3 exige PostgreSQL 17")
        failed = [c for c in document["checks"] if not c["ok"]]
        self.assertEqual(document["verdict"], "APROBADA", failed)
        self.assertGreaterEqual(document["checks_total"], 60)

class MembershipGuardTests(d1.D3B1Case):
    """PostgreSQL 16+ distingue USAGE (heredar privilegios), SET (SET ROLE) y MEMBER (cualquier membresía). Una membresía `INHERIT FALSE, SET TRUE` da USAGE = false y aun así permite
    SET ROLE: el corte debe abortar SIN modificar ninguna ACL, y el preflight debe reflejar el mismo criterio."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        if int(self.connection.execute("SHOW server_version_num").fetchone()[0]) < 160000:
            self.skipTest("las opciones INHERIT/SET de GRANT ... TO solo existen desde PostgreSQL 16")
        self.migrator = f"d3b3_mig_{uuid4().hex[:6]}"
        self.connection.execute(f"CREATE ROLE {self.migrator} NOLOGIN")
        self.addCleanup(lambda: self.connection.execute(f"DROP ROLE IF EXISTS {self.migrator}"))
        self.apply_script(d1.APPLY)
        self.apply_script(d2.GRANTS)

    def apply_script(self, path):
        d1.run(self.connection, d1.sql_statements(path, app=self.business, identity=self.identity, reference=self.reference, migrator=self.migrator))

    def acls(self):
        return {role: d1.acl_snapshot(self.connection, role) for role in (self.business, self.identity, self.reference, self.migrator)}

    def attempt_cut(self):
        self.connection.execute(f"SET vinto.d3b4_approval = '{APPROVAL}'")
        try:
            self.apply_script(CUT)
        finally:
            self.connection.execute("RESET vinto.d3b4_approval")

    def assert_cut_blocked(self, pattern):
        before = self.acls()
        with self.assertRaisesRegex(psycopg.errors.RaiseException, pattern):
            self.attempt_cut()
        self.assertEqual(self.acls(), before)  # abortó sin modificar NINGUNA ACL
        self.assertTrue(self.can_administer(self.business))

    def preflight(self):
        statement = next(s for s in d1.sql_statements(PREFLIGHT, app=self.business, identity=self.identity, reference=self.reference, migrator=self.migrator) if "ready_for_d3b4" in s)
        cursor = self.connection.execute(statement)
        return dict(zip([d.name for d in cursor.description], cursor.fetchone()))

    def grant(self, role, member, options):
        self.connection.execute(f"GRANT {role} TO {member} WITH {options}")

    def new_role(self, prefix):
        name = f"d3b3_{prefix}_{uuid4().hex[:6]}"
        self.connection.execute(f"CREATE ROLE {name} NOLOGIN")
        self.addCleanup(lambda: self.connection.execute(f"DROP ROLE IF EXISTS {name}"))
        return name

    async def test_the_old_usage_check_missed_this_membership_and_the_new_guard_does_not(self):
        self.grant(self.identity, self.business, "INHERIT FALSE, SET TRUE")
        usage, member, set_ = self.connection.execute("SELECT pg_has_role(%(a)s, %(i)s, 'USAGE'), pg_has_role(%(a)s, %(i)s, 'MEMBER'), pg_has_role(%(a)s, %(i)s, 'SET')",
                                                      {"a": self.business, "i": self.identity}).fetchone()
        self.assertEqual((usage, member, set_), (False, True, True))  # la premisa del defecto: USAGE no la ve
        self.assert_cut_blocked("member of other roles")

    async def test_every_kind_of_membership_of_vinto_app_blocks_the_cut_without_changing_any_acl(self):
        other = self.new_role("other")
        for options in ("INHERIT FALSE, SET TRUE", "INHERIT TRUE, SET FALSE", "INHERIT TRUE, SET TRUE", "ADMIN TRUE, INHERIT FALSE, SET FALSE"):
            with self.subTest(options=options):
                self.grant(other, self.business, options)
                self.assert_cut_blocked("member of other roles")
                self.connection.execute(f"REVOKE {other} FROM {self.business}")

    async def test_vinto_app_that_can_assume_the_identity_the_migrator_or_an_owner_blocks_the_cut(self):
        owner = self.new_role("owner")
        original = self.connection.execute("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'vinto_auth.session'::regclass").fetchone()[0]
        self.connection.execute(f"ALTER TABLE vinto_auth.session OWNER TO {owner}")
        self.addCleanup(lambda: self.connection.execute(f'ALTER TABLE vinto_auth.session OWNER TO "{original}"'))
        for target in (self.identity, self.migrator, owner):
            with self.subTest(target=target):
                self.grant(target, self.business, "INHERIT FALSE, SET TRUE")
                self.assert_cut_blocked("member of other roles")
                self.connection.execute(f"REVOKE {target} FROM {self.business}")

    async def test_vinto_identity_that_can_assume_vinto_app_the_migrator_or_an_owner_blocks_the_cut(self):
        owner = self.new_role("owner")
        original = self.connection.execute("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'vinto_auth.session'::regclass").fetchone()[0]
        self.connection.execute(f"ALTER TABLE vinto_auth.session OWNER TO {owner}")
        self.addCleanup(lambda: self.connection.execute(f'ALTER TABLE vinto_auth.session OWNER TO "{original}"'))
        for target, pattern in ((self.business, "members of each other"), (self.migrator, "can assume the role"), (owner, "owns, or can assume")):
            with self.subTest(target=target):
                self.grant(target, self.identity, "INHERIT FALSE, SET TRUE")
                self.assert_cut_blocked(pattern)
                self.connection.execute(f"REVOKE {target} FROM {self.identity}")

    async def test_dangerous_attributes_of_vinto_app_block_the_cut(self):
        for attribute in ("CREATEROLE", "CREATEDB", "BYPASSRLS", "REPLICATION"):
            with self.subTest(attribute=attribute):
                self.connection.execute(f"ALTER ROLE {self.business} {attribute}")
                self.assert_cut_blocked("must not have CREATEROLE")
                self.connection.execute(f"ALTER ROLE {self.business} NO{attribute}")

    async def test_without_any_membership_the_same_cut_succeeds(self):
        """Control positivo: la guarda no es demasiado estricta; retiradas las membresías el corte se aplica y se verifica."""
        other = self.new_role("other")
        self.grant(other, self.business, "INHERIT FALSE, SET TRUE")
        self.assert_cut_blocked("member of other roles")
        self.connection.execute(f"REVOKE {other} FROM {self.business}")
        self.attempt_cut()
        self.assertEqual((self.can_administer(self.business), self.can_administer(self.identity)), (False, True))

    async def test_the_preflight_reflects_the_same_criterion(self):
        baseline = self.preflight()
        self.assertTrue(baseline["ready_for_d3b4"] and baseline["vinto_app_sin_membresias_ni_atributos_peligrosos"] and baseline["vinto_identity_sin_atributos_peligrosos"], baseline)
        other = self.new_role("other")
        self.grant(other, self.business, "INHERIT FALSE, SET TRUE")
        flags = self.preflight()
        self.assertFalse(flags["ready_for_d3b4"] or flags["vinto_app_sin_membresias_ni_atributos_peligrosos"], flags)
        self.connection.execute(f"REVOKE {other} FROM {self.business}")
        self.grant(self.migrator, self.identity, "INHERIT FALSE, SET TRUE")
        flags = self.preflight()
        self.assertFalse(flags["ready_for_d3b4"] or flags["vinto_identity_sin_atributos_peligrosos"], flags)
        self.connection.execute(f"REVOKE {self.migrator} FROM {self.identity}")
        owner = self.new_role("owner")
        original = self.connection.execute("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'vinto_master.sector'::regclass").fetchone()[0]
        self.connection.execute(f"ALTER TABLE vinto_master.sector OWNER TO {owner}")
        self.addCleanup(lambda: self.connection.execute(f'ALTER TABLE vinto_master.sector OWNER TO "{original}"'))
        self.grant(owner, self.business, "INHERIT FALSE, SET TRUE")
        flags = self.preflight()
        self.assertFalse(flags["ready_for_d3b4"] or flags["ready_for_d3b1"] or flags["vinto_app_no_es_superusuario_ni_propietario"], flags)

    async def test_the_earlier_phases_also_refuse_an_owner_reachable_only_through_set(self):
        for script, role_key, pattern in ((d1.APPLY, "business", "member of the owner"), (d2.GRANTS, "identity", "member of the owner")):
            with self.subTest(script=script.name):
                owner = self.new_role("owner")
                original = self.connection.execute("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'vinto_master.sector'::regclass").fetchone()[0]
                self.connection.execute(f"ALTER TABLE vinto_master.sector OWNER TO {owner}")
                member = self.business if role_key == "business" else self.identity
                self.grant(owner, member, "INHERIT FALSE, SET TRUE")
                before = self.acls()
                try:
                    with self.assertRaisesRegex(psycopg.errors.RaiseException, pattern):
                        self.apply_script(script)
                    self.assertEqual(self.acls(), before)
                finally:
                    self.connection.execute(f"REVOKE {owner} FROM {member}")
                    self.connection.execute(f'ALTER TABLE vinto_master.sector OWNER TO "{original}"')


class GateRejectsAnIncorrectCutTests(d1.D3B1Case):
    """Mutantes del corte: la puerta debe RECHAZAR un corte que dejaría el sistema sin poder administrar o sin motor de bloqueos."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.apply_script(d1.APPLY)
        self.apply_script(d2.GRANTS)

    def apply_script(self, path):
        d1.run(self.connection, d1.sql_statements(path, app=self.business, identity=self.identity, reference=self.reference))

    def cut(self, path=None):
        self.connection.execute(f"SET vinto.d3b4_approval = '{APPROVAL}'")
        try:
            d1.run(self.connection, d1.sql_statements(path or CUT, app=self.business, identity=self.identity))
        finally:
            self.connection.execute("RESET vinto.d3b4_approval")

    async def test_the_cut_leaves_exactly_the_business_privileges_the_application_needs(self):
        self.cut()
        self.assertEqual((self.can_administer(self.business), self.can_administer(self.identity)), (False, True))
        for sql in ("SELECT user_id, username, must_change FROM vinto_auth.credential", "UPDATE vinto_auth.session SET last_seen_at = clock_timestamp() WHERE false",
                    "SELECT 1 FROM vinto_master.user_profile FOR SHARE", "SELECT 1 FROM vinto_master.user_machine_form_grant FOR SHARE", "SELECT 1 FROM vinto_master.profile FOR SHARE"):
            self.assertEqual(self.try_as(self.business, sql), "allowed", sql)
        for sql in ("UPDATE vinto_auth.session SET revoked_at = now()", "UPDATE vinto_auth.session SET expires_at = now() + interval '9 years'", "INSERT INTO vinto_auth.auth_event (user_id, event) VALUES (gen_random_uuid(), 'x')",
                    "SELECT password_hash FROM vinto_auth.credential", "SELECT * FROM vinto_auth.credential", "SELECT 1 FROM vinto_auth.auth_event"):
            self.assertEqual(self.try_as(self.business, sql, claim_admin=False), "privilege", sql)

    async def test_a_cut_without_the_lock_privileges_would_be_detected_by_its_own_verification(self):
        broken = CUT.read_text(encoding="utf-8").replace("GRANT UPDATE (updated_at) ON vinto_master.\"user\", vinto_master.user_profile, vinto_master.user_machine_form_grant TO vinto_app;", "")
        self.assertNotEqual(broken, CUT.read_text(encoding="utf-8"))
        directory = tempfile.mkdtemp(prefix="d3b3_")
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)
        path = Path(directory) / "broken_cut.sql"
        path.write_text(broken, encoding="utf-8")
        before = d1.acl_snapshot(self.connection, self.business)
        with self.assertRaisesRegex(psycopg.errors.RaiseException, "unexpected UPDATE privilege|row locks"):
            self.cut(path)
        self.assertEqual(d1.acl_snapshot(self.connection, self.business), before)  # la verificación abortó la transacción: nada cambió

    async def test_the_cut_never_revokes_before_the_identity_role_is_verified(self):
        self.apply_script(d2.ROLLBACK)
        before = d1.acl_snapshot(self.connection, self.business)
        with self.assertRaisesRegex(psycopg.errors.RaiseException, "cannot connect|lacks"):
            self.cut()
        self.assertEqual(d1.acl_snapshot(self.connection, self.business), before)
        self.assertTrue(self.can_administer(self.business))

    async def test_the_cut_refuses_when_the_roles_are_the_same_or_the_application_role_is_an_owner(self):
        with self.assertRaisesRegex(psycopg.errors.RaiseException, "does not exist|same|members"):
            self.connection.execute(f"SET vinto.d3b4_approval = '{APPROVAL}'")
            try:
                d1.run(self.connection, d1.sql_statements(CUT, app=self.business, identity=self.business))
            finally:
                self.connection.execute("RESET vinto.d3b4_approval")
        owner = self.connection.execute("SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'vinto_auth.session'::regclass").fetchone()[0]
        self.connection.execute(f"ALTER TABLE vinto_auth.session OWNER TO {self.business}")
        self.addCleanup(lambda: self.connection.execute(f'ALTER TABLE vinto_auth.session OWNER TO "{owner}"'))
        with self.assertRaisesRegex(psycopg.errors.RaiseException, "owns"):
            self.cut()

    async def test_re_running_03_alone_after_the_cut_restores_the_dml_and_the_drift_query_and_the_guard_query_see_it(self):
        self.cut()
        statement = next(s for s in d1.sql_statements(d1.VERIFICATION, app=self.business) if "d3b4_compliant" in s)
        self.assertTrue(all(row[-1] for row in self.connection.execute(statement).fetchall()))
        for sql in d3b.baseline_statements(self.business):  # re-aprovisionamiento SIN 03d
            self.connection.execute(sql)
        self.assertFalse(any(row[-1] for row in self.connection.execute(statement).fetchall()))
        guard = self.connection.execute(d1.deploy_guard_query(self.business)).fetchone()[0].split(" ")
        self.assertEqual(guard, ["0", "0"])  # 03 deshizo AMBAS fases: la consulta de 07 es la que lo detecta (deploy.sh lo bloquea ANTES de que 03 corra)
        self.apply_script(d1.APPLY)  # el procedimiento correcto: 03, luego 03b, luego 03d
        self.cut()
        guard = self.connection.execute(d1.deploy_guard_query(self.business)).fetchone()[0].split(" ")
        self.assertEqual(guard, ["3", "6"])  # con el corte aplicado, deploy.sh detecta D.3B.1 (3) y D.3B.4 (6) y bloquearía postgres-grants

    async def test_the_guard_query_does_not_flag_a_first_time_provisioning(self):
        fresh = f"d3b3_fresh_{uuid4().hex[:6]}"
        self.connection.execute(f"CREATE ROLE {fresh} NOLOGIN")
        self.addCleanup(lambda: self.connection.execute(f"DROP ROLE IF EXISTS {fresh}"))
        self.assertEqual(self.connection.execute(d1.deploy_guard_query(fresh)).fetchone()[0], "0 0")  # rol creado, 03 aún no ejecutado
        self.assertEqual(self.connection.execute(d1.deploy_guard_query(f"d3b3_absent_{uuid4().hex[:6]}")).fetchone()[0], "0 0")


if __name__ == "__main__":
    unittest.main()
