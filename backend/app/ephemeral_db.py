"""Bases efímeras *_test para suites que confirman datos (solo infraestructura de pruebas).

Cada base se crea en el PostgreSQL de TEST_DATABASE_URL, migrada y con el bundle de referencia (perfiles,
sector, formularios...), y se elimina al terminar. Todo pasa por `connect_test_database()`, que verifica
`current_database()`, y los nombres deben terminar en `_test`.
"""

import contextlib
import io
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app.config import settings
from app.db_guard import UnsafeDatabaseError, connect_test_database, is_test_database_name

OPTIONS = "-c statement_timeout=60000 -c lock_timeout=30000"


def base_url() -> str:
    if settings.test_database_url is None or not settings.test_database_url.get_secret_value():
        raise UnsafeDatabaseError("TEST_DATABASE_URL no está configurada")
    return settings.test_database_url.get_secret_value()


def _admin_base_url() -> str:
    """CREATE/DROP DATABASE exige CREATEDB: TEST_ADMIN_DATABASE_URL es la identidad separada de CLOUD-01B-2
    para esto (solo DEV/QA). Si no está configurada, se mantiene el comportamiento previo (base_url())."""
    admin_url = settings.test_admin_database_url
    return admin_url.get_secret_value() if admin_url else base_url()


def database_url(name: str) -> str:
    assert is_test_database_name(name), name
    return make_conninfo(base_url(), dbname=name)


def _admin():
    return psycopg.connect(make_conninfo(_admin_base_url(), dbname="postgres"), autocommit=True, connect_timeout=5)


def create_database(name: str, template: str | None = None) -> None:
    assert is_test_database_name(name) and (template is None or is_test_database_name(template))
    statement = "CREATE DATABASE {} TEMPLATE {}" if template else "CREATE DATABASE {}"
    identifiers = [sql.Identifier(name)] + ([sql.Identifier(template)] if template else [])
    with _admin() as admin:
        admin.execute(sql.SQL(statement).format(*identifiers))


def drop_database(name: str) -> None:
    assert is_test_database_name(name)
    with _admin() as admin:
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def connect(name: str, **kwargs):
    return connect_test_database(database_url(name), autocommit=True, connect_timeout=5, options=OPTIONS, **kwargs)


def build_reference_template(prefix: str = "vinto_tpl") -> str:
    """Base migrada (0001 + 0002) con el bundle de referencia importado. Úsala solo como plantilla de copias."""
    from app.seed import reference
    from app.seed.bundle import load_bundle
    from migrate import apply as apply_migrations
    from migrate import read_migrations

    name = f"{prefix}_{uuid4().hex[:10]}_test"
    create_database(name)
    with connect(name) as connection:
        with contextlib.redirect_stdout(io.StringIO()):
            apply_migrations(connection, read_migrations())
        reference.apply(connection, load_bundle())
    return name


def copy_database(template: str, prefix: str = "vinto_copy") -> str:
    name = f"{prefix}_{uuid4().hex[:12]}_test"
    create_database(name, template=template)
    return name
