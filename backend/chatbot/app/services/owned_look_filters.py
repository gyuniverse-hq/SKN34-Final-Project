"""Explicit user filters for N02; unknown expressions never become satisfied conditions."""

import re

from app.schemas.catalog import SearchIngredient
from app.schemas.owned_look_context import OwnedLookFilters
from app.services.beauty_consultation_service import _explicit_krw_budget
from app.services.compound_consultation_service import normalized_ingredient

_INGREDIENT = re.compile(
    r"(?:성분\s*['\"‘“](?P<quoted>[^'\"’”\n]{1,120})['\"’”]|"
    r"(?<![가-힣A-Za-z0-9-])(?P<named>[가-힣A-Za-z][가-힣A-Za-z0-9-]{1,119})\s*(?:성분)?)"
    r"\s*(?P<op>포함|제외)(?:\s*조건\s*(?P<clear>해제|취소))?"
)
_FILTER_HINT = re.compile(
    r"예산|가격|현재가|실시간|[\d,만천]+원|원\s*(?:이하|미만)|성분|향료|무향|포함|제외|상품\s*조건|저자극|제형|매트|글로시|지속력"
)


def filter_followup(message):
    return bool(_FILTER_HINT.search(message))


def update_filters(previous, message):
    filters = previous.model_copy(deep=True) if previous else OwnedLookFilters()
    if not filter_followup(message):
        return filters
    # Questions, reported speech and negative predicates require clarification.
    if re.search(r"\?|라고|다고|친구|말고|하지\s*마|아니", message):
        filters.unsupported = ["조건 변경의 의미 확인 필요"]
        return filters
    remaining = message
    if re.search(r"상품\s*조건\s*(?:전체|전부|모두)?\s*(?:해제|취소)", remaining):
        return OwnedLookFilters()
    if re.search(r"(?:예산|가격)\s*(?:조건\s*)?(?:해제|취소)", remaining):
        filters.max_price_krw = None
        remaining = re.sub(r"(?:예산|가격)\s*(?:조건\s*)?(?:해제|취소)\w*", "", remaining)
    budget = _explicit_krw_budget(remaining)
    if budget is not None:
        filters.max_price_krw = budget
        remaining = re.sub(r"[\d,만천\s]+원\s*(?:이하|미만)", "", remaining)
        remaining = re.sub(r"예산(?:은|을)?", "", remaining)
    if re.search(r"현재가|실시간", message):
        filters.price_basis = "current_offer"
    if re.search(r"성분\s*조건\s*(?:전체|전부|모두)?\s*(?:해제|취소)", remaining):
        filters.ingredient_conditions = []
        filters.fragrance_free = False
        remaining = re.sub(r"성분\s*조건\s*(?:전체|전부|모두)?\s*(?:해제|취소)\w*", "", remaining)
    if re.search(r"무향료\s*(?:조건\s*)?(?:해제|취소)", remaining):
        filters.fragrance_free = False
        remaining = re.sub(r"무향료\s*(?:조건\s*)?(?:해제|취소)\w*", "", remaining)
    if "무향료" in remaining:
        filters.fragrance_free = True
        remaining = remaining.replace("무향료", "")
    by_name = {normalized_ingredient(c.ingredient_name): c for c in filters.ingredient_conditions}
    for match in _INGREDIENT.finditer(remaining):
        name = match["quoted"] or match["named"]
        if name in {"제품", "상품", "립", "블러셔", "기억", "보유품"}:
            continue
        key = normalized_ingredient(name)
        if match["clear"]:
            by_name.pop(key, None)
        else:
            by_name[key] = SearchIngredient(
                ingredient_name=name, operator="includes" if match["op"] == "포함" else "excludes"
            )
        remaining = remaining.replace(match.group(), "", 1)
    if len(by_name) > 6:
        filters.unsupported = ["성분 조건은 별칭을 합쳐 최대 6개까지 확인 가능"]
    else:
        filters.ingredient_conditions = list(by_name.values())
    if re.search(
        r"성분|향료|무향|저자극|제형|매트|글로시|지속력|포함|제외|\d\s*원|만원|예산", remaining
    ):
        filters.unsupported = list(dict.fromkeys([*filters.unsupported, "해석되지 않은 상품 조건"]))
    return filters


def has_filters(filters):
    return bool(
        filters.max_price_krw is not None or filters.ingredient_conditions or filters.fragrance_free
    )
