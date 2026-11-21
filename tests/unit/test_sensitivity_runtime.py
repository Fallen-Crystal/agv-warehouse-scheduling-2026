import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_sensitivity_runtime as runtime


class SensitivityRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.repo = Path(__file__).resolve().parents[2]
        (self.repo / "runs").mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="runtime-unit-", dir=self.repo / "runs")
        self.addCleanup(self.temporary.cleanup)
        self.target = Path(self.temporary.name) / "runtime"

    def test_full_baseline_verification_and_materialized_corruption(self):
        runtime.prepare_recommended(self.target, repo=self.repo, main_ref="HEAD")
        command = [
            sys.executable,
            "-B",
            "-c",
            "from paths import verify_baseline; print(verify_baseline())",
        ]
        result = subprocess.run(
            command, cwd=self.target, capture_output=True, text=True, check=True
        )
        self.assertEqual(result.stdout.strip(), "191")
        source = self.target / "baseline/objective.py"
        original = source.read_bytes()
        try:
            source.write_bytes(original + b"\n# corrupted\n")
            result = subprocess.run(command, cwd=self.target, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Frozen baseline differs: objective.py", result.stderr)
        finally:
            source.write_bytes(original)

    def test_recommended_archive_and_main_overlay_are_verified(self):
        target = self.target
        manifest = runtime.prepare_recommended(target, repo=self.repo, main_ref="HEAD")
        self.assertEqual(manifest["archive"]["sha256"], runtime.RECOMMENDED_SHA256)
        self.assertGreater(manifest["archive_manifest_files_verified"], 300)
        self.assertGreater(len(manifest["main_source_overlays"]), 10)
        for name, overlay in manifest["main_source_overlays"].items():
            current = subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(self.repo),
                    "show",
                    manifest["main_commit"] + ":" + overlay["main_path"],
                ]
            )
            self.assertEqual((target / name).read_bytes(), current)
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                "from paths import verify_baseline; print(verify_baseline())",
            ],
            cwd=target,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stdout.strip(), "191")

    def test_existing_destination_and_outside_runs_are_rejected(self):
        self.target.mkdir()
        original = self.target / "original.txt"
        original.write_bytes(b"preserve existing data")
        with self.assertRaises(FileExistsError):
            runtime.prepare(self.target, repo=self.repo, main_ref="HEAD")
        with self.assertRaises(ValueError):
            runtime.prepare(self.repo / "untracked-runtime", repo=self.repo, main_ref="HEAD")
        self.assertEqual(original.read_bytes(), b"preserve existing data")
        self.assertEqual(list(self.target.iterdir()), [original])

    def test_archive_identity_is_checked_before_writing(self):
        git = runtime._git

        def corrupted_archive(repo, *arguments):
            if arguments[0] == "show":
                return b"in-memory bytes that fail the pinned archive checksum"
            return git(repo, *arguments)

        for operation in (runtime.prepare, runtime.prepare_recommended):
            with self.subTest(operation=operation.__name__):
                with patch.object(runtime, "_git", side_effect=corrupted_archive):
                    with self.assertRaisesRegex(ValueError, "archive SHA256 mismatch"):
                        operation(self.target, repo=self.repo, main_ref="HEAD")
                self.assertFalse(self.target.exists())

    def test_unsafe_and_duplicate_members_are_rejected(self):
        for names in (
            [runtime.PREFIX + "../escape.py"],
            ["/absolute.py"],
            [runtime.PREFIX + "nested\\escape.py"],
            [runtime.PREFIX + "same.py", runtime.PREFIX + "same.py"],
            [runtime.PREFIX + "Same.py", runtime.PREFIX + "same.py"],
        ):
            with self.subTest(names=names):
                payload = io.BytesIO()
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", UserWarning)
                    with zipfile.ZipFile(payload, "w") as bundle:
                        for name in names:
                            # Keep malicious bytes even when the Windows writer
                            # would normalize a string filename first.
                            item = zipfile.ZipInfo("fixture.py")
                            item.filename = item.orig_filename = name
                            bundle.writestr(item, "pass")
                with zipfile.ZipFile(payload) as bundle:
                    with self.assertRaisesRegex(ValueError, "Unsafe or duplicate"):
                        runtime._safe_members(bundle)

    def test_original_archive_spelling_is_checked_after_windows_normalization(self):
        item = zipfile.ZipInfo(runtime.PREFIX + "nested/escape.py")
        item.orig_filename = runtime.PREFIX + "nested\\escape.py"
        with patch.object(zipfile.ZipFile, "infolist", return_value=[item]):
            with zipfile.ZipFile(io.BytesIO(), "w") as bundle:
                with self.assertRaisesRegex(ValueError, "Unsafe or duplicate"):
                    runtime._safe_members(bundle)


class HistoricalDQNRuntimeIntegrationTests(unittest.TestCase):
    """Full historical checks are optional when checkout has no old Git objects."""

    @classmethod
    def setUpClass(cls):
        cls.repo = Path(__file__).resolve().parents[2]
        available = subprocess.run(
            [
                "git",
                "-C",
                str(cls.repo),
                "cat-file",
                "-e",
                runtime.ARCHIVE_COMMIT + ":" + runtime.ARCHIVE_PATH,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if available.returncode:
            raise unittest.SkipTest(
                "Historical DQN archive is absent from this checkout. "
                "For the full integration check, run git fetch origin "
                + runtime.ARCHIVE_COMMIT
                + " to make the pinned historical object available. "
                "Independent safety and HEAD recommended-runtime tests still run."
            )
        (cls.repo / "runs").mkdir(exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(
            prefix="dqn-runtime-integration-", dir=cls.repo / "runs"
        )
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.target = Path(cls.temporary.name) / "runtime"
        cls.manifest = runtime.prepare(cls.target, repo=cls.repo, main_ref="HEAD")

    def test_minimal_payload_and_frozen_source_identity(self):
        manifest = self.manifest
        self.assertEqual(manifest["baseline_files_verified"], 191)
        self.assertGreater(manifest["baseline_files_verified_in_archive"], 0)
        self.assertLess(len(manifest["files"]), 100)
        self.assertLess(manifest["materialized_bytes"], 4_000_000)
        for name, expected in manifest["files"].items():
            self.assertEqual(
                hashlib.sha256((self.target / name).read_bytes()).hexdigest(), expected
            )
            self.assertNotIn("/traces/", name)
            self.assertNotIn("train_e", name)
            self.assertFalse(name.startswith("deliverables/"))
        for item in manifest["source_comparison"].values():
            if "main_sha256" in item:
                self.assertTrue(item["normalized_equal"])
        frozen = json.loads((self.target / runtime.RESULTS / "manifest.json").read_text())
        for name, expected in frozen["hashes"].items():
            self.assertEqual(manifest["files"][name], expected)

    def test_original_baseline_verifier_checks_unmaterialized_archive_evidence(self):
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                "from paths import verify_baseline; print(verify_baseline())",
            ],
            cwd=self.target,
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertEqual(result.stdout.strip(), "191")


if __name__ == "__main__":
    unittest.main()
