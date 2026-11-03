"""MM-13-QA · servidor de PRUEBA aislado para el E2E de navegador de la funcionalidad multimáquina (herramienta de QA, no se importa desde la aplicación).
Derivado de e2e_m6a_server.py (mismo patrón y mismas salvaguardas).

Crea una base EFÍMERA `*_test` desde la plantilla migrada, usuarios de prueba y sirve la API real (`app.main:app`). La compuerta WORK_ORDERS_MULTI_MACHINE_ENABLED se enciende
(E2E_3F=on) o se deja apagada (E2E_3F=off) SOLO en este proceso. Con la compuerta encendida el operador recibe concesión máquina-formulario P1-03 en MP1 y MP3 (requisito de PR5);
`operacion_sin_concesion` no recibe ninguna. Ningún modo AUTHZ se modifica. Al terminar se eliminan las bases creadas.

SALVAGUARDAS: el puerto no puede ser 8000 y el origen CORS debe ser exactamente el indicado; la base se identifica con current_database() (termina en `_test`, no es `vinto`).
Variables: E2E_PORT, E2E_ORIGIN, E2E_OUT (JSON con credenciales EFÍMERAS), E2E_3F (on|off), CORS_ORIGINS.
"""

import json
import os
import secrets
import signal
import sys

import uvicorn
from pydantic import SecretStr

from app.auth.machine_form_grants import grant_machine_form
from app.auth.service import create_user
from app.config import settings
from app.db_guard import is_test_database_name
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database
from app.seed.bundle import load_bundle

P103 = "VINTO-P1-03"


def refuse(message: str):
    print(f"E2E ABORTADO: {message}", file=sys.stderr, flush=True)
    sys.exit(2)


def main():
    port, origin, out, gate_on = int(os.environ["E2E_PORT"]), os.environ["E2E_ORIGIN"], os.environ["E2E_OUT"], os.environ.get("E2E_3F", "off") == "on"
    if port == 8000:
        refuse("el puerto 8000 es el del backend DEV")
    if settings.cors_origins != [origin]:
        refuse(f"CORS_ORIGINS debe ser exactamente [{origin!r}] y es {settings.cors_origins!r}")
    template = database = connection = None
    try:
        template = build_reference_template("vinto_mmqa_tpl")
        database = copy_database(template, "vinto_mmqa")
        connection = connect(database)
        identity = connection.execute("SELECT current_database()").fetchone()[0]
        if not is_test_database_name(identity) or identity == "vinto" or identity != database:
            refuse(f"identidad de base inesperada: {identity!r}")
        bundle = load_bundle()
        codes = lambda machine: sorted(r["article_code"] for r in bundle.article_machines if r["machine_code"] == machine)  # noqa: E731
        versions = {a["code"]: a["version"] for a in bundle.articles}
        mp1 = [c for c in codes("MP1") if versions[c]["grammage_g_m2"] is not None]
        mp3_only = [c for c in codes("MP3") if c not in codes("MP1")]
        users = {}
        for name, profile in (("jefatura", "JEFATURA"), ("supervision", "SUPERVISION"), ("operacion", "OPERACION"), ("operacion_sin_concesion", "OPERACION"), ("calidad", "CALIDAD")):
            password = "pw-" + secrets.token_urlsafe(18)
            created = create_user(connection, username=f"e2e.{name}", display_name=f"{name.replace('_', ' ').title()} (prueba E2E)", profile_code=profile, password=password, sectors=("BOBINAS",))
            users[name] = {"username": f"e2e.{name}", "password": password, "user_id": str(created.user_id)}
        admin = create_user(connection, username="e2e.admin", display_name="Admin (prueba E2E)", profile_code="DATA_BALTREK", password="pw-" + secrets.token_urlsafe(18), sectors=("BOBINAS",)).user_id
        connection.execute("SELECT set_config('vinto.actor_id', %s, false)", (str(admin),))
        for machine in ("MP1", "MP3"):  # PR5: con la compuerta encendida Operación solo ve máquinas con concesión activa; también se concede con la apagada (no cambia nada allí)
            grant_machine_form(connection, user_id=users["operacion"]["user_id"], machine_code=machine, form_code=P103, actor_id=admin)
        settings.database_url = SecretStr(database_url(database))
        settings.work_orders_multi_machine_enabled = gate_on  # solo este proceso; el cliente no puede cambiarlo
        print(f"E2E: compuerta multimáquina={'ENCENDIDA' if gate_on else 'APAGADA'} (solo este proceso)", flush=True)
        with connect(database) as check:
            if check.execute("SELECT current_database()").fetchone()[0] != database:
                refuse("la conexión de verificación no apunta a la base efímera")
        with open(out, "w", encoding="utf-8") as handle:
            json.dump({"database": database, "template": template, "users": users, "gate": "on" if gate_on else "off", "articles": {"mp1": mp1[:3], "mp3": mp3_only[:1]}}, handle)
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        from app.main import app  # noqa: E402
        print(f"E2E LISTO base={database} puerto={port} origen={origin}", flush=True)
        uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
    finally:
        if connection is not None:
            connection.close()
        for name in (database, template):
            if name:
                drop_database(name)
        print("E2E LIMPIO: bases efímeras eliminadas", flush=True)


if __name__ == "__main__":
    main()
