"""算法无关的数据模型。时间、距离采用离散单位。"""
from dataclasses import dataclass, asdict
from collections import deque
import random

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


@dataclass
class Scenario:
    width: int
    height: int
    blocked: set[Point]
    shelves: set[Point]
    homes: list[Point]
    tasks: list[Task]
    horizon: int = 600

    def free(self, p):
        return 0 <= p[0] < self.width and 0 <= p[1] < self.height and p not in self.blocked

    def neighbors(self, p):
        x, y = p
        for q in ((x+1, y), (x, y+1), (x-1, y), (x, y-1)):
            if self.free(q):
                yield q

    def pickup_candidates(self, job):
        if job.shelf is None:
            return [job.pickup]
        return sorted(p for p in self.neighbors(job.shelf) if p not in self.homes)

    def check(self):
        def require(ok, message):
            if not ok:
                raise ValueError(message)
        def integer(v):
            return type(v) is int
        def point(p):
            return len(p) == 2 and all(integer(v) for v in p)
        require(integer(self.width) and integer(self.height) and self.width > 0 and self.height > 0, 'Invalid dimensions')
        require(integer(self.horizon) and self.horizon > 0, 'Invalid horizon')
        require(bool(self.homes) and len(set(self.homes)) == len(self.homes), 'Need distinct homes')
        require(self.shelves <= self.blocked, 'Shelves must be blocked')
        for p in self.blocked | set(self.homes):
            require(point(p) and 0 <= p[0] < self.width and 0 <= p[1] < self.height, 'Invalid map point')
        require(all(self.free(p) for p in self.homes), 'Blocked home')
        require(all(integer(j.id) for j in self.tasks), 'Task IDs must be integers')
        require(len({j.id for j in self.tasks}) == len(self.tasks), 'Duplicate task ID')
        for j in self.tasks:
            require(integer(j.release) and j.release >= 0, 'Invalid release')
            require(all(integer(s) and s >= 1 for s in (j.pickup_service, j.delivery_service)), 'Invalid service duration')
            require(point(j.delivery) and self.free(j.delivery) and j.delivery not in self.homes, 'Invalid delivery point')
            if j.shelf is not None:
                require(point(j.shelf) and j.shelf in self.shelves, 'Target must be a shelf cell')
                require(j.pickup is None,'Shelf task must not fix pickup point')
                require(bool(self.pickup_candidates(j)), 'No legal pickup neighbor')
            else:
                require(j.pickup is not None and point(j.pickup) and self.free(j.pickup) and j.pickup not in self.homes, 'Invalid service point')
                require(any(abs(j.pickup[0]-p[0])+abs(j.pickup[1]-p[1]) == 1 for p in self.shelves), 'Pickup must neighbor a shelf')
            # 至少一辆车能完成整个任务；他车停车位属于禁止通行节点。
            reachable = False
            for k, home in enumerate(self.homes):
                forbidden = set(self.homes) - {home}
                seen, queue = {home}, deque([home])
                while queue:
                    for p in self.neighbors(queue.popleft()):
                        if p not in seen and p not in forbidden:
                            seen.add(p); queue.append(p)
                reachable |= any(p in seen for p in self.pickup_candidates(j)) and j.delivery in seen
            require(reachable, f'Unreachable task {j.id}')
        return self

    def to_dict(self):
        return dict(width=self.width, height=self.height, blocked=sorted(self.blocked),
                    shelves=sorted(self.shelves), homes=self.homes, horizon=self.horizon,
                    tasks=[asdict(j) for j in self.tasks])

    @classmethod
    def from_dict(cls, data):
        tasks = [Task(**{**j, 'pickup': tuple(j['pickup']) if j.get('pickup') is not None else None,
                        'shelf':tuple(j['shelf']) if j.get('shelf') is not None else None,
                        'delivery': tuple(j['delivery'])}) for j in data['tasks']]
        return cls(data['width'], data['height'], {tuple(p) for p in data['blocked']},
                   {tuple(p) for p in data['shelves']}, [tuple(p) for p in data['homes']],
                   tasks, data.get('horizon', 600)).check()


def example(mode='static', layout='bottleneck', seed=0, task_count=12,
            vehicles=4, size='small', delivery_pattern='distributed',
            arrival='batch', demand='balanced', horizon=600):
    if mode not in ('static', 'dynamic') or layout not in ('wide', 'bottleneck'):
        raise ValueError('Unknown mode or layout')
    if type(task_count) is not int or task_count < 0:
        raise ValueError('task_count must be a nonnegative integer')
    if type(vehicles) is not int or not 1 <= vehicles <= 8:
        raise ValueError('vehicles must be an integer from 1 to 8')
    if type(seed) is not int or seed < 0:
        raise ValueError('seed must be a nonnegative integer')
    if arrival not in ('batch', 'uniform', 'irregular', 'burst'):
        raise ValueError('Unknown arrival pattern')
    if demand not in ('balanced', 'left_hotspot', 'right_hotspot', 'switching'):
        raise ValueError('Unknown demand pattern')
    sizes = {'small': (13, 11), 'medium': (19, 15), 'large': (25, 19)}
    if size not in sizes or delivery_pattern not in ('distributed', 'shared'):
        raise ValueError('Unknown size or delivery pattern')
    width, height = sizes[size]
    middle = height//2
    rng = random.Random(seed)
    shelf_rng=random.Random(seed ^ 0x54E1F)
    # 到达、需求偏置、基础位置使用独立随机流，改变到达模式不改变任务位置。
    arrival_rng = random.Random(seed ^ 0xA771A1)
    demand_rng = random.Random(seed ^ 0xD3A4AD)
    releases = []
    current_release = 0
    for j in range(task_count):
        if arrival == 'batch':
            current_release = (j//3)*15
        elif arrival == 'uniform':
            current_release = j*5
        elif arrival == 'irregular':
            current_release = 0 if j == 0 else current_release+arrival_rng.randint(1, 9)
        else:
            current_release = (j//6)*30
        releases.append(0 if mode == 'static' else current_release)
    all_homes = [(2, 0), (4, 0), (width-5, 0), (width-3, 0),
                 (1, 0), (width-2, 0), (width//2-1, 0), (width//2+1, 0)]
    homes = [all_homes[0], all_homes[2]] if vehicles == 2 else all_homes[:vehicles]
    shelf_columns=(3,9,15,21) if size=='large' else (3,width-4)
    shelves = {(x, y) for x in shelf_columns for y in range(3, height-2)}
    blocked = shelves | {(x, 0) for x in range(width) if (x, 0) not in homes}
    gates = {middle} if layout == 'bottleneck' else {3, middle, height-4}
    blocked |= {(width//2, y) for y in range(1, height) if y not in gates}
    jobs = []
    for j in range(task_count):
        side = rng.randrange(2)
        if demand != 'balanced':
            hot_side = 1 if demand == 'right_hotspot' or (demand == 'switching' and j >= (task_count+1)//2) else 0
            side = hot_side if demand_rng.random() < .8 else 1-hot_side
        pickup = (rng.choice((2, 4) if side == 0 else (width-5, width-3)), rng.randrange(3, height-2))
        delivery = (rng.choice((1, width-2)), rng.choice((2, height-2)))
        if delivery_pattern == 'shared':
            delivery = (1, middle)
        # 保留位置随机流的抽样顺序，订单目标改为对应货架格，不固定停靠侧。
        shelf=(3 if side==0 else width-4,pickup[1])
        if size=='large':shelf=(shelf_rng.choice((3,9) if side==0 else (15,21)),pickup[1])
        jobs.append(Task(j, None, delivery, releases[j],shelf=shelf))
    return Scenario(width, height, blocked, shelves, homes, jobs, horizon).check()
