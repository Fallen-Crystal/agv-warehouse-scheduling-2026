"""MovingAI map ingestion and explicitly derived online pickup/delivery scenes."""

import hashlib
import random
import zipfile
from collections import deque
from io import BytesIO
from pathlib import Path
from urllib.request import Request, urlopen

from agv.domain import Scenario, Task
from agv.io.storage import write_json

MAP_NAME = "warehouse-10-20-10-2-1"
MAP_URL = f"https://movingai.com/benchmarks/mapf/{MAP_NAME}.map.zip"
LICENSE_URL = "https://opendatacommons.org/licenses/by/1-0/"
REGIONS = {"train": (32, 1, 32, 24), "validation": (64, 1, 32, 24), "test": (96, 34, 32, 24)}


def download_map(destination):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    with urlopen(
        Request(MAP_URL, headers={"User-Agent": "agv-coursework/0.2"}), timeout=30
    ) as response:
        archive = response.read(2_000_001)
    if len(archive) > 2_000_000:
        raise ValueError("Unexpectedly large map archive")
    with zipfile.ZipFile(BytesIO(archive)) as package:
        name = next(
            (n for n in package.namelist() if n.rsplit("/", 1)[-1] == MAP_NAME + ".map"), None
        )
        if name is None or package.getinfo(name).file_size > 1_000_000:
            raise ValueError("Expected warehouse map missing or too large")
        raw = package.read(name)
    parse_map(raw.decode("utf-8"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as output:
        output.write(raw)
    write_json(
        destination.with_suffix(".source.json"),
        dict(
            source_url=MAP_URL,
            source_page="https://movingai.com/benchmarks/mapf.html",
            license=LICENSE_URL,
            attribution="Moving AI Lab benchmark collection; warehouse map credited by its benchmark authors",
            sha256=hashlib.sha256(raw).hexdigest(),
            derived_task_rule="Cropped map geometry + generated shelf pickup/delivery tasks; not official MAPF scenarios",
        ),
    )
    return destination


def parse_map(text):
    lines = text.splitlines()
    if len(lines) < 4 or lines[0] != "type octile" or lines[3] != "map":
        raise ValueError("Expected MovingAI octile map header")
    try:
        height = int(lines[1].removeprefix("height "))
        width = int(lines[2].removeprefix("width "))
    except ValueError as error:
        raise ValueError("Invalid MovingAI dimensions") from error
    if not 1 <= width <= 1000 or not 1 <= height <= 1000 or len(lines[4:]) != height:
        raise ValueError("Map dimensions/rows mismatch or resource limit exceeded")
    grid = lines[4:]
    if any(len(row) != width or set(row) - set(".GS@OTW") for row in grid):
        raise ValueError("Invalid MovingAI row or map symbol")
    return grid


def derived_scene(map_path, split, seed, task_count=20, vehicles=4, horizon=600):
    if split not in REGIONS or type(seed) is not int or seed < 0:
        raise ValueError("Unknown split or invalid seed")
    if (
        type(vehicles) is not int
        or not 1 <= vehicles <= 8
        or type(task_count) is not int
        or task_count < 0
    ):
        raise ValueError("Invalid vehicle/task count")
    grid = parse_map(Path(map_path).read_text(encoding="utf-8"))
    x0, y0, width, height = REGIONS[split]
    if y0 + height > len(grid) or x0 + width > len(grid[0]):
        raise ValueError("Source map does not contain configured crop")
    free = {(x, y) for y in range(height) for x in range(width) if grid[y0 + y][x0 + x] in ".GS"}
    # Keep the largest connected component; disconnected cut-outs are walls.
    components = []
    remaining = set(free)
    while remaining:
        start = min(remaining)
        queue = deque([start])
        component = {start}
        remaining.remove(start)
        while queue:
            x, y = queue.popleft()
            for p in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if p in remaining:
                    remaining.remove(p)
                    component.add(p)
                    queue.append(p)
        components.append(component)
    if not components:
        raise ValueError("Crop contains no floor")
    free = max(components, key=lambda c: (len(c), min(c)))
    # Attach one-cell parking pockets above the crop via distinct top-row
    # portals. This preserves foreign-home exclusion without blocking corridors.
    portals = sorted(x for x, y in free if y == 0)
    if len(portals) < vehicles:
        raise ValueError("Crop has too few connected boundary portals")
    selected = [portals[i * (len(portals) - 1) // max(1, vehicles - 1)] for i in range(vehicles)]
    homes = [(x, 0) for x in selected]
    floor = {(x, y + 1) for x, y in free} | set(homes)
    blocked = {(x, y) for x in range(width) for y in range(height + 1)} - floor
    shelves = {
        p
        for p in blocked
        if p[1] > 1
        and any(
            q in floor and q not in homes
            for q in ((p[0] + 1, p[1]), (p[0] - 1, p[1]), (p[0], p[1] + 1), (p[0], p[1] - 1))
        )
    }
    if not shelves:
        raise ValueError("Crop contains no shelf-adjacent floor")
    rng = random.Random(seed)
    candidates = sorted(shelves)
    deliveries = sorted(floor - set(homes))
    tasks = [
        Task(
            j,
            None,
            rng.choice(deliveries),
            release=(j // 4) * 20,
            pickup_service=rng.randint(1, 3),
            delivery_service=rng.randint(1, 3),
            shelf=rng.choice(candidates),
        )
        for j in range(task_count)
    ]
    return Scenario(width, height + 1, blocked, shelves, homes, tasks, horizon).check()
