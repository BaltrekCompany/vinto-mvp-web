"""OFF-03D.7C: immutable, read-only QA fixture contract. No DB or secrets.

This validates the *approved repository reference bundle* (not production rows).
The importer builds draft versions and publishes them after adding children,
within the same transaction. This file does not inspect a live QA database.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.auth.permissions import CALIDAD, QUALITY_CAPTURE, permissions_for_profiles
from app.quality.machine_capture_service import MACHINE_QUALITY_FORM_CODES
from app.seed.bundle import BUNDLE_DIR, Bundle, load_bundle

QA_USERNAME = "qa.offline.calidad"
QA_DISPLAY_NAME = "Calidad QA Offline (sintetico)"
QA_PROFILE = "CALIDAD"
QA_SECTOR = "BOBINAS"
QA_MACHINES = frozenset({"MP1", "MP3"})
QA_FORMS = frozenset({
    "VINTO-P1-18", "VINTO-P1-22", "VINTO-P1-26", "VINTO-P1-27"
})


class QaFixtureBlocked(ValueError):
    """A source or permission drift requires explicit human review."""


@dataclass(frozen=True)
class QaFixtureContract:
    source_checksum: str
    form_versions: tuple[tuple[str, int], ...]
    machines: tuple[str, ...]
    profile: str
    sector: str
    user: str
    publish_status: str = "NOT_VERIFIED_IN_QA_DB"
    effective_grants: str = "NOT_CREATED"


def validate_qa_bundle(bundle: Bundle) -> QaFixtureContract:
    scope = bundle.manifest.get("scope")
    if not isinstance(scope, dict) or scope.get("candidate") is True:
        raise QaFixtureBlocked("reference_scope_invalid")
    if not isinstance(bundle.source_checksum, str) or len(bundle.source_checksum) != 64:
        raise QaFixtureBlocked("source_checksum_invalid")
    if QA_PROFILE not in {p["code"] for p in bundle.profiles}:
        raise QaFixtureBlocked("qa_profile_missing")
    if QA_PROFILE != CALIDAD or QUALITY_CAPTURE not in permissions_for_profiles([QA_PROFILE]):
        raise QaFixtureBlocked("qa_profile_without_quality_capture")
    if not QA_MACHINES <= {m["code"] for m in bundle.machines
                          if m.get("sector") == QA_SECTOR}:
        raise QaFixtureBlocked("qa_machines_or_sector_missing")
    if not QA_FORMS <= MACHINE_QUALITY_FORM_CODES:
        raise QaFixtureBlocked("quality_machine_policy_drift")
    expected = {}
    for form in bundle.forms:
        if form.get("code") in QA_FORMS:
            code = form["code"]
            if code in expected or form.get("area") != "quality":
                raise QaFixtureBlocked("form_duplicate_or_not_quality")
            if set(form.get("machines", ())) != QA_MACHINES:
                raise QaFixtureBlocked("form_machine_scope_drift")
            version = form.get("version_number")
            if not isinstance(version, int) or isinstance(version, bool) or version < 1:
                raise QaFixtureBlocked("form_version_invalid")
            checksum = form.get("definition_checksum")
            if not isinstance(checksum, str) or len(checksum) != 64:
                raise QaFixtureBlocked("form_definition_checksum_missing")
            expected[code] = version
    if set(expected) != QA_FORMS:
        raise QaFixtureBlocked("qa_forms_missing")
    return QaFixtureContract(
        source_checksum=bundle.source_checksum,
        form_versions=tuple(sorted(expected.items())),
        machines=tuple(sorted(QA_MACHINES)),
        profile=QA_PROFILE,
        sector=QA_SECTOR,
        user=QA_USERNAME,
    )


def validate_repo_qa_fixture_contract() -> QaFixtureContract:
    # load_bundle verifies every manifest SHA256, size and internal reference.
    return validate_qa_bundle(load_bundle(BUNDLE_DIR))


if __name__ == "__main__":
    info = validate_repo_qa_fixture_contract()
    print("OFF03D7C_APPROVED_BUNDLE_CHECKSUM=PASS")
    print("OFF03D7C_CALIDAD_ROLE_MACHINE_FORMS=PASS")
    print("OFF03D7C_TARGET_FORMS=4")
    print("OFF03D7C_QA_PUBLISHED=" + info.publish_status)
    print("OFF03D7C_QA_USER_AND_GRANTS=" + info.effective_grants)
    print("OFF03D7C_NO_DATABASE_ACCESS=PASS")
