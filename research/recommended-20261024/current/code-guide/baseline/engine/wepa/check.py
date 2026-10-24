"""Independent replay checker; no imports from execution or policy modules."""
from collections import Counter, defaultdict


def require(test, message):
    if not test:
        raise ValueError(message)


def cell(p):
    require(isinstance(p, (list, tuple)) and len(p) == 2
            and all(type(x) is int for x in p), "Grid coordinates must be integers")
    return tuple(p)


def validate(model, result):
    require(result["valid"] is True, "Incomplete run")
    s = model["scene"]
    tasks = {j["id"]: j for j in model["tasks"]}
    slots = model["slots"]
    catalogue = {tuple(r["position"]): r for r in s.map_info["rack_catalog"]}
    physical = set()
    pairs = defaultdict(set)
    for slot in slots:
        shelf = cell(slot["shelf"])
        require(shelf in catalogue, "Unknown shelf")
        bay = catalogue[shelf]
        require(slot["bay"] == bay["bay_id"] and type(slot["level"]) is int
                and 1 <= slot["level"] <= bay["levels"], "Illegal shelf level")
        require(set(map(cell, slot["points"])) == set(map(cell, bay["loading_points"])),
                "Changed legal service side")
        require((shelf, slot["level"]) not in physical, "Duplicate physical capacity")
        physical.add((shelf, slot["level"]))
        pairs[bay["pair_id"], bay["bay"]].add((bay["bay_id"], slot["sku"]))
    for owners in pairs.values():
        if len(owners) > 1:
            require(len({sku for _, sku in owners}) == len(owners), "Opposite faces hold same SKU")
    paths = [[cell(p) for p in path] for path in result["paths"]]
    labels = result["labels"]
    end = result["time"]
    require(type(end) is int and end >= model["close_at"], "Premature publisher closure")
    require(len(paths) == model["vehicles"], "Vehicle count mismatch")
    for k, p in enumerate(paths):
        require(len(p) == end + 1 and len(labels[k]) == end, "Trace length mismatch")
        require(p[0] == s.homes[k] and p[-1] == s.homes[k], "Missing final return")
        require(all(s.free(q) and q not in set(s.homes) - {s.homes[k]} for q in p),
                "Blocked cell or foreign home")
        require(all(abs(a[0] - b[0]) + abs(a[1] - b[1]) <= 1
                    for a, b in zip(p, p[1:])), "Non-four-neighbor move")
    for t in range(end + 1):
        require(len({p[t] for p in paths}) == len(paths), "Vertex collision")
        if t:
            for k in range(len(paths)):
                for other in range(k):
                    require(not (paths[k][t] == paths[other][t-1]
                                and paths[k][t-1] == paths[other][t]), "Edge swap")
    records = result["records"]
    require(len(records) == len(tasks) and {r["task"] for r in records} == set(tasks),
            "Missing or duplicate tasks")
    require(set(result["completed"]) == set(tasks), "Incomplete task set")
    services, occupied_port = defaultdict(list), defaultdict(set)
    vehicle_intervals, bay_intervals = defaultdict(list), defaultdict(list)
    stock_events = defaultdict(list)
    for r in records:
        j = tasks[r["task"]]
        require(type(r["slot"]) is int and 0 <= r["slot"] < len(slots), "Unknown slot")
        slot = slots[r["slot"]]
        require(slot["sku"] == j["sku"], "Wrong SKU")
        k = r["vehicle"]
        times = [r[key] for key in ("assigned_at", "pickup_arrival", "pickup_end", "drop_arrival", "end")]
        require(all(type(v) is int for v in times), "Non-integer event time")
        a, pa, pe, da, de = times
        require(j["release"] <= a <= pa < pe <= da < de <= end, "Invalid event chronology")
        pickup, drop = cell(r["pickup"]), cell(r["drop"])
        if j["kind"] == "delivery":
            require(pickup == tuple(j["port"]) and drop in slot["points"], "Illegal inbound endpoints")
            require(pe - pa == 1 and de - da == 2 * slot["level"], "Wrong inbound service")
            stock_events[de].append(("put", slot["id"]))
            port, begin, finish = pickup, pa, pe
            lock_end = de
        else:
            require(pickup in slot["points"] and drop == tuple(j["port"]), "Illegal outbound endpoints")
            require(pe - pa == 2 * slot["level"] and de - da == 1, "Wrong outbound service")
            stock_events[pe].append(("take", slot["id"]))
            port, begin, finish = drop, da, de
            lock_end = pe
        vehicle_intervals[k].append((a, de))
        bay_intervals[slot["bay"]].append((a, lock_end))
        for point, lo, hi in ((pickup, pa, pe), (drop, da, de)):
            require(all(paths[k][t] == point for t in range(lo, hi + 1)), "Missing continuous service")
            services[k].append((lo, hi))
        occupied_port[k].update((t, port) for t in range(begin, finish + 1))
    for intervals in list(vehicle_intervals.values()) + list(bay_intervals.values()):
        ordered = sorted(intervals)
        require(all(b[0] >= a[1] for a, b in zip(ordered, ordered[1:])), "Overlapping task or shelf lock")
    for k, path in enumerate(paths):
        for t, p in enumerate(path):
            if p in s.stations:
                require((t, p) in occupied_port[k], "Terminal used for transit or idle parking")
            if t < end and labels[k][t] == "standby" and path[t+1] == p and p not in s.homes:
                require(p in s.transit_only and p not in s.pickup_zones and p not in s.stations,
                        "Standby on a work cell or port")
    stock = set(model["occupied"])
    require(all(type(v) is int and 0 <= v < len(slots) for v in stock), "Invalid initial stock")
    for t in sorted(stock_events):
        # Capacity released at pickup completion before putaway at same instant.
        for kind, sid in sorted(stock_events[t], key=lambda item: item[0] != "take"):
            slot = slots[sid]
            if kind == "take":
                require(sid in stock, "Negative inventory or use before putaway")
                require(not any(slots[v]["bay"] == slot["bay"] and slots[v]["level"] > slot["level"]
                                for v in stock), "Lower-level pickup before upper stock")
                stock.remove(sid)
            else:
                require(sid not in stock, "Slot capacity exceeded")
                require(all(q["id"] in stock for q in slots
                            if q["bay"] == slot["bay"] and q["level"] < slot["level"]),
                        "Putaway must fill lower levels first")
                stock.add(sid)
    require(stock == set(result["final_stock"]), "Final inventory mismatch")
    expect = Counter(slots[v]["sku"] for v in model["occupied"])
    for j in tasks.values():
        expect[j["sku"]] += 1 if j["kind"] == "delivery" else -1
    require(Counter(slots[v]["sku"] for v in stock) == +expect, "SKU conservation failed")
    recorded = {(r["assigned_at"], r["vehicle"], r["task"]) for r in records}
    decisions = set()
    for d in result["decisions"]:
        visible = {j["id"] for j in tasks.values() if j["release"] <= d["time"]}
        require(set(d["visible_ids"]) == visible, "Observation includes future jobs")
        for k, jid in d["pairs"]:
            require(jid in visible, "Assigned unreleased task")
            decisions.add((d["time"], k, jid))
    require(recorded == decisions, "Decision/commit mismatch")
    flows = [r["end"] - tasks[r["task"]]["release"] for r in records]
    moves = sum(a != b for p in paths for a, b in zip(p, p[1:]))
    require(result["T"] == max((r["end"] for r in records), default=0), "Wrong T")
    require(abs(result["R"] - (sum(flows) / len(flows) if flows else 0)) < 1e-9, "Wrong R")
    require(result["D"] == moves, "Wrong distance")
    # Reconstruct carrying intervals from service events, independently of labels.
    loaded = sum(paths[r["vehicle"]][t] != paths[r["vehicle"]][t+1]
                 for r in records for t in range(r["pickup_end"], r["drop_arrival"]))
    require(result["empty_distance"] == moves - loaded, "Wrong empty distance")
    first_return = next((t for t in range(max(model["close_at"], result["T"]), end + 1)
                         if all(p[t] == s.homes[k] for k, p in enumerate(paths))), None)
    require(first_return == end, "Artificial trailing parking inflates end time")
    return dict(valid=True, tasks=len(tasks), vertices_checked=(end + 1) * len(paths),
                final_inventory_units=len(stock), distance=moves)
