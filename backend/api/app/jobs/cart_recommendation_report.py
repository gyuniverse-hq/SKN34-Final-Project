"""Compare cart recommendation arms using approved orders and mature cart visits."""

import argparse
import asyncio
import json
from datetime import UTC, datetime

from app.services.cart_recommendation_service import experiment_report


def utc(value):
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Timestamp must include a UTC offset")
    return parsed.astimezone(UTC)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--id", required=True)
    parser.add_argument("--start", type=utc, required=True)
    parser.add_argument("--end", type=utc, required=True)
    parser.add_argument("--as-of", type=utc, required=True)
    parser.add_argument("--purchase-window-hours", type=int, required=True)
    args = parser.parse_args()
    if args.start >= args.end or args.purchase_window_hours < 1:
        parser.error("Experiment start must be before end and purchase window must be positive")
    report = asyncio.run(
        experiment_report(
            experiment=args.id,
            start=args.start,
            end=args.end,
            as_of=args.as_of,
            window_hours=args.purchase_window_hours,
        )
    )
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
