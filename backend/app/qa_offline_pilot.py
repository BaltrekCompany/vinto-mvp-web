"""OFF-04.5B — Synthetic physical-pilot receiver for the isolated QA API. NOT part of `app.main`; nothing here is mounted by default.

What this module is: a factory for a SEPARATE FastAPI application that exposes the OFF-04.4 receiver (`/api/offline/captures`) only when ALL of
these hold at creation time:
  1. APP_ENV == "qa";
  2. the dedicated pilot flag OFFLINE_QA_PILOT_ENABLED is on (default off);
  3. the receiver's database is an isolated QA / disposable database (name check);
  4. an explicit synthetic grant registry is supplied (user + machine + form + version), never derived from a readiness-only package.
Per request, the OFF-04.4 service additionally requires a valid session (401), that the authenticated user is the capture's ORIGINAL author (403),
and a matching synthetic grant (403). `observe` mode of the authz engine is logged only and NEVER grants; `enforce` can only RESTRICT further.
Every other mutating request is rejected with 403 by the same guard that OFF-03D.7A (#219) introduced for the QA API.

Industrial capture is not enabled by any of this: the technical receipt it produces always carries industrial_approval=false.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Optional, Protocol
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError
from typing import Annotated

from app.offline_capture import contract as C
from app.offline_capture.router import create_offline_capture_router
from app.offline_capture.service import AuthzDecision, CaptureAuthorizer, ContextProvider, ContextVerdict
from app.offline_capture.store import OfflineCaptureStore
from app.qa_offline_guard import qa_offline_request_permitted

logger = logging.getLogger("vinto.qa_pilot")

PILOT_POST_PATH = "/api/offline/captures"
ENV_ENABLED = "OFFLINE_QA_PILOT_ENABLED"
ENV_GRANTS = "OFFLINE_QA_PILOT_GRANTS"
ENV_AUTHZ_MODE = "OFFLINE_QA_PILOT_AUTHZ_MODE"
MAX_GRANTS = 20
FORBIDDEN_BODY = {"detail": "Operación no disponible en QA offline"}


class PilotConfigError(Exception):
    """Invalid pilot configuration. Never carries values (grants hold user identifiers)."""


# ---------------------------------------------------------------- guard
def pilot_request_permitted(*, app_env: str, method: str, path: str, pilot_enabled: bool) -> bool:
    """The #219 guard, plus exactly one extra unsafe request, only in QA and only with the pilot flag on.

    Case-sensitive exact path: aliases, suffixes, trailing slashes, percent-encoded variants and every other mutating endpoint stay blocked.
    """
    if qa_offline_request_permitted(app_env=app_env, method=method, path=path):
        return True
    return app_env == "qa" and pilot_enabled and method == "POST" and path == PILOT_POST_PATH


# ---------------------------------------------------------------- grants
class PilotGrant(BaseModel):
    """One explicit, SYNTHETIC authorisation: one user, one machine, one form version. Strict: unknown keys are refused."""
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    user_id: UUID
    machine_code: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,48}$")]
    form_code: Annotated[str, StringConstraints(pattern=r"^VINTO-[A-Z0-9-]{2,40}$")]
    form_version: int = Field(ge=1, le=10_000)
    synthetic: Literal[True]
    scope_snapshot_id: Optional[UUID] = None
    context_version: Optional[Annotated[str, StringConstraints(min_length=1, max_length=64)]] = None


def parse_grants(raw: str | list | None) -> tuple[PilotGrant, ...]:
    if raw is None or raw == "":
        return ()
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(data, list) or len(data) > MAX_GRANTS:
            raise ValueError("shape")
        return tuple(PilotGrant.model_validate(item) for item in data)
    except (ValueError, ValidationError):
        raise PilotConfigError("grants_invalid") from None


# ---------------------------------------------------------------- authz engine port
class EngineProbe(Protocol):
    """Port to the central authz engine. Returns True only for an explicit allow; anything else (deny, missing, outage) must raise or return False."""
    def allowed(self, principal: Any, machine_code: str, form_code: str) -> bool: ...


class AuthzEngineProbe:
    """Adapter over `app.authz.engine.authorize` for Calidad-by-machine captures. Reads only; changes no industrial permission."""
    def __init__(self, open_connection: Callable[[], Any]) -> None:
        self._open = open_connection

    def allowed(self, principal, machine_code, form_code) -> bool:
        from app.authz.engine import authorize
        from app.authz.policies import Operation
        with self._open() as connection:
            with connection.transaction():
                return bool(authorize(connection, principal, Operation.QUALITY_MACHINE_CAPTURE, machine_code, form_code, lock=False).allowed)


AuthzMode = Literal["off", "observe", "enforce"]


class QaPilotAuthorizer:
    """Explicit synthetic grants only. A read-only (consultation) snapshot never authorises: the capture's snapshot must be exactly the grant's.

    `engine_mode`: off = engine ignored; observe = engine consulted and LOGGED, never grants and never changes the decision;
    enforce = engine must ALSO allow (it can only restrict). The grant is always required.
    """
    def __init__(self, grants: tuple[PilotGrant, ...], *, engine: EngineProbe | None = None, engine_mode: AuthzMode = "off") -> None:
        if engine_mode not in ("off", "observe", "enforce"):
            raise PilotConfigError("authz_mode_invalid")
        if engine_mode != "off" and engine is None:
            raise PilotConfigError("engine_required")
        self.grants, self.engine, self.mode = tuple(grants), engine, engine_mode

    def authorize(self, principal, capture) -> AuthzDecision:
        candidates = [g for g in self.grants if g.user_id == principal.user_id and g.machine_code == capture.machine_code
                      and g.form_code == capture.form_code and g.form_version == capture.form_version]
        if not any(g.scope_snapshot_id == capture.scope_snapshot_id for g in candidates):
            return AuthzDecision(False, C.R_READ_ONLY_SCOPE if capture.scope_snapshot_id else C.R_NOT_AUTHORIZED)
        if self.mode != "off":
            verdict = self._engine_verdict(principal, capture)
            if self.mode == "observe":
                logger.info("qa_pilot authz observe: engine_allowed=%s (no effect on the decision)", verdict)
            elif not verdict:
                return AuthzDecision(False, C.R_NOT_AUTHORIZED)
        return AuthzDecision(True)

    def _engine_verdict(self, principal, capture) -> bool:
        try:
            return bool(self.engine.allowed(principal, capture.machine_code, capture.form_code))
        except Exception:  # an engine outage is never an allow
            logger.warning("qa_pilot authz engine unavailable (treated as not allowed)")
            return False


class PilotContext:
    """No industrial context is evaluated in the pilot: a capture is `same` only if the grant pins that exact synthetic context, else `unverifiable`
    (central review). Never reports a change as compatible."""
    def __init__(self, grants: tuple[PilotGrant, ...]) -> None:
        self.grants = tuple(grants)

    def evaluate(self, capture) -> ContextVerdict:
        for g in self.grants:
            if (g.machine_code, g.form_code, g.form_version, g.context_version) == (capture.machine_code, capture.form_code, capture.form_version, capture.context_version) \
                    and g.context_version is not None:
                return ContextVerdict("same")
        return ContextVerdict("unverifiable")


# ---------------------------------------------------------------- isolation
_QA_DB_RE = re.compile(r"^(?:[a-z0-9_]*_)?qa(?:_[a-z0-9_]*)?$|^[a-z0-9_]+_test$")


def is_isolated_qa_database_name(name: str) -> bool:
    """QA or disposable test database names only. The operational databases never match."""
    return bool(name) and _QA_DB_RE.match(name.lower()) is not None


def pg_store_database_name(store) -> str:
    """Ask PostgreSQL for the REAL database name behind a PgOfflineCaptureStore (does not trust the connection string)."""
    with store.transaction() as tx:
        return tx.c.execute("SELECT current_database()").fetchone()[0]


# ---------------------------------------------------------------- settings
@dataclass(frozen=True)
class PilotSettings:
    app_env: str
    enabled: bool
    authz_mode: AuthzMode
    grants: tuple[PilotGrant, ...]

    @staticmethod
    def from_env(env: Mapping[str, str] | None = None, *, app_env: str) -> "PilotSettings":
        env = os.environ if env is None else env
        flag = env.get(ENV_ENABLED, "").strip().lower()
        if flag not in ("", "0", "1", "true", "false"):
            raise PilotConfigError("flag_invalid")
        mode = env.get(ENV_AUTHZ_MODE, "off").strip().lower() or "off"
        if mode not in ("off", "observe", "enforce"):
            raise PilotConfigError("authz_mode_invalid")
        return PilotSettings(app_env=app_env, enabled=flag in ("1", "true"), authz_mode=mode, grants=parse_grants(env.get(ENV_GRANTS)))


# ---------------------------------------------------------------- application factory
def create_qa_pilot_app(*, settings: PilotSettings, store: OfflineCaptureStore | None, database_name: str | None,
                        principal_dependency: Callable | None = None, engine: EngineProbe | None = None) -> FastAPI:
    """A SEPARATE application, never `app.main`. The receiver router exists only if every activation condition holds; otherwise the app has no capture route
    at all (every call 404, and in QA every mutating call 403 by the guard)."""
    active = settings.app_env == "qa" and settings.enabled
    app = FastAPI(title="VINTO QA synthetic pilot receiver", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def qa_pilot_write_guard(request: Request, call_next):
        if not pilot_request_permitted(app_env=settings.app_env, method=request.method, path=request.url.path, pilot_enabled=active):
            return JSONResponse(status_code=403, content=FORBIDDEN_BODY, headers={"Cache-Control": "no-store"})
        return await call_next(request)

    if not active:
        return app
    # Activation conditions that must hold at startup; any failure raises (fail closed: the pilot does not start half-configured).
    if store is None:
        raise PilotConfigError("store_required")
    if not settings.grants:
        raise PilotConfigError("grants_required")
    if not database_name or not is_isolated_qa_database_name(database_name):
        raise PilotConfigError("database_not_isolated_qa")
    if principal_dependency is None:
        from app.auth.dependencies import current_user
        principal_dependency = current_user
    authorizer: CaptureAuthorizer = QaPilotAuthorizer(settings.grants, engine=engine, engine_mode=settings.authz_mode)
    context: ContextProvider = PilotContext(settings.grants)
    app.include_router(create_offline_capture_router(store=store, enabled=True, authorizer=authorizer, context=context, principal_dependency=principal_dependency))
    return app
