"""Local web server.
Listens on 127.0.0.1. Pages get the scores pushed over a server-sent-event stream.
"""
import json
import logging
import mimetypes
import secrets
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from . import APP_NAME, paths

log = logging.getLogger(__name__)

BUNDLED_FONTS = {"race": "RacersDelight.otf", "fallback": "MPLUS1p-ExtraBold.ttf", "score": "MPLUS1p-ExtraBold.ttf"}
KEEPALIVE_SECONDS = 15
PORT_TRIES = 10
mimetypes.add_type("font/otf", ".otf")
mimetypes.add_type("font/ttf", ".ttf")
mimetypes.add_type("text/javascript", ".js")


class AlreadyRunning(Exception):
    pass


class _Server(ThreadingHTTPServer):
    allow_reuse_address = False
    daemon_threads = True


FONTS_CSS = (
    '@font-face{font-family:"MKRace";src:url("/font/race");font-display:block;font-style:italic;size-adjust:128%;}\n'
    '@font-face{font-family:"MKFallback";src:url("/font/fallback");font-display:block;font-style:normal;}\n'
    '@font-face{font-family:"MKScore";src:url("/font/score");font-display:block;font-style:normal;}\n'
)


def _make_handler(controller, token):
    web = Path(paths.resource("web")).resolve()

    class Handler(BaseHTTPRequestHandler):
        server_version = "MogiTracker"

        def log_message(self, *_):   # keep console quiet
            pass

        # helpers
        def _local(self):
            host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
            return host in ("127.0.0.1", "localhost")

        def _send(self, code, body=b"", ctype="text/plain; charset=utf-8", cache="no-store"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", cache)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _file(self, path: Path, cache="no-store"):
            try:
                body = path.read_bytes()
            except OSError:
                return self._send(404, b"not found")
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype == "application/json":
                ctype += "; charset=utf-8"
            self._send(200, body, ctype, cache)

        # routes
        def do_GET(self):
            if not self._local():
                return self._send(403, b"forbidden")
            path = urlparse(self.path).path
            if path == "/":
                page = (web / "index.html").read_text(encoding="utf-8").replace("__TOKEN__", token)
                return self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/overlay":
                return self._file(web / "overlay.html")
            if path == "/api/ping":
                return self._json({"app": APP_NAME, "run": RUN})
            if path == "/api/state":
                return self._json(controller.state())
            if path == "/api/events":
                return self._events()
            if path == "/fonts.css":
                return self._send(200, FONTS_CSS.encode("utf-8"), "text/css; charset=utf-8")
            if path.startswith("/font/"):
                role = path[len("/font/"):]
                if role not in BUNDLED_FONTS:
                    return self._send(404, b"not found")
                return self._file(web / "fonts" / BUNDLED_FONTS[role], cache="max-age=86400")
            if path.startswith("/static/"):
                target = (web / path[len("/static/"):]).resolve()
                if web in target.parents and target.is_file():
                    return self._file(target)
            self._send(404, b"not found")

        def do_POST(self):
            if not self._local() or not secrets.compare_digest(self.headers.get("X-Token") or "", token):
                return self._send(403, b"forbidden")
            path = urlparse(self.path).path
            if not path.startswith("/api/"):
                return self._send(404, b"not found")
            try:
                length = int(self.headers.get("Content-Length") or 0)
                data = json.loads(self.rfile.read(length) or b"{}") if length else {}
                if not isinstance(data, dict):
                    raise ValueError("body must be an object")
            except ValueError:
                return self._send(400, b"bad request")
            try:
                self._json(controller.act(path[len("/api/"):], data))
            except Exception as e:
                log.exception("action %s failed", path)
                self._json({"ok": False, "error": str(e)}, 500)

        def _events(self):
            """Push the state now and again whenever it changes, until the page goes away."""
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            seen = -1
            try:
                while True:
                    with controller.changed_cond:
                        if controller.version == seen:
                            controller.changed_cond.wait(KEEPALIVE_SECONDS)
                        version = controller.version
                    if version == seen:
                        self.wfile.write(b": keepalive\n\n")
                    else:
                        seen = version
                        payload = json.dumps(controller.state(), ensure_ascii=False)
                        self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionError, OSError):
                pass

    return Handler


# Create an always-present file so you don't have to start the tracker before OBS
_OVERLAY_FILE = """<!doctype html>
<meta charset="utf-8">
<title>Mogi Tracker Overlay</title>
<style>
  html, body { margin: 0; height: 100%; overflow: hidden; background: transparent; }
  iframe { display: block; width: 100%; height: 100%; border: 0; background: transparent; visibility: hidden; }
</style>
<iframe id="overlay" allowtransparency="true"></iframe>
<script>
  const frame = document.getElementById("overlay"), url = __URL__;
  let ready = false;
  addEventListener("message", (e) => {
    if (e.data === "mkw-overlay-ready") { ready = true; frame.style.visibility = "visible"; }
  });
  function attempt() { if (!ready) frame.src = url + "?t=" + Date.now(); }
  frame.addEventListener("load", () => setTimeout(attempt, 3000));
  attempt();
</script>
"""


def write_overlay_file(port):
    path = paths.data_dir() / "overlay.html"
    try:
        path.write_text(_OVERLAY_FILE.replace("__URL__", json.dumps(f"http://127.0.0.1:{port}/overlay")),
                        encoding="utf-8")
    except OSError as e:
        log.warning("could not write the overlay file: %s", e)
    return path


RUN = secrets.token_hex(4)


def _is_ours(port) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/ping", timeout=1) as r:
            return json.loads(r.read()).get("app") == APP_NAME
    except Exception:
        return False


def start(controller):
    token = secrets.token_urlsafe(24)
    handler = _make_handler(controller, token)
    first = controller.settings["port"]
    for port in range(first, first + PORT_TRIES):
        try:
            server = _Server(("127.0.0.1", port), handler)
        except OSError:
            if _is_ours(port):
                raise AlreadyRunning()
            continue
        controller.port = port
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server, f"http://127.0.0.1:{port}/"
    raise OSError(f"No free port between {first} and {first + PORT_TRIES - 1}.")
