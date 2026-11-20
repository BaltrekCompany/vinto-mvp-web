"""OFF-04.6: signed SYNTHETIC fixture for the client contract tests (Node): scope and packages of the ten Quality forms issued by the QA synthetic issuer, one bobbin context, and the
values, hashes and context versions the BACKEND computes, so the browser code is proven byte-compatible with the server.  Usage:  python -m tests.off046_fixture <out.json>"""
import json
import sys
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.offline_capture import contract as C
from app.offline_quality import bobbin_context
from app.offline_quality.synthetic import SyntheticBobbin
from app.qa_offline_pilot import PilotGrant
from app.qa_pilot_auth import SyntheticIssuer, signer_from_seed
from tests import off045b06b_support as S
from tests import off046_support as T


def build() -> dict:
    signer = signer_from_seed(S.new_seed())
    user = type("P", (), {"user_id": uuid4(), "must_change": False})()
    device = uuid4()
    grants = tuple(PilotGrant.model_validate(g) for g in T.grants_all(user.user_id))
    bobbins = tuple(SyntheticBobbin.model_validate(b) for b in T.BOBBINS)
    issuer = SyntheticIssuer(grants, signer, bobbins=bobbins)
    scope = issuer.scope(user, device, [T.MACHINE])
    packages = {f: issuer.package(user, device, T.MACHINE, f, scope) for f in T.FORMS}
    ctx = issuer.bobbin_contexts(user, device, T.MACHINE, T.BOBBIN_A["bobbin_code"], scope)["contexts"][0]
    snapshot = scope["payload"]["snapshot_id"]
    expected = {}
    for f in T.FORMS:
        values, calculated = T.valid_values(f)
        payload = {"synthetic": True, "payload": values}
        entry = {"values": values, "calculated": calculated}
        if f in T.BY_BOBBIN:
            payload["bobbin"] = {"bobbin_id": ctx["bobbin_id"], "context_digest": ctx["context_digest"]}
            entry["context_version"] = bobbin_context.context_version(snapshot, ctx["bobbin_id"], ctx["context_digest"])
        entry["payload_sha256"] = C.canonical_sha256(payload)
        expected[f] = entry
    return {"identity": {"ownerId": str(user.user_id), "deviceKey": str(device)}, "pin": signer.public_b64url, "scope": scope, "packages": packages, "bobbin": ctx, "expected": expected,
            "by_machine": list(T.BY_MACHINE), "by_bobbin": list(T.BY_BOBBIN), "generated_at": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    with open(sys.argv[1], "w", encoding="utf-8") as fh:
        json.dump(build(), fh)
    print("fixture written")
