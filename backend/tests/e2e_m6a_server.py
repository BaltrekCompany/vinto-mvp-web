"""M6-A · servidor de PRUEBA aislado para los recorridos E2E de Conversión (VINTO-P1-16 candidato) y de regresión de Rebobinado (herramienta de QA, no se importa desde la aplicación).
Derivado de e2e_p110_server.py (M2-B2 / M4-A): mismo patrón y mismas salvaguardas; añade el contexto FICTICIO de Conversión (tests/m6a_fixtures.py).

Crea una base EFÍMERA nueva (`*_test`) a partir de la plantilla migrada, instala los fixtures de prueba (Rebobinado ficticio + definición candidata de P1-10, ver
tests/m2b2_fixtures.py), crea usuarios de prueba y sirve la API real (`app.main:app`) con la configuración de prueba habilitada SOLO en este proceso:
    - E2E_REBOBINADO=on (por defecto): sectors._OPERATIONAL incluye REBOBINADO y la política incluye VINTO-P1-10, el formulario SINTÉTICO agrupado de M3-A y la ficha CANDIDATA P1-29 de M3-B
    - E2E_CONVERSION=on (por defecto): sectors._OPERATIONAL incluye CONVERSION y la política incluye la ficha CANDIDATA VINTO-P1-16 (M6-A)
    - E2E_P112=on (por defecto "off"; requiere E2E_CONVERSION=on): la política incluye además la ficha CANDIDATA VINTO-P1-12 (M6-B) y un formulario vinculado SIN publicar
    - con ambos en "off" se sirve la configuración REAL (solo BOBINAS operativo, política solo F6) con los sectores CONCEDIDOS pero no operativos
La configuración real del producto (app/sectors.py, capture_service.py) no se modifica. Al terminar se eliminan las bases creadas.

SALVAGUARDAS (cualquiera de ellas aborta antes de abrir el puerto):
    - el puerto no puede ser 8000 (backend DEV) y el origen CORS debe ser exactamente el indicado (nunca el del frontend DEV 8787);
    - la base usada se identifica con current_database(): debe terminar en `_test` y no puede ser `vinto`; la creación pasa por connect_test_database;
    - DATABASE_URL del proceso se reemplaza por la de la base efímera y se vuelve a comprobar con una conexión antes de servir.

Variables: E2E_PORT, E2E_ORIGIN (origen del frontend de QA), E2E_OUT (archivo JSON donde se escriben las credenciales de prueba, EFÍMERAS), CORS_ORIGINS (debe coincidir con E2E_ORIGIN).
"""

import json
import os
import secrets
import signal
import sys

import uvicorn
from pydantic import SecretStr

from app import capture_service, sectors
from app.auth.service import create_user
from app.config import settings
from app.db_guard import is_test_database_name
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database
from app.seed.bundle import load_bundle

sys.path.insert(0, os.path.dirname(__file__))
from m2b2_fixtures import P110_CODE, install_p110, install_rebobinado_fixture  # noqa: E402
from m3a_fixtures import GROUPED_CODE, install_grouped_form  # noqa: E402
from m3b_fixtures import P129_CODE, install_p129, install_tubetera_machine  # noqa: E402
from m6a_fixtures import CONV_MACHINE, CONV_MACHINE_NO_FORM, P116_CODE, install_conversion_fixture, install_p116  # noqa: E402
from m6b_fixtures import P112_CODE, P112_DRAFT_CODE, install_p112, install_p112_draft  # noqa: E402

F6 = "VINTO-P1-06"
DEV_PORTS = {8000}
DEV_ORIGINS = {"http://127.0.0.1:8787", "http://localhost:8787"}


def refuse(message: str):
    print(f"E2E ABORTADO: {message}", file=sys.stderr, flush=True)
    sys.exit(2)


def main():
    port, origin, out = int(os.environ["E2E_PORT"]), os.environ["E2E_ORIGIN"], os.environ["E2E_OUT"]
    if port in DEV_PORTS:
        refuse(f"el puerto {port} es el del backend DEV")
    if origin in DEV_ORIGINS:
        refuse("el origen del frontend de QA no puede ser el del frontend DEV")
    if settings.cors_origins != [origin]:
        refuse(f"CORS_ORIGINS debe ser exactamente [{origin!r}] y es {settings.cors_origins!r}")
    template = database = connection = None
    try:
        template = build_reference_template("vinto_m6ae2e_tpl")
        database = copy_database(template, "vinto_m6ae2e")
        connection = connect(database)  # guarded: current_database() must end in _test
        identity = connection.execute("SELECT current_database()").fetchone()[0]
        if not is_test_database_name(identity) or identity == "vinto" or identity != database:
            refuse(f"identidad de base inesperada: {identity!r}")
        article = sorted(r["article_code"] for r in load_bundle().article_machines if r["machine_code"] == "MP1")[0]
        install_rebobinado_fixture(connection, [article])
        install_p110(connection)
        install_grouped_form(connection, machine_codes=("COPASA",))  # M3-A: formulario SINTÉTICO con grupos repetibles (solo esta base efímera)
        install_tubetera_machine(connection, [article])  # M3-B: máquina TUBETERA ficticia + definición CANDIDATA de P1-29 (solo esta base efímera)
        install_p129(connection)
        install_conversion_fixture(connection, [article])  # M6-A: sector CONVERSION ficticio (GAMBINI con P1-16 candidato, WALLY sin formulario, 3 turnos de hipótesis; solo esta base efímera)
        install_p116(connection)
        install_p112(connection)  # M6-B: ficha CANDIDATA P1-12 (un pallet por captura) vinculada a GAMBINI; solo se ofrece si E2E_P112=on
        install_p112_draft(connection)  # M6-B: formulario vinculado a GAMBINI pero SIN publicar (caso negativo)
        grants = ("BOBINAS", "REBOBINADO", "CONVERSION")
        users = {}
        for name, profile, granted in (("jefatura", "JEFATURA", grants), ("supervision", "SUPERVISION", grants), ("operacion", "OPERACION", grants), ("calidad", "CALIDAD", grants),
                                       ("operacion_solo_bobinas", "OPERACION", ("BOBINAS",)), ("operacion_solo_rebobinado", "OPERACION", ("BOBINAS", "REBOBINADO"))):
            password = "pw-" + secrets.token_urlsafe(18)
            created = create_user(connection, username=f"e2e.{name}", display_name=f"{name.replace('_', ' ').title()} (prueba E2E)", profile_code=profile, password=password, sectors=granted)
            users[name] = {"username": f"e2e.{name}", "password": password, "user_id": str(created.user_id)}
        # --- configuración de PRUEBA, solo en este proceso -------------------------------------------------------------------------------
        settings.database_url = SecretStr(database_url(database))
        operational, policy = ["BOBINAS"], {F6}
        if os.environ.get("E2E_REBOBINADO", "on") == "on":  # M4-A: con "off" Rebobinado queda concedido pero NO operativo
            operational.append("REBOBINADO")
            policy |= {P110_CODE, GROUPED_CODE, P129_CODE}
        if os.environ.get("E2E_CONVERSION", "on") == "on":  # M6-A: con "off" Conversión queda concedido pero NO operativo
            operational.append("CONVERSION")
            policy.add(P116_CODE)
            if os.environ.get("E2E_P112", "off") == "on":  # M6-B: P1-12 (y el código del borrador, que nunca se publica) entran en la política SOLO de este proceso
                policy |= {P112_CODE, P112_DRAFT_CODE}
        sectors._OPERATIONAL = sectors.validate_operational_sectors(tuple(operational))
        capture_service.CENTRAL_FORM_CODES = frozenset(policy)
        print(f"E2E: sectores operativos={sectors.operational_sector_codes()} política={sorted(capture_service.CENTRAL_FORM_CODES)}", flush=True)
        with connect(database) as check:  # el proceso sirve exactamente esta base
            if check.execute("SELECT current_database()").fetchone()[0] != database:
                refuse("la conexión de verificación no apunta a la base efímera")
        with open(out, "w", encoding="utf-8") as handle:
            json.dump({"database": database, "article_code": article, "machine_code": "COPASA", "conversion_machine": CONV_MACHINE, "conversion_machine_no_form": CONV_MACHINE_NO_FORM, "draft_form_code": P112_DRAFT_CODE, "users": users}, handle)
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        from app.main import app  # noqa: E402  (after the test configuration; CORS_ORIGINS was read from the environment at import)
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
