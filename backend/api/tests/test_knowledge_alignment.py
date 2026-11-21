import asyncio
import hashlib
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.jobs.align_knowledge_quotes import run, summarize
from app.models.knowledge import AihubDocumentExtractionRow, AihubQuoteAlignmentRow
from app.repositories.knowledge_repository import KnowledgeRepository
from app.schemas.knowledge import DocumentExtraction, QuoteAlignment, QuoteSource
from app.services.knowledge_alignment_service import MATCHER_VERSION, QuoteMatcher
from app.services.knowledge_ingest_service import ingest_extraction
from tests.test_knowledge_extraction import (
    check_knowledge_schema,
    migrate_standard,
    seed_source_documents,
)
from tests.test_knowledge_extraction import (
    knowledge_database as shared_knowledge_database,
)

knowledge_database = shared_knowledge_database


def doc(*parts: str, cells: tuple[int, ...] = (), ole: bool = False) -> DocumentExtraction:
    blocks, start = [], 0
    kind = "ole" if ole else "ooxml"
    for i, part in enumerate(parts):
        length = len(part.encode("utf-16-le")) // 2
        blocks.append(
            dict(
                block_order=i,
                block_type="table_cell" if i in cells else "paragraph",
                text_raw=part,
                text_sha256=hashlib.sha256(part.encode()).hexdigest(),
                source_locator=dict(
                    format=kind,
                    unit="utf16",
                    part="main" if ole else "/word/document.xml",
                    path=[] if ole else [i],
                    paragraph=i if ole else -1,
                    table=-1,
                    row=-1,
                    cell=-1,
                    start=start if ole else 0,
                    end=(start if ole else 0) + length,
                ),
            )
        )
        start += length
    return DocumentExtraction.model_validate(
        dict(
            source_path="sample.doc",
            source_sha256="a" * 64,
            detected_format=kind,
            parser_version="apache-poi-5.5.1",
            extraction_version="body-v1",
            status="success",
            error_code=None,
            warnings=[],
            verified=True,
            blocks=blocks,
        )
    )


def test_exact_repeated_table_cell_and_utf16_locations():
    match = QuoteMatcher(doc("😀홍조와 홍조", "표 홍조", cells=(1,))).match("홍조")
    assert match.status == "exact"
    assert [
        (span.block_order, span.start_utf16, span.end_utf16)
        for candidate in match.candidates
        for span in candidate.spans
    ] == [(0, 2, 4), (0, 6, 8), (1, 2, 4)]


def test_paragraph_boundaries_preserve_real_controls_and_mark_inserted_break():
    quote = "한글\n두 번째"
    real = QuoteMatcher(doc("앞 한글\n", "두 번째 뒤", ole=True)).match(quote)
    synthetic = QuoteMatcher(doc("앞 한글", "두 번째 뒤")).match(quote)
    assert (real.status, synthetic.status) == ("exact", "normalized")
    assert [span.block_order for span in synthetic.candidates[0].spans] == [0, 1]
    assert QuoteMatcher(doc("앞 한글", "두 번째 뒤", cells=(1,))).match(quote).status == (
        "unverified"
    )


def test_layout_and_lossy_punctuation_profiles_are_distinguished():
    matcher = QuoteMatcher(doc("😀한글\tＡ 1.5"))
    strict = matcher.match("한글 a １.５")
    assert (strict.status, strict.reason_code) == ("normalized", "layout")
    assert strict.candidates[0].spans[0].start_utf16 == 2
    lossy = matcher.match("한글 A 15")
    assert (lossy.status, lossy.reason_code) == ("normalized", "letters_digits")
    assert QuoteMatcher(doc("ﬃ")).match("f").status == "unverified"


def test_partial_threshold_and_ties_are_reproducible():
    common = "abcdefghijklmnopqrstuvwx"
    matcher = QuoteMatcher(doc(f"X{common}Y X{common}Y"))
    first = matcher.match(f"Z{common}Z")
    assert first == matcher.match(f"Z{common}Z")
    assert first.status == "partial"
    assert len(first.candidates) == 2
    assert first.candidates[0].matched_length == 24
    assert first.candidates[0].quote_start_utf16 == 1
    assert matcher.match(f"Z{common[:-1]}Z").reason_code == "shared_12_to_23_chars"


def test_partial_trims_inside_a_compatibility_character_and_rechecks_original():
    common = "abcdefghijklmnopqrstuvwxyz123456789012"
    result = QuoteMatcher(doc(f"😀{common}ﬃ끝")).match(f"{common}f뒤")
    assert result.status == "partial"
    candidate = result.candidates[0]
    assert candidate.matched_length == len(common) == 38
    assert candidate.spans[0].end_utf16 == 2 + len(common)
    assert candidate.spans[0].text_sha256 == hashlib.sha256(common.encode()).hexdigest()


def test_batch_distinguishes_missing_extract_failure_and_unlinked():
    unsupported = doc().model_copy(
        update=dict(
            status="unsupported",
            detected_format="rtf",
            verified=False,
            error_code="unsupported_format",
            source_sha256="b" * 64,
        )
    )

    async def fake_extract(*args):
        yield doc("홍조")
        yield unsupported

    inputs = [
        QuoteSource("x", 1, 1, "홍조", "a" * 64),
        QuoteSource("x", 2, 2, "홍조", "b" * 64),
        QuoteSource("x", 3, 3, "홍조", "c" * 64),
        QuoteSource("x", 4, None, "홍조", None),
    ]
    with patch("app.services.knowledge_alignment_service.extract_documents", fake_extract):
        result = asyncio.run(
            summarize(inputs, Path("sample.zip"), Path("extractor.jar"), details=True)
        )
    assert result["status"] == {"exact": 1, "unverified": 2, "unlinked": 1}
    assert result["reasons"]["extraction_unsupported"] == 1
    assert result["reasons"]["document_hash_not_in_zip"] == 1
    assert "홍조" not in str(result)


@pytest.mark.integration
def test_isolated_alignment_storage_and_read_only(knowledge_database):
    url = knowledge_database

    async def check():
        engine = create_async_engine(url)
        sessions = async_sessionmaker(engine)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(check_knowledge_schema, {"aihub_quote_alignment"})
                await seed_source_documents(conn)
                for sql in (
                    "INSERT INTO aihub_dataset_release "
                    "(release_id, dataset_id, dataset_name, received_at, "
                    "source_archive, rights_status, storage_region) "
                    "VALUES (1, 'g5-integration-test', 'G5 test', DATE '2000-01-01', "
                    "'fixture.zip', 'local_only', 'local')",
                    "INSERT INTO aihub_qa_case_raw "
                    "(seq, split, source_archive, source_file_path, sha256, raw_json, release_id) "
                    "VALUES ('g5-test', 'train', 'fixture.zip', 'fixture.json', "
                    "repeat('c',64), '{}'::jsonb, 1)",
                    "INSERT INTO aihub_qa_source_link "
                    "(seq, source_position, document_id, quote_raw) "
                    "VALUES ('g5-test', 1, 1, 'sample'), ('g5-test', 2, NULL, 'lost')",
                ):
                    await conn.execute(text(sql))
            async with sessions() as session, session.begin():
                linked, unlinked = await KnowledgeRepository(session).read_quote_sources()
                assert (await session.execute(text("SHOW transaction_read_only"))).scalar() == "on"
            extracted = doc("😀sample")
            async with sessions() as session:
                assert await ingest_extraction(session, extracted, apply=True) == "inserted"
                extraction_id = (
                    await session.scalars(select(AihubDocumentExtractionRow.extraction_id))
                ).one()

            archive, jar = Path("sample.zip"), Path("extractor.jar")
            extract_path = "app.services.knowledge_alignment_service.extract_documents"

            async def fake_extract(*args):
                yield extracted

            async def mismatching_extract(*args):
                yield doc("xsample")

            with patch(extract_path, fake_extract):
                preview = await run(archive, jar, url)
            assert preview["status"] == {"unlinked": 1, "exact": 1}
            assert "stored" not in preview
            async with sessions() as session:
                assert not (await session.scalars(select(AihubQuoteAlignmentRow))).first()

            with (
                patch(extract_path, mismatching_extract),
                pytest.raises(ValueError, match="different source locator"),
            ):
                await run(archive, jar, url, apply=True)
            async with sessions() as session:
                assert not (await session.scalars(select(AihubQuoteAlignmentRow))).first()

            with patch(extract_path, fake_extract):
                applied = await run(archive, jar, url, apply=True)
                replayed = await run(archive, jar, url, apply=True)
            assert applied["status"] == preview["status"]
            assert applied["stored"] == {"inserted": 2, "already_exists": 0}
            assert replayed["stored"] == {"inserted": 0, "already_exists": 2}

            match = QuoteMatcher(extracted).match(linked.quote_raw)
            async with sessions() as session, session.begin():
                repo = KnowledgeRepository(session)
                assert not await repo.save_alignment(linked, extraction_id, MATCHER_VERSION, match)
                missing = QuoteAlignment("unlinked", "document_not_linked")
                assert not await repo.save_alignment(unlinked, None, MATCHER_VERSION, missing)
            # A missing source FK aborts the transaction including the preceding insert.
            async with sessions() as session:
                with pytest.raises(IntegrityError):
                    async with session.begin():
                        repo = KnowledgeRepository(session)
                        assert await repo.save_alignment(
                            linked, extraction_id, "try-rollback", match
                        )
                        await repo.save_alignment(replace(unlinked, seq="bad"), None, "v", missing)
            async with sessions() as session, session.begin():
                rows = (await session.scalars(select(AihubQuoteAlignmentRow))).all()
                assert len(rows) == 2
                by_position = {row.source_position: row for row in rows}
                verified = by_position[1]
                assert (
                    verified.seq,
                    verified.document_id,
                    verified.extraction_id,
                    verified.status,
                ) == (
                    "g5-test",
                    1,
                    extraction_id,
                    "exact",
                )
                assert verified.verified
                quote_hash = hashlib.sha256(b"sample").hexdigest()
                assert verified.quote_sha256 == quote_hash
                (span,) = verified.candidates[0]["spans"]
                assert (span["block_order"], span["start_utf16"], span["end_utf16"]) == (0, 2, 8)
                assert span["text_sha256"] == quote_hash
                assert span["source_locator"] == extracted.blocks[0].source_locator.model_dump()
                assert (
                    by_position[2].document_id,
                    by_position[2].extraction_id,
                    by_position[2].verified,
                    by_position[2].status,
                ) == (None, None, False, "unlinked")
        finally:
            await engine.dispose()

    async def check_reapplied():
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                await conn.run_sync(check_knowledge_schema, {"aihub_quote_alignment"})
                assert (
                    await conn.execute(text("SELECT count(*) FROM aihub_qa_source_link"))
                ).scalar_one() == 2
                assert (
                    await conn.execute(text("SELECT count(*) FROM aihub_document_extraction"))
                ).scalar_one() == 1
                assert (
                    await conn.execute(text("SELECT count(*) FROM aihub_quote_alignment"))
                ).scalar_one() == 0
        finally:
            await engine.dispose()

    migrate_standard(url, "upgrade", "0030")
    asyncio.run(check())
    migrate_standard(url, "downgrade", "0029")
    migrate_standard(url, "upgrade", "0030")
    asyncio.run(check_reapplied())
