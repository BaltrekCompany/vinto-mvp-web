"""Informe de SOLO LECTURA para activar el motor de autorización efectiva (MF-13-01D.1): quién quedaría bloqueado y qué privilegios directos tiene el rol.

  python authz_readiness.py [--target test]   (imprime JSON; no escribe, no concede, no revoca)

Usa la conexión de referencia ya existente (import_reference.open_connection). No imprime URLs, contraseñas ni valores de entorno.
"""

import argparse
import json
import sys

from app.authz.readiness import build_report
from import_reference import open_connection


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Informe de preparación del motor de autorización (solo lectura)")
    parser.add_argument("--target", choices=("test", "reference"), default="reference")
    args = parser.parse_args(argv)
    with open_connection(args.target) as connection:
        connection.read_only = True
        json.dump(build_report(connection), sys.stdout, ensure_ascii=False, indent=2, default=str)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
