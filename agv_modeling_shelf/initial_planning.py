"""Static first-batch batch planner: screen with greedy, score with joint.

For a fully visible static instance the whole task set is known at t=0, so it is
legal to compare a small set of initial assignments by rolling each one forward
with the same joint policy used for execution.  The base greedy assignment is
always in the comparison set, so the selected plan cannot be worse than the
current joint baseline on these instances.

Dynamic instances are deliberately excluded: a rollout that runs past the
current release frontier would use future arrivals in the score.  The static
guard keeps the planner an offline batch tool; all 240 formal online runs keep
the original greedy + joint path.
"""
import itertools
from baseline import greedy_action
from environment import Environment
from model import Scenario, Task
from joint_planning import JointPlanner
from validation import validate


def _visible_scenario(observation):
    m = observation['map']
    tasks = []
    for data in observation['pending']:
        tasks.append(Task(data['id'], tuple(data['pickup']) if data['pickup'] is not None else None,
                          tuple(data['delivery']), data['release'],
                          data['pickup_service'], data['delivery_service'],
                          tuple(data['shelf']) if data.get('shelf') is not None else None))
    return Scenario(m['width'], m['height'], set(map(tuple, m['blocked'])),
                    set(map(tuple, m['shelves'])), list(map(tuple, m['homes'])),
                    tasks, observation['horizon'])


def _greedy_rollout(scenario, pairs):
    env = Environment(scenario)
    try:
        env.assign(pairs)
    except ValueError:
        return None
    while not env.done and env.time < scenario.horizon:
        env.assign(greedy_action(env.observe()))
        env.advance()
    return env.result() if env.done else None


def _joint_rollout(scenario, pairs, attempts=8, interval=5):
    env = Environment(scenario)
    planner = JointPlanner(attempts)
    try:
        env.assign(pairs)
    except ValueError:
        return None
    while not env.done and env.time < scenario.horizon:
        feedback = env.assign(greedy_action(env.observe()))
        if env.time % interval == 0 or any(f['accepted'] for f in feedback):
            proposal = planner.propose(env.observe())
            if proposal:
                env.apply_replan(proposal)
        env.advance()
    if not env.done:
        return None
    result = env.result()
    validate(scenario, result)
    return result


def candidates(observation, limit=48):
    base = greedy_action(observation)
    pending = [j['id'] for j in observation['pending']]
    used = {j for _, j in base}
    seen, out = set(), []

    def add(pairs):
        key = tuple(pairs)
        if key not in seen:
            seen.add(key); out.append(pairs)

    add(base)
    for (a, ja), (b, jb) in itertools.combinations(base, 2):
        add([(k, jb if k == a else ja if k == b else j) for k, j in base])
    for k, j in base:
        for q in pending:
            if q in used:
                continue
            add([(kk, q if kk == k else jj) for kk, jj in base])
    return out[:limit]


def choose_initial(scenario, limit=48, top_k=4, attempts=8, interval=5):
    """Return an improved static first batch, or [] when not applicable."""
    if any(job.release != 0 for job in scenario.tasks):
        return []
    observation = Environment(scenario).observe()
    visible = _visible_scenario(observation)
    base = greedy_action(observation)
    screened = []
    for pairs in candidates(observation, limit):
        result = _greedy_rollout(visible, pairs)
        if result is not None:
            screened.append((result['mean_flow_time'], tuple(pairs), pairs))
    screened.sort(key=lambda item: (item[0], item[1]))
    pool = [pairs for _, _, pairs in screened[:top_k]]
    if base not in pool:
        pool.append(base)
    best = None
    for pairs in pool:
        result = _joint_rollout(scenario, pairs, attempts, interval)
        if result is None:
            continue
        key = (result['mean_flow_time'], result['makespan'], result['moves'])
        if best is None or key < best[0]:
            best = (key, pairs)
    return best[1] if best else []
