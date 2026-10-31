"""Motor central de autorización efectiva (MF-13-01D.1). Ver app/authz/engine.py. Todavía NO está conectado a ningún endpoint productivo."""

from app.authz.engine import Decision, authorize, require
from app.authz.errors import AuthorizationDenied, AuthorizationUnavailable, ResourceNotFound, public_response
from app.authz.policies import POLICIES, Operation, policy_for

__all__ = ["Decision", "authorize", "require", "AuthorizationDenied", "AuthorizationUnavailable", "ResourceNotFound", "public_response", "POLICIES", "Operation", "policy_for"]
