"""Local warehouse viewer: validated API, packaged templates and static assets."""

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore

from agv.api import (
    DEFAULTS,
    build_scene,
    calculate,
    calculate_batch,
    calculate_loaded,
    validate_options,
)

_LOG = logging.getLogger(__name__)
_ASSETS = Path(__file__).resolve().parent

__all__ = [
    "DEFAULTS",
    "build_scene",
    "calculate",
    "calculate_batch",
    "calculate_loaded",
    "validate_options",
    "make_html",
    "create_server",
]


def make_html(initial=None, *, inline_assets=True):
    html = (_ASSETS / "templates/index.html").read_text(encoding="utf-8")
    if inline_assets:
        style = "<style>" + (_ASSETS / "static/style.css").read_text(encoding="utf-8") + "</style>"
        script = "<script>" + (_ASSETS / "static/app.js").read_text(encoding="utf-8") + "</script>"
    else:
        style = '<link rel="stylesheet" href="/assets/style.css">'
        script = '<script src="/assets/app.js" defer></script>'
    encoded = json.dumps(
        [initial or calculate(dict(profile="v9.1"))], ensure_ascii=False, allow_nan=False
    ).replace("</", r"<\/")
    return (
        html.replace("__STYLE__", style).replace("__DATA__", encoded).replace("__SCRIPT__", script)
    )


class ViewerServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 8

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(10)
        return connection, address


def create_server(host="127.0.0.1", port=0):
    if host != "127.0.0.1":
        raise ValueError("Viewer is local-only; host must be 127.0.0.1")
    html = make_html(inline_assets=False).encode("utf-8")
    assets = {
        "/assets/app.js": (
            (_ASSETS / "static/app.js").read_bytes(),
            "text/javascript; charset=utf-8",
        ),
        "/assets/style.css": (
            (_ASSETS / "static/style.css").read_bytes(),
            "text/css; charset=utf-8",
        ),
    }
    gate = BoundedSemaphore(1)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            _LOG.debug(fmt, *args)

        def send(self, code, body, kind="application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def error(self, code, message):
            self.send(code, json.dumps(dict(error=message), ensure_ascii=False).encode())

        def do_GET(self):
            if self.path in ("/", "/index.html"):
                self.send(200, html, "text/html; charset=utf-8")
            elif self.path in assets:
                body, kind = assets[self.path]
                self.send(200, body, kind)
            else:
                self.error(404, "not found")

        def do_POST(self):
            if self.path not in ("/api/run", "/api/load", "/api/batch"):
                self.error(404, "not found")
                return
            # Validate Host as well as Origin, including requests without Origin.
            if self.headers.get("Host") != f"127.0.0.1:{self.server.server_port}":
                self.error(403, "host rejected")
                return
            origin = self.headers.get("Origin")
            if origin and origin != "http://" + self.headers["Host"]:
                self.error(403, "origin rejected")
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self.error(415, "expected application/json")
                return
            if self.headers.get("Transfer-Encoding"):
                self.error(400, "transfer encoding is unsupported")
                return
            if not gate.acquire(blocking=False):
                self.error(429, "Simulation busy; retry after the current run")
                return
            try:
                limit = 10 * 1024 * 1024 if self.path == "/api/load" else 4096
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= limit:
                    raise ValueError("请求长度不合法")
                payload = self.rfile.read(length)
                if len(payload) != length:
                    raise ValueError("请求正文不完整")
                options = json.loads(payload)
                fn = {
                    "/api/run": calculate,
                    "/api/load": calculate_loaded,
                    "/api/batch": calculate_batch,
                }[self.path]
                entry = fn(options)
                self.send(200, json.dumps(entry, ensure_ascii=False, allow_nan=False).encode())
            except (ValueError, TypeError, KeyError, OverflowError) as error:
                self.error(400, str(error))
            except TimeoutError:
                self.error(408, "Request timed out")
            except Exception:
                _LOG.exception("Unexpected simulation failure")
                self.error(500, "Internal simulation error; see the local server log")
            finally:
                gate.release()

    return ViewerServer((host, port), Handler)


def main():
    from agv.cli import main as cli_main

    return cli_main(["serve"])
