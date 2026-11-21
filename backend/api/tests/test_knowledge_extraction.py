import asyncio
import hashlib
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.db import Base
from app.schemas.knowledge import DocumentExtraction
from app.services.knowledge_extraction_service import validate_database_url
from app.services.knowledge_ingest_service import ingest_extraction


def record():
    text = "한글😀\t본문\n"
    return dict(
        source_path="sample.doc",
        source_sha256="a" * 64,
        detected_format="ooxml",
        parser_version="apache-poi-5.5.1",
        extraction_version="body-v1",
        status="success",
        error_code=None,
        warnings=[],
        verified=True,
        blocks=[
            dict(
                block_order=0,
                block_type="paragraph",
                text_raw=text,
                text_sha256=hashlib.sha256(text.encode()).hexdigest(),
                source_locator=dict(
                    format="ooxml",
                    unit="utf16",
                    part="/word/document.xml",
                    path=[0],
                    paragraph=-1,
                    table=-1,
                    row=-1,
                    cell=-1,
                    start=0,
                    end=len(text.encode("utf-16-le")) // 2,
                ),
            )
        ],
    )


def test_unicode_hash_and_utf16_are_preserved():
    data = record()
    assert (
        DocumentExtraction.model_validate(data).blocks[0].text_raw == data["blocks"][0]["text_raw"]
    )
    data["blocks"][0]["source_locator"]["end"] -= 1
    with pytest.raises(ValidationError, match="UTF-16"):
        DocumentExtraction.model_validate(data)


@pytest.mark.parametrize("change", ["hash", "order", "verified", "format"])
def test_reject_corrupt_result(change):
    data = record()
    if change == "hash":
        data["blocks"][0]["text_raw"] += "changed"
    elif change == "order":
        data["blocks"][0]["block_order"] = 1
    elif change == "verified":
        data["verified"] = False
    else:
        data["detected_format"] = "rtf"
    with pytest.raises(ValidationError):
        DocumentExtraction.model_validate(data)


def test_only_explicit_local_postgres_allowed():
    assert validate_database_url("postgresql+asyncpg://u:p@127.0.0.1:5432/test")
    for url in (
        "postgresql+asyncpg://u:p@example.com/test",
        "postgresql+asyncpg://u:p@localhost/test?host=example.com",
        "sqlite:///test",
    ):
        with pytest.raises(ValueError):
            validate_database_url(url)


class FakeSession:
    def __init__(self):
        self.execute = AsyncMock()
        self.rolled_back = False

    @asynccontextmanager
    async def begin(self):
        try:
            yield
        except Exception:
            self.rolled_back = True
            raise


def test_dry_run_is_read_only_and_does_not_save():
    session = FakeSession()
    with patch("app.services.knowledge_ingest_service.KnowledgeRepository") as factory:
        repo = factory.return_value
        repo.resolve = AsyncMock(return_value=(1, 2))
        repo.save = AsyncMock()
        assert (
            asyncio.run(ingest_extraction(session, DocumentExtraction.model_validate(record())))
            == "verified_source"
        )
        assert str(session.execute.call_args.args[0]) == "SET TRANSACTION READ ONLY"
        repo.save.assert_not_called()


def test_hash_path_mismatch_prevents_save():
    session = FakeSession()
    with patch("app.services.knowledge_ingest_service.KnowledgeRepository") as factory:
        repo = factory.return_value
        repo.resolve = AsyncMock(side_effect=ValueError("Document path/hash is not registered"))
        repo.save = AsyncMock()
        with pytest.raises(ValueError, match="path/hash"):
            asyncio.run(
                ingest_extraction(session, DocumentExtraction.model_validate(record()), apply=True)
            )
        repo.save.assert_not_called()
        assert session.rolled_back


def test_block_failure_propagates_out_of_transaction():
    session = FakeSession()
    with patch("app.services.knowledge_ingest_service.KnowledgeRepository") as factory:
        repo = factory.return_value
        repo.resolve = AsyncMock(return_value=(1, 2))
        repo.save = AsyncMock(side_effect=RuntimeError("block insert failed"))
        with pytest.raises(RuntimeError, match="block insert"):
            asyncio.run(
                ingest_extraction(session, DocumentExtraction.model_validate(record()), apply=True)
            )
        assert session.rolled_back


EXPECTED_TEST_URL = "postgresql+asyncpg://g5_test:g5_test_local@127.0.0.1:15549/g5_extraction_test"
API_ROOT = Path(__file__).resolve().parents[1]


def migrate_standard(url, direction, target):
    subprocess.run(
        [sys.executable, "-B", "-m", "alembic", "-c", "alembic.ini", direction, target],
        cwd=API_ROOT,
        env=os.environ | {"DATABASE_URL": url},
        check=True,
        timeout=120,
    )


async def _test_database_revision(url):
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            assert (await conn.execute(text("SELECT current_database(), current_user"))).one() == (
                "g5_extraction_test",
                "g5_test",
            )
            assert (await conn.execute(text("SHOW cluster_name"))).scalar_one() == (
                "g5-integration-test"
            )
            assert (
                await conn.execute(text("SELECT to_regclass('public.alembic_version_g5')"))
            ).scalar() is None
            if (
                await conn.execute(text("SELECT to_regclass('public.alembic_version')"))
            ).scalar() is None:
                assert not (
                    await conn.execute(
                        text("SELECT count(*) FROM pg_tables WHERE schemaname = 'public'")
                    )
                ).scalar_one()
                return None
            revision = (
                await conn.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            assert revision == "0028", "Use a clean disposable database at the standard predecessor"
            assert (
                await conn.execute(text("SELECT to_regclass('public.look_video_tags')"))
            ).scalar()
            assert (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_schema = 'public' AND table_name = 'shades' "
                        "AND column_name = 'finish'"
                    )
                )
            ).scalar_one() == 1
            for table in ("aihub_knowledge_document", "aihub_qa_case_raw", "aihub_dataset_release"):
                assert not (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
            return revision
    finally:
        await engine.dispose()


async def _delete_test_rows(url):
    engine = create_async_engine(url)
    try:
        async with engine.begin() as conn:
            for sql in (
                "DELETE FROM aihub_qa_source_link WHERE seq = 'g5-test'",
                "DELETE FROM aihub_qa_case_raw WHERE seq = 'g5-test'",
                "DELETE FROM aihub_dataset_release WHERE dataset_id = 'g5-integration-test'",
                "DELETE FROM aihub_knowledge_document_file "
                "WHERE file_id IN (1, 2) AND source_file_path IN ('sample.doc', 'other.doc')",
                "DELETE FROM aihub_knowledge_document "
                "WHERE document_id IN (1, 2) "
                "AND content_sha256 IN (repeat('a',64), repeat('b',64))",
            ):
                await conn.execute(text(sql))
    finally:
        await engine.dispose()


@pytest.fixture
def knowledge_database():
    url = os.getenv("G5_EXTRACTION_TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set G5_EXTRACTION_TEST_DATABASE_URL to the disposable test database")
    assert url == EXPECTED_TEST_URL, "Only the dedicated disposable test database is allowed"
    if asyncio.run(_test_database_revision(url)) is None:
        migrate_standard(url, "upgrade", "0028")
        assert asyncio.run(_test_database_revision(url)) == "0028"
    try:
        yield url
    finally:
        migrate_standard(url, "downgrade", "0028")
        asyncio.run(_delete_test_rows(url))


async def seed_source_documents(conn):
    await conn.execute(
        text("""
        INSERT INTO aihub_knowledge_document (document_id, content_sha256)
        VALUES (1, repeat('a',64)), (2, repeat('b',64))
    """)
    )
    await conn.execute(
        text("""
        INSERT INTO aihub_knowledge_document_file
            (file_id, document_id, source_file_path, file_name, file_extension)
        VALUES (1, 1, 'sample.doc', 'sample.doc', 'doc'),
               (2, 2, 'other.doc', 'other.doc', 'doc')
    """)
    )


def check_knowledge_schema(connection, names):
    context = MigrationContext.configure(
        connection,
        opts={
            "include_object": lambda obj, name, kind, reflected, other: (
                kind != "table" or name in names
            ),
        },
    )
    assert compare_metadata(context, Base.metadata) == []


@pytest.mark.integration
def test_isolated_postgres_migration_idempotency_and_rollback(knowledge_database):
    url = knowledge_database
    extraction_tables = {"aihub_document_extraction", "aihub_document_block"}

    async def check():
        engine = create_async_engine(url)
        sessions = async_sessionmaker(engine)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(check_knowledge_schema, extraction_tables)
                await seed_source_documents(conn)
            result = DocumentExtraction.model_validate(record())
            async with sessions() as session:
                assert await ingest_extraction(session, result) == "verified_source"
                assert not (
                    await session.execute(text("SELECT count(*) FROM aihub_document_extraction"))
                ).scalar_one()
                await session.rollback()
                assert await ingest_extraction(session, result, apply=True) == "inserted"
                assert await ingest_extraction(session, result, apply=True) == "already_exists"
            async with engine.connect() as conn:
                header = (
                    await conn.execute(
                        text("""
                    SELECT document_id, file_id, source_sha256, verified, block_count
                    FROM aihub_document_extraction
                """)
                    )
                ).one()
                assert tuple(header) == (1, 1, result.source_sha256, True, 1)
                block = (
                    await conn.execute(
                        text("""
                    SELECT block_order, text_raw, text_sha256, source_locator, locator_version
                    FROM aihub_document_block WHERE extraction_id =
                      (SELECT extraction_id FROM aihub_document_extraction WHERE document_id = 1)
                """)
                    )
                ).one()
                expected = result.blocks[0]
                assert tuple(block) == (
                    expected.block_order,
                    expected.text_raw,
                    expected.text_sha256,
                    expected.source_locator.model_dump(),
                    result.extraction_version,
                )

            # A real block CHECK failure must roll back the preceding extraction insert.
            broken = result.model_copy(
                update={
                    "source_path": "other.doc",
                    "source_sha256": "b" * 64,
                    "blocks": [result.blocks[0].model_copy(update={"block_type": "invalid"})],
                }
            )
            async with sessions() as session:
                with pytest.raises(IntegrityError):
                    await ingest_extraction(session, broken, apply=True)
            async with engine.connect() as conn:
                assert (
                    await conn.execute(text("SELECT document_id FROM aihub_document_extraction"))
                ).scalars().all() == [1]
                assert (
                    await conn.execute(text("SELECT count(*) FROM aihub_document_block"))
                ).scalar_one() == 1
        finally:
            await engine.dispose()

    async def check_reapplied():
        engine = create_async_engine(url)
        try:
            async with engine.connect() as conn:
                await conn.run_sync(check_knowledge_schema, extraction_tables)
                assert (
                    await conn.execute(text("SELECT count(*) FROM aihub_knowledge_document"))
                ).scalar_one() == 2
                assert (
                    await conn.execute(text("SELECT count(*) FROM aihub_document_extraction"))
                ).scalar_one() == 0
        finally:
            await engine.dispose()

    migrate_standard(url, "upgrade", "0029")
    asyncio.run(check())
    migrate_standard(url, "downgrade", "0028")
    migrate_standard(url, "upgrade", "0029")
    asyncio.run(check_reapplied())
