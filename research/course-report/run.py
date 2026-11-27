"""Run the course report's joint or counterfactual scheduler on a registered case."""

import argparse
import hashlib
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

from cases import PROTOCOL, SIZES, WINDOWS, load_case

HERE = Path(__file__).resolve().parent
ARCHIVE = HERE.parent / "recommended-20261024" / "current" / "runtime.zip"
ARCHIVE_SHA256 = "3a71aa51cf8c6ac5ded1d98444d834f73dff794142b5a5f792ca5b722f868a7b"


def extract_runtime(directory):
    archive = ARCHIVE.read_bytes()
    if hashlib.sha256(archive).hexdigest() != ARCHIVE_SHA256:
        raise ValueError("The frozen WEPA runtime checksum does not match")
    with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
        bundle.extractall(directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=[*WINDOWS, *SIZES], default="day19")
    parser.add_argument("--mode", choices=("counterfactual", "joint", "fixed"), default="counterfactual")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--branch-budget", type=int, choices=range(7), metavar="0..6")
    parser.add_argument("--output", type=Path, help="Write the summary and the validated trajectory to JSON")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()
    if not 0 <= args.seed < 2**31:
        parser.error("--seed must be between 0 and 2147483647")
    if args.branch_budget is not None and args.mode != "counterfactual":
        parser.error("--branch-budget applies to counterfactual mode")
    if args.output and args.output.exists() and not args.overwrite:
        parser.error(f"output already exists: {args.output}")

    case = load_case(args.case)
    with tempfile.TemporaryDirectory(prefix="agv-course-") as temporary:
        extract_runtime(temporary)
        sys.path.insert(0, temporary)
        try:
            from joint_policy import execute, execute_counterfactual
        except ModuleNotFoundError as error:
            if error.name == "ortools":
                parser.exit(2, "Install OR-Tools with: python -m pip install -r research/course-report/requirements.txt\n")
            raise
        if args.mode == "counterfactual":
            row, result = execute_counterfactual(case, PROTOCOL, args.seed, branch_budget=args.branch_budget)
        else:
            row, result = execute(case, PROTOCOL, args.seed, allocation=args.mode)
    row = {**row, "mode": args.mode, "seed": args.seed, "tasks": len(case["tasks"])}
    if args.output:
        payload = json.dumps({"summary": row, "trajectory": result}, ensure_ascii=False, indent=2)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w" if args.overwrite else "x", encoding="utf-8") as output:
            output.write(payload + "\n")
    print(json.dumps(row, ensure_ascii=True))


if __name__ == "__main__":
    main()
