import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from agv.domain import Scenario
from agv.evaluation.validation import validate
from agv.web.app import calculate, create_server, make_html

urlopen = build_opener(ProxyHandler({})).open


class ViewerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server()
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def request(self, options, origin=None, path="/api/run"):
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = origin
        return urlopen(
            Request(self.base + path, data=json.dumps(options).encode(), headers=headers),
            timeout=60,
        )

    def test_import_route_uses_actual_scene(self):
        from agv.domain import example
        from agv.io.scenes import pack_scene, scenario_id

        s = example("dynamic", size="medium", task_count=2, seed=8)
        with self.request(pack_scene(s), path="/api/load") as response:
            data = json.loads(response.read())
        self.assertEqual(data["scenario_sha256"], scenario_id(s))
        self.assertEqual(data["scenario"]["width"], 19)
        self.assertEqual(data["config"], None)

    def test_batch_route_returns_seeds_and_failure_stats(self):
        with self.request(
            dict(config={"task_count": 1}, start_seed=4, count=2), path="/api/batch"
        ) as response:
            data = json.loads(response.read())
        self.assertEqual(data["seeds"], [4, 5])
        self.assertEqual(data["summaries"][0]["runs"], 2)
        self.assertEqual(len(data["entries"]), 2)
        with self.assertRaises(HTTPError) as error:
            self.request(dict(config={}, start_seed=999999, count=2), path="/api/batch")
        self.assertEqual(error.exception.code, 400)

    def test_independent_controls_in_page(self):
        with urlopen(self.base, timeout=5) as response:
            html = response.read().decode()
        for name in (
            "size",
            "vehiclesCount",
            "layout",
            "mode",
            "arrival",
            "demand",
            "delivery",
            "taskCount",
            "seed",
            "horizon",
            "generate",
        ):
            self.assertIn('id="' + name + '"', html)
        self.assertNotIn('id="scene"', html)
        self.assertNotIn("$('scene')", html)
        with urlopen(self.base + "/assets/app.js", timeout=5) as response:
            script = response.read().decode()
        self.assertIn("fetch('/api/run'", script)
        self.assertIn("参数已修改", script)

    def test_metrics_table_exports_and_scope_visible(self):
        html = make_html()
        for name in (
            "metricSummary",
            "metricScope",
            "vehicleMetrics",
            "exportSummary",
            "exportVehicles",
            "exportTasks",
        ):
            self.assertIn('id="' + name + '"', html)
        self.assertIn("draw();renderMetrics()", html)
        self.assertIn("不随动画时间条变化", html)
        self.assertIn("不能与成功场景直接比较", html)
        self.assertIn("90%订单的耗时上限", html)
        self.assertNotIn("90%分位响应时间", html)
        self.assertIn("途中等待总步数", html)
        self.assertIn("车辆工作量差异", html)
        self.assertNotIn("行驶阶段等待", html)
        self.assertNotIn("工作量变异系数", html)
        data = calculate({})
        self.assertIn("p90_flow_time", data["result"])
        self.assertEqual(len(data["result"]["per_vehicle"]), 4)

    def test_chosen_combination_is_deterministic(self):
        options = dict(
            size="medium",
            vehicles=6,
            layout="wide",
            mode="dynamic",
            arrival="irregular",
            demand="switching",
            delivery_pattern="shared",
            task_count=18,
            seed=5,
        )
        with self.request(options) as response:
            a = json.loads(response.read())
        with self.request(options) as response:
            b = json.loads(response.read())
        self.assertEqual(a, b)
        self.assertEqual(a["scenario"]["width"], 19)
        self.assertEqual(len(a["scenario"]["homes"]), 6)
        self.assertEqual(a["config"]["arrival"], "irregular")
        self.assertTrue(a["result"]["feasible"])
        self.assertTrue(validate(Scenario.from_dict(a["scenario"]), a["result"]))

    def test_invalid_parameters_and_external_origin_rejected(self):
        for options in (
            {"vehicles": 9},
            {"task_count": 10000},
            {"seed": -1},
            {"arrival": "fake"},
            {"path": "C:/"},
            [],
        ):
            with self.assertRaises(HTTPError) as error:
                self.request(options)
            self.assertEqual(error.exception.code, 400)
        with self.assertRaises(HTTPError) as error:
            self.request({}, "https://example.com")
        self.assertEqual(error.exception.code, 403)
        with self.assertRaises(HTTPError) as error:
            urlopen(self.base + "/model.py")
        self.assertEqual(error.exception.code, 404)

    def test_malformed_json_and_static_path_traversal_are_rejected(self):
        req = Request(
            self.base + "/api/run", data=b"{broken", headers={"Content-Type": "application/json"}
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(req, timeout=5)
        self.assertEqual(caught.exception.code, 400)
        for path in ("/assets/../app.py", "/assets/missing.js"):
            with self.assertRaises(HTTPError) as caught:
                urlopen(self.base + path, timeout=5)
            self.assertEqual(caught.exception.code, 404)
        req = Request(
            self.base + "/api/run",
            data=b"{}",
            headers={"Host": "attacker.invalid", "Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as caught:
            urlopen(req, timeout=5)
        self.assertEqual(caught.exception.code, 403)

    def test_static_ignores_arrival_and_failure_is_explicit(self):
        a = calculate(dict(mode="static", arrival="burst"))
        self.assertTrue(all(j["release"] == 0 for j in a["scenario"]["tasks"]))
        b = calculate(dict(size="large", vehicles=1, task_count=24, horizon=60))
        self.assertFalse(b["result"]["feasible"])
        self.assertEqual(b["result"]["reason"], "horizon_exhausted")


if __name__ == "__main__":
    unittest.main()
