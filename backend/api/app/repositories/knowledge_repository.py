import hashlib

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.aihub import (
    AihubKnowledgeDocumentFileRow,
    AihubKnowledgeDocumentRow,
    AihubQaSourceLinkRow,
)
from app.models.knowledge import (
    AihubDocumentBlockRow,
    AihubDocumentExtractionRow,
    AihubQuoteAlignmentRow,
)
from app.schemas.knowledge import DocumentExtraction, QuoteAlignment, QuoteSource


class KnowledgeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def read_quote_sources(
        self, case_id: str | None = None, *, lock_for_alignment: bool = False
    ) -> list[QuoteSource]:
        if not lock_for_alignment:
            await self.session.execute(
                text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            )
        link = AihubQaSourceLinkRow
        document = AihubKnowledgeDocumentRow
        statement = (
            select(
                link.seq,
                link.source_position,
                link.document_id,
                link.quote_raw,
                document.content_sha256,
            )
            .outerjoin(document, document.document_id == link.document_id)
            .where(func.btrim(link.quote_raw) != "")
            .order_by(link.seq, link.source_position)
        )
        if case_id is not None:
            statement = statement.where(link.seq == case_id)
        if lock_for_alignment:
            statement = statement.with_for_update(read=True, of=link)
        return [QuoteSource(*row) for row in (await self.session.execute(statement))]

    async def alignment_extraction_ids(
        self, document_ids: set[int], parser_version: str, extraction_version: str
    ) -> dict[tuple[int, str], int]:
        extraction = AihubDocumentExtractionRow
        statement = select(
            extraction.document_id, extraction.source_sha256, extraction.extraction_id
        ).where(
            extraction.document_id.in_(document_ids),
            extraction.parser_version == parser_version,
            extraction.extraction_version == extraction_version,
        )
        return {
            (document_id, source_sha256): extraction_id
            for document_id, source_sha256, extraction_id in await self.session.execute(statement)
        }

    async def save_alignment(
        self,
        source: QuoteSource,
        extraction_id: int | None,
        matcher_version: str,
        alignment: QuoteAlignment,
    ) -> bool:
        """Persist against the matching extraction in the caller's transaction."""
        if extraction_id is not None:
            extraction = await self.session.get(AihubDocumentExtractionRow, extraction_id)
            if (
                extraction is None
                or extraction.document_id != source.document_id
                or extraction.source_sha256 != source.source_sha256
                or (alignment.candidates and not extraction.verified)
            ):
                raise ValueError("Alignment extraction does not match document")
        spans = [span for candidate in alignment.candidates for span in candidate.spans]
        if spans:
            if extraction_id is None:
                raise ValueError("Candidate requires persisted extraction")
            data = await self.session.scalars(
                select(AihubDocumentBlockRow).where(
                    AihubDocumentBlockRow.extraction_id == extraction_id,
                    AihubDocumentBlockRow.block_order.in_({span.block_order for span in spans}),
                )
            )
            blocks = {block.block_order: block for block in data}
            for span in spans:
                block = blocks.get(span.block_order)
                if block is None or block.source_locator != span.source_locator.model_dump():
                    raise ValueError("Candidate has a different source locator")
                raw = block.text_raw.encode("utf-16-le")[2 * span.start_utf16 : 2 * span.end_utf16]
                if hashlib.sha256(raw.decode("utf-16-le").encode()).hexdigest() != span.text_sha256:
                    raise ValueError("Candidate text hash does not match persisted block")
        statement = (
            insert(AihubQuoteAlignmentRow)
            .values(
                seq=source.seq,
                source_position=source.source_position,
                quote_sha256=hashlib.sha256(source.quote_raw.encode()).hexdigest(),
                document_id=source.document_id,
                extraction_id=extraction_id,
                matcher_version=matcher_version,
                status=alignment.status,
                reason_code=alignment.reason_code,
                verified=bool(alignment.candidates),
                candidates=[
                    candidate.model_dump(mode="json") for candidate in alignment.candidates
                ],
            )
            .on_conflict_do_nothing(constraint="uq_aihub_alignment_input")
            .returning(AihubQuoteAlignmentRow.alignment_id)
        )
        return (await self.session.execute(statement)).scalar_one_or_none() is not None

    async def resolve(self, result: DocumentExtraction) -> tuple[int, int]:
        row = (
            await self.session.execute(
                select(AihubKnowledgeDocumentRow.document_id, AihubKnowledgeDocumentFileRow.file_id)
                .join(
                    AihubKnowledgeDocumentFileRow,
                    AihubKnowledgeDocumentFileRow.document_id
                    == AihubKnowledgeDocumentRow.document_id,
                )
                .where(
                    AihubKnowledgeDocumentRow.content_sha256 == result.source_sha256,
                    AihubKnowledgeDocumentFileRow.source_file_path == result.source_path,
                )
            )
        ).one_or_none()
        if row is None:
            raise ValueError("Document path/hash is not registered")
        return row[0], row[1]

    async def save(self, result: DocumentExtraction, document_id: int, file_id: int) -> bool:
        # The service transaction includes both the header and every block.
        statement = (
            insert(AihubDocumentExtractionRow)
            .values(
                document_id=document_id,
                file_id=file_id,
                source_sha256=result.source_sha256,
                detected_format=result.detected_format,
                parser_version=result.parser_version,
                extraction_version=result.extraction_version,
                status=result.status,
                verified=result.verified,
                block_count=len(result.blocks),
                warnings=result.warnings,
                error_code=result.error_code,
            )
            .on_conflict_do_nothing(constraint="uq_aihub_extraction_version")
            .returning(AihubDocumentExtractionRow.extraction_id)
        )
        extraction_id = (await self.session.execute(statement)).scalar_one_or_none()
        if extraction_id is None:
            return False
        for offset in range(0, len(result.blocks), 250):
            rows = [
                dict(
                    extraction_id=extraction_id,
                    block_order=b.block_order,
                    block_type=b.block_type,
                    text_raw=b.text_raw,
                    text_sha256=b.text_sha256,
                    source_locator=b.source_locator.model_dump(),
                    locator_version="body-v1",
                )
                for b in result.blocks[offset : offset + 250]
            ]
            await self.session.execute(insert(AihubDocumentBlockRow), rows)
        return True
