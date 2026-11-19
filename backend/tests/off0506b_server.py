"""OFF-04.5B-06B DISPOSABLE end-to-end server (CI / local scratch only): the QA pilot application exactly as the real entrypoint builds it, over a throwaway
PostgreSQL database with the QA role split (restricted application role, identity role), plus the built lab pages served from the SAME origin.

Test-only controls live under /__test__/ (GET only) and exist ONLY in this script. Binds 127.0.0.1 and prints `READY <json>` once serving. Synthetic users,
keys and grants only; it never reads a deployed database URL and never touches a deployed API.
  --mode full   authentication + capture flags ON (synthetic grant for user A only)
  --mode off    both flags OFF (the default of the real entrypoint)
"""
import argparse
import json
import os
import socket
import sys
import threading
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uvicorn  # noqa: E402
from fastapi import Request, Response  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import SecretStr  # noqa: E402

from app import qa_offline_pilot  # noqa: E402
from app.config import settings  # noqa: E402
from app.ephemeral_db import connect, copy_database, drop_database  # noqa: E402
from app.qa_pilot_main import create_app_from_env  # noqa: E402
from tests import off045b06b_support as S  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--public", required=True)
    ap.add_argument("--mode", choices=("full", "off"), default="full")
    args = ap.parse_args()
    template = S.build_template()
    name = copy_database(template, "off06b_e2e")
    users = S.create_users(name)
    sock = socket.socket(); sock.bind(("127.0.0.1", 0)); port = sock.getsockname()[1]; sock.close()
    origin = f"http://127.0.0.1:{port}"
    settings.database_url = SecretStr(S.app_url(name))
    settings.identity_database_url = SecretStr(S.identity_url(name))
    settings.auth_cookie_name = "vinto_qa_e2e"
    authorizers = []
    real_init = qa_offline_pilot.QaPilotAuthorizer.__init__

    def register(self, *a, **k):
        real_init(self, *a, **k)
        authorizers.append(self)
    qa_offline_pilot.QaPilotAuthorizer.__init__ = register
    # the client sends the snapshot id as its context version, so the pilot grant pins that same value
    grant = S.grant_for(users["a"]["id"], context_version=str(S.SNAPSHOT))
    env = {} if args.mode == "off" else {"OFFLINE_QA_PILOT_ENABLED": "1", "OFFLINE_QA_PILOT_AUTH_ENABLED": "1", "OFFLINE_QA_PILOT_GRANTS": json.dumps([grant]),
                                         "OFFLINE_QA_PILOT_ALLOWED_ORIGINS": origin, "OFFLINE_QA_PILOT_SIGNING_SEED_B64URL": S.new_seed()}
    app = create_app_from_env(env, app_env="qa")
    state = {"lose": 0, "tamper": None}

    @app.middleware("http")
    async def disturb(request: Request, call_next):
        path = request.url.path
        response = await call_next(request)
        if request.method == "POST" and path == "/api/offline/captures" and state["lose"] > 0:
            state["lose"] -= 1
            async for _ in response.body_iterator:   # the server really processed it and persisted it ...
                pass
            return Response(status_code=504)         # ... but the browser never gets the answer
        if request.method == "POST" and state["tamper"] and path == {"scope": "/api/offline/scope", "package": "/api/offline/quality-package"}.get(state["tamper"]) and response.status_code == 200:
            body = b"".join([chunk async for chunk in response.body_iterator])
            doc = json.loads(body)
            sig = doc["signature_b64url"]
            doc["signature_b64url"] = ("A" if sig[0] != "A" else "B") + sig[1:]
            state["tamper"] = None
            return JSONResponse(doc, headers={"Cache-Control": "no-store"})
        return response

    def admin():
        return connect(name)

    @app.get("/__test__/info")
    def info():
        with admin() as c:
            return {"db": name, "receipts": c.execute("SELECT count(*) FROM vinto_offline.capture_receipt").fetchone()[0],
                    "events": c.execute("SELECT count(*) FROM vinto_offline.capture_event").fetchone()[0], "version": c.execute("SHOW server_version").fetchone()[0],
                    "app_role_identity_select": c.execute("SELECT has_table_privilege('vinto_app', 'vinto_auth.session', 'SELECT')").fetchone()[0]}

    @app.get("/__test__/receipts")
    def receipts():
        with admin() as c:
            rows = c.execute("SELECT capture_id::text, author_user_id::text, outcome, reason, server_seq FROM vinto_offline.capture_receipt ORDER BY server_seq").fetchall()
        return [{"capture_id": r[0], "author": r[1], "outcome": r[2], "reason": r[3], "seq": r[4]} for r in rows]

    @app.get("/__test__/events")
    def events():
        with admin() as c:
            rows = c.execute("SELECT capture_id::text, kind, detail FROM vinto_offline.capture_event ORDER BY id").fetchall()
        return [{"capture_id": r[0], "kind": r[1], "detail": r[2]} for r in rows]

    @app.get("/__test__/lose")
    def lose(n: int = 1):
        state["lose"] = n
        return {"ok": True}

    @app.get("/__test__/tamper")
    def tamper(target: str = "none"):
        state["tamper"] = target if target in ("scope", "package") else None
        return {"ok": True}

    @app.get("/__test__/session")
    def session(action: str, user: str = "a"):
        with admin() as c, c.transaction():
            c.execute("SET LOCAL session_replication_role = replica")   # bypasses the session-identity trigger ONLY in this throwaway database
            if action == "revoke":
                c.execute("UPDATE vinto_auth.session SET revoked_at = clock_timestamp() WHERE user_id = %s AND revoked_at IS NULL", (users[user]["id"],))
            elif action == "expire":
                c.execute("UPDATE vinto_auth.session SET created_at = clock_timestamp() - interval '2 hours', expires_at = clock_timestamp() - interval '1 hour' WHERE user_id = %s", (users[user]["id"],))
        return {"ok": True}

    @app.get("/__test__/repin")
    def repin(snapshot: str = ""):
        """Simulates a device whose scope is no longer the one the pilot grant authorises (a readiness-only snapshot): the grant is re-pinned elsewhere."""
        new = uuid.UUID(snapshot) if snapshot else uuid.uuid4()
        for a in authorizers:
            a.grants = tuple(g.model_copy(update={"scope_snapshot_id": new}) for g in a.grants)
        return {"ok": True}

    app.mount("/", StaticFiles(directory=args.public), name="public")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", access_log=False)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    import time
    while not server.started:
        time.sleep(0.05)
    print("READY " + json.dumps({"port": port, "origin": origin, "db": name, "mode": args.mode, "users": {k: {"id": str(v["id"]), "username": v["username"], "password": v["password"]} for k, v in users.items()}}), flush=True)
    try:
        sys.stdin.read()      # the harness closes stdin to stop the server
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        try:
            drop_database(name)
            drop_database(template)
        finally:
            S.drop_roles()


if __name__ == "__main__":
    main()
