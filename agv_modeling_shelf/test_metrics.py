import copy
import unittest
from model import Task, Scenario, example
from environment import Environment
from baseline import run
from validation import validate


def tiny(release=0):
    return Scenario(5,3,{(2,1)},{(2,1)},[(0,0)],
                    [Task(10,(1,1),(4,1),release)],100).check()


class MetricsTests(unittest.TestCase):
    def test_manual_loaded_empty_and_time_decomposition(self):
        s=tiny(10);r=run(s)
        self.assertTrue(validate(s,r))
        self.assertEqual((r['loaded_moves'],r['empty_moves']),(5,7))
        self.assertEqual((r['mean_dispatch_wait'],r['mean_pickup_duration'],r['mean_loaded_duration'],r['mean_service_duration']),(0,2,5,2))
        self.assertEqual((r['max_flow_time'],r['p90_flow_time']),(9,9))
        v=r['per_vehicle'][0]
        self.assertEqual((v['task_busy_steps'],v['idle_steps'],v['completed_tasks']),(9,10,1))
        self.assertAlmostEqual(v['task_utilization'],9/24)
        self.assertEqual(r['workload_cv'],0)

    def test_deliberate_dispatch_delay_is_separate(self):
        s=tiny();env=Environment(s);env.advance(3);env.assign([(0,10)])
        while not env.done:env.advance()
        r=env.result()
        self.assertEqual(r['mean_dispatch_wait'],3)
        self.assertEqual(r['mean_flow_time'],12)
        self.assertEqual(r['per_vehicle'][0]['task_busy_steps'],9)
        self.assertTrue(validate(s,r))

    def test_p90_nearest_rank_and_vehicle_sums(self):
        s=example(task_count=12);r=run(s)
        values=sorted(e['delivery_end'] for e in r['events'])
        self.assertEqual(r['p90_flow_time'],values[10])
        self.assertEqual(r['max_flow_time'],values[-1])
        self.assertAlmostEqual(r['mean_flow_time'],sum(r['mean_'+k] for k in ('dispatch_wait','pickup_duration','loaded_duration','service_duration')))
        for k in ('moves','empty_moves','loaded_moves','service_steps','idle_steps','traffic_wait_steps'):
            self.assertEqual(r[k],sum(v[k] for v in r['per_vehicle']))
        self.assertEqual(sum(v['completed_tasks'] for v in r['per_vehicle']),12)
        self.assertTrue(validate(s,r))

    def test_partial_run_has_no_future_statistics(self):
        s=tiny();env=Environment(s);env.assign([(0,10)]);env.advance(4)
        r=env.result()
        self.assertFalse(r['comparison_valid'])
        self.assertEqual(r['metrics_scope'],'completed_tasks_only')
        self.assertEqual(r['completion_rate'],0)
        self.assertIsNone(r['max_flow_time']);self.assertIsNone(r['p90_flow_time'])
        self.assertEqual(r['task_metrics'],[])
        self.assertEqual(r['loaded_moves'],1)
        self.assertEqual(r['per_vehicle'][0]['task_busy_steps'],4)
        self.assertTrue(validate(s,r))

    def test_completed_tasks_but_return_unfinished(self):
        s=tiny();env=Environment(s);env.assign([(0,10)]);env.advance(9)
        r=env.result()
        self.assertEqual(r['metrics_scope'],'all_tasks')
        self.assertEqual(r['completion_rate'],1)
        self.assertFalse(r['comparison_valid'])
        self.assertTrue(validate(s,r))

    def test_empty_tasks_and_idle_vehicle(self):
        s=example(task_count=0);r=run(s)
        self.assertEqual(r['completion_rate'],1)
        self.assertEqual(r['p90_flow_time'],0)
        self.assertEqual(r['workload_cv'],0)
        self.assertTrue(all(v['task_utilization']==0 for v in r['per_vehicle']))
        self.assertTrue(validate(s,r))
        s=example(task_count=1,vehicles=4);r=run(s)
        self.assertTrue(any(v['completed_tasks']==0 for v in r['per_vehicle']))
        self.assertGreater(r['workload_cv'],0)
        self.assertTrue(validate(s,r))

    def test_independent_auditor_rejects_new_metric_corruption(self):
        s=example(task_count=3);r=run(s)
        for key in ('max_flow_time','p90_flow_time','empty_moves','loaded_moves','workload_cv','completion_rate'):
            bad=copy.deepcopy(r);bad[key]+=1
            with self.assertRaises(ValueError):validate(s,bad)
        for key in ('completed_tasks','assigned_tasks','task_busy_steps','task_utilization','moves','empty_moves','loaded_moves'):
            bad=copy.deepcopy(r);bad['per_vehicle'][0][key]+=1
            with self.assertRaises(ValueError):validate(s,bad)
        bad=copy.deepcopy(r);bad['task_metrics'][0]['dispatch_wait']+=1
        with self.assertRaises(ValueError):validate(s,bad)


if __name__=='__main__':
    unittest.main()
