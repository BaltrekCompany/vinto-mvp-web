"""OFF-04.5B-03: QA entrypoint, migration 0032 (promotion, grants, rollback) and authz-engine probe, on DISPOSABLE PostgreSQL databases only.

Synthetic identities, grants and data. Nothing here touches a deployed API, the VPS or an operational database: every database is a throwaway `*_test`
copy created through app.ephemeral_db (which verifies `current_database()`).
"""
import hashlib
import importlib.util
import json
import logging
import os
import pathlib
import re
import shutil
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi import Header, HTTPException
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo

import migrate
from app.offline_capture import contract as C
from app.offline_capture.store import PgOfflineCaptureStore
from app.qa_offline_pilot import AuthzEngineProbe, PilotConfigError, QaPilotAuthorizer, PilotGrant
from app.qa_pilot_main import create_app_from_env, verify_receiver_database
from tests.off044_support import SNAPSHOT_CAPTURE, SNAPSHOT_CONSULT, USER_A, capture, h, principal

BACKEND = pathlib.Path(__file__).resolve().parents[1]
OFFDIR = BACKEND / "offline_capture_migration"
FORM = "VINTO-P1-22"
APP_ROLE = "vinto_app"
APP_PASSWORD = "app-throwaway-not-a-secret"


def load_promote():
    spec = importlib.util.spec_from_file_location("promote_0032", OFFDIR / "promote_0032.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


promote_module = load_promote()


# ------------------------------------------------------------------ fixtures
def _need_pg(exc: Exception):
    if os.environ.get("OFF045B03_REQUIRE_PG") == "1":
        pytest.fail(f"PostgreSQL is required in CI (OFF045B03_REQUIRE_PG=1) but is not available: {type(exc).__name__}")
    pytest.skip("no disposable PostgreSQL configured (TEST_DATABASE_URL / TEST_ADMIN_DATABASE_URL)")


@pytest.fixture(scope="module")
def app_role():
    from app.ephemeral_db import _admin
    try:
        admin = _admin()
    except Exception as exc:  # noqa: BLE001
        _need_pg(exc)
    with admin:
        admin.execute(f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN "
                      f"CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT; END IF; END $$")
        # the role may already exist as NOLOGIN (created by the OFF-04.4 helper in a shared throwaway cluster): make it the restricted LOGIN role we need
        admin.execute(f"ALTER ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASSWORD}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT")
        admin.execute(f"ALTER ROLE {APP_ROLE} SET search_path = ''")
    yield APP_ROLE
    with _admin() as admin:
        try:
            admin.execute(f"DROP ROLE IF EXISTS {APP_ROLE}")
        except psycopg.Error:
            pass


@pytest.fixture(scope="module")
def tree(tmp_path_factory):
    """A temporary copy of migrations 0001..0031 plus the PROMOTED 0032: the operational directory is never touched."""
    directory = tmp_path_factory.mktemp("migrations")
    for path in (BACKEND / "migrations").glob("*.sql"):
        shutil.copy(path, directory / path.name)
    promote_module.promote(directory)
    return directory


@pytest.fixture(scope="module")
def base_template(app_role):
    from app.ephemeral_db import build_reference_template, drop_database
    try:
        name = build_reference_template("off045b03_base")
    except Exception as exc:  # noqa: BLE001
        _need_pg(exc)
    yield name
    drop_database(name)


@pytest.fixture(scope="module")
def pilot_template(base_template, tree):
    """base + 0032 applied through migrate.py from the temporary tree. Used only as a template for copies."""
    from app.ephemeral_db import connect, copy_database, drop_database
    name = copy_database(base_template, "off045b03_pilot")
    with connect(name) as connection:
        migrate.apply(connection, migrate.read_migrations(tree))
        # what the READ-ONLY central engine needs from the application role (it never writes): SELECT on the catalogue/identity tables it reads. The
        # operational DML of the real role (backend/roles/03_table_grants.sql) is deliberately NOT replicated here.
        for statement in (f"GRANT USAGE ON SCHEMA vinto_master, vinto_config TO {APP_ROLE}",
                          f"GRANT SELECT ON ALL TABLES IN SCHEMA vinto_master, vinto_config TO {APP_ROLE}"):
            connection.execute(statement)
    yield name
    drop_database(name)


@pytest.fixture
def plain_db(base_template):
    from app.ephemeral_db import copy_database, drop_database
    name = copy_database(base_template, "off045b03_plain")
    yield name
    drop_database(name)


@pytest.fixture
def pilot_db(pilot_template):
    from app.ephemeral_db import copy_database, drop_database
    name = copy_database(pilot_template, "off045b03_run")
    yield name
    drop_database(name)


def admin_conn(name):
    from app.ephemeral_db import connect
    return connect(name)


def app_url(name) -> str:
    from app.ephemeral_db import database_url
    return make_conninfo(database_url(name), user=APP_ROLE, password=APP_PASSWORD)


def app_connect(name):
    url = app_url(name)
    return lambda: psycopg.connect(url, connect_timeout=5)


def run_script(connection, path: pathlib.Path):
    """Run a hand-run script (it has its own BEGIN/COMMIT); on failure leave the session clean."""
    try:
        connection.execute(path.read_text(encoding="utf-8"), prepare=False)
    except psycopg.Error:
        connection.execute("ROLLBACK")
        raise


def checks(connection) -> dict:
    rows = connection.execute((OFFDIR / "proposed_0032_offline_capture_receipt.verify.sql").read_text(encoding="utf-8")).fetchall()
    return {name: ok for name, ok in rows}


def who(x_synthetic_user: str | None = Header(default=None)):
    if not x_synthetic_user:
        raise HTTPException(status_code=401, detail="No autenticado")
    return principal(UUID(x_synthetic_user))


GRANT = {"user_id": str(USER_A), "machine_code": "MP1", "form_code": FORM, "form_version": 1, "synthetic": True,
         "scope_snapshot_id": str(SNAPSHOT_CAPTURE), "context_version": "ctx-1"}


def pilot_env(**extra):
    env = {"OFFLINE_QA_PILOT_ENABLED": "1", "OFFLINE_QA_PILOT_GRANTS": json.dumps([GRANT])}
    env.update(extra)
    return env


def cap(**over):
    return capture(**{"form": FORM, **over})


def receipts(name) -> int:
    with admin_conn(name) as c:
        return c.execute("SELECT count(*) FROM vinto_offline.capture_receipt").fetchone()[0]


# ------------------------------------------------------------------ migration: promotion, checksums, history
def test_the_proposal_is_not_in_the_operational_directory_and_has_no_transaction_control():
    assert not list((BACKEND / "migrations").glob("0032*"))
    sql = (OFFDIR / "proposed_0032_offline_capture_receipt.sql").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(BEGIN|COMMIT|END|ROLLBACK|START\s+TRANSACTION)\s*;", sql, re.IGNORECASE | re.MULTILINE)
    assert "IF NOT EXISTS" not in sql.split("CREATE SCHEMA vinto_offline;")[0].splitlines()[-1]
    assert re.search(r"^CREATE SCHEMA vinto_offline;", sql, re.MULTILINE)
    promote_module.check_proposal(sql)
    # the rollback and the verification are hand-run scripts, never numbered migrations
    assert not [p for p in (BACKEND / "migrations").glob("*.sql") if "offline" in p.name]


def test_promotion_refuses_the_operational_directory_and_anything_but_a_clean_0031_tree(tmp_path):
    with pytest.raises(promote_module.PromotionError):
        promote_module.promote(BACKEND / "migrations")
    with pytest.raises(promote_module.PromotionError):
        promote_module.promote(BACKEND / "migrations" / ".")
    with pytest.raises(promote_module.PromotionError):
        promote_module.promote(tmp_path / "missing")
    with pytest.raises(promote_module.PromotionError):
        promote_module.promote(tmp_path)  # empty tree: not 0001..0031
    assert promote_module.main(["--dest", str(BACKEND / "migrations")]) == 1
    assert not list((BACKEND / "migrations").glob("0032*"))


def test_promotion_rejects_a_proposal_that_controls_transactions_or_touches_other_modules(tmp_path):
    good = (OFFDIR / "proposed_0032_offline_capture_receipt.sql").read_text(encoding="utf-8")
    for bad in (good + "\nCOMMIT;\n", "BEGIN;\n" + good, good + "\n\\i other.sql\n", good + "\nDROP TABLE vinto_offline.capture_event;\n",
                good + "\nGRANT SELECT ON vinto_txn.capture TO vinto_app;\n", good.replace("CREATE SCHEMA vinto_offline;", "CREATE SCHEMA IF NOT EXISTS vinto_offline;")):
        with pytest.raises(promote_module.PromotionError):
            promote_module.check_proposal(bad)


def test_promoted_tree_is_a_valid_migrate_py_history(tree):
    migrations = migrate.read_migrations(tree)
    assert [m.version for m in migrations] == list(range(1, 33))
    last = migrations[-1]
    assert last.filename == "0032_offline_capture_receipt.sql"
    text = (OFFDIR / "proposed_0032_offline_capture_receipt.sql").read_text(encoding="utf-8").replace("\r\n", "\n")
    assert last.checksum == hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert [m.checksum for m in migrations[:31]] == [m.checksum for m in migrate.read_migrations()]  # the first 31 are untouched


def test_apply_records_history_and_detects_tampering(pilot_db, tree):
    with admin_conn(pilot_db) as c:
        applied = migrate.applied_migrations(c)
        migrations = migrate.read_migrations(tree)
        assert len(applied) == 32 and applied[-1][1] == "0032_offline_capture_receipt.sql"
        migrate.validate_history(migrations, applied)
        migrate.apply(c, migrations)  # idempotent: nothing pending
        tampered = list(migrations)
        tampered[-1] = migrate.Migration(32, migrations[-1].filename, "0" * 64, migrations[-1].sql)
        with pytest.raises(migrate.MigrationError):
            migrate.validate_history(tampered, applied)
        assert all(checks(c).values()), checks(c)


def test_0032_fails_on_a_preexisting_schema_and_changes_nothing(plain_db, tree):
    with admin_conn(plain_db) as c:
        c.execute("CREATE SCHEMA vinto_offline")
        with pytest.raises(psycopg.Error):
            migrate.apply(c, migrate.read_migrations(tree))
        assert len(migrate.applied_migrations(c)) == 31  # the failed migration was rolled back with its history row
        assert c.execute("SELECT count(*) FROM pg_tables WHERE schemaname = 'vinto_offline'").fetchone()[0] == 0


def test_0032_fails_closed_when_the_application_role_is_missing(plain_db, tree, app_role):
    # a database whose cluster has no such role cannot be simulated in a shared cluster: verify the statement order instead
    sql = (OFFDIR / "proposed_0032_offline_capture_receipt.sql").read_text(encoding="utf-8")
    assert "GRANT USAGE ON SCHEMA vinto_offline TO vinto_app;" in sql
    with admin_conn(plain_db) as c:
        with pytest.raises(psycopg.errors.UndefinedObject):
            with c.transaction():
                c.execute(sql.replace("TO vinto_app;", "TO vinto_role_that_does_not_exist;"), prepare=False)
        assert c.execute("SELECT to_regnamespace('vinto_offline')").fetchone()[0] is None  # nothing was left behind


def test_0032_adds_no_privilege_outside_its_schema(plain_db, tree, app_role):
    snapshot = ("SELECT n.nspname, c.relname, c.relacl::text FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname NOT IN ('vinto_offline') AND n.nspname !~ '^pg_' ORDER BY 1, 2")
    schemas = "SELECT nspname, nspacl::text FROM pg_namespace WHERE nspname <> 'vinto_offline' ORDER BY 1"
    with admin_conn(plain_db) as c:
        before = (c.execute(snapshot).fetchall(), c.execute(schemas).fetchall())
        migrate.apply(c, migrate.read_migrations(tree))
        after = (c.execute(snapshot).fetchall(), c.execute(schemas).fetchall())
    assert before == after  # not one ACL elsewhere changed


# ------------------------------------------------------------------ application role: least privilege
def test_application_role_can_operate_the_receiver_and_nothing_else(pilot_db):
    with psycopg.connect(app_url(pilot_db), autocommit=True) as c:
        cid, user = str(uuid4()), str(uuid4())
        c.execute("INSERT INTO vinto_offline.capture_receipt (capture_id, author_user_id, device_key, form_code, form_version, machine_code, context_version, "
                  "payload_sha256, payload, outcome) VALUES (%s, %s, %s, 'VINTO-P1-22', 1, 'MP1', 'ctx-1', %s, '{}'::jsonb, 'received')", (cid, user, user, "a" * 64))
        c.execute("INSERT INTO vinto_offline.capture_event (capture_id, kind) VALUES (%s, 'x')", (cid,))
        c.execute("UPDATE vinto_offline.capture_receipt SET outcome = 'accepted', reason = NULL, response_status = 201, response_body = '{}'::jsonb WHERE capture_id = %s", (cid,))
        assert c.execute("SELECT count(*) FROM vinto_offline.capture_receipt").fetchone()[0] == 1
        denied = [
            "DELETE FROM vinto_offline.capture_receipt", "TRUNCATE vinto_offline.capture_receipt", "DELETE FROM vinto_offline.capture_event",
            "UPDATE vinto_offline.capture_event SET kind = 'y'", "TRUNCATE vinto_offline.capture_event",
            "CREATE TABLE vinto_offline.rogue (x int)", "DROP TABLE vinto_offline.capture_receipt", "ALTER TABLE vinto_offline.capture_receipt ADD COLUMN x int",
            "DROP SCHEMA vinto_offline CASCADE", "CREATE SCHEMA rogue", "CREATE TABLE public.rogue (x int)",
            "ALTER TABLE vinto_offline.capture_receipt DISABLE TRIGGER ALL",
            "SELECT * FROM vinto_meta.schema_migration", "SELECT * FROM vinto_txn.capture", "INSERT INTO vinto_txn.capture DEFAULT VALUES",
            'UPDATE vinto_master."user" SET username = username', 'DELETE FROM vinto_master."user"', "UPDATE vinto_config.form SET code = code",
            "DELETE FROM vinto_audit.audit_event",
        ]
        for statement in denied:
            with pytest.raises(psycopg.errors.Error):
                c.execute(statement)
        assert c.execute("SELECT count(*) FROM vinto_offline.capture_receipt").fetchone()[0] == 1
        c.execute("GRANT SELECT ON vinto_offline.capture_receipt TO PUBLIC")  # PostgreSQL only WARNS when the grantor holds no grant option: nothing is granted
    with admin_conn(pilot_db) as admin:
        assert all(checks(admin).values()), checks(admin)


def test_database_triggers_keep_results_final_and_events_append_only_even_for_allowed_statements(pilot_db):
    with psycopg.connect(app_url(pilot_db), autocommit=True) as c:
        cid, user = str(uuid4()), str(uuid4())
        c.execute("INSERT INTO vinto_offline.capture_receipt (capture_id, author_user_id, device_key, form_code, form_version, machine_code, context_version, "
                  "payload_sha256, payload, outcome, response_status, response_body) VALUES (%s, %s, %s, 'VINTO-P1-22', 1, 'MP1', 'ctx', %s, '{}'::jsonb, 'accepted', 201, '{}'::jsonb)",
                  (cid, user, user, "b" * 64))
        with pytest.raises(psycopg.errors.Error):  # UPDATE is granted, but a final result and its identity are immutable
            c.execute("UPDATE vinto_offline.capture_receipt SET author_user_id = %s WHERE capture_id = %s", (str(uuid4()), cid))
        with pytest.raises(psycopg.errors.Error):
            c.execute("UPDATE vinto_offline.capture_receipt SET reason = 'x' WHERE capture_id = %s", (cid,))


# ------------------------------------------------------------------ rollback (preserves evidence)
def seed_one(name):
    with psycopg.connect(app_url(name), autocommit=True) as c:
        cid = str(uuid4())
        c.execute("INSERT INTO vinto_offline.capture_receipt (capture_id, author_user_id, device_key, form_code, form_version, machine_code, context_version, "
                  "payload_sha256, payload, outcome, response_status, response_body) VALUES (%s, %s, %s, 'VINTO-P1-22', 1, 'MP1', 'ctx', %s, '{}'::jsonb, 'accepted', 201, '{}'::jsonb)",
                  (cid, str(uuid4()), str(uuid4()), "c" * 64))
        c.execute("INSERT INTO vinto_offline.capture_event (capture_id, kind) VALUES (%s, 'received')", (cid,))
    return cid


def test_rollback_archives_the_schema_keeps_every_row_and_revokes_the_application_role(pilot_db, tree):
    cid = seed_one(pilot_db)
    with admin_conn(pilot_db) as c:
        run_script(c, OFFDIR / "proposed_0032_offline_capture_receipt.rollback.sql")
        assert c.execute("SELECT to_regnamespace('vinto_offline')").fetchone()[0] is None
        assert c.execute("SELECT count(*) FROM vinto_offline_archived.capture_receipt WHERE capture_id = %s", (cid,)).fetchone()[0] == 1
        assert c.execute("SELECT count(*) FROM vinto_offline_archived.capture_event").fetchone()[0] == 1
        assert not c.execute(f"SELECT has_schema_privilege('{APP_ROLE}', 'vinto_offline_archived', 'USAGE')").fetchone()[0]
        assert not c.execute(f"SELECT has_table_privilege('{APP_ROLE}', 'vinto_offline_archived.capture_receipt', 'SELECT')").fetchone()[0]
        migrate.validate_history(migrate.read_migrations(tree), migrate.applied_migrations(c))  # history is append-only and stays valid
    with psycopg.connect(app_url(pilot_db), autocommit=True) as c, pytest.raises(PilotConfigError, match="receiver_schema_missing"):
        verify_receiver_database(c)
    with psycopg.connect(app_url(pilot_db), autocommit=True) as c, pytest.raises(psycopg.errors.Error):
        c.execute("SELECT * FROM vinto_offline_archived.capture_receipt")


def test_rollback_refuses_when_something_outside_the_schema_depends_on_it(pilot_db):
    for ddl in ("CREATE TABLE public.ref_fk (cid uuid REFERENCES vinto_offline.capture_receipt (capture_id))",
                "CREATE VIEW public.v_receipts AS SELECT capture_id FROM vinto_offline.capture_receipt",
                "CREATE TABLE public.audited (x int); CREATE TRIGGER t_ext BEFORE INSERT ON public.audited FOR EACH ROW EXECUTE FUNCTION vinto_offline.guard_capture_event()"):
        with admin_conn(pilot_db) as c:
            c.execute(ddl)
            with pytest.raises(psycopg.errors.Error, match="rollback refused"):
                run_script(c, OFFDIR / "proposed_0032_offline_capture_receipt.rollback.sql")
            assert c.execute("SELECT to_regnamespace('vinto_offline')").fetchone()[0] is not None  # nothing moved
            assert c.execute("SELECT to_regnamespace('vinto_offline_archived')").fetchone()[0] is None
            c.execute("DROP VIEW IF EXISTS public.v_receipts; DROP TABLE IF EXISTS public.ref_fk; DROP TABLE IF EXISTS public.audited")


def test_rollback_refuses_a_second_run_a_missing_schema_and_a_non_owner(pilot_db):
    with admin_conn(pilot_db) as c:
        with c.transaction():
            c.execute(f"SET LOCAL ROLE {APP_ROLE}")
            with pytest.raises(psycopg.errors.Error):  # the application role neither owns the schema nor may rename it
                c.execute((OFFDIR / "proposed_0032_offline_capture_receipt.rollback.sql").read_text(encoding="utf-8").replace("BEGIN;", "").replace("COMMIT;", ""), prepare=False)
        assert c.execute("SELECT to_regnamespace('vinto_offline')").fetchone()[0] is not None
        run_script(c, OFFDIR / "proposed_0032_offline_capture_receipt.rollback.sql")
        with pytest.raises(psycopg.errors.Error, match="does not exist"):
            run_script(c, OFFDIR / "proposed_0032_offline_capture_receipt.rollback.sql")
        c.execute("CREATE SCHEMA vinto_offline")  # an earlier archive is never overwritten
        with pytest.raises(psycopg.errors.Error, match="already exists"):
            run_script(c, OFFDIR / "proposed_0032_offline_capture_receipt.rollback.sql")


# ------------------------------------------------------------------ entrypoint
def test_importing_the_entrypoint_builds_nothing():
    spec = importlib.util.spec_from_file_location("qa_pilot_main_fresh", BACKEND / "app" / "qa_pilot_main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert "app" not in vars(module)  # built lazily, on first access (uvicorn `module:app`) or via the factory


def never_connect():
    raise AssertionError("the inactive pilot must not open a database connection")


@pytest.mark.parametrize("env, app_env", [({}, "qa"), ({"OFFLINE_QA_PILOT_ENABLED": "0"}, "qa"), ({"OFFLINE_QA_PILOT_ENABLED": "false", "OFFLINE_QA_PILOT_GRANTS": json.dumps([GRANT])}, "qa"),
                                          (pilot_env(), "local"), (pilot_env(), "prod"), (pilot_env(), "test"), (pilot_env(), "ci"), (pilot_env(), "QA")])
def test_inactive_pilot_opens_no_connection_and_mounts_no_capture_route(env, app_env):
    app = create_app_from_env(env, app_env=app_env, connect=never_connect, principal_dependency=who)
    assert not [r for r in app.routes if getattr(r, "path", "").startswith("/api/offline")]
    client = TestClient(app)
    expected = 403 if app_env == "qa" else 404  # in QA the guard rejects every mutating call; elsewhere there is simply no route
    assert client.post("/api/offline/captures", json=cap(), headers=h()).status_code == expected
    assert client.get(f"/api/offline/captures/{uuid4()}", headers=h()).status_code == 404


def test_active_pilot_serves_the_receiver_as_the_restricted_application_role(pilot_db):
    app = create_app_from_env(pilot_env(), app_env="qa", connect=app_connect(pilot_db), principal_dependency=who)
    client = TestClient(app)
    body = cap()
    created = client.post("/api/offline/captures", json=body, headers=h())
    assert (created.status_code, created.json()["outcome"], created.json()["industrial_approval"]) == (201, "created", False)
    again = client.post("/api/offline/captures", json=body, headers=h())
    assert (again.status_code, again.json()["outcome"]) == (200, "duplicate")
    assert receipts(pilot_db) == 1
    conflict = client.post("/api/offline/captures", json=cap(payload={"numero_de_cuba": "C-2-SINT"}, capture_id=body["capture_id"]), headers=h())
    assert (conflict.status_code, conflict.json()["reason"]) == (409, C.R_PAYLOAD_MISMATCH)
    assert client.post("/api/offline/captures", json=cap(snapshot=SNAPSHOT_CONSULT), headers=h()).status_code == 403
    assert client.post("/api/offline/captures", json=cap()).status_code == 401
    assert receipts(pilot_db) == 1
    mine = client.get(f"/api/offline/captures/{body['capture_id']}", headers=h())
    assert mine.status_code == 200 and mine.json()["found"] is True
    # every other mutating request stays blocked in the live pilot app
    for method, path in (("POST", "/api/captures"), ("POST", "/api/offline/sync"), ("PUT", "/api/offline/captures"), ("DELETE", "/api/offline/captures"), ("POST", "/api/admin/users")):
        assert client.request(method, path, headers=h()).status_code == 403, (method, path)
    # no grant, no deny-by-default bypass: a user without a grant is refused and persists nothing
    other = uuid4()
    denied = client.post("/api/offline/captures", json=cap(author=other, snapshot=None), headers=h(other))
    assert (denied.status_code, denied.json()["reason"]) == (403, C.R_NOT_AUTHORIZED)
    assert receipts(pilot_db) == 1


def test_startup_refuses_every_unsafe_database_shape(pilot_db, plain_db):
    def start(name):
        return create_app_from_env(pilot_env(), app_env="qa", connect=app_connect(name), principal_dependency=who)

    with pytest.raises(PilotConfigError, match="receiver_schema_missing"):
        start(plain_db)  # migration not applied
    with pytest.raises(PilotConfigError, match="app_role_too_privileged"):
        create_app_from_env(pilot_env(), app_env="qa", connect=lambda: admin_conn(pilot_db), principal_dependency=who)
    mutations = {
        "app_role_can_create_in_schema": f"GRANT CREATE ON SCHEMA vinto_offline TO {APP_ROLE}",
        "app_role_has_excess_privilege": f"GRANT DELETE ON vinto_offline.capture_receipt TO {APP_ROLE}",
        "app_role_owns_receiver_tables": f"ALTER TABLE vinto_offline.capture_receipt OWNER TO {APP_ROLE}",
        "app_role_lacks_required_privilege": f"REVOKE UPDATE ON vinto_offline.capture_receipt FROM {APP_ROLE}",
        "receiver_guards_missing": "DROP TRIGGER capture_event_guard ON vinto_offline.capture_event",
        "app_role_can_create_in_database": f"GRANT CREATE ON DATABASE {{db}} TO {APP_ROLE}",
    }
    from app.ephemeral_db import copy_database, drop_database
    for code, statement in mutations.items():
        name = copy_database(pilot_db, "off045b03_mut")
        try:
            with admin_conn(name) as c:
                c.execute(statement.replace("{db}", f'"{name}"'))
            with pytest.raises(PilotConfigError, match=code):
                start(name)
        finally:
            drop_database(name)


class FakeConn:
    def __init__(self, name): self.name = name
    def execute(self, sql, params=()):
        outer = self
        class R:
            def fetchone(self_inner): return (outer.name,) if "current_database()" in sql and sql.startswith("SELECT current_database") else (False,)
        return R()


@pytest.mark.parametrize("name", ["vinto_prod", "vinto", "postgres", "vinto_mvp", "pilot", "vintoqa"])
def test_non_qa_database_names_are_refused_before_anything_else(name):
    with pytest.raises(PilotConfigError, match="database_not_isolated_qa"):
        verify_receiver_database(FakeConn(name))


def test_startup_failures_are_fixed_codes_and_never_echo_connection_details(caplog):
    secret = "postgresql://user:SuperSecretPw@db.invalid:5432/prod_db"

    def boom():
        raise psycopg.OperationalError(f"could not connect to {secret}")
    with caplog.at_level(logging.DEBUG), pytest.raises(PilotConfigError) as raised:
        create_app_from_env(pilot_env(), app_env="qa", connect=boom, principal_dependency=who)
    assert str(raised.value) == "database_unavailable" and raised.value.__cause__ is None
    assert "SuperSecretPw" not in caplog.text and "db.invalid" not in caplog.text and str(USER_A) not in caplog.text


def test_active_startup_logs_no_identifiers(pilot_db, caplog):
    with caplog.at_level(logging.DEBUG):
        create_app_from_env(pilot_env(), app_env="qa", connect=app_connect(pilot_db), principal_dependency=who)
    text = caplog.text
    assert "qa_pilot startup" in text
    for forbidden in (str(USER_A), pilot_db, APP_PASSWORD, "MP1", FORM):
        assert forbidden not in text


# ------------------------------------------------------------------ authz engine probe against PostgreSQL
class Engine:
    """The real central engine over a disposable reference database (users, profiles, sectors, machines, forms and grants are the repo's own)."""
    def __init__(self, name):
        from app.auth.machine_form_grants import grant_machine_form, revoke_machine_form
        from app.auth.service import create_user
        self.name, self.grant_fn, self.revoke_fn, self.create_user = name, grant_machine_form, revoke_machine_form, create_user
        self.c = admin_conn(name)
        self.admin = self.user("DATA_BALTREK")

    def user(self, profile="CALIDAD", sectors=("BOBINAS",)):
        return self.create_user(self.c, username=f"az.{uuid4().hex[:12]}", display_name="t", profile_code=profile, password="pw-" + uuid4().hex, sectors=sectors).user_id

    def grant(self, user, machine="MP1", form=FORM):
        self.grant_fn(self.c, user_id=user, machine_code=machine, form_code=form, actor_id=self.admin)

    def revoke(self, user, machine="MP1", form=FORM):
        self.revoke_fn(self.c, user_id=user, machine_code=machine, form_code=form, actor_id=self.admin)

    def probe(self):
        return AuthzEngineProbe(lambda: admin_conn(self.name))

    def grant_count(self):
        return self.c.execute("SELECT count(*) FROM vinto_master.user_machine_form_grant").fetchone()[0]


@pytest.fixture
def engine(pilot_db):
    e = Engine(pilot_db)
    yield e
    e.c.close()


def test_probe_follows_the_central_engine_on_real_data(engine):
    probe = engine.probe()
    granted, stranger, operator = engine.user(), engine.user(), engine.user("OPERACION")
    engine.grant(granted)
    engine.grant(operator)  # a grant alone does not replace the functional permission of the profile
    assert probe.allowed(principal(granted), "MP1", FORM) is True
    assert probe.allowed(principal(stranger), "MP1", FORM) is False  # different user, no grant
    assert probe.allowed(principal(operator), "MP1", FORM) is False  # grant without the quality permission
    assert probe.allowed(principal(granted), "MP3", FORM) is False  # other machine
    assert probe.allowed(principal(granted), "MP1", "VINTO-P1-26") is False  # other form
    assert probe.allowed(principal(uuid4()), "MP1", FORM) is False  # unknown user
    engine.revoke(granted)
    assert probe.allowed(principal(granted), "MP1", FORM) is False  # revoked


def test_probe_never_writes(engine):
    user = engine.user()
    engine.grant(user)
    before = engine.c.execute("SELECT (SELECT count(*) FROM vinto_master.user_machine_form_grant), (SELECT count(*) FROM vinto_audit.audit_event)").fetchone()
    engine.probe().allowed(principal(user), "MP1", FORM)
    engine.probe().allowed(principal(uuid4()), "MP1", FORM)
    assert engine.c.execute("SELECT (SELECT count(*) FROM vinto_master.user_machine_form_grant), (SELECT count(*) FROM vinto_audit.audit_event)").fetchone() == before


def make_pilot(engine, *, mode, grants=None, connect=None):
    env = {"OFFLINE_QA_PILOT_ENABLED": "1", "OFFLINE_QA_PILOT_AUTHZ_MODE": mode, "OFFLINE_QA_PILOT_GRANTS": json.dumps(grants if grants is not None else [GRANT])}
    return create_app_from_env(env, app_env="qa", connect=connect or app_connect(engine.name), principal_dependency=who)


def registry_grant_for(user, **over):
    return {**GRANT, "user_id": str(user), **over}


def post_as(client, user, **over):
    return client.post("/api/offline/captures", json=cap(author=user, **over), headers=h(user))


def test_modes_off_observe_enforce_with_the_real_engine(engine):
    both, registry_only, engine_only = engine.user(), engine.user(), engine.user()
    engine.grant(both)
    engine.grant(engine_only)
    registry = [registry_grant_for(both), registry_grant_for(registry_only)]
    results = {}
    for mode in ("off", "observe", "enforce"):
        client = TestClient(make_pilot(engine, mode=mode, grants=registry))
        results[mode] = {"both": post_as(client, both).status_code, "registry_only": post_as(client, registry_only).status_code,
                         "engine_only": post_as(client, engine_only).status_code}
    # the synthetic registry is ALWAYS required; the engine can only restrict, and only in enforce
    assert results["off"] == {"both": 201, "registry_only": 201, "engine_only": 403}
    assert results["observe"] == {"both": 201, "registry_only": 201, "engine_only": 403}  # observe: the engine is consulted and logged, nothing more
    assert results["enforce"] == {"both": 201, "registry_only": 403, "engine_only": 403}


def test_observe_never_grants_even_when_the_engine_allows(engine):
    user = engine.user()
    engine.grant(user)
    client = TestClient(make_pilot(engine, mode="observe", grants=[registry_grant_for(uuid4())]))  # the registry holds somebody else
    r = post_as(client, user)
    assert r.status_code == 403 and r.json()["reason"] in (C.R_NOT_AUTHORIZED, C.R_READ_ONLY_SCOPE)
    assert receipts(engine.name) == 0


def test_a_registry_grant_does_not_create_an_industrial_permission(engine):
    user = engine.user()
    before = engine.grant_count()
    client = TestClient(make_pilot(engine, mode="off", grants=[registry_grant_for(user)]))
    assert post_as(client, user).status_code == 201
    assert engine.grant_count() == before
    assert engine.probe().allowed(principal(user), "MP1", FORM) is False  # the central engine still denies: the pilot grant is not an industrial one


def test_engine_outage_denies_in_enforce_and_changes_nothing_in_observe(engine):
    user = engine.user()
    engine.grant(user)
    real = app_connect(engine.name)
    state = {"fail_next": 0}

    def connect():
        if state["fail_next"] > 0:  # armed right before a request: the engine's connection (the first one in the request) fails, the store's does not
            state["fail_next"] -= 1
            raise psycopg.OperationalError("engine unavailable")
        return real()

    for mode, expected in (("observe", 201), ("enforce", 403)):
        env = {"OFFLINE_QA_PILOT_ENABLED": "1", "OFFLINE_QA_PILOT_AUTHZ_MODE": mode, "OFFLINE_QA_PILOT_GRANTS": json.dumps([registry_grant_for(user)])}
        client = TestClient(create_app_from_env(env, app_env="qa", connect=connect, principal_dependency=who))
        state["fail_next"] = 1
        r = post_as(client, user)
        assert r.status_code == expected, mode
        assert state["fail_next"] == 0  # the failure really hit the engine, not something else
    # an engine that always fails is never an allow, whatever the mode
    broken = AuthzEngineProbe(lambda: (_ for _ in ()).throw(psycopg.OperationalError("down")))
    capture_like = type("Cap", (), dict(machine_code="MP1", form_code=FORM, form_version=1, scope_snapshot_id=SNAPSHOT_CAPTURE))()
    grants = (PilotGrant.model_validate(registry_grant_for(user)),)
    assert QaPilotAuthorizer(grants, engine=broken, engine_mode="enforce").authorize(principal(user), capture_like).allowed is False
    assert QaPilotAuthorizer(grants, engine=broken, engine_mode="observe").authorize(principal(user), capture_like).allowed is True  # the registry grant stands; observe never changes it
    assert receipts(engine.name) == 1  # only the observe-mode request persisted
