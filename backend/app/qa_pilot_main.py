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
                        principal_dependency: Callable | None = None, connect: Callable[[], Any] | None = None,
                        identity_connect: Callable[[], Any] | None = None) -> FastAPI:
    """Build the pilot application from the environment. `connect`, `identity_connect` and `principal_dependency` exist so tests can inject disposable resources."""
    import os
    env = os.environ if env is None else env
    if app_env is None:
        from app.config import settings
        app_env = settings.app_env
    settings_ = PilotSettings.from_env(env, app_env=app_env)
    active = settings_.app_env == "qa" and settings_.enabled
    auth_active = settings_.app_env == "qa" and settings_.auth_enabled
    logger.info("qa_pilot startup: active=%s auth=%s authz_mode=%s grants=%d", active, auth_active, settings_.authz_mode, len(settings_.grants))
    if not active and not auth_active:
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
            receiver_role = connection.execute("SELECT current_user").fetchone()[0]
    except PilotConfigError:
        raise
    except Exception:  # driver or network failures: fixed code, never the driver's message (it may echo the connection)
        raise PilotConfigError("database_unavailable") from None
    mount = _build_auth_mount(settings_, identity_connect, database_name, receiver_role, principal_dependency) if auth_active else None
    engine = AuthzEngineProbe(connect) if settings_.authz_mode != "off" and active else None
    return create_qa_pilot_app(settings=settings_, store=PgOfflineCaptureStore(connect) if active else None, database_name=database_name if active else None,
                               principal_dependency=principal_dependency if mount is None else None, engine=engine, auth_mount=mount)


def _build_auth_mount(settings_: PilotSettings, identity_connect, database_name: str, receiver_role: str, principal_dependency):
    """Authentication conditions, all fail-closed with fixed codes: QA-exclusive cookie, DEDICATED identity connection that differs from the application
    URL and passes a privilege check, an Origin allow-list and a synthetic signing key that exists only for the pilot."""
    from app.config import settings as global_settings
    from app.database import identity_connection_mode
    from app.qa_pilot_auth import COOKIE_NAME_RE, build_auth_mount, parse_origins, signer_from_seed, verify_identity_database
    origins = parse_origins(settings_.origins_raw)
    signer = signer_from_seed(settings_.signing_seed)
    if not COOKIE_NAME_RE.fullmatch(global_settings.auth_cookie_name):
        raise PilotConfigError("cookie_name_not_qa_exclusive")
    if global_settings.app_env == "local":
        raise PilotConfigError("cookie_would_not_be_secure")   # cookie_options() marks the cookie Secure everywhere except APP_ENV=local
    if identity_connection_mode() != "dedicated":
        raise PilotConfigError("identity_connection_not_dedicated")
    identity_url = global_settings.identity_database_url.get_secret_value()
    if global_settings.database_url is not None and identity_url == global_settings.database_url.get_secret_value():
        raise PilotConfigError("identity_equals_application_url")
    try:
        with (identity_connect or connect_factory(identity_url))() as connection:
            verify_identity_database(connection, receiver_database=database_name, receiver_role=receiver_role)
    except PilotConfigError:
        raise
    except Exception:
        raise PilotConfigError("identity_database_unavailable") from None
    return build_auth_mount(grants=settings_.grants, signer=signer, origins=origins)


def create_app() -> FastAPI:
    return create_app_from_env()


def __getattr__(name: str):
    """`app` is built on first access, not at import: importing this module (tests, tooling) never reads the environment or touches a database."""
    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(name)
