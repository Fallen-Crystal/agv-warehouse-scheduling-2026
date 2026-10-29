"""Compatibility entry point for the installed, source-visible WEPA model."""

import argparse
import json
import warnings
from pathlib import Path

warnings.warn(
    "agv.wepa is a deprecated launcher; use agv run --profile wepa --algorithm <method> --case <case> --output <path>.",
    DeprecationWarning,
    stacklevel=2,
)


def main(argv=None):
    from agv.experiments.wepa import run_case

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default="wepa-day45-bin4335")
    parser.add_argument("--profile", default="gate")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        trace = run_case(args.case, args.profile, args.seed, args.output)
    except (ValueError, OSError) as error:
        parser.exit(2, f"agv-wepa: {error}\n")
    print(json.dumps(trace["row"], ensure_ascii=False))
    if not trace["row"]["valid"]:
        parser.exit(1, "WEPA execution did not pass independent validation; trace preserved\n")


if __name__ == "__main__":
    main()
