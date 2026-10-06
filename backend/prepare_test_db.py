"""Crea (si falta) la base de pruebas y le aplica las migraciones. Idempotente."""

import sys

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.config import settings
from app.db_guard import UnsafeDatabaseError, connect_test_database, is_test_database_name
from migrate import MigrationError, apply, read_migrations


def main() -> int:
    try:
        if settings.test_database_url is None or not settings.test_database_url.get_secret_value():
            raise UnsafeDatabaseError("TEST_DATABASE_URL no está configurada")
        test_url = settings.test_database_url.get_secret_value()
        target = conninfo_to_dict(test_url).get("dbname", "")
        if not is_test_database_name(target):
            raise UnsafeDatabaseError(f"La base '{target}' no termina en '_test'; no se crea ni se migra")
        if settings.database_url is not None:
            dev_name = conninfo_to_dict(settings.database_url.get_secret_value()).get("dbname")
            if dev_name == target:
                raise UnsafeDatabaseError("TEST_DATABASE_URL apunta a la misma base que DATABASE_URL")
        # Conexión de mantenimiento a "postgres": la base de desarrollo no se toca.
        with psycopg.connect(make_conninfo(test_url, dbname="postgres"), autocommit=True,
                             connect_timeout=settings.db_connect_timeout) as admin:
            if admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target,)).fetchone():
                print(f"Base de pruebas existente: {target}")
            else:
                try:
                    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
                    print(f"Base de pruebas creada: {target}")
                except psycopg.errors.DuplicateDatabase:
                    print(f"Base de pruebas existente: {target}")
        with connect_test_database(autocommit=True, connect_timeout=settings.db_connect_timeout,
                                   options="-c lock_timeout=5000 -c statement_timeout=60000") as connection:
            apply(connection, read_migrations())
        return 0
    except (UnsafeDatabaseError, MigrationError) as error:
        print(f"Preparación detenida: {error}")
    except psycopg.Error as error:
        print(f"Preparación fallida: {type(error).__name__}; SQLSTATE={error.sqlstate or 'n/a'}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
