"""OFF-04.8 QA-only CAPTURE-scope issuance. Not mounted in app.main.

Unlike /api/offline/scope (readiness-only), this endpoint issues a signed
CAPTURE authority registered atomically in vinto_offline. A signed envelope
never replaces current MF-13 enforce at operational sync time.

The factory defaults to disabled, and requires explicit QA DB identity and
a separately provisioned CAPTURE signing key. No fallbacks or implicit grants.
"""
from __future__ import annotations

from typing import Callable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from typing import Annotated
from pydantic import StringConstraints

from app.auth.dependencies import current_user
from app.auth.service import AuthenticatedUser
from app.database import get_connection
from app.offline_scope.signing import SigningKey
from app.quality.offline_capture_authority import CaptureScopeDenied, issue_capture_scope

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_QA_DB = "vinto_qa_offline"


class CaptureScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    device_key: UUID
    machine_codes: list[Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,48}$")]] = Field(
        min_length=1, max_length=25
    )


def create_qa_capture_scope_router(
    *, enabled: bool = False, signer: SigningKey | None = None,
    expected_qa_database: str = _QA_DB, app_env: str = "",
    principal_dependency: Callable = current_user,
    connection_dependency: Callable = get_connection,
) -> APIRouter:
    router = APIRouter(prefix="/api/offline", tags=["Offline Calidad QA — CAPTURE"])
    active = enabled and app_env == "qa" and signer is not None and expected_qa_database == _QA_DB

    @router.post("/capture-scope")
    def issue(
        body: CaptureScopeRequest, request: Request,
        principal: AuthenticatedUser = Depends(principal_dependency),
        connection=Depends(connection_dependency),
    ):
        if not active:
            raise HTTPException(status_code=404, detail="Recurso no disponible", headers=NO_STORE)
        if request.url.scheme != "https" and request.client and request.client.host not in ("testclient", "127.0.0.1"):
            raise HTTPException(status_code=503, detail="HTTPS requerido", headers=NO_STORE)
        # Verify actual database, not the DSN/configured database label.
        db_name = connection.execute("SELECT current_database()").fetchone()[0]
        if db_name != expected_qa_database:
            raise HTTPException(status_code=503, detail="Base QA no disponible", headers=NO_STORE)
        try:
            return issue_capture_scope(
                connection, principal, device_key=body.device_key,
                machine_codes=body.machine_codes, signer=signer,
            )
        except CaptureScopeDenied:
            raise HTTPException(status_code=403, detail="Acceso no autorizado", headers=NO_STORE) from None

    return router
