from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.knowledge_repository import KnowledgeRepository
from app.schemas.knowledge import DocumentExtraction


async def ingest_extraction(
    session: AsyncSession,
    result: DocumentExtraction,
    *,
    apply: bool = False,
) -> str:
    async with session.begin():
        if not apply:
            await session.execute(text("SET TRANSACTION READ ONLY"))
        repo = KnowledgeRepository(session)
        document_id, file_id = await repo.resolve(result)
        if not apply:
            return "verified_source"
        return "inserted" if await repo.save(result, document_id, file_id) else "already_exists"
