import argparse
import asyncio
import csv
from collections import Counter
from pathlib import Path

from app.services.curated_video_check_service import get_curated_video_check_service


async def run(start: int, output: Path | None) -> None:
    service = get_curated_video_check_service()
    if not service.youtube.configured:
        print("YOUTUBE_API_KEY 없음")
        return
    results = await service.check(start)
    for row in results:
        print(f"{row['index']} {row['source']} {row['videoId']} {row['status']}")
    print(f"counts={dict(Counter(row['status'] for row in results))}")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["index", "source", "videoId", "status"])
            writer.writeheader()
            writer.writerows(results)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--from", dest="start", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.start < 0:
        parser.error("--from must be non-negative")
    asyncio.run(run(args.start, args.output))


if __name__ == "__main__":
    main()
