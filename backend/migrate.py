"""Ordered SQL migrations over Psycopg; SQL files are the schema source of truth."""

import argparse
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg

from app.config import settings

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
LOCK_KEY = 867420031


class MigrationError(Exception):
    """Safe diagnostic without connection strings."""


@dataclass(frozen=True)
class Migration:
    version: int
    filename: str
    checksum: str
    sql: str


def read_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    migrations = []
    for path in sorted(directory.glob("*.sql")):
        match = re.fullmatch(r"([0-9]{4})_[a-z0-9_]+\.sql", path.name)
        if not match:
            raise MigrationError(f"Nombre de migración inválido: {path.name}")
        # Git may use CRLF on Windows and LF elsewhere; checksum logical UTF-8 SQL.
        sql = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        migrations.append(Migration(int(match[1]), path.name, hashlib.sha256(sql.encode("utf-8")).hexdigest(), sql))
    if not migrations:
        raise MigrationError("No se encontraron migraciones")
    if [item.version for item in migrations] != list(range(1, len(migrations) + 1)):
        raise MigrationError("Las versiones deben ser consecutivas desde 0001 y no repetirse")
    return migrations


def applied_migrations(connection) -> list[tuple]:
    if connection.execute("SELECT to_regclass('vinto_meta.schema_migration')").fetchone()[0] is None:
        return []
    return connection.execute(
        "SELECT version, filename, checksum FROM vinto_meta.schema_migration ORDER BY version"
    ).fetchall()


def validate_history(migrations: list[Migration], applied: list[tuple]) -> None:
    if [row[0] for row in applied] != list(range(1, len(applied) + 1)):
        raise MigrationError("El historial de la base no es consecutivo")
    for version, filename, checksum in applied:
        if version > len(migrations):
            raise MigrationError("La base tiene migraciones ausentes de este checkout")
        local = migrations[version - 1]
        if filename != local.filename or checksum != local.checksum:
            raise MigrationError(f"Migración aplicada modificada: {filename}; crear una nueva versión")


def apply(connection, migrations: list[Migration]) -> None:
    locked = connection.execute("SELECT pg_try_advisory_lock(%s)", (LOCK_KEY,)).fetchone()[0]
    if not locked:
        raise MigrationError("Otra ejecución está migrando esta base; reintentar cuando termine")
    try:
        applied = applied_migrations(connection)
        validate_history(migrations, applied)
        if len(applied) == len(migrations):
            print("Sin migraciones pendientes; checksum verificado")
            return
        with connection.transaction():
            connection.execute("CREATE SCHEMA IF NOT EXISTS vinto_meta")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS vinto_meta.schema_migration (
                    version integer PRIMARY KEY CHECK (version > 0),
                    filename text NOT NULL UNIQUE,
                    checksum text NOT NULL CHECK (checksum ~ '^[a-f0-9]{64}$'),
                    applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
                )
            """)
        for migration in migrations[len(applied):]:
            with connection.transaction():
                connection.execute(migration.sql, prepare=False)
                connection.execute(
                    "INSERT INTO vinto_meta.schema_migration (version,filename,checksum) VALUES (%s,%s,%s)",
                    (migration.version, migration.filename, migration.checksum),
                )
            print(f"Aplicada: {migration.filename}")
    finally:
        connection.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--status", action="store_true", help="Mostrar estado sin modificar la base")
    modes.add_argument("--check", action="store_true", help="Fallar si hay pendientes o checksums modificados")
    args = parser.parse_args()
    try:
        migrations = read_migrations()
        if settings.database_url is None or not settings.database_url.get_secret_value():
            raise MigrationError("DATABASE_URL no configurada")
        with psycopg.connect(
            settings.database_url.get_secret_value(),
            connect_timeout=settings.db_connect_timeout,
            autocommit=True,
            options="-c lock_timeout=5000 -c statement_timeout=60000",
        ) as connection:
            if args.status or args.check:
                applied = applied_migrations(connection)
                validate_history(migrations, applied)
                for migration in migrations:
                    status = "aplicada" if migration.version <= len(applied) else "pendiente"
                    print(f"{migration.filename}: {status}")
                return int(args.check and len(applied) != len(migrations))
            apply(connection, migrations)
        return 0
    except MigrationError as error:
        print(f"Migración detenida: {error}")
    except psycopg.Error as error:
        print(f"Migración fallida: {type(error).__name__}; SQLSTATE={error.sqlstate or 'n/a'}; transacción revertida")
    except (OSError, UnicodeError, ValueError) as error:
        print(f"Migración detenida: {type(error).__name__}; revisar archivos y configuración")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
