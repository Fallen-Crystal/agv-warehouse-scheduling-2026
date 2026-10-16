"""Historical provenance checks stay strict when new algorithms add source files."""

import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import verify_v4


class HistoricalAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.git("init", "--quiet")

    def git(self, *arguments):
        return (
            subprocess.run(
                ["git", "-C", str(self.root), *arguments],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            .stdout.decode()
            .strip()
        )

    def write(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)

    def commit(self):
        self.git("add", ".")
        self.git(
            "-c",
            "user.name=Audit Test",
            "-c",
            "commit.gpgsign=false",
            "-c",
            "core.hooksPath=" + str(self.root / "empty-hooks"),
            "-c",
            "user.email=audit@example.invalid",
            "commit",
            "--quiet",
            "-m",
            "test snapshot",
        )
        return self.git("rev-parse", "HEAD")

    def test_current_mode_uses_complete_current_hashes_without_git(self):
        hashes = {"one.py": "abc", "new.py": "def"}
        with patch.object(verify_v4, "source_hashes", return_value=hashes):
            self.assertEqual(
                verify_v4.source_snapshot(),
                {"revision": "current-working-tree", "hashes": hashes},
            )

    def test_historical_revision_enumerates_complete_tree_and_hashes_blob_content(self):
        tracked = {
            "a.py": b"print('source')\n",
            "web/app.js": b"const value = 1;\n",
            "web/index.html": b"<p>source</p>\n",
            "web/style.css": b"p {color: blue}\n",
            "data/model.json": b'{"weight": 2}\n',
        }
        for relative, content in tracked.items():
            self.write("src/agv/" + relative, content)
        self.write("src/agv/README.md", b"not a measured suffix\n")
        self.write("src/other.py", b"outside project source\n")
        revision = self.commit()
        self.write("src/agv/untracked.py", b"not in historical tree\n")
        self.write("src/agv/a.py", b"changed current content\n")
        with patch.object(verify_v4, "ROOT", self.root):
            snapshot = verify_v4.source_snapshot(revision[:10])
        self.assertEqual(snapshot["revision"], revision)
        self.assertEqual(
            snapshot["hashes"],
            {name: hashlib.sha256(content).hexdigest() for name, content in tracked.items()},
        )

    def test_extra_historical_file_rejects_partial_manifest(self):
        self.write("src/agv/a.py", b"a = 1\n")
        self.write("src/agv/extra.py", b"extra = 2\n")
        revision = self.commit()
        manifest = {
            "status": "complete",
            "source_hashes": {"a.py": hashlib.sha256(b"a = 1\n").hexdigest()},
        }
        with (
            patch.object(verify_v4, "ROOT", self.root),
            patch.object(verify_v4, "read_json", return_value=manifest),
        ):
            with self.assertRaisesRegex(ValueError, "file set or content"):
                verify_v4.audit(self.root, self.root / "example.json", revision)

    def test_default_mode_still_rejects_source_drift(self):
        manifest = {"status": "complete", "source_hashes": {"old.py": "abc"}}
        with (
            patch.object(verify_v4, "read_json", return_value=manifest),
            patch.object(verify_v4, "source_hashes", return_value={"old.py": "different"}),
        ):
            with self.assertRaisesRegex(ValueError, "snapshot has drifted"):
                verify_v4.audit(self.root, self.root / "example.json")

    def test_unknown_revision_and_empty_project_source_are_rejected(self):
        self.write("README.md", b"no project source\n")
        revision = self.commit()
        with patch.object(verify_v4, "ROOT", self.root):
            with self.assertRaisesRegex(ValueError, "no project source"):
                verify_v4.source_snapshot(revision)
            with self.assertRaisesRegex(ValueError, "Cannot read historical"):
                verify_v4.source_snapshot("missing-revision")
            with self.assertRaisesRegex(ValueError, "Cannot read historical"):
                verify_v4.source_snapshot("--help")

    def test_archived_review_validation_cannot_be_overwritten_by_revision_mode(self):
        results = self.root / "results"
        results.mkdir()
        output = results / "review-validation.json"
        output.write_text(json.dumps({"original": True}), encoding="utf-8")
        with patch(
            "sys.argv",
            [
                "verify_v4.py",
                "--results",
                str(results),
                "--source-revision",
                "HEAD",
                "--output",
                str(output),
            ],
        ):
            with self.assertRaisesRegex(ValueError, "must not overwrite"):
                verify_v4.main()
        self.assertEqual(json.loads(output.read_text()), {"original": True})


if __name__ == "__main__":
    unittest.main()
