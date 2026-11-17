#!/usr/bin/env python3
"""Test-only HTTP root that serves OFF-02 public assets, not VINTO authenticated UI."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PUBLIC = Path(__file__).resolve().parent.parent / "public"
ROOT = b"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>VINTO OFF-02 public shell QA</title></head>
<body><h1>VINTO OFF-02 shell QA</h1><p>Only public assets; no credentials or production data.</p>
<script>window.addEventListener('load', () => { navigator.serviceWorker.register('/sw.js', {scope:'/'}) })</script>
</body></html>"""

class Handler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, ".webmanifest": "application/manifest+json"}
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(PUBLIC), **kwargs)
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(ROOT)))
            self.end_headers()
            self.wfile.write(ROOT)
            return
        super().do_GET()

if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
