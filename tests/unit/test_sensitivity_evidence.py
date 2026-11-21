"""Artificial consistency fixtures only; these are not real experiment results."""

import copy
import gzip
import json
import shutil
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

from scripts import verify_sensitivity_evidence as evidence


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


class PortableSensitivityEvidenceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(prefix="synthetic-evidence-unit-")
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.study, self.traces = self.root / "study", self.root / "ignored-traces"
        (self.study / "trials").mkdir(parents=True)
        self.traces.mkdir()
        self.case = dict(case="synthetic-day1", tasks=[dict(id=0)])
        objective = dict(
            version="linear-physical-v2-20261024",
            horizon_seconds=900.0,
            vehicles=6,
            speed_cells_per_second=1.0,
            seconds_per_step=1.0,
            weights=[0.5, 0.3, 0.2],
        )
        self.variant = dict(id="synthetic-gate", profile="gate", overrides={})
        self.ids = [f"{self.case['case']}__{self.variant['id']}__s{seed}" for seed in range(200)]
        self.plan = dict(
            study_id="ARTIFICIAL-UNIT-FIXTURE-NOT-EXPERIMENT-DATA",
            sources={"runner": "a" * 64},
            cases=[self.case["case"]],
            seeds=list(range(200)),
            variants=[self.variant],
            expected_trials=200,
            execution_order=self.ids,
            objective=objective,
            runtime="/nonexistent/unit-fixture-runtime",
            trace_root=str(self.traces),
            case_provenance={self.case["case"]: dict(sha256=evidence.digest(self.case), tasks=1)},
        )
        self.plan_path = self.study / "plan.json"
        self.freeze_path = self.study / "freeze.json"
        self._plan(self.plan)
        plan_sha = evidence.sha(self.plan_path.read_bytes())
        objective_sha = evidence.digest(objective, compact=True)
        row = dict(
            valid=True,
            T=900,
            R=90,
            D=600,
            p90=100,
            empty_distance=300,
            traffic_wait=2,
            cpu=1,
            wall=1.2,
            tasks=1,
        )
        row["F"] = 0.5 * row["T"] / 900 + 0.3 * row["R"] / 900 + 0.2 * row["D"] / 5400
        settings = dict(proxy=192, previews=6, generations=16, gate=True)
        activity = [dict(synthetic_fixture=True)]
        search = dict(
            searches=1,
            proxy_evaluations=4,
            previews=2,
            gate_decisions=1,
            proxy_cap_hits=0,
            preview_cap_hits=0,
            improvements=1,
            operator_activity=activity,
        )
        audit = dict(valid=True, synthetic_fixture=True)
        for seed, name in enumerate(self.ids):
            job = dict(id=name, case=self.case["case"], variant=self.variant["id"], seed=seed)
            result = dict(
                valid=True,
                method="gate",
                objective=objective,
                objective_sha256=objective_sha,
                **{key: row[key] for key in evidence.METRICS},
                search_log=[
                    dict(proxy_evaluations=4, previews=2, changed=True),
                    dict(mode="immediate_batch_matching"),
                ],
            )
            scoring = dict(
                F_linear_v2=row["F"],
                J_equivalent_seconds=900 * row["F"],
                audit=audit,
                objective_sha256=objective_sha,
                weighted_terms=dict(T=0.5, R=0.03, D=0.2 * 600 / 5400),
            )
            trace = dict(
                job=job,
                variant=self.variant,
                case=self.case,
                row=row,
                result=result,
                scoring=scoring,
                settings=settings,
                operator_activity=activity,
            )
            raw = gzip.compress(json.dumps(trace).encode(), mtime=0)
            path = self.traces / (name + ".json.gz")
            path.write_bytes(raw)
            trial = dict(
                **job,
                status="ok",
                row=row,
                settings=settings,
                search=search,
                case_sha256=evidence.digest(self.case),
                objective_sha256=objective_sha,
                plan_sha256=plan_sha,
                sources=self.plan["sources"],
                independent_audit=audit,
                trace=dict(path=str(path), sha256=evidence.sha(raw), bytes=len(raw)),
            )
            write(self.study / "trials" / (name + ".json"), trial)

    def _plan(self, plan):
        write(self.plan_path, plan)
        write(
            self.freeze_path,
            dict(plan_sha256=evidence.sha(self.plan_path.read_bytes()), sources=plan["sources"]),
        )

    def _rewrite_zip(self, change):
        path = self.study / "trajectories.zip"
        with zipfile.ZipFile(path) as archive:
            entries = [(info.filename, archive.read(info)) for info in archive.infolist()]
        entries = change(entries)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "w") as archive:
                for name, raw in entries:
                    archive.writestr(name, raw)
        manifest = evidence.read(self.study / "evidence.json")
        manifest["files"]["trajectories.zip"] = evidence.sha(path.read_bytes())
        write(self.study / "evidence.json", manifest)

    def test_portable_after_moving_study_and_removing_original_runtime_paths(self):
        result = evidence.seal(self.study)
        self.assertEqual(result["valid"], 200)
        self.assertTrue(result["all_checks"])
        self.assertFalse(result["physical_validation_rerun"])
        with zipfile.ZipFile(self.study / "trajectories.zip") as archive:
            self.assertEqual(set(archive.namelist()), {name + ".json.gz" for name in self.ids})
            for info in archive.infolist():
                self.assertEqual(info.date_time, (1980, 1, 1, 0, 0, 0))
                self.assertEqual(info.compress_type, zipfile.ZIP_STORED)
        moved = self.root / "different-absolute-path" / "published-study"
        moved.parent.mkdir()
        shutil.move(self.study, moved)
        shutil.rmtree(self.traces)
        self.assertEqual(evidence.verify(moved), result)

    def test_seal_refuses_overwrite(self):
        evidence.seal(self.study)
        old = (self.study / "trajectories.zip").read_bytes()
        with self.assertRaises(FileExistsError):
            evidence.seal(self.study)
        self.assertEqual((self.study / "trajectories.zip").read_bytes(), old)

    def test_missing_or_duplicate_planned_trial_cannot_seal(self):
        path = self.study / "trials" / (self.ids[-1] + ".json")
        original = path.read_bytes()
        path.unlink()
        with self.assertRaisesRegex(ValueError, "Trial set"):
            evidence.seal(self.study)
        path.write_bytes(original)
        plan = copy.deepcopy(self.plan)
        plan["seeds"][-1] = 0
        self._plan(plan)
        with self.assertRaisesRegex(ValueError, "Duplicate planned"):
            evidence.seal(self.study)
        self.assertFalse((self.study / "trajectories.zip").exists())

    def test_non_200_plan_and_invalid_status_cannot_seal(self):
        changed = copy.deepcopy(self.plan)
        changed["expected_trials"] = 199
        self._plan(changed)
        with self.assertRaisesRegex(ValueError, "200"):
            evidence.seal(self.study)
        self._plan(self.plan)
        path = self.study / "trials" / (self.ids[0] + ".json")
        trial = evidence.read(path)
        trial["status"] = "timeout"
        write(path, trial)
        with self.assertRaisesRegex(ValueError, "invalid trial"):
            evidence.seal(self.study)

    def test_self_consistent_compact_metric_tampering_cannot_seal(self):
        path = self.study / "trials" / (self.ids[0] + ".json")
        trial = evidence.read(path)
        trial["row"]["T"] += 90
        trial["row"]["F"] += 0.05
        write(path, trial)
        with self.assertRaisesRegex(ValueError, "row or settings"):
            evidence.seal(self.study)
        self.assertFalse((self.study / "evidence.json").exists())

    def test_trial_identity_and_trace_digest_must_match(self):
        path = self.study / "trials" / (self.ids[0] + ".json")
        trial = evidence.read(path)
        trial["id"] = self.ids[1]
        write(path, trial)
        with self.assertRaisesRegex(ValueError, "identity"):
            evidence.seal(self.study)
        trial["id"] = self.ids[0]
        trial["trace"]["sha256"] = "0" * 64
        write(path, trial)
        with self.assertRaisesRegex(ValueError, "Trajectory digest"):
            evidence.seal(self.study)

    def test_settings_search_case_source_and_recorded_audit_are_checked(self):
        path = self.study / "trials" / (self.ids[0] + ".json")
        original = evidence.read(path)
        for key, change in (
            ("settings", {**original["settings"], "previews": 3}),
            ("search", {**original["search"], "proxy_evaluations": 5}),
            ("case_sha256", "0" * 64),
            ("sources", {"runner": "0" * 64}),
            ("independent_audit", {"valid": False, "synthetic_fixture": True}),
        ):
            with self.subTest(field=key):
                changed = copy.deepcopy(original)
                changed[key] = change
                write(path, changed)
                with self.assertRaises(ValueError):
                    evidence.seal(self.study)
                self.assertFalse((self.study / "evidence.json").exists())
                self.assertFalse((self.study / "trajectories.zip").exists())

    def test_verify_rejects_path_traversal_and_duplicate_archive_members(self):
        evidence.seal(self.study)
        original_zip = (self.study / "trajectories.zip").read_bytes()
        original_manifest = (self.study / "evidence.json").read_bytes()
        for change in (
            lambda entries: [("../escape.json.gz", entries[0][1]), *entries[1:]],
            lambda entries: [*entries, entries[0]],
        ):
            with self.subTest(change=change):
                self._rewrite_zip(change)
                with self.assertRaisesRegex(ValueError, "archive member"):
                    evidence.verify(self.study)
                (self.study / "trajectories.zip").write_bytes(original_zip)
                (self.study / "evidence.json").write_bytes(original_manifest)

    def test_resigning_compact_digest_does_not_hide_trace_mismatch(self):
        evidence.seal(self.study)
        relative = "trials/" + self.ids[0] + ".json"
        path = self.study / relative
        trial = evidence.read(path)
        trial["row"]["T"] += 90
        trial["row"]["F"] += 0.05
        write(path, trial)
        manifest = evidence.read(self.study / "evidence.json")
        manifest["files"][relative] = evidence.sha(path.read_bytes())
        write(self.study / "evidence.json", manifest)
        with self.assertRaisesRegex(ValueError, "row or settings"):
            evidence.verify(self.study)


if __name__ == "__main__":
    unittest.main()
