import json
import logging
from collections import Counter
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.curated_video_rows import mention_payloads, published_looks
from app.schemas.consultation_recipe import ConsultationRecipe
from app.schemas.style_look import StyleLook

_DATA = Path(__file__).resolve().parents[1] / "catalog_data"
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _reviewed_recipes() -> dict[str, ConsultationRecipe]:
    # DB display metadata cannot bypass the separately reviewed registry.
    recipes = []
    for row in json.loads((_DATA / "reviewed_style_recipes.json").read_text(encoding="utf-8")):
        try:
            recipe = ConsultationRecipe.model_validate(row)
        except ValidationError:
            logger.warning("Invalid consultation recipe withheld")
            continue
        if not recipe.synthetic:
            recipes.append(recipe)
    counts = Counter(recipe.look_id for recipe in recipes)
    return {recipe.look_id: recipe for recipe in recipes if counts[recipe.look_id] == 1}


class StyleLookRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_looks(self) -> list[StyleLook]:
        looks = await published_looks(self._session, "style")
        products = await mention_payloads(self._session, "style")
        recipes = _reviewed_recipes()
        return [
            StyleLook.model_validate(
                {
                    "id": look["video_id"],
                    "title": look["catalog_title"],
                    "group": look["style_group"],
                    "tag": look["style_tag"],
                    "videoUrl": f"https://www.youtube.com/watch?v={look['video_id']}",
                    "products": products.get(look["video_id"], []),
                    "recipe": recipes.get(look["video_id"]),
                }
            )
            for look in looks
        ]
