"""Read the V1 skincare exposure, cart and paid-order funnel."""

import argparse
import asyncio
import json
from datetime import UTC, datetime

from app.core.config import get_settings
from app.services.recommendation_feedback_service import skincare_funnel_report


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("Timestamp must include a UTC offset")
    return parsed.astimezone(UTC)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=timestamp, required=True)
    parser.add_argument("--end", type=timestamp, required=True)
    parser.add_argument("--as-of", type=timestamp, default=datetime.now(UTC))
    args = parser.parse_args()
    if not args.start < args.end <= args.as_of:
        parser.error("Expected start < end <= as-of")
    result = asyncio.run(skincare_funnel_report(args.start, args.end, args.as_of, get_settings()))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
