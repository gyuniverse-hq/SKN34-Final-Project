import asyncio
import json
from copy import deepcopy
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest

from app.clients.openai_responses_client import OpenAIResponses, StageResult
from app.core.config import get_settings
from app.core.errors import UpstreamError
from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter
from app.repositories.chat_session_repository import ChatSessionRepository
from app.schemas.knowledge import (
    Candidate,
    KnowledgeReply,
    NeighborResult,
    OriginalBlock,
    SearchResult,
)
from app.services import chat_service, knowledge_service
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
    fallback = resolve(
        draft | {"claims": draft["claims"][1:]},
        audit | {"reviews": [audit["reviews"][1] | {"index": 1}]},
        citable,
    )
    assert fallback.status == ("partial" if keep else "insufficient_evidence")
    assert [c.claim for c in fallback.claims] == ([secondary] if keep else [])
    assert [e.id for e in fallback.evidence] == ([extra] if keep else [])
    if keep:
        assert "기본 도포법" in fallback.limitations
        assert "야외에서 덧바르는 방법" in fallback.limitations
        assert secondary + f" [{extra}]" in Consultation(fallback, {}).answer


@pytest.mark.parametrize(
    ("advice", "condition"),
    [
        ("건조한 부위에만 보습 후 베이스를 얇게 바르세요.", "건조한 부위에만"),
        ("유분이 많을 때는 바르기 전에 여분의 유분을 가볍게 눌러 정돈하세요.", "유분이 많을 때는"),
        ("각질이 들뜬 부위에만 기초 보습 후 가볍게 밀착시키세요.", "각질이 들뜬 부위에만"),
    ],
    ids=["dry-base", "oily-preparation", "flaky-preparation"],
)
@pytest.mark.parametrize("coverage", ["answered", "partial", "conditional-only"])
def test_http_conditional_general_advice_keeps_citations_without_filling_missing_core(
    advice, condition, coverage, routed_chat, monkeypatch
):
    # Prescribed verdicts test the service contract, not Terra's semantic accuracy.
    ask, service, _, _ = routed_chat
    block = BEFORE.model_copy(update={"text": advice})
    candidate = candidate_for(block, "general-preparation")
    missing_core = coverage != "answered"
    conditional_only = coverage == "conditional-only"
    required = ("사용 부위", "실행 순서") if missing_core else ("사용 부위",)
    question = (
        "그럼 사용하는 부위와 순서를 알려줄래요?"
        if missing_core
        else "그럼 사용하는 부위는 어디예요?"
    )
    prior = "컨실러의 사용 부위와 색상별 효과가 궁금해요."

    class AdviceRetrieval(Retrieval):
        async def search(self, question, strategy):
            result = await super().search(question, strategy)
            result.candidates.append(candidate)
            return result

        async def context(self, locations):
            result = originals(locations)
            result[0].blocks.insert(0, block)
            return result

    class PrescribedModel(Model):
        async def run(self, stage, prompt, value, schema, max_tokens):
            result = await super().run(stage)
            if stage == "answer":
                result.content["claims"] = [
                    {"claim": QUOTE, "citations": ["E1"]},
                    {"claim": advice, "citations": ["E1.1"]},
                ]
            elif stage == "detect":
                assert prompt == knowledge_service.DETECT + knowledge_service._FOLLOWUP_INSTRUCTIONS
                assert max_tokens == 1700 and schema == knowledge_service.DETECT_SCHEMA
                assert value["question"] == question and value["prior_user_context"] == prior
                assert value["original_contexts"][1]["text"] == "앞 문단: " + advice
                result = StageResult(
                    verification(
                        check(
                            1,
                            requirements=["R1"],
                            citations=["E1"],
                            applicability="UNCERTAIN" if conditional_only else "APPLICABLE",
                        ),
                        check(
                            2,
                            requirements=[f"R{len(required) + 1}"],
                            citations=["E1.1"],
                            applicability="CONDITIONAL",
                            condition=condition,
                        ),
                        required=required,
                        optional=["근거 범위의 일반 준비 조언"],
                    ),
                    result.usage,
                    0,
                    1,
                    None,
                )
            return result

    model = PrescribedModel()
    model.run = AsyncMock(wraps=model.run)
    consultation = KnowledgeService(AdviceRetrieval(), model)
    monkeypatch.setattr(chat_service, "consult_knowledge", consultation.consult)
    response = ask(
        question,
        requestType="knowledge_consultation",
        recentMessages=[{"id": "prior", "role": "user", "text": prior}],
    )
    assert response.status_code == 200 and service.last_route.result.tool == "knowledge"
    body = response.json()
    assert body["knowledge"]["status"] == ("partial" if missing_core else "answered")
    expected_claims = [
        {"claim": QUOTE, "citations": ["E1"]},
        {"claim": advice, "citations": ["E1.1"]},
    ]
    assert body["knowledge"]["claims"] == (
        expected_claims[1:] if conditional_only else expected_claims
    )
    evidence = body["knowledge"]["evidence"]
    assert [e["id"] for e in evidence] == (["E1.1"] if conditional_only else ["E1", "E1.1"])
    assert evidence[-1]["quote"] == advice
    assert evidence[-1]["chunkId"] == "general-preparation"
    assert advice + " [E1.1]" in body["answer"]
    assert "색상별 효과" not in body["knowledge"]["limitations"]
    if missing_core:
        assert "실행 순서" in body["knowledge"]["limitations"]
        if conditional_only:
            assert "사용 부위" in body["knowledge"]["limitations"]
            assert "[E1]" not in body["answer"]
    else:
        assert body["knowledge"]["limitations"] == ""
    assert [call.args[0] for call in model.run.await_args_list] == ["select", "answer", "detect"]


@pytest.mark.parametrize(
    ("required", "claim", "condition", "match", "scope", "basis"),
    [
        (
            "수분량 비교",
            "선호도 조사에서만 A가 더 높았습니다.",
            "선호도 조사에서만",
            "MISMATCHED",
            "CONDITIONAL",
            "BOUNDED",
        ),
        (
            "피부 자극 감소",
            "만족도 조사에서만 B가 더 높았습니다.",
            "만족도 조사에서만",
            "MISMATCHED",
            "CONDITIONAL",
            "BOUNDED",
        ),
        (
            "야외 촬영에서 고정하는 방법",
            "실내에서만 파우더를 누르세요.",
            "실내에서만",
            "PARTIAL_MATCH",
            "NOT_APPLICABLE",
            "CONFLICT",
        ),
        (
            "쿠션 시험군의 지속력",
            "스틱 시험군에서만 지속력이 높았습니다.",
            "스틱 시험군에서만",
            "MISMATCHED",
            "CONDITIONAL",
            "BOUNDED",
        ),
    ],
    ids=["different-metric", "preference-not-irritation", "conflicting-setting", "different-arm"],
)
def test_general_advice_cannot_bypass_metric_or_scope_guards(
    required, claim, condition, match, scope, basis
):
    block = OriginalBlock(
        block_order=4, kind="paragraph", text=claim, source_locator={"paragraph": 4}
    )
    evidence, _, _ = verify_selection(
        [SELECTED | {"exact_quote": claim}], {"C1": candidate_for(block, "other-scope")}
    )
    draft = {"claims": [{"claim": claim, "citations": ["E1"]}], "limitations": ""}
    audit = verification(
        check(
            1,
            requirements=["R1"],
            citations=["E1"],
            match=match,
            applicability=scope,
            basis=basis,
            condition=condition,
        ),
        required=[required],
    )
    result = resolve(draft, audit, evidence)
    assert result.status == "insufficient_evidence"
    assert not result.claims and not result.evidence
    assert claim not in Consultation(result, {}).answer


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


def test_delegated_explanation_scope_reaches_all_g5_stages_and_keeps_coverage():
    seen = []

    class ScopedModel(Model):
        async def run(self, stage, prompt, payload, *args):
            seen.append((stage, prompt, payload))
            return await super().run(stage, prompt, payload, *args)

    question = "사용 방법을 설명하고 제품도 찾아줘"
    result = asyncio.run(
        KnowledgeService(Retrieval(), ScopedModel()).consult(
            question, delegation_scope="explanation"
        )
    )
    assert [stage for stage, _, _ in seen] == ["select", "answer", "detect"]
    assert all("Catalog actions are NOT requirements" in prompt for _, prompt, _ in seen)
    assert all(payload["question"] == question for _, _, payload in seen)
    assert result.trace["coverage"]["scope"] == "explanation"
    assert result.trace["coverage"]["requirements"] == [
        {"requirement_id": "R1", "description": "사용 범위", "fulfilled": True}
    ]


def test_coverage_uses_original_review_ids_after_first_claim_dropped():
    from app.schemas.consultation_answer import KnowledgeCoverage

    evidence, _, _ = verify_selection([SELECTED], {"C1": HIT})
    draft = {
        "status": "partial",
        "limitations": "",
        "claims": [
            {"claim": "모든 곳에 사용", "citations": ["E1"]},
            {"claim": "볼에 한정됩니다.", "citations": ["E1"]},
        ],
    }
    audit = verification(
        check(1, label="UNSUPPORTED", match="MISMATCHED"),
        check(2, requirements=["R2"], citations=["E1"]),
        required=("개인 원인", "사용 범위"),
    )
    coverage = KnowledgeCoverage(scope="explanation")
    reply = resolve(draft, audit, evidence, coverage=coverage)
    assert reply.status == "partial" and len(reply.claims) == 1
    assert [(r.requirement_id, r.fulfilled) for r in coverage.requirements] == [
        ("R1", False),
        ("R2", True),
    ]
    assert reply.findings[0].index == 1


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        ("audit_schema", "invalid_verification_schema"),
        ("claim_schema", "invalid_claim_schema"),
        ("count", "claim_review_mismatch"),
        ("requirements", "invalid_requirements"),
        ("requirement_id", "unknown_requirement"),
        ("evidence_id", "unknown_evidence"),
        ("incomplete", "incomplete_supported_claim"),
    ],
)
def test_verification_failure_logs_only_safe_diagnostics(failure, expected, caplog):
    class InvalidModel(Model):
        async def run(self, stage, *args):
            result = await super().run(stage, *args)
            data = deepcopy(result.content)
            if stage == "answer":
                data["claims"][0]["claim"] = "PRIVATE_DRAFT"
                if failure == "claim_schema":
                    data["claims"][0]["citations"] = 123
            if stage == "detect":
                data["reviews"][0]["reason"] = "PRIVATE_REASON"
                if failure == "audit_schema":
                    data["reviews"] = None
                elif failure == "count":
                    data["reviews"] = []
                elif failure == "requirements":
                    data["requirements"] = []
                elif failure == "requirement_id":
                    data["reviews"][0]["requirement_ids"] = ["PRIVATE_REQUIREMENT_ID"]
                elif failure == "evidence_id":
                    data["reviews"][0]["supporting_ids"] = ["PRIVATE_SOURCE_ID"]
                elif failure == "incomplete":
                    data["reviews"][0]["supporting_ids"] = []
            return StageResult(data, result.usage, 0, 1, None)

    with caplog.at_level("INFO", logger="app.services.knowledge_service"):
        result = asyncio.run(
            KnowledgeService(Retrieval(), InvalidModel()).consult("PRIVATE_QUESTION")
        )
    assert result.reply.status == "error"
    assert result.reply.claims == [] and result.reply.evidence == []
    assert result.trace["verificationFailure"]["code"] == expected
    assert result.trace["verificationFailure"]["claims"] == 1
    assert result.trace["verificationFailure"]["evidence"] == 1
    assert expected in caplog.text
    for private in (
        "PRIVATE_QUESTION",
        "PRIVATE_DRAFT",
        "PRIVATE_REASON",
        "PRIVATE_REQUIREMENT_ID",
        "PRIVATE_SOURCE_ID",
        QUOTE,
    ):
        assert private not in caplog.text


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
        "케이스에는 보습이라고만 써 있고 어떤 제품인지 모르겠어요.",
        requestType="knowledge_consultation",
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
        json={
            "locale": "ko",
            "message": "패인 흉터 화장은 어떻게 해요?",
            "requestType": "knowledge_consultation",
        },
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
    enabled = asyncio.run(service.answer(explicit))
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
    limiter = MemoryRateLimiter(limit=10)
    client.app.dependency_overrides[get_rate_limiter] = lambda: limiter

    def ask(message, **fields):
        return client.post(
            "/api/chat",
            json={"locale": "ko", "message": message, "requestId": str(uuid4()), **fields},
            headers={"Authorization": "Bearer ok-1"},
        )

    return ask, service, llm, consult


def test_general_multiturn_and_evidence_request_preserve_context(routed_chat):
    ask, service, llm, consult = routed_chat
    llm.complete = AsyncMock(return_value="베이스를 얇게 발라 보세요.")
    q1 = "볼 홍조를 화장으로 가리려면 어떻게 해요?"
    a1 = ask(q1)
    assert a1.status_code == 200 and service.last_route.result.tool == "graph_chat"
    history = [
        {"id": "q1", "role": "user", "text": q1},
        {"id": "a1", "role": "assistant", "text": a1.json()["answer"]},
    ]
    q2 = "피부가 건조할 때도 그렇게 해도 돼요?"
    a2 = ask(q2, recentMessages=history)
    assert a2.status_code == 200 and service.last_route.result.tool == "graph_chat"
    assert any(m["content"] == q1 for m in llm.complete.await_args.args[0])
    history.extend(
        [
            {"id": "q2", "role": "user", "text": q2},
            {"id": "a2", "role": "assistant", "text": a2.json()["answer"]},
        ]
    )
    q3 = "그럼 양은 얼마나 써요?"
    a3 = ask(q3, recentMessages=history)
    assert a3.status_code == 200 and service.last_route.result.tool == "graph_chat"
    messages = llm.complete.await_args.args[0]
    assert [m["content"] for m in messages[1:]] == [x["text"] for x in history] + [q3]
    consult.assert_not_awaited()


def test_general_new_topic_does_not_inherit_old_g5_context(routed_chat):
    ask, service, llm, consult = routed_chat

    async def complete(messages):
        if "Determine whether" in messages[0]["content"]:
            return '{"continuation": false}'
        return "새로운 주제에 대한 안내예요."

    llm.complete = AsyncMock(side_effect=complete)
    response = ask(
        "아이라인이 잘 번지는데 어떻게 해요?",
        recentMessages=[
            {"id": "q1", "role": "user", "text": "볼 홍조를 가릴 땐 어떻게 해요?"},
            {"id": "a1", "role": "assistant", "text": "베이스를 얇게 사용해요."},
        ],
    )
    assert response.status_code == 200 and service.last_route.result.tool == "graph_chat"
    assert llm.complete.await_args.args[0][-1]["content"] == "아이라인이 잘 번지는데 어떻게 해요?"
    consult.assert_not_awaited()


def test_app_general_makeup_multiturn_keeps_history_without_g5(routed_chat):
    from app.services.beauty_consultation_service import PLAN_PROMPT

    ask, service, llm, consult = routed_chat
    service._sessions = ChatSessionRepository(RedisDouble())
    answers = []

    async def complete(messages):
        if messages[0]["content"].startswith(PLAN_PROMPT):
            return json.dumps({"intent": "general"})
        answers.append(messages)
        return "화장 부위에 얇게 발라 보세요."

    llm.complete = AsyncMock(side_effect=complete)
    history = []
    context = None
    questions = ["볼의 붉은 기를 덜 보이게 하려면요?", "건조할 때도 괜찮아요?", "그럼 얼마나 써요?"]
    for i, question in enumerate(questions):
        response = ask(
            question,
            requestType="beauty_consultation",
            generalMakeup=i == 0,
            recentMessages=history,
            **({"chatContext": context} if context else {}),
        )
        assert response.status_code == 200
        assert response.json().get("knowledge") is None
        assert [m["content"] for m in answers[-1][1:]] == [turn["text"] for turn in history] + [
            question
        ]
        history.extend(
            [
                {"id": f"q{i}", "role": "user", "text": question},
                {"id": f"a{i}", "role": "assistant", "text": response.json()["answer"]},
            ]
        )
        context = response.json().get("chatContext")
    consult.assert_not_awaited()


def test_direct_evidence_question_uses_g5_without_extra_classifier(routed_chat):
    ask, service, llm, consult = routed_chat
    question = "홍조 메이크업에 그린 베이스를 쓰는 근거 자료는 무엇인가요?"
    response = ask(question, requestType="knowledge_consultation")
    assert response.status_code == 200 and service.last_route.result.tool == "knowledge"
    consult.assert_awaited_once_with(question)
    assert llm.calls == 0


def test_failed_evidence_request_does_not_fabricate_luna_answer(routed_chat):
    ask, service, llm, consult = routed_chat
    consult.return_value = Consultation(
        KnowledgeReply(status="error", limitations="근거 확인 중 오류가 발생했습니다."), {}
    )
    response = ask("홍조 메이크업의 근거 자료를 알려 주세요.", requestType="knowledge_consultation")
    assert response.status_code == 200 and service.last_route.result.tool == "knowledge"
    assert response.json()["knowledge"]["status"] == "error"
    assert response.json()["answer"] == "근거 확인 중 오류가 발생했습니다."
    assert not response.json()["knowledge"]["evidence"] and llm.calls == 0


def test_semantic_followup_uses_previous_answer_and_preserves_new_condition(routed_chat):
    ask, service, llm, consult = routed_chat
    llm.complete = AsyncMock(
        side_effect=[json.dumps({"intent": "general"}), "건조할 때는 보습을 먼저 확인하세요."]
    )
    history = [
        {"id": "q1", "role": "user", "text": "볼에 홍조가 있는데 화장으로 가리려면 어떻게 해요?"},
        {"id": "a1", "role": "assistant", "text": "그린 코렉터를 얇게 발라 보세요."},
    ]
    question = "피부가 많이 건조한 날에도 그렇게 해도 돼?"
    response = ask(question, requestType="beauty_consultation", recentMessages=history)
    assert response.status_code == 200
    assert service.last_route.result.tool == "graph_chat"
    messages = llm.complete.await_args.args[0]
    assert [m["content"] for m in messages[1:]] == [t["text"] for t in history] + [question]
    consult.assert_not_awaited()


def test_semantic_followup_keeps_three_turn_context(routed_chat):
    ask, service, llm, consult = routed_chat
    llm.complete = AsyncMock(return_value="상황에 맞는 도구를 사용해 보세요.")
    history = [
        {"id": "q1", "role": "user", "text": "홍조가 있는데 메이크업으로 어떻게 가려요?"},
        {"id": "a1", "role": "assistant", "text": "그린 코렉터를 얇게 발라 보세요."},
        {"id": "q2", "role": "user", "text": "피부가 건조해도 그렇게 해도 돼요?"},
        {"id": "a2", "role": "assistant", "text": "건조할 때는 보습을 먼저 확인하세요."},
    ]
    response = ask("그 상태에서 도구를 써도 될까요?", recentMessages=history)
    assert response.status_code == 200
    assert service.last_route.result.tool == "graph_chat"
    messages = llm.complete.await_args.args[0]
    assert [m["content"] for m in messages[1:]] == [t["text"] for t in history] + [
        "그 상태에서 도구를 써도 될까요?"
    ]
    consult.assert_not_awaited()


@pytest.mark.parametrize("question", ["그 제품 가격은 얼마예요?", "립 제품 추천해줘요."])
def test_semantic_followup_does_not_intercept_shopping(question, routed_chat):
    ask, _, llm, consult = routed_chat
    original = llm.complete
    llm.complete = AsyncMock(wraps=original)
    response = ask(
        question,
        recentMessages=[
            {
                "id": "q1",
                "role": "user",
                "text": "볼에 홍조가 있는데 화장으로 가리려면 어떻게 해요?",
            },
            {"id": "a1", "role": "assistant", "text": "그린 코렉터를 얇게 발라 보세요."},
        ],
    )
    assert response.status_code == 200
    consult.assert_not_awaited()
    assert all(
        "Determine whether" not in str(call.args[0]) for call in llm.complete.await_args_list
    )


def test_semantic_followup_rejects_topic_switch(routed_chat):
    ask, service, llm, consult = routed_chat
    original = llm.complete

    async def classify(messages):
        if "Determine whether" in messages[0]["content"]:
            return '{"continuation": false}'
        return await original(messages)

    llm.complete = AsyncMock(side_effect=classify)
    response = ask(
        "오늘 날씨는 어떤가요?",
        recentMessages=[
            {
                "id": "q1",
                "role": "user",
                "text": "볼에 홍조가 있는데 화장으로 가리려면 어떻게 해요?",
            },
            {"id": "a1", "role": "assistant", "text": "그린 코렉터를 얇게 발라 보세요."},
        ],
    )
    assert response.status_code == 200
    assert service.last_route.result.tool != "knowledge"
    consult.assert_not_awaited()


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
    assert service.last_route.result.tool == "graph_chat"
    assert response.json().get("knowledge") is None
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
    response = ask(message, requestType="knowledge_consultation")
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
        requestType="knowledge_consultation",
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
    "questions",
    [
        pytest.param(
            [
                "볼에 홍조가 있는데 메이크업으로 자연스럽게 가리려면 어떻게 해야 해?",
                "그 방법을 건조한 피부에 쓸 때는 뭘 조심해야 해?",
                "그럼 스펀지를 써도 돼요?",
                "그럼 모든 피부 타입에 똑같이 적용해도 된다는 뜻이야?",
            ],
            id="redness-four-turns",
        ),
        pytest.param(
            [
                "아이라인이 쉽게 번지는데 어떻게 그려야 해요?",
                "그 방법을 눈두덩이에 유분이 많을 때도 써요?",
                "그럼 이번에는 건조한 날로 바꿔서 설명해 주세요.",
                "그 조건에서도 같은 순서로 해도 돼요?",
            ],
            id="different-topic-changed-condition",
        ),
        pytest.param(
            [
                "립글로스 연구에서 수분량과 광택 결과가 궁금해요.",
                "그 지표 중에서는 광택만 알려줄래요?",
                "그럼 28일 이후에도 같은 결론인가요?",
            ],
            id="research-metric-three-turns",
        ),
    ],
)
@pytest.mark.parametrize("request_type", ["knowledge_consultation"])
def test_http_g5_keeps_contiguous_followups_through_all_stages(
    questions, request_type, routed_chat, monkeypatch
):
    ask, service, llm, _ = routed_chat
    service._sessions = ChatSessionRepository(RedisDouble())
    retrieval, model = Retrieval(), Model()
    retrieval.search = AsyncMock(wraps=retrieval.search)
    model.run = AsyncMock(wraps=model.run)
    consultation = KnowledgeService(retrieval, model)
    monkeypatch.setattr(chat_service, "consult_knowledge", consultation.consult)
    history = []
    for index, question in enumerate(questions):
        retrieval.search.reset_mock()
        model.run.reset_mock()
        response = ask(
            question,
            requestType=request_type,
            recentMessages=history,
            **(
                {"generalMakeup": True}
                if request_type == "beauty_consultation" and index == 0
                else {}
            ),
        )
        assert response.status_code == 200
        assert service.last_route.result.tool == "knowledge"
        assert response.json()["knowledge"]["evidence"][0]["quote"] == QUOTE
        prior = "\n".join(questions[:index])
        retrieval.search.assert_awaited_once_with(
            question + ("\n" + prior if prior else ""), "large"
        )
        assert [call.args[0] for call in model.run.await_args_list] == [
            "select",
            "answer",
            "detect",
        ]
        for call in model.run.await_args_list:
            value = call.args[2]
            assert value["question"] == question
            assert value.get("prior_user_context", "") == prior
            assert "앞 답변을 원문처럼 사용해요" not in str(value)
        history.extend(
            [
                {"id": f"u{index}", "role": "user", "text": question},
                {"id": f"a{index}", "role": "assistant", "text": "앞 답변을 원문처럼 사용해요."},
            ]
        )
    assert llm.calls == 0


@pytest.mark.parametrize(
    "interruption",
    [
        "2만원 이하 립 제품 추천해줘.",
        "그럼 립 제품을 찾아줘요.",
        "그 제품 가격은 얼마예요?",
        "그럼 이 룩의 레시피는요?",
        "오늘 일정 정리를 하고 있어요.",
    ],
)
@pytest.mark.parametrize("request_type", ["chat", "beauty_consultation", "knowledge_consultation"])
def test_http_g5_does_not_cross_an_interrupted_topic(interruption, request_type, routed_chat):
    ask, service, _, consult = routed_chat
    response = ask(
        "그럼 그 방법을 계속 써도 돼요?",
        requestType=request_type,
        recentMessages=[
            {"id": "old", "role": "user", "text": "볼 홍조를 화장으로 가리려면 어떻게 해요?"},
            {"id": "other", "role": "user", "text": interruption},
        ],
    )
    assert response.status_code == 200
    assert service.last_route.result.tool == "graph_chat"
    consult.assert_not_awaited()


@pytest.mark.parametrize("request_type", ["knowledge_consultation"])
def test_http_g5_followup_uses_new_topic_without_older_conditions(request_type, routed_chat):
    ask, _, _, consult = routed_chat
    older = "볼 홍조를 메이크업으로 가리려면 어떻게 해요?"
    newer = "립밤을 바른 뒤 립스틱을 고르게 바르는 방법이 궁금해요."
    history = [
        {"id": "old", "role": "user", "text": older},
        {"id": "old-followup", "role": "user", "text": "그 방법을 건조할 때도 써요?"},
    ]
    assert ask(newer, requestType=request_type, recentMessages=history).status_code == 200
    consult.assert_awaited_once_with(newer)
    consult.reset_mock()
    history.append({"id": "new", "role": "user", "text": newer})
    question = "그럼 그 방법은 어느 순서로 해요?"
    assert ask(question, requestType=request_type, recentMessages=history).status_code == 200
    consult.assert_awaited_once_with(question, prior_user_context=newer)


def test_http_g5_does_not_invent_a_topic_when_anchor_is_outside_history(routed_chat):
    ask, _, _, consult = routed_chat
    response = ask(
        "그럼 모든 경우에 적용해요?",
        recentMessages=[
            {"id": "followup", "role": "user", "text": "그럼 스펀지를 써도 돼요?"},
            {"id": "answer", "role": "assistant", "text": "볼 홍조 메이크업이라고 가정하세요."},
        ],
    )
    assert response.status_code == 200
    consult.assert_not_awaited()


@pytest.mark.parametrize(("g1", "g5"), [(True, False), (False, True), (False, False)])
def test_http_g5_followup_history_respects_disabled_flags(g1, g5, routed_chat, monkeypatch):
    ask, service, _, consult = routed_chat
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", g1)
    monkeypatch.setattr(get_settings(), "g5_enabled", g5)
    response = ask(
        "그럼 모든 경우에 적용해요?",
        recentMessages=[
            {"id": "topic", "role": "user", "text": "홍조를 화장으로 가리는 방법은요?"},
            {"id": "condition", "role": "user", "text": "그 방법을 건조할 때도 써요?"},
        ],
    )
    assert response.status_code == 200
    assert service.last_route.result.tool == "graph_chat"
    consult.assert_not_awaited()


def test_http_g5_history_does_not_take_over_shopping_session(routed_chat):
    ask, service, llm, consult = routed_chat
    service._sessions = ChatSessionRepository(RedisDouble())
    history = [{"id": "g5", "role": "user", "text": "볼 홍조를 화장으로 가리는 방법은요?"}]
    llm.plan = {"intent": "search", "category": "lip", "maxPriceKRW": 20000}
    first = ask("2만원 이하 립 추천해줘.", recentMessages=history)
    assert first.status_code == 200 and first.json()["products"]
    assert service.last_route.result.tool == "beauty"
    context = first.json()["chatContext"]
    second_id = context["candidateIds"][1]
    llm.plan = {"intent": "price", "scope": "previous", "ordinal": 2}
    second = ask("그중 두 번째 제품 가격은요?", chatContext=context, recentMessages=history)
    assert second.status_code == 200
    assert second.json()["products"][0]["id"] == second_id
    assert second.json()["chatContext"]["filters"]["maxPriceKRW"] == 20000
    assert service.last_route.result.tool == "beauty"
    llm.plan = {
        "intent": "detail",
        "scope": "previous",
        "ingredientLookup": True,
        "ingredientName": "향료",
    }
    third = ask(
        "그 제품에 향료가 들어 있어요?",
        chatContext=second.json()["chatContext"],
        recentMessages=history,
    )
    assert third.status_code == 200
    assert third.json()["products"][0]["id"] == second_id
    assert third.json()["ingredientResults"][0]["productId"] == second_id
    assert service.last_route.result.tool == "beauty"
    consult.assert_not_awaited()


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
    consult.assert_not_awaited()


def test_http_app_general_makeup_hint_uses_general_chat(routed_chat):
    ask, service, llm, consult = routed_chat
    service._sessions = ChatSessionRepository(RedisDouble())
    message = "파우더를 얇게 펴 바르는 방법이 궁금해요."
    response = ask(message, requestType="beauty_consultation", generalMakeup=True)
    assert response.status_code == 200
    assert response.json().get("knowledge") is None
    assert service.last_route.result.tool == "graph_chat"
    consult.assert_not_awaited()
    assert llm.calls >= 1


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
@pytest.mark.parametrize("request_type", ["chat", "knowledge_consultation"])
def test_http_keeps_existing_other_locale_route(routed_chat, locale, message, request_type):
    ask, service, _, consult = routed_chat
    response = ask(message, locale=locale, requestType=request_type)
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


@pytest.mark.parametrize("request_type", ["beauty_consultation", "knowledge_consultation"])
def test_http_active_shopping_session_keeps_general_makeup_context(request_type, routed_chat):
    ask, service, llm, consult = routed_chat
    service._sessions = ChatSessionRepository(RedisDouble())
    llm.plan = {"intent": "search", "category": "lip", "maxPriceKRW": 20000}
    first = ask("2만원 이하 립 추천해줘.", requestType="beauty_consultation")
    assert first.status_code == 200
    previous = first.json()["chatContext"]
    followup = ask(
        "파우더를 맨 마지막에 바르는 방법은요?",
        requestType=request_type,
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


@pytest.mark.parametrize(
    ("message", "fields", "plan"),
    [
        ("이 제품 가격은 얼마예요?", {}, {"intent": "general"}),
        ("2만원 이하 립 추천해줘.", {}, {"intent": "search", "category": "lip"}),
        (
            "이 립의 전성분에서 향료를 확인해 주세요.",
            {"screenContext": {"screenId": "product-detail", "productId": "a", "shadeId": "a-03"}},
            {
                "intent": "detail",
                "scope": "previous",
                "ingredientLookup": True,
                "ingredientName": "향료",
            },
        ),
        (
            "이 제품 호수는 어떤 게 있어요?",
            {"screenContext": {"screenId": "product-detail", "productId": "a"}},
            {"intent": "detail", "scope": "previous"},
        ),
        ("이 룩의 베이스는 어떻게 바르나요?", {}, {"intent": "general"}),
        ("립 추천하고 그걸 AR에 발라줘.", {}, {"intent": "general"}),
    ],
    ids=["price", "shopping", "ingredients", "options", "style", "ar-compound"],
)
def test_http_explicit_knowledge_keeps_existing_tool_responsibilities(
    message, fields, plan, routed_chat
):
    ask, service, llm, consult = routed_chat
    llm.plan = plan
    ordinary = ask(message, **fields)
    assert ordinary.status_code == 200
    expected_tool = service.last_route.result.tool
    expected_status = service.last_route.result.status
    assert expected_tool != "knowledge"

    explicit = ask(message, requestType="knowledge_consultation", **fields)
    assert explicit.status_code == 200
    assert service.last_route.result.tool == expected_tool
    assert service.last_route.result.status == expected_status
    assert explicit.json().get("knowledge") is None
    consult.assert_not_awaited()


@pytest.mark.parametrize(("g1", "g5"), [(True, True), (True, False), (False, True), (False, False)])
@pytest.mark.parametrize("history_key", ["recentMessages", "recent_messages"])
def test_http_explicit_knowledge_history_contract(g1, g5, history_key, routed_chat, monkeypatch):
    ask, service, _, consult = routed_chat
    monkeypatch.setattr(get_settings(), "g1_supervisor_enabled", g1)
    monkeypatch.setattr(get_settings(), "g5_enabled", g5)
    topic = "볼 홍조를 화장으로 가리는 방법은요?"
    question = "그럼 그 방법을 건조할 때도 써요?"
    history = [{"id": "topic", "role": "user", "text": topic}]
    response = ask(
        question,
        requestType="knowledge_consultation",
        clarificationId="ignored-g2-only-field",
        **{history_key: history},
    )
    assert response.status_code == 200
    assert service.request.clarification_id is None
    if g1 and g5:
        assert len(service.request.recent_messages) == 1
        consult.assert_awaited_once_with(question, prior_user_context=topic)
    else:
        assert not service.request.recent_messages
        assert service.last_route.result.tool == "graph_chat"
        consult.assert_not_awaited()


@pytest.mark.parametrize(
    "history",
    [
        [{"id": str(i), "role": "user", "text": "과거 질문"} for i in range(9)],
        [{"id": "duplicate", "role": "user", "text": "과거 질문"}] * 2,
        [{"id": str(i), "role": "assistant", "text": "가" * 1001} for i in range(8)],
    ],
    ids=["count", "duplicate-id", "total-length"],
)
def test_http_explicit_knowledge_rejects_invalid_history(history, routed_chat):
    ask, _, _, consult = routed_chat
    response = ask(
        "파우더를 바르는 순서를 알려주세요.",
        requestType="knowledge_consultation",
        recentMessages=history,
    )
    assert (response.status_code, response.json()["code"]) == (400, "invalid_request")
    consult.assert_not_awaited()


def test_http_explicit_knowledge_keeps_history_limits_and_ignores_ar_fields(routed_chat):
    ask, service, _, consult = routed_chat
    question = "파우더는 어느 순서로 발라요?"
    response = ask(
        question,
        requestType="knowledge_consultation",
        recentMessages=[{"id": str(i), "role": "assistant", "text": "가" * 1000} for i in range(8)],
        arContext={"untrusted": "not an AR command"},
    )
    assert response.status_code == 200
    assert len(service.request.recent_messages) == 8
    assert service.request.ar_context is None
    assert "arResult" not in response.json()
    consult.assert_awaited_once_with(question)


@pytest.mark.parametrize(
    ("field", "status", "code"),
    [
        ("sessionToken", 403, "chat_session_forbidden"),
        ("stateVersion", 409, "chat_session_conflict"),
    ],
)
def test_http_explicit_knowledge_cannot_bypass_session_validation(field, status, code, routed_chat):
    ask, service, llm, consult = routed_chat
    service._sessions = ChatSessionRepository(RedisDouble())
    llm.plan = {"intent": "search", "category": "lip", "maxPriceKRW": 20000}
    first = ask("2만원 이하 립 추천해줘.")
    assert first.status_code == 200
    context = first.json()["chatContext"]
    context["session"][field] = (
        "x" * 32 if field == "sessionToken" else context["session"][field] + 1
    )
    calls = llm.calls
    for request_type in ("chat", "knowledge_consultation"):
        response = ask(
            "그중 두 번째 제품 가격은요?",
            requestType=request_type,
            chatContext=context,
        )
        assert (response.status_code, response.json()["code"]) == (status, code)
    assert llm.calls == calls
    consult.assert_not_awaited()


@pytest.mark.parametrize("request_type", ["chat", "beauty_consultation", "knowledge_consultation"])
@pytest.mark.parametrize(
    "message",
    [
        "롬앤 틴트가 얼마예요?",
        "마스카라는 얼마인가요?",
        "이 파운데이션 얼마에 팔아요?",
        "블러셔 얼마야?",
    ],
)
def test_http_price_without_selection_keeps_catalog_route(message, request_type, routed_chat):
    ask, service, llm, consult = routed_chat
    service._sessions = ChatSessionRepository(RedisDouble())
    llm.plan = {"intent": "search", "category": "lip", "query": message}
    response = ask(message, requestType=request_type)
    assert response.status_code == 200
    assert service.last_route.result.tool == "beauty"
    assert response.json().get("knowledge") is None
    consult.assert_not_awaited()


@pytest.mark.parametrize("request_type", ["chat", "beauty_consultation", "knowledge_consultation"])
@pytest.mark.parametrize(
    "message",
    [
        "블러셔는 얼마나 자주 발라요?",
        "파운데이션은 얼마큼 짜서 써요?",
        "선크림을 바른 뒤 얼마 동안 기다려요?",
        "얼마 뒤 파우더를 바르나요?",
    ],
)
def test_http_quantity_and_frequency_are_not_price_questions(message, request_type, routed_chat):
    ask, service, _, consult = routed_chat
    response = ask(
        message,
        requestType=request_type,
        **({"generalMakeup": True} if request_type == "beauty_consultation" else {}),
    )
    assert response.status_code == 200
    if request_type == "knowledge_consultation":
        assert service.last_route.result.tool == "knowledge"
        consult.assert_awaited_once_with(message)
    else:
        assert service.last_route.result.tool == "graph_chat"
        consult.assert_not_awaited()


@pytest.mark.parametrize("adequate", [True, False])
@pytest.mark.parametrize("supported", [True, False])
def test_answered_requires_both_supported_coverage_and_adequate_context(adequate, supported):
    evidence, _, _ = verify_selection([SELECTED], {"C1": HIT})
    draft = {
        "status": "answered",
        "claims": [{"claim": QUOTE, "citations": ["E1"]}],
        "limitations": "",
    }
    audit = verification(
        check(
            1,
            requirements=["R1"],
            citations=["E1"],
            label="SUPPORTED" if supported else "UNSUPPORTED",
        )
    )
    audit["adequate_context"] = adequate
    result = resolve(draft, audit, evidence)
    expected = (
        "answered"
        if supported and adequate
        else "partial"
        if supported
        else "insufficient_evidence"
    )
    assert result.status == expected
    assert result.evidence == (evidence if supported else [])
    assert bool(result.claims) == supported
    if supported and not adequate:
        assert "전체 질문에 답하기 어렵습니다" in result.limitations
        assert f"{QUOTE} [E1]" in Consultation(result, {}).answer
        assert "항목은 입니다" not in result.limitations


def test_http_inadequate_context_preserves_supported_answer_as_partial(routed_chat, monkeypatch):
    ask, service, _, _ = routed_chat

    class InadequateModel(Model):
        async def run(self, stage, *args):
            result = await super().run(stage, *args)
            if stage == "detect":
                result.content["adequate_context"] = False
            return result

    consultation = KnowledgeService(Retrieval(), InadequateModel())
    monkeypatch.setattr(chat_service, "consult_knowledge", consultation.consult)
    response = ask("볼 홍조를 화장으로 가리는 방법은요?", requestType="knowledge_consultation")
    assert response.status_code == 200
    reply = response.json()["knowledge"]
    assert reply["status"] == "partial"
    assert reply["claims"][0]["citations"] == ["E1"]
    assert reply["evidence"][0]["quote"] == QUOTE
    assert service.last_route.result.status == "partial"


@pytest.mark.parametrize("stage_seconds", [15, 21])
def test_consultation_deadline_is_shared_across_successful_model_stages(stage_seconds):
    stages = []

    async def run():
        loop = asyncio.get_running_loop()
        real_time = loop.time
        elapsed = 0

        class TimedModel(Model):
            async def run(self, stage, *args):
                nonlocal elapsed
                stages.append(stage)
                elapsed += stage_seconds
                await asyncio.sleep(0.001)
                return await super().run(stage, *args)

        with patch.object(loop, "time", lambda: real_time() + elapsed):
            return await KnowledgeService(Retrieval(), TimedModel()).consult("볼에 사용하나요?")

    result = asyncio.run(run())
    assert stages == ["select", "answer", "detect"]
    if stage_seconds == 15:
        assert result.reply.status == "answered" and result.reply.evidence
    else:
        assert result.reply.status == "error"
        assert result.trace["error"] == "TimeoutError"
        assert not result.reply.claims and not result.reply.evidence


def test_consultation_deadline_includes_model_retry_wait():
    requests = []

    async def run():
        loop = asyncio.get_running_loop()
        real_time = loop.time
        elapsed = 0

        async def fail(request):
            nonlocal elapsed
            requests.append(request)
            elapsed = 56
            return httpx.Response(500)

        async with httpx.AsyncClient(
            base_url="https://example.test/", transport=httpx.MockTransport(fail)
        ) as http:
            with patch.object(loop, "time", lambda: real_time() + elapsed):
                return await KnowledgeService(Retrieval(), OpenAIResponses(http)).consult(
                    "볼에 쓰나요?"
                )

    result = asyncio.run(run())
    assert len(requests) == 1
    assert result.reply.status == "error" and result.trace["error"] == "TimeoutError"
    assert not result.reply.claims and not result.reply.evidence


def test_http_search_deadline_returns_g5_error_and_stops_later_stages(routed_chat, monkeypatch):
    ask, service, _, _ = routed_chat
    cancelled = []

    class SlowRetrieval(Retrieval):
        async def search(self, *args):
            try:
                await asyncio.sleep(0.2)
            except asyncio.CancelledError:
                cancelled.append(True)
                raise
            return await super().search(*args)

    model = Model()
    model.run = AsyncMock(wraps=model.run)
    consultation = KnowledgeService(SlowRetrieval(), model)
    monkeypatch.setattr(knowledge_service, "CONSULTATION_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(chat_service, "consult_knowledge", consultation.consult)
    response = ask("볼 홍조를 화장으로 가리는 방법은요?", requestType="knowledge_consultation")
    assert response.status_code == 200
    assert response.json()["knowledge"]["status"] == "error"
    assert response.json()["knowledge"]["claims"] == []
    assert response.json()["knowledge"]["evidence"] == []
    assert service.last_route.result.status == "error"
    assert cancelled == [True]
    model.run.assert_not_awaited()


@pytest.mark.parametrize("source_bound", [False, True])
def test_delegated_limits_follow_verified_requirements_and_keep_sourced_bounds(source_bound):
    from app.schemas.consultation_answer import KnowledgeCoverage

    evidence, _, _ = verify_selection([SELECTED], {"C1": HIT})
    draft = {
        "claims": [{"claim": "볼에 한정됩니다.", "citations": ["E1"]}],
        "limitations": "제공된 원문은 볼 사용에 한정됩니다."
        if source_bound
        else "제공된 근거에서는 판매 정보를 확인할 수 없습니다.",
        "limitation_citations": ["E1"] if source_bound else [],
    }
    audit = verification(check(1, requirements=["R1"], citations=["E1"]))
    reply = resolve(draft, audit, evidence, coverage=KnowledgeCoverage(scope="explanation"))
    assert reply.status == "answered" and len(reply.claims) == 1
    assert bool(reply.limitations) == source_bound
    if source_bound:
        assert "볼 사용에 한정" in reply.limitations and reply.evidence
    # Unmet actual explanation requirements are regenerated, not silently removed.
    audit = verification(
        check(1, requirements=["R1"], citations=["E1"]), required=["사용 범위", "바르는 순서"]
    )
    partial = resolve(draft, audit, evidence, coverage=KnowledgeCoverage(scope="explanation"))
    assert partial.status == "partial"
    assert (
        "볼 사용에 한정" in partial.limitations
        if source_bound
        else "바르는 순서" in partial.limitations
    )
