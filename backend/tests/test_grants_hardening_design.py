"""MF-13-01D.3B: auditoría de privilegios y prueba de VIABILIDAD de la separación de roles (no se aplica nada real).

Se construye en PostgreSQL 17 aislado el rol de aplicación ACTUAL (privilegios de backend/roles/03_table_grants.sql + la 0007) y, sobre copias suyas, el diseño propuesto en
backend/roles/proposals/D3B_split_identity_role.sql: un rol de NEGOCIO sin DML sobre identidad y autorización y un rol de IDENTIDAD/ADMINISTRACIÓN. Se demuestra:
  1. la matriz de privilegios efectivos y la exposición actual (un SQL directo con el rol actual puede darse el perfil de administrador, forjar una sesión, cambiar un hash...);
  2. que con el diseño propuesto el rol de negocio ya no puede nada de eso, y SÍ puede seguir ejecutando las cuatro capturas con el motor en enforce, resolver sesiones y bloquear las filas del motor;
  3. que el rol de identidad conserva el flujo legítimo (concesiones, sectores, usuarios, login) y la sincronización de MF-13-01D.3A frente a las capturas del rol de negocio;
  4. la plantilla de endurecimiento de funciones SECURITY DEFINER (por si una fase posterior las adopta) y sus límites.
Los tests no cambian ningún privilegio real: los roles son temporales y se eliminan al terminar.
"""

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


def proposal_statements(business, identity):
    text = "\n".join(l for l in PROPOSAL.read_text(encoding="utf-8").splitlines() if not l.lstrip().startswith("--"))
    return [s.replace("__BUSINESS__", business).replace("__IDENTITY__", identity) for s in text.split(";") if s.strip()]


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


class RolesCase(sync.SyncCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        suffix = uuid4().hex[:6]
        self.current, self.business, self.identity = f"d3b_cur_{suffix}", f"d3b_biz_{suffix}", f"d3b_idn_{suffix}"
        for role in (self.current, self.business, self.identity):
            self.connection.execute(f"CREATE ROLE {role} NOLOGIN NOINHERIT")
            self.addCleanup(lambda r=role: (self.connection.execute(f"DROP OWNED BY {r}"), self.connection.execute(f"DROP ROLE IF EXISTS {r}")))
        for statement in baseline_statements(self.current) + baseline_statements(self.business):
            self.connection.execute(statement)
        for statement in proposal_statements(self.business, self.identity):
            self.connection.execute(statement)
        self.victim = self.operator
        self.params = {"op": self.operator, "admin": self.admin, "sec": self.scalar("SELECT id FROM vinto_master.sector WHERE code = 'REBOBINADO'"),
                       "mp1": self.scalar("SELECT id FROM vinto_master.machine WHERE code = 'MP1'"), "form": self.scalar("SELECT id FROM vinto_config.form WHERE code = 'VINTO-P1-05'"),
                       "pa": self.scalar("SELECT id FROM vinto_master.profile WHERE code = 'DATA_BALTREK'"), "hash": hashlib.sha256(b"attacker-token").hexdigest()}

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
        created = create_user(app, username=f"idn.{uuid4().hex[:8]}", display_name="Nuevo", profile_code="OPERACION", password="pw-" + uuid4().hex, sectors=("BOBINAS",))
        self.assertTrue(grant_machine_form(app, user_id=created.user_id, machine_code="MP1", form_code="VINTO-P1-06", actor_id=self.admin))
        self.assertFalse(grant_machine_form(app, user_id=created.user_id, machine_code="MP1", form_code="VINTO-P1-06", actor_id=self.admin))  # idempotente
        self.assertTrue(revoke_machine_form(app, user_id=created.user_id, machine_code="MP1", form_code="VINTO-P1-06", actor_id=self.admin))
        self.assertTrue(grant_sector(app, user_id=created.user_id, sector_code="REBOBINADO", actor_id=self.admin))
        self.assertTrue(revoke_sector(app, user_id=created.user_id, sector_code="REBOBINADO", actor_id=self.admin))
        password = "pw-" + uuid4().hex
        other = create_user(app, username=f"idn2.{uuid4().hex[:8]}", display_name="Otro", profile_code="CALIDAD", password=password, sectors=("BOBINAS",))
        user, session = login_with_session(app, other.username, password)
        self.assertEqual(user.user_id, other.user_id)
        self.assertEqual(resolve_session(app, session.raw_token).user_id, other.user_id)


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


if __name__ == "__main__":
    unittest.main()
