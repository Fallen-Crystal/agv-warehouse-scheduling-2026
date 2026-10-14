"""RHCR/LNS-inspired feasible suffix improvement; no future order access.

Full remaining routes remain collision-free. Unlike RHCR, collision checks are
not truncated to a short window. Deterministic bounded prioritized repair is
not complete and does not certify globally optimal task schedules.
"""
from copy import deepcopy
from itertools import islice
import random
from model import Scenario, Task
from routing import Router
from pickup_planning import plan_task


def reservations(plans, start):
    vertices, edges = set(), set()
    for p in plans:
        vertices.update((start+i, q) for i, q in enumerate(p))
        edges.update((start+i, a, b) for i, (a, b) in enumerate(zip(p, p[1:])))
    return vertices, edges


def score(plans, records, now):
    # Primary: sum of predicted remaining completion times of assigned jobs.
    # Return duration/moves are secondary; already completed jobs contribute 0.
    return (sum(max(0, r['delivery_end']-now) for r in records if r),
            max((now+len(p)-1 for p in plans), default=now),
            sum(a != b for p in plans for a, b in zip(p, p[1:])))


def repair_vehicle(s, router, v, now, vertices, edges):
    k, pos = v['id'], tuple(v['position'])
    old = deepcopy(v['route_record'])
    if v['active_task'] is None:
        path = router.leg(pos, s.homes[k], now, k, vertices, edges)
        if path is None:
            return None
        if old is not None:
            old['return_end'] = old['return_arrival'] = now+len(path)-1
        return path, old
    data = v['active_task']
    job = Task(**{**data, 'pickup': tuple(data['pickup']) if data['pickup'] else None,
                  'delivery': tuple(data['delivery']),
                  'shelf': tuple(data['shelf']) if data['shelf'] else None})
    if now < old['pickup_arrival']:
        path, record, failed, _ = plan_task(s, router, job, k, pos, now, vertices, edges)
        if failed:
            return None
        record['assigned_at'] = old['assigned_at']
        return path, record
    # Loading already begun: preserve position, start/end and chosen shelf side.
    path = [pos]
    if now < old['pickup_end']:
        path += [pos]*(old['pickup_end']-now)
    if now < old['delivery_arrival']:
        legs = [('delivery', job.delivery, job.delivery_service), ('return', s.homes[k], 0)]
    else:
        # Unloading already begun: preserve the complete ongoing service.
        path += [pos]*max(0, old['delivery_end']-now)
        legs = [('return', s.homes[k], 0)]
    if any((now+i, p) in vertices for i, p in enumerate(path)):
        return None
    for name, goal, service in legs:
        leg = router.leg(path[-1], goal, now+len(path)-1, k, vertices, edges, service)
        if leg is None:
            return None
        path.extend(leg[1:])
        old[name+'_end'] = now+len(path)-1
        old[name+'_arrival'] = old[name+'_end']-service
    return path, old


class JointPlanner:
    """Destroy all or a small pair of suffixes, repair in several priorities.

    Candidate plans are accepted only if the explicit lexicographic objective
    improves. The incumbent is a safe fallback after bounded search fails.
    """
    def __init__(self, attempts=8):
        if type(attempts) is not int or attempts < 1:
            raise ValueError('attempts must be positive')
        self.attempts = attempts
        self.router = None

    def propose(self, observation):
        m, now = observation['map'], observation['time']
        s = Scenario(m['width'], m['height'], set(map(tuple, m['blocked'])),
                     set(map(tuple, m['shelves'])), list(map(tuple, m['homes'])), [], observation['horizon'])
        if self.router is None or self.router.s.to_dict() != s.to_dict():
            self.router = Router(s)
        vehicles = observation['vehicles']
        plans = [[tuple(q) for q in (v['committed_path'] if not v['available'] else v['return_path'])] for v in vehicles]
        records = [deepcopy(v['route_record']) for v in vehicles]
        original = score(plans, records, now)
        best = original
        moving = [v['id'] for v in vehicles if len(plans[v['id']]) > 1]
        if len(moving) < 2:
            return None
        # Rotate priorities to let a later assigned busy vehicle go first.
        orders = [moving[i:]+moving[:i] for i in range(len(moving))]
        orders += [list(reversed(o)) for o in orders[:]]
        rng = random.Random(now)
        while len(orders) < self.attempts:
            order = moving[:]; rng.shuffle(order); orders.append(order)
        trials = list(islice(orders, self.attempts))
        # Pair neighborhoods retain other vehicles' good routes (LNS idea).
        trials += [[a, b] for a, b in zip(moving, moving[1:])]
        for order in trials:
            candidate = deepcopy(plans); updates = deepcopy(records)
            vtx, edg = reservations([p for k, p in enumerate(plans) if k not in order], now)
            # All real start positions are occupied at now, including agents
            # which will be repaired later. Their later suffix is destroyed.
            vtx.update((now, tuple(v['position'])) for v in vehicles)
            okay = True
            for k in order:
                own = (now, tuple(vehicles[k]['position']))
                vtx.discard(own)
                item = repair_vehicle(s, self.router, vehicles[k], now, vtx, edg)
                vtx.add(own)
                if item is None:
                    okay = False; break
                candidate[k], updates[k] = item
                more_v, more_e = reservations([candidate[k]], now)
                vtx.update(more_v); edg.update(more_e)
            if okay:
                value = score(candidate, updates, now)
                if value < best:
                    plans, records, best = candidate, updates, value
        if best >= original:
            return None
        return dict(plans=plans, records=records, before=original, after=best,
                    trials=len(trials), time=now)
