"""USR-04: logical user deactivation/reactivation via authenticated administration.

Uses the same last-administrator advisory lock and locked administrator set as
USR-03 and the legacy CLI. No credentials, profile, grants, OT, captures or
historical records are modified. Revoked sessions are never restored.
"""

import uuid

from app.admin.actor import require_actor_authorized
from app.admin.errors import LastActiveAdministrator, UserNotFound
from app.admin.user_editing import _actor_context, _admin_ids_locked
from app.auth.service import ADMIN_PROFILE_CODES, LAST_ADMIN_CHANGE_LOCK_KEY, _clean_reason


def change_user_state(connection, *, target_id, actor_id, active, reason):
    """One transaction: authorize actor, protect last admin, audit and update state.

    No-op requests return changed=False and do not write an audit record. The
    advisory lock serializes with the existing CLI deactivation and USR-03
    profile changes, including attempts targeting different administrators.
    """
    clean_reason = _clean_reason(reason)
    if not isinstance(active, bool):
        raise ValueError("active must be a boolean")
    request_id = "admin-user-" + ("reactivate:" if active else "deactivate:") + str(uuid.uuid4())
    with connection.transaction():
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (LAST_ADMIN_CHANGE_LOCK_KEY,))
        require_actor_authorized(connection, actor_id)

        # The shared lock prevents a concurrent profile demotion / CLI
        # deactivation from racing the last active administrator check.
        holds_admin = False
        admin_ids = []
        if not active:
            holds_admin = connection.execute(
                """SELECT EXISTS(
                       SELECT 1 FROM vinto_master.user_profile up
                       JOIN vinto_master.profile p ON p.id=up.profile_id
                       WHERE up.user_id=%s AND p.active AND p.code=ANY(%s))""",
                (target_id, list(ADMIN_PROFILE_CODES))).fetchone()[0]
            if holds_admin:
                admin_ids = _admin_ids_locked(connection)

        target = connection.execute(
            """SELECT u.active, c.username
               FROM vinto_master."user" u
               JOIN vinto_auth.credential c ON c.user_id=u.id
               WHERE u.id=%s FOR UPDATE OF u""", (target_id,)).fetchone()
        if target is None:
            raise UserNotFound()
        old_active, username = target

        if old_active == active:
            return {"user_id": target_id, "username": username, "active": active,
                    "changed": False, "sessions_revoked": 0, "request_id": None}
        if not active and holds_admin and target_id in admin_ids and len(admin_ids) <= 1:
            raise LastActiveAdministrator()

        _actor_context(connection, actor_id, request_id, clean_reason)
        connection.execute('UPDATE vinto_master."user" SET active=%s WHERE id=%s', (active, target_id))
        sessions_revoked = 0
        if not active:
            sessions_revoked = connection.execute(
                """UPDATE vinto_auth.session SET revoked_at=clock_timestamp()
                   WHERE user_id=%s AND revoked_at IS NULL""", (target_id,)).rowcount

    return {"user_id": target_id, "username": username, "active": active,
            "changed": True, "sessions_revoked": sessions_revoked, "request_id": request_id}
