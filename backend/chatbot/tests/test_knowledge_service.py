import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.clients.openai_responses_client import StageResult
from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.repositories.chat_session_repository import ChatSessionRepository
from app.schemas.knowledge import (
    Candidate,
    KnowledgeReply,
    NeighborResult,
    OriginalBlock,
    SearchResult,
)
from app.services import chat_service
from app.services.knowledge_service import (
    CONTEXT_BUDGET,
    Consultation,
    KnowledgeService,
    pack,
    resolve,
    tokens,
    verify_selection,
)
from tests.test_beauty_consultation import PlanLlm
from tests.test_chat_sessions import RedisDouble, SessionCatalog

RAW = "홍조 설명😀. 사용 범위는 볼에 한정됩니다."
QUOTE = "사용 범위는 볼에 한정됩니다."
LOCATOR = {"start": 0, "end": len(RAW.encode("utf-16-le")) // 2}
HIT = Candidate.model_validate(
    {
        "chunkId": "chunk",
        "documentId": 8,
        "extractionId": 3,
        "sourceVersion": "v1",
        "sourceFileId": 2,
        "title": "제목",
        "score": 1.0,
        "channels": ["keyword", "vector"],
        "segments": [
            {
                "span": {
                    "blockOrder": 4,
                    "startUtf16": 0,
                    "endUtf16": LOCATOR["end"],
                    "sourceLocator": LOCATOR,
                },
                "text": RAW,
            }
        ],
    }
)
SELECTED = {
    "candidate_id": "C1",
    "document_id": 8,
    "paragraph": 4,
    "exact_quote": QUOTE,
    "relevance": "essential",
}


def originals(loc):
    return [
        NeighborResult(
            source=loc[0],
            blocks=[
                OriginalBlock(block_order=4, kind="paragraph", text=RAW, source_locator=LOCATOR)
            ],
        )
    ]


def test_utf16_selection_and_context_budget():
    evidence, loc, rejected = verify_selection([SELECTED], {"C1": HIT})
    assert not rejected and evidence[0].start_utf16 == 9
    ctx, citable, used = pack(evidence, loc, originals(loc), [HIT])
    assert ctx == [{"id": "E1", "text": QUOTE}]
    assert citable == evidence and used <= CONTEXT_BUDGET


BEFORE = OriginalBlock(
    block_order=3, kind="paragraph", text="✔ 패인 흉터형😀", source_locator={"paragraph": 3}
)
AFTER = OriginalBlock(
    block_order=5, kind="paragraph", text="다른 도구 소개", source_locator={"paragraph": 5}
)


def candidate_for(block, chunk_id):
    candidate = HIT.model_dump()
    candidate.update(
        chunk_id=chunk_id,
        segments=[
            {
                "span": {
                    "block_order": block.block_order,
                    "start_utf16": 0,
                    "end_utf16": len(block.text.encode("utf-16-le")) // 2,
                    "source_locator": block.source_locator,
                },
                "text": block.text,
            }
        ],
    )
    return Candidate.model_validate(candidate)


def neighboring_originals(loc):
    original = originals(loc)[0]
    original.blocks = [BEFORE, *original.blocks, AFTER]
    return [original]


def test_citable_neighbor_uses_containing_chunk_and_budget_counts_new_id():
    evidence, loc, _ = verify_selection([SELECTED], {"C1": HIT})
    before = candidate_for(BEFORE, "different-chunk")
    ctx, citable, used = pack(evidence, loc, neighboring_originals(loc), [HIT, before])
    assert ctx == [
        {"id": "E1", "text": QUOTE},
        {"id": "E1.1", "text": f"앞 문단: {BEFORE.text}"},
    ]
    ref = citable[1]
    assert (ref.document_id, ref.chunk_id, ref.source_version) == (8, "different-chunk", "v1")
    assert (ref.block_order, ref.start_utf16, ref.end_utf16) == (3, 0, 10)
    assert ref.quote == BEFORE.text and ref.source_locator == BEFORE.source_locator
    assert used == sum(tokens(f"[{x['id']}] {x['text']}\n\n") for x in ctx)
    clipped, refs, _ = pack(evidence, loc, neighboring_originals(loc), [HIT, before], used - 1)
    assert clipped == ctx[:1] and refs == evidence


@pytest.mark.parametrize(
    "field", ["document_id", "extraction_id", "source_version", "source_file_id"]
)
def test_mismatched_chunk_identity_cannot_publish_a_neighbor(field):
    evidence, loc, _ = verify_selection([SELECTED], {"C1": HIT})
    candidate = candidate_for(BEFORE, "wrong")
    wrong = candidate.model_copy(update={field: "v2" if field == "source_version" else 100})
    ctx, citable, _ = pack(evidence, loc, neighboring_originals(loc), [HIT, wrong])
    assert ctx == [{"id": "E1", "text": QUOTE}] and citable == evidence


@pytest.mark.parametrize("mismatch", ["span", "locator", "text"])
def test_invalid_chunk_span_cannot_publish_a_neighbor(mismatch):
    evidence, loc, _ = verify_selection([SELECTED], {"C1": HIT})
    wrong = candidate_for(BEFORE, "wrong")
    segment = wrong.segments[0]
    if mismatch == "span":
        segment.span.start_utf16 = 1
    elif mismatch == "locator":
        segment.span.source_locator = {"paragraph": 30}
    else:
        segment.text = "X" + segment.text[1:]
    _, citable, _ = pack(evidence, loc, neighboring_originals(loc), [HIT, wrong])
    assert citable == evidence


def test_mismatched_original_version_is_rejected():
    evidence, loc, _ = verify_selection([SELECTED], {"C1": HIT})
    wrong = neighboring_originals(loc)
    wrong[0].source = loc[0].model_copy(update={"source_version": "v2"})
    with pytest.raises(ValueError, match="Original source identity mismatch"):
        pack(evidence, loc, wrong, [HIT])


def check(
    index,
    *,
    requirements=(),
    citations=(),
    label="SUPPORTED",
    match="MATCHED",
    applicability="APPLICABLE",
    basis=None,
    condition="",
    condition_ids=(),
    link="NONE",
):
    if basis is None:
        basis = {
            "APPLICABLE": "DIRECT",
            "CONDITIONAL": "BOUNDED",
            "NOT_APPLICABLE": "CONFLICT",
            "UNCERTAIN": "UNVERIFIED",
        }.get(applicability, "UNVERIFIED")
    return {
        "index": index,
        "label": label,
        "match": match,
        "requirement_ids": list(requirements),
        "supporting_ids": list(citations),
        "reason": "고정 검증 판정",
        "condition_evidence_ids": list(condition_ids),
        "condition_link": link,
        "applicability": applicability,
        "scope_basis": basis,
        "condition_quote": condition,
    }


def verification(*reviews, required=("사용 범위",), optional=(), bad_limits=False):
    requirements = [
        {"id": f"R{i}", "description": description, "required": i <= len(required)}
        for i, description in enumerate((*required, *optional), 1)
    ]
    return {
        "requirements": requirements,
        "reviews": list(reviews),
        "adequate_context": True,
        "limits_unsubstantiated": bad_limits,
    }


def test_status_resolver_drops_bad_optional_claim_and_keeps_complete_answer():
    evidence, _, _ = verify_selection([SELECTED], {"C1": HIT})
    draft = {
        "status": "answered",
        "limitations": "",
        "claims": [
            {"claim": "볼에 한정됩니다.", "citations": ["E1"]},
            {"claim": "어떤 부위든 적용합니다.", "citations": ["E1"]},
        ],
    }
    audit = verification(
        check(1, requirements=["R1"], citations=["E1"]),
        check(2, label="OVERGENERALIZED", match="PARTIAL_MATCH"),
        optional=["다른 부위 조언"],
    )
    result = resolve(draft, audit, evidence)
    assert result.status == "answered"
    assert [c.claim for c in result.claims] == ["볼에 한정됩니다."]
    assert result.evidence == evidence
    assert "어떤 부위든" not in Consultation(result, {}).answer
    assert result.findings[0].label == "OVERGENERALIZED"
    assert not result.limitations
    assert len(draft["claims"]) == 2


def test_unknown_citation_cannot_pass():
    evidence, _, _ = verify_selection([SELECTED], {"C1": HIT})
    draft = {
        "status": "answered",
        "limitations": "",
        "claims": [
            {"claim": "볼에 한정됩니다.", "citations": ["E2"]},
        ],
    }
    audit = verification(check(1, requirements=["R1"], citations=["E2"]))
    result = resolve(draft, audit, evidence)
    assert result.status == "insufficient_evidence"
    assert result.findings[0].label == "UNSUPPORTED"


def test_limit_only_evidence_follows_existing_insufficient_result():
    evidence, _, _ = verify_selection([SELECTED], {"C1": HIT})
    draft = {
        "status": "insufficient",
        "claims": [],
        "limitations": "해당 원문은 볼 사용만 설명합니다. [E99]",
        "limitation_citations": ["E1", "E99"],
    }
    audit = verification()
    result = resolve(draft, audit, evidence)
    assert result.status == "insufficient_evidence"
    assert result.limitations == "해당 원문은 볼 사용만 설명합니다. [E1]"
    assert result.evidence == evidence
    removed = resolve(draft, audit | {"limits_unsubstantiated": True}, evidence)
    assert not removed.evidence and "[E" not in removed.limitations


@pytest.mark.parametrize(
    ("required", "claim", "reason"),
    [
        ("호감도가 가장 높았던 립 컬러", "핑크의 매력성이 가장 높았습니다.", "지표"),
        ("고화질 촬영에서 고정하는 방법", "요철에 파우더를 눌러 보정합니다.", "촬영 상황"),
        ("스틱 셰이딩을 푸는 방법", "쿠션 컨실러를 스펀지로 펴세요.", "제품과 제형"),
    ],
    ids=["J11", "M04", "I10"],
)
def test_supported_wrong_question_is_removed(required, claim, reason):
    evidence, _, _ = verify_selection([SELECTED], {"C1": HIT})
    evidence = [evidence[0].model_copy(update={"quote": claim})]
    draft = {
        "status": "answered",
        "claims": [{"claim": claim, "citations": ["E1"]}],
        "limitations": "",
    }
    audit = verification(
        check(1, citations=["E1"], match="MISMATCHED") | {"reason": reason},
        required=[required],
    )
    result = resolve(draft, audit, evidence)
    assert result.status == "insufficient_evidence"
    assert not result.claims and not result.evidence
    assert claim not in Consultation(result, {}).answer and reason in result.findings[0].reason


@pytest.mark.parametrize(
    ("required", "claim", "scope", "basis"),
    [
        (
            "고화질 촬영용 파우더 동작",
            "요철에 파우더를 눌러 보정합니다.",
            "UNCERTAIN",
            "UNVERIFIED",
        ),
        (
            "고화질 촬영용 파우더 동작",
            "요철에 파우더를 눌러 보정합니다.",
            "APPLICABLE",
            "UNVERIFIED",
        ),
        ("얼굴 전체의 올바른 도포법", "눈꼬리에만 얇게 펴 바르세요.", "NOT_APPLICABLE", "CONFLICT"),
        (
            "시험의 8시간 지속력",
            "A가 만족도 조사에서 가장 높았습니다.",
            "NOT_APPLICABLE",
            "CONFLICT",
        ),
        (
            "밤 제형을 녹여 쓰는 방법",
            "오일을 건조한 얼굴에 먼저 펴 바르세요.",
            "NOT_APPLICABLE",
            "CONFLICT",
        ),
    ],
    ids=["M04-scope", "unverified-despite-positive-label", "new-area", "new-metric", "new-formula"],
)
def test_supported_matched_claim_outside_scope_cannot_satisfy_requirement(
    required, claim, scope, basis
):
    evidence, _, _ = verify_selection([SELECTED], {"C1": HIT})
    evidence = [evidence[0].model_copy(update={"quote": claim})]
    draft = {"claims": [{"claim": claim, "citations": ["E1"]}], "limitations": ""}
    audit = verification(
        check(1, requirements=["R1"], citations=["E1"], applicability=scope, basis=basis),
        required=[required],
    )
    result = resolve(draft, audit, evidence)
    assert result.status == "insufficient_evidence"
    assert not result.claims and not result.evidence
    assert claim not in Consultation(result, {}).answer
    assert "적용 조건" in result.findings[0].reason


@pytest.mark.parametrize(
    ("quote", "keep"),
    [("실내에서만", True), ("", False), ("야외에서만", False)],
    ids=["already-bounded", "no-condition", "condition-invented-by-validator"],
)
def test_conditional_advice_needs_existing_bound_and_never_completes_required_item(quote, keep):
    evidence, loc, _ = verify_selection([SELECTED], {"C1": HIT})
    primary = "볼에는 소량을 바르세요."
    secondary = "실내에서만 얇게 덧바르는 방법이 자료에 있습니다."
    before = BEFORE.model_copy(update={"text": secondary})
    source = neighboring_originals(loc)
    source[0].blocks[0] = before
    _, citable, _ = pack(evidence, loc, source, [HIT, candidate_for(before, "pre")])
    extra = citable[1].id
    draft = {
        "claims": [
            {"claim": primary, "citations": ["E1"]},
            {"claim": secondary, "citations": [extra]},
        ],
        "limitations": "",
    }
    audit = verification(
        check(1, requirements=["R1"], citations=["E1"]),
        check(
            2, requirements=["R2"], citations=[extra], applicability="CONDITIONAL", condition=quote
        ),
        required=["기본 도포법", "야외에서 덧바르는 방법"],
    )
    result = resolve(draft, audit, citable)
    assert result.status == "partial" and "야외에서 덧바르는 방법" in result.limitations
    assert [c.claim for c in result.claims] == ([primary, secondary] if keep else [primary])
    assert result.evidence == (citable if keep else evidence)
    assert (secondary in Consultation(result, {}).answer) == keep
    if keep:
        fallback = resolve(
            draft | {"claims": draft["claims"][1:]},
            audit | {"reviews": [audit["reviews"][1] | {"index": 1}]},
            citable,
        )
        assert fallback.status == "insufficient_evidence"
        assert not fallback.claims and not fallback.evidence


def test_same_study_conditions_can_attach_to_direct_evidence_and_be_published():
    evidence, loc, _ = verify_selection([SELECTED], {"C1": HIT})
    candidates = [HIT, candidate_for(BEFORE, "pre"), candidate_for(AFTER, "post")]
    _, citable, _ = pack(evidence, loc, neighboring_originals(loc), candidates)
    condition_id = citable[1].id
    text = "측정값이 줄었습니다."
    draft = {"claims": [{"claim": text, "citations": ["E1"]}], "limitations": ""}
    audit = verification(
        check(
            1,
            requirements=["R1"],
            citations=["E1"],
            condition_ids=[condition_id, condition_id],
            link="SAME_CONTEXT",
        )
    )
    result = resolve(draft, audit, citable)
    assert result.status == "answered"
    assert Consultation(result, {}).answer == f"{text} [E1] [{condition_id}]"
    assert result.evidence == citable[:2]
    assert draft["claims"][0]["citations"] == ["E1"]


@pytest.mark.parametrize(
    ("link", "different_source"),
    [
        ("DIFFERENT_CONTEXT", {}),
        ("UNVERIFIED", {}),
        ("SAME_CONTEXT", {"source_version": "v2"}),
        ("SAME_CONTEXT", {"document_id": 33}),
        ("SAME_CONTEXT", {"source_file_id": 44}),
    ],
    ids=["other-arm-same-doc", "unknown-study", "other-version", "other-doc", "other-file"],
)
def test_condition_evidence_must_share_study_and_source_identity(link, different_source):
    evidence, loc, _ = verify_selection([SELECTED], {"C1": HIT})
    _, citable, _ = pack(
        evidence,
        loc,
        neighboring_originals(loc),
        [HIT, candidate_for(BEFORE, "pre")],
    )
    citable[1] = citable[1].model_copy(update=different_source)
    draft = {
        "claims": [{"claim": "두 번째 시험군에서 효과가 있었습니다.", "citations": ["E1"]}],
        "limitations": "",
    }
    audit = verification(
        check(
            1,
            requirements=["R1"],
            citations=["E1"],
            condition_ids=[citable[1].id],
            link=link,
        )
    )
    result = resolve(draft, audit, citable)
    assert result.status == "insufficient_evidence"
    assert not result.claims and not result.evidence
    assert "CONDITION_CONTEXT_MISMATCH" in result.findings[0].reason


def test_unverified_absence_from_a_publication_is_removed():
    evidence, _, _ = verify_selection([SELECTED], {"C1": HIT})
    absence = "해당 원문 전체에 UVA와 UVB를 같이 차단하라는 언급이 없습니다."
    draft = {
        "claims": [{"claim": absence, "citations": ["E1"]}],
        "limitations": absence,
        "limitation_citations": ["E1"],
    }
    audit = verification(
        check(1, label="UNSUPPORTED", match="MATCHED", requirements=["R1"]),
        required=["해당 자료의 UVA·UVB 권고"],
        bad_limits=True,
    )
    result = resolve(draft, audit, evidence)
    assert result.status == "insufficient_evidence" and not result.evidence
    assert "제공된 원문으로는" in Consultation(result, {}).answer
    assert absence not in Consultation(result, {}).answer


@pytest.mark.parametrize(
    ("label", "match", "applicability", "basis"),
    [
        ("UNCERTAIN", "MATCHED", "APPLICABLE", None),
        ("SUPPORTED", "UNCERTAIN", "APPLICABLE", None),
        ("SUPPORTED", "IRRELEVANT", "APPLICABLE", None),
        ("CONTRADICTED", "MATCHED", "APPLICABLE", None),
        ("UNSUPPORTED", "MATCHED", "APPLICABLE", None),
        ("SUPPORTED", "PARTIAL_MATCH", "NOT_APPLICABLE", None),
        ("SUPPORTED", "PARTIAL_MATCH", "UNCERTAIN", None),
        ("SUPPORTED", "MATCHED", "APPLICABLE", "SIMILAR_ONLY"),
    ],
)
def test_valid_core_survives_uncertain_wrong_or_unrelated_advice(
    label, match, applicability, basis
):
    evidence, loc, _ = verify_selection([SELECTED], {"C1": HIT})
    candidates = [HIT, candidate_for(BEFORE, "pre")]
    _, citable, _ = pack(evidence, loc, neighboring_originals(loc), candidates)
    wrong = citable[-1].id
    draft = {
        "status": "partial",
        "claims": [
            {"claim": "볼 실핏줄에 컨실러를 톡톡 올리세요.", "citations": ["E1", wrong]},
            {"claim": "실핏줄 선을 그린 코렉터로 가리세요.", "citations": [wrong]},
        ],
        "limitations": "",
    }
    audit = verification(
        check(1, requirements=["R1"], citations=["E1"]),
        check(
            2,
            label=label,
            match=match,
            applicability=applicability,
            basis=basis,
            citations=[wrong],
            requirements=["R1"],
        ),
        required=["실핏줄을 가릴 제품과 사용법"],
    )
    result = resolve(draft, audit, citable)
    assert result.status == "answered" and result.evidence == evidence
    assert Consultation(result, {}).answer == "볼 실핏줄에 컨실러를 톡톡 올리세요. [E1]"
    assert len(result.findings) == 1


@pytest.mark.parametrize(
    ("claim", "required", "match", "missing"),
    [
        ("각질을 누르듯 정돈하세요.", ("각질 정돈", "베이스 제품과 사용법"), "MATCHED", "베이스"),
        (
            "선을 따라 조금씩 점으로 올리세요.",
            ("실핏줄을 가릴 제품과 사용법",),
            "PARTIAL_MATCH",
            "제품",
        ),
        (
            "립글로스 군의 수분 변화는 유의하지 않았습니다.",
            ("두 제형의 수분 변화 비교",),
            "PARTIAL_MATCH",
            "비교",
        ),
        (
            "건조할 때는 베이스를 얇게 펴세요.",
            ("건조한 날의 베이스 도포법", "화장 전 피부 준비 순서"),
            "MATCHED",
            "피부 준비",
        ),
    ],
    ids=["03", "V06", "I07", "new-partially-related"],
)
def test_partial_coverage_uses_only_retained_claims(claim, required, match, missing):
    evidence, _, _ = verify_selection([SELECTED], {"C1": HIT})
    draft = {
        "status": "answered",
        "claims": [
            {"claim": claim, "citations": ["E1"]},
            {"claim": "제공 근거가 없는 답입니다.", "citations": ["E99"]},
        ],
        "limitations": "",
    }
    audit = verification(
        check(1, requirements=["R1"], citations=["E1"], match=match),
        check(2, requirements=["R2" if len(required) == 2 else "R1"], citations=["E99"]),
        required=required,
    )
    result = resolve(draft, audit, evidence)
    assert result.status == "partial" and result.evidence == evidence
    assert Consultation(result, {}).answer.startswith(f"{claim} [E1]")
    assert missing in result.limitations and "E99" not in Consultation(result, {}).answer


@pytest.mark.parametrize(
    "claim",
    [
        "도드라지는 부위에 소량을 여러 번 얇게 올리세요.",
        "가볍게 두드리면서 피부색에 맞춘 컨실러로 경계를 연결하세요.",
        "열감이 돌면 마찰을 피하고 얇게 펴 바르세요.",
        "건조한 날에는 소량을 얇게 올리고 당기는 부위의 마찰을 줄이세요.",
    ],
    ids=["13", "V13", "V04", "new-transferable-dry-base"],
)
def test_open_consultation_keeps_grounded_alternative(claim):
    evidence, _, _ = verify_selection([SELECTED], {"C1": HIT})
    evidence = [evidence[0].model_copy(update={"quote": claim})]
    draft = {"claims": [{"claim": claim, "citations": ["E1"]}], "limitations": ""}
    audit = verification(
        check(1, requirements=["R1"], citations=["E1"]),
        required=["적용 상황에서 지킬 수 있는 화장 조언"],
        optional=["추가로 가능한 조언"],
    )
    result = resolve(draft, audit, evidence)
    assert result.status == "answered" and result.evidence == evidence
    assert Consultation(result, {}).answer == f"{claim} [E1]"


class Retrieval:
    async def search(self, _q, _strategy):
        return SearchResult(candidates=[HIT], embedding_input_tokens=1, embedding_ms=0, lookup_ms=0)

    async def context(self, loc):
        return originals(loc)


class Model:
    async def run(self, stage, *_args):
        data = {
            "select": {"sufficiency": "sufficient", "ranking": [SELECTED], "evidence": [SELECTED]},
            "answer": {
                "status": "answered",
                "limitations": "",
                "limitation_citations": [],
                "claims": [{"claim": "볼에 한정됩니다.", "citations": ["E1"]}],
            },
            "detect": verification(check(1, requirements=["R1"], citations=["E1"])),
        }
        return StageResult(data[stage], {"input_tokens": 1, "output_tokens": 1}, 0, 1, None)


def test_pipeline_keeps_document_citations():
    result = asyncio.run(KnowledgeService(Retrieval(), Model()).consult("볼에 사용하나요?"))
    assert result.reply.status == "answered"
    assert result.reply.evidence[0].document_id == 8
    assert "[E1]" in result.answer


def test_followup_search_respects_existing_character_limit():
    question, prior = "가" * 1000, "나" * 1000
    retrieval = Retrieval()
    retrieval.search = AsyncMock(
        return_value=SearchResult(
            candidates=[],
            embedding_input_tokens=1,
            embedding_ms=0,
            lookup_ms=0,
        )
    )
    reply = asyncio.run(
        KnowledgeService(retrieval, Model()).consult(
            question,
            prior_user_context=prior,
        )
    )
    retrieval.search.assert_awaited_once_with(question + "\n" + prior[:999], "large")
    assert reply.reply.status == "insufficient_evidence"


def test_incomplete_verification_returns_error_without_retrying_stage():
    stages = []

    class IncompleteModel(Model):
        async def run(self, stage, *args):
            stages.append(stage)
            if stage == "detect":
                assert args[-1] == 1700
                raise UpstreamError("Incomplete knowledge response")
            return await super().run(stage, *args)

    result = asyncio.run(KnowledgeService(Retrieval(), IncompleteModel()).consult("볼에 쓰나요?"))
    assert stages == ["select", "answer", "detect"]
    assert result.reply.status == "error" and not result.reply.evidence and not result.reply.claims


@pytest.mark.parametrize("citation_ids", [[], ["E1"]], ids=["without-citations", "with-citation"])
def test_http_empty_draft_uses_verification_only_for_cited_limits(
    citation_ids,
    routed_chat,
    monkeypatch,
):
    limitation = (
        "해당 원문은 볼 사용만 설명합니다."
        if citation_ids
        else "제공된 근거만으로는 ‘보습’이라고 표시된 립스틱이 마스크에 얼마나 묻을지 "
        "확인할 수 없습니다."
    )

    class EmptyDraftModel(Model):
        async def run(self, stage, *args):
            result = await super().run(stage, *args)
            if stage == "answer":
                result.content.update(
                    status="insufficient",
                    claims=[],
                    limitations=limitation,
                    limitation_citations=citation_ids,
                )
            elif stage == "detect":
                if not citation_ids:
                    raise UpstreamError("Incomplete knowledge response")
                result.content.update(verification())
            return result

    ask, _, _, _ = routed_chat
    model = EmptyDraftModel()
    model.run = AsyncMock(wraps=model.run)
    consultation = KnowledgeService(Retrieval(), model)
    monkeypatch.setattr(chat_service, "consult_knowledge", consultation.consult)
    response = ask(
        "집에 있는 립스틱이 마스크에 많이 묻을까요? "
        "케이스에는 보습이라고만 써 있고 어떤 제품인지 모르겠어요."
    )
    assert response.status_code == 200
    body = response.json()
    assert body["knowledge"]["status"] == "insufficient_evidence"
    assert body["knowledge"]["claims"] == []
    assert [item["id"] for item in body["knowledge"]["evidence"]] == citation_ids
    stages = [call.args[0] for call in model.run.await_args_list]
    if citation_ids:
        assert stages == ["select", "answer", "detect"]
        assert body["answer"] == limitation + " [E1]"
    else:
        assert stages == ["select", "answer"]
        assert body["answer"] == "제공된 원문으로는 질문에 필요한 내용을 확인할 수 없습니다."


@pytest.mark.parametrize(
    "override",
    [
        {"requirements": []},
        {"reviews": []},
        {"reviews": [check(0, requirements=["R1"], citations=["E1"])]},
        {"reviews": [check(1, requirements=["R2"], citations=["E1"])]},
        {"reviews": [check(1, requirements=["R1"], citations=["E99"])]},
        {"reviews": [check(1, requirements=["R1"], label="UNKNOWN")]},
        {"reviews": [check(1, requirements=["R1"], applicability="UNKNOWN")]},
        {"reviews": [{k: v for k, v in check(1).items() if k != "applicability"}]},
        {"reviews": [check(1) | {"condition_evidence_ids": "E1"}]},
        {
            "reviews": [
                check(
                    1,
                    requirements=["R1"],
                    citations=["E1"],
                    condition_ids=["E99"],
                    link="SAME_CONTEXT",
                )
            ]
        },
        {"reviews": [check(1) | {"scope_basis": "UNKNOWN"}]},
        {"limits_unsubstantiated": "false"},
    ],
    ids=[
        "missing-reqs",
        "missing-review",
        "index",
        "req-id",
        "evidence-id",
        "label",
        "scope-label",
        "missing-scope",
        "scope-field-type",
        "condition-id",
        "scope-basis",
        "type",
    ],
)
def test_invalid_verification_is_an_error_with_no_answer_or_sources(override):
    class InvalidModel(Model):
        async def run(self, stage, *_args):
            result = await super().run(stage)
            if stage == "detect":
                result.content.update(deepcopy(override))
            return result

    result = asyncio.run(KnowledgeService(Retrieval(), InvalidModel()).consult("볼에 사용하나요?"))
    assert result.reply.status == "error"
    assert not result.reply.claims and not result.reply.evidence
    assert "오류" in result.answer and "볼에 한정됩니다." not in result.answer


def test_no_selected_evidence_does_not_invent_personal_measurement():
    class NoEvidenceModel(Model):
        async def run(self, stage, *_args):
            assert stage == "select"
            result = await super().run(stage)
            result.content["evidence"] = []
            return result

    result = asyncio.run(
        KnowledgeService(Retrieval(), NoEvidenceModel()).consult("제 얼굴의 실측값을 알려 주세요.")
    )
    assert result.reply.status == "insufficient_evidence"
    assert "확인할 수 없습니다" in result.answer
    assert not result.reply.claims and not result.reply.evidence


def test_http_exposes_only_cited_boosts_and_limits_in_existing_shape(client, monkeypatch):
    before = candidate_for(BEFORE, "preceding-chunk")
    after = candidate_for(AFTER, "following-chunk")

    class NeighborRetrieval(Retrieval):
        async def search(self, _q, _strategy):
            result = await super().search(_q, _strategy)
            result.candidates.extend([before, after])
            return result

        async def context(self, loc):
            return neighboring_originals(loc)

    class CitationModel(Model):
        async def run(self, stage, _prompt, value, *_args):
            result = await super().run(stage)
            if stage == "answer":
                evidence = value["evidence"]
                assert evidence[1]["text"] == f"앞 문단: {BEFORE.text}"
                assert evidence[2]["text"] == f"뒤 문단: {AFTER.text}"
                result.content["claims"][0]["claim"] += " [E98]"
                result.content["limitations"] = "패인 흉터에 한정된 방법입니다. [E1.1, E99]"
                result.content["limitation_citations"] = [evidence[1]["id"], "E99"]
            elif stage == "detect":
                assert value["draft"]["limitation_citations"] == ["E1.1", "E99"]
                base, neighbor, _ = value["original_contexts"]
                assert neighbor["id"] == "E1.1" and neighbor["block"] == BEFORE.block_order
                assert base["source"] == neighbor["source"]
            return result

    monkeypatch.setattr(get_settings(), "g5_enabled", True)
    consultation = KnowledgeService(NeighborRetrieval(), CitationModel())
    monkeypatch.setattr(chat_service, "consult_knowledge", consultation.consult)
    response = client.post(
        "/api/chat",
        json={"locale": "ko", "message": "패인 흉터 화장은 어떻게 해요?"},
        headers={"Authorization": "Bearer ok-1"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["knowledge"]["status"] == "answered"
    assert payload["knowledge"]["claims"][0]["citations"] == ["E1"]
    assert payload["knowledge"]["limitations"] == "패인 흉터에 한정된 방법입니다. [E1.1]"
    assert "E98" not in payload["answer"] and "E99" not in payload["answer"]
    records = payload["knowledge"]["evidence"]
    assert [r["id"] for r in records] == ["E1", "E1.1"]
    assert records[1] == {
        "id": "E1.1",
        "documentId": 8,
        "chunkId": "preceding-chunk",
        "title": "제목",
        "sourceFileId": 2,
        "sourceVersion": "v1",
        "blockOrder": 3,
        "startUtf16": 0,
        "endUtf16": 10,
        "sourceLocator": BEFORE.source_locator,
        "quote": BEFORE.text,
        "relevance": "support",
    }


def test_upstream_failure_is_an_explicit_error():
    class Failing(Retrieval):
        async def search(self, _q, _strategy):
            raise UpstreamError("timeout")

    result = asyncio.run(KnowledgeService(Failing(), Model()).consult("볼에 사용하나요?"))
    assert result.reply.status == "error"
    assert not result.reply.claims


def test_chat_service_only_routes_eligible_free_chat_when_enabled(monkeypatch):
    from types import SimpleNamespace

    from app.core.config import get_settings
    from app.schemas.chat import ChatRequest
    from app.schemas.knowledge import KnowledgeReply
    from app.services import chat_service

    class ChatModel:
        configured = False

    read = []

    async def consult(question):
        read.append(question)
        return SimpleNamespace(
            answer="검증된 근거가 없습니다.",
            reply=KnowledgeReply(status="insufficient_evidence"),
        )

    settings = get_settings()
    monkeypatch.setattr(chat_service, "consult_knowledge", consult)
    service = chat_service.ChatService(None, ChatModel())
    explicit = ChatRequest(
        message="홍조에 메이크업은 어떻게 하나요?",
        locale="ko",
        request_type="knowledge_consultation",
    )
    monkeypatch.setattr(settings, "g5_enabled", False)
    disabled = asyncio.run(service.answer(explicit))
    assert disabled.knowledge is None and not read
    assert disabled.supervisor.result.reason == "tool_unavailable"
    monkeypatch.setattr(settings, "g5_enabled", True)
    enabled = asyncio.run(service.answer(explicit.model_copy(update={"request_type": "chat"})))
    assert enabled.knowledge.status == "insufficient_evidence"
    assert enabled.supervisor.result.tool == "knowledge"
    assert enabled.supervisor.result.status == "unsupported"
    assert read == [explicit.message]


def test_price_question_keeps_existing_route_with_g5_enabled(monkeypatch):
    from app.core.config import get_settings
    from app.schemas.chat import ChatRequest
    from app.services import chat_service

    class Graph:
        async def find_products(self, _terms):
            return []

    class ExistingModel:
        configured = True

        async def complete(self, _messages):
            return "기존 상담 응답"

    async def forbidden(_question):
        raise AssertionError("Price request entered G5")

    settings = get_settings()
    monkeypatch.setattr(settings, "g5_enabled", True)
    monkeypatch.setattr(settings, "g1_supervisor_enabled", False)
    monkeypatch.setattr(chat_service, "consult_knowledge", forbidden)
    result = asyncio.run(
        chat_service.ChatService(Graph(), ExistingModel()).answer(
            ChatRequest(message="홍조 커버 파운데이션 가격이 얼마예요?", locale="ko")
        )
    )
    assert result.knowledge is None
    assert result.supervisor.result.tool == "graph_chat"


@pytest.fixture
def routed_chat(client, graph, monkeypatch):
    class RecordingChatService(chat_service.ChatService):
        async def answer(self, req, principal_key=None):
            response = await super().answer(req, principal_key)
            self.last_route = response.supervisor
            self.request = req
            return response

    consult = AsyncMock(
        return_value=Consultation(
            KnowledgeReply(status="insufficient_evidence", limitations="원문 확인 필요"), {}
        )
    )
    monkeypatch.setattr(chat_service, "consult_knowledge", consult)
    monkeypatch.setattr(get_settings(), "g5_enabled", True)
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", True)
    llm = PlanLlm(intent="general")
    service = RecordingChatService(graph, llm, SessionCatalog())
    client.app.dependency_overrides[chat_service.get_chat_service] = lambda: service

    def ask(message, **fields):
        return client.post(
            "/api/chat",
            json={"locale": "ko", "message": message, "requestId": str(uuid4()), **fields},
            headers={"Authorization": "Bearer ok-1"},
        )

    return ask, service, llm, consult


@pytest.mark.parametrize(
    "message",
    [
        "립밤을 바른 뒤 립스틱이 고르게 발리려면 어떻게 하면 돼요?",
        "화장품 사용자 설문에서 방부제 성분과 향료는 각각 어떤 반응이 있었나요?",
        "스킨케어에서 보습 성분의 역할과 일반적인 종류를 설명해 주세요.",
    ],
)
@pytest.mark.parametrize("enabled", [True, False], ids=["g5-on", "g5-off"])
def test_http_routes_general_makeup_and_research(message, enabled, routed_chat, monkeypatch):
    ask, service, llm, consult = routed_chat
    monkeypatch.setattr(get_settings(), "g5_enabled", enabled)
    response = ask(
        message, recentMessages=[{"id": "prior", "role": "user", "text": "틴트 가격은?"}]
    )
    assert response.status_code == 200
    assert service.request.recent_messages[0].text == "틴트 가격은?"
    assert service.last_route.result.tool == ("knowledge" if enabled else "graph_chat")
    assert bool(response.json().get("knowledge")) == enabled
    if enabled:
        assert service.last_route.intent.intent == "knowledge"
        consult.assert_awaited_once_with(message)
        assert llm.calls == 0
    else:
        consult.assert_not_awaited()
        assert llm.calls == 1


@pytest.mark.parametrize(
    ("message", "expected_tool"),
    [
        ("이마 하이라이트를 옆으로 펴는 게 나을까요?", "knowledge"),
        ("볼은 덜 넓어 보이고 싶어요. 쉐딩 방향을 잡아줘요.", "knowledge"),
        ("토너를 피부에 바를 때 화장솜을 꼭 써야 하나요?", "knowledge"),
        ("bb크림이 톤업크림보다 잡티를 잘 가려요?", "knowledge"),
        ("스파출라로 파운데이션을 얇게 올릴 때 제형은 어떤 걸 써요?", "knowledge"),
        ("에어브러시 메이크업에서 손에 든 부분이 분사기인지 헷갈려요.", "knowledge"),
        ("저자극 세안제 실험에서 모공 수를 어떤 기기로 셌나요?", "knowledge"),
        ("얼굴형 자료에서 볼 색을 어느 방향으로 넣으라고 했어요?", "knowledge"),
        ("논문에서 사용한 피부 젤의 대조군 결과는 어땠나요?", "knowledge"),
        ("요즘 판매하는 BB크림과 톤업크림은 같은 제품처럼 써도 될까요?", "knowledge"),
        ("시판 모공 프라이머 두 제품을 비교한 연구에서 어느 쪽이 오래 갔나요?", "knowledge"),
        ("논문 속 모공 프라이머가 지금 그 회사가 납품 중인 같은 제품인가요?", "graph_chat"),
        ("논문 속 모공 프라이머가 요새 온라인몰에 파는 그 물건과 같은 건가요?", "graph_chat"),
        ("논문 속 모공 프라이머가 온라인몰에 올라온 제품과 같은 건가요?", "graph_chat"),
        ("논문의 CC크림 A가 지금 온라인몰에서 팔리는 그 제품 맞아요?", "graph_chat"),
        ("프린터 토너를 어떻게 관리해요?", "graph_chat"),
        ("프린터 토너가 손에 묻었는데 물로 닦아도 돼요?", "graph_chat"),
        ("프린터 토너로 찍은 사진이 볼수록 흐려져요. 왜 그럴까요?", "graph_chat"),
        ("축구 하이라이트에서 득점 장면만 찾아줘요.", "graph_chat"),
        ("축구에서 코너킥 하이라이트는 어디서 봐요?", "graph_chat"),
        ("요리용 스파출라로 피자 베이스를 눌러도 돼요?", "graph_chat"),
        ("에어브러시로 모형을 칠할 때 공기압을 어떻게 잡아줘요?", "graph_chat"),
        ("에어브러시로 레진 모형 얼굴 도색은 어떻게 해요?", "graph_chat"),
    ],
)
def test_http_routes_beauty_terms_in_context(message, expected_tool, routed_chat):
    ask, service, _, consult = routed_chat
    response = ask(message)
    assert response.status_code == 200
    assert service.last_route.result.tool == expected_tool
    if expected_tool == "knowledge":
        consult.assert_awaited_once_with(message)
    else:
        consult.assert_not_awaited()


@pytest.mark.parametrize(
    ("question", "prior"),
    [
        pytest.param(
            "그럼 컨실러는 지금 바른 파데보다 밝은 걸 써요, 어두운 걸 써요?",
            "파데는 다 발랐어요. 앞볼이 좀 평평해 보여서 앞볼만 살짝 도톰해 보이게 하고 싶어요.",
            id="D07",
        ),
        pytest.param(
            "그럼 컨실러는 지금 바른 파데보다 밝은 걸 써요, 어두운 걸 써요?",
            "파데는 다 발랐어요. 얼굴 옆선이 좀 도드라져 보여서 바깥쪽만 살짝 눌러주고 싶어요.",
            id="D08",
        ),
        pytest.param(
            "그럼 그 논문에서 피부 자극은 몇 명한테 "
            "붙이는 방식으로 봤어요, 열어 둔 방식으로 봤어요?",
            "패션프루트 씨앗 추출물을 넣은 리퀴드 파운데이션이랑 컨실러 무스 연구를 보고 있어요.",
            id="P11A",
        ),
        pytest.param(
            "그럼 그 논문에서 피부 자극은 몇 명한테 "
            "붙이는 방식으로 봤어요, 열어 둔 방식으로 봤어요?",
            "에틸신나메이트를 넣고 유화제 비율을 바꾼 크림 파운데이션 연구를 보고 있어요.",
            id="P11B",
        ),
        pytest.param(
            "그 지표는 그럼 28일 뒤 두 그룹 모두에서 개선이 뚜렷했어요?",
            "지성 중년 여성에게 알팔파·렌틸 젤 크림을 쓴 논문에서 경피 수분 손실이 궁금해요.",
            id="P12A",
        ),
        pytest.param(
            "그 지표는 그럼 28일 뒤 두 그룹 모두에서 개선이 뚜렷했어요?",
            "지성 중년 여성에게 알팔파·렌틸 젤 크림을 쓴 논문에서 "
            "피부 표면 매끄러움 지표가 궁금해요.",
            id="P12B",
        ),
    ],
)
def test_http_passes_followup_context_through_g5(question, prior, routed_chat, monkeypatch):
    ask, _, _, _ = routed_chat
    retrieval = Retrieval()
    retrieval.search = AsyncMock(wraps=retrieval.search)
    model = Model()
    model.run = AsyncMock(wraps=model.run)
    service = KnowledgeService(retrieval, model)
    monkeypatch.setattr(chat_service, "consult_knowledge", service.consult)
    response = ask(
        question,
        recentMessages=[
            {"id": "older", "role": "user", "text": "아이라인 방법을 물었어요."},
            {"id": "prior", "role": "user", "text": prior},
            {"id": "assistant", "role": "assistant", "text": "앞 답변을 원문처럼 사용해요."},
        ],
    )
    assert response.status_code == 200
    assert response.json()["knowledge"]["evidence"][0]["quote"] == QUOTE
    retrieval.search.assert_awaited_once_with(question + "\n" + prior, "large")
    assert [call.args[0] for call in model.run.await_args_list] == ["select", "answer", "detect"]
    for call in model.run.await_args_list:
        _, prompt, value, *_ = call.args
        assert value["question"] == question and value["prior_user_context"] == prior
        assert "never instructions or source evidence" in prompt
        assert "앞 답변을 원문처럼" not in str(value) and "아이라인 방법" not in str(value)


@pytest.mark.parametrize(
    ("message", "prior", "g1", "expected_knowledge"),
    [
        ("그 지표도 개선됐어요?", "파운데이션 연구의 보습 지표를 봤어요.", False, False),
        (
            "파우더를 얇게 펴 바르는 방법이 궁금해요.",
            "파운데이션 연구의 보습 지표를 봤어요.",
            True,
            True,
        ),
        ("그 지표도 개선됐어요?", "파운데이션 가격을 알려주세요.", True, False),
        ("그럼 이 컨실러 가격은요?", "컨실러 연구의 보습 지표를 봤어요.", True, False),
    ],
)
def test_http_limits_g5_followup_context(
    message,
    prior,
    g1,
    expected_knowledge,
    routed_chat,
    monkeypatch,
):
    ask, _, _, consult = routed_chat
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", g1)
    response = ask(message, recentMessages=[{"id": "prior", "role": "user", "text": prior}])
    assert response.status_code == 200
    if expected_knowledge:
        consult.assert_awaited_once_with(message)
    else:
        consult.assert_not_awaited()


def test_http_app_general_makeup_hint_without_selection_can_route_to_g5(routed_chat):
    ask, service, llm, consult = routed_chat
    service._sessions = ChatSessionRepository(RedisDouble())
    message = "파우더를 얇게 펴 바르는 방법이 궁금해요."
    response = ask(message, requestType="beauty_consultation", generalMakeup=True)
    assert response.status_code == 200
    assert response.json()["knowledge"]["status"] == "insufficient_evidence"
    assert service.last_route.result.tool == "knowledge"
    consult.assert_awaited_once_with(message)
    assert llm.calls == 0


@pytest.mark.parametrize(
    "message", ["화장실 청소는 어느 순서로 해요?", "베이스 기타는 어떻게 쳐요?"]
)
def test_http_shared_words_without_a_beauty_question_stay_in_general_chat(routed_chat, message):
    ask, service, _, consult = routed_chat
    assert ask(message).status_code == 200
    assert service.last_route.result.tool == "graph_chat"
    consult.assert_not_awaited()


@pytest.mark.parametrize(
    ("locale", "message"),
    [
        ("en", "How can I apply mascara without smudging?"),
        ("ja", "マスカラがにじまない塗り方を教えてください。"),
        ("zh", "怎么涂睫毛膏才不容易晕开？"),
    ],
)
def test_http_keeps_existing_other_locale_route(routed_chat, locale, message):
    ask, service, _, consult = routed_chat
    response = ask(message, locale=locale)
    assert response.status_code == 200
    assert service.last_route.result.tool == "graph_chat"
    consult.assert_not_awaited()


def test_http_keeps_product_and_ingredient_requests_with_catalog(routed_chat):
    ask, service, llm, consult = routed_chat
    service._sessions = ChatSessionRepository(RedisDouble())
    llm.plan = {"intent": "search", "category": "lip", "maxPriceKRW": 20000}
    products = ask("립 바르는 법도 설명하고 2만원 이하에서 쓸 제품을 찾아줘.")
    assert products.status_code == 200
    assert service.last_route.result.tool == "beauty"
    assert products.json()["products"]

    llm.plan = {
        "intent": "detail",
        "scope": "previous",
        "ingredientLookup": True,
        "ingredientName": "향료",
    }
    ingredients = ask(
        "제품 자료를 찾아봤는데 이 립의 향료 성분을 확인해 주세요.",
        requestType="beauty_consultation",
        screenContext={"screenId": "product-detail", "productId": "a", "shadeId": "a-03"},
    )
    assert ingredients.status_code == 200
    assert service.last_route.result.tool == "beauty"
    assert service.last_route.intent.intent == "ingredient"
    evidence = ingredients.json()["ingredientResults"][0]
    assert (evidence["productId"], evidence["shadeId"]) == ("a", "a-03")
    assert service._catalog.ingredient_calls == [("a", "a-03")]
    consult.assert_not_awaited()


def test_http_keeps_look_screen_without_style_context(routed_chat):
    ask, service, _, consult = routed_chat
    response = ask(
        "파우더를 어디에 바르는지 궁금해요.",
        screenContext={"screenId": "look-detail", "lookId": "look-1"},
    )
    assert response.status_code == 200
    assert service.last_route.result.tool == "graph_chat"
    consult.assert_not_awaited()


def test_http_active_shopping_session_keeps_general_makeup_context(routed_chat):
    ask, service, llm, consult = routed_chat
    service._sessions = ChatSessionRepository(RedisDouble())
    llm.plan = {"intent": "search", "category": "lip", "maxPriceKRW": 20000}
    first = ask("2만원 이하 립 추천해줘.", requestType="beauty_consultation")
    assert first.status_code == 200
    previous = first.json()["chatContext"]
    followup = ask(
        "파우더를 맨 마지막에 바르는 방법은요?",
        requestType="beauty_consultation",
        generalMakeup=True,
        chatContext=previous,
        recentMessages=[{"id": "prior", "role": "user", "text": "2만원 이하 립 추천해줘."}],
    )
    assert followup.status_code == 200
    assert followup.json()["chatContext"]["session"] == previous["session"]
    assert followup.json()["sessionStatus"] == "unchanged"
    assert service.last_route.result.tool == "graph_chat"
    consult.assert_not_awaited()


def test_http_keeps_style_and_stops_shopping_with_ar(routed_chat):
    ask, service, llm, consult = routed_chat
    style = ask("이 룩의 베이스는 어떻게 바르나요?", requestType="style_consultation")
    assert style.status_code == 200
    assert service.last_route.result.tool == "style"
    compound = ask("립 추천하고 그걸 AR에 발라줘.")
    assert compound.status_code == 200
    assert service.last_route.intent.intent == "compound"
    assert service.last_route.plan.tasks == []
    assert service.last_route.result.status == "unsupported"
    assert llm.calls == 0
    consult.assert_not_awaited()
