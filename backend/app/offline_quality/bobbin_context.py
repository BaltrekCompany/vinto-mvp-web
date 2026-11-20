"""OFF-04.6: the HISTORICAL context of a physical bobbin, prepared online and carried offline.

The authority of a Quality capture by bobbin is the bobbin's own F3 history (machine, shift, operating date, assignment, work order, line, PV, article); the online route never uses
the active assignment. That history does not change after the bobbin exists, so the context digest below is over those immutable attributes only (never over the quality-release
status: capturing a measurement does not depend on it online either). A change of the digest between preparation and reconnection is therefore an anomaly and goes to central review.

`context_version` of a capture by bobbin = SHA-256 of (domain, signed-scope snapshot, bobbin id, digest): 64 hex characters, the maximum the receipt table accepts."""
from __future__ import annotations

import hashlib
import json
import uuid

from app.sectors import scoped_sector_codes

DOMAIN = "vinto-offline-bobbin-context-v1"
FIELDS = ("bobbin_id", "bobbin_code", "machine_code", "is_mother", "work_order", "line_code", "pv_reference", "article_code", "article_description", "shift_code", "operating_date")
DISPLAY = ("bobbin_code", "machine_code", "work_order", "line_code", "pv_reference", "article_code", "article_description", "shift_code", "operating_date")

_SQL = """SELECT b.id,
                 CASE WHEN b.rewind_mother_capture_id IS NOT NULL THEN
                   (SELECT btrim(d.value_text) FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition fd ON fd.id=d.field_definition_id
                    WHERE d.capture_id=b.rewind_mother_capture_id AND fd.key='etiqueta_numero_de_bobina' LIMIT 1)
                 ELSE b.code END,
                 m.code, b.rewind_mother_capture_id IS NOT NULL, wo.number, l.line_code, l.pv_reference, ar.code, av.description, sh.code, c.operating_date
          FROM vinto_txn.bobbin b
          JOIN vinto_txn.capture c ON c.id = b.source_capture_id
          JOIN vinto_master.machine m ON m.id = b.machine_id
          JOIN vinto_master.sector s ON s.id = m.sector_id
          JOIN vinto_config.shift_schedule sc ON sc.id = c.shift_schedule_id
          JOIN vinto_config.shift sh ON sh.id = sc.shift_id
          JOIN vinto_txn.assignment a ON a.id = c.assignment_id
          JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
          JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id
          JOIN vinto_txn.work_order wo ON wo.id = v.work_order_id
          JOIN vinto_master.article_version av ON av.id = b.article_version_id
          JOIN vinto_master.article ar ON ar.id = av.article_id
          WHERE (b.sequence_number IS NOT NULL OR b.rewind_mother_capture_id IS NOT NULL) AND b.rewind_child_position IS NULL AND s.code = ANY(%s)"""


def context_digest(context: dict) -> str:
    """SHA-256 over the canonical JSON of the context fields (strings only), so the device and the server never disagree about number or date formats."""
    canonical = {k: ("true" if context[k] is True else "false" if context[k] is False else str(context[k])) for k in FIELDS}
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def context_version(snapshot_id: str, bobbin_id: str, digest: str) -> str:
    return hashlib.sha256("\0".join((DOMAIN, str(snapshot_id).lower(), str(bobbin_id).lower(), digest)).encode("utf-8")).hexdigest()


def _from_row(row) -> dict:
    ctx = dict(zip(FIELDS, (str(row[0]), row[1], row[2], bool(row[3]), row[4], row[5], row[6], row[7], row[8], row[9], row[10].isoformat())))
    ctx["context_digest"] = context_digest(ctx)
    return ctx


def load_by_id(connection, bobbin_id, sectors) -> dict | None:
    try:
        bobbin_id = uuid.UUID(str(bobbin_id))
    except ValueError:
        return None
    row = connection.execute(_SQL + " AND b.id = %s", (list(scoped_sector_codes(sectors)), bobbin_id)).fetchone()
    return _from_row(row) if row else None


def load_by_code(connection, machine_code, bobbin_code, sectors, limit=5) -> list[dict]:
    """Numbered F3 bobbins of ONE machine with that exact code (consultation by the user, who is then authorised online)."""
    rows = connection.execute(_SQL + " AND m.code = %s AND b.code = %s ORDER BY b.created_at DESC LIMIT %s", (list(scoped_sector_codes(sectors)), machine_code, bobbin_code, limit)).fetchall()
    return [_from_row(r) for r in rows]


class BobbinContextDenied(Exception):
    pass


def issue_for_code(connection, principal, *, device_key, machine_code: str, bobbin_code: str, signed_scope: dict, signer) -> dict:
    """Online preparation of a bobbin's historical context for the device. Read-only. The signed scope (verified with the issuer's key) proves WHICH by-bobbin forms the user holds
    on that machine; the sector scope of the user limits which bobbins are visible, exactly as in the online consultation. Nothing is created and nothing is approved."""
    from app.offline_scope.signing import verify_scope
    from app.authz.policies import Operation
    if principal.must_change or not isinstance(device_key, uuid.UUID) or device_key.version != 4 or not verify_scope(signed_scope, trusted_public_key_b64url=signer.public_b64url):
        raise BobbinContextDenied()
    sp = signed_scope["payload"]
    if sp.get("kind") != "scope_readiness_only" or sp.get("subject_user_id") != str(principal.user_id) or sp.get("device_key") != str(device_key) or not isinstance(sp.get("snapshot_id"), str):
        raise BobbinContextDenied()
    if not any(isinstance(e, dict) and e.get("machine_code") == machine_code and e.get("operation") == Operation.QUALITY_BOBBIN_CAPTURE.value for e in sp.get("form_scopes", [])):
        raise BobbinContextDenied()
    return {"snapshot_id": sp["snapshot_id"], "machine_code": machine_code, "contexts": load_by_code(connection, machine_code, bobbin_code, principal.sectors)}
