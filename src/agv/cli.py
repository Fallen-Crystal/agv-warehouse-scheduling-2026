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
    run.add_argument("--algorithm", choices=SOLVERS, default="sipp_conflict")
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--seed", type=int, default=0)
    run.add_argument("--tasks", type=int, default=12)
    run.add_argument("--overwrite", action="store_true")
    serve = sub.add_parser("serve", help="Start the local-only browser interface")
    serve.add_argument("--port", type=int, default=0)
    serve.add_argument("--no-browser", action="store_true")
    benchmark = sub.add_parser("benchmark", help="Run paired scenarios and solver ablations")
    benchmark.add_argument("--seeds", type=int, default=10)
    benchmark.add_argument("--map", type=Path, help="Include heldout MovingAI-derived MAPD scenes")
    benchmark.add_argument("--output", type=Path, required=True)
    data = sub.add_parser("fetch-data", help="Fetch the attributed public MovingAI warehouse map")
    data.add_argument("--output", type=Path, required=True)
    training = sub.add_parser("train", help="Train a transparent candidate ranker")
    training.add_argument("--map", type=Path, required=True)
    training.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            scenario = (
                load_scene(args.input)
                if args.input
                else example(seed=args.seed, task_count=args.tasks)
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
