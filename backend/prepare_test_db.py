"""Crea (si falta) la base de pruebas y le aplica las migraciones. Idempotente."""

import sys

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from app.config import settings
from app.db_guard import UnsafeDatabaseError, assert_test_admin_allowed, connect_test_database, is_test_database_name, resolve_role_url
from migrate import MigrationError, apply, read_migrations


def main() -> int:
    try:
        # PG54-04: este script crea/destruye bases *_test (CREATEDB); en modo hardened, exige un APP_ENV
        # reconocido como no operativo, sin importar si TEST_ADMIN_DATABASE_URL está configurada.
        assert_test_admin_allowed()
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
        # Conexión de mantenimiento a "postgres": la base de desarrollo no se toca. PG54-04: resolve_role_url
        # honra pg_privilege_mode (en "hardened" exige TEST_ADMIN_DATABASE_URL, nunca cae en TEST_DATABASE_URL).
        admin_base = resolve_role_url(settings.test_admin_database_url, settings.test_database_url, label="TEST_ADMIN_DATABASE_URL")
        with psycopg.connect(make_conninfo(admin_base, dbname="postgres"), autocommit=True,
                             connect_timeout=settings.db_connect_timeout) as admin:
            if admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target,)).fetchone():
                print(f"Base de pruebas existente: {target}")
            else:
                try:
                    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
                    print(f"Base de pruebas creada: {target}")
                except psycopg.errors.DuplicateDatabase:
                    print(f"Base de pruebas existente: {target}")
        # PG54-04: igual, para MIGRATOR_TEST_DATABASE_URL. Siempre se concede CREATE+CONNECT al rol
        # resultante (en modo legacy sin override coincide con el propio rol aplicativo: no hace daño
        # concedérselo a sí mismo; en modo hardened o con override es indispensable).
        migrator_test_url = resolve_role_url(settings.migrator_test_database_url, settings.test_database_url, label="MIGRATOR_TEST_DATABASE_URL")
        # Quien creó "target" (admin_base) es su propietario: puede conceder CREATE sin ser superusuario.
        # Sin esto, vinto_migrator no podría crear los esquemas en una base nueva (CONNECT ya lo da PUBLIC
        # por defecto en una base nueva, heredado de template1; CREATE no, y es lo que de verdad falta).
        migrator_role = conninfo_to_dict(migrator_test_url).get("user")
        with psycopg.connect(make_conninfo(admin_base, dbname=target), autocommit=True,
                             connect_timeout=settings.db_connect_timeout) as owner:
            owner.execute(sql.SQL("GRANT CREATE, CONNECT ON DATABASE {} TO {}").format(
                sql.Identifier(target), sql.Identifier(migrator_role)))
        with connect_test_database(migrator_test_url, autocommit=True, connect_timeout=settings.db_connect_timeout,
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
