"""MF-13-01D.3B.2: revalidación del actor de una escritura administrativa DENTRO de la transacción de la escritura.

`require_permission(USER_MANAGE)` resuelve la sesión con la conexión de negocio y la escritura se ejecuta después, con la conexión de identidad y en otra transacción: entre ambas
un administrador desactivado (o sin perfil con `user.manage`) podía todavía completar una operación en curso. Esta función cierra esa ventana:

  - comprueba que el actor sigue activo y conserva `user.manage` por un perfil activo, en la MISMA transacción que escribe;
  - toma `FOR KEY SHARE` sobre su fila de usuario, de perfil de usuario y de perfil. Choca con el `FOR UPDATE` de `deactivate_user` (la desactivación espera a que la
    escritura confirme, o la escritura ve la desactivación ya confirmada y se rechaza) y NO choca con el `FOR NO KEY UPDATE` de `revoke_sector` ni con el `FOR SHARE` del motor
    de autorización (sin riesgo de interbloqueo cuando dos administradores se modifican mutuamente).

No comprueba la sesión: una sesión cerrada con `logout` justo en paralelo no invalida una operación ya iniciada (la desactivación del usuario sí, porque revoca sus sesiones).
Necesita `UPDATE` de al menos una columna sobre esas tablas (privilegio de columna suficiente), que el rol de identidad conserva.
"""

from app.admin.errors import ActorNotAuthorized
from app.auth.permissions import USER_MANAGE, permissions_for_profiles


def require_actor_authorized(connection, actor_id) -> None:
    if connection.execute('SELECT 1 FROM vinto_master."user" WHERE id = %s AND active FOR KEY SHARE', (actor_id,)).fetchone() is None:
        raise ActorNotAuthorized()
    codes = [row[0] for row in connection.execute(
        """SELECT p.code FROM vinto_master.user_profile up JOIN vinto_master.profile p ON p.id = up.profile_id
           WHERE up.user_id = %s AND p.active FOR KEY SHARE OF up, p""", (actor_id,)).fetchall()]
    if USER_MANAGE not in permissions_for_profiles(codes):
        raise ActorNotAuthorized()
