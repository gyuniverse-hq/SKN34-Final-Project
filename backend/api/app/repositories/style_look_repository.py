import json
import logging
from collections import Counter
from functools import lru_cache
from pathlib import Path

from pydantic import ValidationError

from app.schemas.consultation_recipe import ConsultationRecipe
from app.schemas.style_look import StyleLook

_DATA = Path(__file__).resolve().parents[1] / "catalog_data"
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load() -> list[StyleLook]:
    rows = json.loads((_DATA / "style_looks.json").read_text(encoding="utf-8"))
    # Embedded metadata cannot bypass the separately reviewed registry.
    looks = [StyleLook.model_validate({**row, "recipe": None}) for row in rows]
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
    by_id = {recipe.look_id: recipe for recipe in recipes if counts[recipe.look_id] == 1}
    return [look.model_copy(update={"recipe": by_id.get(look.id)}) for look in looks]


class StyleLookRepository:
    async def list_looks(self) -> list[StyleLook]:
        return _load()
