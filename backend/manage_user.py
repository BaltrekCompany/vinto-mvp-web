"""CLI administrativa restringida para desactivar/reactivar una cuenta interna (CLOUD-DEP-02B.2-G.12-B2/-R1).

  python manage_user.py --target test --action deactivate --username qa.jefatura \\
      --actor-username qa.admin --reason "piloto cerrado: baja temporal" --yes

  python manage_user.py --target test --action reactivate --username qa.jefatura \\
      --actor-username qa.admin --reason "piloto cerrado: alta de nuevo" --yes

No crea, borra ni modifica contraseñas, perfiles ni sectores: solo cambia vinto_master."user".active y,
al desactivar, revoca de forma permanente las sesiones vigentes del usuario (ver app/auth/service.py).

--target es obligatorio y nunca tiene un valor por defecto productivo, igual que create_user.py.
--target test exige TEST_DATABASE_URL y una base cuyo nombre termine en "_test" (connect_test_database,
sin cambios respecto de create_user.py). --target dev NUNCA confía en el nombre lógico "dev" ni en el
DSN que haya en DATABASE_URL: después de conectar, pregunta a psycopg la identidad YA RESUELTA de la
conexión (host/IP, puerto y base — nunca el texto crudo de la cadena de conexión) y exige que coincida,
exactamente, con una entrada de la variable de entorno MANAGE_USER_DEV_ALLOWED_TARGETS
("host:puerto/base,host2:puerto2/base2"). Sin esa variable no hay NINGÚN destino "dev" autorizado por
defecto (modo cerrado). Un nombre de base productiva conocido (vinto_piloto) se rechaza incondicionalmente
aunque alguien lo añadiera, por error, al allowlist. Esta protección vive solo aquí: no modifica
create_user.py ni app/db_guard.py.

--actor-username por sí solo NO autoriza nada: desde G.12-B2-R1 la CLI exige probar la identidad del
actor con su propia contraseña (--actor-password-env, o un único prompt getpass si se omite) y la
AUTENTICA de verdad contra vinto_auth.credential (app.auth.service.authenticate) antes de ejecutar
cualquier acción. Sin esa prueba, nombrar a un administrador por su username ya no basta para actuar en
su nombre: un operador no puede suplantar a otro administrador sin conocer su contraseña real.

Sin --yes la CLI solo valida argumentos y motivo y muestra una vista previa: NO abre conexión, NO
autentica al actor (autenticar ya escribe un evento en vinto_auth.auth_event, incluso si falla) y NO
escribe nada. La autenticación del actor y la escritura ocurren únicamente tras una segunda invocación
explícita con --yes.
"""

import argparse
import getpass
import os
import sys

import psycopg

from app.auth.errors import AuthError
from app.auth.permissions import USER_MANAGE
from app.auth.service import authenticate, deactivate_user, reactivate_user
from app.config import settings
from app.db_guard import UnsafeDatabaseError, connect_test_database

CONNECTION_OPTIONS = "-c lock_timeout=5000 -c statement_timeout=30000"

ACTIONS = {"deactivate": deactivate_user, "reactivate": reactivate_user}

# Nombres de base productiva conocidos: rechazados incondicionalmente, incluso si aparecieran en el
# allowlist por error del operador. No es la defensa principal (el allowlist por defecto vacío lo es):
# es una segunda capa para un nombre que ya sabemos que nunca debe tocar esta herramienta.
FORBIDDEN_DATABASE_NAMES = frozenset({"vinto_piloto"})

DEV_ALLOWLIST_ENV = "MANAGE_USER_DEV_ALLOWED_TARGETS"


class UnauthorizedDevTargetError(UnsafeDatabaseError):
    """--target dev intentó operar contra un destino no autorizado explícitamente por el operador."""


def _target_identity(connection) -> str:
    """Identidad REAL de la conexión ya abierta, tal como la resolvió psycopg (nunca el texto del DSN
    ni el nombre lógico "dev"): host/IP (hostaddr si está disponible, si no host), puerto y base."""
    info = connection.info
    host = info.hostaddr or info.host or "?"
    return f"{host}:{info.port}/{info.dbname}"


def _authorized_dev_targets() -> frozenset[str]:
    raw = os.environ.get(DEV_ALLOWLIST_ENV, "")
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def assert_dev_target_authorized(connection) -> str:
    """Ver el docstring del módulo. Devuelve la identidad autorizada (para el mensaje final) o lanza
    UnauthorizedDevTargetError sin exponer credenciales (solo host/IP, puerto y nombre de base)."""
    dbname = connection.info.dbname
    if dbname in FORBIDDEN_DATABASE_NAMES:
        raise UnauthorizedDevTargetError(f"'{dbname}' es el nombre de una base productiva conocida; rechazado incondicionalmente")
    allowed = _authorized_dev_targets()
    identity = _target_identity(connection)
    if not allowed:
        raise UnauthorizedDevTargetError(
            f"--target dev requiere {DEV_ALLOWLIST_ENV} configurada explícitamente; no hay ningún destino autorizado por defecto")
    if identity not in allowed:
        raise UnauthorizedDevTargetError(f"El destino conectado ({identity}) no está en {DEV_ALLOWLIST_ENV}")
    return identity


def open_connection(target: str):
    """Conexión del rol de IDENTIDAD (MF-13-01D.3B.2): IDENTITY_TEST_DATABASE_URL / IDENTITY_DATABASE_URL si están definidas; si no, TEST_DATABASE_URL / DATABASE_URL
    como antes. Con la URL de identidad definida no hay retroceso silencioso: si falla, falla."""
    kwargs = {"autocommit": True, "connect_timeout": settings.db_connect_timeout, "options": CONNECTION_OPTIONS}
    if target == "test":
        dedicated = settings.identity_test_database_url
        return connect_test_database(dedicated.get_secret_value() if dedicated is not None and dedicated.get_secret_value() else None, **kwargs)
    dedicated = settings.identity_database_url
    url = dedicated if dedicated is not None and dedicated.get_secret_value() else settings.database_url
    if url is None or not url.get_secret_value():
        raise UnsafeDatabaseError("DATABASE_URL no está configurada")
    connection = psycopg.connect(url.get_secret_value(), **kwargs)
    try:
        assert_dev_target_authorized(connection)
    except BaseException:
        connection.close()
        raise
    return connection


def read_actor_password(password_env: str | None) -> str:
    if password_env:
        value = os.environ.get(password_env)
        if not value:
            raise AuthError(f"La variable de entorno {password_env} no está definida")
        return value
    return getpass.getpass("Contraseña del actor (prueba de identidad, nunca se imprime): ")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    parser.add_argument("--target", choices=("test", "dev"), required=True, help="Base de destino (obligatorio)")
    parser.add_argument("--action", choices=tuple(ACTIONS), required=True)
    parser.add_argument("--username", required=True, help="Cuenta objetivo (identificador inequívoco: username normalizado)")
    parser.add_argument("--actor-username", required=True, help="Cuenta administrativa que autoriza la operación")
    parser.add_argument("--actor-password-env", metavar="VAR", help="Leer la contraseña del actor de esta variable (solo automatización)")
    parser.add_argument("--reason", required=True, help="Motivo obligatorio, se registra en vinto_audit.audit_event")
    parser.add_argument("--yes", action="store_true", help="Confirma la escritura; sin esta opción solo se valida (dry-run)")
    args = parser.parse_args(argv)

    if not args.reason.strip():
        print("Operación detenida: --reason no puede estar vacío")
        return 1
    if not args.yes:
        print(f"Vista previa (sin conectar ni autenticar): target={args.target} action={args.action} username={args.username} "
              f"actor={args.actor_username} reason={args.reason!r}")
        print("Repita el comando con --yes para confirmar: se autenticará al actor y se ejecutará la escritura.")
        return 2

    action = ACTIONS[args.action]
    try:
        actor_password = read_actor_password(args.actor_password_env)
        with open_connection(args.target) as connection:
            database = connection.execute("SELECT current_database()").fetchone()[0]
            principal = authenticate(connection, args.actor_username, actor_password)
            if not principal.can(USER_MANAGE):
                raise AuthError("El actor autenticado no conserva un perfil con user.manage")
            result = action(connection, username=args.username, actor_username=principal.username, reason=args.reason)
    except AuthError as error:
        print(f"Operación no aplicada: {error}")
        return 1
    except UnsafeDatabaseError as error:
        print(f"Operación detenida: {error}")
        return 1
    except psycopg.Error as error:
        print(f"Operación no aplicada: {type(error).__name__}; SQLSTATE={error.sqlstate or 'n/a'}; transacción revertida")
        return 1
    estado = "activo" if result.active else "inactivo"
    cambio = "aplicado" if result.changed else "sin cambios (ya estaba en ese estado)"
    print(f"{args.action} en {database}: username={result.username} id={result.user_id} estado={estado} ({cambio})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
