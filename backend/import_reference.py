"""CLI del importador de datos de referencia. Solo orquesta; la lógica vive en app/seed.

  python import_reference.py --target test            dry-run contra TEST_DATABASE_URL (no escribe)
  python import_reference.py --target test --apply    importa en vinto_test
  python import_reference.py --target dev             dry-run contra DATABASE_URL (no escribe)
  python import_reference.py --target dev --apply     importa en la base de desarrollo

--target es obligatorio: nunca se elige una base de forma implícita.
"""

import argparse
import sys
from pathlib import Path

import psycopg

from app.config import settings
from app.db_guard import UnsafeDatabaseError, connect_test_database
from app.seed import reference
from app.seed.bundle import BUNDLE_DIR, BundleError, load_bundle

CONNECTION_OPTIONS = "-c lock_timeout=30000 -c statement_timeout=120000"


def open_connection(target: str):
    kwargs = {"autocommit": True, "connect_timeout": settings.db_connect_timeout, "options": CONNECTION_OPTIONS}
    if target == "test":
        return connect_test_database(**kwargs)  # verifica current_database() antes de devolverla
    if settings.database_url is None or not settings.database_url.get_secret_value():
        raise UnsafeDatabaseError("DATABASE_URL no está configurada")
    return psycopg.connect(settings.database_url.get_secret_value(), **kwargs)


def print_counts(counts: dict) -> None:
    for entity, numbers in counts.items():
        print(f"  {entity:<22} crear={numbers['create']:<4} ya_presentes={numbers['present']}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target", choices=("test", "dev"), required=True, help="Base de destino (obligatorio)")
    parser.add_argument("--apply", action="store_true", help="Escribir. Sin esta opción es un dry-run que no persiste nada")
    parser.add_argument("--bundle", type=Path, default=BUNDLE_DIR, help="Directorio del bundle (por defecto backend/seed_data)")
    args = parser.parse_args(argv)

    try:
        bundle = load_bundle(args.bundle)  # valida todo ANTES de abrir cualquier conexión
    except BundleError as error:
        print(f"Bundle rechazado: {error}")
        return 1
    print(f"Bundle válido; source_checksum={bundle.source_checksum}")

    try:
        with open_connection(args.target) as connection:
            database = connection.execute("SELECT current_database()").fetchone()[0]
            print(f"Base de destino: {database} (target={args.target}, modo={'apply' if args.apply else 'dry-run'})")
            if connection.execute("SELECT to_regclass('vinto_audit.import_batch')").fetchone()[0] is None:
                print("La base no tiene el esquema 0001; ejecutar migrate.py antes de importar.")
                return 1
            result = reference.apply(connection, bundle) if args.apply else reference.dry_run(connection, bundle)
    except (BundleError, UnsafeDatabaseError) as error:
        print(f"Importación detenida: {error}")
        return 1
    except reference.ReferenceConflictError as error:
        print(f"Importación detenida por conflicto/drift; no se escribió nada ni se reparó: {error}")
        return 1
    except psycopg.Error as error:
        print(f"Importación fallida: {type(error).__name__}; SQLSTATE={error.sqlstate or 'n/a'}; transacción revertida")
        return 1

    if result.mode == "noop":
        print(f"NO-OP: bundle ya importado (batch completed {result.batch_id}) y la base coincide con él. 0 escrituras.")
    elif result.mode == "dry-run":
        print("Plan (dry-run, 0 filas escritas):")
        print_counts(result.counts)
        if result.state == "conflict":
            print(f"CONFLICT / DRIFT ({len(result.conflicts)}): un --apply se detendría sin escribir.")
            for conflict in result.conflicts:
                print(f"  {conflict.key}: {conflict.detail}")
            return 1
        if result.state == "consistent":
            suffix = f" (batch completed {result.batch_id})" if result.batch_id else ""
            print(f"CONSISTENT / NO CHANGES: la base coincide con el bundle{suffix}. 0 escrituras.")
        else:
            print(f"Pendiente: un --apply crearía {result.pending_creates} fila(s) de maestros. Sin conflictos.")
    else:
        print(f"Importación completada; batch {result.batch_id}")
        print_counts(result.counts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
