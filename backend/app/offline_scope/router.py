"""OFF-03B.2: authenticated issuance of a read-only signed scope snapshot.

Server flag defaults OFF; no production routes for storing offline captures.
"""
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing import Annotated

from app.auth.dependencies import current_user
from app.auth.service import AuthenticatedUser
from app.config import settings
from app.database import get_connection
from app.offline_scope.service import OfflineScopeDenied, OfflineScopeTooLarge, issue_scope
from app.offline_scope.quality_package import PackageDenied, PackageUnavailable, build_quality_package
from app.offline_scope.signing import OfflineSigningUnavailable, load_signer
from app.offline_quality.bobbin_context import BobbinContextDenied, issue_for_code

logger = logging.getLogger("vinto.offline.scope")
router = APIRouter(prefix="/api/offline", tags=["Offline — contrato en desarrollo"])
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
MachineCode = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,48}$")]


class IssueScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    device_key: UUID
    machine_codes: list[MachineCode] = Field(min_length=1, max_length=25)


@router.post("/scope", responses={
    401: {"description": "Sesión necesaria"},
    403: {"description": "Sin concesiones efectivas"},
    404: {"description": "Módulo deshabilitado"},
    503: {"description": "Firma o autorización no disponible"},
})
def issue_offline_scope(body: IssueScopeRequest, request: Request, response: Response,
                        principal: AuthenticatedUser = Depends(current_user),
                        connection=Depends(get_connection)):
    response.headers.update(NO_STORE)
    if not settings.offline_scope_issue_enabled:
        raise HTTPException(status_code=404, detail="Recurso no disponible", headers=NO_STORE)
    # Strictly no key material without explicit server-side provision.
    try:
        signer = load_signer()
    except OfflineSigningUnavailable:
        raise HTTPException(status_code=503, detail="Módulo offline no disponible", headers=NO_STORE) from None
    if not request.url.scheme == "https" and settings.app_env not in {"ci", "test", "local", "qa"}:
        raise HTTPException(status_code=503, detail="Se requiere HTTPS", headers=NO_STORE)
    try:
        signed = issue_scope(connection, principal, device_key=body.device_key,
                             machine_codes=body.machine_codes, signer=signer)
    except OfflineScopeDenied:
        raise HTTPException(status_code=403, detail="Acceso no autorizado", headers=NO_STORE) from None
    except OfflineScopeTooLarge:
        raise HTTPException(status_code=409, detail="Alcance demasiado amplio", headers=NO_STORE) from None
    # No secrets, credentials or operator names in operational logs.
    logger.info("offline scope issued snapshot=%s pairs=%d", signed["payload"]["snapshot_id"],
                len(signed["payload"]["form_scopes"]))
    return signed

class QualityPackageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    device_key: UUID
    machine_code: MachineCode
    form_code: Annotated[str, StringConstraints(pattern=r"^VINTO-P1-[0-9]{2}$")]
    signed_scope: dict


@router.post("/quality-package", responses={
    401: {"description": "Sesión necesaria"},
    403: {"description": "No autorizado o no vinculado al alcance firmado"},
    404: {"description": "Exportación no habilitada"},
    503: {"description": "Paquete no disponible"},
})
def issue_quality_package(body: QualityPackageRequest, request: Request, response: Response,
                          principal: AuthenticatedUser = Depends(current_user),
                          connection=Depends(get_connection)):
    response.headers.update(NO_STORE)
    if not settings.offline_quality_package_issue_enabled or not settings.offline_scope_issue_enabled:
        raise HTTPException(status_code=404, detail="Recurso no disponible", headers=NO_STORE)
    if request.url.scheme != "https" and settings.app_env not in {"ci", "test", "local", "qa"}:
        raise HTTPException(status_code=503, detail="Se requiere HTTPS", headers=NO_STORE)
    try:
        signer = load_signer()
    except OfflineSigningUnavailable:
        raise HTTPException(status_code=503, detail="Módulo offline no disponible", headers=NO_STORE) from None
    try:
        package = build_quality_package(connection, principal,
            device_key=body.device_key, machine_code=body.machine_code,
            form_code=body.form_code, signed_scope=body.signed_scope, signer=signer)
    except PackageDenied:
        raise HTTPException(status_code=403, detail="Acceso no autorizado", headers=NO_STORE) from None
    except PackageUnavailable:
        raise HTTPException(status_code=503, detail="Paquete no disponible", headers=NO_STORE) from None
    logger.info("offline quality package issued package=%s", package["payload"]["package_id"])
    return package


class BobbinContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    device_key: UUID
    machine_code: MachineCode
    bobbin_code: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,48}$")]
    signed_scope: dict


@router.post("/bobbin-context", responses={
    401: {"description": "Sesión necesaria"},
    403: {"description": "No autorizado o no vinculado al alcance firmado"},
    404: {"description": "Exportación no habilitada"},
    503: {"description": "Firma no disponible"},
})
def issue_bobbin_context(body: BobbinContextRequest, request: Request, response: Response,
                         principal: AuthenticatedUser = Depends(current_user),
                         connection=Depends(get_connection)):
    """OFF-04.6: historical context of one physical bobbin, for by-bobbin Quality forms prepared online. Read-only; never a permission to capture."""
    response.headers.update(NO_STORE)
    if not settings.offline_quality_package_issue_enabled or not settings.offline_scope_issue_enabled:
        raise HTTPException(status_code=404, detail="Recurso no disponible", headers=NO_STORE)
    if request.url.scheme != "https" and settings.app_env not in {"ci", "test", "local", "qa"}:
        raise HTTPException(status_code=503, detail="Se requiere HTTPS", headers=NO_STORE)
    try:
        signer = load_signer()
    except OfflineSigningUnavailable:
        raise HTTPException(status_code=503, detail="Módulo offline no disponible", headers=NO_STORE) from None
    try:
        with connection.transaction():
            return issue_for_code(connection, principal, device_key=body.device_key, machine_code=body.machine_code,
                                  bobbin_code=body.bobbin_code, signed_scope=body.signed_scope, signer=signer)
    except BobbinContextDenied:
        raise HTTPException(status_code=403, detail="Acceso no autorizado", headers=NO_STORE) from None
