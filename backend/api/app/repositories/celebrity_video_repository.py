import json
from functools import lru_cache
from pathlib import Path

from app.schemas.celebrity_video import CelebrityVideo


@lru_cache(maxsize=1)
def _load() -> list[CelebrityVideo]:
    path = Path(__file__).resolve().parents[1] / "catalog_data" / "celebrity_videos.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return [CelebrityVideo.model_validate(item) for item in data]


class CelebrityVideoRepository:
    async def list_videos(self) -> list[CelebrityVideo]:
        return _load()
