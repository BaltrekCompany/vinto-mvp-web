"""OFF-04.5B-06B shared test support: a DISPOSABLE migrated PostgreSQL database that reproduces the QA role split.

  * `vinto_app`      : only what migration 0032 grants it (the receiver tables) - NO identity privileges at all;
  * `vinto_identity` : the grants of backend/roles/03c_d3b2_identity_role_grants.sql (login/session/credential), nothing on the receiver.

Used by the pytest suite and by the Chrome end-to-end server. Synthetic identities and passwords only; never a deployed database.
"""
import base64
import contextlib
import io
import os
import pathlib
import re
import shutil
import tempfile
from uuid import UUID, uuid4

import psycopg
from psycopg.conninfo import make_conninfo

BACKEND = pathlib.Path(__file__).resolve().parents[1]
APP_ROLE, APP_PASSWORD = "vinto_app", "app-throwaway-not-a-secret"
ID_ROLE, ID_PASSWORD = "vinto_identity", "identity-throwaway-not-a-secret"
PASSWORD_A, PASSWORD_B = "synthetic-password-A-1234", "synthetic-password-B-5678"
MACHINE, FORM, CONTEXT = "MP1", "VINTO-P1-22", "ctx-1"
SNAPSHOT = UUID("55555555-5555-4555-8555-555555555555")


def load_promote():
    import importlib.util
    spec = importlib.util.spec_from_file_location("promote_0032", BACKEND / "offline_capture_migration" / "promote_0032.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ensure_roles() -> None:
    from app.ephemeral_db import _admin
    with _admin() as admin:
        for role, password in ((APP_ROLE, APP_PASSWORD), (ID_ROLE, ID_PASSWORD)):
            admin.execute(f"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN CREATE ROLE {role} LOGIN PASSWORD '{password}'; END IF; END $$")
            admin.execute(f"ALTER ROLE {role} LOGIN PASSWORD '{password}' NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT")
        admin.execute(f"ALTER ROLE {APP_ROLE} SET search_path = ''")


def drop_roles() -> None:
    from app.ephemeral_db import _admin
    with _admin() as admin:
        for role in (APP_ROLE, ID_ROLE):
            try:
                admin.execute(f"DROP ROLE IF EXISTS {role}")
            except psycopg.Error:
                pass


def build_template() -> str:
    """Reference template (31 migrations + bundle) + the PROMOTED 0032 (from a temporary tree) + the identity role grants. Copies of it are the test databases."""
    import migrate
    from app.ephemeral_db import build_reference_template, connect
    ensure_roles()
    name = build_reference_template("off06b_base")
    tree = pathlib.Path(tempfile.mkdtemp(prefix="off06b-migrations-"))
    try:
        for path in (BACKEND / "migrations").glob("*.sql"):
            shutil.copy(path, tree / path.name)
        load_promote().promote(tree)
        grants = "\n".join(line for line in (BACKEND / "roles" / "03c_d3b2_identity_role_grants.sql").read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("\\"))
        with connect(name) as connection:
            with contextlib.redirect_stdout(io.StringIO()):
                migrate.apply(connection, migrate.read_migrations(tree))
            connection.execute(grants, prepare=False)
            # OFF-04.6: the central validation reads the published definitions with the APPLICATION role (the real QA role already has exactly this read access); never identity tables
            connection.execute("GRANT USAGE ON SCHEMA vinto_master, vinto_config TO vinto_app")
            connection.execute("GRANT SELECT ON vinto_master.machine, vinto_master.sector, vinto_master.unit TO vinto_app")
            connection.execute("GRANT SELECT ON ALL TABLES IN SCHEMA vinto_config TO vinto_app")
    finally:
        shutil.rmtree(tree, ignore_errors=True)
    return name


def url_for(name: str, role: str, password: str) -> str:
    from app.ephemeral_db import database_url
    return make_conninfo(database_url(name), user=role, password=password)


def app_url(name: str) -> str:
    return url_for(name, APP_ROLE, APP_PASSWORD)


def identity_url(name: str) -> str:
    return url_for(name, ID_ROLE, ID_PASSWORD)


def create_users(name: str) -> dict:
    """Two synthetic users with real credentials (Argon2id) created by the repository's own `create_user`, as the database superuser of the test cluster."""
    from app.auth.service import create_user
    from app.ephemeral_db import connect
    out = {}
    with connect(name) as connection:
        for label, password in (("a", PASSWORD_A), ("b", PASSWORD_B)):
            created = create_user(connection, username=f"qa.pilot.{label}.{uuid4().hex[:6]}", display_name=f"Synthetic {label}", profile_code="CALIDAD",
                                  password=password, sectors=("BOBINAS",))
            out[label] = {"id": created.user_id, "username": created.username, "password": password}
    return out


def new_seed() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode()


def grant_for(user_id, **over) -> dict:
    g = {"user_id": str(user_id), "machine_code": MACHINE, "form_code": FORM, "form_version": 2, "synthetic": True, "scope_snapshot_id": str(SNAPSHOT), "context_version": CONTEXT}
    g.update(over)
    return g
