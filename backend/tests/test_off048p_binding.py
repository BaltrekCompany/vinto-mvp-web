"""OFF-04.8P: binding is opt-in, validates pinned key, and stays unmounted."""
from __future__ import annotations

import pytest
from unittest.mock import patch

from app.quality.offline_operational import QualityOperationalPromoter
from app.quality.offline_operational_binding import registered_scope_promoter


def test_binding_rejects_missing_or_invalid_pinned_key():
    for value in ("", "invalid", None):
        with pytest.raises(ValueError):
            registered_scope_promoter(trusted_public_key_b64url=value)


def test_binding_passes_the_same_connection_to_server_authority():
    import base64
    key = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
    promoter = registered_scope_promoter(trusted_public_key_b64url=key)
    assert isinstance(promoter, QualityOperationalPromoter)
    principal, capture, connection = object(), object(), object()
    with patch(
        "app.quality.offline_operational_binding.verify_registered_capture_scope",
        return_value=True,
    ) as verifier:
        assert promoter._verify_capture_scope(principal, capture, connection) is True
        verifier.assert_called_once_with(
            connection, principal=principal, capture=capture,
            trusted_public_key_b64url=key,
        )


def test_binding_fails_closed_on_authority_refusal():
    import base64
    key = base64.urlsafe_b64encode(bytes(range(32))).decode().rstrip("=")
    promoter = registered_scope_promoter(trusted_public_key_b64url=key)
    with patch(
        "app.quality.offline_operational_binding.verify_registered_capture_scope",
        return_value=False,
    ):
        assert promoter._verify_capture_scope(object(), object(), object()) is False


def test_binding_is_not_mounted_in_main():
    from pathlib import Path
    main = (Path(__file__).parents[1] / "app" / "main.py").read_text()
    assert "offline_operational_binding" not in main
    assert "registered_scope_promoter" not in main
