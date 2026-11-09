"""USR-03: administrator-only user editing and password reset.

One active profile per user is preserved. No credential plaintext is logged or
returned, and no sector/machine/form grant is created, revoked or changed.
User/role updates are audited by the existing vinto_audit triggers; password
reset writes a sanitized manual audit event and an auth_event (never a hash).
"""

import uuid

from app.admin.actor import require_actor_authorized
from app.admin.errors import (LastActiveAdministrator, NewUserInvalid, ProfileUnavailable,
                              UserNotFound, UserProfileInvalid)
from app.auth.errors import InvalidDisplayNameError, InvalidPasswordPolicyError
from app.auth.passwords import HASH_ALGORITHM, hash_password, validate_password_policy
from app.auth.permissions import DATA_BALTREK, PROFILE_PERMISSIONS
from app.auth.service import _clean_display_name


def _actor_context(connection, actor_id, request_id, reason):
    connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(actor_id),))
    connection.execute("SELECT set_config('vinto.request_id', %s, true)", (request_id,))
    connection.execute("SELECT set_config('vinto.reason', %s, true)", (reason,))


def _admin_ids_locked(connection):
    """Serialize with the existing deactivate_user last-admin FOR UPDATE guard.

    Lock the complete active admin set before changing a profile; a concurrent
    deactivation rechecks the active user condition under READ COMMITTED.
    """
    return [row[0] for row in connection.execute(
        """SELECT u.id FROM vinto_master."user" u
           JOIN vinto_master.user_profile up ON up.user_id=u.id
           JOIN vinto_master.profile p ON p.id=up.profile_id
           WHERE u.active AND p.active AND p.code=%s
           ORDER BY u.id FOR UPDATE OF u""", (DATA_BALTREK,)).fetchall()]


def edit_user(connection, *, target_id, actor_id, display_name=None, profile_code=None):
    if display_name is None and profile_code is None:
        raise NewUserInvalid()
    try:
        clean_name = _clean_display_name(display_name) if display_name is not None else None
    except InvalidDisplayNameError:
        raise NewUserInvalid() from None
    if profile_code is not None and profile_code not in PROFILE_PERMISSIONS:
        raise ProfileUnavailable()

    request_id = "admin-user-edit:" + str(uuid.uuid4())
    with connection.transaction():
        require_actor_authorized(connection, actor_id)
        # Lock the admin set BEFORE the target when a profile might change, to
        # serialize with legacy CLI deactivation and protect the last admin.
        admin_ids = _admin_ids_locked(connection) if profile_code is not None else []
        row = connection.execute(
            """SELECT u.active, u.display_name, c.username, p.code
               FROM vinto_master."user" u
               JOIN vinto_auth.credential c ON c.user_id=u.id
               JOIN vinto_master.user_profile up ON up.user_id=u.id
               JOIN vinto_master.profile p ON p.id=up.profile_id
               WHERE u.id=%s FOR UPDATE OF u, up""", (target_id,)).fetchone()
        if row is None:
            # Keep 404 for a genuinely absent user; treat missing profile or
            # credential as data corruption instead of silently repairing it.
            exists = connection.execute('SELECT 1 FROM vinto_master."user" WHERE id=%s', (target_id,)).fetchone()
            if exists:
                raise UserProfileInvalid()
            raise UserNotFound()
        active, old_name, username, old_profile = row
        changed_name = clean_name is not None and clean_name != old_name
        changed_profile = profile_code is not None and profile_code != old_profile
        if changed_profile:
            available = connection.execute(
                "SELECT 1 FROM vinto_master.profile WHERE code=%s AND active FOR KEY SHARE",
                (profile_code,)).fetchone()
            if available is None:
                raise ProfileUnavailable()
            if active and target_id in admin_ids and len(admin_ids) <= 1 and profile_code != DATA_BALTREK:
                raise LastActiveAdministrator()
        changed = changed_name or changed_profile
        sessions_revoked = 0
        if changed:
            _actor_context(connection, actor_id, request_id, "admin user edit")
            if changed_name:
                connection.execute('UPDATE vinto_master."user" SET display_name=%s WHERE id=%s',
                                   (clean_name, target_id))
            if changed_profile:
                connection.execute(
                    """UPDATE vinto_master.user_profile
                       SET profile_id=(SELECT id FROM vinto_master.profile WHERE code=%s AND active)
                       WHERE user_id=%s""", (profile_code, target_id))
                sessions_revoked = connection.execute(
                    "UPDATE vinto_auth.session SET revoked_at=clock_timestamp() WHERE user_id=%s AND revoked_at IS NULL",
                    (target_id,)).rowcount
    return {"user_id": target_id, "username": username,
            "display_name": clean_name if changed_name else old_name,
            "profile_code": profile_code if changed_profile else old_profile,
            "active": active, "changed": changed, "sessions_revoked": sessions_revoked,
            "request_id": request_id if changed else None}


def reset_password(connection, *, target_id, actor_id, password):
    try:
        validate_password_policy(password)
    except InvalidPasswordPolicyError:
        raise NewUserInvalid() from None
    # Costly hashing before opening locks; this still runs only after the API
    # authorization dependency has approved user.manage.
    new_hash = hash_password(password)
    request_id = "admin-password-reset:" + str(uuid.uuid4())
    with connection.transaction():
        require_actor_authorized(connection, actor_id)
        target = connection.execute(
            """SELECT 1 FROM vinto_master."user" u
               JOIN vinto_auth.credential c ON c.user_id=u.id
               WHERE u.id=%s FOR UPDATE OF u,c""", (target_id,)).fetchone()
        if target is None:
            raise UserNotFound()
        _actor_context(connection, actor_id, request_id, "admin password reset")
        connection.execute(
            """UPDATE vinto_auth.credential
               SET password_hash=%s, hash_algorithm=%s, password_changed_at=clock_timestamp(),
                   must_change=false, failed_attempts=0, locked_until=NULL
               WHERE user_id=%s""", (new_hash, HASH_ALGORITHM, target_id))
        sessions_revoked = connection.execute(
            "UPDATE vinto_auth.session SET revoked_at=clock_timestamp() WHERE user_id=%s AND revoked_at IS NULL",
            (target_id,)).rowcount
        connection.execute(
            "INSERT INTO vinto_auth.auth_event (user_id,event,request_id) VALUES (%s,'password_change',%s)",
            (target_id, request_id))
        # credential deliberately has no generic audit trigger (never copy a
        # password hash into audit tables). Only known safe metadata is emitted.
        connection.execute(
            """INSERT INTO vinto_audit.audit_event
               (entity_schema, entity_table, entity_key, action, actor_id, request_id,
                reason, old_data, new_data)
               VALUES ('vinto_auth','credential',
                       jsonb_build_object('user_id', %s::text),
                       'UPDATE',%s,%s,'admin password reset',
                       NULL,jsonb_build_object('must_change',false,'sessions_revoked',%s))""",
            (target_id, actor_id, request_id, sessions_revoked))
    return {"user_id": target_id, "changed": True, "sessions_revoked": sessions_revoked,
            "must_change": False, "request_id": request_id}
