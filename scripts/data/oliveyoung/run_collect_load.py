"""Entry point shared by skincare and makeup collection/load commands."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def run(kind: str) -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
    parser = argparse.ArgumentParser(
        description=f"Collect and load Olive Young {kind} data through a local snapshot"
    )
    parser.add_argument(
        "--phase", choices=("collect", "preflight", "apply", "run"), required=True
    )
    parser.add_argument("--mode", choices=("full", "incremental"), default="full")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument(
        "--confirm-unavailable",
        action="append",
        default=[],
        metavar="GOODS_NO",
        help="Manually confirm one listed but inaccessible product as unavailable",
    )
    from load_snapshot import add_arguments

    add_arguments(parser)
    args = parser.parse_args()
    if args.confirm_unavailable and args.phase not in {"collect", "run"}:
        parser.error("--confirm-unavailable is only valid during collection")
    if args.phase == "run" and args.target == "shared" and not args.execute_shared:
        parser.error("--phase run --target shared requires --execute-shared")
    if args.phase in {"collect", "run"}:
        from collect_snapshot import collect

        manifest = collect(
            kind,
            Path(args.snapshot_dir),
            args.workers,
            args.mode,
            args.confirm_unavailable,
        )
        if not manifest["complete"]:
            raise SystemExit(
                "Collection incomplete. Re-run this phase with the same snapshot folder."
            )
        if args.phase == "collect":
            return
    from load_snapshot import load

    args.kind = kind
    # The apply transaction stages and validates every CSV before writing rows.
    args.apply = args.phase in {"apply", "run"}
    asyncio.run(load(args))
