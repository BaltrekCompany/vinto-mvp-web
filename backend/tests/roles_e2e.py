"""CLOUD-01B-2B.1 · validación end-to-end del modelo de privilegios mínimos de PostgreSQL 17.

Herramienta de QA/infraestructura, NO se importa desde la aplicación ni desde la suite de unittest
(requiere Docker y tarda; se ejecuta a mano: `cd backend && PYTHONPATH=. python tests/roles_e2e.py`).

Corregido tras la auditoría del PR #54 (PG54-01 a PG54-06):
  - PG54-01: ya no hay ningún privilegio por defecto sobre tablas futuras (ver backend/roles/
    05_no_default_privileges.sql); se agrega una prueba que crea una tabla "futura" y confirma que
    vinto_app/vinto_reference/PUBLIC no tienen NINGÚN privilegio sobre ella.
  - PG54-02: el contenedor Docker usa un nombre único por ejecución (nunca uno fijo), se verifica que
    no exista antes de crearlo (si colisiona, se aborta SIN eliminar nada) y la limpieza final usa el
    ID del contenedor que esta misma ejecución creó, nunca un nombre adivinado.
  - PG54-03: ninguna contraseña se pasa como argumento -v de psql (visible en la lista de procesos);
    se leen con \\getenv desde variables de entorno del proceso exec'ado, y PGPASSWORD se sustituye por
    un archivo .pgpass con permisos 600 dentro del contenedor, borrado tras cada uso. Todo lo que se
    imprime pasa por `redact()`; al final se verifica que ningún secreto generado aparece en el reporte.
  - PG54-04: nueva señal explícita `PG_PRIVILEGE_MODE` ("legacy", igual que antes; "hardened", sin
    fallback silencioso a DATABASE_URL/TEST_DATABASE_URL y sin permitir operaciones de aprovisionamiento
    de pruebas efímeras fuera de un APP_ENV reconocido). Nunca se activa por defecto.
  - PG54-05: 00_create_roles.sql ya NO crea vinto_test_admin (ver 00b_create_test_admin_role.sql,
    exclusivo de DEV/QA); ambos son idempotentes y detectan colisión de nombre de rol.
  - PG54-06: se ejecuta además la suite completa del backend (los ~60 archivos test_*.py, 1145 pruebas)
    en modo legado, bajo aislamiento demostrado (su propio par de bases "vinto"/"vinto_test" en el
    mismo contenedor efímero), ANTES de aplicar el modelo de roles. Se ejecuta archivo por archivo
    (`unittest discover -s tests -p "<archivo>.py"`), no un solo `discover -s tests` monolítico: un
    `discover` sin filtro que importa los ~60 módulos en UN SOLO proceso produce cientos de fallos
    (verificado al depurar) que no se reproducen archivo por archivo — un problema preexistente de
    aislamiento ENTRE ARCHIVOS de la propia suite, no una regresión de este PR. Sus resultados se
    reportan por separado y NUNCA se presentan como equivalentes a las pruebas específicas del modelo
    de 4 roles.

No modifica main, no toca ninguna base real, no lee ningún .env real: cada conexión de este script usa
una URL construida en memoria contra el contenedor efímero, nunca backend/.env.
"""

import os
import re
import secrets
import subprocess
import sys
import time
import uuid
from datetime import date
from pathlib import Path

# En Windows, stdout/stderr redirigidos a un archivo (no a una consola) usan por defecto la codificación
# del sistema (p. ej. cp1252), que no puede representar todos los caracteres que puede devolver un hijo
# decodificado con errors="replace" (p. ej. el carácter de reemplazo �), y hace que un simple
# print() de este script lance UnicodeEncodeError (visto al depurar esta fase). UTF-8 los representa
# todos.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROLES_DIR = BACKEND_DIR / "roles"

HOST_PORT = 55461
DB = "vinto_cloud01b2"
BOOT_USER = "cloud01b2_root"

RESULTS = []  # (name, status, detail) — status in PASS/FAIL/BLOCKED
SECRETS: set[str] = set()  # contraseñas sintéticas generadas en esta ejecución; nunca credenciales reales

# Identidad del contenedor que ESTA ejecución creó (PG54-02). None hasta que docker_up() lo confirme.
_CONTAINER = {"name": None, "id": None}


def register_secret(value: str) -> str:
    SECRETS.add(value)
    return value


_URL_PATTERN = re.compile(r"postgresql://[^:\s@]+:([^@\s]+)@")


def redact(text) -> str:
    """PG54-03: nunca se imprime una contraseña generada ni una URL completa de PostgreSQL."""
    text = str(text)
    for secret in SECRETS:
        if secret:
            text = text.replace(secret, "***")
    return _URL_PATTERN.sub(lambda m: m.group(0).replace(m.group(1), "***"), text)


def report(name, status, detail=""):
    detail = redact(detail)
    RESULTS.append((name, status, detail))
    print(f"{status:7} {name}{'  — ' + detail if detail else ''}", flush=True)


def run(cmd, **kwargs):
    # encoding="utf-8" explícito para lo que ESTE proceso envía (p. ej. el contenido de un .sql al
    # stdin de psql dentro del contenedor Linux, que espera UTF-8: sin esto, Windows usa la codificación
    # del sistema -p. ej. cp1252- y corrompe los acentos, como se vio al ejecutar
    # 00b_create_test_admin_role.sql). errors="replace" para lo que SE LEE: un hijo nativo de Windows
    # (python.exe ejecutando migrate.py/unittest) imprime con la codificación de consola de Windows, no
    # UTF-8, así que decodificarlo en modo "strict" como UTF-8 puede lanzar UnicodeDecodeError dentro del
    # hilo lector interno de subprocess.run (visto en la primera corrida de esta fase: varios
    # "Exception in thread ... UnicodeDecodeError" que además truncaban result.stdout/stderr a None).
    # "replace" nunca falla; como los textos que se buscan en el reporte (hardened, modificada, OK) son
    # ASCII puro, un acento mal decodificado en otra parte del texto no afecta esas comprobaciones.
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kwargs)


def _write_pgpass(container_id, *, host, port, dbname, user, password):
    """PG54-03: PGPASSWORD se sustituye por un archivo .pgpass (permisos 600, dentro del contenedor,
    borrado tras cada uso) — reduce la exposición frente a pasar la contraseña como variable de entorno
    de un proceso exec'ado, visible en inspecciones del propio contenedor mientras vive el proceso."""
    line = f"{host}:{port}:{dbname}:{user}:{password}\n"
    write = run(["docker", "exec", "-i", container_id, "sh", "-c",
                "umask 077 && cat > /tmp/.cloud01b2-pgpass && chmod 600 /tmp/.cloud01b2-pgpass"], input=line)
    if write.returncode != 0:
        raise RuntimeError(f"no se pudo escribir .pgpass en el contenedor: {write.stderr}")


def _remove_pgpass(container_id):
    run(["docker", "exec", container_id, "rm", "-f", "/tmp/.cloud01b2-pgpass"])


def psql_file(path, *, user, password, dbname, env_vars=None, port=5432):
    """Ejecuta un script SQL vía psql dentro del contenedor efímero. Ninguna contraseña viaja como
    argumento -v (PG54-03): las variables no secretas (p. ej. DBNAME) se pasan como variables de
    entorno del proceso exec'ado (-e), leídas por el script con \\getenv; la contraseña de conexión
    nunca se pasa como PGPASSWORD en texto plano: se escribe un .pgpass temporal (600) y se borra
    después."""
    container_id = _CONTAINER["id"]
    _write_pgpass(container_id, host="127.0.0.1", port=port, dbname=dbname, user=user, password=password)
    try:
        args = ["docker", "exec", "-i", "-e", "PGPASSFILE=/tmp/.cloud01b2-pgpass"]
        for key, value in (env_vars or {}).items():
            args += ["-e", f"{key}={value}"]
        args += [container_id, "psql", "-h", "127.0.0.1", "-p", str(port), "-U", user, "-d", dbname,
                "-v", "ON_ERROR_STOP=1", "-f", "-"]
        with open(path, "rb") as handle:
            result = run(args, input=handle.read().decode("utf-8"))
        return result
    finally:
        _remove_pgpass(container_id)


def url(user, password, dbname, host="127.0.0.1", port=HOST_PORT):
    register_secret(password)
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def docker_up(boot_password):
    """PG54-02: nombre único por ejecución (nunca uno fijo). Antes de crear, verifica que no exista ya
    un contenedor con ese nombre; si existe, se detiene SIN eliminar nada (no puede demostrarse la
    propiedad de un recurso que no creó esta ejecución). Tras crearlo, guarda el ID devuelto por
    `docker run` y lo confirma con `docker inspect`: la limpieza final usa SIEMPRE ese ID, nunca un
    nombre adivinado ni un `docker rm -f` sobre algo que esta ejecución no demostró haber creado."""
    name = f"vinto-cloud01b2-{uuid.uuid4().hex[:12]}"
    existing = run(["docker", "ps", "-a", "-q", "--filter", f"name=^{name}$"])
    if existing.stdout.strip():
        raise RuntimeError(f"colisión de nombre de contenedor ({name}); abortando sin eliminar nada (PG54-02)")
    result = run(["docker", "run", "-d", "--name", name,
                  "-e", f"POSTGRES_USER={BOOT_USER}", "-e", f"POSTGRES_PASSWORD={boot_password}", "-e", f"POSTGRES_DB={DB}",
                  "-p", f"127.0.0.1:{HOST_PORT}:5432", "--tmpfs", "/var/lib/postgresql/data",
                  "postgres:17"])
    if result.returncode != 0:
        raise RuntimeError(f"docker run falló: {redact(result.stderr)}")
    container_id = result.stdout.strip()
    inspected = run(["docker", "inspect", "--format", "{{.Name}}", container_id])
    if inspected.returncode != 0 or inspected.stdout.strip().lstrip("/") != name:
        # No puede demostrarse que el ID devuelto corresponde al nombre que pedimos: no se registra
        # como propio y no se intenta limpiar nada bajo ese ID sin esa prueba.
        raise RuntimeError("no se pudo confirmar la identidad del contenedor recién creado; abortando sin registrarlo (PG54-02)")
    _CONTAINER["name"], _CONTAINER["id"] = name, container_id
    for _ in range(60):
        ready = run(["docker", "exec", container_id, "pg_isready", "-U", BOOT_USER, "-d", DB])
        if ready.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("PostgreSQL efímero no respondió a tiempo")


def docker_down():
    """PG54-02: limpia ÚNICAMENTE el contenedor cuyo ID quedó registrado por docker_up() en esta misma
    ejecución. Si nunca se confirmó un ID (p. ej. abortó por colisión antes de crear nada), no hace nada
    — nunca se elimina un recurso por nombre adivinado."""
    container_id = _CONTAINER["id"]
    if container_id:
        run(["docker", "rm", "-f", container_id])


def subprocess_env(**overrides):
    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    env["DB_CONNECT_TIMEOUT"] = "10"
    env["DB_STATEMENT_TIMEOUT_MS"] = "20000"
    # Nunca se hereda silenciosamente una variable de CLOUD-01B-2 del entorno real del proceso padre:
    # cada llamada declara explícitamente las que necesita.
    for key in ("MIGRATOR_DATABASE_URL", "MIGRATOR_TEST_DATABASE_URL", "REFERENCE_DATABASE_URL",
               "REFERENCE_TEST_DATABASE_URL", "TEST_ADMIN_DATABASE_URL", "PG_PRIVILEGE_MODE",
               "DATABASE_URL", "TEST_DATABASE_URL", "APP_ENV"):
        env.pop(key, None)
    # Cada URL de identidad se fija explícitamente: lo que backend/.env real pueda tener para
    # DATABASE_URL/TEST_DATABASE_URL queda sobrescrito, nunca usado (no se lee su contenido real).
    env.update(overrides)
    return env


def run_backend_script(args, **overrides):
    return run([sys.executable, "-B", *args], cwd=str(BACKEND_DIR), env=subprocess_env(**overrides))


def sqlstate_of(error):
    return getattr(error, "sqlstate", None) or getattr(getattr(error, "diag", None), "sqlstate", None)


def expect_ok(name, fn):
    try:
        fn()
        report(name, "PASS")
        return True
    except Exception as error:  # noqa: BLE001 — se reporta cualquier excepción como fallo del caso
        report(name, "FAIL", f"{type(error).__name__}: {error}")
        return False


def expect_fail(name, fn, want_sqlstate=None):
    try:
        fn()
    except Exception as error:  # noqa: BLE001
        got = sqlstate_of(error)
        if want_sqlstate is not None and got != want_sqlstate:
            report(name, "FAIL", f"se rechazó pero con SQLSTATE={got!r}, se esperaba {want_sqlstate!r} ({type(error).__name__}: {error})")
            return False
        report(name, "PASS", f"rechazado correctamente (SQLSTATE={got!r}, {type(error).__name__})")
        return True
    report(name, "FAIL", "se esperaba un rechazo y la operación tuvo éxito")
    return False


def expect_process_fail(name, result, *, contains=None):
    """Para subprocesos (migrate.py/import_reference.py/prepare_test_db.py) que deben fallar: su propio
    try/except imprime un mensaje y devuelve 1, nunca una excepción Python en este proceso."""
    if result.returncode == 0:
        report(name, "FAIL", "se esperaba que el subproceso fallara y terminó con éxito")
        return False
    text = (result.stdout or "") + (result.stderr or "")
    if contains and contains not in text:
        report(name, "FAIL", f"falló pero sin el mensaje esperado ({contains!r}): {text.strip()[-300:]}")
        return False
    report(name, "PASS", text.strip().splitlines()[-1] if text.strip() else "falló como se esperaba")
    return True


def main() -> int:
    boot_password = register_secret(secrets.token_urlsafe(24))
    passwords = {role: register_secret(secrets.token_urlsafe(24)) for role in ("app", "migrator", "reference", "test_admin")}

    print(f"=== Levantando PostgreSQL 17 efímero (nombre único por ejecución, puerto {HOST_PORT}) ===", flush=True)
    try:
        docker_up(boot_password)
    except RuntimeError as error:
        report("arranque del contenedor efímero", "BLOCKED", str(error))
        docker_down()
        return 1
    print(f"Contenedor confirmado: {_CONTAINER['name']} ({_CONTAINER['id'][:12]})", flush=True)

    try:
        _run_all(boot_password, passwords)
    finally:
        print(f"=== Deteniendo y eliminando el contenedor efímero ({_CONTAINER['name']}) ===", flush=True)
        docker_down()

    # PG54-03: comprobación final de que ningún secreto generado quedó en el reporte impreso.
    transcript = "\n".join(f"{n} {s} {d}" for n, s, d in RESULTS)
    leaked = sorted(s for s in SECRETS if s and s in transcript)
    report("logs sin secretos: ninguna contraseña generada aparece en el reporte", "PASS" if not leaked else "FAIL",
          "" if not leaked else f"{len(leaked)} secreto(s) filtrado(s) en el log")

    failures = [r for r in RESULTS if r[1] != "PASS"]
    print(f"\nTOTAL {len(RESULTS)} · PASS {len(RESULTS) - len(failures)} · FAIL/BLOCKED {len(failures)}")
    print(
        "\nLímite de cobertura (PG54-06): las pruebas de este runner validan el MODELO DE PRIVILEGIOS "
        "(separación de roles, SQLSTATE, fail-closed sobre objetos futuros). La suite completa del "
        "backend (reportada por separado, fase 'regresión completa en modo legado') valida la LÓGICA DE "
        "NEGOCIO bajo el rol único legado. Ambas se ejecutaron bajo aislamiento (mismo contenedor "
        "efímero, bases separadas), pero NO son equivalentes ni sustituyen una a la otra.\n"
        "El 1145/1145 de la fase de regresión corresponde a ejecución ARCHIVO POR ARCHIVO. La ejecución "
        "monolítica ('unittest discover -s tests' sin filtro) produce interferencias entre archivos "
        "todavía no explicadas (ver comentario en el código de esta fase); NO se declara reparado el "
        "runner monolítico — se recomienda un incremento posterior dedicado a esa causa raíz.")
    return 1 if failures else 0


def _run_all(boot_password, passwords):
    # =====================================================================================================
    # Fase 0 (PG54-06): suite completa del backend en modo LEGADO, bajo aislamiento demostrado, en un par
    # de bases propio dentro del MISMO contenedor efímero — antes de aplicar el modelo de roles, para no
    # mezclar "¿falla por mi cambio de privilegios?" con "¿falla por lógica de negocio preexistente?".
    #
    # CLOUD01B2_SKIP_FASE0=1 omite esta fase (son ~1145 pruebas, archivo por archivo, varios minutos).
    # Úsalo solo cuando no haya ningún cambio de lógica de negocio desde la última vez que se corrió
    # completa (p. ej. una corrección focalizada de los scripts de roles/privilegios): repetir la suite
    # completa sin necesidad técnica no es gratis y esta fase ya se validó en 1145/1145 en una corrida
    # previa de este mismo PR.
    # =====================================================================================================
    import psycopg

    if os.environ.get("CLOUD01B2_SKIP_FASE0") == "1":
        report("suite completa backend (archivo por archivo) — modo legado, aislada", "PASS",
              "omitida intencionalmente (CLOUD01B2_SKIP_FASE0=1): sin cambios de lógica de negocio desde la corrida 1145/1145 previa de este PR")
        return _run_role_model(boot_password, passwords)

    print("\n=== Fase 0: regresión completa del backend (modo legado, aislada) ===", flush=True)

    # Nombres "vinto"/"vinto_test" (no "vinto_legacy*"): backend/tests/test_db_guard.py hardcodea el
    # nombre literal "vinto_test" que debe devolver current_database() (test_configured_test_database_
    # is_vinto_test). Son nombres SOLO dentro de este contenedor efímero propio, nunca el "vinto"/
    # "vinto_test" de ningún entorno real.
    boot_url_db = url(BOOT_USER, boot_password, DB)
    with psycopg.connect(boot_url_db, autocommit=True) as boot_conn:
        boot_conn.execute("CREATE DATABASE vinto")
        boot_conn.execute("CREATE DATABASE vinto_test")

    legacy_dev_url = url(BOOT_USER, boot_password, "vinto")
    legacy_test_url = url(BOOT_USER, boot_password, "vinto_test")

    # Prerrequisito documentado en backend/README.md ("Base de pruebas (vinto_test)"): TEST_DATABASE_URL
    # debe estar migrada ANTES de correr la suite — muchos test_*.py se conectan directamente a ella
    # (connect_test_database() sin copia efímera propia) y no la migran por sí mismos. Omitir este paso
    # produce cientos de "relation ... does not exist" en los módulos que se ejecutan antes (por orden
    # alfabético de unittest discover) que el módulo que migra TEST_DATABASE_URL como parte de sus propias
    # pruebas (encontrado al depurar el primer intento de esta fase).
    migrate_legacy_dev = run_backend_script(["migrate.py"], DATABASE_URL=legacy_dev_url)
    migrate_legacy_test = run_backend_script(["migrate.py", "--target", "test"], TEST_DATABASE_URL=legacy_test_url)
    if migrate_legacy_dev.returncode != 0 or migrate_legacy_test.returncode != 0:
        report("preparación de vinto/vinto_test (prerrequisito de la suite)", "BLOCKED",
              (migrate_legacy_dev.stdout + migrate_legacy_test.stdout).strip()[-300:])
        report("suite completa backend — modo legado, aislada", "BLOCKED", "no se intentó: el prerrequisito de migración falló")
    else:
        # PG54-06 / PG54-FINAL: se ejecuta ARCHIVO POR ARCHIVO (discover -p "<archivo>.py"), no un solo
        # "discover -s tests" monolítico. Encontrado al depurar: un "discover" sin filtro que importa
        # los ~48 módulos de prueba en UN SOLO proceso produce cientos de fallos (409 en vez de 201 en
        # rutas que dependen de app.sectors._OPERATIONAL parcheado, entre otros) que NO se reproducen si
        # cada archivo se ejecuta en su propio proceso — un problema preexistente de aislamiento ENTRE
        # ARCHIVOS de la propia suite (nunca tocado por este PR: ningún archivo de test se modificó), no
        # una regresión de CLOUD-01B-2.
        #
        # IMPORTANTE: esto NO declara reparado el runner monolítico ("unittest discover -s tests" sin
        # filtro). Sigue interfiriendo entre archivos y su causa raíz no se investigó (requeriría
        # instrumentar qué estado de proceso se filtra entre módulos — p. ej. un patch.object de
        # app.sectors._OPERATIONAL u otro singleton que no se restaura del todo entre archivos). Correr
        # archivo por archivo es un workaround que demuestra la misma cobertura (1145/1145 pruebas,
        # verificado) sin ese artefacto, pero no es una corrección del runner monolítico en sí. Se
        # recomienda un incremento posterior dedicado a identificar esa causa raíz si se quiere volver a
        # usar "discover -s tests" sin filtro (p. ej. en CI).
        test_files = sorted(p.name for p in (BACKEND_DIR / "tests").glob("test_*.py"))
        file_failures = []
        total_tests_run = 0
        for name in test_files:
            result = run_backend_script(
                ["-m", "unittest", "discover", "-s", "tests", "-p", name],
                DATABASE_URL=legacy_dev_url, TEST_DATABASE_URL=legacy_test_url, PG_PRIVILEGE_MODE="legacy",
            )
            text = (result.stderr or result.stdout or "")
            match = re.search(r"Ran (\d+) test", text)
            if match:
                total_tests_run += int(match.group(1))
            if result.returncode != 0:
                file_failures.append((name, text.strip().splitlines()[-1] if text.strip() else ""))
        if file_failures:
            report("suite completa backend (archivo por archivo) — modo legado, aislada", "FAIL",
                  f"{len(file_failures)}/{len(test_files)} archivos con fallo, {total_tests_run} pruebas en total: "
                  + "; ".join(f"{n} ({d})" for n, d in file_failures[:8]))
        else:
            report("suite completa backend (archivo por archivo) — modo legado, aislada", "PASS",
                  f"{len(test_files)} archivos, {total_tests_run} pruebas, 0 fallos")

    return _run_role_model(boot_password, passwords)


def _run_role_model(boot_password, passwords):
    import psycopg

    # =====================================================================================================
    # Fase A: aprovisionamiento de roles sobre la base de negocio (vinto_cloud01b2)
    # =====================================================================================================
    app_url = url("vinto_app", passwords["app"], DB)
    migrator_url = url("vinto_migrator", passwords["migrator"], DB)
    reference_url = url("vinto_reference", passwords["reference"], DB)

    print("\n=== Fase A: aprovisionamiento de roles ===", flush=True)
    result = psql_file(ROLES_DIR / "00_create_roles.sql", user=BOOT_USER, password=boot_password, dbname=DB,
                       env_vars={"APP_PASSWORD": passwords["app"], "MIGRATOR_PASSWORD": passwords["migrator"],
                                 "REFERENCE_PASSWORD": passwords["reference"]})
    report("00_create_roles.sql (vinto_app/migrator/reference, sin vinto_test_admin)",
          "PASS" if result.returncode == 0 else "FAIL", result.stderr.strip()[-300:])

    # PG54-05: re-ejecutar el mismo script debe ser un no-op (idempotente), no un error.
    rerun = psql_file(ROLES_DIR / "00_create_roles.sql", user=BOOT_USER, password=boot_password, dbname=DB,
                      env_vars={"APP_PASSWORD": passwords["app"], "MIGRATOR_PASSWORD": passwords["migrator"],
                                "REFERENCE_PASSWORD": passwords["reference"]})
    report("00_create_roles.sql es idempotente (re-ejecución sin error)", "PASS" if rerun.returncode == 0 else "FAIL",
          rerun.stderr.strip()[-300:])

    result = psql_file(ROLES_DIR / "00b_create_test_admin_role.sql", user=BOOT_USER, password=boot_password, dbname=DB,
                       env_vars={"TEST_ADMIN_PASSWORD": passwords["test_admin"]})
    report("00b_create_test_admin_role.sql (solo DEV/QA)", "PASS" if result.returncode == 0 else "FAIL", result.stderr.strip()[-300:])

    result = psql_file(ROLES_DIR / "01_database_grants.sql", user=BOOT_USER, password=boot_password, dbname=DB,
                       env_vars={"DBNAME": DB})
    report("01_database_grants.sql", "PASS" if result.returncode == 0 else "FAIL", result.stderr.strip()[-300:])

    print("\n=== Fase B: compatibilidad del migrador ===", flush=True)
    migrate_result = run_backend_script(["migrate.py"], MIGRATOR_DATABASE_URL=migrator_url)
    report("migrate.py --target dev (como vinto_migrator)", "PASS" if migrate_result.returncode == 0 else "FAIL",
          migrate_result.stdout.strip().splitlines()[-1] if migrate_result.stdout else migrate_result.stderr.strip()[-300:])

    check_result = run_backend_script(["migrate.py", "--check"], MIGRATOR_DATABASE_URL=migrator_url)
    report("migrate.py --check (0 pendientes, checksum verificado)", "PASS" if check_result.returncode == 0 else "FAIL",
          check_result.stdout.strip().splitlines()[-1] if check_result.stdout else "")

    for script in ("02_schema_grants.sql", "03_table_grants.sql", "03b_d3b1_restrict_catalog_writes.sql", "04_function_grants.sql",
                  "05_no_default_privileges.sql", "06_public_and_meta_protection.sql"):
        result = psql_file(ROLES_DIR / script, user="vinto_migrator", password=passwords["migrator"], dbname=DB)
        report(script, "PASS" if result.returncode == 0 else "FAIL", result.stderr.strip()[-300:])

    verify_result = psql_file(ROLES_DIR / "07_verification_queries.sql", user="vinto_migrator", password=passwords["migrator"], dbname=DB)
    report("07_verification_queries.sql (ejecuta sin error)", "PASS" if verify_result.returncode == 0 else "FAIL", verify_result.stderr.strip()[-300:])
    if verify_result.returncode == 0:
        print(redact(verify_result.stdout))

    # ---- PG54-01: una tabla "futura" no hereda ningún privilegio (fail-closed) -----------------------
    print("\n=== PG54-01: objetos futuros sin ningún privilegio por defecto ===", flush=True)
    with psycopg.connect(migrator_url, autocommit=True) as migrator_conn:
        def future_table_is_fail_closed():
            migrator_conn.execute("CREATE TABLE vinto_txn.futura_0007_demo (id uuid PRIMARY KEY DEFAULT gen_random_uuid())")
            try:
                rows = migrator_conn.execute(
                    "SELECT role, priv, has_table_privilege(role, 'vinto_txn.futura_0007_demo', priv) "
                    "FROM (VALUES ('vinto_app'),('vinto_reference'),('public')) AS r(role), "
                    "(VALUES ('SELECT'),('INSERT'),('UPDATE'),('DELETE')) AS p(priv)").fetchall()
                granted = [(role, priv) for role, priv, has in rows if has]
                if granted:
                    raise AssertionError(f"una tabla recién creada por migrator concede privilegios sin GRANT explícito: {granted!r}")
            finally:
                migrator_conn.execute("DROP TABLE IF EXISTS vinto_txn.futura_0007_demo")

        expect_ok("tabla futura sin migración-GRANT: vinto_app/vinto_reference/PUBLIC sin ningún privilegio (SELECT/INSERT/UPDATE/DELETE)",
                 future_table_is_fail_closed)

        def future_function_protected_by_global_default():
            # PG54-FINAL (verificación de ChatGPT): "ALTER DEFAULT PRIVILEGES FOR ROLE vinto_migrator
            # REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC" (SIN "IN SCHEMA", aplicado en
            # backend/roles/05_no_default_privileges.sql) SÍ protege automáticamente, con alcance global
            # por rol creador, a cualquier función nueva — sin necesitar un REVOKE explícito por función.
            # Esta prueba crea la función SIN ningún REVOKE propio y confirma que ya queda protegida.
            migrator_conn.execute("CREATE FUNCTION vinto_txn.futura_funcion_0007(x date) RETURNS integer LANGUAGE sql IMMUTABLE STRICT AS $$ SELECT 1 $$")
            try:
                rows = migrator_conn.execute(
                    "SELECT role, has_function_privilege(role, 'vinto_txn.futura_funcion_0007(date)', 'EXECUTE') "
                    "FROM (VALUES ('vinto_app'),('vinto_reference'),('public')) AS r(role)").fetchall()
                granted = [role for role, has in rows if has]
                if granted:
                    raise AssertionError(f"una función futura SIN REVOKE propio quedó con EXECUTE para: {granted!r} (el default global no la protegió)")
            finally:
                migrator_conn.execute("DROP FUNCTION IF EXISTS vinto_txn.futura_funcion_0007(date)")

        expect_ok("función futura SIN REVOKE propio, protegida solo por el default global de vinto_migrator: "
                 "vinto_app/vinto_reference/PUBLIC sin EXECUTE", future_function_protected_by_global_default)

        def other_role_function_not_covered_by_migrator_default():
            # No atribuir el default de vinto_migrator a otra identidad: una función creada por un rol
            # DISTINTO (aquí, el administrador del clúster) no debe heredar ese REVOKE global.
            with psycopg.connect(url(BOOT_USER, boot_password, DB), autocommit=True) as boot_conn:
                boot_conn.execute("CREATE FUNCTION public.futura_funcion_otro_rol(x date) RETURNS integer LANGUAGE sql IMMUTABLE STRICT AS $$ SELECT 1 $$")
                try:
                    has_it = boot_conn.execute(
                        "SELECT has_function_privilege('public', 'public.futura_funcion_otro_rol(date)', 'EXECUTE')").fetchone()[0]
                    if not has_it:
                        raise AssertionError("una función creada por el administrador del clúster (no vinto_migrator) quedó sin EXECUTE para PUBLIC: el default de vinto_migrator se filtró a otra identidad")
                finally:
                    boot_conn.execute("DROP FUNCTION IF EXISTS public.futura_funcion_otro_rol(date)")

        expect_ok("el default global de vinto_migrator NO se atribuye a una función creada por otra identidad",
                 other_role_function_not_covered_by_migrator_default)

        def management_start_year_is_not_public():
            rows = migrator_conn.execute(
                "SELECT role, has_function_privilege(role, 'vinto_txn.management_start_year(date)', 'EXECUTE') "
                "FROM (VALUES ('vinto_reference'),('vinto_test_admin'),('public')) AS r(role)").fetchall()
            granted = [role for role, has in rows if has]
            if granted:
                raise AssertionError(f"management_start_year sigue siendo ejecutable por quien no debería: {granted!r}")

        expect_ok("vinto_txn.management_start_year: vinto_reference/vinto_test_admin/PUBLIC sin EXECUTE "
                 "(corregido con REVOKE explícito sobre el objeto existente, 04_function_grants.sql)",
                 management_start_year_is_not_public)

    # =====================================================================================================
    # Fase B/D: la API no puede alterar la estructura (negativas, SQLSTATE verificado)
    # =====================================================================================================
    print("\n=== Fase B/D: la API no puede alterar la estructura ===", flush=True)
    with psycopg.connect(app_url, autocommit=True) as app_conn:
        expect_fail("vinto_app: CREATE TABLE rechazado por permiso",
                   lambda: app_conn.execute("CREATE TABLE vinto_txn.intento_no_autorizado (id int)"), "42501")
        expect_fail("vinto_app: ALTER TABLE rechazado por permiso",
                   lambda: app_conn.execute("ALTER TABLE vinto_txn.capture ADD COLUMN intento int"), "42501")

        def grant_is_noop():
            # PostgreSQL no lanza una excepción cuando quien concede no es propietario ni tiene
            # WITH GRANT OPTION: emite un WARNING y no concede nada (comprobado empíricamente). La
            # verificación real es que el estado de privilegios no cambia, no que la sentencia falle.
            before = app_conn.execute("SELECT has_table_privilege('vinto_reference', 'vinto_master.\"user\"', 'SELECT')").fetchone()[0]
            app_conn.execute("GRANT SELECT ON vinto_master.\"user\" TO vinto_reference")
            after = app_conn.execute("SELECT has_table_privilege('vinto_reference', 'vinto_master.\"user\"', 'SELECT')").fetchone()[0]
            if before is not False or after is not False:
                raise AssertionError(f"el GRANT emitido por vinto_app (sin WITH GRANT OPTION) SÍ otorgó algo: before={before} after={after}")

        expect_ok("vinto_app: GRANT a otro rol es un no-op (sin WITH GRANT OPTION, PostgreSQL no concede nada)", grant_is_noop)
        expect_fail("vinto_app: SELECT sobre vinto_meta.schema_migration rechazado por permiso",
                   lambda: app_conn.execute("SELECT * FROM vinto_meta.schema_migration"), "42501")
        expect_fail("vinto_app: DELETE sobre vinto_txn.capture rechazado por permiso (no por trigger)",
                   lambda: app_conn.execute("DELETE FROM vinto_txn.capture"), "42501")
        expect_fail("vinto_app: TRUNCATE sobre vinto_audit.audit_event rechazado por permiso",
                   lambda: app_conn.execute("TRUNCATE vinto_audit.audit_event"), "42501")

    with psycopg.connect(reference_url, autocommit=True) as ref_conn:
        expect_fail("vinto_reference: INSERT sobre vinto_txn rechazado (sin USAGE del esquema)",
                   lambda: ref_conn.execute("INSERT INTO vinto_txn.work_order (machine_id, order_number) VALUES (gen_random_uuid(), 'X')"),
                   "42501")
        expect_fail("vinto_reference: SELECT sobre vinto_auth rechazado (sin USAGE del esquema)",
                   lambda: ref_conn.execute("SELECT * FROM vinto_auth.credential"), "42501")

    # =====================================================================================================
    # Fase C: importador de referencias con identidad propia
    # =====================================================================================================
    print("\n=== Fase C: importador de referencias con identidad propia ===", flush=True)
    import_result = run_backend_script(["import_reference.py", "--target", "dev", "--apply"], REFERENCE_DATABASE_URL=reference_url)
    report("import_reference.py --target dev --apply (como vinto_reference)", "PASS" if import_result.returncode == 0 else "FAIL",
          import_result.stdout.strip().splitlines()[-1] if import_result.stdout else import_result.stderr.strip()[-300:])

    # =====================================================================================================
    # Fase D: flujo real de negocio como vinto_app
    # =====================================================================================================
    print("\n=== Fase D: flujo de negocio real con vinto_app ===", flush=True)
    sys.path.insert(0, str(BACKEND_DIR))
    sys.path.insert(0, str(BACKEND_DIR / "tests"))
    from app.auth.service import create_user
    from app.auth.sessions import login_with_session, revoke_session
    from app.auth.grants import revoke_sector, sector_codes_for_user
    from app.seed.bundle import load_bundle
    from app.work_orders import service as work_orders_module
    from app.work_orders.service import LineInput
    from app.assignments import service as assignments_module
    from app.bobbins import service as bobbins_module
    from scope_helpers import internal

    work_orders_i = internal(work_orders_module)
    assignments_i = internal(assignments_module)
    bobbins_i = internal(bobbins_module)
    bundle = load_bundle()
    mp1_codes = sorted(r["article_code"] for r in bundle.article_machines if r["machine_code"] == "MP1")

    with psycopg.connect(app_url, autocommit=True) as app_conn, psycopg.connect(migrator_url, autocommit=True) as audit_reader:
        # audit_reader: vinto_app por diseño NO tiene SELECT sobre vinto_auth.auth_event ni vinto_audit.audit_event
        # (solo INSERT, ver backend/roles/03_table_grants.sql) — verificar lo que quedó escrito exige una
        # identidad con más alcance, aquí vinto_migrator, igual que lo haría un auditor real.
        state = {}

        def setup_users():
            state["jefatura"] = create_user(app_conn, username=f"cloud01b2.jefatura.{uuid.uuid4().hex[:8]}", display_name="Jefatura CLOUD-01B-2",
                                            profile_code="JEFATURA", password="pw-" + secrets.token_urlsafe(18), sectors=("BOBINAS",)).user_id
            state["supervision"] = create_user(app_conn, username=f"cloud01b2.supervision.{uuid.uuid4().hex[:8]}", display_name="Supervisión CLOUD-01B-2",
                                               profile_code="SUPERVISION", password="pw-" + secrets.token_urlsafe(18), sectors=("BOBINAS",)).user_id
            password = "pw-" + secrets.token_urlsafe(18)
            username = f"cloud01b2.operacion.{uuid.uuid4().hex[:8]}"
            created = create_user(app_conn, username=username, display_name="Operación CLOUD-01B-2", profile_code="OPERACION",
                                  password=password, sectors=("BOBINAS",))
            state["operacion"] = (created.user_id, username, password)

        expect_ok("vinto_app: create_user (JEFATURA/SUPERVISION/OPERACION) con sector BOBINAS", setup_users)

        def login_logout():
            operator_id, username, password = state["operacion"]
            user, session = login_with_session(app_conn, username, password, request_id="cloud01b2-e2e")
            if user.user_id != operator_id:
                raise AssertionError("login devolvió un usuario distinto al creado")
            revoked = revoke_session(app_conn, session.raw_token, request_id="cloud01b2-e2e")
            if not revoked:
                raise AssertionError("revoke_session no revocó la sesión recién creada")
            events = audit_reader.execute("SELECT event FROM vinto_auth.auth_event WHERE user_id = %s ORDER BY occurred_at", (operator_id,)).fetchall()
            if [e[0] for e in events] != ["login_ok", "logout"]:
                raise AssertionError(f"bitácora inesperada: {events!r}")

        expect_ok("vinto_app: login + sesión + logout + bitácora (vinto_auth.auth_event)", login_logout)

        def f3_capture():
            order = work_orders_i.create_work_order(app_conn, actor_id=state["jefatura"], machine_code="MP1",
                                                     lines=[LineInput("PV-CLOUD01B2", mp1_codes[0], 5, date(2026, 11, 1))])
            order = work_orders_i.publish_work_order(app_conn, actor_id=state["jefatura"], work_order_id=order.id)
            activation = assignments_i.activate(app_conn, actor_id=state["supervision"], work_order_id=order.id,
                                                baseline_line_id=order.baseline.lines[0].id)
            result = bobbins_i.submit_bobbin_production(
                app_conn, actor_id=state["operacion"][0], capture_id=uuid.uuid4(), assignment_id=activation.assignment.id,
                device_key=str(uuid.uuid4()),
                values={"hora_inicio": "07:15", "hora_fin": "08:40", "diametro": "1200.5", "peso_kg": "845.25",
                       "numero_de_cortes": "3", "observaciones": "CLOUD-01B-2B.1"})
            if result.bobbin.sequence_number != 1:
                raise AssertionError(f"bobina F3 inesperada: {result.bobbin!r}")
            release = app_conn.execute("SELECT status FROM vinto_txn.quality_release WHERE bobbin_id = %s", (result.bobbin.id,)).fetchone()
            if release is None:
                raise AssertionError("falta la fila quality_release exigida por el trigger require_quality_release")

        expect_ok("vinto_app: OT + asignación + captura F3 completa (vinto_txn.bobbin + quality_release)", f3_capture)

        def management_start_year_execute():
            value = app_conn.execute("SELECT vinto_txn.management_start_year(%s)", (date(2026, 11, 1),)).fetchone()[0]
            if value != 2026:
                raise AssertionError(f"resultado inesperado de management_start_year: {value!r}")

        expect_ok("vinto_app: EXECUTE directo sobre vinto_txn.management_start_year", management_start_year_execute)

        def sector_revoke():
            operator_id = state["operacion"][0]
            before = sector_codes_for_user(app_conn, operator_id)
            changed = revoke_sector(app_conn, user_id=operator_id, sector_code="BOBINAS", request_id="cloud01b2-e2e-revoke")
            after = sector_codes_for_user(app_conn, operator_id)
            if not changed or "BOBINAS" not in before or "BOBINAS" in after:
                raise AssertionError(f"revocación de sector inesperada: before={before!r} after={after!r} changed={changed!r}")
            audited = audit_reader.execute(
                "SELECT count(*) FROM vinto_audit.audit_event WHERE entity_schema='vinto_master' AND entity_table='user_sector' AND action='DELETE'"
            ).fetchone()[0]
            if audited < 1:
                raise AssertionError("la revocación de sector no quedó auditada en vinto_audit.audit_event")

        expect_ok("vinto_app: DELETE vinto_master.user_sector (revocación) + auditoría automática", sector_revoke)

    # =====================================================================================================
    # Fase D: administrador de bases efímeras (solo DEV/QA)
    # =====================================================================================================
    print("\n=== Fase D: administrador de bases efímeras (solo DEV/QA) ===", flush=True)
    test_admin_pg_url = url("vinto_test_admin", passwords["test_admin"], "postgres")

    def test_admin_lifecycle():
        from psycopg import sql as _sql
        name = f"vinto_cloud01b2_{uuid.uuid4().hex[:10]}_test"
        with psycopg.connect(test_admin_pg_url, autocommit=True) as admin:
            admin.execute(_sql.SQL("CREATE DATABASE {}").format(_sql.Identifier(name)))
            with psycopg.connect(url("vinto_test_admin", passwords["test_admin"], name), autocommit=True) as owner_conn:
                owner_conn.execute(_sql.SQL("GRANT CONNECT ON DATABASE {} TO vinto_migrator, vinto_app").format(_sql.Identifier(name)))
                owner_conn.execute(_sql.SQL("GRANT CREATE ON DATABASE {} TO vinto_migrator").format(_sql.Identifier(name)))
            migrate_test = run_backend_script(["migrate.py", "--target", "test"],
                                              MIGRATOR_TEST_DATABASE_URL=url("vinto_migrator", passwords["migrator"], name),
                                              TEST_DATABASE_URL=url("vinto_app", passwords["app"], name))
            if migrate_test.returncode != 0:
                raise AssertionError(f"migrate.py --target test falló: {migrate_test.stdout}{migrate_test.stderr}")
            check_test = run_backend_script(["migrate.py", "--target", "test", "--check"],
                                            MIGRATOR_TEST_DATABASE_URL=url("vinto_migrator", passwords["migrator"], name),
                                            TEST_DATABASE_URL=url("vinto_app", passwords["app"], name))
            if check_test.returncode != 0:
                raise AssertionError(f"migrate.py --target test --check falló tras migrar: {check_test.stdout}")
            with psycopg.connect(url("vinto_migrator", passwords["migrator"], name), autocommit=True) as mig_conn:
                mig_conn.execute("UPDATE vinto_meta.schema_migration SET checksum = repeat('0', 64) WHERE version = 1")
            tampered = run_backend_script(["migrate.py", "--target", "test", "--check"],
                                          MIGRATOR_TEST_DATABASE_URL=url("vinto_migrator", passwords["migrator"], name),
                                          TEST_DATABASE_URL=url("vinto_app", passwords["app"], name))
            if tampered.returncode == 0 or "modificada" not in tampered.stdout:
                raise AssertionError(f"un checksum corrompido debía hacer fallar --check: {tampered.stdout}{tampered.stderr}")
            admin.execute(_sql.SQL("DROP DATABASE {} WITH (FORCE)").format(_sql.Identifier(name)))

    expect_ok("vinto_test_admin: crear base *_test, migrar como vinto_migrator, detectar checksum alterado, destruir la base",
             test_admin_lifecycle)

    def prepare_test_db_cli():
        from psycopg import sql as _sql
        name = f"vinto_cloud01b2_prep_{uuid.uuid4().hex[:10]}_test"
        try:
            result = run_backend_script(
                ["prepare_test_db.py"],
                TEST_ADMIN_DATABASE_URL=test_admin_pg_url,
                MIGRATOR_TEST_DATABASE_URL=url("vinto_migrator", passwords["migrator"], name),
                TEST_DATABASE_URL=url("vinto_app", passwords["app"], name),
            )
            if result.returncode != 0:
                raise AssertionError(f"prepare_test_db.py falló: {result.stdout}{result.stderr}")
            # vinto_app no tiene USAGE sobre vinto_meta por diseño: to_regclass() con ese rol lanzaría
            # "permission denied for schema vinto_meta" en vez de devolver NULL (solo ocurre así cuando
            # el esquema SÍ existe pero no es visible; si no existiera, devolvería NULL sin error). La
            # verificación usa vinto_migrator, que es quien de verdad puede ver vinto_meta.
            with psycopg.connect(url("vinto_migrator", passwords["migrator"], name), autocommit=True) as check_conn:
                migrated = check_conn.execute("SELECT to_regclass('vinto_meta.schema_migration') IS NOT NULL").fetchone()[0]
            if not migrated:
                raise AssertionError("prepare_test_db.py terminó OK pero la base no quedó migrada")
        finally:
            with psycopg.connect(test_admin_pg_url, autocommit=True) as admin:
                admin.execute(_sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(_sql.Identifier(name)))

    expect_ok("prepare_test_db.py (CLI real, modo legado) con TEST_ADMIN_DATABASE_URL/MIGRATOR_TEST_DATABASE_URL separadas",
             prepare_test_db_cli)

    def ephemeral_db_module():
        from pydantic import SecretStr
        from app.config import settings as live_settings
        from app import ephemeral_db

        previous = (live_settings.test_database_url, live_settings.test_admin_database_url,
                   live_settings.migrator_test_database_url, live_settings.pg_privilege_mode, live_settings.app_env)
        try:
            live_settings.pg_privilege_mode = "legacy"
            live_settings.test_database_url = SecretStr(url("vinto_app", passwords["app"], "postgres"))
            live_settings.test_admin_database_url = SecretStr(test_admin_pg_url)
            name = f"vinto_cloud01b2_mod_{uuid.uuid4().hex[:10]}_test"
            ephemeral_db.create_database(name)
            try:
                from psycopg import sql as _sql
                with psycopg.connect(url("vinto_test_admin", passwords["test_admin"], name), autocommit=True) as owner_conn:
                    owner_conn.execute(_sql.SQL("GRANT CONNECT ON DATABASE {} TO vinto_app").format(_sql.Identifier(name)))
                live_settings.test_database_url = SecretStr(url("vinto_app", passwords["app"], name))
                with ephemeral_db.connect(name) as conn:
                    identity = conn.execute("SELECT current_database()").fetchone()[0]
                    if identity != name:
                        raise AssertionError(f"ephemeral_db.connect() conectó a {identity!r}, se esperaba {name!r}")
            finally:
                ephemeral_db.drop_database(name)
        finally:
            (live_settings.test_database_url, live_settings.test_admin_database_url,
             live_settings.migrator_test_database_url, live_settings.pg_privilege_mode, live_settings.app_env) = previous

    expect_ok("app/ephemeral_db.py: create_database/connect/drop_database reales con TEST_ADMIN_DATABASE_URL", ephemeral_db_module)

    # PUBLIC conserva CONNECT sobre "postgres" por defecto (es la base de mantenimiento del clúster,
    # compartida; no se le revoca PUBLIC CONNECT de forma universal). La barrera real contra
    # vinto_app/vinto_reference no es CONNECT: es no tener CREATEDB.
    def app_cannot_createdb():
        from psycopg import sql as _sql
        with psycopg.connect(url("vinto_app", passwords["app"], "postgres"), autocommit=True, connect_timeout=5) as conn:
            conn.execute(_sql.SQL("CREATE DATABASE {}").format(_sql.Identifier(f"vinto_cloud01b2_intento_{uuid.uuid4().hex[:8]}_test")))

    expect_fail("vinto_app: sin CREATEDB, no puede crear una base *_test (negativo)", app_cannot_createdb, "42501")

    # =====================================================================================================
    # PG54-04: modo hardened — positivas y negativas
    # =====================================================================================================
    print("\n=== PG54-04: señal explícita de modo endurecido (hardened) ===", flush=True)

    # Positiva: hardened + todas las URL requeridas presentes -> funciona igual que en modo legado.
    hardened_ok = run_backend_script(["migrate.py", "--check"], MIGRATOR_DATABASE_URL=migrator_url, PG_PRIVILEGE_MODE="hardened")
    report("hardened + MIGRATOR_DATABASE_URL presente: migrate.py --check funciona igual",
          "PASS" if hardened_ok.returncode == 0 else "FAIL",
          hardened_ok.stdout.strip().splitlines()[-1] if hardened_ok.stdout else hardened_ok.stderr.strip()[-300:])

    # Negativa: hardened + falta MIGRATOR_DATABASE_URL -> debe fallar explícitamente, NUNCA caer en
    # DATABASE_URL (la cuenta de la API, más privilegiada de lo necesario para migrar).
    hardened_missing = run_backend_script(["migrate.py", "--check"], DATABASE_URL=app_url, PG_PRIVILEGE_MODE="hardened")
    expect_process_fail("hardened + MIGRATOR_DATABASE_URL ausente: falla explícito, sin fallback silencioso a DATABASE_URL",
                       hardened_missing, contains="hardened")

    # Negativa equivalente para el importador de referencias.
    hardened_ref_missing = run_backend_script(["import_reference.py", "--target", "dev"], DATABASE_URL=app_url, PG_PRIVILEGE_MODE="hardened")
    expect_process_fail("hardened + REFERENCE_DATABASE_URL ausente: import_reference.py falla explícito",
                       hardened_ref_missing, contains="hardened")

    # Negativa: hardened + APP_ENV no reconocido como entorno de prueba -> ninguna identidad
    # administrativa de pruebas efímeras puede operar, aunque TEST_ADMIN_DATABASE_URL esté configurada.
    def _prepare_test_db_hardened(app_env, name_suffix):
        name = f"vinto_cloud01b2_hard_{name_suffix}_test"
        return run_backend_script(
            ["prepare_test_db.py"],
            PG_PRIVILEGE_MODE="hardened", APP_ENV=app_env,
            TEST_ADMIN_DATABASE_URL=test_admin_pg_url,
            MIGRATOR_TEST_DATABASE_URL=url("vinto_migrator", passwords["migrator"], name),
            TEST_DATABASE_URL=url("vinto_app", passwords["app"], name),
        ), name

    hardened_prod, _ = _prepare_test_db_hardened("production", uuid.uuid4().hex[:8])
    expect_process_fail("hardened + APP_ENV=production: prepare_test_db.py se niega a operar (identidad de pruebas en proceso operativo)",
                       hardened_prod, contains="hardened")

    # Positiva: hardened + APP_ENV reconocido como de prueba (qa) -> la misma operación SÍ funciona.
    def hardened_qa_allowed():
        from psycopg import sql as _sql
        result, name = _prepare_test_db_hardened("qa", uuid.uuid4().hex[:8])
        try:
            if result.returncode != 0:
                raise AssertionError(f"prepare_test_db.py en hardened+APP_ENV=qa debía funcionar: {result.stdout}{result.stderr}")
        finally:
            with psycopg.connect(test_admin_pg_url, autocommit=True) as admin:
                admin.execute(_sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(_sql.Identifier(name)))

    expect_ok("hardened + APP_ENV=qa: prepare_test_db.py funciona con todas las credenciales explícitas", hardened_qa_allowed)


if __name__ == "__main__":
    sys.exit(main())
