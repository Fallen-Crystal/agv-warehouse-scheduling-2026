"""Prepare a small, verified historical DQN runtime under ignored runs/.

The runtime uses archive bytes so the original frozen-prediction checks remain
valid. Retained main sources must match after line-ending normalization. Nothing
is restored into the production source tree.
"""

import argparse
import ast
import hashlib
import io
import json
import stat
import subprocess
import zipfile
from pathlib import Path, PurePosixPath

ARCHIVE_COMMIT = "ed2bd0a96930ea042aab31b845f1c8cc06dcc55d"
ARCHIVE_PATH = "research/dqn-experiment-v2/DQN(1).zip"
ARCHIVE_SHA256 = "241d5c3072e0eaf120e01c4c2df77bbd240fd0529c069f0740f94d4a9b6e82b6"
PREFIX = "adaptive_hungarian_ga_dqn_experiment_v2/"
EXPERIMENT = "research/dqn-experiment-v2/"
RESULTS = "results/adaptive_hungarian_learning_v2/"
IMPORT_ROOTS = ("", "baseline/", "baseline/engine/", "baseline/engine/src/")
RECOMMENDED = "research/recommended-20261024/current/"
RECOMMENDED_SHA256 = "3a71aa51cf8c6ac5ded1d98444d834f73dff794142b5a5f792ca5b722f868a7b"


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _git(repo, *arguments):
    return subprocess.check_output(["git", "-C", str(repo), *arguments])


def _safe_members(bundle, prefix=PREFIX):
    """Reject unsafe or ambiguous members before selecting any payload."""
    members = {}
    folded = set()
    for item in bundle.infolist():
        # ZipInfo sanitizes separators on Windows (and truncates NUL bytes).
        # Inspect the archive's original spelling before that information is lost.
        name = item.orig_filename
        path = PurePosixPath(name)
        key = name.rstrip("/").casefold()
        if (
            path.is_absolute()
            or name != item.filename
            or ".." in path.parts
            or "\\" in name
            or not name.startswith(prefix)
            or key in folded
            or stat.S_ISLNK(item.external_attr >> 16)
        ):
            raise ValueError("Unsafe or duplicate archive member: " + name)
        folded.add(key)
        if not item.is_dir():
            members[name.removeprefix(prefix)] = item
    return members


def _dependency_closure(bundle, members, entrypoints):
    def locate(module):
        stem = module.replace(".", "/")
        for root in IMPORT_ROOTS:
            for suffix in (".py", "/__init__.py"):
                candidate = root + stem + suffix
                if candidate in members:
                    return candidate
        return None

    selected = set()
    pending = list(entrypoints)
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        if name not in members:
            raise ValueError("Required archive source missing: " + name)
        selected.add(name)
        text = bundle.read(members[name]).decode("utf-8-sig")
        for node in ast.walk(ast.parse(text, filename=name)):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    raise ValueError("Unexpected relative runtime import: " + name)
                base = node.module or ""
                modules = [base, *(base + "." + alias.name for alias in node.names)]
            else:
                continue
            for module in modules:
                dependency = locate(module)
                if dependency is not None:
                    pending.append(dependency)
                    parts = module.split(".")
                    for length in range(1, len(parts)):
                        package = locate(".".join(parts[:length]))
                        if package:
                            pending.append(package)
    return selected


def _paths_bridge(original, repo, omitted_baseline):
    # Keep verify_baseline's 191 SHA comparisons; omitted evidence stays in Git.
    bridge = f"""

# Experiment-only support: verify omitted baseline evidence in the pinned ZIP.
_disk_sha = sha
_baseline_zip = None
_omitted_baseline = frozenset({sorted(omitted_baseline)!r})

def sha(path):
    global _baseline_zip
    candidate = Path(path)
    try:
        relative = candidate.resolve().relative_to(BASE.resolve()).as_posix()
    except ValueError:
        return _disk_sha(candidate)
    if candidate.exists() or relative not in _omitted_baseline:
        return _disk_sha(candidate)
    if _baseline_zip is None:
        import io
        import subprocess
        import zipfile
        payload = subprocess.check_output([
            "git", "-C", {str(repo)!r}, "show", {ARCHIVE_COMMIT + ":" + ARCHIVE_PATH!r}
        ])
        if hashlib.sha256(payload).hexdigest() != {ARCHIVE_SHA256!r}:
            raise ValueError("Historical runtime archive changed")
        _baseline_zip = zipfile.ZipFile(io.BytesIO(payload))
    payload = _baseline_zip.read({PREFIX + "baseline/"!r} + relative)
    return hashlib.sha256(payload).hexdigest()
"""
    return original + bridge.encode("utf-8")


def _context(destination, repo, main_ref):
    repo = Path(repo or Path(__file__).resolve().parents[1]).resolve()
    repo = Path(_git(repo, "rev-parse", "--show-toplevel").decode().strip())
    destination = Path(destination)
    if not destination.is_absolute():
        destination = repo / destination
    destination = destination.resolve()
    runs = (repo / "runs").resolve()
    if destination == runs or not destination.is_relative_to(runs):
        raise ValueError("Runtime destination must be a new directory inside repo/runs")
    if destination.exists():
        raise FileExistsError(destination)
    source_commit = _git(repo, "rev-parse", main_ref + "^{commit}").decode().strip()
    return repo, destination, source_commit


def _write_runtime(destination, payloads, manifest):
    destination.mkdir(parents=True, exist_ok=False)
    for name, raw in payloads.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(raw)
    with (destination / "runtime_manifest.json").open("x", encoding="utf-8") as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    return manifest


def prepare_recommended(destination, *, repo=None, main_ref="origin/main"):
    """Prepare the same verified runtime and source overlay as current/run.py.

    Invoke run_trial.py --profile PROFILE --case CASE --seed SEED --output NEW
    in a fresh subprocess with cwd=returned['runtime']. Unlike current/run.py,
    this experimental runtime allows explicitly requested comparison profiles.
    """
    repo, destination, source_commit = _context(destination, repo, main_ref)
    archive_path = RECOMMENDED + "runtime.zip"
    archive = _git(repo, "show", source_commit + ":" + archive_path)
    if _sha(archive) != RECOMMENDED_SHA256:
        raise ValueError("Recommended runtime archive SHA256 mismatch")
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        members = _safe_members(bundle, prefix="")
        payloads = {name: bundle.read(item) for name, item in members.items()}
    expected = json.loads(payloads["MANIFEST.sha256.json"])
    for name, digest in expected.items():
        if name not in payloads or _sha(payloads[name]) != digest:
            raise ValueError("Recommended runtime file SHA256 mismatch: " + name)
    overlay_paths = (
        _git(
            repo, "ls-tree", "-r", "--name-only", source_commit, RECOMMENDED + "code-guide/improved"
        )
        .decode()
        .splitlines()
    )
    overlays = {}
    for path in overlay_paths:
        if path.endswith(".py"):
            name = "improved/" + PurePosixPath(path).name
            raw = _git(repo, "show", source_commit + ":" + path)
            payloads[name] = raw
            overlays[name] = {"main_path": path, "sha256": _sha(raw)}
    manifest = {
        "schema": "agv-recommended-sensitivity-runtime-v1",
        "runtime": str(destination),
        "main_commit": source_commit,
        "archive": {
            "commit": source_commit,
            "path": archive_path,
            "sha256": RECOMMENDED_SHA256,
            "bytes": len(archive),
        },
        "preparer_sha256": _sha(Path(__file__).read_bytes()),
        "source_policy": "Verified recommended runtime ZIP plus exact main code-guide/improved overlay, matching current/run.py",
        "main_source_overlays": overlays,
        "archive_manifest_files_verified": len(expected),
        "files": {name: _sha(raw) for name, raw in payloads.items()},
        "materialized_bytes": sum(map(len, payloads.values())),
        "entrypoints": {
            "trial": "run_trial.py --profile PROFILE --case CASE --seed SEED --output NEW.json",
            "execute": "improved.execute.run(model, method=PROFILE, seed=SEED, objective=objective)",
            "independent_check": "objective.checked_score(model, result, objective)",
        },
        "qualification": "Experimental comparison runtime; original recommended launcher and default gate remain unchanged",
    }
    return _write_runtime(destination, payloads, manifest)


def prepare(destination, *, repo=None, main_ref="origin/main"):
    """Return provenance after preparing a new DQN runtime in repo/runs.

    Use a fresh subprocess with cwd=returned['runtime'] for runtime imports.
    adaptive_hungarian_learning.execute(case, protocol, agent, training=False,
    strategy='dqn', seed=0) is the callable execution interface. The original
    predict_adaptive_hungarian_dqn.py CLI also works without relaxing its checks.
    """
    repo, destination, source_commit = _context(destination, repo, main_ref)
    archive = _git(repo, "show", ARCHIVE_COMMIT + ":" + ARCHIVE_PATH)
    if _sha(archive) != ARCHIVE_SHA256:
        raise ValueError("Historical runtime archive SHA256 mismatch")
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        members = _safe_members(bundle)
        package = json.loads(bundle.read(members["PACKAGE_MANIFEST.json"]))["files"]
        frozen = json.loads(bundle.read(members[RESULTS + "manifest.json"]))
        baseline = json.loads(bundle.read(members["data/baseline-manifest.json"]))
        selected = _dependency_closure(
            bundle,
            members,
            ("adaptive_hungarian_learning.py", "predict_adaptive_hungarian_dqn.py"),
        )
        selected.update(frozen["hashes"])
        selected.update(
            {
                "data/baseline-manifest.json",
                "data/protocol.json",
                "data/hungarian_learning_protocol.json",
                "data/adaptive_hungarian_learning_protocol.json",
                "data/hungarian_prediction_example.json",
                *(
                    RESULTS + name
                    for name in (
                        "manifest.json",
                        "best.npz",
                        "latest.npz",
                        "selection.json",
                        "fit_complete.json",
                        "learning_curve.json",
                    )
                ),
            }
        )
        payloads = {name: bundle.read(members[name]) for name in sorted(selected)}
        for name, raw in payloads.items():
            if package.get(name) != _sha(raw):
                raise ValueError("Package file SHA256 mismatch: " + name)
        for name, digest in frozen["hashes"].items():
            if _sha(payloads[name]) != digest:
                raise ValueError("Frozen model source SHA256 mismatch: " + name)
        for name, digest in baseline.items():
            if _sha(bundle.read(members["baseline/" + name])) != digest:
                raise ValueError("Baseline archive SHA256 mismatch: " + name)

    tracked = set(
        _git(repo, "ls-tree", "-r", "--name-only", source_commit, EXPERIMENT).decode().splitlines()
    )
    source_comparison = {}
    for name, raw in payloads.items():
        if not name.endswith(".py"):
            continue
        current_path = EXPERIMENT + name
        item = {"archive_sha256": _sha(raw), "source": "pinned_historical_archive"}
        if current_path in tracked:
            current = _git(repo, "show", source_commit + ":" + current_path)
            same = current.decode("utf-8-sig").splitlines() == raw.decode("utf-8-sig").splitlines()
            item.update(main_sha256=_sha(current), normalized_equal=same)
            if not same:
                raise ValueError("Retained main implementation differs from archive: " + name)
        source_comparison[name] = item

    omitted = {name for name in baseline if "baseline/" + name not in payloads}
    payloads["paths.py"] = _paths_bridge(payloads["paths.py"], repo, omitted)
    manifest = {
        "schema": "agv-sensitivity-runtime-v1",
        "runtime": str(destination),
        "main_commit": source_commit,
        "archive": {
            "commit": ARCHIVE_COMMIT,
            "path": ARCHIVE_PATH,
            "sha256": ARCHIVE_SHA256,
            "bytes": len(archive),
        },
        "preparer_sha256": _sha(Path(__file__).read_bytes()),
        "source_policy": "Archive bytes; retained main Python sources must match after BOM/line-ending normalization",
        "source_comparison": source_comparison,
        "paths_bridge": "Only omitted baseline evidence is SHA-checked directly in the pinned Git ZIP; materialized sources remain disk-checked",
        "baseline_files_verified": len(baseline),
        "baseline_files_materialized": len(baseline) - len(omitted),
        "baseline_files_verified_in_archive": len(omitted),
        "files": {name: _sha(raw) for name, raw in payloads.items()},
        "materialized_bytes": sum(map(len, payloads.values())),
        "entrypoints": {
            "execute": "adaptive_hungarian_learning.execute(case, protocol, agent=None, *, training=False, strategy='dqn', seed=0)",
            "frozen_prediction": "predict_adaptive_hungarian_dqn.py --case-json data/hungarian_prediction_example.json --output NEW.json",
        },
        "qualification": "Prepared dependency runtime only; no training, test-date evaluation, or performance claim",
    }
    return _write_runtime(destination, payloads, manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="new directory inside ignored runs/")
    parser.add_argument("--main-ref", default="origin/main")
    parser.add_argument("--kind", choices=("dqn", "recommended"), default="dqn")
    args = parser.parse_args()
    operation = prepare if args.kind == "dqn" else prepare_recommended
    manifest = operation(args.output, main_ref=args.main_ref)
    print(
        json.dumps(
            {
                key: manifest[key]
                for key in (
                    "runtime",
                    "main_commit",
                    "archive",
                    "materialized_bytes",
                    "baseline_files_verified",
                    "baseline_files_materialized",
                    "entrypoints",
                )
                if key in manifest
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
