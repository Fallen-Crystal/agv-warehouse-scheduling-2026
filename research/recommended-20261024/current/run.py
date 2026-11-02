"""Run the readable implementation with the frozen experiment dependencies."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

HERE = Path(__file__).resolve().parent
EXPECTED = "3a71aa51cf8c6ac5ded1d98444d834f73dff794142b5a5f792ca5b722f868a7b"

def main():
    archive = HERE / "runtime.zip"
    if hashlib.sha256(archive.read_bytes()).hexdigest() != EXPECTED:
        raise ValueError("Runtime archive changed")
    arguments = sys.argv[1:]
    if any(arg == "--profile" or arg.startswith("--profile=") for arg in arguments):
        raise ValueError("Recommended launcher fixes gate")
    # The ZIP supplies frozen dependencies and historical evidence. The readable
    # modules below are the active implementation, not a second code example.
    with tempfile.TemporaryDirectory(prefix="agv-readable-", dir=HERE) as directory:
        runtime = Path(directory)
        with zipfile.ZipFile(archive) as bundle:
            for name in bundle.namelist():
                if not (runtime / name).resolve().is_relative_to(runtime.resolve()):
                    raise ValueError("Unsafe archive path")
            bundle.extractall(runtime)
        manifest = json.loads((runtime / "MANIFEST.sha256.json").read_text())
        for name, digest in manifest.items():
            if hashlib.sha256((runtime / name).read_bytes()).hexdigest() != digest:
                raise ValueError("Extracted runtime changed: " + name)
        for source in (HERE / "code-guide/improved").glob("*.py"):
            shutil.copyfile(source, runtime / "improved" / source.name)
        environment = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        environment.pop("PYTHONPATH", None)
        return subprocess.call(
            [sys.executable, str(runtime / "run_trial.py"), "--profile", "gate", *arguments],
            env=environment,
        )

if __name__ == "__main__":
    sys.exit(main())
