"""Local AR training pipeline with stable inputs and file outputs for automation."""

import argparse
import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.services.ar_palette_training_service import (
    experiment_report,
    export_dataset,
    synthetic_dataset,
    train_dataset,
)


def utc(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Timestamp must include a UTC offset")
    return parsed.astimezone(UTC)


def timing(command):
    command.add_argument("--as-of", type=utc, required=True)
    command.add_argument("--window-hours", type=int, default=24)
    command.add_argument("--grace-hours", type=int, default=24)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    synthetic = commands.add_parser("synthetic", help="Write a synthetic dataset for local tests")
    synthetic.add_argument("--output", required=True, type=Path)
    export = commands.add_parser(
        "export", help="Read AR observations and immutable feature snapshots"
    )
    export.add_argument("--output", required=True, type=Path)
    timing(export)
    train = commands.add_parser("train", help="Train and evaluate a candidate bundle")
    train.add_argument("--dataset", required=True, type=Path)
    train.add_argument("--output", required=True, type=Path)
    train.add_argument("--baseline", type=Path)
    train.add_argument("--code-revision")
    train.add_argument("--min-hit", type=float)
    train.add_argument("--min-lift", type=float)
    experiment = commands.add_parser("experiment", help="Compare session metrics by assigned arm")
    experiment.add_argument("--output", required=True, type=Path)
    experiment.add_argument("--id", required=True)
    experiment.add_argument("--start", required=True, type=utc)
    experiment.add_argument("--end", required=True, type=utc)
    experiment.add_argument("--min-sessions", type=int)
    experiment.add_argument("--min-lift", type=float)
    timing(experiment)
    args = parser.parse_args()
    if args.command == "synthetic":
        report = synthetic_dataset(args.output)
    elif args.command == "train":
        for value in (args.min_hit, args.min_lift):
            if value is not None and not 0 <= value <= 1:
                parser.error("Offline thresholds must be within [0, 1]")
        report = train_dataset(
            args.dataset,
            args.output,
            baseline=args.baseline,
            min_hit=args.min_hit,
            min_lift=args.min_lift,
            code_revision=args.code_revision,
        )
    else:
        if args.window_hours <= 0 or args.grace_hours < 0:
            parser.error("Observation window must be positive and receiving grace nonnegative")
        times = {
            "as_of": args.as_of,
            "window": timedelta(hours=args.window_hours),
            "grace": timedelta(hours=args.grace_hours),
        }
        if args.command == "export":
            report = asyncio.run(export_dataset(args.output, **times))
        else:
            if args.start >= args.end:
                parser.error("Experiment start must be before end")
            if args.min_sessions is not None and args.min_sessions < 1:
                parser.error("Minimum sessions must be positive")
            if args.min_lift is not None and not 0 <= args.min_lift <= 1:
                parser.error("Minimum lift must be within [0, 1]")
            report = asyncio.run(
                experiment_report(
                    args.output,
                    experiment=args.id,
                    start=args.start,
                    end=args.end,
                    min_sessions=args.min_sessions,
                    min_lift=args.min_lift,
                    **times,
                )
            )
    print(json.dumps(report, sort_keys=True, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "error": type(error).__name__}))
        raise SystemExit(1) from None
