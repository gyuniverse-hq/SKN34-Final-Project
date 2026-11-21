"""Read existing AIHub excerpts and match them to verified ZIP body locations."""

import argparse
import asyncio
import json
import os
from collections import Counter
from collections.abc import Iterable
from contextlib import aclosing
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.schemas.knowledge import QuoteAlignment, QuoteSource
from app.services.knowledge_alignment_service import (
    MATCHER_VERSION,
    align_quotes,
    read_quote_sources,
    save_alignments,
)
from app.services.knowledge_extraction_service import validate_database_url


async def run(
    archive: Path,
    jar: Path,
    database_url: str,
    case_id: str | None = None,
    *,
    apply: bool = False,
) -> dict:
    engine = create_async_engine(validate_database_url(database_url))
    sessions = async_sessionmaker(engine)
    try:
        async with sessions() as session:
            sources = await read_quote_sources(session, case_id)
        results: list[tuple[QuoteSource, QuoteAlignment]] | None = [] if apply else None
        summary = await summarize(
            sources, archive, jar, details=case_id is not None, results=results
        )
        if results is not None:
            async with sessions() as session:
                summary["stored"] = await save_alignments(session, results, case_id)
        return summary
    finally:
        await engine.dispose()


async def summarize(
    sources: Iterable[QuoteSource],
    archive: Path,
    jar: Path,
    *,
    details: bool = False,
    results: list[tuple[QuoteSource, QuoteAlignment]] | None = None,
) -> dict:
    status: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    locations: Counter[str] = Counter()
    linked_documents = set()
    records = []
    async with aclosing(align_quotes(sources, archive, jar)) as matches:
        async for source, match in matches:
            if results is not None:
                results.append((source, match))
            status[match.status] += 1
            reasons[match.reason_code] += 1
            if source.document_id is not None:
                linked_documents.add(source.document_id)
            if match.candidates:
                locations["verified_rows"] += 1
                locations["verified_candidates"] += len(match.candidates)
                locations["multiple_candidates"] += len(match.candidates) > 1
                locations["multiple_blocks"] += any(len(c.spans) > 1 for c in match.candidates)
                locations["partial_at_least_half"] += match.status == "partial" and (
                    match.candidates[0].fraction >= 0.5
                )
            if details:
                records.append(
                    dict(
                        caseId=source.seq,
                        sourcePosition=source.source_position,
                        documentId=source.document_id,
                        sourceSha256=source.source_sha256,
                        status=match.status,
                        reason=match.reason_code,
                        candidates=[c.model_dump(mode="json") for c in match.candidates],
                    )
                )
    result = dict(
        matcherVersion=MATCHER_VERSION,
        total=status.total(),
        linkedDocuments=len(linked_documents),
        status=dict(status),
        reasons=dict(reasons),
        locations=dict(locations),
    )
    if details:
        result["records"] = records
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--jar", type=Path, required=True)
    parser.add_argument("--database-url", default=os.getenv("G5_DATABASE_URL"))
    parser.add_argument(
        "--case-id", help="Show locations (without raw text) for one existing case."
    )
    parser.add_argument("--apply", action="store_true", help="Store alignment results locally.")
    args = parser.parse_args()
    if not args.database_url:
        parser.error("Set G5_DATABASE_URL or provide --database-url")
    print(
        json.dumps(
            asyncio.run(
                run(args.archive, args.jar, args.database_url, args.case_id, apply=args.apply)
            )
        )
    )


if __name__ == "__main__":
    main()
