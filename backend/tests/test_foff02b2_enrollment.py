"""FOFF-02B.2: disabled-by-default, grant-gated device registration."""
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException, Response

from app.offline_production import ProductionEnrollmentIn, enroll_production_device


def _catalog(eligible):
    return SimpleNamespace(sectors=[
        SimpleNamespace(code="CONVERSION", machines=[
            SimpleNamespace(forms=[
                SimpleNamespace(eligible=eligible)], bobbin_forms=None),
        ]),
    ])


def _user():
    return SimpleNamespace(user_id=uuid.uuid4(), sectors=["CONVERSION"])


def _enroll(*, enabled, eligible, device_key=None):
    user = _user()
    with patch("app.offline_production.settings.offline_conversion_preparation_signing_seed_hex", None), \
         patch("app.offline_production.settings.offline_production_enrollment_enabled", enabled), \
         patch("app.offline_production.production_machines", return_value=_catalog(eligible)), \
         patch("app.offline_production.central_captures._context") as context, \
         patch("app.offline_production.central_captures._resolve_device") as resolver:
        response = Response()
        try:
            result = enroll_production_device(
                ProductionEnrollmentIn(device_key=device_key or uuid.uuid4()),
                response=response, user=user, connection=_Connection())
            return result, response, resolver, context
        except HTTPException as exc:
            return exc, response, resolver, context


class _Connection:
    def transaction(self):
        from contextlib import nullcontext
        return nullcontext()


def test_disabled_never_writes_or_queries_grants():
    with patch("app.offline_production.production_machines") as available:
        with patch("app.offline_production.settings.offline_production_enrollment_enabled", False):
            with pytest.raises(HTTPException) as raised:
                enroll_production_device(ProductionEnrollmentIn(device_key=uuid.uuid4()),
                                         response=Response(), user=_user(), connection=_Connection())
        assert raised.value.status_code == 503
        available.assert_not_called()


@pytest.mark.parametrize("eligible", [False, None])
def test_missing_grant_denied_without_device_write(eligible):
    result, response, resolver, context = _enroll(enabled=True, eligible=eligible)
    assert isinstance(result, HTTPException)
    assert result.status_code == 403
    resolver.assert_not_called()
    context.assert_not_called()
    assert response.headers["Cache-Control"] == "no-store"


def test_granted_device_is_enrolled_without_capture_authority():
    key = uuid.uuid4()
    result, response, resolver, context = _enroll(enabled=True, eligible=True, device_key=key)
    assert result == {"device_key": str(key), "enrolled": True, "preparation_signing_pin": None, "captureEnabled": False}
    assert response.headers["Cache-Control"] == "no-store"
    resolver.assert_called_once_with(resolver.call_args.args[0], str(key), None)
    context.assert_called_once()


def test_non_v4_device_rejected_before_write():
    result, _, resolver, context = _enroll(enabled=True, eligible=True, device_key=uuid.UUID("00000000-0000-1000-8000-000000000000"))
    assert isinstance(result, HTTPException)
    assert result.status_code == 422
    resolver.assert_not_called()
    context.assert_not_called()


def test_inactive_device_rejection_is_not_swallowed():
    from app.capture_errors import DeviceInactiveError
    with patch("app.offline_production.settings.offline_production_enrollment_enabled", True), \
         patch("app.offline_production.production_machines", return_value=_catalog(True)), \
         patch("app.offline_production.central_captures._context"), \
         patch("app.offline_production.central_captures._resolve_device", side_effect=DeviceInactiveError()):
        with pytest.raises(DeviceInactiveError):
            enroll_production_device(ProductionEnrollmentIn(device_key=uuid.uuid4()),
                                     response=Response(), user=_user(), connection=_Connection())
