from uuid import UUID, uuid4

from fastapi import Depends
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.errors import ApiError
from app.models.aihub import AihubClaimPublicationRow
from app.repositories.claim_publication_repository import ClaimPublicationRepository
from app.schemas.claim_publication import (
    ClaimIngredientKey,
    ClaimSearchRequest,
    ClaimSearchResponse,
    PublishClaim,
    PublishedClaim,
    ReviewedApplicability,
)


class ClaimPublicationService:
    def __init__(self, repository: ClaimPublicationRepository):
        self.repository = repository

    async def search(self, request: ClaimSearchRequest) -> ClaimSearchResponse:
        return await self._search(request, allow_test=False)

    async def _search(
        self, request: ClaimSearchRequest, *, allow_test: bool
    ) -> ClaimSearchResponse:
        try:
            keys = await self.repository.resolve_ingredient_keys(request.ingredient_names)
            keys.update((item.mfds_ingredient_id, item.source_hash) for item in request.ingredients)
            if not keys and not request.publication_ids:
                return ClaimSearchResponse(claims=[])
            rows = await self.repository.eligible(
                ingredient_keys=keys,
                publication_ids=request.publication_ids or None,
                use=request.use,
                allow_test=allow_test,
            )
            claims = []
            for publication, claim, review, document, ingredient in rows:
                reviewed = ReviewedApplicability.model_validate(claim.applicability)
                identity = ClaimIngredientKey(
                    mfds_ingredient_id=ingredient.ingredient_id, source_hash=ingredient.source_hash
                )
                if reviewed.ingredient != identity or not reviewed.scope.applies(request.context):
                    continue
                claims.append(
                    PublishedClaim(
                        publication_id=publication.publication_id,
                        revision=claim.revision,
                        ingredient=identity,
                        ingredient_name=ingredient.name_ko,
                        summary=publication.summary,
                        use=request.use,
                        scope=reviewed.scope,
                        source_title=publication.source_title,
                        source_url=publication.source_url,
                        source_version=document.source_version,
                        study_type=review.study_type,
                    )
                )
                if len(claims) == 24:
                    break
        except (SQLAlchemyError, ValidationError) as exc:
            raise ApiError(503, "Published evidence lookup failed", "claim_lookup_failed") from exc
        return ClaimSearchResponse(claims=claims)

    async def publish(self, request: PublishClaim, *, test_only: bool = False) -> UUID:
        claim = await self.repository.lock_claim(request.claim_version_id)
        if claim is None:
            raise ApiError(404, "Claim revision not found", "claim_version_not_found")
        try:
            reviewed = ReviewedApplicability.model_validate(claim.applicability)
        except ValidationError as exc:
            raise ApiError(409, "Claim scope requires review", "claim_scope_unverified") from exc
        if reviewed.ingredient != request.ingredient:
            raise ApiError(
                409, "Ingredient version differs from review", "claim_ingredient_changed"
            )
        if len(claim.canonical_text) > 1200 or (
            claim.approval_status == "limited_approved"
            and not reviewed.scope.model_dump(exclude_none=True, exclude_defaults=True)
        ):
            raise ApiError(409, "Claim wording or scope requires review", "claim_scope_unverified")

        publication_id = uuid4()
        try:
            eligible = await self.repository.add_eligible(
                AihubClaimPublicationRow(
                    publication_id=publication_id,
                    claim_version_id=request.claim_version_id,
                    source_review_id=request.source_review_id,
                    release_id=request.release_id,
                    ingredient_id=request.ingredient.mfds_ingredient_id,
                    mfds_source_hash=request.ingredient.source_hash,
                    summary=claim.canonical_text,
                    source_title=request.source_title,
                    source_url=str(request.source_url),
                    publisher=request.publisher,
                    test_only=test_only,
                )
            )
            if not eligible:
                raise ApiError(409, "Claim fails publication requirements", "claim_ineligible")
        except IntegrityError as exc:
            raise ApiError(
                409, "Invalid or duplicate publication", "claim_publication_conflict"
            ) from exc
        return publication_id

    async def revoke(self, publication_id: UUID) -> bool:
        return await self.repository.revoke(publication_id)


def get_claim_publication_service(
    session: AsyncSession = Depends(get_session),
) -> ClaimPublicationService:
    return ClaimPublicationService(ClaimPublicationRepository(session))
