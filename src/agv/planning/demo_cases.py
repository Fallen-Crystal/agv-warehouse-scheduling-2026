"""展示实际时空A*的局部避让；不是完整订单实验或训练结果。"""

from agv.domain import Scenario
from agv.planning.astar import Router


def cases():
    entries = []
    for name, bay, entry in [
        ("侧边让行", True, False),
        ("入口等待", False, True),
        ("没有错车位置", False, False),
    ]:
        free = {(x, 2) for x in range(7)} | {(0, 0), (6, 0)}
        if bay:
            free.add((4, 1))
        if entry:
            free.update({(5, 1), (5, 3)})
        s = Scenario(
            7,
            4,
            {(x, y) for x in range(7) for y in range(4)} - free,
            set(),
            [(0, 0), (6, 0)],
            [],
            30,
        ).check()
        router = Router(s)
        leader = router.leg((1, 2), (5, 3) if entry else (6, 2), 0, 0, set(), set())
        vertices = {(t, p) for t, p in enumerate(leader)}
        vertices.update((t, leader[-1]) for t in range(len(leader), s.horizon + 1))
        edges = {(t, a, b) for t, (a, b) in enumerate(zip(leader, leader[1:]))}
        follower = router.leg((5, 1) if entry else (5, 2), (0, 2), 0, 1, vertices, edges)
        entries.append(
            dict(
                name=name,
                width=7,
                height=4,
                blocked=sorted(s.blocked),
                leader=leader,
                follower=follower,
                start=[5, 1] if entry else [5, 2],
                note=(
                    "绿色车退到侧边空位，等蓝色车通过后继续前进。"
                    if bay
                    else "绿色车在入口等待，等蓝色车离开通道后进入。"
                    if entry
                    else "按蓝色车已有路线，绿色车找不到安全路线；不能把等待当成必然能解决堵塞。"
                ),
            )
        )
    return entries
