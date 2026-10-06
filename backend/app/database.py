"""Comprobación de PostgreSQL con una conexión breve por petición."""

import logging

import psycopg

from app.config import settings

logger = logging.getLogger("uvicorn.error")


UNAVAILABLE_BODY = {"status": "error", "database": "unavailable"}


class DatabaseUnavailable(Exception):
    """Error público sin detalles de conexión ni credenciales."""


def check_database() -> None:
    if settings.database_url is None or not settings.database_url.get_secret_value():
        logger.warning("DB health: DATABASE_URL no está configurada")
        raise DatabaseUnavailable("Database unavailable")

    try:
        with psycopg.connect(
            settings.database_url.get_secret_value(),
            connect_timeout=settings.db_connect_timeout,
            autocommit=True,
            options=f"-c statement_timeout={settings.db_statement_timeout_ms}",
        ) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
    except (psycopg.Error, ValueError) as error:
        # No registrar str(error), traceback ni DATABASE_URL: podrían revelar secretos.
        logger.warning("DB health: fallo de conexión o consulta (%s)", type(error).__name__)
        raise DatabaseUnavailable("Database unavailable") from None

    if result != (1,):
        logger.warning("DB health: respuesta inesperada de SELECT 1")
        raise DatabaseUnavailable("Database unavailable")

    logger.info("DB health: conexión y SELECT 1 correctos")


def open_connection():
    """Conexión breve en autocommit con DATABASE_URL, connect_timeout y statement_timeout.

    Lanza DatabaseUnavailable (sin URL, contraseña ni SQL) si falta la configuración o la conexión falla.
    El llamador debe cerrarla (ver `get_connection`).
    """
    if settings.database_url is None or not settings.database_url.get_secret_value():
        logger.warning("DB: DATABASE_URL no está configurada")
        raise DatabaseUnavailable("Database unavailable")
    try:
        return psycopg.connect(
            settings.database_url.get_secret_value(),
            connect_timeout=settings.db_connect_timeout,
            autocommit=True,
            options=f"-c statement_timeout={settings.db_statement_timeout_ms}",
        )
    except (psycopg.Error, ValueError) as error:
        logger.warning("DB: fallo de conexión (%s)", type(error).__name__)  # nunca str(error): podría incluir la URL
        raise DatabaseUnavailable("Database unavailable") from None


def get_connection():
    """Dependencia FastAPI: una conexión por petición, siempre cerrada. Los endpoints sync corren en el thread pool."""
    connection = open_connection()
    try:
        yield connection
    finally:
        connection.close()
