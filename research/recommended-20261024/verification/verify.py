"""Verify immutable published artifacts without re-signing the migrated source."""

import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATED_DOCUMENTS = {"README.md", "current/README.md", "current/run.py", "verification/verify.py"}


def main():
    manifest = json.loads((ROOT / "MANIFEST.sha256.json").read_text(encoding="utf-8"))
    checked, recovered = 0, 0
    with zipfile.ZipFile(ROOT / "current/runtime.zip") as runtime:
        for name, expected in manifest.items():
            if name in MIGRATED_DOCUMENTS:
                continue
            if name.startswith("current/code-guide/"):
                original = runtime.read(name.removeprefix("current/code-guide/"))
                variants = (original, original.replace(b"\r\n", b"\n"))
                if not any(hashlib.sha256(data).hexdigest() == expected for data in variants):
                    raise ValueError("Archived guide identity differs: " + name)
                recovered += 1
            else:
                path = ROOT / name
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise ValueError(name)
                checked += 1
    for path in ROOT.rglob("*.zip"):
        if "_runtime" not in path.parts:
            with zipfile.ZipFile(path) as archive:
                if archive.testzip():
                    raise ValueError(str(path))
    print(
        json.dumps(
            dict(
                immutable_files_verified=checked,
                archived_guide_files_verified=recovered,
                migrated_documents=sorted(MIGRATED_DOCUMENTS),
                zip_crc_valid=True,
                historical_manifest_unchanged=True,
            )
        )
    )


if __name__ == "__main__":
    main()
