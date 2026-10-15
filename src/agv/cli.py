"""Installed CLI. All paths are caller-selected, independent of package location."""

import argparse
import json
import logging
import sys
import webbrowser
from pathlib import Path

from agv.dispatch.registry import SOLVERS, run_named
from agv.domain import example
from agv.evaluation.validation import validate
from agv.io.scenes import load_scene, pack_scene
from agv.io.storage import write_json


def main(argv=None):
    parser = argparse.ArgumentParser(prog="agv", description="Warehouse AGV scheduling experiments")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Generate or load a scene and save validated results")
    run.add_argument("--input", type=Path)
    run.add_argument("--algorithm", choices=SOLVERS, default="sipp_budget")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--tasks", type=int, default=12)
    run.add_argument("--profile", choices=("legacy", "v4"), default="legacy")
    run.add_argument("--mode", choices=("static", "dynamic"), default="static")
    run.add_argument(
        "--size", choices=("small", "medium", "large", "xlarge", "xxlarge"), default="small"
    )
    run.add_argument("--vehicles", type=int, default=4)
    run.add_argument("--layers", type=int, default=3)
    run.add_argument("--work-width", type=int, default=2)
    run.add_argument(
        "--obstacles", choices=("none", "columns", "columns_equipment"), default="none"
    )
    run.add_argument(
        "--horizon",
        type=int,
        help="Optional finite cutoff; V4 defaults to completion/stall termination",
    )
    run.add_argument("--overwrite", action="store_true")
    serve = sub.add_parser("serve", help="Start the local-only browser interface")
    serve.add_argument("--port", type=int, default=0)
    serve.add_argument("--no-browser", action="store_true")
    benchmark = sub.add_parser("benchmark", help="Run paired scenarios and solver ablations")
    benchmark.add_argument("--seeds", type=int, default=10)
    benchmark.add_argument("--map", type=Path, help="Include heldout MovingAI-derived MAPD scenes")
    benchmark.add_argument("--output", type=Path, required=True)
    benchmark_v4 = sub.add_parser(
        "benchmark-v4", help="Paired V4 profile comparison with fixed offline reference"
    )
    benchmark_v4.add_argument("--seeds", type=int, default=6)
    benchmark_v4.add_argument("--output", type=Path, required=True)
    data = sub.add_parser("fetch-data", help="Fetch the attributed public MovingAI warehouse map")
    data.add_argument("--output", type=Path, required=True)
    training = sub.add_parser("train", help="Train a transparent candidate ranker")
    training.add_argument("--map", type=Path, required=True)
    training.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            if args.input:
                scenario = load_scene(args.input)
            elif args.profile == "v4":
                from agv.warehouse.layout import generate

                scenario = generate(
                    seed=args.seed,
                    task_count=args.tasks,
                    mode=args.mode,
                    size=args.size,
                    vehicles=args.vehicles,
                    shelf_layers=args.layers,
                    work_width=args.work_width,
                    obstacle_layout=args.obstacles,
                    horizon=args.horizon,
                )
            else:
                scenario = example(
                    seed=args.seed,
                    task_count=args.tasks,
                    mode=args.mode,
                    size=args.size,
                    vehicles=args.vehicles,
                    horizon=args.horizon if args.horizon is not None else 600,
                )
            result = run_named(args.algorithm, scenario)
            validate(scenario, result)
            write_json(
                args.output,
                pack_scene(scenario, config={"algorithm": args.algorithm}, result=result),
                overwrite=args.overwrite,
            )
            print(
                json.dumps(
                    {k: result[k] for k in ("feasible", "completed", "makespan", "mean_flow_time")}
                )
            )
        elif args.command == "serve":
            from agv.web.app import create_server

            if not 0 <= args.port <= 65535:
                raise ValueError("port must be 0..65535")
            logging.basicConfig(level=logging.INFO)
            server = create_server(port=args.port)
            url = f"http://127.0.0.1:{server.server_port}/"
            print(url, flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
        elif args.command == "benchmark":
            from agv.experiments.benchmark import run_benchmark

            run_benchmark(args.output, seeds=args.seeds, public_map=args.map)
        elif args.command == "benchmark-v4":
            from agv.experiments.v4 import run_benchmark

            run_benchmark(args.output, args.seeds)
        elif args.command == "fetch-data":
            from agv.io.movingai import download_map

            print(download_map(args.output))
        elif args.command == "train":
            from agv.learning.train import train

            train(args.map, args.output)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        parser.exit(2, f"agv: {error}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
