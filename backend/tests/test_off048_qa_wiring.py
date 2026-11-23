"""OFF-04.8 — no operational QA writes without explicit activation.

Pure FastAPI and configuration tests; no VPS, no migration, no user records.
Database-backed positive scenarios remain in test_off048p_real_mf13_pg17.
"""
from __future__ import annotations

from dataclasses import dataclass
from app.offline_scope.signing import encode_b64
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.quality.offline_qa_app import (
    OfflineQaConfigurationError, create_offline_qa_app, QA_DATABASE,
)
from app.quality.offline_qa_capture_scope_router import create_qa_capture_scope_router


class FakeDb:
    def __init__(self, name=QA_DATABASE):
        self.name = name

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, statement):
        assert "current_database()" in statement
        return Mock(fetchone=lambda: (self.name,))


@dataclass(frozen=True)
class FakeSigner:
    public_b64url: str = encode_b64(bytes(range(32)))


def opts(**overrides):
    baseline = dict(
        app_env="qa", database_name=QA_DATABASE,
        issue_enabled=True, receive_enabled=False,
        signer=FakeSigner(), trusted_public_key_b64url=encode_b64(bytes(range(32))),
        open_connection=lambda: FakeDb(),
        allowed_origin="https://qa.example.test",
    )
    baseline.update(overrides)
    return baseline


def test_default_qa_app_has_no_operational_capture_or_issue_routes():
    app = create_offline_qa_app()
    client = TestClient(app)
    assert client.post("/api/offline/capture-scope", json={}).status_code == 403
    assert client.post("/api/offline/captures", json={}).status_code == 403
    assert client.get("/api/offline/captures/11111111-1111-4111-8111-111111111111").status_code == 404
    assert all(not getattr(route, 'path', '').endswith("/capture-scope") for route in app.routes)
    assert all(not getattr(route, 'path', '').endswith("/captures") for route in app.routes)


@pytest.mark.parametrize("overrides", (
    {"app_env": "production"},
    {"app_env": "local"},
    {"database_name": "vinto_prod"},
    {"open_connection": None},
    {"signer": None},
    {"trusted_public_key_b64url": "different-key"},
    {"allowed_origin": "http://qa.example.test"},
    {"allowed_origin": "https://qa.example.test/evil"},
))
def test_active_qa_wiring_rejects_bad_environment_or_key(overrides):
    with pytest.raises(OfflineQaConfigurationError):
        create_offline_qa_app(**opts(**overrides))


def test_qa_wiring_checks_postgres_actual_identity_not_only_config_label():
    with pytest.raises(OfflineQaConfigurationError, match="qa_database_identity_mismatch"):
        create_offline_qa_app(**opts(open_connection=lambda: FakeDb("vinto_prod")))


def test_issue_only_does_not_expose_receiver_and_requires_exact_origin():
    app = create_offline_qa_app(**opts())
    client = TestClient(app)
    assert client.post("/api/offline/captures", json={}).status_code == 403
    assert client.post("/api/offline/capture-scope", json={}).status_code == 403
    response = client.post("/api/offline/capture-scope", headers={"origin":"https://qa.example.test"}, json={})
    # The pydantic contract rejects malformed data before database effects.
    assert response.status_code in (401, 422)
    assert all(not getattr(route, 'path', '').endswith("/captures") for route in app.routes)


def test_receiver_only_does_not_issue_capture_capable_scope():
    app = create_offline_qa_app(**opts(issue_enabled=False, receive_enabled=True))
    assert all(not getattr(route, 'path', '').endswith("/capture-scope") for route in app.routes)
    assert any(getattr(route, 'path', '').endswith("/captures") for route in app.routes)


def test_qa_capture_endpoint_factory_is_disabled_by_default():
    app = create_offline_qa_app()
    assert all(not getattr(route, 'path', '').endswith("/capture-scope") for route in app.routes)
    router = create_qa_capture_scope_router()
    app.include_router(router)
    response = TestClient(app).post(
        "/api/offline/capture-scope",
        json={"device_key": "33333333-3333-4333-8333-333333333333", "machine_codes":["MP1"]},
    )
    assert response.status_code == 403
