import argparse
from pathlib import Path

from app.services.video_mapping_service import VideoMappingService, default_catalog

WRITE_DISABLED = (
    "--write 중지: 스타일·셀럽 화면은 DB(makeup_looks, raw_yt_product_mention)를 읽어 "
    "JSON에 쓴 매핑은 화면에 반영되지 않습니다. DB 기준 매핑 반영은 후속 작업입니다."
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=default_catalog())
    parser.add_argument(
        "--review", type=Path, default=Path("seed/source/video_product_mapping_review.csv")
    )
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.write:
        # The style/celebrity screens read the database now; writing the JSON copies would
        # change nothing on screen and let the two sources drift apart.
        raise SystemExit(WRITE_DISABLED)
    result = VideoMappingService().apply(args.catalog, args.review, args.write)
    print(result)
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
