from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

KnowledgeStatus = Literal["answered", "partial", "insufficient_evidence", "error"]
ClaimLabel = Literal["SUPPORTED", "OVERGENERALIZED", "CONTRADICTED", "UNSUPPORTED"]
QuestionMatch = Literal["MATCHED", "PARTIAL_MATCH", "MISMATCHED", "IRRELEVANT", "UNCERTAIN"]
Applicability = Literal["APPLICABLE", "CONDITIONAL", "NOT_APPLICABLE", "UNCERTAIN"]
ScopeBasis = Literal[
    "DIRECT",
    "SUPPORTED_TRANSFER",
    "BOUNDED",
    "SIMILAR_ONLY",
    "UNVERIFIED",
    "CONFLICT",
]
ConditionLink = Literal["NONE", "SAME_CONTEXT", "DIFFERENT_CONTEXT", "UNVERIFIED"]


class KnowledgeModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class KnowledgeSpan(KnowledgeModel):
    block_order: int
    start_utf16: int
    end_utf16: int
    source_locator: dict


class KnowledgeSegment(KnowledgeModel):
    span: KnowledgeSpan
    text: str


class Candidate(KnowledgeModel):
    chunk_id: str
    document_id: int
    extraction_id: int
    source_version: str
    source_file_id: int
    title: str
    score: float
    channels: list[str]
    segments: list[KnowledgeSegment]


class SearchResult(KnowledgeModel):
    candidates: list[Candidate]
    embedding_input_tokens: int
    embedding_ms: int
    lookup_ms: int


class Location(KnowledgeModel):
    document_id: int
    extraction_id: int
    source_version: str
    block_order: int
    chunk_id: str
    start_utf16: int
    end_utf16: int


class OriginalBlock(KnowledgeModel):
    block_order: int
    kind: str
    text: str
    source_locator: dict


class NeighborResult(KnowledgeModel):
    source: Location
    blocks: list[OriginalBlock]


class KnowledgeEvidence(KnowledgeModel):
    id: str
    document_id: int
    chunk_id: str
    title: str
    source_file_id: int
    source_version: str
    block_order: int
    start_utf16: int
    end_utf16: int
    source_locator: dict
    quote: str
    relevance: Literal["essential", "support"]


class KnowledgeClaim(KnowledgeModel):
    claim: str
    citations: list[str]


class ClaimCheck(KnowledgeModel):
    index: int
    label: ClaimLabel
    reason: str


class VerificationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class QuestionRequirement(VerificationModel):
    id: str
    description: str
    required: bool


class ClaimReview(VerificationModel):
    index: int
    label: Literal["SUPPORTED", "OVERGENERALIZED", "CONTRADICTED", "UNSUPPORTED", "UNCERTAIN"]
    match: QuestionMatch
    requirement_ids: list[str]
    supporting_ids: list[str]
    condition_evidence_ids: list[str]
    condition_link: ConditionLink
    applicability: Applicability
    scope_basis: ScopeBasis
    condition_quote: str
    reason: str


class AnswerVerification(VerificationModel):
    requirements: list[QuestionRequirement]
    reviews: list[ClaimReview]
    adequate_context: bool
    limits_unsubstantiated: bool


class KnowledgeReply(KnowledgeModel):
    status: KnowledgeStatus
    claims: list[KnowledgeClaim] = Field(default_factory=list)
    evidence: list[KnowledgeEvidence] = Field(default_factory=list)
    findings: list[ClaimCheck] = Field(default_factory=list)
    limitations: str = ""
