"""FastAPI router of the offline capture receiver (OFF-04.4). Built on demand; NEVER included by `app.main`.

`create_offline_capture_router(enabled=False)` (the default) answers 404 to every call: a disabled receiver accepts no writes.
"""
from __future__ import annotations

from typing import Callable
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.auth.dependencies import current_user
from app.auth.service import AuthenticatedUser
from app.offline_capture import contract as C
from app.offline_capture.service import CaptureAuthorizer, ContextProvider, DenyAllAuthorizer, PayloadValidator, UnverifiableContext, receive_capture, reconcile_capture
from app.offline_capture.store import OfflineCaptureStore, StoreUnavailable

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
DISABLED = {"detail": "Recurso no disponible"}


def create_offline_capture_router(*, store: OfflineCaptureStore | None = None, enabled: bool = False, authorizer: CaptureAuthorizer | None = None,
                                  context: ContextProvider | None = None, principal_dependency: Callable = current_user,
                                  validator: PayloadValidator | None = None) -> APIRouter:
    authorizer = authorizer or DenyAllAuthorizer()
    context = context or UnverifiableContext()
    router = APIRouter(prefix="/api/offline", tags=["Offline — recepción idempotente (aislado, CI)"])

    def disabled() -> JSONResponse:
        return JSONResponse(status_code=404, content=DISABLED, headers=NO_STORE)

    @router.post("/captures")
    def post_capture(body: C.CaptureIn, principal: AuthenticatedUser = Depends(principal_dependency)):
        if not enabled or store is None:
            return disabled()
        try:
            reply = receive_capture(store, principal, body, authorizer=authorizer, context=context, validator=validator)
        except StoreUnavailable:
            return JSONResponse(status_code=503, content={"outcome": "error", "reason": C.R_UNAVAILABLE, "technical_acceptance": False,
                                                          "industrial_approval": False}, headers=NO_STORE)
        return JSONResponse(status_code=reply.status, content=reply.body, headers=NO_STORE)

    @router.get("/captures/{capture_id}")
    def get_capture(capture_id: UUID, principal: AuthenticatedUser = Depends(principal_dependency)):
        if not enabled or store is None:
            return disabled()
        try:
            reply = reconcile_capture(store, principal, capture_id)
        except StoreUnavailable:
            return JSONResponse(status_code=503, content={"found": None, "reason": C.R_UNAVAILABLE}, headers=NO_STORE)
        return JSONResponse(status_code=reply.status, content=reply.body, headers=NO_STORE)

    return router
