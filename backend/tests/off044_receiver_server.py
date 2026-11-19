"""OFF-04.4 DISPOSABLE test server (CI / local scratch only): the isolated receiver behind a throwaway loopback uvicorn.

Synthetic principals come from the X-Synthetic-User header (absent = no session). Test-only control endpoints live under
/__test__/ and exist ONLY in this script, never in the receiver package or the operational app. Binds 127.0.0.1 and prints
`PORT=<n>` once ready. It never reads DATABASE_URL and never touches a deployed API.
"""
import argparse
import os
import socket
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from tests.off044_support import FlakyStore, ScriptedContext, SyntheticAuthorizer, build_app, make_pg_store, make_sqlite_store  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--disabled", action="store_true")
    ap.add_argument("--store", choices=["sqlite", "pg"], default="sqlite", help="pg = a throwaway *_test PostgreSQL database (OFF044_PG_URL or a user-space instance)")
    ap.add_argument("--cors-origin", action="append", default=[], help="origin of a browser page that may call this DISPOSABLE server (loopback only)")
    args = ap.parse_args()
    inner = make_pg_store() if args.store == "pg" else make_sqlite_store(args.db)
    store = FlakyStore(inner)
    authorizer, context = SyntheticAuthorizer(), ScriptedContext()
    app: FastAPI = build_app(store, enabled=not args.disabled, authorizer=authorizer, context=context)
    if args.cors_origin:
        from fastapi.middleware.cors import CORSMiddleware
        assert all(o.startswith(("http://127.0.0.1", "http://localhost")) for o in args.cors_origin), "loopback origins only"
        app.add_middleware(CORSMiddleware, allow_origins=args.cors_origin, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["Content-Type", "X-Synthetic-User"])

    @app.post("/__test__/config")
    def config(body: dict):
        if "grants" in body:
            from uuid import UUID
            authorizer.grants = {(UUID(u), m, f) for u, m, f in body["grants"]}
        if "context_default" in body:
            context.default = str(body["context_default"])
        if "context" in body:
            context.table.update({str(k): str(v) for k, v in body["context"].items()})
        if "fail_next" in body:
            store.fail = int(body["fail_next"])
        return {"ok": True}

    @app.get("/__test__/stats")
    def stats():
        inner_store = store.inner
        if hasattr(inner_store, "counts"):
            return inner_store.counts()
        with inner_store.transaction() as tx:
            return {"receipts": tx.c.execute("SELECT count(*) FROM vinto_offline.capture_receipt").fetchone()[0],
                    "events": tx.c.execute("SELECT count(*) FROM vinto_offline.capture_event").fetchone()[0]}

    @app.get("/__test__/receipts")
    def receipts():
        with store.inner.transaction() as tx:
            if hasattr(store.inner, "counts"):
                rows = tx.c.execute("SELECT capture_id, author_user_id, outcome, reason, server_seq FROM capture_receipt ORDER BY server_seq").fetchall()
            else:
                rows = tx.c.execute("SELECT capture_id::text, author_user_id::text, outcome, reason, server_seq FROM vinto_offline.capture_receipt ORDER BY server_seq").fetchall()
        return [{"capture_id": str(r[0]), "author": str(r[1]), "outcome": r[2], "reason": r[3], "seq": r[4]} for r in rows]

    @app.get("/__test__/db")
    def db():
        if hasattr(store.inner, "counts"):
            return {"engine": "sqlite"}
        with store.inner.transaction() as tx:
            return {"engine": "postgresql", "version": tx.c.execute("SHOW server_version").fetchone()[0],
                    "database": tx.c.execute("SELECT current_database()").fetchone()[0]}

    @app.get("/__test__/events")
    def events():
        with store.inner.transaction() as tx:
            if hasattr(store.inner, "counts"):
                rows = tx.c.execute("SELECT capture_id, kind FROM capture_event ORDER BY id").fetchall()
            else:
                rows = tx.c.execute("SELECT capture_id::text, kind FROM vinto_offline.capture_event ORDER BY id").fetchall()
        return [{"capture_id": str(r[0]), "kind": r[1]} for r in rows]

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error"))
    threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True).start()
    while not server.started:
        pass
    print(f"PORT={port}", flush=True)
    try:
        sys.stdin.read()          # parent closes stdin (or kills us) to stop the server
    finally:
        server.should_exit = True


if __name__ == "__main__":
    main()
