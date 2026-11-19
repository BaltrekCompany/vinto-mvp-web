"""OFF-04.5B-06B — authentication and SYNTHETIC package issuer for the isolated QA pilot app. NOT imported by `app.main`.

What it adds to the pilot application (all behind the independent flag OFFLINE_QA_PILOT_AUTH_ENABLED, off by default, QA only):
  * the EXISTING VINTO login/me/logout router, verbatim (`app.auth.router`): same credential checks, same session table, same cookie code;
  * session resolution for the receiver through the existing `current_user`, whose connection dependency is redirected to the dedicated IDENTITY
    connection, so the capture role never needs (nor receives) identity privileges;
  * a QA-only issuer, at the same two paths and with the same request contracts as the real readiness endpoints (`/api/offline/scope`,
    `/api/offline/quality-package`), that signs SYNTHETIC P1-22 packages with a SYNTHETIC Ed25519 key for explicit registry grants only.
    The real issuer (database authorisation, real form versions, the real signing seed) is never mounted here;
  * an Origin allow-list for every authenticated write (CSRF defence together with the SameSite cookie). No CORS is configured at all.
Nothing here enables industrial capture: every artefact it signs is readiness-only (`captures_enabled=false`).
"""
from __future__ import annotations

import hashlib
import json
import logging
import pathlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.auth.service import AuthenticatedUser
from app.offline_scope.router import IssueScopeRequest, QualityPackageRequest
from app.offline_scope.signing import (AUDIENCE, ISSUER, PACKAGE_AUDIENCE, PACKAGE_SCHEMA, SCHEMA, SigningKey, canonical_payload, decode_b64, encode_b64,
                                       sign_quality_package, sign_scope, verify_scope)
from app.qa_offline_pilot import PilotConfigError, PilotGrant, is_isolated_qa_database_name

logger = logging.getLogger("vinto.qa_pilot")

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
COOKIE_NAME_RE = re.compile(r"^vinto_qa_[A-Za-z0-9_-]{1,50}$")
SEED_DIR = pathlib.Path(__file__).resolve().parents[1] / "seed_data" / "forms"
SUPPORTED_FORM = "VINTO-P1-22"
SYNTHETIC_NAME = "SINTÉTICO · Grado de refinación Schopper (piloto QA, no homologado)"
SYNTHETIC_NOTE = "Synthetic QA-only definition; no industrial captures."
GRANT_NAMESPACE = uuid.UUID("b3a1c0de-5b06-4b06-8b06-0ff0455b06b0")
SCOPE_MAX_AGE_SECONDS = 24 * 3600
UNSAFE = frozenset({"POST", "PUT", "PATCH", "DELETE"})


# ---------------------------------------------------------------- origins (CSRF)
def parse_origins(raw: str | None) -> tuple[str, ...]:
    """Exact origins (scheme://host[:port], no path). https only, plus http on loopback for disposable test servers."""
    if not raw or not raw.strip():
        raise PilotConfigError("origins_required")
    out = []
    for item in (p.strip() for p in raw.split(",")):
        parts = urlsplit(item)
        loopback = parts.hostname in ("127.0.0.1", "localhost", "::1")
        if (parts.scheme not in ("https", "http") or (parts.scheme == "http" and not loopback) or not parts.hostname or parts.path not in ("", "/")
                or parts.query or parts.fragment or parts.username or "*" in item):
            raise PilotConfigError("origin_invalid")
        out.append(f"{parts.scheme}://{parts.netloc}")
    if not out or len(out) > 5:
        raise PilotConfigError("origins_invalid")
    return tuple(dict.fromkeys(out))


# ---------------------------------------------------------------- synthetic signer
def signer_from_seed(seed_b64url: str | None) -> SigningKey:
    """A key that exists ONLY for the synthetic pilot (separate setting from the real issuer's seed). Fails closed."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    try:
        private = Ed25519PrivateKey.from_private_bytes(decode_b64(seed_b64url or "", 32))
    except (ValueError, TypeError):
        raise PilotConfigError("signing_seed_invalid") from None
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return SigningKey(private, encode_b64(public), "ed25519-" + hashlib.sha256(public).hexdigest()[:20])


# ---------------------------------------------------------------- synthetic definition (fields and required flags follow the published seed)
def synthetic_definition(version: int) -> dict:
    seed = json.loads((SEED_DIR / f"{SUPPORTED_FORM}.json").read_text(encoding="utf-8"))
    fields = []
    for f in seed["fields"]:
        if f["source"] != "manual":
            raise PilotConfigError("seed_has_calculated_field")  # this synthetic form is manual-only; anything else needs a new, reviewed contract
        fields.append({"key": f["key"], "label": f["label"], "description": "", "value_type": f["value_type"], "source": "manual", "required": bool(f["required"]),
                       "unit": f.get("unit"), "classification": None, "proposal": None, "needs_validation": False, "display_order": f["display_order"],
                       "calculation_rule": None, "options": []})
    return {"form_code": SUPPORTED_FORM, "form_name": SYNTHETIC_NAME, "form_version": version, "area": "quality",
            "source_definition_checksum": hashlib.sha256(f"off045b06b:{SUPPORTED_FORM}:{version}".encode()).hexdigest(),
            "published_at": "2026-11-19T00:00:00+00:00", "groups": [], "fields": sorted(fields, key=lambda x: x["display_order"]), "calculated_rules": {},
            "option_dependencies": [], "recipe_bundle_included": False, "capture_eligible": False, "note": SYNTHETIC_NOTE}


def grant_id_for(g: PilotGrant) -> str:
    return str(uuid.uuid5(GRANT_NAMESPACE, f"{g.user_id}|{g.machine_code}|{g.form_code}|{g.form_version}"))


class IssuerDenied(Exception):
    pass


class IssuerUnavailable(Exception):
    pass


class SyntheticIssuer:
    """Readiness-only scope and quality package for explicit registry grants. Never reads the database, never uses real keys or real definitions."""

    def __init__(self, grants: tuple[PilotGrant, ...], signer: SigningKey, *, now: Callable[[], datetime] | None = None) -> None:
        self.grants, self.signer = tuple(g for g in grants if g.form_code == SUPPORTED_FORM), signer
        self._now = now or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _stamp(dt: datetime) -> str:
        return dt.isoformat(timespec="seconds").replace("+00:00", "Z")

    def _mine(self, principal: AuthenticatedUser) -> list[PilotGrant]:
        return [g for g in self.grants if g.user_id == principal.user_id]

    def scope(self, principal: AuthenticatedUser, device_key: uuid.UUID, machine_codes: list[str]) -> dict:
        if principal.must_change or device_key.version != 4:
            raise IssuerDenied()
        matched = [g for g in self._mine(principal) if g.machine_code in machine_codes]
        if not matched:
            raise IssuerDenied()
        snapshots = {g.scope_snapshot_id for g in matched}
        if len(snapshots) != 1 or None in snapshots:
            raise IssuerDenied()          # the pilot grant must pin ONE snapshot: the receiver only accepts captures carrying exactly that snapshot
        pairs = sorted(({"machine_code": g.machine_code, "form_code": g.form_code, "form_version": g.form_version, "grant_id": grant_id_for(g),
                         "operation": "quality_machine_capture"} for g in matched), key=lambda p: (p["machine_code"], p["form_code"]))
        payload = {"schema": SCHEMA, "issuer": ISSUER, "audience": AUDIENCE, "snapshot_id": str(snapshots.pop()), "subject_user_id": str(principal.user_id),
                   "device_key": str(device_key), "issued_at": self._stamp(self._now()), "kind": "scope_readiness_only", "captures_enabled": False, "form_scopes": pairs}
        return sign_scope(payload, signer=self.signer)

    def package(self, principal: AuthenticatedUser, device_key: uuid.UUID, machine_code: str, form_code: str, signed_scope: dict) -> dict:
        if principal.must_change or device_key.version != 4 or form_code != SUPPORTED_FORM:
            raise IssuerDenied()
        if not verify_scope(signed_scope, trusted_public_key_b64url=self.signer.public_b64url):   # a scope signed by any other key (real or not) is refused
            raise IssuerDenied()
        sp = signed_scope["payload"]
        if (sp.get("kind") != "scope_readiness_only" or sp.get("captures_enabled") is not False or sp.get("subject_user_id") != str(principal.user_id)
                or sp.get("device_key") != str(device_key)):
            raise IssuerDenied()
        try:
            issued = datetime.fromisoformat(str(sp["issued_at"]).replace("Z", "+00:00"))
        except ValueError:
            raise IssuerDenied() from None
        if (self._now() - issued).total_seconds() > SCOPE_MAX_AGE_SECONDS or issued > self._now():
            raise IssuerDenied()
        item = next((x for x in sp.get("form_scopes", []) if x.get("machine_code") == machine_code and x.get("form_code") == form_code), None)
        grant = next((g for g in self._mine(principal) if g.machine_code == machine_code and g.form_code == form_code), None)  # re-read NOW: a removed grant denies
        if item is None or grant is None or item.get("grant_id") != grant_id_for(grant) or item.get("form_version") != grant.form_version \
                or sp.get("snapshot_id") != str(grant.scope_snapshot_id):
            raise IssuerDenied()
        definition = synthetic_definition(grant.form_version)
        payload = {"schema": PACKAGE_SCHEMA, "issuer": ISSUER, "audience": PACKAGE_AUDIENCE, "kind": "quality_definition_readiness_only", "captures_enabled": False,
                   "package_id": str(uuid.uuid4()), "scope_snapshot_id": sp["snapshot_id"], "subject_user_id": str(principal.user_id), "device_key": str(device_key),
                   "machine_code": machine_code, "form_code": form_code, "form_version": grant.form_version, "grant_id": item["grant_id"],
                   "issued_at": self._stamp(self._now()), "content_sha256": hashlib.sha256(canonical_payload(definition)).hexdigest(), "definition": definition}
        return sign_quality_package(payload, signer=self.signer)


def create_issuer_router(issuer: SyntheticIssuer, principal_dependency: Callable) -> APIRouter:
    """Same paths and request models as the real readiness endpoints (so the existing client contract is unchanged), different and isolated implementation."""
    router = APIRouter(prefix="/api/offline", tags=["QA pilot — synthetic readiness issuer (isolated)"])
    denied = lambda: JSONResponse(status_code=403, content={"detail": "Acceso no autorizado"}, headers=NO_STORE)  # noqa: E731

    @router.post("/scope")
    def issue_scope(body: IssueScopeRequest, principal: AuthenticatedUser = Depends(principal_dependency)):
        try:
            signed = issuer.scope(principal, body.device_key, body.machine_codes)
        except IssuerDenied:
            return denied()
        logger.info("qa pilot synthetic scope issued pairs=%d", len(signed["payload"]["form_scopes"]))
        return JSONResponse(content=signed, headers=NO_STORE)

    @router.post("/quality-package")
    def issue_package(body: QualityPackageRequest, principal: AuthenticatedUser = Depends(principal_dependency)):
        try:
            package = issuer.package(principal, body.device_key, body.machine_code, body.form_code, body.signed_scope)
        except IssuerDenied:
            return denied()
        logger.info("qa pilot synthetic package issued")
        return JSONResponse(content=package, headers=NO_STORE)

    return router


# ---------------------------------------------------------------- identity connection verification
def verify_identity_database(connection, *, receiver_database: str, receiver_role: str) -> None:
    """The identity connection must be a DIFFERENT, minimal role on the SAME isolated QA database. Fixed codes, no values."""
    def one(sql: str, params: tuple = ()):
        return connection.execute(sql, params).fetchone()[0]
    if one("SELECT current_database()") != receiver_database or not is_isolated_qa_database_name(receiver_database):
        raise PilotConfigError("identity_database_mismatch")
    role = one("SELECT current_user")
    if role == receiver_role:
        raise PilotConfigError("identity_role_not_separate")
    flags = connection.execute("SELECT rolsuper, rolcreatedb, rolcreaterole, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = current_user").fetchone()
    if flags is None or any(flags):
        raise PilotConfigError("identity_role_too_privileged")
    if one("SELECT has_database_privilege(current_user, current_database(), 'CREATE')") or one("SELECT has_schema_privilege(current_user, 'public', 'CREATE')"):
        raise PilotConfigError("identity_role_can_create")
    if one("SELECT to_regnamespace('vinto_offline') IS NOT NULL AND (has_schema_privilege(current_user, 'vinto_offline', 'USAGE') OR has_schema_privilege(current_user, 'vinto_offline', 'CREATE'))"):
        raise PilotConfigError("identity_role_reaches_receiver")
    for table in ("vinto_auth.credential", "vinto_auth.session"):
        if not one("SELECT has_table_privilege(current_user, %s::regclass, 'SELECT') AND has_table_privilege(current_user, %s::regclass, 'UPDATE')", (table, table)):
            raise PilotConfigError("identity_role_lacks_privilege")
        if one("SELECT has_table_privilege(current_user, %s::regclass, 'DELETE') OR has_table_privilege(current_user, %s::regclass, 'TRUNCATE')", (table, table)):
            raise PilotConfigError("identity_role_has_excess_privilege")
    if one("SELECT EXISTS (SELECT 1 FROM pg_class c WHERE c.relowner = (SELECT oid FROM pg_roles WHERE rolname = current_user))"):
        raise PilotConfigError("identity_role_owns_objects")


@dataclass(frozen=True)
class AuthMount:
    """What the pilot application needs to serve authentication: routers, the Origin allow-list and the dependency redirection."""
    routers: tuple[APIRouter, ...]
    allowed_origins: tuple[str, ...]
    dependency_overrides: dict = field(default_factory=dict)


def build_auth_mount(*, grants: tuple[PilotGrant, ...], signer: SigningKey, origins: tuple[str, ...], principal_dependency: Callable | None = None) -> AuthMount:
    """`principal_dependency` is the existing `current_user`; the redirection of its connection to the identity role is what keeps identity privileges
    out of the capture role."""
    from app.auth.dependencies import current_user
    from app.auth.router import router as auth_router
    from app.database import get_connection, get_identity_connection
    principal_dependency = principal_dependency or current_user
    issuer = SyntheticIssuer(grants, signer)
    return AuthMount(routers=(auth_router, create_issuer_router(issuer, principal_dependency)), allowed_origins=origins,
                     dependency_overrides={get_connection: get_identity_connection})
