from uuid import UUID

from sqlalchemy import and_, any_, exists, func, or_, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.aihub import (
    AihubClaimPublicationRow as Publication,
)
from app.models.aihub import (
    AihubClaimReviewRow as Review,
)
from app.models.aihub import (
    AihubClaimVersionRow as Claim,
)
from app.models.aihub import (
    AihubDatasetReleaseRow as Release,
)
from app.models.aihub import (
    AihubKnowledgeDocumentRow as Document,
)
from app.models.aihub import (
    AihubQaCaseRawRow as RawQa,
)
from app.models.aihub import (
    AihubQaClaimRow as QaClaim,
)
from app.models.aihub import (
    AihubQaSourceLinkRow as QaSource,
)
from app.models.raw_mfds_ingredient import RawMfdsIngredientRow as Mfds
from app.repositories.ingredient_identity_repository import IngredientIdentityRepository
from app.schemas.claim_publication import ClaimUse


class ClaimPublicationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def resolve_ingredient_keys(self, names: list[str]) -> set[tuple[int, str]]:
        resolver = IngredientIdentityRepository(self.session)
        keys = set()
        for name in dict.fromkeys(names):
            identity = await resolver.resolve(name)
            if identity is not None:
                keys.add((identity.mfds_ingredient_id, identity.source_hash))
        return keys

    async def eligible(
        self,
        *,
        ingredient_keys: set[tuple[int, str]] | None = None,
        publication_ids: list[UUID] | None = None,
        use: ClaimUse | None = None,
        allow_test: bool = False,
    ):
        newer_claim = aliased(Claim)
        newer_document = aliased(Document)
        origin_release = aliased(Release)
        newer_revision = (
            exists()
            .where(newer_claim.claim_key == Claim.claim_key, newer_claim.revision > Claim.revision)
            .correlate(Claim)
        )
        newer_source = (
            exists()
            .where(
                newer_document.source_identifier == Document.source_identifier,
                newer_document.document_id > Document.document_id,
            )
            .correlate(Document)
        )
        claim_qa = (
            exists()
            .where(QaClaim.seq == RawQa.seq, QaClaim.claim_version_id == Claim.claim_version_id)
            .correlate(RawQa, Claim)
        )
        source_qa = (
            exists()
            .where(QaSource.seq == RawQa.seq, QaSource.document_id == Document.document_id)
            .correlate(RawQa, Document)
        )
        restricted_origin = exists(
            select(RawQa.seq)
            .join(origin_release, origin_release.release_id == RawQa.release_id)
            .where(origin_release.rights_status != "service_approved", or_(claim_qa, source_qa))
            .correlate(Claim, Document)
        )
        review_source_matches = (
            exists()
            .where(
                QaSource.seq == Review.seq,
                QaSource.source_position == Review.source_position,
                QaSource.document_id == Document.document_id,
                QaSource.match_status == "matched",
            )
            .correlate(Review, Document)
        )
        statement = (
            select(Publication, Claim, Review, Document, Mfds)
            .join(Claim, Claim.claim_version_id == Publication.claim_version_id)
            .join(Review, Review.claim_id == Publication.source_review_id)
            .join(Document, Document.document_id == Review.document_id)
            .join(Release, Release.release_id == Publication.release_id)
            .join(Mfds, Mfds.ingredient_id == Publication.ingredient_id)
            .where(
                Publication.revoked_at.is_(None),
                Claim.review_progress == "completed",
                Claim.approval_status.in_(("approved", "limited_approved")),
                Claim.canonical_text == Publication.summary,
                Review.claim_version_id == Claim.claim_version_id,
                Review.rights_status == "service_approved",
                or_(
                    Review.support_status == "direct",
                    and_(
                        Review.support_status == "limited",
                        Claim.approval_status == "limited_approved",
                    ),
                ),
                or_(Review.source_position.is_(None), review_source_matches),
                Document.review_status == "approved",
                Document.rights_status == "service_approved",
                Document.source_version.is_not(None),
                Release.rights_status == "service_approved",
                Mfds.is_current.is_(True),
                Mfds.source_hash == Publication.mfds_source_hash,
                ~newer_revision,
                ~newer_source,
                ~restricted_origin,
            )
            .order_by(Publication.published_at.desc(), Publication.publication_id)
            .limit(128)
        )
        if not allow_test:
            statement = statement.where(Publication.test_only.is_(False))
        if use is not None:
            statement = statement.where(use == any_(Claim.approved_uses))
        if publication_ids is not None:
            statement = statement.where(Publication.publication_id.in_(publication_ids))
        else:
            statement = statement.where(
                tuple_(Publication.ingredient_id, Publication.mfds_source_hash).in_(
                    sorted(ingredient_keys or ())
                )
            )
        return (await self.session.execute(statement)).all()

    async def lock_claim(self, claim_version_id: int) -> Claim | None:
        return await self.session.scalar(
            select(Claim).where(Claim.claim_version_id == claim_version_id).with_for_update()
        )

    async def add_eligible(self, publication: Publication) -> bool:
        async with self.session.begin_nested() as savepoint:
            self.session.add(publication)
            await self.session.flush()
            if not await self.eligible(
                publication_ids=[publication.publication_id], allow_test=publication.test_only
            ):
                await savepoint.rollback()
                return False
        return True

    async def revoke(self, publication_id: UUID) -> bool:
        result = await self.session.execute(
            update(Publication)
            .where(Publication.publication_id == publication_id, Publication.revoked_at.is_(None))
            .values(revoked_at=func.clock_timestamp())
            .returning(Publication.publication_id)
        )
        return result.scalar_one_or_none() is not None
