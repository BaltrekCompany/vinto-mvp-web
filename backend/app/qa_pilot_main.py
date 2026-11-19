"""OFF-04.5B-03 — ASGI entrypoint of the synthetic QA pilot receiver. NOT `app.main`; nothing here is imported by the operational application.

Run (only in a future, explicitly authorised installation):  uvicorn app.qa_pilot_main:app   or   uvicorn --factory app.qa_pilot_main:create_app

Default behaviour: with OFFLINE_QA_PILOT_ENABLED unset/off, or APP_ENV other than `qa`, building the application opens NO database connection and mounts NO
capture route (every mutating request is rejected by the QA guard). Only when every activation condition holds does it connect, with the application role's
connection string (DATABASE_URL, never an identity/migrator/admin URL), and verify the REAL database and role before mounting anything. The application role never reads the migration history (vinto_meta is closed to it by design): migration history/checksums are verified by the operator with
the migrator role (`migrate.py --check`, proposed_0032 verification script). Any failed check raises
`PilotConfigError` with a fixed code: the process does not start half-configured. Messages and logs never contain connection strings, role or database names,
user identifiers or grants.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Mapping

from fastapi import FastAPI

from app.offline_capture.store import PgOfflineCaptureStore
from app.qa_offline_pilot import (AuthzEngineProbe, PilotConfigError, PilotSettings, create_qa_pilot_app, is_isolated_qa_database_name)

logger = logging.getLogger("vinto.qa_pilot")

STATEMENT_TIMEOUT_MS = 10_000
LOCK_TIMEOUT_MS = 5_000
CONNECT_TIMEOUT_S = 5


def connect_factory(url: str) -> Callable[[], Any]:
    """Application-role connections with bounded timeouts. psycopg is imported lazily so the inactive path never needs a driver or a database."""
    import psycopg
    options = f"-c statement_timeout={STATEMENT_TIMEOUT_MS} -c lock_timeout={LOCK_TIMEOUT_MS}"
    return lambda: psycopg.connect(url, connect_timeout=CONNECT_TIMEOUT_S, options=options)


def verify_receiver_database(connection) -> str:
    """Check the REAL connected database and role (PostgreSQL's answers, not the connection string). Returns the database name for the caller's own use only;
    it is never logged. Raises PilotConfigError(<fixed code>) on the first failed attribute."""
    def one(sql: str, params: tuple = ()):
        return connection.execute(sql, params).fetchone()[0]

    name = one("SELECT current_database()")
    if not is_isolated_qa_database_name(name):
        raise PilotConfigError("database_not_isolated_qa")
    if one("SELECT pg_is_in_recovery()"):
        raise PilotConfigError("database_is_replica")
    role = connection.execute("SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = current_user").fetchone()
    if role is None or any(role):
        raise PilotConfigError("app_role_too_privileged")
    if one("SELECT has_database_privilege(current_user, current_database(), 'CREATE')"):
        raise PilotConfigError("app_role_can_create_in_database")
    if not one("SELECT to_regclass('vinto_offline.capture_receipt') IS NOT NULL AND to_regclass('vinto_offline.capture_event') IS NOT NULL"):
        raise PilotConfigError("receiver_schema_missing")
    if one("SELECT has_schema_privilege(current_user, 'vinto_offline', 'CREATE')"):
        raise PilotConfigError("app_role_can_create_in_schema")
    for table in ("vinto_offline.capture_receipt", "vinto_offline.capture_event"):
        if one("SELECT pg_has_role(current_user, relowner, 'MEMBER') FROM pg_class WHERE oid = %s::regclass", (table,)):
            raise PilotConfigError("app_role_owns_receiver_tables")
        for privilege in ("DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
            if one("SELECT has_table_privilege(current_user, %s::regclass, %s)", (table, privilege)):
                raise PilotConfigError("app_role_has_excess_privilege")
    if not one("SELECT has_table_privilege(current_user, 'vinto_offline.capture_receipt', 'INSERT') "
               "AND has_table_privilege(current_user, 'vinto_offline.capture_receipt', 'UPDATE') "
               "AND has_table_privilege(current_user, 'vinto_offline.capture_event', 'INSERT')"):
        raise PilotConfigError("app_role_lacks_required_privilege")
    if one("SELECT count(*) FROM pg_trigger WHERE tgname IN ('capture_receipt_guard', 'capture_event_guard') AND NOT tgisinternal") != 2:
        raise PilotConfigError("receiver_guards_missing")
    return name


def create_app_from_env(env: Mapping[str, str] | None = None, *, app_env: str | None = None, database_url: str | None = None,
                        principal_dependency: Callable | None = None, connect: Callable[[], Any] | None = None) -> FastAPI:
    """Build the pilot application from the environment. `connect` and `principal_dependency` exist so tests can inject disposable resources."""
    import os
    env = os.environ if env is None else env
    if app_env is None:
        from app.config import settings
        app_env = settings.app_env
    settings_ = PilotSettings.from_env(env, app_env=app_env)
    active = settings_.app_env == "qa" and settings_.enabled
    logger.info("qa_pilot startup: active=%s authz_mode=%s grants=%d", active, settings_.authz_mode, len(settings_.grants))
    if not active:
        return create_qa_pilot_app(settings=settings_, store=None, database_name=None, principal_dependency=principal_dependency)
    if connect is None:
        if database_url is None:
            from app.config import settings
            if settings.database_url is None or not settings.database_url.get_secret_value():
                raise PilotConfigError("database_url_missing")
            database_url = settings.database_url.get_secret_value()
        connect = connect_factory(database_url)
    try:
        with connect() as connection:
            database_name = verify_receiver_database(connection)
    except PilotConfigError:
        raise
    except Exception:  # driver or network failures: fixed code, never the driver's message (it may echo the connection)
        raise PilotConfigError("database_unavailable") from None
    engine = AuthzEngineProbe(connect) if settings_.authz_mode != "off" else None
    return create_qa_pilot_app(settings=settings_, store=PgOfflineCaptureStore(connect), database_name=database_name,
                               principal_dependency=principal_dependency, engine=engine)


def create_app() -> FastAPI:
    return create_app_from_env()


def __getattr__(name: str):
    """`app` is built on first access, not at import: importing this module (tests, tooling) never reads the environment or touches a database."""
    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(name)
