"""OFF-03D.7A — Reject operational writes in the isolated offline QA API.

The offline-readiness device test needs a small number of POSTs for session
and cryptographically signed read-only packages. It never needs central capture,
administration, approvals, work orders or synchronization write endpoints.

This guard is forcibly active whenever APP_ENV=qa, independent of feature flags.
It does not change local, CI, test or production behavior. It is not a replacement
for network-level QA access control, authenticated scopes or a separated DB.
"""

from __future__ import annotations

QA_ALLOWED_UNSAFE_REQUESTS = frozenset({
    ("POST", "/api/auth/login"),  # creates a QA session; never a production login
    ("POST", "/api/auth/logout"),  # revokes a QA session
    ("POST", "/api/offline/scope"),  # signed read-only machine scope, auth required
    ("POST", "/api/offline/quality-package"),  # signed read-only definition, auth required
})
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def qa_offline_request_permitted(*, app_env: str, method: str, path: str) -> bool:
    """Return False for every other mutating endpoint when running APP_ENV=qa.

    Use exact case-sensitive paths: aliases, suffixes, percent-encoded variants
    and unexpected future endpoints fail closed; URL routing still owns auth.
    """
    if app_env != "qa":
        return True
    if method in SAFE_METHODS:
        return True
    return (method, path) in QA_ALLOWED_UNSAFE_REQUESTS
