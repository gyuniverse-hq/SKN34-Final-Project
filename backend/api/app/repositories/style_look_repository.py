import json
from functools import lru_cache
from pathlib import Path

from app.schemas.style_look import StyleLook


@lru_cache(maxsize=1)
def _load() -> list[StyleLook]:
    path = Path(__file__).resolve().parents[1] / "catalog_data" / "style_looks.json"
    return [StyleLook.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))]


class StyleLookRepository:
    async def list_looks(self) -> list[StyleLook]:
        return _load()
