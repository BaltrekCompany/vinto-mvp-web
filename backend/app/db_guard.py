"""Protección de la base de pruebas: toda suite que muta datos o esquema pasa por aquí."""

import psycopg

from app.config import settings

TEST_DATABASE_SUFFIX = "_test"


class UnsafeDatabaseError(Exception):
    """La conexión no apunta a una base de pruebas; el mensaje nunca incluye credenciales."""


def is_test_database_name(name: str) -> bool:
    return len(name) > len(TEST_DATABASE_SUFFIX) and name.endswith(TEST_DATABASE_SUFFIX)


def assert_test_database(connection) -> str:
    """Pregunta a PostgreSQL por el nombre real; no confía en la cadena de conexión."""
    name = connection.execute("SELECT current_database()").fetchone()[0]
    if not is_test_database_name(name):
        raise UnsafeDatabaseError(
            f"Abortado: la base conectada es '{name}' y no termina en '{TEST_DATABASE_SUFFIX}'. "
            "No se ejecutó DDL ni fixtures. Revisar TEST_DATABASE_URL."
        )
    return name


def connect_test_database(url: str | None = None, **kwargs):
    """Abre TEST_DATABASE_URL (o `url`) y verifica current_database() antes de devolverla."""
    if url is None:
        if settings.test_database_url is None or not settings.test_database_url.get_secret_value():
            raise UnsafeDatabaseError("TEST_DATABASE_URL no está configurada; no se usa DATABASE_URL como reemplazo.")
        url = settings.test_database_url.get_secret_value()
    connection = psycopg.connect(url, **kwargs)
    try:
        assert_test_database(connection)
        if not connection.autocommit:
            connection.rollback()
    except BaseException:
        connection.close()
        raise
    return connection
