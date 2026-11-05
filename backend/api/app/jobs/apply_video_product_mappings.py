import argparse
from pathlib import Path

from app.services.video_mapping_service import VideoMappingService, default_catalog


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=default_catalog())
    parser.add_argument(
        "--review", type=Path, default=Path("seed/source/video_product_mapping_review.csv")
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    result = VideoMappingService().apply(args.catalog, args.review, args.write)
    print(result)
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
