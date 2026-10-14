"""Regression tests for service safety, atomic suffix repair and online inputs."""
import copy
import unittest
from environment import Environment
from model import example, Task
from baseline import greedy_action, run as baseline_run
from optimized import run, matching_action
from joint_planning import JointPlanner, repair_vehicle
from routing import Router
from validation import validate


class OptimizerTests(unittest.TestCase):
    def test_service_and_midroute_stages_keep_executed_prefix(self):
        s=example(mode='static',seed=3)
        s.tasks=[Task(j.id,j.pickup,j.delivery,j.release,3,4,j.shelf) for j in s.tasks]
        e=Environment(s);seen=set();planner=JointPlanner()
        while not e.done and e.time<s.horizon:
            e.assign(greedy_action(e.observe()))
            obs=e.observe();before=copy.deepcopy(e._paths)
            for v in obs['vehicles']:
                seen.add(v['state'])
                path,rec=repair_vehicle(s,Router(s),v,e.time,set(),set())
                if v['state'] in ('loading','unloading'):
                    leg='pickup' if v['state']=='loading' else 'delivery'
                    self.assertEqual(rec[leg+'_arrival'],v['route_record'][leg+'_arrival'])
                    self.assertEqual(rec[leg+'_end'],v['route_record'][leg+'_end'])
                    remaining=rec[leg+'_end']-e.time
                    self.assertTrue(all(p==v['position'] for p in path[:remaining+1]))
            p=planner.propose(obs)
            if p:e.apply_replan(p)
            self.assertEqual(e._paths,before)
            e.advance()
        self.assertTrue({'to_pickup','loading','to_delivery','unloading','returning'}<=seen)
        self.assertTrue(e.done);validate(s,e.result())

    def test_atomic_rejects_collision_and_interrupted_service(self):
        s=example();e=Environment(s);e.assign(greedy_action(e.observe()))
        planner=JointPlanner()
        for _ in range(5):e.advance()
        obs=e.observe()
        proposal=dict(time=e.time,plans=copy.deepcopy(e._plans),
                      records=[v['route_record'] for v in obs['vehicles']],before=(1,),after=(0,),trials=1)
        proposal['plans'][0][0]=(12,10)
        before=copy.deepcopy(e.__dict__)
        with self.assertRaises(ValueError):e.apply_replan(proposal)
        self.assertEqual(e._plans,before['_plans']);self.assertEqual(e._records,before['_records'])
        self.assertEqual(e._paths,before['_paths'])

    def test_missing_metadata_rejects_before_atomic_commit(self):
        s=example(mode='dynamic',arrival='burst',size='medium',vehicles=6,task_count=30)
        e=Environment(s);e.assign(matching_action(e.observe()))
        proposal=JointPlanner().propose(e.observe());self.assertIsNotNone(proposal)
        proposal.pop('trials');before=e.result()
        with self.assertRaises(KeyError):e.apply_replan(proposal)
        self.assertEqual(e.result(),before)

    def test_no_future_tasks_in_extended_observation(self):
        s=example(mode='dynamic',arrival='uniform')
        a=Environment(s)
        altered=copy.deepcopy(s);altered.tasks=[j for j in altered.tasks if j.release==0]
        b=Environment(altered)
        self.assertEqual(a.observe(),b.observe())
        a.assign(matching_action(a.observe()));b.assign(matching_action(b.observe()))
        self.assertEqual(a.observe(),b.observe())
        self.assertEqual(JointPlanner().propose(a.observe()),JointPlanner().propose(b.observe()))

    def test_joint_busy_routes_really_change_and_cost_decreases(self):
        s=example(mode='dynamic',arrival='burst',size='medium',vehicles=6,task_count=30)
        r=run(s);validate(s,r)
        self.assertTrue(any(c['state'] in ('to_pickup','to_delivery')
            for ev in r['replanning_events'] for c in ev['changes']))
        self.assertTrue(all(tuple(ev['after'])<tuple(ev['before']) for ev in r['replanning_events']))
        self.assertEqual(r,run(s))

    def test_exact_matching_on_known_counterexample_to_greedy(self):
        # Cost matrix [[10,6],[14,8]]: greedy 6+14=20, optimum 10+8=18.
        from model import Scenario
        s=Scenario(7,4,{(2,2),(4,2)},{(2,2),(4,2)},[(0,0),(6,0)],
            [Task(0,(1,2),(5,1)),Task(1,(2,1),(1,1))]).check()
        obs=Environment(s).observe()
        actual=matching_action(obs)
        # Compute exhaustive matrix sum for this real geometry (no mocked DP).
        from itertools import permutations
        router=Router(s)
        def cost(pairs):
            return sum(router.distance(s.homes[k],s.tasks[j].pickup,k)+
                router.distance(s.tasks[j].pickup,s.tasks[j].delivery,k)+2 for k,j in pairs)
        possibilities=[list(zip(range(2),p)) for p in permutations(range(2))]
        self.assertEqual(cost(actual),min(map(cost,possibilities)))
        self.assertLess(cost(actual),cost(greedy_action(obs)))

    def test_failure_and_ablation_traces_are_valid(self):
        s=example(size='medium',vehicles=6,task_count=30,horizon=70)
        for assignment,joint in [('matching',False),('greedy',True),('matching',True)]:
            r=run(s,assignment=assignment,joint=joint);validate(s,r)
            self.assertFalse(r['feasible']);self.assertFalse(r['comparison_valid'])


if __name__=='__main__':unittest.main()
