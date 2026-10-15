import copy
import json
import tempfile
import unittest
from pathlib import Path

from agv.domain import Scenario, example
from agv.io.movingai import map_provenance, parse_map
from agv.io.storage import write_json
from agv.learning.ranker import FEATURES, CandidateRanker, fit
from agv.planning.reservations import VertexReservations
from agv.web.app import calculate_batch, calculate_loaded, validate_options


class BoundaryTests(unittest.TestCase):
    def test_scenario_json_types_have_clear_rejection(self):
        original = example(task_count=1).to_dict()
        for field, value in [("width", True), ("blocked", "bad"), ("homes", None), ("tasks", {})]:
            data = copy.deepcopy(original)
            data[field] = value
            with self.assertRaises(ValueError):
                Scenario.from_dict(data)
        for value in ([True, 1], ["2", 1], None, [1, 2, 3]):
            data = copy.deepcopy(original)
            data["tasks"][0]["delivery"] = value
            with self.assertRaises(ValueError):
                Scenario.from_dict(data)
        data = copy.deepcopy(original)
        data["tasks"][0]["surprise"] = 1
        with self.assertRaises(ValueError):
            Scenario.from_dict(data)

    def test_atomic_json_preserves_existing_file_and_cleans_temporary(self):
        with tempfile.TemporaryDirectory() as folder:
            file = Path(folder) / "result.json"
            write_json(file, {"ok": 1})
            with self.assertRaises(FileExistsError):
                write_json(file, {"ok": 2})
            self.assertEqual(json.loads(file.read_text()), {"ok": 1})
            with self.assertRaises(ValueError):
                write_json(file, {"bad": float("nan")}, overwrite=True)
            self.assertEqual(list(Path(folder).iterdir()), [file])
            self.assertEqual(json.loads(file.read_text()), {"ok": 1})

    def test_mutating_reservations_invalidates_cached_index(self):
        r = VertexReservations({(1, (0, 0))})
        self.assertEqual(r.timeline(), {(0, 0): [1]})
        r |= {(3, (0, 0))}
        self.assertEqual(r.timeline(), {(0, 0): [1, 3]})
        r -= {(1, (0, 0))}
        self.assertEqual(r.timeline(), {(0, 0): [3]})
        r ^= {(2, (1, 1))}
        self.assertIn((1, 1), r.timeline())
        r &= {(3, (0, 0))}
        self.assertEqual(r.timeline(), {(0, 0): [3]})
        r.clear()
        self.assertEqual(r.timeline(), {})

    def test_map_and_request_limits_fail_before_running_simulation(self):
        for text in ("bad", "type octile\nheight 2\nwidth 2\nmap\n..\n."):
            with self.assertRaises(ValueError):
                parse_map(text)
        with self.assertRaises(ValueError):
            validate_options({"vehicles": True})
        with self.assertRaises(ValueError):
            calculate_batch({"config": [], "start_seed": 0, "count": 1})
        with self.assertRaises(ValueError):
            calculate_loaded({"width": 10000000, "height": 1000000})

    def test_public_map_headers_and_provenance_are_explicit(self):
        with self.assertRaises(ValueError):
            parse_map("type octile\n2\n2\nmap\n..\n..")
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "custom.map"
            p.write_text("type octile\nheight 2\nwidth 2\nmap\n..\n..")
            self.assertEqual(map_provenance(p)["origin"], "user-supplied")
            self.assertIsNone(map_provenance(p)["source_url"])
            write_json(
                p.with_suffix(".source.json"),
                {"sha256": "incorrect", "source_url": "url", "license": "url"},
            )
            with self.assertRaises(ValueError):
                map_provenance(p)

    def test_ranker_fit_and_model_parameter_validation(self):
        samples = [dict(features=[i] + [0] * (len(FEATURES) - 1), target=2 * i) for i in range(10)]
        model = fit(samples, steps=300)
        self.assertGreater(model.predict([8] + [0] * 7), model.predict([2] + [0] * 7))
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "model.json"
            write_json(p, model.to_dict())
            self.assertEqual(CandidateRanker.load(p), model)
            data = model.to_dict()
            data["scales"] = [0] * len(FEATURES)
            write_json(p, data, overwrite=True)
            with self.assertRaises(ValueError):
                CandidateRanker.load(p)
