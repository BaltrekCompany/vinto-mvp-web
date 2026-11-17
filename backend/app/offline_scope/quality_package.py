"""OFF-03C.1: signed, read-only definition packages for *machine* Quality.

Never exports operational captures or creates write privileges. Uses the exact
published PostgreSQL form version + the existing effective grant engine.
Only independent machine-quality candidates are supported for this increment.
"""
import hashlib
import uuid
from datetime import datetime, timezone

from app import capture_service as capture
from app.auth.service import AuthenticatedUser
from app.authz.engine import authorize
from app.authz.policies import Operation
from app.quality.machine_capture_service import MACHINE_QUALITY_FORM_CODES, PERCENT_RULES
from app.offline_scope.signing import (
    AUDIENCE, SCHEMA, ISSUER, PACKAGE_AUDIENCE, PACKAGE_SCHEMA,
    SigningKey, canonical_payload, verify_scope, sign_quality_package,
)

MAX_FIELDS = 128
MAX_OPTIONS = 512


class PackageDenied(Exception):
    pass


class PackageUnavailable(Exception):
    pass


def _quality_scope(signed_scope, signer: SigningKey, principal: AuthenticatedUser,
                   device_key: uuid.UUID, machine_code: str, form_code: str) -> dict:
    if not isinstance(signed_scope, dict) or not verify_scope(
        signed_scope, trusted_public_key_b64url=signer.public_b64url
    ):
        raise PackageDenied()
    payload = signed_scope["payload"]
    if (payload.get("schema") != SCHEMA or payload.get("audience") != AUDIENCE
            or payload.get("issuer") != ISSUER or payload.get("kind") != "scope_readiness_only"
            or payload.get("captures_enabled") is not False
            or payload.get("subject_user_id") != str(principal.user_id)
            or payload.get("device_key") != str(device_key)):
        raise PackageDenied()
    matches = [entry for entry in payload.get("form_scopes", []) if isinstance(entry, dict)
               and entry.get("machine_code") == machine_code
               and entry.get("form_code") == form_code
               and entry.get("operation") == Operation.QUALITY_MACHINE_CAPTURE.value]
    if len(matches) != 1 or not isinstance(matches[0].get("form_version"), int):
        raise PackageDenied()
    if not isinstance(payload.get("snapshot_id"), str):
        raise PackageDenied()
    return {"snapshot_id": payload["snapshot_id"], "scope": matches[0]}


def _definition(connection, *, machine_code: str, form_code: str, version: int) -> dict:
    # Authorize() has already validated active user, grants, sector, machine and
    # the current highest published form version. Query EXACT version again.
    row = connection.execute(
        """SELECT fv.id, fv.name, fv.area, fv.status, fv.version_number,
                  fv.definition_checksum, fv.published_at
           FROM vinto_config.form f JOIN vinto_config.form_version fv ON fv.form_id = f.id
           JOIN vinto_config.form_version_machine fvm ON fvm.form_version_id = fv.id
           JOIN vinto_master.machine m ON m.id = fvm.machine_id
           WHERE f.code = %s AND f.active AND m.code = %s AND m.active
             AND fv.status = 'published' AND fv.area = 'quality'
             AND fv.version_number = %s""",
        (form_code, machine_code, version)).fetchone()
    if row is None:
        raise PackageUnavailable()
    version_id, name, area, status, number, checksum, published_at = row

    # Same structural support checks as the actual machine-quality capture route.
    try:
        admitted = capture.load_fields(connection, version_id, allow_calculated=True)
    except Exception as exc:
        # Structural exceptions are fail-closed, never silently strip fields.
        raise PackageUnavailable() from exc
    if not admitted or len(admitted) > MAX_FIELDS:
        raise PackageUnavailable()
    rows = connection.execute(
        """SELECT fd.id,fd.key,fd.label,fd.description,fd.value_type,fd.source,
                  fd.required,u.code,fd.classification,fd.proposal,fd.needs_validation,
                  fd.display_order,fd.calculation_rule,fd.field_group_id
           FROM vinto_config.field_definition fd
           LEFT JOIN vinto_master.unit u ON u.id=fd.unit_id
           WHERE fd.form_version_id = %s ORDER BY fd.display_order,fd.key""",
        (version_id,)).fetchall()
    if len(rows) != len(admitted) or any(r[13] is not None for r in rows):
        raise PackageUnavailable()
    options_rows = connection.execute(
        """SELECT fo.field_definition_id,fo.option_key,fo.label,fo.display_order
           FROM vinto_config.field_option fo
           WHERE fo.form_version_id = %s ORDER BY fo.field_definition_id,fo.display_order,fo.option_key""",
        (version_id,)).fetchall()
    if len(options_rows) > MAX_OPTIONS:
        raise PackageUnavailable()
    # Machine-quality capture has no dependency resolver in the write route;
    # exporting one as "supported" would be misleading.
    dependent = connection.execute(
        "SELECT 1 FROM vinto_config.field_option_dependency WHERE form_version_id=%s LIMIT 1",
        (version_id,)).fetchone()
    if dependent:
        raise PackageUnavailable()
    by_id = {r[0]: [] for r in rows}
    for field_id, option_key, label, order in options_rows:
        if field_id not in by_id:
            raise PackageUnavailable()
        by_id[field_id].append({
            "option_key": option_key, "label": label, "display_order": order
        })
    fields = []
    calculated_keys = set()
    field_types = {}
    for (field_id,key,label,description,value_type,source,required,unit,classification,
         proposal,needs_validation,order,rule,group_id) in rows:
        if source not in ("manual", "calculated"):
            raise PackageUnavailable()
        if source == "calculated":
            calculated_keys.add(key)
        field_types[key] = (source,value_type)
        fields.append({
            "key":key, "label":label, "description":description,
            "value_type":value_type, "source":source, "required":bool(required),
            "unit":unit, "classification":classification, "proposal":proposal,
            "needs_validation":bool(needs_validation), "display_order":order,
            "calculation_rule":rule, "options":by_id[field_id]
        })
    calculated = {}
    rules = PERCENT_RULES.get(form_code, {})
    if calculated_keys != set(rules):
        raise PackageUnavailable()
    for calc_key,(numerator, denominator) in rules.items():
        if (field_types.get(calc_key) != ("calculated","decimal") or
            field_types.get(numerator) != ("manual","decimal") or
            field_types.get(denominator) != ("manual","decimal")):
            raise PackageUnavailable()
        calculated[calc_key] = {
            "method":"percent_two_decimals_half_up",
            "numerator":numerator, "denominator":denominator,
            "denominator_zero":"omit_calculation"
        }
    return {
        "form_code":form_code, "form_name":name, "form_version":number,
        "area":area, "source_definition_checksum":checksum,
        "published_at":published_at.isoformat() if published_at is not None else None,
        "groups":[], "fields":fields, "calculated_rules":calculated,
        "option_dependencies":[], "recipe_bundle_included":False,
        "capture_eligible":False,
        "note":"Readiness preview only. No OT, shifts, recipes, capture or acceptance."
    }


def build_quality_package(connection, principal: AuthenticatedUser, *, device_key: uuid.UUID,
                          machine_code: str, form_code: str, signed_scope: dict,
                          signer: SigningKey) -> dict:
    if (not isinstance(principal, AuthenticatedUser) or principal.must_change
            or not isinstance(device_key, uuid.UUID) or device_key.version != 4
            or not isinstance(machine_code, str) or not isinstance(form_code, str)
            or form_code not in MACHINE_QUALITY_FORM_CODES):
        raise PackageDenied()
    token = _quality_scope(signed_scope, signer, principal, device_key, machine_code, form_code)
    with connection.transaction():
        # Still current? Revoked, inactive, wrong sector or unpublished -> deny.
        decision = authorize(connection, principal, Operation.QUALITY_MACHINE_CAPTURE,
                             machine_code, form_code, lock=True)
        item = token["scope"]
        if (not decision.allowed or not decision.grant_id or
            str(decision.grant_id) != item.get("grant_id") or
            decision.effective_version != item.get("form_version")):
            raise PackageDenied()
        definition = _definition(connection, machine_code=machine_code,
                                 form_code=form_code, version=decision.effective_version)
        digest = hashlib.sha256(canonical_payload(definition)).hexdigest()
        payload = {
            "schema":PACKAGE_SCHEMA, "issuer":ISSUER, "audience":PACKAGE_AUDIENCE,
            "kind":"quality_definition_readiness_only",
            "captures_enabled":False, "package_id":str(uuid.uuid4()),
            "scope_snapshot_id":token["snapshot_id"],
            "subject_user_id":str(principal.user_id),
            "device_key":str(device_key), "machine_code":machine_code,
            "form_code":form_code,"form_version":decision.effective_version,
            "grant_id":str(decision.grant_id),
            "issued_at":datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00","Z"),
            "content_sha256":digest, "definition":definition,
        }
        return sign_quality_package(payload, signer=signer)
