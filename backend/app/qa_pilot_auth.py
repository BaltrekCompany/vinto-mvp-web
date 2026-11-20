"""OFF-04.5B-06B — authentication and SYNTHETIC package issuer for the isolated QA pilot app. NOT imported by `app.main`.

What it adds to the pilot application (all behind the independent flag OFFLINE_QA_PILOT_AUTH_ENABLED, off by default, QA only):
  * the EXISTING VINTO login/me/logout router, verbatim (`app.auth.router`): same credential checks, same session table, same cookie code;
  * session resolution for the receiver through the existing `current_user`, whose connection dependency is redirected to the dedicated IDENTITY
    connection, so the capture role never needs (nor receives) identity privileges;
  * a QA-only issuer, at the same two paths and with the same request contracts as the real readiness endpoints (`/api/offline/scope`,
    `/api/offline/quality-package`), that signs SYNTHETIC packages for the ten OFF-04.6 Quality forms with a SYNTHETIC Ed25519 key for explicit registry grants only.
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
from typing import Annotated, Any, Callable
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StringConstraints

from app.auth.service import AuthenticatedUser
from app.offline_scope.router import IssueScopeRequest, QualityPackageRequest
from app.offline_scope.signing import (AUDIENCE, ISSUER, PACKAGE_AUDIENCE, PACKAGE_SCHEMA, SCHEMA, SigningKey, canonical_payload, decode_b64, encode_b64,
                                       sign_quality_package, sign_scope, verify_scope)
from app.offline_quality.registry import BATCH_FORMS, BOBBIN, spec_for
from app.offline_quality.rules import UnsupportedCalculation, calculated_rules
from app.qa_offline_pilot import PilotConfigError, PilotGrant, is_isolated_qa_database_name

logger = logging.getLogger("vinto.qa_pilot")

NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
COOKIE_NAME_RE = re.compile(r"^vinto_qa_[A-Za-z0-9_-]{1,50}$")
SEED_DIR = pathlib.Path(__file__).resolve().parents[1] / "seed_data" / "forms"
SUPPORTED_FORMS = frozenset(BATCH_FORMS)      # OFF-04.6: the ten Quality forms (the registry says which are by machine and which by bobbin)
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


# ---------------------------------------------------------------- synthetic definition (fields, options, required flags and rules follow the published seed of each form)
_SEEDS: dict = {}


def seed_for(form_code: str) -> dict:
    if form_code not in SUPPORTED_FORMS:
        raise PilotConfigError("form_not_supported")
    if form_code not in _SEEDS:
        seed = json.loads((SEED_DIR / f"{form_code}.json").read_text(encoding="utf-8"))
        if seed.get("code") != form_code:
            raise PilotConfigError("seed_mismatch")
        _SEEDS[form_code] = seed
    return _SEEDS[form_code]


def synthetic_name(form_code: str) -> str:
    return f"SINTÉTICO · {seed_for(form_code)['name']} (piloto QA, no homologado)"


def synthetic_definition(form_code: str, version: int) -> dict:
    seed = seed_for(form_code)
    if version != seed["version_number"]:
        raise PilotConfigError("seed_version_mismatch")     # the device only ever edits the version the repository's contract describes
    fields = []
    for f in seed["fields"]:
        options = [{"option_key": o["option_key"], "label": o["label"], "display_order": o["display_order"]} for o in f.get("options", [])]
        calculated = f["source"] == "calculated"
        fields.append({"key": f["key"], "label": f["label"], "description": "", "value_type": f["value_type"], "source": f["source"], "required": False if calculated else bool(f["required"]),
                       "unit": f.get("unit"), "classification": None, "proposal": None, "needs_validation": False, "display_order": f["display_order"],
                       "calculation_rule": None, "options": options})
    try:
        rules = calculated_rules(form_code, [{"key": x["key"], "value_type": x["value_type"], "source": x["source"]} for x in fields])
    except UnsupportedCalculation:
        raise PilotConfigError("seed_calculation_unsupported") from None
    return {"form_code": form_code, "form_name": synthetic_name(form_code), "form_version": version, "area": "quality",
            "source_definition_checksum": seed["definition_checksum"], "published_at": "2026-11-19T00:00:00+00:00", "groups": [],
            "fields": sorted(fields, key=lambda x: x["display_order"]), "calculated_rules": rules, "option_dependencies": [], "recipe_bundle_included": False,
            "capture_eligible": False, "note": SYNTHETIC_NOTE}


def grant_id_for(g: PilotGrant) -> str:
    return str(uuid.uuid5(GRANT_NAMESPACE, f"{g.user_id}|{g.machine_code}|{g.form_code}|{g.form_version}"))


class IssuerDenied(Exception):
    pass


class IssuerUnavailable(Exception):
    pass


class SyntheticIssuer:
    """Readiness-only scope and quality package for explicit registry grants. Never reads the database, never uses real keys or real definitions."""

    def __init__(self, grants: tuple[PilotGrant, ...], signer: SigningKey, *, now: Callable[[], datetime] | None = None, bobbins=()) -> None:
        self.grants, self.signer = tuple(g for g in grants if g.form_code in SUPPORTED_FORMS), signer
        for g in self.grants:       # a grant for another version than the repository's contract is a configuration error (fail closed at startup)
            if g.form_version != seed_for(g.form_code)["version_number"]:
                raise PilotConfigError("grant_version_not_seed")
        self.bobbins = tuple(bobbins)
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
                         "operation": spec_for(g.form_code).operation.value} for g in matched), key=lambda p: (p["machine_code"], p["form_code"]))
        payload = {"schema": SCHEMA, "issuer": ISSUER, "audience": AUDIENCE, "snapshot_id": str(snapshots.pop()), "subject_user_id": str(principal.user_id),
                   "device_key": str(device_key), "issued_at": self._stamp(self._now()), "kind": "scope_readiness_only", "captures_enabled": False, "form_scopes": pairs}
        return sign_scope(payload, signer=self.signer)

    def package(self, principal: AuthenticatedUser, device_key: uuid.UUID, machine_code: str, form_code: str, signed_scope: dict) -> dict:
        if principal.must_change or device_key.version != 4 or form_code not in SUPPORTED_FORMS:
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
        definition = synthetic_definition(form_code, grant.form_version)
        payload = {"schema": PACKAGE_SCHEMA, "issuer": ISSUER, "audience": PACKAGE_AUDIENCE, "kind": "quality_definition_readiness_only", "captures_enabled": False,
                   "package_id": str(uuid.uuid4()), "scope_snapshot_id": sp["snapshot_id"], "subject_user_id": str(principal.user_id), "device_key": str(device_key),
                   "machine_code": machine_code, "form_code": form_code, "form_version": grant.form_version, "grant_id": item["grant_id"],
                   "issued_at": self._stamp(self._now()), "content_sha256": hashlib.sha256(canonical_payload(definition)).hexdigest(), "definition": definition}
        return sign_quality_package(payload, signer=self.signer)


def _bobbin_contexts(self, principal: AuthenticatedUser, device_key: uuid.UUID, machine_code: str, bobbin_code: str, signed_scope: dict) -> dict:
    """Historical context of the SYNTHETIC bobbins with that exact code on that machine, for a user who holds a by-bobbin grant there (read-only, nothing is created)."""
    if principal.must_change or device_key.version != 4 or not verify_scope(signed_scope, trusted_public_key_b64url=self.signer.public_b64url):
        raise IssuerDenied()
    sp = signed_scope["payload"]
    if sp.get("kind") != "scope_readiness_only" or sp.get("subject_user_id") != str(principal.user_id) or sp.get("device_key") != str(device_key):
        raise IssuerDenied()
    try:
        issued = datetime.fromisoformat(str(sp["issued_at"]).replace("Z", "+00:00"))
    except ValueError:
        raise IssuerDenied() from None
    if (self._now() - issued).total_seconds() > SCOPE_MAX_AGE_SECONDS or issued > self._now():
        raise IssuerDenied()
    mine = [g for g in self._mine(principal) if g.machine_code == machine_code and spec_for(g.form_code).kind == BOBBIN and g.scope_snapshot_id is not None and str(g.scope_snapshot_id) == sp.get("snapshot_id")]
    if not mine:
        raise IssuerDenied()
    found = [b.context() for b in self.bobbins if b.machine_code == machine_code and b.bobbin_code == bobbin_code]
    return {"snapshot_id": sp["snapshot_id"], "machine_code": machine_code, "contexts": found}


SyntheticIssuer.bobbin_contexts = _bobbin_contexts


class BobbinContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    device_key: uuid.UUID
    machine_code: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,48}$")]
    bobbin_code: Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,48}$")]
    signed_scope: dict


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

    @router.post("/bobbin-context")
    def issue_bobbin_context(body: BobbinContextRequest, principal: AuthenticatedUser = Depends(principal_dependency)):
        try:
            result = issuer.bobbin_contexts(principal, body.device_key, body.machine_code, body.bobbin_code, body.signed_scope)
        except IssuerDenied:
            return denied()
        return JSONResponse(content=result, headers=NO_STORE)

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


def build_auth_mount(*, grants: tuple[PilotGrant, ...], signer: SigningKey, origins: tuple[str, ...], principal_dependency: Callable | None = None, bobbins=()) -> AuthMount:
    """`principal_dependency` is the existing `current_user`; the redirection of its connection to the identity role is what keeps identity privileges
    out of the capture role."""
    from app.auth.dependencies import current_user
    from app.auth.router import router as auth_router
    from app.database import get_connection, get_identity_connection
    principal_dependency = principal_dependency or current_user
    issuer = SyntheticIssuer(grants, signer, bobbins=bobbins)
    return AuthMount(routers=(auth_router, create_issuer_router(issuer, principal_dependency)), allowed_origins=origins,
                     dependency_overrides={get_connection: get_identity_connection})
