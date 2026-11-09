"""Compuerta RG-MP3-01 para importar antes de activar código nuevo.

Emite exclusivamente un plan estructurado; no muestra conexiones ni secretos.
Sin --apply, la transacción es READ ONLY. Con --apply, exige una
confirmación externa en el script ops, reevalúa el plan y aplica con el
importador oficial; rechaza cualquier cambio adicional en el catálogo.
"""

import argparse
import json

from app.seed import reference
from app.seed.bundle import load_bundle, BUNDLE_DIR
from import_reference import open_connection

FORM_CODE = "VINTO-MP3-01"
EXPECTED = {"form": 1, "form_version": 1, "form_version_machine": 1, "field": 133}
ALLOWED_KEYS = set(EXPECTED)


class ImportGateError(Exception):
    pass


def check_bundle(bundle) -> None:
    """Exige el catálogo oficial, RG01 en MP3 y 25 contratos anteriores invariables."""
    form = next((f for f in bundle.forms if f["code"] == FORM_CODE), None)
    if form is None:
        raise ImportGateError("RG01_FORM_MISSING")
    if len(bundle.forms) != 26 or form["machines"] != ["MP3"] or form["version_number"] != 1:
        raise ImportGateError("RG01_SCOPE_INVALID")
    if len(form["fields"]) != 133 or sum(bool(f["required"]) for f in form["fields"]) != 7:
        raise ImportGateError("RG01_FIELD_CONTRACT_INVALID")
    if any(f["required"] and not f["key"].startswith("pulper_") for f in form["fields"]):
        raise ImportGateError("RG01_PULPER_REQUIREMENT_INVALID")
    if bundle.manifest.get("scope", {}).get("candidate") is True:
        raise ImportGateError("CANDIDATE_BUNDLE_NOT_APPROVED")


def validate_plan(result):
    """Solo se permite agregar RG01, o un no-op completo. Todo drift falla cerrado."""
    if result.conflicts:
        raise ImportGateError("REFERENCE_CONFLICT_OR_DRIFT")
    creates = {key: data["create"] for key, data in result.counts.items() if data["create"] != 0}
    if creates != EXPECTED and creates != {}:
        raise ImportGateError("UNEXPECTED_REFERENCE_CREATES:" + json.dumps(creates, sort_keys=True))
    return "new" if creates else "already_imported"


def inspect(connection, bundle):
    result = reference.dry_run(connection, bundle)
    return {"state": validate_plan(result), "pending_creates": result.pending_creates, "source_checksum": bundle.source_checksum}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Aplique solo después del gate/backup externo")
    args = parser.parse_args(argv)
    bundle = load_bundle(BUNDLE_DIR)
    check_bundle(bundle)
    with open_connection("dev") as connection:
        before = inspect(connection, bundle)
        print("MP3_RG01_PLAN=" + json.dumps(before, sort_keys=True))
        if not args.apply:
            print("MP3_RG01_DRY_RUN=PASS")
            return 0
        if before["state"] == "already_imported":
            print("MP3_RG01_IMPORT=NOOP")
            return 0
        result = reference.apply(connection, bundle)
        if result.mode not in {"applied", "noop"}:
            raise ImportGateError("REFERENCE_NOT_APPLIED")
        after = inspect(connection, bundle)
        if after["state"] != "already_imported":
            raise ImportGateError("REFERENCE_POSTCHECK_NOT_CLEAN")
        print("MP3_RG01_IMPORT=PASS")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ImportGateError as error:
        print("MP3_RG01_GATE=BLOCKED:" + str(error))
        raise SystemExit(2)
