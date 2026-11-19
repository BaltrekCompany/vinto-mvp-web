"""OFF-04.4 test support: synthetic principals, authoriser/context doubles, flaky store, and the stores under test.

Everything is synthetic and runs against a DISPOSABLE database (SQLite file, or a throwaway PostgreSQL: CI service via
OFF044_PG_URL, or a user-space instance of the `pgserver` package). Nothing connects to a real or deployed database.
"""
import os
import pathlib
import tempfile
from uuid import UUID, uuid4

import psycopg
from fastapi import FastAPI, Header, HTTPException
from pydantic import SecretStr  # noqa: F401  (kept for parity with sibling tests)

from app.auth.service import AuthenticatedUser
from app.db_guard import assert_test_database
from app.offline_capture import contract as C
from app.offline_capture.router import create_offline_capture_router
from app.offline_capture.service import AuthzDecision, ContextVerdict
from app.offline_capture.store import PgOfflineCaptureStore, SqliteOfflineCaptureStore, StoreUnavailable

USER_A = UUID("11111111-1111-4111-8111-111111111111")
USER_B = UUID("22222222-2222-4222-8222-222222222222")
DEVICE = UUID("33333333-3333-4333-8333-333333333333")
SNAPSHOT_CONSULT = UUID("44444444-4444-4444-8444-444444444444")     # readiness-only snapshot
SNAPSHOT_CAPTURE = UUID("55555555-5555-4555-8555-555555555555")
DDL = pathlib.Path(__file__).resolve().parents[1] / "offline_capture_migration" / "proposed_0032_offline_capture_receipt.sql"


def principal(user_id: UUID) -> AuthenticatedUser:
    return AuthenticatedUser(user_id=user_id, username="synthetic." + str(user_id)[:4], display_name="Synthetic", profile_codes=("CALIDAD",),
                             permissions=frozenset(), must_change=False)


class SyntheticAuthorizer:
    """Explicit grants only. A readiness-only (consultation) snapshot NEVER authorises, whatever grants exist."""
    def __init__(self, grants=None, readonly_snapshots=(SNAPSHOT_CONSULT,)):
        self.grants = set(grants if grants is not None else {(USER_A, "MP1", "VINTO-P1-26"), (USER_B, "MP1", "VINTO-P1-26")})
        self.readonly = set(readonly_snapshots)

    def authorize(self, who, capture):
        if capture.scope_snapshot_id in self.readonly:
            return AuthzDecision(False, C.R_READ_ONLY_SCOPE)
        return AuthzDecision((who.user_id, capture.machine_code, capture.form_code) in self.grants, None if (who.user_id, capture.machine_code, capture.form_code) in self.grants else C.R_NOT_AUTHORIZED)


class ScriptedContext:
    """`ctx-1` is current; other versions map to a verdict kind (default: incompatible)."""
    def __init__(self, table=None, default="incompatible_change"):
        self.default = default
        self.table = {"ctx-1": "same", "ctx-compat": "compatible_change", "ctx-incompat": "incompatible_change", "ctx-oldform": "unknown_form_version",
                      "ctx-unknown": "unverifiable", **(table or {})}

    def evaluate(self, capture):
        return ContextVerdict(self.table.get(capture.context_version, self.default))


class FlakyStore:
    """Delegates to a real store but fails the next `fail` transactions with a temporary error (nothing committed)."""
    def __init__(self, inner):
        self.inner, self.fail = inner, 0

    def transaction(self):
        if self.fail > 0:
            self.fail -= 1
            raise StoreUnavailable("injected")
        return self.inner.transaction()

    def get(self, capture_id):
        if self.fail > 0:
            self.fail -= 1
            raise StoreUnavailable("injected")
        return self.inner.get(capture_id)


def build_app(store, *, enabled=True, authorizer=None, context=None) -> FastAPI:
    """Test-only app: the principal comes from a synthetic header (absent = no valid session). Not the operational app."""
    def who(x_synthetic_user: str | None = Header(default=None)) -> AuthenticatedUser:
        if not x_synthetic_user:
            raise HTTPException(status_code=401, detail="No autenticado")
        return principal(UUID(x_synthetic_user))
    app = FastAPI()
    app.include_router(create_offline_capture_router(store=store, enabled=enabled, authorizer=authorizer or SyntheticAuthorizer(),
                                                    context=context or ScriptedContext(), principal_dependency=who))
    return app


def capture(payload=None, *, capture_id=None, author=USER_A, context="ctx-1", snapshot=SNAPSHOT_CAPTURE, machine="MP1", form="VINTO-P1-26", **over) -> dict:
    body = {"synthetic": True, "payload": payload or {"numero_de_cuba": "C-1-SINT", "masa_g": "101"}}
    base = {"capture_id": str(capture_id or uuid4()), "author_user_id": str(author), "device_key": str(DEVICE), "form_code": form, "form_version": 1,
            "machine_code": machine, "scope_snapshot_id": str(snapshot) if snapshot else None, "context_version": context,
            "payload_sha256": C.canonical_sha256(body), "payload": body}
    base.update(over)
    return base


def h(user=USER_A) -> dict:
    return {"X-Synthetic-User": str(user)}


# ------------------------------------------------------------------------------------------------ stores under test
_PG = {}


def _pg_url() -> str | None:
    url = os.environ.get("OFF044_PG_URL")
    if url:
        return url
    try:
        import pgserver
    except ImportError:
        return None
    if "srv" not in _PG:
        _PG["dir"] = tempfile.mkdtemp(prefix="vinto-off044-pg-")
        _PG["srv"] = pgserver.get_server(pathlib.Path(_PG["dir"]), cleanup_mode="stop")
    return _PG["srv"].get_uri()


def pg_available() -> bool:
    return _pg_url() is not None


def make_pg_store() -> PgOfflineCaptureStore:
    """A brand-new *_test database per call, with the PROPOSED DDL applied (never the operational schema)."""
    base = _pg_url()
    name = "off044_" + uuid4().hex[:10] + "_test"
    admin = psycopg.connect(base, autocommit=True)
    # the proposed DDL grants to the application role (OFF-04.5B-03); in a throwaway cluster that role may not exist yet
    admin.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_app') THEN CREATE ROLE vinto_app NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE; END IF; END $$")
    admin.execute(f'CREATE DATABASE "{name}"')
    admin.close()
    url = psycopg.conninfo.make_conninfo(base, dbname=name)
    with psycopg.connect(url, autocommit=True) as c:
        assert_test_database(c)
        c.execute(DDL.read_text(encoding="utf-8"), prepare=False)
    return PgOfflineCaptureStore(lambda: psycopg.connect(url))


def make_sqlite_store(path=None) -> SqliteOfflineCaptureStore:
    return SqliteOfflineCaptureStore(path or os.path.join(tempfile.mkdtemp(prefix="vinto-off044-"), "receipts.sqlite"))
