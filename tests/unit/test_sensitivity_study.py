import copy
import gzip
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from scripts import report_sensitivity_study as report
from scripts import run_sensitivity_study as study


def physical_row(fitness):
    return dict(
        valid=True,
        F=fitness,
        T=fitness * 900,
        R=fitness * 900,
        D=fitness * 5400,
        cpu=2,
        wall=3,
        p90=4,
        empty_distance=5,
        traffic_wait=6,
    )


class FrozenSensitivityStudyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="sensitivity-study-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runtime = self.root / "runtime"
        (self.runtime / "data").mkdir(parents=True)
        self.cases = [
            dict(
                case=f"wepa-day{day}-bin{index}",
                source_day=day,
                tasks=[dict(id=index)],
                close_at=900,
                initial={"11": 1},
            )
            for index, day in enumerate((12, 32, 33, 45, 61))
        ]
        protocol = dict(
            cases=self.cases,
            development=[c["case"] for c in self.cases[:4]],
            validation=[self.cases[-1]["case"]],
            objective=dict(weights=[0.5, 0.3, 0.2], horizon_seconds=900, vehicles=6),
            configuration=dict(size="large", vehicles=6, layers=5),
        )
        study.write_new(self.runtime / "data/protocol.json", protocol)
        (self.runtime / "module.py").write_text("FROZEN = True\n")
        self.provenance = dict(
            main_commit=study.MAIN,
            archive=dict(path="runtime.zip", sha256="a" * 64),
            main_source_overlays={"module.py": dict(sha256=study.sha(self.runtime / "module.py"))},
            files={
                name: study.sha(self.runtime / name) for name in ("data/protocol.json", "module.py")
            },
        )
        study.write_new(self.runtime / "runtime_manifest.json", self.provenance)
        self.directory = self.root / "study"
        with redirect_stdout(io.StringIO()):
            self.plan = study.initialize(self.directory, self.runtime)

    def test_matrix_is_exactly_200_paired_jobs_with_declared_seed_budgets(self):
        jobs = study.jobs(self.plan)
        self.assertEqual(len(jobs), 200)
        self.assertEqual(self.plan["expected_trials"], 200)
        self.assertEqual(len({job["id"] for job in jobs}), 200)
        self.assertEqual(set(self.plan["execution_order"]), {job["id"] for job in jobs})
        self.assertEqual(self.plan["cases"], [case["case"] for case in self.cases[:4]])
        self.assertNotIn(self.cases[-1]["case"], self.plan["cases"])
        for variant in self.plan["variants"]:
            actual = [job for job in jobs if job["variant"] == variant["id"]]
            expected = {(case, seed) for case in self.plan["cases"] for seed in variant["seeds"]}
            self.assertEqual({(job["case"], job["seed"]) for job in actual}, expected)
            if variant["id"] in ("fcfs", "eta", "hungarian"):
                self.assertEqual(variant["seeds"], [0, 1])
            elif variant["group"] == "evolution":
                self.assertEqual(variant["seeds"], list(range(5)))
            else:
                self.assertEqual(variant["seeds"], [0, 1, 2])

    def test_budget_interventions_and_adaptive_factorial_are_explicit(self):
        variants = {variant["id"]: variant for variant in self.plan["variants"]}
        expected = {
            "gate_proxy96": {"proxy": 96},
            "gate_preview3": {"previews": 3},
            "gate_gen8": {"generations": 8},
            "gate_proxy96_preview3": {"proxy": 96, "previews": 3},
        }
        for name, overrides in expected.items():
            self.assertEqual(variants[name]["profile"], "gate")
            self.assertEqual(variants[name]["overrides"], overrides)
        self.assertEqual(variants["gate"]["overrides"], {})
        for mutation, crossover in ((0, 0), (1, 0), (0, 1), (1, 1)):
            variant = variants[f"wide_adapt{mutation}{crossover}"]
            self.assertEqual(variant["profile"], "wide")
            self.assertEqual(variant["overrides"], {})
            self.assertEqual(
                variant["adaptive"],
                dict(
                    adaptive_mutation=bool(mutation),
                    adaptive_crossover=bool(crossover),
                    mutation_rate=0.7,
                    crossover_rate=0.9,
                ),
            )

    def test_frozen_plan_and_runtime_sources_cannot_change(self):
        self.assertEqual(study.check_sources(self.directory), self.plan)
        plan_path = self.directory / "plan.json"
        original = plan_path.read_bytes()
        plan_path.write_bytes(original + b"\n")
        with self.assertRaisesRegex(ValueError, "Frozen plan changed"):
            study.check_sources(self.directory)
        plan_path.write_bytes(original)
        (self.runtime / "module.py").write_text("FROZEN = False\n")
        with self.assertRaisesRegex(ValueError, "Prepared runtime changed: module.py"):
            study.check_sources(self.directory)

    def test_original_source_provenance_and_case_identity_are_retained(self):
        self.assertEqual(self.plan["runtime_provenance"], self.provenance)
        self.assertEqual(self.plan["sources"]["runner"], study.sha(study.SCRIPT))
        self.assertEqual(self.plan["sources"]["adaptive_operator"], study.sha(study.ADAPTIVE))
        self.assertEqual(
            self.plan["protocol_sha256"], study.sha(self.runtime / "data/protocol.json")
        )
        for case in self.cases[:4]:
            self.assertEqual(
                self.plan["case_provenance"][case["case"]],
                dict(
                    source_day=case["source_day"],
                    tasks=len(case["tasks"]),
                    sha256=study.digest(case),
                ),
            )
        with self.assertRaises(FileExistsError):
            study.initialize(self.directory, self.runtime)

    def test_same_named_studies_cannot_share_trace_or_log_paths(self):
        with redirect_stdout(io.StringIO()):
            other = study.initialize(self.root / "different" / "study", self.runtime)
        self.assertNotEqual(other["trace_root"], self.plan["trace_root"])

    def _one_job_plan(self):
        plan = copy.deepcopy(self.plan)
        plan["variants"] = [dict(id="gate", profile="gate", overrides={}, seeds=[0])]
        plan["cases"] = [self.cases[0]["case"]]
        plan["seeds"] = [0]
        job = study.jobs(plan)[0]
        plan["execution_order"] = [job["id"]]
        plan["trace_root"] = str(self.root / "evidence/trajectories")
        return plan, job

    def test_interrupted_log_does_not_prevent_failure_recording(self):
        plan, job = self._one_job_plan()
        logfile = Path(plan["trace_root"]).parent / "logs" / (job["id"] + ".log")
        logfile.parent.mkdir(parents=True)
        logfile.write_text("previous interrupted attempt\n")
        old_bytes = logfile.read_bytes()
        process = subprocess.CompletedProcess(args=[], returncode=1)
        with (
            patch.object(study, "check_sources", return_value=plan),
            patch.object(study, "verify"),
            patch.object(study.subprocess, "run", return_value=process) as launch,
            redirect_stdout(io.StringIO()),
        ):
            study.run_study(self.directory, workers=1)
        self.assertEqual(logfile.read_bytes(), old_bytes)
        trial = study.read(self.directory / "trials" / (job["id"] + ".json"))
        launch.assert_not_called()
        self.assertEqual(trial["status"], "interrupted")
        self.assertFalse(trial["row"]["valid"])
        self.assertIsNone(trial["row"]["F"])
        self.assertEqual(trial["sources"], plan["sources"])

    def test_compact_metrics_must_match_the_preserved_trace(self):
        plan, job = self._one_job_plan()
        row = physical_row(2)
        trace = Path(plan["trace_root"]) / (job["id"] + ".json.gz")
        trace.parent.mkdir(parents=True)
        contents = dict(
            job=job,
            variant=plan["variants"][0],
            case=self.cases[0],
            result=dict(**{key: row[key] for key in ("valid", *study.METRICS)}, search_log=[]),
            scoring=dict(
                F_linear_v2=row["F"], audit=dict(valid=True), objective_sha256="synthetic-objective"
            ),
            row=row,
            settings={},
            operator_activity=[],
        )
        trace.write_bytes(gzip.compress(json.dumps(contents).encode(), mtime=0))
        record = dict(
            **job,
            status="ok",
            row=row,
            independent_audit=dict(valid=True),
            case_sha256=study.digest(self.cases[0]),
            objective_sha256="synthetic-objective",
            plan_sha256=study.sha(self.directory / "plan.json"),
            sources=plan["sources"],
            trace=dict(path=str(trace), sha256=study.sha(trace), bytes=trace.stat().st_size),
            settings={},
            search=study.search_summary(contents["result"], {}, []),
        )
        path = self.directory / "trials" / (job["id"] + ".json")
        study.write_new(path, record)
        with (
            patch.object(study, "check_sources", return_value=plan),
            redirect_stdout(io.StringIO()),
        ):
            self.assertTrue(study.verify(self.directory, traces=True)["all_valid"])
        record["row"].update(F=1, T=900, R=900, D=5400)
        path.write_text(json.dumps(record))
        with (
            patch.object(study, "check_sources", return_value=plan),
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(ValueError):
                study.verify(self.directory, traces=True)


class SensitivityAnalysisTests(unittest.TestCase):
    def _paired_fixture(self):
        cases = ["wepa-day12-bin1", "wepa-day12-bin2", "wepa-day32-bin3"]
        plan = dict(
            cases=cases,
            seeds=[0, 1, 2],
            baseline="gate",
            variants=[
                dict(id="gate", profile="gate", seeds=[0, 1]),
                dict(id="candidate", profile="wide", seeds=[0, 1, 2]),
            ],
        )
        trials = []
        for case, scores in zip(cases, ((100, 200), (300, 500), (20, 40))):
            for seed, score in enumerate(scores):
                trials.append(
                    dict(variant="gate", case=case, seed=seed, status="ok", row=physical_row(score))
                )
                trials.append(
                    dict(
                        variant="candidate",
                        case=case,
                        seed=seed,
                        status="ok",
                        row=physical_row(score * 0.9),
                    )
                )
            trials.append(
                dict(variant="candidate", case=case, seed=2, status="ok", row=physical_row(10000))
            )
        return plan, trials

    def test_dates_have_equal_weight_and_unpaired_seeds_cannot_change_pairing(self):
        plan, trials = self._paired_fixture()
        bootstrap_inputs = []

        def descriptive_interval(values):
            values = list(values)
            bootstrap_inputs.append(values)
            return [min(values), max(values)]

        with patch.object(report, "bootstrap_ci", side_effect=descriptive_interval):
            result = report.analyze(plan, trials)
        gate = next(row for row in result["variants"] if row["variant"] == "gate")
        self.assertEqual(result["case_count"], 3)
        self.assertEqual(result["source_date_count"], 2)
        self.assertAlmostEqual(gate["means"]["F"], (275 + 30) / 2)
        self.assertEqual([len(values) for values in bootstrap_inputs], [2, 2, 2])
        comparison = result["comparisons"][0]
        self.assertEqual(comparison["paired_seeds"], [0, 1])
        self.assertEqual(comparison["excluded_seeds"]["candidate"], [2])
        self.assertEqual(comparison["expected_pairs"], 6)
        self.assertAlmostEqual(comparison["mean_paired_F_gain_percent"], 10)
        self.assertEqual((comparison["wins"], comparison["ties"], comparison["losses"]), (2, 0, 0))

    def test_failures_and_missing_records_remain_in_the_planned_denominator(self):
        plan, original = self._paired_fixture()
        key = ("candidate", plan["cases"][0], 0)
        for mode in ("failure", "missing"):
            with self.subTest(mode=mode):
                trials = copy.deepcopy(original)
                bad = next(
                    row for row in trials if (row["variant"], row["case"], row["seed"]) == key
                )
                if mode == "failure":
                    bad.update(
                        status="wall_timeout",
                        row=dict(valid=False, F=None),
                        error="kept original timeout",
                    )
                else:
                    trials.remove(bad)
                result = report.analyze(plan, trials)
                summary = next(row for row in result["variants"] if row["variant"] == "candidate")
                self.assertEqual(result["planned_trials"], 15)
                self.assertEqual(summary["expected"], 9)
                self.assertEqual(summary["valid"], 8)
                self.assertFalse(summary["complete"])
                self.assertIsNone(summary["means"]["F"])
                self.assertFalse(summary["pareto_efficient"])
                self.assertEqual(summary["failed"], mode == "failure")
                self.assertEqual(summary["missing"], mode == "missing")
                comparison = result["comparisons"][0]
                self.assertEqual(comparison["expected_pairs"], 6)
                self.assertEqual(comparison["valid_pairs"], 5)
                self.assertFalse(comparison["complete"])
                self.assertIsNone(comparison["mean_paired_F_gain_percent"])
                if mode == "failure":
                    status = next(row for row in result["trial_status"] if row.get("error"))
                    self.assertEqual(status["error"], "kept original timeout")

    def test_csv_uses_repository_lf_to_preserve_provenance(self):
        # .gitattributes enforces LF. A CSV's fingerprint must survive checkout.
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "summary.csv"
            report._csv(target, [dict(variant="候选", F=0.5)])
            raw = target.read_bytes()
            self.assertNotIn(b"\r\n", raw)
            self.assertTrue(raw.endswith(b"\n"))
            self.assertIn("候选".encode(), raw)

    def test_real_plan_schema_produces_both_paired_factorials(self):
        plan = dict(cases=["wepa-day12-bin1"], seeds=list(range(5)), variants=study.variants())
        trials = [
            dict(**job, status="ok", row=physical_row(job["seed"] + 1)) for job in study.jobs(plan)
        ]
        result = report.analyze(plan, trials)
        factorials = {row["name"]: row for row in result["factorials"]}
        self.assertEqual(set(factorials), {"budget_2x2", "adaptive_2x2"})
        for factorial in factorials.values():
            self.assertEqual(factorial["paired_seeds"], [0, 1, 2])
            self.assertEqual(len(factorial["cells"]), 4)
            self.assertTrue(factorial["complete"])
            for cell in factorial["cells"]:
                self.assertEqual(cell["means"]["F"], 2)


if __name__ == "__main__":
    unittest.main()
