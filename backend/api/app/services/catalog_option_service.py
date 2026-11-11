from fastapi import Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import ApiError
from app.repositories.catalog_option_repository import CatalogOptionRepository
from app.schemas.catalog_options import (
    BudgetDecision,
    EvaluatedOption,
    OptionCategoriesResponse,
    OptionPrice,
    OptionSearchRequest,
    OptionSearchResponse,
    OptionSearchScope,
)
from app.services.ingredient_service import (
    IngredientService,
    get_ingredient_service,
    required_verdict,
)


def _budget(request: OptionSearchRequest, price: OptionPrice) -> BudgetDecision | None:
    cap = request.max_price_krw
    if cap is None:
        return None
    if request.price_basis == "current_sale":
        return BudgetDecision(
            price_basis=request.price_basis,
            max_price_krw=cap,
            verdict="UNKNOWN",
            reason="current_sale_price_unverified",
        )

    captured = price.collected
    if captured is None or captured.sale_price_krw is None or captured.collected_at_raw is None:
        return BudgetDecision(
            price_basis=request.price_basis,
            max_price_krw=cap,
            verdict="UNKNOWN",
            reason="collected_sale_price_unavailable",
            evidence_id=captured.evidence_id if captured else None,
        )
    within = captured.sale_price_krw <= cap
    return BudgetDecision(
        price_basis=request.price_basis,
        max_price_krw=cap,
        verdict="MATCH" if within else "NOT_MATCH",
        reason="within_budget_at_collection" if within else "over_budget_at_collection",
        evidence_id=captured.evidence_id,
    )


class CatalogOptionService:
    def __init__(self, catalog: CatalogOptionRepository, ingredients: IngredientService):
        self._catalog = catalog
        self._ingredients = ingredients

    async def categories(self) -> OptionCategoriesResponse:
        try:
            return OptionCategoriesResponse(categories=await self._catalog.categories())
        except (SQLAlchemyError, OSError) as exc:
            raise ApiError(
                503, "Catalog categories unavailable", "catalog_category_lookup_failed"
            ) from exc

    async def search(self, request: OptionSearchRequest) -> OptionSearchResponse:
        try:
            category = await self._catalog.start_search(request.category_id)
            if category is None:
                raise ApiError(400, "Unsupported category", "unsupported_category")
            total, candidates = await self._catalog.options(request)
        except (SQLAlchemyError, OSError) as exc:
            raise ApiError(
                503, "Catalog options unavailable", "catalog_option_lookup_failed"
            ) from exc

        ingredients = await self._ingredients.check_options(
            {option.option_id: option.product_id for option in candidates},
            request.ingredient_conditions,
            request.ingredient_evidence_since,
        )
        matches, excluded, unconfirmed = [], [], []
        errors = 0
        for candidate in candidates:
            info = ingredients[candidate.option_id]
            budget = _budget(request, candidate.price)
            verdicts = [check.verdict for check in info.review.conditions]
            if budget:
                verdicts.append(budget.verdict)
            verdict = required_verdict(verdicts)
            result = EvaluatedOption(
                **candidate.model_dump(),
                ingredients=info,
                budget_condition=budget,
                required_verdict=verdict,
            )
            if verdict == "MATCH":
                matches.append(result)
            elif verdict == "NOT_MATCH":
                excluded.append(result)
            else:
                unconfirmed.append(result)
            if info.error_code or "ERROR" in verdicts:
                errors += 1

        stop = request.offset + len(candidates)
        exhaustive = request.offset == 0 and stop >= total
        if errors:
            status = "partial_failure"
        elif matches:
            status = "matches"
        elif unconfirmed:
            status = "unconfirmed"
        elif exhaustive:
            status = "no_matches"
        else:
            status = "search_incomplete"
        return OptionSearchResponse(
            status=status,
            scope=OptionSearchScope(
                request=request,
                category=category,
                candidate_count=total,
                evaluated_count=len(candidates),
                next_offset=stop if stop < total else None,
                exhaustive=exhaustive,
                options_with_lookup_errors=errors,
            ),
            matches=matches,
            excluded=excluded,
            unconfirmed=unconfirmed,
        )


def get_catalog_option_service(
    session: AsyncSession = Depends(get_session),
    ingredients: IngredientService = Depends(get_ingredient_service),
) -> CatalogOptionService:
    return CatalogOptionService(CatalogOptionRepository(session), ingredients)
