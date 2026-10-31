"""Motor central de autorización efectiva (MF-13-01D.1): decisiones, límites de privilegios, concurrencia con revocaciones e informe de preparación.

Las pruebas puras fijan la forma del motor (no conectado, solo lectura, políticas disjuntas, respuestas públicas fijas). Las de base de datos usan bases *_test efímeras (plantilla con el
bundle de referencia: MP1/MP3 con sus formularios reales publicados). Ninguna toca una base que no sea de prueba, un endpoint productivo, el catálogo, los perfiles ni los formularios.
"""

import ast
import re
import threading
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg

from app import capture_service
from app.auth import permissions
from app.auth.grants import grant_sector
from app.auth.machine_form_grants import grant_machine_form, has_active_machine_form_grant, revoke_machine_form
from app.auth.service import AuthenticatedUser, create_user
from app.authz import (POLICIES, AuthorizationDenied, AuthorizationUnavailable, Operation, ResourceNotFound, authorize, policy_for,
                       public_response, require)
from app.authz import engine as engine_module
from app.authz import readiness
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database

BACKEND = Path(__file__).resolve().parent.parent
PRODUCTION, BOBBIN, Q_BOBBIN, Q_MACHINE = (Operation.PRODUCTION_CAPTURE, Operation.BOBBIN_PRODUCTION, Operation.QUALITY_BOBBIN_CAPTURE, Operation.QUALITY_MACHINE_CAPTURE)
P101, P103, P118, P119 = "VINTO-P1-01", "VINTO-P1-03", "VINTO-P1-18", "VINTO-P1-19"  # P1-01 central; P1-03 F3; P1-18 calidad por máquina; P1-19 calidad por bobina
TEMPLATE = None


def drop_role(connection, role):
    connection.execute(f"DROP OWNED BY {role}")  # retira sus privilegios en esta base antes de borrar el rol
    connection.execute(f"DROP ROLE IF EXISTS {role}")


def setUpModule():
    global TEMPLATE
    TEMPLATE = build_reference_template("vinto_authz_tpl")


def tearDownModule():
    drop_database(TEMPLATE)


def principal(user_id, profiles=("OPERACION",), grants=frozenset()):
    """Un principal AUTENTICADO. Sus campos (permisos, sectores) pueden estar desfasados: el motor los ignora y relee todo de la base de datos."""
    return AuthenticatedUser(user_id=user_id, username="u", display_name="U", profile_codes=tuple(profiles), permissions=permissions.permissions_for_profiles(profiles),
                             must_change=False, sectors=frozenset(grants))


# ---- 1. forma del motor (pura) -----------------------------------------------------------------------------------------------

class ShapeTests(unittest.TestCase):
    def test_the_four_policies_exist_and_their_admitted_sets_are_pairwise_disjoint(self):
        self.assertEqual(set(POLICIES), {PRODUCTION, BOBBIN, Q_BOBBIN, Q_MACHINE})
        operations = list(POLICIES)
        for index, first in enumerate(operations):
            for second in operations[index + 1:]:
                self.assertEqual(POLICIES[first].admitted() & POLICIES[second].admitted(), frozenset(), (first, second))

    def test_the_policies_follow_the_live_route_constants_without_enabling_anything(self):
        self.assertEqual(POLICIES[PRODUCTION].admitted(), frozenset(capture_service.CENTRAL_FORM_CODES))
        self.assertEqual(POLICIES[BOBBIN].admitted(), frozenset({P103}))
        self.assertNotIn(P103, POLICIES[PRODUCTION].admitted())  # la F3 especializada no se autoriza por la captura central
        self.assertEqual(POLICIES[Q_MACHINE].admitted() & POLICIES[Q_BOBBIN].admitted(), frozenset())

    def test_permissions_and_areas_per_operation(self):
        for operation in (PRODUCTION, BOBBIN):
            self.assertEqual((POLICIES[operation].permission, POLICIES[operation].area), (permissions.PRODUCTION_CAPTURE, "production"))
        for operation in (Q_BOBBIN, Q_MACHINE):
            self.assertEqual((POLICIES[operation].permission, POLICIES[operation].area), (permissions.QUALITY_CAPTURE, "quality"))

    def test_an_unknown_operation_is_a_programming_error_never_an_implicit_allow(self):
        for bad in ("delete_everything", None, 7):
            with self.assertRaises(TypeError):
                policy_for(bad)

    def test_public_responses_are_fixed_and_leak_nothing(self):
        decision = engine_module.Decision(False, "forbidden", "SECTOR_NOT_GRANTED", "production_capture", uuid4(), "MP1", P101)
        bodies = [public_response(AuthorizationDenied(decision)), public_response(ResourceNotFound(decision)), public_response(AuthorizationUnavailable("42P01"))]
        self.assertEqual([status for status, _ in bodies], [403, 404, 503])
        text = repr(bodies)
        for secret in ("SECTOR_NOT_GRANTED", "42P01", "MP1", P101, "vinto_", "grant"):
            self.assertNotIn(secret, text)
        self.assertEqual(public_response(RuntimeError("x"))[0], 503)  # una excepción desconocida jamás es "permitido"

    def test_the_engine_is_read_only_and_uses_for_share_never_for_key_share_or_dml(self):
        tree = ast.parse((BACKEND / "app/authz/engine.py").read_text(encoding="utf-8"))
        docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                      if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef)) and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
        literals = " | ".join(n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings)
        self.assertNotRegex(literals, r"\b(INSERT|UPDATE|DELETE|TRUNCATE)\b")
        self.assertNotIn("KEY SHARE", literals)
        self.assertIn("FOR SHARE", literals)

    def test_the_engine_is_wired_only_to_captures_and_bobbins(self):
        consumers = [str(path.relative_to(BACKEND)).replace("\\", "/") for path in sorted((BACKEND / "app").rglob("*.py"))
                     if "app/authz" not in str(path).replace("\\", "/") and re.search(r"\bapp\.authz\b|\bfrom app import authz\b", path.read_text(encoding="utf-8"))]
        # MF-13-01D.2A/2B: solo POST /api/captures (captures.py), POST /api/bobbins (bobbins/router.py) y el manejador de errores (main.py); Calidad y el resto siguen sin usarlo
        self.assertEqual(consumers, ["app/bobbins/router.py", "app/captures.py", "app/main.py"])

    def test_the_locked_tables_are_exactly_those_vinto_app_may_lock(self):
        """Deriva de roles/03_table_grants.sql: lo que el motor bloquea tiene UPDATE para vinto_app; user_sector y vinto_config no lo tienen y por eso NO se bloquean."""
        sql = (BACKEND / "roles/03_table_grants.sql").read_text(encoding="utf-8")
        updatable = re.search(r"GRANT SELECT, INSERT, UPDATE ON\s+(vinto_master\.\"user\".*?)\s+TO vinto_app;", sql, re.S).group(1)
        for table in ('vinto_master."user"', "vinto_master.profile", "vinto_master.user_profile", "vinto_master.sector", "vinto_master.machine"):
            self.assertIn(table, updatable)
        self.assertIn("GRANT SELECT, INSERT, DELETE ON vinto_master.user_sector TO vinto_app;", sql)
        self.assertRegex(sql, r"GRANT SELECT ON\s+vinto_config\.shift,")
        source = (BACKEND / "app/authz/engine.py").read_text(encoding="utf-8")
        for unlocked in ("vinto_master.user_sector", "vinto_config.form WHERE", "vinto_config.form_version fv", "vinto_config.form_version_machine"):
            line = next(l for l in source.splitlines() if unlocked in l and "SELECT" in l)
            self.assertNotIn("FOR SHARE", line, unlocked)
            self.assertNotIn("+ share", line, unlocked)


# ---- 2. fixtures de base de datos ---------------------------------------------------------------------------------------------

class DatabaseCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = copy_database(TEMPLATE, "vinto_authz")
        cls.addClassCleanup(drop_database, cls.db)
        cls.connection = connect(cls.db)
        cls.addClassCleanup(cls.connection.close)
        cls.admin = cls.new_user("DATA_BALTREK")

    @classmethod
    def new_user(cls, profile="OPERACION", sectors=("BOBINAS",)):
        return create_user(cls.connection, username=f"az.{uuid4().hex[:12]}", display_name=f"{profile} test", profile_code=profile, password="pw-" + uuid4().hex, sectors=sectors).user_id

    def operator(self, machine="MP1", form=P101, profile="OPERACION", sectors=("BOBINAS",), grant=True):
        user = self.new_user(profile, sectors)
        if grant:
            self.grant(user, machine, form)
        return user

    def grant(self, user, machine="MP1", form=P101, connection=None):
        return grant_machine_form(connection or self.connection, user_id=user, machine_code=machine, form_code=form, actor_id=self.admin)

    def revoke(self, user, machine="MP1", form=P101, connection=None):
        return revoke_machine_form(connection or self.connection, user_id=user, machine_code=machine, form_code=form, actor_id=self.admin)

    def decide(self, user, operation=PRODUCTION, machine="MP1", form=P101, *, lock=False, connection=None, profiles=("OPERACION",)):
        return authorize(connection or self.connection, principal(user, profiles), operation, machine, form, lock=lock)

    def assertAllowed(self, user, *args, **kwargs):
        decision = self.decide(user, *args, **kwargs)
        self.assertTrue(decision.allowed, decision)
        return decision

    def assertDenied(self, user, reason, *args, kind="forbidden", **kwargs):
        decision = self.decide(user, *args, **kwargs)
        self.assertEqual((decision.allowed, decision.kind, decision.reason), (False, kind, reason), decision)

    @contextmanager
    def mutated(self, *statements):
        """Aplica cambios de catálogo SOLO dentro de una transacción que siempre se revierte (los triggers de inmutabilidad se omiten solo aquí, con el rol de prueba superusuario)."""
        with self.connection.transaction():
            self.connection.execute("SET LOCAL session_replication_role = replica")
            for statement in statements:
                self.connection.execute(statement)
            yield
            raise psycopg.Rollback()


# ---- 3. decisiones ------------------------------------------------------------------------------------------------------------

class DecisionTests(DatabaseCase):
    def test_all_seven_conditions_together_allow_and_report_the_backing_grant_and_version(self):
        user = self.operator()
        decision = self.assertAllowed(user)
        self.assertEqual((decision.kind, decision.reason, decision.effective_version), ("allowed", "ALLOWED", 4))
        self.assertIsNotNone(decision.grant_id)

    def test_each_of_the_four_routes_allows_its_own_forms_with_the_right_profile(self):
        production = self.operator("MP3", P101)
        bobbin = self.operator("MP1", P103)
        quality_bobbin = self.operator("MP1", P119, profile="CALIDAD")
        quality_machine = self.operator("MP3", P118, profile="CALIDAD")
        self.assertAllowed(production, PRODUCTION, "MP3", P101)
        self.assertAllowed(bobbin, BOBBIN, "MP1", P103, profiles=("OPERACION",))
        self.assertAllowed(quality_bobbin, Q_BOBBIN, "MP1", P119, profiles=("CALIDAD",))
        self.assertAllowed(quality_machine, Q_MACHINE, "MP3", P118, profiles=("CALIDAD",))

    def test_a_specialised_form_is_not_authorised_on_another_route_even_with_an_active_grant(self):
        user = self.operator("MP1", P103)
        self.assertDenied(user, "POLICY_DOES_NOT_ADMIT_FORM", PRODUCTION, "MP1", P103)  # P1-03 se registra solo por /api/bobbins
        self.assertAllowed(user, BOBBIN, "MP1", P103)
        central = self.operator("MP1", P101)
        self.assertDenied(central, "POLICY_DOES_NOT_ADMIT_FORM", BOBBIN, "MP1", P101)
        calidad = self.operator("MP1", P118, profile="CALIDAD")
        self.assertDenied(calidad, "POLICY_DOES_NOT_ADMIT_FORM", Q_BOBBIN, "MP1", P118)
        self.assertAllowed(calidad, Q_MACHINE, "MP1", P118)

    def test_without_the_grant_the_triple_is_denied_even_with_profile_and_sector(self):
        self.assertDenied(self.operator(grant=False), "GRANT_MISSING")

    def test_a_grant_for_mp1_does_not_authorise_mp3_nor_another_form(self):
        user = self.operator("MP1", P101)
        self.assertDenied(user, "GRANT_MISSING", PRODUCTION, "MP3", P101)
        self.assertDenied(user, "GRANT_MISSING", PRODUCTION, "MP1", "VINTO-P1-02")
        self.assertAllowed(user, PRODUCTION, "MP1", P101)

    def test_the_grant_never_replaces_the_profile_permission(self):
        self.assertDenied(self.operator("MP1", P101, profile="CALIDAD"), "PERMISSION_MISSING", PRODUCTION)
        self.assertDenied(self.operator("MP1", P118, profile="OPERACION"), "PERMISSION_MISSING", Q_MACHINE)

    def test_data_baltrek_administering_users_gets_no_capture_authorisation(self):
        admin = self.new_user("DATA_BALTREK", sectors=("BOBINAS",))
        self.grant(admin)
        self.assertDenied(admin, "PERMISSION_MISSING", PRODUCTION)

    def test_multiple_active_profiles_keep_the_union_of_permissions(self):
        user = self.operator("MP1", P118, profile="OPERACION")
        self.grant(user, "MP1", P101)
        self.assertDenied(user, "PERMISSION_MISSING", Q_MACHINE)
        self.connection.execute("INSERT INTO vinto_master.user_profile (user_id, profile_id) SELECT %s, id FROM vinto_master.profile WHERE code = 'CALIDAD'", (user,))
        self.assertAllowed(user, PRODUCTION, "MP1", P101)
        self.assertAllowed(user, Q_MACHINE, "MP1", P118)

    def test_an_inactive_profile_contributes_nothing(self):
        user = self.operator()
        with self.mutated("UPDATE vinto_master.profile SET active = false WHERE code = 'OPERACION'"):
            self.assertDenied(user, "PERMISSION_MISSING")
        self.assertAllowed(user)

    def test_the_sector_grant_is_required_and_the_machine_grant_never_grants_it(self):
        user = self.operator(sectors=())
        self.assertDenied(user, "SECTOR_NOT_GRANTED")
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_master.user_sector WHERE user_id = %s", (user,)).fetchone()[0], 0)  # y consultar no concede nada
        grant_sector(self.connection, user_id=user, sector_code="BOBINAS")
        self.assertAllowed(user)

    def test_an_inactive_user_sector_machine_or_form_is_denied(self):
        user = self.operator()
        cases = (("UPDATE vinto_master.\"user\" SET active = false WHERE id = '%s'" % user, "USER_INACTIVE"),
                 ("UPDATE vinto_master.sector SET active = false WHERE code = 'BOBINAS'", "SECTOR_INACTIVE"),
                 ("UPDATE vinto_master.machine SET active = false WHERE code = 'MP1'", "MACHINE_INACTIVE"),
                 (f"UPDATE vinto_config.form SET active = false WHERE code = '{P101}'", "FORM_INACTIVE"))
        for statement, reason in cases:
            with self.subTest(reason), self.mutated(statement):
                self.assertDenied(user, reason)
        self.assertAllowed(user)

    def test_a_non_operational_sector_is_denied_even_if_active_and_granted(self):
        user = self.operator()
        with self.mutated("UPDATE vinto_master.sector SET code = 'LEGACY_X' WHERE code = 'BOBINAS'"):
            self.assertDenied(user, "SECTOR_NOT_OPERATIONAL")

    def test_a_form_without_a_published_version_is_denied(self):
        user = self.operator()
        with self.mutated(f"UPDATE vinto_config.form_version SET status = 'retired' WHERE form_id = (SELECT id FROM vinto_config.form WHERE code = '{P101}')"):
            self.assertDenied(user, "NO_EFFECTIVE_VERSION")

    def test_an_effective_version_of_another_area_denies_the_route(self):
        user = self.operator()
        with self.mutated(f"UPDATE vinto_config.form_version SET area = 'quality' WHERE form_id = (SELECT id FROM vinto_config.form WHERE code = '{P101}')"):
            self.assertDenied(user, "EFFECTIVE_VERSION_OTHER_AREA")  # MF-13-01D.1.1: la equivalencia completa con el catálogo está en test_authz_version_equivalence

    def test_an_active_grant_whose_pair_is_no_longer_offered_authorises_nothing(self):
        user = self.operator()
        unlink = ("DELETE FROM vinto_config.form_version_machine WHERE machine_id = (SELECT id FROM vinto_master.machine WHERE code = 'MP1') "
                  f"AND form_version_id IN (SELECT fv.id FROM vinto_config.form_version fv JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code = '{P101}')")
        with self.mutated(unlink):
            self.assertTrue(has_active_machine_form_grant(self.connection, user_id=user, machine_code="MP1", form_code=P101))  # la concesión sigue activa…
            self.assertDenied(user, "PAIR_NOT_OFFERED")  # …pero no autoriza

    def test_a_link_that_only_exists_on_a_historical_version_does_not_count(self):
        user = self.operator()
        historical = [
            f"CREATE TEMP TABLE _fv ON COMMIT DROP AS SELECT * FROM vinto_config.form_version WHERE form_id = (SELECT id FROM vinto_config.form WHERE code = '{P101}')",
            "UPDATE _fv SET id = gen_random_uuid(), version_number = 3",
            "INSERT INTO vinto_config.form_version SELECT * FROM _fv",
            "INSERT INTO vinto_config.form_version_machine (form_version_id, machine_id) SELECT (SELECT id FROM _fv), (SELECT id FROM vinto_master.machine WHERE code = 'MP1')",
            "DELETE FROM vinto_config.form_version_machine WHERE machine_id = (SELECT id FROM vinto_master.machine WHERE code = 'MP1') AND form_version_id <> (SELECT id FROM _fv) "
            f"AND form_version_id IN (SELECT fv.id FROM vinto_config.form_version fv JOIN vinto_config.form f ON f.id = fv.form_id WHERE f.code = '{P101}')"]
        with self.mutated(*historical):
            self.assertDenied(user, "PAIR_NOT_OFFERED")

    def test_unknown_or_malformed_resources_are_not_found_never_errors_or_allows(self):
        user = self.operator()
        self.assertDenied(user, "MACHINE_NOT_FOUND", PRODUCTION, "NO-SUCH-MACHINE", P101, kind="not_found")
        self.assertDenied(user, "FORM_NOT_FOUND", PRODUCTION, "MP1", "NO-SUCH-FORM", kind="not_found")
        self.assertDenied(user, "MACHINE_NOT_FOUND", PRODUCTION, None, P101, kind="not_found")
        self.assertDenied(user, "FORM_NOT_FOUND", PRODUCTION, "MP1", 42, kind="not_found")
        self.assertDenied(uuid4(), "USER_NOT_FOUND", kind="not_found")

    def test_a_stale_authenticated_user_cannot_authorise_what_the_database_no_longer_says(self):
        user = self.operator(grant=False)
        stale = principal(user, ("OPERACION", "CALIDAD"), grants={"BOBINAS", "REBOBINADO"})
        self.assertFalse(authorize(self.connection, stale, PRODUCTION, "MP1", P101).allowed)

    def test_an_unauthenticated_caller_is_a_programming_error(self):
        for bad in (None, uuid4(), {"user_id": uuid4()}):
            with self.assertRaises(TypeError):
                authorize(self.connection, bad, PRODUCTION, "MP1", P101)

    def test_require_maps_each_outcome_to_its_own_exception(self):
        user = self.operator()
        with self.connection.transaction():
            self.assertTrue(require(self.connection, principal(user), PRODUCTION, "MP1", P101).allowed)
            with self.assertRaises(AuthorizationDenied):
                require(self.connection, principal(user), PRODUCTION, "MP3", P101)
            with self.assertRaises(ResourceNotFound):
                require(self.connection, principal(user), PRODUCTION, "NOPE", P101)

    def test_users_are_isolated_from_each_other(self):
        first, second = self.operator(), self.operator(grant=False)
        self.assertAllowed(first)
        self.assertDenied(second, "GRANT_MISSING")
        self.revoke(first)
        self.assertDenied(first, "GRANT_MISSING")
        third = self.operator()
        self.assertAllowed(third)

    def test_a_revoked_grant_denies_and_a_new_grant_after_revocation_allows_again(self):
        user = self.operator()
        self.assertAllowed(user)
        self.revoke(user)
        self.assertDenied(user, "GRANT_MISSING")
        self.grant(user)
        self.assertAllowed(user)

    def test_the_decision_is_pure_reading_it_writes_no_rows_and_no_audit(self):
        user = self.operator()
        before = [self.connection.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("vinto_master.user_machine_form_grant", "vinto_audit.audit_event", "vinto_master.user_sector")]
        for lock in (False, True):
            with self.connection.transaction():
                self.decide(user, lock=lock)
        after = [self.connection.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in ("vinto_master.user_machine_form_grant", "vinto_audit.audit_event", "vinto_master.user_sector")]
        self.assertEqual(before, after)


# ---- 4. fallos de infraestructura: jamás acceso concedido ----------------------------------------------------------------------

class UnavailableTests(DatabaseCase):
    def test_a_missing_grants_table_is_unavailable_not_allowed(self):
        user = self.operator()
        with self.assertRaises(AuthorizationUnavailable) as raised:
            with self.connection.transaction():
                self.connection.execute("ALTER TABLE vinto_master.user_machine_form_grant RENAME TO grants_gone")
                self.decide(user)
                raise psycopg.Rollback()
        self.assertEqual(raised.exception.cause, "42P01")
        self.assertAllowed(user)  # la reversión dejó todo como estaba

    def test_a_missing_privilege_is_unavailable_not_allowed(self):
        user = self.operator()
        role = "az_nopriv_" + uuid4().hex[:8]
        self.connection.execute(f"CREATE ROLE {role} NOLOGIN")
        self.addCleanup(drop_role, self.connection, role)
        self.connection.execute(f"GRANT USAGE ON SCHEMA vinto_master, vinto_config TO {role}")
        with self.assertRaises(AuthorizationUnavailable) as raised:
            with self.connection.transaction():
                self.connection.execute(f"SET LOCAL ROLE {role}")
                self.decide(user)
        self.assertEqual(raised.exception.cause, "42501")

    def test_a_closed_connection_is_unavailable_not_allowed(self):
        user = self.operator()
        broken = connect(self.db)
        broken.close()
        with self.assertRaises(AuthorizationUnavailable):
            self.decide(user, connection=broken)

    def test_locking_without_an_open_transaction_fails_closed(self):
        user = self.operator()
        with self.assertRaises(AuthorizationUnavailable) as raised:
            self.decide(user, lock=True)  # conexión en autocommit y sin connection.transaction(): los bloqueos no protegerían nada
        self.assertEqual(raised.exception.cause, "NO_TRANSACTION")
        with self.assertRaises(AuthorizationUnavailable):
            require(self.connection, principal(user), PRODUCTION, "MP1", P101)  # require bloquea por defecto

    def test_a_serialization_failure_under_repeatable_read_is_unavailable(self):
        user = self.operator()
        other = connect(self.db)
        self.addCleanup(other.close)
        with self.connection.transaction():
            self.connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            self.connection.execute("SELECT 1 FROM vinto_master.user_machine_form_grant LIMIT 1")  # fija la instantánea
            self.revoke(user, connection=other)  # revocación confirmada DESPUÉS de la instantánea
            with self.assertRaises(AuthorizationUnavailable) as raised:
                self.decide(user, lock=True)
            self.assertEqual(raised.exception.cause, "40001")


# ---- 5. bloqueos y concurrencia -------------------------------------------------------------------------------------------------

class LockTests(DatabaseCase):
    def raw_revoke(self, connection, user, timeout_ms=None):
        """Revocación directa (UPDATE de revoked_at) como la hace un operador: con el actor de la sesión; opcionalmente con lock_timeout para DETECTAR el bloqueo."""
        with connection.transaction():
            if timeout_ms:
                connection.execute(f"SET LOCAL lock_timeout = {int(timeout_ms)}")
            connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(self.admin),))
            connection.execute("UPDATE vinto_master.user_machine_form_grant SET revoked_at = clock_timestamp(), revoked_by = %s WHERE user_id = %s AND revoked_at IS NULL", (self.admin, user))

    def other(self):
        connection = connect(self.db)
        self.addCleanup(connection.close)
        return connection

    def test_for_share_blocks_an_update_of_revoked_at_while_the_capture_transaction_is_open(self):
        user, revoker = self.operator(), self.other()
        with self.connection.transaction():
            self.assertAllowed(user, lock=True)
            with self.assertRaises(psycopg.errors.LockNotAvailable):
                self.raw_revoke(revoker, user, timeout_ms=300)  # la revocación NO puede colarse entre la autorización y el registro
        self.raw_revoke(revoker, user, timeout_ms=300)  # al terminar la captura ya puede revocar
        self.assertDenied(user, "GRANT_MISSING")

    def test_for_key_share_would_NOT_have_been_enough(self):
        """Prueba de la decisión de diseño: el UPDATE de revoked_at no cambia columnas clave, así que FOR KEY SHARE no lo bloquea."""
        user, revoker = self.operator(), self.other()
        with self.connection.transaction():
            self.connection.execute("SELECT id FROM vinto_master.user_machine_form_grant WHERE user_id = %s AND revoked_at IS NULL FOR KEY SHARE", (user,))
            self.raw_revoke(revoker, user, timeout_ms=300)  # no bloquea: una captura protegida solo con KEY SHARE se registraría con una concesión ya revocada
        self.assertDenied(user, "GRANT_MISSING")

    def test_the_capture_also_holds_the_user_profile_and_machine_rows_against_concurrent_deactivation(self):
        user, other = self.operator(), self.other()
        deactivations = (f"UPDATE vinto_master.\"user\" SET active = false WHERE id = '{user}'",
                         f"UPDATE vinto_master.user_profile SET profile_id = profile_id WHERE user_id = '{user}'",
                         "UPDATE vinto_master.machine SET active = active WHERE code = 'MP1'",
                         "UPDATE vinto_master.sector SET active = active WHERE code = 'BOBINAS'")
        for statement in deactivations:
            with self.subTest(statement=statement[:60]), self.connection.transaction():
                self.assertAllowed(user, lock=True)
                with self.assertRaises(psycopg.errors.LockNotAvailable), other.transaction():
                    other.execute("SET LOCAL lock_timeout = 300")
                    other.execute(statement)

    def test_without_lock_the_read_does_not_hold_anything(self):
        user, revoker = self.operator(), self.other()
        with self.connection.transaction():
            self.assertAllowed(user, lock=False)
            self.raw_revoke(revoker, user, timeout_ms=300)

    def test_a_revocation_committed_before_the_capture_is_never_ignored(self):
        user, revoker = self.operator(), self.other()
        self.revoke(user, connection=revoker)
        with self.connection.transaction():
            self.assertDenied(user, "GRANT_MISSING", lock=True)

    def test_a_capture_waiting_on_an_uncommitted_revocation_sees_it_after_commit(self):
        user, revoker = self.operator(), self.other()
        outcome = []
        with revoker.transaction():
            revoker.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(self.admin),))
            revoker.execute("UPDATE vinto_master.user_machine_form_grant SET revoked_at = clock_timestamp(), revoked_by = %s WHERE user_id = %s AND revoked_at IS NULL", (self.admin, user))

            def capture():
                with connect(self.db) as connection, connection.transaction():
                    outcome.append(self.decide(user, lock=True, connection=connection))
            thread = threading.Thread(target=capture)
            thread.start()
            thread.join(0.7)
            self.assertTrue(thread.is_alive())  # la captura espera la revocación en curso…
        thread.join(15)
        self.assertEqual((outcome[0].allowed, outcome[0].reason), (False, "GRANT_MISSING"))  # …y al confirmarse la ve (READ COMMITTED reevalúa)

    def test_a_revocation_waits_for_the_running_capture_and_then_wins_for_the_next_one(self):
        user = self.operator()
        done = threading.Event()

        def revoker():
            with connect(self.db) as connection:
                self.revoke(user, connection=connection)
            done.set()
        with self.connection.transaction():
            decision = self.assertAllowed(user, lock=True)
            thread = threading.Thread(target=revoker)
            thread.start()
            self.assertFalse(done.wait(0.7))  # la revocación espera: la captura en curso quedó autorizada con una concesión que seguía vigente
        thread.join(15)
        self.assertTrue(done.is_set() and decision.allowed)
        self.assertDenied(user, "GRANT_MISSING", lock=False)

    def test_idempotent_retries_inside_one_transaction_and_across_grant_and_revoke(self):
        user = self.operator()
        with self.connection.transaction():
            first, second = self.decide(user, lock=True), self.decide(user, lock=True)  # los bloqueos son reentrantes
        self.assertEqual((first.allowed, first.grant_id), (second.allowed, second.grant_id))
        self.assertFalse(self.grant(user))  # conceder de nuevo es idempotente: False = ya había una concesión activa
        self.assertEqual(self.decide(user).grant_id, first.grant_id)
        self.revoke(user)
        self.revoke(user)  # revocar dos veces es inofensivo
        self.assertDenied(user, "GRANT_MISSING")

    def test_mixed_load_of_captures_grants_and_revocations_neither_deadlocks_nor_fails_open(self):
        users = [self.operator() for _ in range(4)]
        errors, observed = [], []

        def worker(index):
            try:
                with connect(self.db) as connection:
                    for step in range(12):
                        user = users[(index + step) % len(users)]
                        action = (index + step) % 3
                        if action == 0:
                            with connection.transaction():
                                decision = self.decide(user, lock=True, connection=connection)
                                observed.append(decision)
                                time.sleep(0.005)  # la captura "registra" mientras mantiene los bloqueos
                        elif action == 1:
                            self.revoke(user, connection=connection)
                        else:
                            self.grant(user, connection=connection)
            except BaseException as error:  # cualquier DeadlockDetected o AuthorizationUnavailable falla la prueba
                errors.append(repr(error))
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(90)
        self.assertEqual(errors, [])
        self.assertTrue(observed and all(d.reason in ("ALLOWED", "GRANT_MISSING") for d in observed))
        for user in users:  # estado final coherente: a lo sumo una concesión activa por terna
            self.assertLessEqual(self.connection.execute("SELECT count(*) FROM vinto_master.user_machine_form_grant WHERE user_id = %s AND revoked_at IS NULL", (user,)).fetchone()[0], 1)


# ---- 6. el motor con los privilegios REALES de vinto_app ---------------------------------------------------------------------------

class RestrictedRoleTests(DatabaseCase):
    """Replica los privilegios de backend/roles/03_table_grants.sql: sin UPDATE en user_sector ni en vinto_config. Con el rol de prueba superusuario esto pasaría desapercibido."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.role = "az_app_" + uuid4().hex[:8]
        cls.connection.execute(f"CREATE ROLE {cls.role} NOLOGIN")
        cls.addClassCleanup(drop_role, cls.connection, cls.role)
        for statement in (
                f"GRANT USAGE ON SCHEMA vinto_master, vinto_config, vinto_audit TO {cls.role}",
                f'GRANT SELECT, INSERT, UPDATE ON vinto_master."user", vinto_master.profile, vinto_master.user_profile, vinto_master.sector, vinto_master.machine, vinto_master.user_machine_form_grant TO {cls.role}',
                f"GRANT SELECT, INSERT, DELETE ON vinto_master.user_sector TO {cls.role}",
                f"GRANT SELECT ON ALL TABLES IN SCHEMA vinto_config TO {cls.role}"):
            cls.connection.execute(statement)

    @contextmanager
    def as_app(self):
        with self.connection.transaction():
            self.connection.execute(f"SET LOCAL ROLE {self.role}")
            yield

    def test_the_premise_user_sector_and_the_config_tables_cannot_be_row_locked_by_that_role(self):
        for table in ("vinto_master.user_sector", "vinto_config.form", "vinto_config.form_version", "vinto_config.form_version_machine"):
            for mode in ("FOR SHARE", "FOR KEY SHARE"):
                with self.subTest(table=table, mode=mode), self.assertRaises(psycopg.errors.InsufficientPrivilege), self.as_app():
                    self.connection.execute(f"SELECT 1 FROM {table} LIMIT 1 {mode}")

    def test_the_locking_engine_works_end_to_end_with_those_privileges(self):
        user, stranger = self.operator(), self.operator(grant=False)
        with self.as_app():
            self.assertAllowed(user, lock=True)
            self.assertDenied(user, "GRANT_MISSING", PRODUCTION, "MP3", P101, lock=True)
            self.assertDenied(stranger, "GRANT_MISSING", lock=True)

    def test_the_lock_still_blocks_a_concurrent_revocation_under_those_privileges(self):
        user = self.operator()
        revoker = connect(self.db)
        self.addCleanup(revoker.close)
        with self.as_app():
            self.assertAllowed(user, lock=True)
            with self.assertRaises(psycopg.errors.LockNotAvailable), revoker.transaction():
                revoker.execute("SET LOCAL lock_timeout = 300")
                revoker.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(self.admin),))
                revoker.execute("UPDATE vinto_master.user_machine_form_grant SET revoked_at = clock_timestamp(), revoked_by = %s WHERE user_id = %s AND revoked_at IS NULL", (self.admin, user))


# ---- 7. informe de preparación ----------------------------------------------------------------------------------------------------

class ReadinessTests(DatabaseCase):
    def test_users_without_grants_are_reported_as_would_be_blocked_and_grants_cover_them(self):
        user = self.operator(grant=False)
        blocked = {(i["username"], i["machine"], i["form"]) for i in readiness.coverage_report(self.connection)["production_capture"]["blocked"]}
        username = self.connection.execute("SELECT username FROM vinto_auth.credential WHERE user_id = %s", (user,)).fetchone()[0]
        self.assertIn((username, "MP1", P101), blocked)
        self.assertIn((username, "MP3", P101), blocked)
        self.grant(user, "MP1", P101)
        report = readiness.coverage_report(self.connection)["production_capture"]
        self.assertNotIn((username, "MP1", P101), {(i["username"], i["machine"], i["form"]) for i in report["blocked"]})
        self.assertIn((username, "MP3", P101), {(i["username"], i["machine"], i["form"]) for i in report["blocked"]})
        self.assertGreaterEqual(report["covered"], 1)

    def test_users_without_the_functional_permission_are_not_reported_as_blocked(self):
        user = self.operator(profile="CALIDAD", grant=False)
        username = self.connection.execute("SELECT username FROM vinto_auth.credential WHERE user_id = %s", (user,)).fetchone()[0]
        self.assertNotIn(username, readiness.coverage_report(self.connection)["production_capture"]["blocked_by_user"])
        self.assertIn(username, readiness.coverage_report(self.connection)["quality_machine_capture"]["blocked_by_user"])

    def test_the_report_is_read_only_and_flags_direct_write_privileges(self):
        self.operator(grant=False)
        tables = ("vinto_master.user_machine_form_grant", "vinto_audit.audit_event", "vinto_master.user_sector", "vinto_master.\"user\"")
        before = [self.connection.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables]
        report = readiness.build_report(self.connection)
        self.assertEqual(before, [self.connection.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in tables])
        self.assertEqual(report["mode"], "read-only")
        self.assertTrue(report["privileges"]["available"] and report["privileges"]["direct_write"])  # el rol de prueba es superusuario: se señala
        self.assertEqual(report["total_would_be_blocked"], sum(v["would_be_blocked"] for v in report["coverage"].values()))

    def test_a_missing_grants_table_is_reported_as_unavailable_not_as_safe(self):
        with self.connection.transaction():
            self.connection.execute("DROP TABLE vinto_master.user_machine_form_grant CASCADE")
            self.assertFalse(readiness.privilege_report(self.connection)["available"])
            raise psycopg.Rollback()


if __name__ == "__main__":
    unittest.main()
