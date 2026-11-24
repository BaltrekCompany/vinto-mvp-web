"""VINTO OFF-04.8 — QA-only ASGI entrypoint for operational Quality offline.

Run independently from app.main; all operational capabilities OFF by default.
Do not use this app for production. No configuration activates outside APP_ENV=qa
and the physical database identity vinto_qa_offline.
"""
from __future__ import annotations

import os

from app.config import settings
from app.database import open_connection
from app.offline_scope.signing import OfflineSigningUnavailable, load_signer
from app.quality.offline_qa_app import create_offline_qa_app

def _on(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    if value not in ("", "0", "1", "false", "true"):
        raise ValueError("invalid_offline_qa_flag")
    return value in ("1", "true")


def build_app():
    issue = _on("VINTO_OFFLINE_QA_CAPTURE_ISSUE")
    receive = _on("VINTO_OFFLINE_QA_CAPTURE_RECEIVE")
    if not issue and not receive:
        return create_offline_qa_app()
    if settings.app_env != "qa":
        raise RuntimeError("offline_operational_qa_not_authorized")
    if not settings.offline_scope_issue_enabled:
        raise RuntimeError("offline_qa_signing_disabled")
    try:
        signer = load_signer()
    except OfflineSigningUnavailable:
        raise RuntimeError("offline_qa_signer_unavailable") from None
    return create_offline_qa_app(
        app_env=settings.app_env, database_name="vinto_qa_offline",
        issue_enabled=issue, receive_enabled=receive, signer=signer,
        trusted_public_key_b64url=signer.public_b64url,
        open_connection=open_connection,
        allowed_origin=os.environ.get("VINTO_OFFLINE_QA_ORIGIN", ""),
    )

app = build_app()
