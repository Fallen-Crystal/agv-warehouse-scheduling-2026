"""参考路径规划器：有等待动作和服务占位检查的时空 A*。"""
from collections import deque
import heapq


class Router:
    """Immutable-map router with cached adjacency and goal distances.

    The warehouse graph never changes while an Environment lives, so building
    the adjacency list once removes millions of generator/`free()` calls from
    the inner A* and BFS loops.  This is a pure performance change: neighbour
    order and therefore tie-breaking remain the historical order
    (east, north, west, south, wait).
    """

    def __init__(self, scenario):
        self.s = scenario
        self.cache = {}
        self.adj = {}
        for y in range(scenario.height):
            for x in range(scenario.width):
                p = (x, y)
                if scenario.free(p):
                    self.adj[p] = tuple(scenario.neighbors(p))

    def distances(self, goal, vehicle):
        key = (goal, vehicle)
        if key not in self.cache:
            forbidden = set(self.s.homes) - {self.s.homes[vehicle]}
            seen, queue = {goal: 0}, deque([goal])
            adj = self.adj
            while queue:
                p = queue.popleft()
                for q in adj[p]:
                    if q not in forbidden and q not in seen:
                        seen[q] = seen[p]+1; queue.append(q)
            self.cache[key] = seen
        return self.cache[key]

    def distance(self, start, goal, vehicle):
        return self.distances(goal, vehicle).get(start, float('inf'))

    def leg(self, start, goal, time, vehicle, vertices, edges, service=0,service_blocked=None):
        service_blocked=set() if service_blocked is None else service_blocked
        forbidden = set(self.s.homes) - {self.s.homes[vehicle]}
        distances = self.distances(goal, vehicle)
        if start not in distances or (time, start) in vertices:
            return None
        adj = self.adj
        root = (start, time)
        parent = {root: None}
        queue = [(time+distances[start], time, start)]
        heappush, heappop = heapq.heappush, heapq.heappop
        horizon = self.s.horizon
        while queue:
            _, t, p = heappop(queue)
            if p == goal and t+service <= horizon and all((u, p) not in vertices for u in range(t, t+service+1)) and all(u not in service_blocked for u in range(t,t+service)):
                path, state = [], (p, t)
                while state is not None:
                    path.append(state[0]); state = parent[state]
                return path[::-1] + [goal]*service
            if t >= horizon:
                continue
            nt = t+1
            for q in adj[p]:
                state = (q, nt)
                if q in forbidden or q not in distances or state in parent:
                    continue
                if (nt, q) in vertices or (t, q, p) in edges:
                    continue
                if nt+distances[q]+service > horizon:
                    continue
                parent[state] = (p, t)
                heappush(queue, (nt+distances[q], nt, q))
            # Waiting is the last successor, matching the historical order.
            state = (p, nt)
            if state not in parent and (nt, p) not in vertices and (t, p, p) not in edges and nt+distances[p]+service <= horizon:
                parent[state] = (p, t)
                heappush(queue, (nt+distances[p], nt, p))
        return None
