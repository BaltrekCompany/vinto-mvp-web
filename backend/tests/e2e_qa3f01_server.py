"""QA-3F-01 · servidor de PRUEBA aislado para la integración E2E de los TRES frentes (Bobinas, Rebobinado, Conversión) y Calidad en UNA sola instancia
y base de datos (herramienta de QA, no se importa desde la aplicación). Derivado de e2e_b0_server.py (Bobinas/Calidad con la política REAL) y de
e2e_m6a_server.py (fixtures de Rebobinado/Conversión); no reimplementa ninguno de los dos.

Crea una base EFÍMERA nueva (`*_test`) a partir de la plantilla migrada con el bundle de referencia (MP1/MP3, F3/P1-06/P1-19/P1-20 reales), instala
ADEMÁS los fixtures FICTICIOS ya existentes de Rebobinado (tests/m2b2_fixtures.py: máquina COPASA + VINTO-P1-10 candidato) y de Conversión
(tests/m6a_fixtures.py: máquinas GAMBINI/WALLY + VINTO-P1-16 candidato), crea usuarios FICTICIOS de prueba y sirve la API real (`app.main:app`):

    - E2E_3F=on (por defecto): habilita, SOLO en este proceso, sectors._OPERATIONAL = (BOBINAS, REBOBINADO, CONVERSION) y
      capture_service.CENTRAL_FORM_CODES = {VINTO-P1-06, VINTO-P1-10, VINTO-P1-16} ("fase habilitada" de QA-3F-01, sección 5).
    - E2E_3F=off: sirve la configuración REAL sin ningún parche (solo BOBINAS operativo, política solo VINTO-P1-06); los sectores Rebobinado y
      Conversión quedan CONCEDIDOS a los usuarios de prueba pero NO operativos ("fase de política cerrada", sección 5.E).

La configuración real del producto (app/sectors.py, app/capture_service.py) NO se modifica: ambas ramas se verifican contra sus valores reales
ANTES de aplicar cualquier parche, igual que e2e_b0_server.py / e2e_m6a_server.py. Calidad (P1-19/P1-20) no depende de sectors._OPERATIONAL ni de
CENTRAL_FORM_CODES: su propia política (app/quality/capture_service.py, INT-01A) no se toca en ningún caso. Al terminar se eliminan las bases creadas.

SALVAGUARDAS (cualquiera de ellas aborta antes de abrir el puerto):
    - el puerto no puede ser 8000 (backend DEV) y el origen CORS debe ser exactamente el indicado (nunca el del frontend DEV 8787);
    - el servidor solo escucha en 127.0.0.1;
    - la base usada se identifica con current_database(): debe terminar en `_test`, no puede ser `vinto`/`vinto_test`/`postgres` y debe ser la creada por este proceso;
    - TEST_DATABASE_URL debe apuntar a 127.0.0.1 y a un puerto distinto de 5432 (nunca el PostgreSQL de desarrollo);
    - DATABASE_URL del proceso se reemplaza por la de la base efímera y se vuelve a comprobar con una conexión antes de servir;
    - los sectores operativos reales y la política real de formularios centrales se verifican ANTES de decidir si se parchean o no.

Variables: E2E_PORT, E2E_ORIGIN (origen del frontend de QA), E2E_OUT (JSON con las credenciales de prueba, EFÍMERAS, fuera del repositorio),
CORS_ORIGINS (= E2E_ORIGIN), TEST_DATABASE_URL, E2E_3F (on|off, por defecto on).
"""

import json
import os
import secrets
import signal
import sys
from urllib.parse import urlparse

import uvicorn
from pydantic import SecretStr

from app import capture_service, sectors
from app.auth.service import create_user
from app.config import settings
from app.db_guard import is_test_database_name
from app.ephemeral_db import base_url, build_reference_template, connect, copy_database, database_url, drop_database
from app.seed.bundle import load_bundle

sys.path.insert(0, os.path.dirname(__file__))
from m2b2_fixtures import P110_CODE, install_p110, install_rebobinado_fixture  # noqa: E402
from m6a_fixtures import CONV_MACHINE, CONV_MACHINE_NO_FORM, P116_CODE, install_conversion_fixture, install_p116  # noqa: E402

F6 = "VINTO-P1-06"
DEV_PORTS = {8000}
DEV_ORIGINS = {"http://127.0.0.1:8787", "http://localhost:8787"}
FORBIDDEN_DATABASES = {"vinto", "vinto_test", "postgres"}
REB_MACHINE = "COPASA"
# (clave, perfil, sectores concedidos): usuarios FICTICIOS creados solo en la base efímera. Los tres frentes se conceden a todos los roles
# operativos para que la DISPONIBILIDAD real (sectors._OPERATIONAL) sea la única variable entre la fase habilitada y la fase cerrada.
GRANTS_3F = ("BOBINAS", "REBOBINADO", "CONVERSION")
USERS = (
    ("jefatura", "JEFATURA", GRANTS_3F),
    ("supervision", "SUPERVISION", GRANTS_3F),
    ("operacion", "OPERACION", GRANTS_3F),
    ("calidad", "CALIDAD", GRANTS_3F),
    ("operacion_solo_bobinas", "OPERACION", ("BOBINAS",)),  # D: la concesión por sector sigue limitando la disponibilidad incluso con los 3 frentes operativos
)


def refuse(message: str):
    print(f"E2E ABORTADO: {message}", file=sys.stderr, flush=True)
    sys.exit(2)


def main():
    port, origin, out = int(os.environ["E2E_PORT"]), os.environ["E2E_ORIGIN"], os.environ["E2E_OUT"]
    enable_3f = os.environ.get("E2E_3F", "on") == "on"
    if port in DEV_PORTS:
        refuse(f"el puerto {port} es el del backend DEV")
    if origin in DEV_ORIGINS:
        refuse("el origen del frontend de QA no puede ser el del frontend DEV")
    if settings.cors_origins != [origin]:
        refuse(f"CORS_ORIGINS debe ser exactamente [{origin!r}] y es {settings.cors_origins!r}")
    parsed = urlparse(base_url())
    if parsed.hostname != "127.0.0.1" or parsed.port in (None, 5432):
        refuse("TEST_DATABASE_URL debe apuntar a 127.0.0.1 y a un puerto distinto de 5432 (PostgreSQL exclusivo de QA-3F-01)")
    # --- la configuración REAL se verifica ANTES de decidir si se parchea: ninguna rama puede partir de un producto ya alterado ---------
    if tuple(sectors._OPERATIONAL) != ("BOBINAS",):
        refuse(f"los sectores operativos reales no son solo BOBINAS: {sectors._OPERATIONAL!r}")
    if capture_service.CENTRAL_FORM_CODES != frozenset({F6}):
        refuse(f"CENTRAL_FORM_CODES real inesperado: {sorted(capture_service.CENTRAL_FORM_CODES)!r}")
    template = database = connection = None
    try:
        template = build_reference_template("vinto_qa3f01_tpl")
        database = copy_database(template, "vinto_qa3f01")
        connection = connect(database)  # guarded: current_database() must end in _test
        identity = connection.execute("SELECT current_database()").fetchone()[0]
        if not is_test_database_name(identity) or identity in FORBIDDEN_DATABASES or identity != database:
            refuse(f"identidad de base inesperada: {identity!r}")
        bundle = load_bundle()
        articles = {}
        for machine in ("MP1", "MP3"):
            with_gram = sorted(r["article_code"] for r in bundle.article_machines if r["machine_code"] == machine)
            articles[machine] = with_gram[0]
        article_for_fixtures = [articles["MP1"]]
        install_rebobinado_fixture(connection, article_for_fixtures)  # M2-B2/M4-A: sector/máquina/turnos ficticios de Rebobinado (COPASA)
        install_p110(connection)
        install_conversion_fixture(connection, article_for_fixtures)  # M6-A: sector/máquinas/turnos ficticios de Conversión (GAMBINI/WALLY)
        install_p116(connection)
        users = {}
        for key, profile, grants in USERS:
            password = "pw-" + secrets.token_urlsafe(18)
            created = create_user(connection, username=f"qa3f01.{key}", display_name=f"{key.replace('_', ' ').title()} (prueba QA-3F-01)", profile_code=profile, password=password, sectors=grants)
            users[key] = {"username": f"qa3f01.{key}", "password": password, "user_id": str(created.user_id), "profile": profile}
        # --- habilitación de PRUEBA, SOLO en este proceso (sección 4 de QA-3F-01) --------------------------------------------------------
        if enable_3f:
            sectors._OPERATIONAL = sectors.validate_operational_sectors(GRANTS_3F)
            capture_service.CENTRAL_FORM_CODES = frozenset({F6, P110_CODE, P116_CODE})
            print(f"QA-3F-01: FASE HABILITADA sectores={sectors.operational_sector_codes()} política={sorted(capture_service.CENTRAL_FORM_CODES)}", flush=True)
        else:
            print("QA-3F-01: FASE DE POLÍTICA CERRADA (configuración real: solo BOBINAS operativo, política solo VINTO-P1-06)", flush=True)
        settings.database_url = SecretStr(database_url(database))
        with connect(database) as check:
            if check.execute("SELECT current_database()").fetchone()[0] != database:
                refuse("la conexión de verificación no apunta a la base efímera")
        with open(out, "w", encoding="utf-8") as handle:
            json.dump({
                "database": database, "template": template, "articles": articles, "users": users, "phase": "enabled" if enable_3f else "closed",
                "rebobinado_machine": REB_MACHINE, "conversion_machine": CONV_MACHINE, "conversion_machine_no_form": CONV_MACHINE_NO_FORM,
            }, handle)
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
        from app.main import app  # noqa: E402  (CORS_ORIGINS se leyó del entorno al importar)
        print(f"E2E LISTO base={database} puerto={port} origen={origin}", flush=True)
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    finally:
        if connection is not None:
            connection.close()
        for name in (database, template):
            if name:
                drop_database(name)
        print("E2E LIMPIO: bases efímeras eliminadas", flush=True)


if __name__ == "__main__":
    main()
