from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict

from .config import Settings
from .copilot_runner import run_jev, run_traditional
from .models import DEFAULT_ORDER
from .simulation import render_simulation


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare Jev and traditional Harness Agents.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    simulate = subparsers.add_parser("simulate", help="Print an offline, side-effect-free trace.")
    simulate.add_argument("--request", default=DEFAULT_ORDER)

    run = subparsers.add_parser("run", help="Run one live harness against the MCD MCP server.")
    run.add_argument("--engine", choices=["jev", "traditional"], required=True)
    run.add_argument("--request", default=DEFAULT_ORDER)
    run.add_argument("--commit", action="store_true", help="Expose create-order. May place a real order.")

    benchmark = subparsers.add_parser("benchmark", help="Measure both live harnesses once.")
    benchmark.add_argument("--request", default=DEFAULT_ORDER)
    return parser


async def _run_live(engine: str, request: str, commit: bool) -> None:
    settings = Settings.from_env()
    runner = run_jev if engine == "jev" else run_traditional
    result = await runner(request, settings, commit=commit)
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


async def _benchmark(request: str) -> None:
    settings = Settings.from_env()
    results = [
        await run_traditional(request, settings),
        await run_jev(request, settings),
    ]
    print(json.dumps([asdict(result) for result in results], ensure_ascii=False, indent=2))


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "simulate":
        print(render_simulation(args.request))
        return
    if args.command == "run":
        asyncio.run(_run_live(args.engine, args.request, args.commit))
        return
    asyncio.run(_benchmark(args.request))


if __name__ == "__main__":
    main()

