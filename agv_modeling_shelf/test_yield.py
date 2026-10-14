import unittest
from yield_demo import cases


class YieldTests(unittest.TestCase):
    def check_safe(self,c):
        a,b=c['leader'],c['follower']
        self.assertIsNotNone(b)
        for path in (a,b):
            self.assertTrue(all(list(p) not in [list(q) for q in c['blocked']] for p in path))
            self.assertTrue(all(abs(p[0]-q[0])+abs(p[1]-q[1])<=1 for p,q in zip(path,path[1:])))
        for t in range(max(len(a),len(b))):
            p,q=a[min(t,len(a)-1)],b[min(t,len(b)-1)]
            self.assertNotEqual(p,q)
            if t:self.assertFalse(a[min(t-1,len(a)-1)]==q and b[min(t-1,len(b)-1)]==p)

    def test_side_bay_yield_and_rejoin(self):
        c=cases()[0];self.check_safe(c)
        self.assertIn((4,1),c['follower'])
        self.assertEqual(c['follower'][-1],(0,2))
        # 进侧边时暂时远离目标：允许局部绕路来避免迎面冲突。
        self.assertTrue(any(abs(q[0])+abs(q[1]-2)>abs(p[0])+abs(p[1]-2)
                            for p,q in zip(c['follower'],c['follower'][1:])))

    def test_wait_outside_entrance(self):
        c=cases()[1];self.check_safe(c)
        self.assertGreater(c['follower'].count((5,1)),1)
        self.assertEqual(c['follower'][-1],(0,2))

    def test_no_passing_space_reports_failure(self):
        self.assertIsNone(cases()[2]['follower'])


if __name__=='__main__':unittest.main()
