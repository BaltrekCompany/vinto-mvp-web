"""USR-02: backend-only administration of user creation and the active profile catalog.

The authenticated actor (never accepted from request JSON) is revalidated under
locks in the SAME transaction as the new account. A user receives one active
profile and an Argon2id credential, no implicit sector/machine/form grants.
No credential/hash is ever included in the return value or the audit payload.
"""

import uuid

from app.admin.actor import require_actor_authorized
from app.admin.errors import NewUserInvalid, ProfileUnavailable, UsernameAlreadyExists
from app.auth.errors import (InvalidDisplayNameError, InvalidPasswordPolicyError,
                             InvalidUsernameError, ProfileNotFoundError, UserAlreadyExistsError)
from app.auth.permissions import PROFILE_PERMISSIONS
from app.auth.service import create_user


def list_available_profiles(connection) -> list[dict]:
    rows = connection.execute(
        "SELECT code, name FROM vinto_master.profile WHERE active AND code = ANY(%s) ORDER BY code",
        (sorted(PROFILE_PERMISSIONS),),
    ).fetchall()
    return [{"code": code, "name": name} for code, name in rows]


def create_admin_user(connection, *, actor_id, username, display_name, profile_code, password) -> dict:
    if profile_code not in PROFILE_PERMISSIONS:
        raise ProfileUnavailable()

    request_id = "admin-user-create:" + str(uuid.uuid4())
    try:
        with connection.transaction():
            require_actor_authorized(connection, actor_id)
            # Domain create_user sets the request id / reason inside its nested
            # transaction; this actor id persists within the outer transaction.
            connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor_id),))
            created = create_user(connection, username=username, display_name=display_name,
                                  profile_code=profile_code, password=password,
                                  request_id=request_id, sectors=())
    except UserAlreadyExistsError:
        raise UsernameAlreadyExists() from None
    except ProfileNotFoundError:
        raise ProfileUnavailable() from None
    except (InvalidUsernameError, InvalidDisplayNameError, InvalidPasswordPolicyError):
        raise NewUserInvalid() from None

    return {"id": created.user_id, "username": created.username,
            "display_name": created.display_name, "active": True,
            "profiles": [created.profile_code], "sectors": []}
