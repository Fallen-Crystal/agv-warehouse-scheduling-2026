"""参考路径规划器：有等待动作和服务占位检查的时空 A*。"""
from collections import deque
import heapq


class Router:
    def __init__(self, scenario):
        self.s = scenario
        self.cache = {}

    def distances(self, goal, vehicle):
        key = (goal, vehicle)
        if key not in self.cache:
            forbidden = set(self.s.homes) - {self.s.homes[vehicle]}
            seen, queue = {goal: 0}, deque([goal])
            while queue:
                p = queue.popleft()
                for q in self.s.neighbors(p):
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
        root = (start, time)
        parent = {root: None}
        queue = [(time+distances[start], time, start)]
        while queue:
            _, t, p = heapq.heappop(queue)
            if p == goal and t+service <= self.s.horizon and all((u, p) not in vertices for u in range(t, t+service+1)) and all(u not in service_blocked for u in range(t,t+service)):
                path, state = [], (p, t)
                while state is not None:
                    path.append(state[0]); state = parent[state]
                return path[::-1] + [goal]*service
            if t >= self.s.horizon:
                continue
            for q in (*self.s.neighbors(p), p):
                state = (q, t+1)
                if q in forbidden or q not in distances or state in parent:
                    continue
                if (t+1, q) in vertices or (t, q, p) in edges:
                    continue
                if t+1+distances[q]+service > self.s.horizon:
                    continue
                parent[state] = (p, t)
                heapq.heappush(queue, (t+1+distances[q], t+1, q))
        return None
