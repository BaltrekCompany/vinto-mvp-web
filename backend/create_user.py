"""CLI para crear un usuario (user + user_profile + credential) en una sola transacción.

  python create_user.py --target test --username dev.jefatura --display-name "Jefatura DEV" --profile JEFATURA

La contraseña se pide con getpass (dos veces) y nunca se imprime ni se guarda. Para automatización
existe `--password-env NOMBRE`: lee la contraseña de esa variable de entorno, solo si se pide
explícitamente, y tampoco se imprime. No hay opción para pasar la contraseña como argumento.
No crea perfiles: el perfil debe existir y estar activo. --target es obligatorio.
Sin --sector el usuario no accede a ningún sector; las concesiones son explícitas (--sector BOBINAS, repetible).
"""

import argparse
import getpass
import os
import sys

import psycopg

from app.auth.errors import AuthError
from app.auth.service import create_user
from app.config import settings
from app.db_guard import UnsafeDatabaseError, connect_test_database

CONNECTION_OPTIONS = "-c lock_timeout=5000 -c statement_timeout=30000"


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
    return psycopg.connect(url.get_secret_value(), **kwargs)


def read_password(password_env: str | None) -> str:
    if password_env:
        value = os.environ.get(password_env)
        if not value:
            raise AuthError(f"La variable de entorno {password_env} no está definida")
        return value
    password = getpass.getpass("Contraseña: ")
    if password != getpass.getpass("Confirmar contraseña: "):
        raise AuthError("Las contraseñas no coinciden")
    return password


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter, allow_abbrev=False)
    parser.add_argument("--target", choices=("test", "dev"), required=True, help="Base de destino (obligatorio)")
    parser.add_argument("--username", required=True)
    parser.add_argument("--display-name", required=True)
    parser.add_argument("--profile", required=True, help="Código de un perfil existente (por ejemplo JEFATURA)")
    parser.add_argument("--sector", action="append", default=[], metavar="CODIGO", help="Sector concedido explícitamente (repetible, p. ej. --sector BOBINAS). Sin --sector el usuario no accede a ningún sector")
    parser.add_argument("--password-env", metavar="VAR", help="Leer la contraseña de esta variable de entorno (solo automatización)")
    args = parser.parse_args(argv)

    try:
        password = read_password(args.password_env)
        with open_connection(args.target) as connection:
            database = connection.execute("SELECT current_database()").fetchone()[0]
            created = create_user(connection, username=args.username, display_name=args.display_name,
                                  profile_code=args.profile, password=password, sectors=args.sector)
    except AuthError as error:
        print(f"Usuario no creado: {error}")
        return 1
    except UnsafeDatabaseError as error:
        print(f"Operación detenida: {error}")
        return 1
    except psycopg.Error as error:
        print(f"Usuario no creado: {type(error).__name__}; SQLSTATE={error.sqlstate or 'n/a'}; transacción revertida")
        return 1
    print(f"Usuario creado en {database}: username={created.username} perfil={created.profile_code} sectores={','.join(args.sector) or 'ninguno'} id={created.user_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
