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
from dataclasses import dataclass, field
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
ENV_AUTH_ENABLED = "OFFLINE_QA_PILOT_AUTH_ENABLED"
ENV_ORIGINS = "OFFLINE_QA_PILOT_ALLOWED_ORIGINS"
ENV_SIGNING_SEED = "OFFLINE_QA_PILOT_SIGNING_SEED_B64URL"
ENV_BOBBINS = "OFFLINE_QA_PILOT_BOBBINS"
MAX_GRANTS = 40
FORBIDDEN_BODY = {"detail": "Operación no disponible en QA offline"}


class PilotConfigError(Exception):
    """Invalid pilot configuration. Never carries values (grants hold user identifiers)."""


# ---------------------------------------------------------------- guard
PILOT_BOBBIN_CONTEXT_PATH = "/api/offline/bobbin-context"


def pilot_request_permitted(*, app_env: str, method: str, path: str, pilot_enabled: bool, auth_enabled: bool = False) -> bool:
    """The #219 guard (NOT widened), plus the pilot's own extra unsafe requests, only in QA: the capture POST with the pilot flag on, and (OFF-04.6) the read-only bobbin-context POST
    with the independent authentication flag on.

    Case-sensitive exact path: aliases, suffixes, trailing slashes, percent-encoded variants and every other mutating endpoint stay blocked.
    """
    if qa_offline_request_permitted(app_env=app_env, method=method, path=path):
        return True
    return app_env == "qa" and method == "POST" and ((pilot_enabled and path == PILOT_POST_PATH) or (auth_enabled and path == PILOT_BOBBIN_CONTEXT_PATH))


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
        from app.offline_quality.registry import operation_for
        operation = operation_for(form_code)   # machine route or bobbin route, as the online policy says; an unknown form is never allowed
        if operation is None:
            return False
        with self._open() as connection:
            with connection.transaction():
                return bool(authorize(connection, principal, operation, machine_code, form_code, lock=False).allowed)


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
    def __init__(self, grants: tuple[PilotGrant, ...], bobbins=()) -> None:
        self.grants = tuple(grants)
        self.bobbins = {str(b.bobbin_id): b for b in bobbins}

    def evaluate(self, capture) -> ContextVerdict:
        from app.offline_quality import bobbin_context
        from app.offline_quality.registry import BOBBIN, spec_for
        spec = spec_for(capture.form_code)
        if spec is not None and spec.kind == BOBBIN:
            # By-bobbin forms (OFF-04.6): the context is the SYNTHETIC bobbin the device prepared online. Same digest and `context_version` derivation as the real contexts.
            ref = capture.payload.get("bobbin") if isinstance(capture.payload, dict) else None
            bobbin = self.bobbins.get(str(ref.get("bobbin_id", "")).lower()) if isinstance(ref, dict) else None
            grant = next((g for g in self.grants if (g.machine_code, g.form_code, g.form_version) == (capture.machine_code, capture.form_code, capture.form_version)
                          and g.scope_snapshot_id is not None and g.scope_snapshot_id == capture.scope_snapshot_id), None)
            if bobbin is None or grant is None or bobbin.machine_code != capture.machine_code:
                return ContextVerdict("unverifiable")
            expected = bobbin_context.context_version(str(grant.scope_snapshot_id), str(bobbin.bobbin_id), bobbin.context()["context_digest"])
            return ContextVerdict("same") if expected == capture.context_version else ContextVerdict("incompatible_change")
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
    # OFF-04.5B-06B: independent authentication flag (off by default), Origin allow-list and the SYNTHETIC signing seed (never shown in a repr)
    auth_enabled: bool = False
    origins_raw: Optional[str] = field(default=None, repr=False)
    signing_seed: Optional[str] = field(default=None, repr=False)
    bobbins: tuple = ()     # OFF-04.6 synthetic bobbin contexts (the isolated QA database holds no industrial bobbin)

    @staticmethod
    def from_env(env: Mapping[str, str] | None = None, *, app_env: str) -> "PilotSettings":
        env = os.environ if env is None else env
        flag = env.get(ENV_ENABLED, "").strip().lower()
        if flag not in ("", "0", "1", "true", "false"):
            raise PilotConfigError("flag_invalid")
        mode = env.get(ENV_AUTHZ_MODE, "off").strip().lower() or "off"
        if mode not in ("off", "observe", "enforce"):
            raise PilotConfigError("authz_mode_invalid")
        auth_flag = env.get(ENV_AUTH_ENABLED, "").strip().lower()
        if auth_flag not in ("", "0", "1", "true", "false"):
            raise PilotConfigError("auth_flag_invalid")
        from app.offline_quality.synthetic import parse_bobbins
        try:
            bobbins = parse_bobbins(env.get(ENV_BOBBINS))
        except ValueError:
            raise PilotConfigError("bobbins_invalid") from None
        return PilotSettings(app_env=app_env, enabled=flag in ("1", "true"), authz_mode=mode, grants=parse_grants(env.get(ENV_GRANTS)),
                             auth_enabled=auth_flag in ("1", "true"), origins_raw=env.get(ENV_ORIGINS), signing_seed=env.get(ENV_SIGNING_SEED),
                             bobbins=bobbins)


# ---------------------------------------------------------------- application factory
def create_qa_pilot_app(*, settings: PilotSettings, store: OfflineCaptureStore | None, database_name: str | None,
                        principal_dependency: Callable | None = None, engine: EngineProbe | None = None, auth_mount: Any = None,
                        validator: Any = None) -> FastAPI:
    """A SEPARATE application, never `app.main`. The receiver router exists only if every activation condition holds; otherwise the app has no capture route
    at all (every call 404, and in QA every mutating call 403 by the guard)."""
    active = settings.app_env == "qa" and settings.enabled
    auth_active = settings.app_env == "qa" and settings.auth_enabled
    allowed_origins = tuple(auth_mount.allowed_origins) if (auth_active and auth_mount is not None) else ()
    app = FastAPI(title="VINTO QA synthetic pilot receiver", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def qa_pilot_write_guard(request: Request, call_next):
        if not pilot_request_permitted(app_env=settings.app_env, method=request.method, path=request.url.path, pilot_enabled=active, auth_enabled=auth_active):
            return JSONResponse(status_code=403, content=FORBIDDEN_BODY, headers={"Cache-Control": "no-store"})
        # CSRF defence for authenticated writes (together with the SameSite cookie): the Origin header must be present and EXACTLY one allowed origin.
        if auth_active and request.method in ("POST", "PUT", "PATCH", "DELETE") and request.headers.get("origin") not in allowed_origins:
            return JSONResponse(status_code=403, content={"detail": "Origen no permitido"}, headers={"Cache-Control": "no-store"})
        return await call_next(request)

    if auth_active:
        if auth_mount is None:
            raise PilotConfigError("auth_mount_required")
        if not settings.grants:
            raise PilotConfigError("grants_required")
        app.dependency_overrides.update(auth_mount.dependency_overrides)
        for router in auth_mount.routers:
            app.include_router(router)
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
    context: ContextProvider = PilotContext(settings.grants, settings.bobbins)
    app.include_router(create_offline_capture_router(store=store, enabled=True, authorizer=authorizer, context=context, principal_dependency=principal_dependency, validator=validator))
    return app
