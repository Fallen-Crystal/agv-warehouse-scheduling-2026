"""算法无关的数据模型。时间、距离采用离散单位。"""

import random
from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass
from dataclasses import field as dataclass_field

Point = tuple[int, int]


@dataclass(frozen=True)
class Task:
    id: int
    pickup: Point | None
    delivery: Point
    release: int = 0
    pickup_service: int = 1
    delivery_service: int = 1
    shelf: Point | None = None
    shelf_level: int = 1


@dataclass
class Scenario:
    width: int
    height: int
    blocked: set[Point]
    shelves: set[Point]
    homes: list[Point]
    tasks: list[Task]
    horizon: int | None = 600
    service_axis: str = "any"
    pickup_zones: set[Point] = dataclass_field(default_factory=set)
    transit_only: set[Point] = dataclass_field(default_factory=set)
    stations: list[Point] = dataclass_field(default_factory=list)
    map_info: dict = dataclass_field(default_factory=dict)

    @property
    def is_v4(self):
        return self.map_info.get("model_version") == "math-v4-integrated"

    @property
    def is_v9(self):
        return self.map_info.get("model_version") == "mixed-v9"

    @property
    def uses_layer_rules(self):
        return self.is_v4 or self.is_v9

    def free(self, p):
        return 0 <= p[0] < self.width and 0 <= p[1] < self.height and p not in self.blocked

    def neighbors(self, p):
        x, y = p
        for q in ((x + 1, y), (x, y + 1), (x - 1, y), (x, y - 1)):
            if self.free(q):
                yield q

    def travel_neighbors(self, p, delivery_goal=None):
        """A V4 delivery station may be entered only for its designated delivery."""
        for q in self.neighbors(p):
            if self.uses_layer_rules and q in self.stations and q != delivery_goal:
                continue
            yield q

    def pickup_candidates(self, job):
        if job.shelf is None:
            return [job.pickup]
        if self.is_v9:
            row = next(
                (v for v in self.map_info["rack_catalog"] if tuple(v["position"]) == job.shelf),
                None,
            )
            return [tuple(p) for p in row["loading_points"]] if row else []
        return sorted(
            p
            for p in self.neighbors(job.shelf)
            if p not in self.homes
            and (not self.is_v4 or (p[0] == job.shelf[0] and p in self.pickup_zones))
        )

    def check(self):
        def require(ok, message):
            if not ok:
                raise ValueError(message)

        def integer(v):
            return type(v) is int

        def point(p):
            return isinstance(p, (tuple, list)) and len(p) == 2 and all(integer(v) for v in p)

        require(
            integer(self.width) and integer(self.height) and self.width > 0 and self.height > 0,
            "Invalid dimensions",
        )
        require(
            self.horizon is None or (integer(self.horizon) and self.horizon > 0),
            "Invalid horizon",
        )
        require(isinstance(self.map_info, dict), "map_info must be an object")
        from agv.warehouse.rules import validate_profile

        require(bool(self.homes) and len(set(self.homes)) == len(self.homes), "Need distinct homes")
        require(self.shelves <= self.blocked, "Shelves must be blocked")
        for p in self.blocked | set(self.homes):
            require(
                point(p) and 0 <= p[0] < self.width and 0 <= p[1] < self.height, "Invalid map point"
            )
        require(all(self.free(p) for p in self.homes), "Blocked home")
        validate_profile(self)
        require(all(integer(j.id) for j in self.tasks), "Task IDs must be integers")
        require(len({j.id for j in self.tasks}) == len(self.tasks), "Duplicate task ID")
        reach_cache = {}
        catalog = {tuple(row["position"]): row for row in self.map_info.get("rack_catalog", [])}
        for j in self.tasks:
            require(integer(j.release) and j.release >= 0, "Invalid release")
            require(integer(j.shelf_level) and j.shelf_level >= 1, "Invalid shelf level")
            if self.uses_layer_rules:
                row = catalog.get(j.shelf) if point(j.shelf) else None
                require(row is not None, "Layered orders must specify a catalog shelf")
                require(j.shelf_level <= row["levels"], "Shelf level exceeds this bay's layers")
                require(
                    j.pickup_service == 2 * j.shelf_level and j.delivery_service == 1,
                    "Layered service duration must be 2*level and unload 1",
                )
                require(j.delivery in self.stations, "Layered delivery must be a specified station")
                require(j.shelf is not None, "Layered orders must specify a shelf")
            else:
                require(j.shelf_level == 1, "Shelf layers require an explicit warehouse profile")
            require(
                all(integer(s) and s >= 1 for s in (j.pickup_service, j.delivery_service)),
                "Invalid service duration",
            )
            require(
                point(j.delivery) and self.free(j.delivery) and j.delivery not in self.homes,
                "Invalid delivery point",
            )
            if j.shelf is not None:
                require(point(j.shelf) and j.shelf in self.shelves, "Target must be a shelf cell")
                require(j.pickup is None, "Shelf task must not fix pickup point")
                require(bool(self.pickup_candidates(j)), "No legal pickup neighbor")
            else:
                require(
                    j.pickup is not None
                    and point(j.pickup)
                    and self.free(j.pickup)
                    and j.pickup not in self.homes,
                    "Invalid service point",
                )
                require(
                    any(
                        abs(j.pickup[0] - p[0]) + abs(j.pickup[1] - p[1]) == 1 for p in self.shelves
                    ),
                    "Pickup must neighbor a shelf",
                )
            # 至少一辆车能完成整个任务；他车停车位属于禁止通行节点。
            reachable = False
            for k, home in enumerate(self.homes):
                forbidden = set(self.homes) - {home}
                if k not in reach_cache:
                    seen, queue = {home}, deque([home])
                    while queue:
                        for p in self.travel_neighbors(queue.popleft()):
                            if p not in seen and p not in forbidden:
                                seen.add(p)
                                queue.append(p)
                    reach_cache[k] = seen
                seen = reach_cache[k]
                delivery_reachable = (
                    any(p in seen for p in self.neighbors(j.delivery))
                    if self.uses_layer_rules
                    else j.delivery in seen
                )
                reachable |= (
                    any(p in seen for p in self.pickup_candidates(j)) and delivery_reachable
                )
            require(reachable, f"Unreachable task {j.id}")
        return self

    def to_dict(self):
        tasks = [asdict(j) for j in self.tasks]
        if not self.uses_layer_rules:
            for job in tasks:
                job.pop("shelf_level")
        data = dict(
            width=self.width,
            height=self.height,
            blocked=sorted(self.blocked),
            shelves=sorted(self.shelves),
            homes=self.homes,
            horizon=self.horizon,
            tasks=tasks,
        )
        if self.uses_layer_rules:
            data.update(
                service_axis=self.service_axis,
                pickup_zones=sorted(self.pickup_zones),
                transit_only=sorted(self.transit_only),
                stations=list(self.stations),
                map_info=deepcopy(self.map_info),
            )
        return data

    def observation_map(self):
        """Static public geometry only; no task generator state or evaluation reference."""
        data = dict(
            width=self.width,
            height=self.height,
            blocked=sorted(self.blocked),
            shelves=sorted(self.shelves),
            homes=list(self.homes),
        )
        if self.uses_layer_rules:
            data.update(
                service_axis=self.service_axis,
                pickup_zones=sorted(self.pickup_zones),
                transit_only=sorted(self.transit_only),
                stations=list(self.stations),
                map_info=deepcopy(self.map_info),
            )
        return data

    @classmethod
    def from_observation_map(cls, data, horizon=600):
        if not isinstance(data, dict) or "tasks" in data or "horizon" in data:
            raise ValueError("Observation map must contain static geometry only")
        return cls.from_dict({**deepcopy(data), "tasks": [], "horizon": horizon})

    @classmethod
    def from_dict(cls, data):
        """Validate JSON shape before constructing hashable coordinates/jobs."""
        required = {"width", "height", "blocked", "shelves", "homes", "tasks"}
        profile_fields = {"service_axis", "pickup_zones", "transit_only", "stations", "map_info"}
        if (
            not isinstance(data, dict)
            or not required <= set(data)
            or set(data) - required - {"horizon"} - profile_fields
        ):
            raise ValueError("Scenario must contain the documented fields only")
        for field in ("width", "height", "horizon"):
            if field == "horizon" and data.get(field, 600) is None:
                continue
            if type(data.get(field, 600)) is not int:
                raise ValueError(f"{field} must be an integer")
        info = data.get("map_info", {})
        if not isinstance(info, dict):
            raise ValueError("map_info must be an object")
        is_layered = info.get("model_version") in ("math-v4-integrated", "mixed-v9")
        if profile_fields & set(data) and not is_layered:
            raise ValueError("Extended scene fields require an explicit V4/V9 profile")
        if is_layered and not profile_fields <= set(data):
            raise ValueError("Layered scene is missing profile fields")

        def coordinate(value, label):
            if (
                not isinstance(value, (tuple, list))
                or len(value) != 2
                or any(type(x) is not int for x in value)
            ):
                raise ValueError(f"{label} must be two integer coordinates")
            return tuple(value)

        coordinates = {}
        for field in (
            "blocked",
            "shelves",
            "homes",
            *(("pickup_zones", "transit_only", "stations") if is_layered else ()),
        ):
            if not isinstance(data[field], (tuple, list)):
                raise ValueError(f"{field} must be a list")
            coordinates[field] = [coordinate(p, field) for p in data[field]]
        if not isinstance(data["tasks"], list):
            raise ValueError("tasks must be a list")
        tasks = []
        allowed = {
            "id",
            "pickup",
            "delivery",
            "release",
            "pickup_service",
            "delivery_service",
            "shelf",
        }
        if is_layered:
            allowed.add("shelf_level")
        for raw in data["tasks"]:
            if (
                not isinstance(raw, dict)
                or not {"id", "delivery"} <= set(raw)
                or set(raw) - allowed
            ):
                raise ValueError("Invalid task fields")
            if type(raw["id"]) is not int:
                raise ValueError("Task ID must be an integer")
            for field in ("release", "pickup_service", "delivery_service", "shelf_level"):
                if type(raw.get(field, 0 if field == "release" else 1)) is not int:
                    raise ValueError(f"Task {field} must be an integer")
            item = dict(raw)
            for field in ("pickup", "shelf"):
                item[field] = coordinate(raw[field], field) if raw.get(field) is not None else None
            item["delivery"] = coordinate(raw["delivery"], "delivery")
            tasks.append(Task(**item))
        return cls(
            data["width"],
            data["height"],
            set(coordinates["blocked"]),
            set(coordinates["shelves"]),
            coordinates["homes"],
            tasks,
            data.get("horizon", 600),
            service_axis=data.get("service_axis", "any"),
            pickup_zones=set(coordinates.get("pickup_zones", [])),
            transit_only=set(coordinates.get("transit_only", [])),
            stations=coordinates.get("stations", []),
            map_info=deepcopy(info),
        ).check()


def example(
    mode="static",
    layout="bottleneck",
    seed=0,
    task_count=12,
    vehicles=4,
    size="small",
    delivery_pattern="distributed",
    arrival="batch",
    demand="balanced",
    horizon=600,
):
    if mode not in ("static", "dynamic") or layout not in ("wide", "bottleneck"):
        raise ValueError("Unknown mode or layout")
    if type(task_count) is not int or task_count < 0:
        raise ValueError("task_count must be a nonnegative integer")
    if type(vehicles) is not int or not 1 <= vehicles <= 8:
        raise ValueError("vehicles must be an integer from 1 to 8")
    if type(seed) is not int or seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    if arrival not in ("batch", "uniform", "irregular", "burst"):
        raise ValueError("Unknown arrival pattern")
    if demand not in ("balanced", "left_hotspot", "right_hotspot", "switching"):
        raise ValueError("Unknown demand pattern")
    sizes = {"small": (13, 11), "medium": (19, 15), "large": (25, 19)}
    if size not in sizes or delivery_pattern not in ("distributed", "shared"):
        raise ValueError("Unknown size or delivery pattern")
    width, height = sizes[size]
    middle = height // 2
    rng = random.Random(seed)
    shelf_rng = random.Random(seed ^ 0x54E1F)
    # 到达、需求偏置、基础位置使用独立随机流，改变到达模式不改变任务位置。
    arrival_rng = random.Random(seed ^ 0xA771A1)
    demand_rng = random.Random(seed ^ 0xD3A4AD)
    releases = []
    current_release = 0
    for j in range(task_count):
        if arrival == "batch":
            current_release = (j // 3) * 15
        elif arrival == "uniform":
            current_release = j * 5
        elif arrival == "irregular":
            current_release = 0 if j == 0 else current_release + arrival_rng.randint(1, 9)
        else:
            current_release = (j // 6) * 30
        releases.append(0 if mode == "static" else current_release)
    all_homes = [
        (2, 0),
        (4, 0),
        (width - 5, 0),
        (width - 3, 0),
        (1, 0),
        (width - 2, 0),
        (width // 2 - 1, 0),
        (width // 2 + 1, 0),
    ]
    homes = [all_homes[0], all_homes[2]] if vehicles == 2 else all_homes[:vehicles]
    shelf_columns = (3, 9, 15, 21) if size == "large" else (3, width - 4)
    shelves = {(x, y) for x in shelf_columns for y in range(3, height - 2)}
    blocked = shelves | {(x, 0) for x in range(width) if (x, 0) not in homes}
    gates = {middle} if layout == "bottleneck" else {3, middle, height - 4}
    blocked |= {(width // 2, y) for y in range(1, height) if y not in gates}
    jobs = []
    for j in range(task_count):
        side = rng.randrange(2)
        if demand != "balanced":
            hot_side = (
                1
                if demand == "right_hotspot"
                or (demand == "switching" and j >= (task_count + 1) // 2)
                else 0
            )
            side = hot_side if demand_rng.random() < 0.8 else 1 - hot_side
        pickup = (
            rng.choice((2, 4) if side == 0 else (width - 5, width - 3)),
            rng.randrange(3, height - 2),
        )
        delivery = (rng.choice((1, width - 2)), rng.choice((2, height - 2)))
        if delivery_pattern == "shared":
            delivery = (1, middle)
        # 保留位置随机流的抽样顺序，订单目标改为对应货架格，不固定停靠侧。
        shelf = (3 if side == 0 else width - 4, pickup[1])
        if size == "large":
            shelf = (shelf_rng.choice((3, 9) if side == 0 else (15, 21)), pickup[1])
        jobs.append(Task(j, None, delivery, releases[j], shelf=shelf))
    return Scenario(width, height, blocked, shelves, homes, jobs, horizon).check()
