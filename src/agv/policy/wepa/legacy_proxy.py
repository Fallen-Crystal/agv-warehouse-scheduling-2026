"""Mixed-flow adapter for the existing GA and joint ACO/PSO generators.

This reservation-free list schedule only ranks proposals. Physical execution is
always checked by complete visible-work SIPP rollouts. Predicted slot bindings
come from the anchor rollout; real WMS bindings are never overridden.
"""

from math import inf


class MixedCosts:
    def __init__(self, world, prediction):
        self.world = world
        self.jobs = {j: world.tasks[j] for j in world.visible if j not in world.assigned}
        self.obs = {"vehicles": [{"position": p[0]} for p in world.plans]}
        self.projected = {r["task"]: r for r in prediction.records}
        self.slots = {j: world.slots[self.projected[j]["slot"]] for j in self.jobs}
        self.cache, self.values, self.permutations = {}, {}, {}
        self.allowance, self.evaluations = 1000000, 0
        self.predecessor = {}
        last = {}
        for r in sorted(
            prediction.records,
            key=lambda r: (r["assigned_at"], r["vehicle"], r["task"]),
        ):
            j = r["task"]
            if j not in self.jobs:
                continue
            bay = self.slots[j]["bay"]
            if bay in last:
                self.predecessor[j] = last[bay]
            last[bay] = j

    def details(self, vehicle, position, job):
        jid = job["id"]
        key = vehicle, tuple(position), jid
        if key not in self.cache:
            slot = self.slots[jid]
            if job["kind"] == "delivery":
                options = [(job["port"], p, 1, 2 * slot["level"]) for p in slot["points"]]
            else:
                options = [(p, job["port"], 2 * slot["level"], 1) for p in slot["points"]]
            d, approach, pickup, drop, ps, ds = min(
                (
                    self.world.router.distance(tuple(position), a, vehicle)
                    + self.world.router.distance(a, b, vehicle),
                    self.world.router.distance(tuple(position), a, vehicle),
                    a,
                    b,
                    ps,
                    ds,
                )
                for a, b, ps, ds in options
            )
            self.cache[key] = d, approach, pickup, drop, ps, ds
        return self.cache[key][:3]

    def _schedule(self, order, owners=None):
        w = self.world
        times, positions = [], []
        flows = [r["end"] - w.tasks[r["task"]]["release"] for r in w.records]
        final_t = max((r["end"] for r in w.records), default=w.time)
        moves = w.past_moves
        for k, r in enumerate(w.active):
            if r is None:
                times.append(w.time)
                positions.append(w.plans[k][0])
            else:
                times.append(r["end"])
                positions.append(r["drop"])
                suffix = w.plans[k][: r["end"] - w.time + 1]
                moves += sum(a != b for a, b in zip(suffix, suffix[1:]))
        locks = dict(w.locks)
        pending, assignment = list(order), {}
        while pending:
            jid = next((j for j in pending if self.predecessor.get(j) not in pending), None)
            if jid is None:
                return (inf, inf, inf), assignment
            job, slot = self.jobs[jid], self.slots[jid]
            bay = slot["bay"]
            choices = range(len(times)) if owners is None else [owners[jid]]
            options = []
            for k in choices:
                self.details(k, positions[k], job)
                d, approach, pickup, drop, ps, ds = self.cache[k, tuple(positions[k]), jid]
                start = max(times[k], locks.get(bay, 0))
                finish = start + d + ps + ds
                options.append((finish, d, k, approach, drop, ps, ds, start))
            finish, d, k, approach, drop, ps, ds, start = min(options)
            times[k], positions[k] = finish, drop
            locks[bay] = finish if job["kind"] == "delivery" else start + approach + ps
            flows.append(finish - job["release"])
            moves += d
            final_t = max(final_t, finish)
            pending.remove(jid)
            assignment[jid] = k
        moves += sum(
            w.router.distance(tuple(p), w.scene.homes[k], k) for k, p in enumerate(positions)
        )
        return (final_t, sum(flows) / max(1, len(flows)), moves), assignment

    def estimate(self, order):
        key = tuple(order)
        if key not in self.permutations:
            if self.evaluations >= self.allowance:
                return (inf, inf, inf)
            self.permutations[key] = self._schedule(order)[0]
            self.evaluations += 1
        return self.permutations[key]

    def owners(self, order):
        return self._schedule(order)[1]

    def estimate_joint(self, order, owners):
        key = tuple(order), tuple(owners[j] for j in order)
        if key not in self.values:
            if self.evaluations >= self.allowance:
                return (inf, inf, inf)
            self.values[key] = self._schedule(order, owners)[0]
            self.evaluations += 1
        return self.values[key]
