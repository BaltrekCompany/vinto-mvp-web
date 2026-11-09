"""Inspección read-only de autorizaciones operativas para RG-MP3-01.

Se ejecuta DESPUÉS de importar catálogo y ANTES de habilitar el nuevo
frontend. No concede, revoca ni escribe; no imprime secretos ni IDs.
El resultado positivo solo acredita la concesión efectiva según el motor;
aun así hace falta QA funcional del operador.
"""

import json

from app.auth.permissions import PRODUCTION_CAPTURE, permissions_for_profiles
from app.authz.engine import authorize, ALLOWED
from app.authz.policies import Operation
from app.auth.service import AuthenticatedUser
from import_reference import open_connection

MACHINE = "MP3"
FORM = "VINTO-MP3-01"


def report(connection):
    rows = connection.execute(
        """SELECT u.id, c.username
           FROM vinto_master."user" u
           JOIN vinto_auth.credential c ON c.user_id=u.id
           JOIN vinto_master.user_sector us ON us.user_id=u.id
           JOIN vinto_master.sector s ON s.id=us.sector_id AND s.code='BOBINAS'
           WHERE u.active ORDER BY c.username""").fetchall()

    out = {"eligible": [], "needs_grant": [], "not_authorized": [], "machine": MACHINE, "form": FORM}
    from app.auth.permissions import permissions_for_profiles
    for user_id, username in rows:
        # Motor vuelve a resolver el perfil, sector, máquina, versión y concesión
        # desde la BD; estos placeholders NO otorgan ningún permiso.
        user = AuthenticatedUser(user_id, username, username, tuple(), frozenset(), False)
        decision = authorize(connection, user, Operation.PRODUCTION_CAPTURE, MACHINE, FORM, lock=False)
        if decision.allowed:
            out["eligible"].append(username)
        elif decision.reason == "GRANT_MISSING":
            out["needs_grant"].append(username)
        else:
            out["not_authorized"].append({"username": username, "reason": decision.reason})

    out["counts"] = {k: len(out[k]) for k in ("eligible", "needs_grant", "not_authorized")}
    return out


def main():
    with open_connection("dev") as connection:
        connection.read_only = True
        results = report(connection)
    print("MP3_RG01_OPERATOR_READINESS=" + json.dumps(results, sort_keys=True, ensure_ascii=False))
    if not results["eligible"]:
        print("MP3_RG01_OPERATOR_GATE=NEEDS_EXPLICIT_GRANTS")
        return 2
    print("MP3_RG01_OPERATOR_GATE=PASS_WITH_ELIGIBLE_OPERATORS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
