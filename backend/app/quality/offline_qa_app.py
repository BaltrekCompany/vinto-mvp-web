"""Explicit isolated QA FastAPI application for capture-only OFF-04.8.

This module is NOT imported from app.main. It cannot mount any operational
router outside QA, without an explicitly pinned trusted signing key, or on a
database other than the audited vinto_qa_offline. Both flags default OFF.

The separate application exposes only existing authentication and offline
readiness endpoints plus signed CAPTURE issuance and idempotent receiver.
No OT, administration, approvals, F3 creation, or release routers are mounted.
"""
from __future__ import annotations

from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.auth.router import router as auth_router
from app.offline_scope.router import router as readiness_router
from app.offline_scope.signing import SigningKey
from app.quality.offline_operational_router import create_operational_quality_router
from app.quality.offline_qa_capture_scope_router import create_qa_capture_scope_router

QA_DATABASE = "vinto_qa_offline"
WRITE_ALLOWLIST = frozenset({
    ("POST", "/api/auth/login"),
    ("POST", "/api/auth/logout"),
    ("POST", "/api/offline/scope"),
    ("POST", "/api/offline/quality-package"),
    ("POST", "/api/offline/bobbin-context"),
    ("POST", "/api/offline/capture-scope"),
    ("POST", "/api/offline/captures"),
})


class OfflineQaConfigurationError(RuntimeError):
    pass


def create_offline_qa_app(
    *, app_env: str = "", database_name: str = "",
    issue_enabled: bool = False, receive_enabled: bool = False,
    signer: SigningKey | None = None,
    open_connection: Callable | None = None,
    allowed_origin: str = "",
    trusted_public_key_b64url: str = "",
) -> FastAPI:
    """Build QA app; OFF flags never authorize a service on the wrong database.

    The separate QA deploy must supply a connection callable restricted to its
    QA database. Verify the REAL server-side database name on each activation.
    """
    if issue_enabled or receive_enabled:
        if app_env != "qa" or database_name != QA_DATABASE or not callable(open_connection):
            raise OfflineQaConfigurationError("qa_isolation_required")
        if signer is None or signer.public_b64url != trusted_public_key_b64url:
            raise OfflineQaConfigurationError("qa_capture_signer_required")
        if not allowed_origin.startswith("https://") or "/" in allowed_origin[8:]:
            raise OfflineQaConfigurationError("qa_origin_required")
        with open_connection() as connection:
            actual = connection.execute("SELECT current_database()").fetchone()[0]
        if actual != QA_DATABASE:
            raise OfflineQaConfigurationError("qa_database_identity_mismatch")

    app = FastAPI(title="VINTO Quality Offline QA isolated", docs_url=None,
                  redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def qa_guard(request: Request, call_next):
        path, method = request.url.path, request.method
        if method not in ("GET", "HEAD", "OPTIONS"):
            if (method, path) not in WRITE_ALLOWLIST or (
                path == "/api/offline/capture-scope" and not issue_enabled
            ) or (
                path == "/api/offline/captures" and not receive_enabled
            ):
                return JSONResponse(status_code=403, content={"detail":"Operación QA no disponible"})
            # CSRF: authenticated mutations must come from the exact QA origin.
            if request.headers.get("origin") != allowed_origin:
                return JSONResponse(status_code=403, content={"detail":"Origen no autorizado"})
        return await call_next(request)

    app.include_router(auth_router)
    app.include_router(readiness_router)
    if issue_enabled:
        app.include_router(create_qa_capture_scope_router(
            enabled=True, signer=signer, app_env=app_env,
            expected_qa_database=QA_DATABASE,
        ))
    if receive_enabled:
        app.include_router(create_operational_quality_router(
            enabled=True, open_connection=open_connection,
            trusted_public_key_b64url=trusted_public_key_b64url,
        ))
    return app
