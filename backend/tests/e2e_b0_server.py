"""E2E-B0 · servidor de PRUEBA aislado para la validación integral de Bobinas MP1/MP3 y Calidad (herramienta de QA, no se importa desde la aplicación).

Crea una base EFÍMERA nueva (`*_test`) en el PostgreSQL de TEST_DATABASE_URL a partir de la plantilla migrada con el bundle de referencia (datos CANDIDATOS, no homologados),
crea usuarios FICTICIOS de prueba y sirve la API real (`app.main:app`) con la configuración REAL del producto: NO se modifica `sectors._OPERATIONAL` (solo BOBINAS) ni
`capture_service.CENTRAL_FORM_CODES` (solo VINTO-P1-06). F3 y Calidad usan sus rutas existentes (`/api/bobbins`, `/api/quality/...`). No se instala ningún fixture ni formulario sintético.
Al terminar se eliminan las bases creadas.

SALVAGUARDAS (cualquiera de ellas aborta antes de abrir el puerto):
    - el puerto no puede ser 8000 (backend DEV) y el origen CORS debe ser exactamente el indicado (nunca el del frontend DEV 8787);
    - el servidor solo escucha en 127.0.0.1;
    - la base usada se identifica con current_database(): debe terminar en `_test`, no puede ser `vinto` ni `vinto_test` y debe ser la creada por este proceso;
    - TEST_DATABASE_URL debe apuntar a 127.0.0.1 y a un puerto distinto de 5432 (nunca el PostgreSQL de desarrollo);
    - DATABASE_URL del proceso se reemplaza por la de la base efímera y se vuelve a comprobar con una conexión antes de servir;
    - los sectores operativos y la política de formularios centrales se verifican contra la configuración real antes de servir.

Variables: E2E_PORT, E2E_ORIGIN (origen del frontend de QA), E2E_OUT (JSON con las credenciales de prueba, EFÍMERAS, fuera del repositorio), CORS_ORIGINS (= E2E_ORIGIN), TEST_DATABASE_URL.
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

DEV_PORTS = {8000}
DEV_ORIGINS = {"http://127.0.0.1:8787", "http://localhost:8787"}
FORBIDDEN_DATABASES = {"vinto", "vinto_test", "postgres"}
# (clave, perfil, sectores concedidos): usuarios FICTICIOS creados solo en la base efímera
USERS = (
    ("jefatura", "JEFATURA", ("BOBINAS",)),
    ("supervision", "SUPERVISION", ("BOBINAS",)),
    ("operacion", "OPERACION", ("BOBINAS",)),
    ("calidad", "CALIDAD", ("BOBINAS",)),
    ("calidad_sin_sector", "CALIDAD", ()),  # perfil CALIDAD SIN concesión de sector
    ("operacion_sin_sector", "OPERACION", ()),  # perfil OPERACION SIN concesión de sector
    ("data_baltrek", "DATA_BALTREK", ()),  # administración técnica, sin permisos funcionales de planta
)


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
    parsed = urlparse(base_url())
    if parsed.hostname != "127.0.0.1" or parsed.port in (None, 5432):
        refuse("TEST_DATABASE_URL debe apuntar a 127.0.0.1 y a un puerto distinto de 5432 (PostgreSQL exclusivo de E2E-B0)")
    if tuple(sectors._OPERATIONAL) != ("BOBINAS",):
        refuse(f"los sectores operativos reales no son solo BOBINAS: {sectors._OPERATIONAL!r}")
    if capture_service.CENTRAL_FORM_CODES != frozenset({"VINTO-P1-06"}):
        refuse(f"CENTRAL_FORM_CODES real inesperado: {sorted(capture_service.CENTRAL_FORM_CODES)!r}")
    template = database = connection = None
    try:
        template = build_reference_template("vinto_e2eb0_tpl")
        database = copy_database(template, "vinto_e2eb0")
        connection = connect(database)  # guarded: current_database() must end in _test
        identity = connection.execute("SELECT current_database()").fetchone()[0]
        if not is_test_database_name(identity) or identity in FORBIDDEN_DATABASES or identity != database:
            refuse(f"identidad de base inesperada: {identity!r}")
        bundle = load_bundle()
        articles = {}
        for machine in ("MP1", "MP3"):
            with_gram = sorted(r["article_code"] for r in bundle.article_machines if r["machine_code"] == machine)
            articles[machine] = with_gram[0]
        users = {}
        for key, profile, grants in USERS:
            password = "pw-" + secrets.token_urlsafe(18)
            created = create_user(connection, username=f"e2eb0.{key}", display_name=f"{key.replace('_', ' ').title()} (prueba E2E-B0)", profile_code=profile, password=password, sectors=grants)
            users[key] = {"username": f"e2eb0.{key}", "password": password, "user_id": str(created.user_id), "profile": profile}
        # --- la API sirve EXACTAMENTE esta base; la configuración real del producto NO se toca -------------------------------------------
        settings.database_url = SecretStr(database_url(database))
        with connect(database) as check:
            if check.execute("SELECT current_database()").fetchone()[0] != database:
                refuse("la conexión de verificación no apunta a la base efímera")
        with open(out, "w", encoding="utf-8") as handle:
            json.dump({"database": database, "template": template, "articles": articles, "users": users}, handle)
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
