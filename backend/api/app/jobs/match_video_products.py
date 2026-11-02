import argparse
from pathlib import Path

from app.services.video_mapping_service import VideoMappingService, default_catalog


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=default_catalog())
    parser.add_argument(
        "--output", type=Path, default=Path("seed/source/video_product_mapping_review.csv")
    )
    parser.add_argument("--aliases", type=Path, default=Path("seed/source/brand_aliases.csv"))
    args = parser.parse_args()
    print(dict(VideoMappingService().match(args.catalog, args.output, args.aliases)))


if __name__ == "__main__":
    main()
