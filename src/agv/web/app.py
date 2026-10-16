"""Local warehouse viewer: validated API, packaged templates and static assets."""

import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore

from agv.dispatch.registry import SOLVERS, run_named
from agv.domain import example
from agv.evaluation.validation import validate
from agv.experiments.batch import run_batch
from agv.io.scenes import scenario_id, unpack_scene

_LOG = logging.getLogger(__name__)
_ASSETS = Path(__file__).resolve().parent
DEFAULTS = dict(
    profile="legacy",
    size="small",
    vehicles=4,
    layout="bottleneck",
    mode="static",
    arrival="batch",
    demand="balanced",
    delivery_pattern="distributed",
    task_count=12,
    seed=0,
    horizon=600,
    algorithm="baseline",
    shelf_layers=3,
    work_width=2,
    obstacle_layout="none",
    layout_variant=0,
)


def validate_options(options):
    if not isinstance(options, dict) or set(options) - set(DEFAULTS):
        raise ValueError("参数必须是包含已知字段的对象")
    v9_defaults = (
        dict(size="medium", obstacle_layout="columns_equipment")
        if options.get("profile") == "v9"
        else {}
    )
    options = {**DEFAULTS, **v9_defaults, **options}
    if options["profile"] not in ("legacy", "v4", "v9"):
        raise ValueError("Invalid scene profile")
    for name, minimum, maximum in [
        ("vehicles", 1, 10 if options["profile"] in ("v4", "v9") else 8),
        ("task_count", 0, 60),
        ("seed", 0, 999999),
        ("horizon", 60, 1800),
        (
            "shelf_layers",
            3 if options["profile"] == "v9" else 1,
            8 if options["profile"] == "v9" else 5,
        ),
        ("work_width", 2, 4),
        ("layout_variant", 0, 2),
    ]:
        if type(options[name]) is not int or not minimum <= options[name] <= maximum:
            raise ValueError(f"{name} 必须是 {minimum} 到 {maximum} 的整数")
    choices = dict(
        size=("medium", "large", "xlarge", "xxlarge")
        if options["profile"] == "v9"
        else ("small", "medium", "large", "xlarge", "xxlarge")
        if options["profile"] == "v4"
        else ("small", "medium", "large"),
        layout=("wide", "bottleneck"),
        mode=("static", "dynamic"),
        arrival=("batch", "uniform", "irregular", "burst"),
        demand=("balanced", "left_hotspot", "right_hotspot", "switching"),
        delivery_pattern=("distributed", "shared"),
        algorithm=tuple(SOLVERS),
        obstacle_layout=("none", "columns", "columns_equipment"),
    )
    for name, allowed in choices.items():
        if options[name] not in allowed:
            raise ValueError(f"Invalid {name}: {options[name]!r}")
    if options["profile"] == "v9" and options["obstacle_layout"] != "columns_equipment":
        raise ValueError("V9 requires its fixed columns and central equipment")
    if "standby" in options["algorithm"] and options["profile"] != "v9":
        raise ValueError("Bounded standby requires V9")
    return options


def calculate(options):
    options = validate_options(options)
    scenario = build_scene(options)
    result = run_named(options["algorithm"], scenario)
    validate(scenario, result)
    return dict(
        name="自选场景",
        config=options,
        scenario=scenario.to_dict(),
        result=result,
        scenario_sha256=scenario_id(scenario),
    )


def build_scene(options):
    """One explicit scene profile; never reinterpret the legacy wall control."""
    if options["profile"] in ("v4", "v9"):
        if options["profile"] == "v9":
            from agv.warehouse.mixed import generate
        else:
            from agv.warehouse.layout import generate

        return generate(
            **{k: v for k, v in options.items() if k not in ("profile", "algorithm", "layout")}
        )
    return example(
        **{
            k: v
            for k, v in options.items()
            if k
            not in (
                "profile",
                "algorithm",
                "shelf_layers",
                "work_width",
                "obstacle_layout",
                "layout_variant",
            )
        }
    )


def calculate_loaded(data):
    if not isinstance(data, dict):
        raise ValueError("场景必须是JSON对象")
    raw = data.get("scenario", data)
    if not isinstance(raw, dict):
        raise ValueError("scenario必须是对象")
    # Resource limits are checked before expensive reachability/route checks.
    for field, limit in [("width", 96), ("height", 96), ("horizon", 1800)]:
        value = raw.get(field, 600 if field == "horizon" else None)
        if type(value) is not int or not 1 <= value <= limit:
            raise ValueError(
                "页面导入限制：地图不超过96×96、10辆车、60单、1800步；无截止场景请使用CLI"
            )
    if (
        not isinstance(raw.get("tasks"), list)
        or len(raw["tasks"]) > 60
        or not isinstance(raw.get("homes"), list)
        or len(raw["homes"]) > 10
    ):
        raise ValueError("页面导入限制：地图不超过96×96、10辆车、60单、1800步")
    scenario = unpack_scene(data)
    if any(j.shelf is None for j in scenario.tasks):
        raise ValueError("新版页面只接受指定货架格的订单；旧固定取货点文件请使用旧版打开。")
    config = data.get("config")
    if config is not None and not isinstance(config, dict):
        raise ValueError("config必须是对象或null")
    name = (config or {}).get("algorithm", "baseline")
    result = run_named(name, scenario)
    validate(scenario, result)
    return dict(
        name="导入的固定场景",
        config=None,
        scenario=scenario.to_dict(),
        result=result,
        scenario_sha256=scenario_id(scenario),
    )


def calculate_batch(data):
    if not isinstance(data, dict) or set(data) != {"config", "start_seed", "count"}:
        raise ValueError("批量参数不合法")
    start, count = data["start_seed"], data["count"]
    if (
        type(start) is not int
        or type(count) is not int
        or not 1 <= count <= 20
        or not 0 <= start <= 999999 - count + 1
    ):
        raise ValueError("批量数量1～20，起始种子需保证全部种子不超过999999")
    config = validate_options(data["config"])
    name = config.pop("algorithm")
    if config["profile"] in ("v4", "v9"):
        from agv.experiments.v4 import run_web_batch

        return run_web_batch(config, range(start, start + count), name)
    config = {
        k: v
        for k, v in config.items()
        if k not in ("profile", "shelf_layers", "work_width", "obstacle_layout", "layout_variant")
    }
    from agv.dispatch.greedy import greedy_action

    return run_batch(
        config,
        range(start, start + count),
        policies={name: greedy_action},
        runners={name: lambda scenario: run_named(name, scenario)},
    )


def make_html(initial=None, *, inline_assets=True):
    html = (_ASSETS / "templates/index.html").read_text(encoding="utf-8")
    if inline_assets:
        style = "<style>" + (_ASSETS / "static/style.css").read_text(encoding="utf-8") + "</style>"
        script = "<script>" + (_ASSETS / "static/app.js").read_text(encoding="utf-8") + "</script>"
    else:
        style = '<link rel="stylesheet" href="/assets/style.css">'
        script = '<script src="/assets/app.js" defer></script>'
    encoded = json.dumps([initial or calculate({})], ensure_ascii=False, allow_nan=False).replace(
        "</", r"<\/"
    )
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
