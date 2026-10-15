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


_SAFE_APP_ENVS = frozenset({"local", "test", "qa", "ci"})


def resolve_role_url(specific, fallback, *, label: str) -> str:
    """PG54-04: resuelve qué URL de conexión usar para una identidad de CLOUD-01B-2 (migrator/reference/
    test_admin), según `settings.pg_privilege_mode`.

    - "hardened": exige `specific` (p. ej. MIGRATOR_DATABASE_URL); nunca cae de vuelta a `fallback`
      (DATABASE_URL/TEST_DATABASE_URL, la cuenta privilegiada única). Si falta, se detiene — nunca un
      fallback silencioso a una cuenta con más privilegios de los necesarios.
    - "legacy" (por defecto): usa `specific` si está configurada, si no usa `fallback` — comportamiento
      idéntico al de antes de CLOUD-01B-2 cuando `specific` nunca se configura.

    `specific`/`fallback` son `SecretStr | None`. Nunca se registra ni se incluye en el mensaje de error
    el valor de ninguna URL.
    """
    if settings.pg_privilege_mode == "hardened":
        if specific is None or not specific.get_secret_value():
            raise UnsafeDatabaseError(
                f"Modo hardened: {label} es obligatoria para esta operación; no hay reemplazo automático "
                "por una cuenta más privilegiada."
            )
        return specific.get_secret_value()
    url = specific or fallback
    if url is None or not url.get_secret_value():
        raise UnsafeDatabaseError(f"Ni {label} ni la URL heredada están configuradas")
    return url.get_secret_value()


def assert_test_admin_allowed() -> None:
    """PG54-04: en modo hardened, las operaciones de aprovisionamiento de bases *_test efímeras
    (CREATEDB: app/ephemeral_db.py, backend/prepare_test_db.py) se niegan fuera de un APP_ENV reconocido
    como no operativo. Un entorno operativo nunca debe poder crear/destruir bases a voluntad, sin
    importar si TEST_ADMIN_DATABASE_URL está configurada."""
    if settings.pg_privilege_mode == "hardened" and settings.app_env not in _SAFE_APP_ENVS:
        raise UnsafeDatabaseError(
            f"Modo hardened: APP_ENV={settings.app_env!r} no es un entorno de prueba reconocido "
            f"({sorted(_SAFE_APP_ENVS)}); el aprovisionamiento de bases *_test efímeras no está permitido aquí."
        )


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
