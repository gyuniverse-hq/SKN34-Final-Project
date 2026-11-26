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
    # Resolve explicit operations in textual order, including multiple operations per clause.
    patterns = {
        "all": r"상품\s*조건\s*(?:전체|전부|모두)?\s*(?:해제|취소)\w*",
        "ingredients": r"성분\s*조건\s*(?:전체|전부|모두)?\s*(?:해제|취소)\w*",
        "budget_clear": r"(?:예산|가격)\s*(?:조건\s*)?(?:해제|취소)\w*",
        "budget": r"[\d,만천]+(?:\s*[\d,만천]+)*\s*원\s*(?:이하|미만)",
        "fragrance_clear": r"무향료\s*(?:조건\s*)?(?:해제|취소)\w*",
        "fragrance": r"무향료",
        "basis": r"현재가|실시간",
        "ingredient": _INGREDIENT,
    }
    events = sorted(
        (
            (m.start(), -len(m.group()), kind, m)
            for kind, pattern in patterns.items()
            for m in re.finditer(pattern, message)
        ),
        key=lambda item: item[:2],
    )
    remaining = list(message)
    end = 0
    for start, _, kind, match in events:
        if start < end:
            continue
        end = match.end()
        if kind == "all":
            filters = OwnedLookFilters()
        elif kind == "ingredients":
            filters.ingredient_conditions = []
            filters.fragrance_free = False
        elif kind == "budget_clear":
            filters.max_price_krw = None
        elif kind == "budget":
            filters.max_price_krw = _explicit_krw_budget(match.group())
        elif kind == "basis":
            filters.price_basis = "current_offer"
        elif kind in {"fragrance", "fragrance_clear"}:
            filters.fragrance_free = kind == "fragrance"
        else:
            name = match["quoted"] or match["named"]
            if name in {"제품", "상품", "립", "블러셔", "기억", "보유품"}:
                continue
            by_name = {
                normalized_ingredient(c.ingredient_name): c for c in filters.ingredient_conditions
            }
            key = normalized_ingredient(name)
            if match["clear"]:
                by_name.pop(key, None)
            else:
                by_name[key] = SearchIngredient(
                    ingredient_name=name,
                    operator="includes" if match["op"] == "포함" else "excludes",
                )
            if len(by_name) > 6:
                filters.unsupported = ["성분 조건은 별칭을 합쳐 최대 6개까지 확인 가능"]
            else:
                filters.ingredient_conditions = list(by_name.values())
        remaining[start:end] = " " * (end - start)
    leftover = re.sub(r"예산(?:은|을)?", "", "".join(remaining))
    if re.search(r"성분|향료|무향|저자극|제형|매트|글로시|지속력|포함|제외|\d\s*원|만원", leftover):
        filters.unsupported = list(dict.fromkeys([*filters.unsupported, "해석되지 않은 상품 조건"]))
    return filters


def has_filters(filters):
    return bool(
        filters.max_price_krw is not None
        or filters.ingredient_conditions
        or filters.fragrance_free
        or filters.price_basis != "collected_snapshot"
    )
