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

from tests.off044_support import FlakyStore, ScriptedContext, SyntheticAuthorizer, build_app, make_sqlite_store  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--disabled", action="store_true")
    args = ap.parse_args()
    store = FlakyStore(make_sqlite_store(args.db))
    authorizer, context = SyntheticAuthorizer(), ScriptedContext()
    app: FastAPI = build_app(store, enabled=not args.disabled, authorizer=authorizer, context=context)

    @app.post("/__test__/config")
    def config(body: dict):
        if "grants" in body:
            from uuid import UUID
            authorizer.grants = {(UUID(u), m, f) for u, m, f in body["grants"]}
        if "fail_next" in body:
            store.fail = int(body["fail_next"])
        return {"ok": True}

    @app.get("/__test__/stats")
    def stats():
        return store.inner.counts()

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
