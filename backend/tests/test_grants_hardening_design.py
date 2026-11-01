"""MF-13-01D.3B: auditoría de privilegios y prueba de VIABILIDAD de la separación de roles (no se aplica nada real).

Se construye en PostgreSQL 17 aislado el rol de aplicación ACTUAL (privilegios de backend/roles/03_table_grants.sql + la 0007) y, sobre copias suyas, el diseño propuesto en
backend/roles/proposals/D3B_split_identity_role.sql: un rol de NEGOCIO sin DML sobre identidad y autorización y un rol de IDENTIDAD/ADMINISTRACIÓN. Se demuestra:
  1. la matriz de privilegios efectivos y la exposición actual (un SQL directo con el rol actual puede darse el perfil de administrador, forjar una sesión, cambiar un hash...);
  2. que con el diseño propuesto el rol de negocio ya no puede nada de eso, y SÍ puede seguir ejecutando las cuatro capturas con el motor en enforce, resolver sesiones y bloquear las filas del motor;
  3. que el rol de identidad conserva el flujo legítimo (concesiones, sectores, usuarios, login) y la sincronización de MF-13-01D.3A frente a las capturas del rol de negocio;
  4. la plantilla de endurecimiento de funciones SECURITY DEFINER (por si una fase posterior las adopta) y sus límites.
Los tests no cambian ningún privilegio real: los roles son temporales y se eliminan al terminar.
"""

import ast
import hashlib
import re
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg

from app import capture_service as cs
from app.auth.grants import grant_sector, revoke_sector
from app.auth.machine_form_grants import grant_machine_form, revoke_machine_form
from app.auth.service import create_user
from app.auth.sessions import create_session, login_with_session, resolve_session
from app.authz import authorize
from app.authz.policies import Operation
from app.ephemeral_db import build_reference_template, connect, drop_database

try:
    import test_f3_bobbins_api as f3
    import test_sector_revocation_sync as sync
except ModuleNotFoundError:
    import tests.test_f3_bobbins_api as f3
    import tests.test_sector_revocation_sync as sync

BACKEND = Path(__file__).resolve().parent.parent
PROPOSAL = BACKEND / "roles/proposals/D3B_split_identity_role.sql"
SENSITIVE = ("vinto_master.user", "vinto_master.user_profile", "vinto_master.profile", "vinto_master.user_sector", "vinto_master.user_machine_form_grant",
             "vinto_master.machine", "vinto_master.sector", "vinto_auth.credential", "vinto_auth.session", "vinto_auth.auth_event", "vinto_audit.audit_event")
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_d3b_tpl")
    f3.STATE["template"] = STATE["template"]


def tearDownModule():
    drop_database(STATE["template"])


def baseline_statements(role):
    """Los privilegios ACTUALES de vinto_app (roles/02, 03, 04 y la 0007), traducidos al rol de prueba."""
    roles_dir = BACKEND / "roles"
    tables = (roles_dir / "03_table_grants.sql").read_text(encoding="utf-8")
    section = tables[tables.index("-- ===== vinto_app"):tables.index("-- ===== vinto_reference")]
    statements = [s for s in "\n".join(l for l in section.splitlines() if not l.lstrip().startswith(("--", "\\"))).split(";") if s.strip()]
    schema = re.search(r"GRANT USAGE ON SCHEMA [^;]+TO vinto_app;", (roles_dir / "02_schema_grants.sql").read_text(encoding="utf-8")).group(0)
    function = re.search(r"GRANT EXECUTE ON FUNCTION vinto_txn\.management_start_year\(date\) TO vinto_app;", (roles_dir / "04_function_grants.sql").read_text(encoding="utf-8")).group(0)
    grants_0007 = re.search(r'GRANT SELECT, INSERT, UPDATE ON vinto_master\."user_machine_form_grant" TO vinto_app;', (BACKEND / "migrations/0007_user_machine_form_grants.sql").read_text(encoding="utf-8")).group(0)
    return [s.replace("vinto_app", role) for s in [schema, function, grants_0007] + statements]


FORWARD_PHASES = ("D3B1", "D3B2", "D3B4")


def split_sql(text):
    """Separa sentencias por ';' respetando los bloques $tag$...$tag$ (la guarda del corte es un DO)."""
    statements, buffer, position, tag = [], [], 0, None
    while position < len(text):
        if tag:
            if text.startswith(tag, position):
                buffer.append(tag)
                position += len(tag)
                tag = None
                continue
        else:
            opening = re.match(r"\$\w*\$", text[position:])
            if opening:
                tag = opening.group(0)
                buffer.append(tag)
                position += len(tag)
                continue
            if text[position] == ";":
                statements.append("".join(buffer))
                buffer, position = [], position + 1
                continue
        buffer.append(text[position])
        position += 1
    statements.append("".join(buffer))
    return [s.strip() for s in statements if s.strip()]


def proposal_phases():
    """Sentencias del prototipo por fase (marcadores «-- @phase NOMBRE»); los comentarios se descartan."""
    phases, current = {}, None
    for line in PROPOSAL.read_text(encoding="utf-8").splitlines():
        marker = re.match(r"-- @phase (\w+)\s*$", line)
        if marker:
            current = marker.group(1)
            phases[current] = []
        elif current and not line.lstrip().startswith("--"):
            phases[current].append(re.sub(r"\s+--.*$", "", line))
    return {name: split_sql("\n".join(lines)) for name, lines in phases.items()}


def phase_statements(names, business, identity):
    phases = proposal_phases()
    return [s.replace("__BUSINESS__", business).replace("__IDENTITY__", identity) for name in names for s in phases[name]]


def proposal_statements(business, identity):
    return phase_statements(FORWARD_PHASES, business, identity)


def matrix(connection, role, tables=SENSITIVE):
    """Privilegios efectivos del rol: letras de tabla (S I U D T) y, si no tiene el de tabla, las columnas con ese privilegio (s= SELECT, u= UPDATE)."""
    result = {}
    for table in tables:
        schema, name = table.split(".")
        qualified = f'{schema}."{name}"'
        letters = "".join(letter for letter, priv in (("S", "SELECT"), ("I", "INSERT"), ("U", "UPDATE"), ("D", "DELETE"), ("T", "TRUNCATE"))
                          if connection.execute("SELECT has_table_privilege(%s, %s, %s)", (role, qualified, priv)).fetchone()[0])
        columns = []
        for kind, priv, table_letter in (("s", "SELECT", "S"), ("u", "UPDATE", "U")):
            if table_letter not in letters:
                cols = [r[0] for r in connection.execute(
                    "SELECT a.attname FROM pg_attribute a WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped AND has_column_privilege(%s, %s::regclass, a.attname, %s) ORDER BY a.attnum",
                    (qualified, role, qualified, priv)).fetchall()]
                if cols:
                    columns.append(f"{kind}=({','.join(cols)})")
        result[table] = letters + (";" + ";".join(columns) if columns else "")
    return result


def identity_flow(app, admin):
    """Flujo completo de autenticación y administración que hoy ejecuta la aplicación: crear usuario, conceder/revocar máquina-formulario y sector, login y resolución de sesión."""
    created = create_user(app, username=f"idn.{uuid4().hex[:8]}", display_name="Nuevo", profile_code="OPERACION", password="pw-" + uuid4().hex, sectors=("BOBINAS",))
    assert grant_machine_form(app, user_id=created.user_id, machine_code="MP1", form_code="VINTO-P1-06", actor_id=admin)
    assert not grant_machine_form(app, user_id=created.user_id, machine_code="MP1", form_code="VINTO-P1-06", actor_id=admin)  # idempotente
    assert revoke_machine_form(app, user_id=created.user_id, machine_code="MP1", form_code="VINTO-P1-06", actor_id=admin)
    assert grant_sector(app, user_id=created.user_id, sector_code="REBOBINADO", actor_id=admin)
    assert revoke_sector(app, user_id=created.user_id, sector_code="REBOBINADO", actor_id=admin)
    password = "pw-" + uuid4().hex
    other = create_user(app, username=f"idn2.{uuid4().hex[:8]}", display_name="Otro", profile_code="CALIDAD", password=password, sectors=("BOBINAS",))
    user, session = login_with_session(app, other.username, password)
    assert user.user_id == other.user_id and resolve_session(app, session.raw_token).user_id == other.user_id


class RolesCase(sync.SyncCase):
    FORWARD = FORWARD_PHASES  # fases del prototipo aplicadas al montar el caso; las pruebas de transición las aplican una a una

    async def asyncSetUp(self):
        await super().asyncSetUp()
        suffix = uuid4().hex[:6]
        self.current, self.business, self.identity = f"d3b_cur_{suffix}", f"d3b_biz_{suffix}", f"d3b_idn_{suffix}"
        for role in (self.current, self.business, self.identity):
            self.connection.execute(f"CREATE ROLE {role} NOLOGIN NOINHERIT")
            self.addCleanup(lambda r=role: (self.connection.execute(f"DROP OWNED BY {r}"), self.connection.execute(f"DROP ROLE IF EXISTS {r}")))
        for statement in baseline_statements(self.current) + baseline_statements(self.business):
            self.connection.execute(statement)
        for statement in phase_statements(self.FORWARD, self.business, self.identity):
            self.connection.execute(statement)
        self.victim = self.operator
        self.params = {"op": self.operator, "admin": self.admin, "sec": self.scalar("SELECT id FROM vinto_master.sector WHERE code = 'REBOBINADO'"),
                       "mp1": self.scalar("SELECT id FROM vinto_master.machine WHERE code = 'MP1'"), "form": self.scalar("SELECT id FROM vinto_config.form WHERE code = 'VINTO-P1-05'"),
                       "pa": self.scalar("SELECT id FROM vinto_master.profile WHERE code = 'DATA_BALTREK'"), "hash": hashlib.sha256(b"attacker-token").hexdigest()}

    def apply(self, *phases, business=None, identity=None):
        for statement in phase_statements(phases, business or self.business, identity or self.identity):
            self.connection.execute(statement)

    def can_administer(self, role):
        """True si el rol ejecuta el flujo completo de autenticación y administración; False si el único fallo es de privilegio."""
        app = connect(self.database)
        try:
            app.execute(f"SET ROLE {role}")
            identity_flow(app, self.admin)
            return True
        except psycopg.errors.InsufficientPrivilege:
            return False
        finally:
            app.close()

    ATTACKS = {
        "grant": "INSERT INTO vinto_master.user_machine_form_grant (user_id, machine_id, form_id) VALUES (%(op)s,%(mp1)s,%(form)s)",
        "sector": "INSERT INTO vinto_master.user_sector (user_id, sector_id) VALUES (%(op)s,%(sec)s)",
        "admin_profile": "INSERT INTO vinto_master.user_profile (user_id, profile_id) VALUES (%(op)s,%(pa)s)",
        "password_hash": "UPDATE vinto_auth.credential SET password_hash = password_hash WHERE user_id = %(admin)s",
        "forged_session": "INSERT INTO vinto_auth.session (user_id, token_hash, expires_at) VALUES (%(admin)s, %(hash)s, now() + interval '1 hour')",
        "user_active": "UPDATE vinto_master.\"user\" SET active = active WHERE id = %(admin)s",
        "profile_active": "UPDATE vinto_master.profile SET active = active WHERE id = %(pa)s",
        "sector_delete": "DELETE FROM vinto_master.user_sector WHERE user_id = %(op)s",
        "machine_update": "UPDATE vinto_master.machine SET active = active WHERE id = %(mp1)s",
    }

    def try_as(self, role, sql, claim_admin=True):
        """Ejecuta el SQL con el rol y devuelve 'allowed', 'privilege' (42501) o el SQLSTATE; siempre revierte."""
        try:
            with self.connection.transaction():
                self.connection.execute(f"SET LOCAL ROLE {role}")
                # con claim_admin el propio rol declara ser el administrador; sin él se limpia la variable (la conexión de prueba la trae fijada a nivel de sesión)
                self.connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(self.admin) if claim_admin else "",))
                self.connection.execute(sql, self.params)
                raise psycopg.Rollback()
        except psycopg.errors.InsufficientPrivilege:
            return "privilege"
        except psycopg.Error as error:
            return error.sqlstate
        return "allowed"


# ---- 1. exposición ACTUAL (caracterización: documenta el riesgo, no lo aprueba) ----------------------------------------------------------------------------------

class CurrentExposureTests(RolesCase):
    async def test_the_current_privilege_matrix_of_the_application_role(self):
        self.assertEqual(matrix(self.connection, self.current), {
            "vinto_master.user": "SIU", "vinto_master.user_profile": "SIU", "vinto_master.profile": "SIU", "vinto_master.user_sector": "SID",
            "vinto_master.user_machine_form_grant": "SIU", "vinto_master.machine": "SIU", "vinto_master.sector": "SIU", "vinto_auth.credential": "SIU",
            "vinto_auth.session": "SIU", "vinto_auth.auth_event": "I", "vinto_audit.audit_event": "I"})

    async def test_direct_sql_with_the_current_role_can_escalate_to_administrator_and_alter_grants(self):
        """EXPOSICIÓN: por eso endurecer SOLO la tabla de concesiones no basta; el diseño debe cerrar también identidad (perfiles, credenciales, sesiones)."""
        results = {name: self.try_as(self.current, sql) for name, sql in self.ATTACKS.items()}
        self.assertEqual(results, {name: "allowed" for name in self.ATTACKS})

    async def test_what_is_already_protected_today(self):
        for sql in ("DELETE FROM vinto_master.user_machine_form_grant", "TRUNCATE vinto_master.user_machine_form_grant", "UPDATE vinto_audit.audit_event SET reason = 'x'",
                    "TRUNCATE vinto_master.user_sector"):
            self.assertEqual(self.try_as(self.current, sql), "privilege", sql)  # historial de concesiones y auditoría: inmutables para el rol
        # la atribución, en cambio, la declara el propio rol: created_by lo valida contra vinto.actor_id, que el rol fija a voluntad
        attributed = ("INSERT INTO vinto_master.user_machine_form_grant (user_id, machine_id, form_id, created_by) VALUES (%(op)s,%(mp1)s,%(form)s,%(admin)s)")
        self.assertEqual(self.try_as(self.current, attributed), "allowed")
        self.assertEqual(self.try_as(self.current, attributed, claim_admin=False), "23514")  # sin declarar el actor, el trigger de guarda lo rechaza


# ---- 1b. inventario de quién escribe identidad y autorización (insumo del diseño; fija los consumidores) ----------------------------------------------------------

class WriteInventoryTests(unittest.TestCase):
    """Cualquier SQL nuevo que escriba identidad/autorización cambia este inventario y obliga a revisar a qué rol debe pertenecer (negocio o identidad) ANTES de separar privilegios."""

    STATEMENT = re.compile(r"(INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(vinto_(?:master|auth|audit))\.\"?(\w+)\"?")
    EXPECTED = {
        "vinto_master.user": {"INSERT": ["app/auth/service.py"], "UPDATE": ["app/auth/service.py"]},
        "vinto_master.user_profile": {"INSERT": ["app/auth/service.py"]},
        "vinto_master.user_sector": {"INSERT": ["app/auth/grants.py"], "DELETE": ["app/auth/grants.py"]},
        "vinto_master.user_machine_form_grant": {"INSERT": ["app/auth/machine_form_grants.py"], "UPDATE": ["app/auth/machine_form_grants.py"]},
        "vinto_auth.credential": {"INSERT": ["app/auth/service.py"], "UPDATE": ["app/auth/service.py"]},
        "vinto_auth.session": {"INSERT": ["app/auth/sessions.py"], "UPDATE": ["app/auth/service.py", "app/auth/sessions.py"]},
        "vinto_auth.auth_event": {"INSERT": ["app/auth/service.py", "app/auth/sessions.py"]},
    }

    def test_only_the_auth_modules_write_identity_and_authorisation_tables_and_nobody_writes_profiles_machines_or_sectors(self):
        found = {}
        for path in sorted((BACKEND / "app").rglob("*.py")):
            relative = str(path.relative_to(BACKEND)).replace("\\", "/")
            if "/seed/" in relative:
                continue
            for kind, schema, table in self.STATEMENT.findall(path.read_text(encoding="utf-8")):
                found.setdefault(f"{schema}.{table}", {}).setdefault(kind.split()[0].upper(), set()).add(relative)
        identity = {t: {k: sorted(v) for k, v in kinds.items()} for t, kinds in found.items() if t in self.EXPECTED or t in (
            "vinto_master.profile", "vinto_master.machine", "vinto_master.sector")}
        self.assertEqual(identity, self.EXPECTED)  # profile, machine y sector: ningún DML de la aplicación (solo vinto_reference los escribe)


# ---- 2. el diseño propuesto: matriz y rol de negocio ---------------------------------------------------------------------------------------------------------------

class ProposedMatrixTests(RolesCase):
    async def test_the_proposed_privilege_matrices(self):
        self.assertEqual(matrix(self.connection, self.business), {
            "vinto_master.user": "S;u=(updated_at)", "vinto_master.user_profile": "S;u=(updated_at)", "vinto_master.profile": "S;u=(updated_at)", "vinto_master.user_sector": "S",
            "vinto_master.user_machine_form_grant": "S;u=(updated_at)", "vinto_master.machine": "S;u=(updated_at)", "vinto_master.sector": "S;u=(updated_at)",
            "vinto_auth.credential": ";s=(user_id,username,must_change)", "vinto_auth.session": "S;u=(last_seen_at)", "vinto_auth.auth_event": "", "vinto_audit.audit_event": "I"})
        identity = matrix(self.connection, self.identity)
        self.assertEqual({k: identity[k] for k in ("vinto_master.user", "vinto_master.user_profile", "vinto_master.user_sector", "vinto_master.user_machine_form_grant",
                                                   "vinto_auth.credential", "vinto_auth.session", "vinto_auth.auth_event")},
                         {"vinto_master.user": "SIU", "vinto_master.user_profile": "SIU", "vinto_master.user_sector": "SID", "vinto_master.user_machine_form_grant": "SIU",
                          "vinto_auth.credential": "SIU", "vinto_auth.session": "SIU", "vinto_auth.auth_event": "SI"})
        self.assertEqual(identity["vinto_master.profile"], "S;u=(active,updated_at,updated_by)")

    async def test_the_business_role_can_no_longer_escalate_or_touch_grants(self):
        results = {name: self.try_as(self.business, sql) for name, sql in self.ATTACKS.items()}
        self.assertEqual(results, {name: "privilege" for name in self.ATTACKS})  # todo denegado por PRIVILEGIO (42501), no por un trigger que podría saltarse

    async def test_the_business_role_cannot_read_password_hashes(self):
        self.assertEqual(self.try_as(self.business, "SELECT password_hash FROM vinto_auth.credential"), "privilege")
        self.assertEqual(self.try_as(self.business, "SELECT user_id, username, must_change FROM vinto_auth.credential"), "allowed")

    async def test_the_column_privilege_that_enables_row_locks_cannot_alter_a_grant(self):
        """FOR SHARE exige UPDATE de al menos una columna; con UPDATE(updated_at) el motor bloquea la concesión, y el trigger de guarda rechaza cualquier cambio de una concesión activa que no sea revocarla."""
        grant_machine_form(self.connection, user_id=self.operator, machine_code="MP1", form_code="VINTO-P1-03", actor_id=self.admin)
        self.assertEqual(self.try_as(self.business, "SELECT id FROM vinto_master.user_machine_form_grant WHERE revoked_at IS NULL FOR SHARE"), "allowed")
        self.assertEqual(self.try_as(self.business, "UPDATE vinto_master.user_machine_form_grant SET updated_at = now() WHERE revoked_at IS NULL"), "23514")
        self.assertEqual(self.try_as(self.business, "UPDATE vinto_master.user_machine_form_grant SET revoked_at = now(), revoked_by = %(admin)s"), "privilege")

    async def test_sessions_can_still_be_resolved_but_not_created_or_altered_by_the_business_role(self):
        session = create_session(self.connection, self.operator)  # creada por el rol de identidad (aquí, el propietario)
        app = connect(self.database)
        self.addCleanup(app.close)
        app.execute(f"SET ROLE {self.business}")
        user = resolve_session(app, session.raw_token)  # UPDATE de last_seen_at por privilegio de columna + SELECT de columnas de credencial
        self.assertEqual(user.user_id, self.operator)
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            create_session(app, self.operator)
        with self.assertRaises(psycopg.errors.InsufficientPrivilege):
            app.execute("UPDATE vinto_auth.session SET revoked_at = NULL, expires_at = now() + interval '10 years'")


class AuditResidualRiskTests(RolesCase):
    """RIESGO RESIDUAL que el diseño NO elimina: los triggers de auditoría son SECURITY INVOKER, así que quien escribe necesita INSERT en la auditoría y puede AÑADIR eventos falsos (no modificarlos ni borrarlos)."""

    FORGED = ("INSERT INTO vinto_audit.audit_event (entity_schema, entity_table, entity_key, action, actor_id, database_actor, request_id, reason) "
              "VALUES ('vinto_master','user_machine_form_grant','{}'::jsonb,'INSERT',%(admin)s,'forged','forged','forged')")

    async def test_both_the_current_and_the_business_role_can_append_forged_audit_events_but_never_alter_history(self):
        for role in (self.current, self.business):
            with self.subTest(role=role):
                self.assertEqual(self.try_as(role, self.FORGED), "allowed")
                self.assertEqual(self.try_as(role, "UPDATE vinto_audit.audit_event SET reason = 'x'"), "privilege")
                self.assertEqual(self.try_as(role, "DELETE FROM vinto_audit.audit_event"), "privilege")
        self.assertEqual(self.try_as(self.identity, self.FORGED), "allowed")  # el rol de identidad también (por la misma razón)


# ---- 3. las cuatro capturas con el motor en enforce, con el rol de negocio del diseño -----------------------------------------------------------------------

class BusinessRoleCapturesTests(RolesCase):
    async def test_the_four_captures_run_in_enforce_with_the_proposed_business_role(self):
        for op in sync.OPERATIONS:
            with self.subTest(operation=op):
                user, run, _ = await self.target(op)
                results = []
                thread = self.threaded(run, results, role=self.business)
                thread.start()
                thread.join(60)
                self.assertTrue(results and getattr(results[0], "created", False), (op, results))

    async def test_the_engine_decisions_and_locks_work_with_the_proposed_business_role(self):
        from app.auth.service import AuthenticatedUser
        principal = AuthenticatedUser(self.operator, "u", "U", ("OPERACION",), frozenset(), False, frozenset({"BOBINAS"}))
        app = connect(self.database)
        self.addCleanup(app.close)
        app.execute(f"SET ROLE {self.business}")
        with app.transaction():
            decision = authorize(app, principal, Operation.PRODUCTION_CAPTURE, "MP1", "VINTO-P1-06", lock=True)  # FOR SHARE en usuario, perfiles, máquina+sector y concesión
        self.assertEqual((decision.allowed, decision.reason), (True, "ALLOWED"))

    async def test_sector_revocation_by_the_identity_role_still_waits_for_business_captures_and_denies_the_next(self):
        for op in sync.OPERATIONS:
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
                    capture = self.threaded(run, captured, role=self.business)  # la captura, con el rol de negocio
                    capture.start()
                    self.assertTrue(inside.wait(20))
                    revoker, revoked = self.revoke(user, role=self.identity)  # la revocación, con el rol de identidad
                    revoker.start()
                    revoker.join(1.0)
                    self.assertTrue(revoker.is_alive(), "la revocación (rol de identidad) debe esperar la captura (rol de negocio)")
                    release.set()
                    capture.join(30)
                    revoker.join(30)
                self.assertTrue(captured and getattr(captured[0], "created", False), captured)
                self.assertEqual(revoked, [True])
                from app.authz.errors import AuthorizationDenied
                with self.assertRaises(AuthorizationDenied):
                    run(self.connection)


# ---- 4. el flujo legítimo con el rol de identidad ----------------------------------------------------------------------------------------------------------------------

class IdentityRoleTests(RolesCase):
    async def test_the_identity_role_runs_the_administrative_and_authentication_flows(self):
        app = connect(self.database)
        self.addCleanup(app.close)
        app.execute(f"SET ROLE {self.identity}")
        identity_flow(app, self.admin)


# ---- 5. plantilla de endurecimiento de funciones SECURITY DEFINER (por si una fase posterior las adopta) ----------------------------------------------------------

class SecurityDefinerTemplateTests(RolesCase):
    """Cubre la parte «PUBLIC, search_path, propietario y privilegios» del encargo. NO añade autenticación: una función invocable por el rol de negocio no puede
    saber quién es el administrador (vinto.actor_id y los parámetros los fija el propio rol). Por eso no se adopta como mecanismo principal (ver el documento)."""

    TEMPLATE = """
        CREATE FUNCTION vinto_master.d3b_revoke_sector_checked(p_user uuid, p_sector text) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog AS $fn$
        DECLARE v_sector uuid; v_rows int;
        BEGIN
          SELECT id INTO v_sector FROM vinto_master.sector WHERE code = p_sector;
          IF v_sector IS NULL THEN RAISE EXCEPTION 'unknown sector' USING ERRCODE = 'P0002'; END IF;
          PERFORM 1 FROM vinto_master."user" WHERE id = p_user FOR NO KEY UPDATE;
          DELETE FROM vinto_master.user_sector WHERE user_id = p_user AND sector_id = v_sector;
          GET DIAGNOSTICS v_rows = ROW_COUNT;
          RETURN v_rows > 0;
        END $fn$"""

    def install(self):
        self.connection.execute(self.TEMPLATE)
        self.connection.execute("REVOKE ALL ON FUNCTION vinto_master.d3b_revoke_sector_checked(uuid, text) FROM PUBLIC")
        self.addCleanup(lambda: self.connection.execute("DROP FUNCTION IF EXISTS vinto_master.d3b_revoke_sector_checked(uuid, text)"))

    async def test_public_and_other_roles_cannot_execute_it_and_only_the_granted_role_can(self):
        self.install()
        self.assertFalse(self.connection.execute("SELECT has_function_privilege('public', 'vinto_master.d3b_revoke_sector_checked(uuid, text)', 'EXECUTE')").fetchone()[0])
        call = "SELECT vinto_master.d3b_revoke_sector_checked(%(op)s, 'BOBINAS')"
        self.assertEqual(self.try_as(self.business, call, claim_admin=False), "privilege")
        self.connection.execute(f"GRANT EXECUTE ON FUNCTION vinto_master.d3b_revoke_sector_checked(uuid, text) TO {self.identity}")
        self.assertEqual(self.try_as(self.identity, call), "allowed")

    async def test_it_runs_with_the_owners_rights_pinned_search_path_and_resists_name_hijacking(self):
        self.install()
        self.connection.execute(f"GRANT EXECUTE ON FUNCTION vinto_master.d3b_revoke_sector_checked(uuid, text) TO {self.identity}")
        self.assertEqual(self.connection.execute("SELECT prosecdef, proconfig FROM pg_proc WHERE proname = 'd3b_revoke_sector_checked'").fetchone(), (True, ["search_path=pg_catalog"]))
        # un rol sin DML sobre user_sector puede, a través de la función, hacer lo que la función hace (derechos del propietario)…
        self.assertEqual(self.matrix_letters(self.identity, "vinto_master.user_sector"), "SID")
        with self.connection.transaction():
            self.connection.execute(f"SET LOCAL ROLE {self.identity}")
            self.connection.execute("CREATE TEMP TABLE sector (id uuid, code text)")  # intento de suplantar nombres con objetos propios en pg_temp
            self.assertTrue(self.connection.execute("SELECT vinto_master.d3b_revoke_sector_checked(%(op)s, 'BOBINAS')", self.params).fetchone()[0])  # sigue operando sobre el esquema real
            raise psycopg.Rollback()

    def matrix_letters(self, role, table):
        return matrix(self.connection, role, (table,))[table]

    async def test_a_session_variable_or_a_parameter_cannot_make_the_database_trust_an_administrator(self):
        """Límite documentado: lo que el rol fije (vinto.actor_id) o pase por parámetro no demuestra quién es el administrador. Con rol compartido, la defensa real es NO darle al rol de negocio el DML ni la ejecución."""
        self.assertEqual(self.try_as(self.business, "SELECT set_config('vinto.actor_id', %(admin)s::text, true)", claim_admin=False), "allowed")  # fijar la variable es libre…
        self.assertEqual(self.try_as(self.business, "INSERT INTO vinto_master.user_machine_form_grant (user_id, machine_id, form_id, created_by) VALUES (%(op)s,%(mp1)s,%(form)s,%(admin)s)"), "privilege")  # …pero sin privilegio no sirve de nada


# ---- 6. fases: lo que D.3B.1 puede revocar sin cambios de código, transiciones y reversión ------------------------------------------------------------------------------

class PhaseD3B1Tests(RolesCase):
    """D.3B.1 retira SOLO privilegios sin consumidores. El rol de negocio sigue siendo el ÚNICO rol (no existe aún el de identidad): login, administración y capturas deben seguir funcionando con el código actual."""

    FORWARD = ("D3B1",)

    async def test_it_only_changes_profile_machine_and_sector(self):
        before, after = matrix(self.connection, self.current), matrix(self.connection, self.business)
        changed = {table for table in before if before[table] != after[table]}
        self.assertEqual(changed, {"vinto_master.profile", "vinto_master.machine", "vinto_master.sector"})
        for table in changed:
            self.assertEqual(after[table], "S;u=(updated_at)")
        self.assertEqual(after["vinto_auth.credential"], "SIU")  # el hash sigue legible: login lo necesita hasta D.3B.4

    async def test_the_single_role_still_runs_authentication_administration_and_the_four_captures(self):
        self.assertTrue(self.can_administer(self.business))
        for op in sync.OPERATIONS:
            with self.subTest(operation=op):
                user, run, _ = await self.target(op)
                results = []
                thread = self.threaded(run, results, role=self.business)
                thread.start()
                thread.join(60)
                self.assertTrue(results and getattr(results[0], "created", False), (op, results))

    async def test_it_does_not_yet_protect_against_escalation_only_against_profile_and_machine_writes(self):
        results = {name: self.try_as(self.business, sql) for name, sql in self.ATTACKS.items()}
        self.assertEqual({name for name, outcome in results.items() if outcome == "privilege"}, {"profile_active", "machine_update"})
        self.assertEqual({name for name, outcome in results.items() if outcome == "allowed"}, set(self.ATTACKS) - {"profile_active", "machine_update"})


class PhaseTransitionTests(RolesCase):
    """Cada estado intermedio del despliegue y de la reversión conserva al menos un rol que administra usuarios; el corte y la reversión están probados."""

    FORWARD = ()

    def administrators(self):
        return {"business": self.can_administer(self.business), "identity": self.can_administer(self.identity)}

    async def test_no_intermediate_state_leaves_nobody_able_to_administer(self):
        expected = [
            ("D3B1", {"business": True, "identity": False}),
            ("D3B2", {"business": True, "identity": True}),  # aditivo: ambos roles administran; aquí se puede desplegar y verificar el código
            ("D3B4", {"business": False, "identity": True}),  # corte: solo identidad
            ("ROLLBACK_D3B4", {"business": True, "identity": True}),  # reversión de privilegios: vuelve a poder el negocio ANTES de tocar la conexión
            ("ROLLBACK_D3B1", {"business": True, "identity": True}),
        ]
        for phase, administrators in expected:
            with self.subTest(after=phase):
                self.apply(phase)
                self.assertEqual(self.administrators(), administrators)
                self.assertTrue(any(administrators.values()))

    async def test_the_full_rollback_restores_the_current_business_privileges_and_the_single_role_connection_works(self):
        before = matrix(self.connection, self.current)
        self.apply("D3B1", "D3B2", "D3B4")
        self.assertNotEqual(matrix(self.connection, self.business), before)
        self.apply("ROLLBACK_D3B4", "ROLLBACK_D3B1")
        self.assertEqual(matrix(self.connection, self.business), before)  # misma matriz que el rol actual
        self.assertEqual({name: self.try_as(self.business, sql) for name, sql in self.ATTACKS.items()},
                         {name: self.try_as(self.current, sql) for name, sql in self.ATTACKS.items()})
        self.assertTrue(self.can_administer(self.business))  # rol único (IDENTITY_DATABASE_URL eliminada): login y administración operan

    async def test_the_cut_aborts_without_changes_when_the_identity_role_does_not_have_its_privileges_yet(self):
        self.apply("D3B1")
        before = matrix(self.connection, self.business)
        with self.assertRaisesRegex(psycopg.errors.RaiseException, "identity role lacks"):
            self.apply("D3B4")
        self.assertEqual(matrix(self.connection, self.business), before)
        self.assertTrue(self.can_administer(self.business))

    async def test_a_plan_that_cuts_before_the_identity_role_exists_is_blocked_by_the_script_itself(self):
        before = matrix(self.connection, self.business)
        with self.assertRaises(psycopg.errors.RaiseException):
            self.apply("D3B4", "D3B2", "D3B1")  # orden invertido: el corte va primero
        self.assertEqual(matrix(self.connection, self.business), before)

    async def test_the_cut_aborts_when_both_roles_are_the_same_role(self):
        before = matrix(self.connection, self.business)
        with self.assertRaisesRegex(psycopg.errors.RaiseException, "same role"):
            self.apply("D3B4", identity=self.business)
        self.assertEqual(matrix(self.connection, self.business), before)


# ---- 7. guarda del orden del plan: ninguna revocación antes de migrar sus consumidores ------------------------------------------------------------------------------

DOC = BACKEND.parent / "docs/MF-13-01D3B-endurecimiento-privilegios-concesiones.md"
PHASE_ORDER = ("D.3B.1", "D.3B.2", "D.3B.3", "D.3B.4", "D.3B.5")
REVOKING_PHASES = ("D.3B.1", "D.3B.4", "D.3B.5")  # D.3B.2 solo concede y D.3B.3 solo verifica
SQL_PHASE = {"D3B1": "D.3B.1", "D3B4": "D.3B.4"}
IDENTITY_ENTRY_POINTS = ("login_with_session", "revoke_session", "create_session", "authenticate", "create_user", "deactivate_user", "reactivate_user", "grant_sector",
                         "revoke_sector", "grant_machine_form", "revoke_machine_form", "resolve_session")


def doc_section(prefix):
    text = DOC.read_text(encoding="utf-8")
    start = text.index(prefix)
    following = [m.start() for m in re.finditer(r"^#{2,3} ", text[start + len(prefix):], re.M)]
    return text[start:start + len(prefix) + following[0]] if following else text[start:]


def table_rows(section):
    rows = []
    for line in section.splitlines():
        if line.startswith("|") and not re.match(r"^\|[\s:|-]+\|$", line):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows[1:]  # sin la cabecera


def revocation_plan():
    plan = []
    for cells in table_rows(doc_section("### 7.3")):
        plan.append({"table": re.search(r"`([^`]+)`", cells[0]).group(1).replace('"', ""), "privileges": cells[0].split("`")[2], "revoked": cells[1],
                     "consumers": re.findall(r"`([^`]+)`", cells[2]), "migrated": cells[3]})
    return plan


def plan_violations(plan):
    """Una revocación solo es válida si se ejecuta en una fase que revoca y TODOS sus consumidores migraron en una fase estrictamente anterior."""
    violations = []
    for row in plan:
        name = f"{row['table']} ({row['revoked']})"
        if row["revoked"] not in REVOKING_PHASES:
            violations.append(f"{name}: la fase no puede revocar")
        elif row["consumers"]:
            if row["migrated"] not in PHASE_ORDER:
                violations.append(f"{name}: tiene consumidores sin fase de migración")
            elif PHASE_ORDER.index(row["migrated"]) >= PHASE_ORDER.index(row["revoked"]):
                violations.append(f"{name}: se revoca antes (o a la vez) que se migran sus consumidores ({row['migrated']})")
    return violations


def revoked_tables(statements):
    tables = set()
    for statement in statements:
        match = re.match(r"REVOKE\s+(.+?)\s+ON\s+(.+?)\s+FROM\s", statement, re.S | re.I)
        if match:
            tables |= {name.strip().replace('"', "") for name in match.group(2).split(",")}
    return tables


class PhaseOrderGuardTests(unittest.TestCase):
    """Detecta una planificación donde los privilegios se revocan antes de migrar sus consumidores (y un documento que se aparte del código o del script)."""

    def test_the_documented_plan_never_revokes_before_its_consumers_migrate(self):
        plan = revocation_plan()
        self.assertGreaterEqual(len(plan), 11)
        self.assertEqual(plan_violations(plan), [])

    def test_the_guard_detects_a_plan_that_revokes_before_migrating(self):
        plan = revocation_plan()
        early = [dict(row, revoked="D.3B.1") if row["table"] == "vinto_auth.credential" else row for row in plan]  # la planificación original: el hash se revocaba en D.3B.1
        violations = plan_violations(early)
        self.assertEqual(len(violations), 2)
        self.assertTrue(all("vinto_auth.credential" in v and "antes" in v for v in violations))
        simultaneous = [dict(row, revoked="D.3B.2") if row["table"] == "vinto_master.user_sector" else row for row in plan]
        self.assertTrue(any("no puede revocar" in v for v in plan_violations(simultaneous)))  # D.3B.2 integra el código: no revoca
        same_phase = [dict(row, migrated="D.3B.4") if row["table"] == "vinto_auth.session" else row for row in plan]
        self.assertTrue(any("antes (o a la vez)" in v for v in plan_violations(same_phase)))
        unmigrated = [dict(row, migrated="—") if row["table"] == "vinto_auth.auth_event" else row for row in plan]
        self.assertTrue(any("sin fase de migración" in v for v in plan_violations(unmigrated)))

    def test_the_plan_matches_the_sql_prototype_phase_by_phase(self):
        phases, plan = proposal_phases(), revocation_plan()
        for sql_phase, doc_phase in SQL_PHASE.items():
            with self.subTest(phase=sql_phase):
                self.assertEqual(revoked_tables(phases[sql_phase]), {row["table"] for row in plan if row["revoked"] == doc_phase})
        for sql_phase in ("D3B2", "ROLLBACK_D3B4", "ROLLBACK_D3B1"):
            with self.subTest(phase=sql_phase):
                self.assertEqual(revoked_tables(phases[sql_phase]), set())  # solo conceden
                self.assertFalse(any(s.upper().startswith("REVOKE") for s in phases[sql_phase]))
        self.assertEqual([m.group(1) for m in re.finditer(r"^REVOKE\s+(.+?)\s+ON\s", " ".join(phases["D3B1"]), re.M | re.I)], ["INSERT, UPDATE"])

    def test_the_plan_matches_the_real_writers_of_each_table(self):
        plan = revocation_plan()
        for row in plan:
            with self.subTest(table=row["table"], phase=row["revoked"]):
                writers = WriteInventoryTests.EXPECTED.get(row["table"])
                if row["revoked"] == "D.3B.1":
                    self.assertIsNone(writers)  # sin consumidores de escritura en el código
                    self.assertEqual(row["consumers"], [])
                else:
                    expected = {module for modules in writers.values() for module in modules}
                    self.assertTrue(expected <= set(row["consumers"]), (expected, row["consumers"]))
                for module in row["consumers"]:
                    self.assertTrue((BACKEND / module).is_file(), module)
        credential_readers = {str(path.relative_to(BACKEND)).replace("\\", "/") for path in (BACKEND / "app").rglob("*.py")
                              if "password_hash" in path.read_text(encoding="utf-8") and re.search(r"(?:FROM|JOIN)\s+vinto_auth\.credential", path.read_text(encoding="utf-8"))}
        select_row = next(row for row in plan if row["table"] == "vinto_auth.credential" and "SELECT" in row["privileges"])
        self.assertTrue(credential_readers and credential_readers <= set(select_row["consumers"]), credential_readers)

    def test_the_d3b2_inventory_names_every_current_caller_of_the_identity_functions(self):
        section = doc_section("### 7.4")
        # referencia real en el código (AST), no solo llamada ni mención en un docstring: admin/service.py las elige con `action = grant_sector if … else revoke_sector`
        def references(path):
            names = set()
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Name):
                    names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    names.add(node.attr)
                elif isinstance(node, ast.ImportFrom):
                    names.update(alias.name for alias in node.names)
            return names & set(IDENTITY_ENTRY_POINTS)
        callers = set()
        for path in list((BACKEND / "app").rglob("*.py")) + sorted(BACKEND.glob("*.py")):
            relative = str(path.relative_to(BACKEND)).replace("\\", "/")
            if "/seed/" in relative or relative in ("migrate.py", "prepare_test_db.py", "import_reference.py", "authz_readiness.py", "candidate_report.py"):
                continue
            if references(path):
                callers.add(relative)
        self.assertTrue({"app/auth/router.py", "app/auth/dependencies.py", "app/admin/service.py", "manage_user.py", "create_user.py"} <= callers, callers)
        for relative in sorted(callers | {"app/admin/router.py"}):
            with self.subTest(consumer=relative):
                self.assertIn(f"`{relative}", section)
        for required in ("login", "logout", "resolve_session", "IDENTITY_DATABASE_URL", "app/admin/router.py", "manage_user.py", "create_user.py"):
            self.assertIn(required, section)

    def test_the_documented_transition_and_rollback_keep_access_in_every_step(self):
        transition = doc_section("### 7.5")
        self.assertRegex(transition, r"ausente o vac[ií]a.*comportamiento existente")
        self.assertIn("sin retroceso silencioso", transition)
        self.assertIn("el corte queda prohibido si falta cualquiera", transition)
        rollback = doc_section("### 7.6")
        self.assertLess(rollback.index("ROLLBACK_D3B4"), rollback.index("quitar `IDENTITY_DATABASE_URL`"))  # privilegios primero, conexión después
        self.assertIn("Prohibido", rollback)
        self.assertIn("No retirar privilegios al rol de identidad", rollback)


if __name__ == "__main__":
    unittest.main()
