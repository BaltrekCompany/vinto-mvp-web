"""CLOUD-01B-2B.1 · validación end-to-end del modelo de privilegios mínimos de PostgreSQL 17.

Herramienta de QA/infraestructura, NO se importa desde la aplicación ni desde la suite de unittest
(requiere Docker y tarda; se ejecuta a mano: `cd backend && PYTHONPATH=. python tests/roles_e2e.py`).

Qué hace, en una instancia PostgreSQL 17 EFÍMERA propia (contenedor con nombre y puerto exclusivos,
`--tmpfs`, sin volumen, nunca el stack compartido de docker-compose.yml):

  1. Crea las 4 identidades de backend/roles/ (vinto_app, vinto_migrator, vinto_reference,
     vinto_test_admin) con contraseñas generadas al vuelo (nunca credenciales reales).
  2. Aplica las migraciones 0001-0006 conectando como vinto_migrator (migrate.py --target dev), de
     modo que resulte propietario real de los 6 esquemas.
  3. Aplica los GRANT de backend/roles/02..06 conectando como vinto_migrator.
  4. Importa el bundle oficial (import_reference.py --target dev --apply) conectando como
     vinto_reference.
  5. Ejerce el flujo real de negocio (login/sesión/logout, OT, asignación, captura F3, revocación de
     sector) conectando como vinto_app, reutilizando las funciones de app/ tal cual las usa la API.
  6. Repite el ciclo de vida de una base *_test efímera (prepare_test_db.py) con vinto_test_admin
     (CREATEDB) + vinto_migrator, y la destruye al terminar.
  7. Ejecuta pruebas negativas (DDL, GRANT, TRUNCATE, acceso a vinto_meta/vinto_auth/vinto_txn fuera de
     alcance) verificando el SQLSTATE exacto para no confundir un rechazo por permiso (42501) con uno
     por trigger de negocio (23514).
  8. Imprime un informe PASS/FAIL/BLOCKED y limpia el contenedor (incluso si algo falla).

No modifica main, no toca ninguna base real, no lee ningún .env real: cada conexión de este script usa
una URL construida en memoria contra el contenedor efímero, nunca backend/.env.
"""

import json
import os
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent
ROLES_DIR = BACKEND_DIR / "roles"

CONTAINER = "vinto-cloud01b2-pg"
HOST_PORT = 55461
DB = "vinto_cloud01b2"
BOOT_USER = "cloud01b2_root"

RESULTS = []  # (name, status, detail) — status in PASS/FAIL/BLOCKED


def report(name, status, detail=""):
    RESULTS.append((name, status, detail))
    print(f"{status:7} {name}{'  — ' + detail if detail else ''}", flush=True)


def run(cmd, **kwargs):
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def psql_file(path, *, user, password, dbname, variables=None, port=5432):
    args = ["docker", "exec", "-i", "-e", f"PGPASSWORD={password}", CONTAINER,
            "psql", "-h", "127.0.0.1", "-p", str(port), "-U", user, "-d", dbname, "-v", "ON_ERROR_STOP=1"]
    for key, value in (variables or {}).items():
        args += ["-v", f"{key}={value}"]
    args += ["-f", "-"]
    with open(path, "rb") as handle:
        result = run(args, input=handle.read().decode("utf-8"))
    return result


def url(user, password, dbname, host="127.0.0.1", port=HOST_PORT):
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def docker_up(boot_password):
    run(["docker", "rm", "-f", CONTAINER])  # por si quedó de una corrida anterior interrumpida
    result = run(["docker", "run", "-d", "--name", CONTAINER,
                  "-e", f"POSTGRES_USER={BOOT_USER}", "-e", f"POSTGRES_PASSWORD={boot_password}", "-e", f"POSTGRES_DB={DB}",
                  "-p", f"127.0.0.1:{HOST_PORT}:5432", "--tmpfs", "/var/lib/postgresql/data",
                  "postgres:17"])
    if result.returncode != 0:
        raise RuntimeError(f"docker run falló: {result.stderr}")
    for _ in range(60):
        ready = run(["docker", "exec", CONTAINER, "pg_isready", "-U", BOOT_USER, "-d", DB])
        if ready.returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("PostgreSQL efímero no respondió a tiempo")


def docker_down():
    run(["docker", "rm", "-f", CONTAINER])


def subprocess_env(**overrides):
    env = os.environ.copy()
    env["PYTHONPATH"] = "."
    env["DB_CONNECT_TIMEOUT"] = "10"
    env["DB_STATEMENT_TIMEOUT_MS"] = "20000"
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


def main() -> int:
    boot_password = secrets.token_urlsafe(24)
    passwords = {role: secrets.token_urlsafe(24) for role in ("app", "migrator", "reference", "test_admin")}

    print(f"=== Levantando PostgreSQL 17 efímero ({CONTAINER}, puerto {HOST_PORT}) ===", flush=True)
    try:
        docker_up(boot_password)
    except RuntimeError as error:
        report("arranque del contenedor efímero", "BLOCKED", str(error))
        docker_down()
        return 1

    try:
        _run_all(boot_password, passwords)
    finally:
        print(f"=== Deteniendo y eliminando el contenedor efímero ({CONTAINER}) ===", flush=True)
        docker_down()

    failures = [r for r in RESULTS if r[1] != "PASS"]
    print(f"\nTOTAL {len(RESULTS)} · PASS {len(RESULTS) - len(failures)} · FAIL/BLOCKED {len(failures)}")
    return 1 if failures else 0


def _run_all(boot_password, passwords):
    app_url = url("vinto_app", passwords["app"], DB)
    migrator_url = url("vinto_migrator", passwords["migrator"], DB)
    reference_url = url("vinto_reference", passwords["reference"], DB)

    # ---- 1. Aprovisionamiento de roles (00) ---------------------------------------------------------
    print("\n=== Fase A: aprovisionamiento de roles ===", flush=True)
    result = psql_file(ROLES_DIR / "00_create_roles.sql", user=BOOT_USER, password=boot_password, dbname=DB,
                       variables={"app_password": passwords["app"], "migrator_password": passwords["migrator"],
                                  "reference_password": passwords["reference"], "test_admin_password": passwords["test_admin"]})
    report("00_create_roles.sql", "PASS" if result.returncode == 0 else "FAIL", result.stderr.strip()[-300:])

    # ---- 2. CONNECT / PUBLIC sobre la base de negocio (01) ------------------------------------------
    result = psql_file(ROLES_DIR / "01_database_grants.sql", user=BOOT_USER, password=boot_password, dbname=DB,
                       variables={"dbname": DB})
    report("01_database_grants.sql", "PASS" if result.returncode == 0 else "FAIL", result.stderr.strip()[-300:])

    # ---- 3. Migraciones 0001-0006 como vinto_migrator (Fase B) --------------------------------------
    print("\n=== Fase B: compatibilidad del migrador ===", flush=True)
    migrate_result = run_backend_script(["migrate.py"], MIGRATOR_DATABASE_URL=migrator_url)
    report("migrate.py --target dev (como vinto_migrator)", "PASS" if migrate_result.returncode == 0 else "FAIL",
          migrate_result.stdout.strip().splitlines()[-1] if migrate_result.stdout else migrate_result.stderr.strip()[-300:])

    check_result = run_backend_script(["migrate.py", "--check"], MIGRATOR_DATABASE_URL=migrator_url)
    report("migrate.py --check (0 pendientes, checksum verificado)", "PASS" if check_result.returncode == 0 else "FAIL",
          check_result.stdout.strip().splitlines()[-1] if check_result.stdout else "")

    # ---- 4. GRANT 02-06 como vinto_migrator ----------------------------------------------------------
    for script in ("02_schema_grants.sql", "03_table_grants.sql", "04_function_grants.sql",
                  "05_default_privileges.sql", "06_public_and_meta_protection.sql"):
        result = psql_file(ROLES_DIR / script, user="vinto_migrator", password=passwords["migrator"], dbname=DB)
        report(script, "PASS" if result.returncode == 0 else "FAIL", result.stderr.strip()[-300:])

    verify_result = psql_file(ROLES_DIR / "07_verification_queries.sql", user="vinto_migrator", password=passwords["migrator"], dbname=DB)
    report("07_verification_queries.sql (ejecuta sin error)", "PASS" if verify_result.returncode == 0 else "FAIL", verify_result.stderr.strip()[-300:])
    if verify_result.returncode == 0:
        print(verify_result.stdout)

    import psycopg  # import tardío: después de fijar sys.path vía subprocess_env para los hijos, pero psycopg no depende de eso

    # ---- 5. Bloqueo consultivo (parte de Fase B): dos sesiones, mismo LOCK_KEY -----------------------
    lock_key = 867420031  # el mismo LOCK_KEY de backend/migrate.py
    with psycopg.connect(migrator_url, autocommit=True) as c1, psycopg.connect(migrator_url, autocommit=True) as c2:
        got1 = c1.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,)).fetchone()[0]
        got2 = c2.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,)).fetchone()[0]
        ok = got1 is True and got2 is False
        report("bloqueo consultivo del migrador: una sesión lo obtiene, la otra no", "PASS" if ok else "FAIL", f"got1={got1} got2={got2}")
        c1.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))
        got3 = c2.execute("SELECT pg_try_advisory_lock(%s)", (lock_key,)).fetchone()[0]
        report("bloqueo consultivo: liberado por una sesión, la otra puede tomarlo", "PASS" if got3 is True else "FAIL", f"got3={got3}")
        c2.execute("SELECT pg_advisory_unlock(%s)", (lock_key,))

    # ---- 6. vinto_app NO puede alterar la estructura (Fase B / Fase D negativas) ----------------------
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

    # ---- 7. Importación de catálogos como vinto_reference (Fase C) ----------------------------------
    print("\n=== Fase C: importador de referencias con identidad propia ===", flush=True)
    import_result = run_backend_script(["import_reference.py", "--target", "dev", "--apply"], REFERENCE_DATABASE_URL=reference_url)
    report("import_reference.py --target dev --apply (como vinto_reference)", "PASS" if import_result.returncode == 0 else "FAIL",
          import_result.stdout.strip().splitlines()[-1] if import_result.stdout else import_result.stderr.strip()[-300:])

    # ---- 8. Flujo real de negocio como vinto_app (Fase D positivas) ---------------------------------
    print("\n=== Fase D: flujo de negocio real con vinto_app ===", flush=True)
    sys.path.insert(0, str(BACKEND_DIR))
    sys.path.insert(0, str(BACKEND_DIR / "tests"))
    from app import sectors as sectors_module
    from app.auth.service import create_user
    from app.auth.sessions import login_with_session, revoke_session
    from app.auth.grants import grant_sector, revoke_sector, sector_codes_for_user
    from app.seed.bundle import load_bundle
    from app.work_orders import service as work_orders_module
    from app.work_orders.service import LineInput
    from app.assignments import service as assignments_module
    from app.bobbins import service as bobbins_module
    from scope_helpers import internal
    from datetime import date

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

    # ---- 9. Ciclo de vida de una base *_test efímera con vinto_test_admin (Fase D / principio 4) ------
    print("\n=== Fase D: administrador de bases efímeras (solo DEV/QA) ===", flush=True)
    test_admin_pg_url = url("vinto_test_admin", passwords["test_admin"], "postgres")

    def test_admin_lifecycle():
        import psycopg as _psycopg
        from psycopg import sql as _sql
        name = f"vinto_cloud01b2_{uuid.uuid4().hex[:10]}_test"
        with _psycopg.connect(test_admin_pg_url, autocommit=True) as admin:
            admin.execute(_sql.SQL("CREATE DATABASE {}").format(_sql.Identifier(name)))
            with _psycopg.connect(url("vinto_test_admin", passwords["test_admin"], name), autocommit=True) as owner_conn:
                # vinto_test_admin es propietario de "name" (lo creó): puede conceder sin ser superusuario.
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
            with _psycopg.connect(url("vinto_migrator", passwords["migrator"], name), autocommit=True) as mig_conn:
                mig_conn.execute("UPDATE vinto_meta.schema_migration SET checksum = repeat('0', 64) WHERE version = 1")
            tampered = run_backend_script(["migrate.py", "--target", "test", "--check"],
                                          MIGRATOR_TEST_DATABASE_URL=url("vinto_migrator", passwords["migrator"], name),
                                          TEST_DATABASE_URL=url("vinto_app", passwords["app"], name))
            if tampered.returncode == 0 or "modificada" not in tampered.stdout:
                raise AssertionError(f"un checksum corrompido debía hacer fallar --check: {tampered.stdout}{tampered.stderr}")
            admin.execute(_sql.SQL("DROP DATABASE {} WITH (FORCE)").format(_sql.Identifier(name)))

    expect_ok("vinto_test_admin: crear base *_test, migrar como vinto_migrator, detectar checksum alterado, destruir la base",
             test_admin_lifecycle)

    # ---- 9b. prepare_test_db.py tal cual (regresión directa del archivo modificado) ------------------
    def prepare_test_db_cli():
        import psycopg as _psycopg
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
            with _psycopg.connect(url("vinto_migrator", passwords["migrator"], name), autocommit=True) as check_conn:
                migrated = check_conn.execute("SELECT to_regclass('vinto_meta.schema_migration') IS NOT NULL").fetchone()[0]
            if not migrated:
                raise AssertionError("prepare_test_db.py terminó OK pero la base no quedó migrada")
        finally:
            with _psycopg.connect(test_admin_pg_url, autocommit=True) as admin:
                admin.execute(_sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(_sql.Identifier(name)))

    expect_ok("prepare_test_db.py (CLI real) con TEST_ADMIN_DATABASE_URL/MIGRATOR_TEST_DATABASE_URL separadas", prepare_test_db_cli)

    # ---- 9c. app/ephemeral_db.py en sí mismo (no una reimplementación): _admin_base_url() nueva -------
    def ephemeral_db_module():
        from pydantic import SecretStr
        from app.config import settings as live_settings
        from app import ephemeral_db

        previous = (live_settings.test_database_url, live_settings.test_admin_database_url, live_settings.migrator_test_database_url)
        try:
            live_settings.test_database_url = SecretStr(url("vinto_app", passwords["app"], "postgres"))
            live_settings.test_admin_database_url = SecretStr(test_admin_pg_url)
            name = f"vinto_cloud01b2_mod_{uuid.uuid4().hex[:10]}_test"
            ephemeral_db.create_database(name)
            try:
                import psycopg as _psycopg
                from psycopg import sql as _sql
                with _psycopg.connect(url("vinto_test_admin", passwords["test_admin"], name), autocommit=True) as owner_conn:
                    owner_conn.execute(_sql.SQL("GRANT CONNECT ON DATABASE {} TO vinto_app").format(_sql.Identifier(name)))
                live_settings.test_database_url = SecretStr(url("vinto_app", passwords["app"], name))
                with ephemeral_db.connect(name) as conn:
                    identity = conn.execute("SELECT current_database()").fetchone()[0]
                    if identity != name:
                        raise AssertionError(f"ephemeral_db.connect() conectó a {identity!r}, se esperaba {name!r}")
            finally:
                ephemeral_db.drop_database(name)
        finally:
            live_settings.test_database_url, live_settings.test_admin_database_url, live_settings.migrator_test_database_url = previous

    expect_ok("app/ephemeral_db.py: create_database/connect/drop_database reales con TEST_ADMIN_DATABASE_URL", ephemeral_db_module)

    # PUBLIC conserva CONNECT sobre "postgres" por defecto (es la base de mantenimiento del clúster,
    # compartida; no se le revoca PUBLIC CONNECT de forma universal). La barrera real contra
    # vinto_app/vinto_reference no es CONNECT: es no tener CREATEDB.
    def app_cannot_createdb():
        import psycopg as _psycopg
        from psycopg import sql as _sql
        with _psycopg.connect(url("vinto_app", passwords["app"], "postgres"), autocommit=True, connect_timeout=5) as conn:
            conn.execute(_sql.SQL("CREATE DATABASE {}").format(_sql.Identifier(f"vinto_cloud01b2_intento_{uuid.uuid4().hex[:8]}_test")))

    expect_fail("vinto_app: sin CREATEDB, no puede crear una base *_test (negativo)", app_cannot_createdb, "42501")


if __name__ == "__main__":
    sys.exit(main())
