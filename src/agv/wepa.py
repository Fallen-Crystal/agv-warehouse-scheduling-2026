"""Compatibility entry point for the installed, source-visible WEPA model."""

import argparse
import json
from pathlib import Path


def main(argv=None):
    from agv.experiments.wepa import run_case

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", default="wepa-day45-bin4335")
    parser.add_argument("--profile", default="gate")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    trace = run_case(args.case, args.profile, args.seed, args.output)
    print(json.dumps(trace["row"], ensure_ascii=False))


if __name__ == "__main__":
    main()
