"""Application services shared by the local HTTP boundary and other callers.

This module owns option validation, scene construction, single-run dispatch and
batch execution.  It deliberately has no HTTP, asset or browser dependency, so
the same contracts can be tested or reused without starting a server.
"""

from collections.abc import Mapping
from typing import Any

from agv.dispatch.registry import SOLVERS, run_named, validate_solver
from agv.domain import Scenario, example
from agv.evaluation.validation import validate
from agv.experiments.batch import run_batch
from agv.io.scenes import scenario_id, unpack_scene

__all__ = [
    "DEFAULTS",
    "generate_scene",
    "build_scene",
    "validate_options",
    "calculate",
    "calculate_loaded",
    "calculate_batch",
]


def generate_scene(
    profile: str = "legacy",
    *,
    seed: int = 0,
    task_count: int = 12,
    mode: str = "static",
    size: str | None = None,
    vehicles: int = 4,
    layout: str = "bottleneck",
    shelf_layers: int = 3,
    work_width: int = 2,
    obstacle_layout: str | None = None,
    layout_variant: int = 0,
    delivery_pattern: str = "distributed",
    arrival: str = "batch",
    demand: str = "balanced",
    horizon: int | None = None,
) -> Scenario:
    """Build one scene from an explicit profile, shared by CLI and HTTP callers."""
    if profile == "legacy":
        return example(
            mode=mode,
            layout=layout,
            seed=seed,
            task_count=task_count,
            vehicles=vehicles,
            size=size or "small",
            delivery_pattern=delivery_pattern,
            arrival=arrival,
            demand=demand,
            horizon=600 if horizon is None else horizon,
        )
    if profile == "v4":
        from agv.warehouse.layout import generate

        return generate(
            mode=mode,
            seed=seed,
            task_count=task_count,
            vehicles=vehicles,
            size=size or "small",
            delivery_pattern=delivery_pattern,
            arrival=arrival,
            demand=demand,
            horizon=horizon,
            work_width=work_width,
            obstacle_layout=obstacle_layout or "none",
            layout_variant=layout_variant,
            shelf_layers=shelf_layers,
        )
    if profile == "v9":
        from agv.warehouse.mixed import generate

        return generate(
            mode=mode,
            seed=seed,
            task_count=task_count,
            vehicles=vehicles,
            size=size or "medium",
            delivery_pattern=delivery_pattern,
            arrival=arrival,
            demand=demand,
            horizon=horizon,
            work_width=work_width,
            obstacle_layout=obstacle_layout or "columns_equipment",
            layout_variant=layout_variant,
            shelf_layers=shelf_layers,
        )
    if profile == "v9.1":
        from agv.warehouse.mixed import generate_current as generate

        return generate(
            mode=mode,
            seed=seed,
            task_count=task_count,
            vehicles=vehicles,
            size=size or "medium",
            delivery_pattern=delivery_pattern,
            arrival=arrival,
            demand=demand,
            horizon=horizon,
            work_width=work_width,
            obstacle_layout=obstacle_layout or "columns_equipment",
            layout_variant=layout_variant,
            shelf_layers=shelf_layers,
        )
    raise ValueError("Invalid scene profile")


DEFAULTS: dict[str, Any] = dict(
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


def validate_options(options: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(options, dict) or set(options) - set(DEFAULTS):
        raise ValueError("参数必须是包含已知字段的对象")
    v9_defaults = (
        dict(size="medium", obstacle_layout="columns_equipment")
        if options.get("profile") in ("v9", "v9.1")
        else {}
    )
    current_defaults = (
        dict(horizon=None, algorithm="sipp_stream_dispatch")
        if options.get("profile") == "v9.1"
        else {}
    )
    options = {**DEFAULTS, **v9_defaults, **current_defaults, **options}
    if options["profile"] not in ("legacy", "v4", "v9", "v9.1"):
        raise ValueError("Invalid scene profile")
    for name, minimum, maximum in [
        ("vehicles", 1, 10 if options["profile"] in ("v4", "v9", "v9.1") else 8),
        ("task_count", 0, 60),
        ("seed", 0, 999999),
        ("horizon", 60, 1800),
        (
            "shelf_layers",
            3 if options["profile"] in ("v9", "v9.1") else 1,
            8 if options["profile"] in ("v9", "v9.1") else 5,
        ),
        ("work_width", 2, 4),
        ("layout_variant", 0, 2),
    ]:
        if name == "horizon" and options["profile"] == "v9.1" and options[name] is None:
            continue
        if type(options[name]) is not int or not minimum <= options[name] <= maximum:
            raise ValueError(f"{name} 必须是 {minimum} 到 {maximum} 的整数")
    choices = dict(
        size=("medium", "large", "xlarge", "xxlarge")
        if options["profile"] in ("v9", "v9.1")
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
    if options["profile"] in ("v9", "v9.1") and options["obstacle_layout"] != "columns_equipment":
        raise ValueError("V9 requires its fixed columns and central equipment")
    validate_solver(options["algorithm"], options["profile"])
    return options


def calculate(options: Mapping[str, Any]) -> dict[str, Any]:
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


def build_scene(options: Mapping[str, Any]) -> Scenario:
    """One explicit scene profile; never reinterpret the legacy wall control."""
    return generate_scene(**{k: v for k, v in options.items() if k != "algorithm"})


def calculate_loaded(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("场景必须是JSON对象")
    raw = data.get("scenario", data)
    if not isinstance(raw, dict):
        raise ValueError("scenario必须是对象")
    if not isinstance(raw.get("map_info", {}), dict):
        raise ValueError("map_info必须是对象")
    # Resource limits are checked before expensive reachability/route checks.
    for field, limit in [("width", 96), ("height", 96), ("horizon", 1800)]:
        value = raw.get(field, 600 if field == "horizon" else None)
        if (
            field == "horizon"
            and value is None
            and raw.get("map_info", {}).get("model_version") == "mixed-v9.1"
        ):
            continue
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
    name = (config or {}).get(
        "algorithm", "sipp_stream_dispatch" if scenario.is_v9_1 else "baseline"
    )
    if not isinstance(name, str) or name not in SOLVERS:
        raise ValueError("algorithm必须是已注册的算法名称")
    result = run_named(name, scenario)
    validate(scenario, result)
    return dict(
        name="导入的固定场景",
        config=None,
        scenario=scenario.to_dict(),
        result=result,
        scenario_sha256=scenario_id(scenario),
    )


def calculate_batch(data: Mapping[str, Any]) -> dict[str, Any]:
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
    if config["profile"] in ("v4", "v9", "v9.1"):
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
