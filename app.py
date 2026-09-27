"""Local THESIS interface. Start: python3 app.py, then open http://127.0.0.1:8765."""
import argparse
import json
import secrets
import threading
import webbrowser
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from runner import Application, mechanical_demo
from run_export import export_run


def handler(application, token, port):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log request bodies or credentials.

        def send(self, body, status=200, content_type="application/json", filename=None):
            data = body if isinstance(body, bytes) else body.encode() if isinstance(body, str) else json.dumps(body, allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type + "; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.send_header("Content-Length", str(len(data)))
            if filename:
                self.send_header('Content-Disposition', 'attachment; filename="' + filename + '"')
            self.end_headers()
            self.wfile.write(data)

        def valid_host(self):
            return self.headers.get("Host") in allowed_hosts

        def do_GET(self):
            if not self.valid_host():
                return self.send({"error": "Invalid host"}, 403)
            path = urllib.parse.urlsplit(self.path)
            try:
                if path.path == "/":
                    html = Path(__file__).with_name("interface.html").read_text()
                    return self.send(html.replace("__THESIS_CSRF__", token), content_type="text/html")
                if path.path == "/api/status":
                    return self.send(application.snapshot())
                if path.path == "/api/demo":
                    return self.send(mechanical_demo())
                if path.path in ("/research.js", "/research.css", "/journal.js", "/journal.css"):
                    suffix = path.path.rsplit(".", 1)[1]
                    return self.send(Path(__file__).with_name(path.path[1:]).read_text(),
                                     content_type="text/javascript" if suffix == "js" else "text/css")
                if path.path == "/api/review":
                    args = urllib.parse.parse_qs(path.query)
                    return self.send(application.reviews.get(args.get("id", [""])[0]))
                if path.path == "/api/export":
                    args = urllib.parse.parse_qs(path.query)
                    return self.send(application.ledger(args.get("symbol", ["RAAPLUSDT"])[0], args.get("kind", ["agent"])[0]))
                if path.path == "/api/export-run":
                    return self.send(export_run(application), content_type='application/zip', filename='THESIS-run-evidence.zip')
                return self.send({"error": "Not found"}, 404)
            except Exception as exc:
                return self.send({"error": str(exc)[:180] if isinstance(exc, ValueError) else type(exc).__name__}, 400)

        def do_POST(self):
            origin = self.headers.get("Origin", "")
            if not self.valid_host() or self.headers.get("X-Thesis-Token") != token or (origin and origin not in {"http://" + h for h in allowed_hosts}):
                return self.send({"error": "This page belongs to an earlier app session. Reload the page, then try again."}, 403)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 32768:
                    raise ValueError("Invalid request size")
                data = json.loads(self.rfile.read(length))
                if self.path == "/api/research-groq":
                    application.reviews.configure_groq(data.get("key", ""))
                elif self.path == "/api/model":
                    application.connect_model(data.get("endpoint", "").strip(), data.get("model", "").strip(), data.get("key", "").strip())
                elif self.path == "/api/observe":
                    application.job("observe")
                elif self.path == "/api/cycle":
                    application.job("cycle")
                elif self.path == "/api/start":
                    application.start()
                elif self.path == "/api/stop":
                    application.stop()
                elif self.path == "/api/review":
                    review_id = application.reviews.start(data.get("event_id"))
                    return self.send({"ok": True, "review_id": review_id})
                elif self.path == "/api/review-again":
                    review_id = application.reviews.recheck(data.get("review_id"))
                    return self.send({"ok": True, "review_id": review_id})
                elif self.path == "/api/review-assess":
                    review_id = application.reviews.assess(data.get("review_id"))
                    return self.send({"ok": True, "review_id": review_id})
                else:
                    return self.send({"error": "Unknown action"}, 404)
                return self.send({"ok": True})
            except Exception as exc:
                return self.send({"error": str(exc)[:180] if isinstance(exc, (ValueError, RuntimeError)) else type(exc).__name__}, 400)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", default="run-data")
    parser.add_argument("--open", action="store_true", help="Open the local workspace in the default browser")
    args = parser.parse_args()
    app = Application(args.data)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(app, secrets.token_urlsafe(32), args.port))
    print(f"THESIS is ready at http://127.0.0.1:{args.port} — paper trading only.", flush=True)
    if args.open:
        opener = threading.Timer(0.5, webbrowser.open, args=(f"http://127.0.0.1:{args.port}",))
        opener.daemon = True
        opener.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop()
        server.server_close()


if __name__ == "__main__":
    main()
