"""Joint task-order/vehicle-assignment proxy; never commits a physical action."""

import random

from agv.planning.f_search import ProposalCosts


class JointCosts(ProposalCosts):
    def estimate_joint(self, order, owners):
        now = self.obs["time"]
        times, positions, flows, locks = [], [], [], {}
        for v in self.obs["vehicles"]:
            if v["available"]:
                times.append(now)
                positions.append(tuple(v["position"]))
            else:
                r, j = v["route_record"], v["active_task"]
                times.append(r["delivery_end"])
                positions.append(tuple(j["delivery"]))
                flows.append(r["delivery_end"] - j["release"])
                locks[tuple(j["shelf"])] = max(locks.get(tuple(j["shelf"]), 0), r["pickup_end"])
        pending, clock, moves = list(order), now, 0
        while pending:
            used, dispatched = set(), []
            for jid in pending:
                k, j = owners[jid], self.jobs[jid]
                face = tuple(j["shelf"])
                if times[k] > clock or k in used or locks.get(face, 0) > clock:
                    continue
                if any(
                    self.jobs[p]["shelf"] == j["shelf"]
                    and (-self.jobs[p]["shelf_level"], self.jobs[p]["release"], p)
                    < (-j["shelf_level"], j["release"], jid)
                    for p in pending
                    if p != jid
                ):
                    continue
                d, approach, _ = self.details(k, positions[k], j)
                times[k] = clock + d + j["pickup_service"] + j["delivery_service"]
                positions[k] = tuple(j["delivery"])
                locks[face] = clock + approach + j["pickup_service"]
                flows.append(times[k] - j["release"])
                moves += d
                used.add(k)
                dispatched.append(jid)
            for jid in dispatched:
                pending.remove(jid)
            if not dispatched:
                events = [t for t in times + list(locks.values()) if t > clock]
                if not events:
                    return float("inf"), float("inf"), float("inf")
                clock = min(events)
        if self.obs["order_stream_closed"]:
            moves += sum(
                self.router.distance(p, self.s.homes[k], k) for k, p in enumerate(positions)
            )
        return max(times, default=now) - now, sum(flows) / max(1, len(flows)), moves


def neighbors(order, owners, vehicles, *, seed=0, limit=192):
    """Unique relocate, ownership-swap and sequence neighborhoods of one plan."""
    rng, seen, result = random.Random(seed), set(), []

    def add(sequence, assignment, kind):
        key = tuple(sequence), tuple(assignment[j] for j in sequence)
        if key not in seen and len(result) < limit:
            seen.add(key)
            result.append((list(sequence), dict(assignment), kind))

    for j in rng.sample(list(order), len(order)):
        for k in rng.sample(list(range(vehicles)), vehicles):
            if k != owners[j]:
                assignment = dict(owners)
                assignment[j] = k
                add(order, assignment, "relocate")
    for _ in range(limit * 4):
        if len(order) < 2 or len(result) >= limit:
            break
        a, b = rng.sample(range(len(order)), 2)
        sequence, assignment = list(order), dict(owners)
        if rng.random() < 0.5:
            assignment[order[a]], assignment[order[b]] = assignment[order[b]], assignment[order[a]]
            kind = "swap_owners"
        else:
            sequence.insert(b, sequence.pop(a))
            kind = "relocate_order"
        add(sequence, assignment, kind)
    return result
