"""Verify I-1 against an isolated, migrated PostgreSQL database."""

import os
import runpy
from pathlib import Path
from uuid import uuid4

import asyncpg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[3]
INVENTORY_SCRIPT = ROOT / "scripts" / "data" / "aihub" / "analyze_qa.py"
DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_i1_has_one_develop_based_head_and_its_own_revision_id():
    config = Config()
    config.set_main_option("script_location", str(ROOT / "backend" / "api" / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    assert len(scripts.get_heads()) == 1
    assert scripts.get_revision("aihub_claim_review_v1").down_revision == "0018"


def test_release_validation_detects_count_and_distribution_drift():
    cli = runpy.run_path(str(INVENTORY_SCRIPT))
    baseline = cli["RELEASE_BASELINE"]
    assert cli["validate_release"](baseline) == {"passed": True, "mismatches": {}}
    report = {**baseline, "releases": 2, "by_concern": {"01": 9031}}
    result = cli["validate_release"](report)
    assert not result["passed"]
    assert set(result["mismatches"]) == {"releases", "by_concern"}


@pytest.mark.anyio
@pytest.mark.integration
@pytest.mark.skipif(not DATABASE_URL, reason="needs migrated TEST_DATABASE_URL")
async def test_intake_review_decisions_and_historical_evidence_stay_separate():
    read_inventory = runpy.run_path(str(INVENTORY_SCRIPT))["read_inventory"]
    conn = await asyncpg.connect(DATABASE_URL.replace("+asyncpg", "", 1))
    transaction = conn.transaction(isolation="repeatable_read")
    await transaction.start()
    try:
        release_id = await conn.fetchval("""
            INSERT INTO public.aihub_dataset_release
                (dataset_id, dataset_name, received_at, source_archive,
                 rights_status, storage_region)
            VALUES ('test', 'review contract', CURRENT_DATE, 'test.zip', 'local_only', 'kr-local')
            RETURNING release_id
        """)
        first_seq, second_seq = f"test-{uuid4()}", f"test-{uuid4()}"
        for seq in (first_seq, second_seq):
            await conn.execute(
                """
                INSERT INTO public.aihub_qa_case_raw
                    (seq, split, source_archive, source_file_path, sha256, raw_json, release_id)
                VALUES ($1, 'train', 'test.zip', 'case.json', 'hash', '{}', $2)
            """,
                seq,
                release_id,
            )
            await conn.execute(
                """
                INSERT INTO public.aihub_qa_case (seq, subject_id, concern_code)
                VALUES ($1, 'test-subject', '01')
            """,
                seq,
            )

        source_id = f"test-source:{uuid4()}"
        doc_1, doc_2 = [
            await conn.fetchval(
                """
                INSERT INTO public.aihub_knowledge_document
                    (content_sha256, source_identifier, source_version)
                VALUES ($1, $2, $3) RETURNING document_id
            """,
                f"{source_id}:{version}",
                source_id,
                version,
            )
            for version in ("v1", "v2")
        ]
        await conn.execute(
            """
            INSERT INTO public.aihub_qa_source_link
                (seq, source_position, document_id, match_status)
            VALUES ($1, 1, $3, 'matched'), ($2, 1, NULL, 'unmatched')
        """,
            first_seq,
            second_seq,
            doc_1,
        )
        await conn.execute(
            """
            INSERT INTO public.aihub_ingredient_mention (seq, mention_type, raw_text)
            VALUES ($1, 'recommended', 'test mention'), ($1, 'recommended', 'test mention')
            ON CONFLICT DO NOTHING
        """,
            first_seq,
        )
        assert (
            await conn.fetchval(
                "SELECT count(*) FROM public.aihub_ingredient_mention WHERE seq = $1", first_seq
            )
            == 1
        )
        report = await read_inventory(conn, list_cases=True, case_ids=[first_seq, second_seq])
        cases = {row["seq"]: row for row in report["selected_cases"]}
        assert cases[first_seq]["review_progress"] == "not_started"
        assert cases[first_seq]["sources"][0]["document_id"] == doc_1
        assert cases[first_seq]["sources"][0]["rights_status"] == "pending_confirmation"
        assert cases[first_seq]["claims"] == []
        assert cases[second_seq]["sources"][0]["document_id"] is None
        assert {row["seq"] for row in report["cases"]} >= cases.keys()

        claim_key = uuid4()
        insert_claim = """
            INSERT INTO public.aihub_claim_version (claim_key, revision, canonical_text)
            VALUES ($1, $2, 'test claim') RETURNING claim_version_id
        """
        version_1 = await conn.fetchval(insert_claim, claim_key, 1)
        another_claim = await conn.fetchval(insert_claim, uuid4(), 1)
        link_claim = """
            INSERT INTO public.aihub_qa_claim (seq, claim_version_id, answer_locator)
            VALUES ($1, $2, 'answer:1')
        """
        await conn.executemany(
            link_claim,
            [(first_seq, version_1), (second_seq, version_1), (first_seq, another_claim)],
        )
        insert_review = """
            INSERT INTO public.aihub_claim_review
                (seq, claim_version_id, source_position, document_id)
            VALUES ($1, $2, $3, $4) RETURNING claim_id
        """
        evidence_1 = await conn.fetchval(insert_review, first_seq, version_1, 1, doc_1)
        await conn.fetchval(insert_review, second_seq, version_1, 1, None)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            async with conn.transaction():
                await conn.fetchval(insert_review, second_seq, another_claim, 1, None)
        with pytest.raises(asyncpg.ForeignKeyViolationError):
            async with conn.transaction():
                await conn.fetchval(insert_review, first_seq, version_1, 2, None)
        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE public.aihub_claim_version SET approval_status = 'approved'
                    WHERE claim_version_id = $1
                """,
                    version_1,
                )
        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():
                await conn.execute(
                    """
                    UPDATE public.aihub_claim_review
                    SET support_status = 'direct', reviewer = 'test', reviewed_at = CURRENT_DATE
                    WHERE claim_id = $1
                """,
                    evidence_1,
                )

        await conn.execute(
            """
            UPDATE public.aihub_claim_review
            SET support_status = 'direct', reviewer = 'test', reviewed_at = CURRENT_DATE,
                source_locator = 'p. 1', study_type = 'test type', notes = 'test limitation'
            WHERE claim_id = $1
        """,
            evidence_1,
        )
        await conn.execute(
            """
            UPDATE public.aihub_claim_version
            SET review_progress = 'completed', approval_status = 'approved',
                approved_uses = ARRAY['explain'], reviewer = 'test',
                reviewed_at = now(), decision_reason = 'test decision'
            WHERE claim_version_id = $1
        """,
            version_1,
        )
        await conn.execute(
            """
            UPDATE public.aihub_qa_source_link SET document_id = $2 WHERE seq = $1
        """,
            first_seq,
            doc_2,
        )
        version_2 = await conn.fetchval(insert_claim, claim_key, 2)
        await conn.execute(link_claim, first_seq, version_2)
        await conn.fetchval(insert_review, first_seq, version_2, 1, doc_2)
        report = await read_inventory(conn, list_cases=False, case_ids=[first_seq, "missing"])
        assert report["missing_case_ids"] == ["missing"]
        case = report["selected_cases"][0]
        assert case["sources"][0]["source_version"] == "v2"
        claims = {row["claim_version_id"]: row for row in case["claims"]}
        assert claims[version_1]["source_version"] == "v1"
        assert claims[version_1]["approval_status"] == "approved"
        assert claims[version_1]["rights_status"] == "pending_confirmation"
        assert not claims[version_1]["is_current"]
        assert claims[version_2]["is_current"]
        assert claims[version_2]["source_version"] == "v2"
        assert claims[version_2]["support_status"] == "pending"
        assert claims[version_2]["approval_status"] is None
        assert claims[another_claim]["support_status"] is None
    finally:
        await transaction.rollback()
        await conn.close()
