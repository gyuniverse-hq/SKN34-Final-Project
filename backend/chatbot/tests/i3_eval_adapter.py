"""Independent I-3 observation contract; never fill observations from an oracle."""

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

AXES = ("interpretation", "retrieval", "ingredient", "option", "conversation", "answer")
Mode = Literal["synthetic_contract", "real_llm"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Gold(StrictModel):
    status: Literal["candidate"] = "candidate"
    reviewerIds: list[str] = Field(default_factory=list, max_length=0)
    approvedAt: None = None


class Assertion(StrictModel):
    id: str = Field(min_length=1)
    axis: Literal["interpretation", "retrieval", "ingredient", "option", "conversation", "answer"]
    path: str = Field(min_length=1)
    op: Literal["eq", "contains", "empty", "lte", "same", "increment"]
    expected: Any
    critical: bool = False


class Turn(StrictModel):
    turn: int = Field(ge=1)
    replayOfTurn: int | None = Field(default=None, ge=1)
    request: dict[str, Any]
    expectedIntent: dict[str, Any]
    requiredConditions: list[str] = Field(min_length=1)
    allowedResponses: list[str] = Field(min_length=1)
    forbiddenResponses: list[str] = Field(min_length=1)
    expectedState: str = Field(min_length=1)
    assertions: list[Assertion] = Field(min_length=1)
    humanCriteria: list[str] = Field(min_length=1)


class Case(StrictModel):
    recordType: Literal["case"] = "case"
    caseId: str = Field(pattern=r"^I3-(Q0[1-6]|E0[1-6]|I0[1-6]|O(0[1-9]|10)|M0[1-8])$")
    caseVersion: int = Field(ge=1)
    sourceCaseIds: list[str]
    questionProvenance: Literal["newly_authored"]
    contractRef: str
    gold: Gold
    fixtureRef: str
    fixtureHash: str = Field(pattern=r"^[a-f0-9]{64}$")
    realEvidenceRequiredForPositiveContent: bool
    variants: list[str]
    turns: list[Turn] = Field(min_length=1)

    @model_validator(mode="after")
    def check_turns(self):
        if [t.turn for t in self.turns] != list(range(1, len(self.turns) + 1)):
            raise ValueError("Turns must be contiguous")
        ids = [a.id for t in self.turns for a in t.assertions]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate assertion IDs")
        if any(t.replayOfTurn is not None and t.replayOfTurn >= t.turn for t in self.turns):
            raise ValueError("Replay must reference an earlier turn")
        return self


class Provenance(StrictModel):
    mode: Mode
    planner: Literal["fixture", "real_llm"]
    dataKind: Literal["synthetic", "actual_unpublished", "actual_published"]
    sutCommit: str = Field(pattern=r"^[a-f0-9]{40}$")
    model: str = Field(min_length=1)
    promptHash: str = Field(pattern=r"^[a-f0-9]{64}$")
    fixtureHash: str = Field(pattern=r"^[a-f0-9]{64}$")
    dataSnapshotHash: str = Field(pattern=r"^[a-f0-9]{64}$")
    dictionaryHash: str = Field(pattern=r"^[a-f0-9]{64}$")
    executionRef: str = Field(min_length=1)
    executedAt: str = Field(min_length=1)
    settings: dict[str, Any]

    @model_validator(mode="after")
    def separate_modes(self):
        if self.mode == "real_llm" and self.planner != "real_llm":
            raise ValueError("Fixture planner is not real LLM evaluation")
        if self.mode == "synthetic_contract" and (
            self.planner != "fixture" or self.dataKind != "synthetic"
        ):
            raise ValueError("Synthetic contract requires synthetic data and fixture planner")
        return self


class Observation(StrictModel):
    recordType: Literal["observation"] = "observation"
    runId: str = Field(min_length=1)
    caseId: str
    turn: int = Field(ge=1)
    repeat: int = Field(ge=1)
    provenance: Provenance
    request: dict[str, Any]
    httpStatus: int = Field(ge=100, le=599)
    response: dict[str, Any]
    trace: dict[str, Any] = Field(default_factory=dict)
    stateBefore: dict[str, Any] | None = None
    stateAfter: dict[str, Any] | None = None


RECORD = TypeAdapter(Case | Observation)
MISSING = object()


def get_path(value, path):
    for part in path.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and part.isdigit() and int(part) < len(value):
            value = value[int(part)]
        else:
            return MISSING
    return value


def exact_equal(left, right):
    """JSON equality without treating True as 1, including nested values."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(exact_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(
            exact_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    return left == right


def normalize_observation(raw):
    """Retain raw option/claim/state observations, without case expectations."""
    obs = Observation.model_validate(raw)
    data = deepcopy(obs.model_dump())
    response = data["response"]
    if obs.httpStatus == 200:
        if not isinstance(response.get("answer"), str) or not isinstance(
            response.get("products"), list
        ):
            raise ValueError("Successful chat requires answer and products")
        if any(
            not isinstance(p, dict) or not isinstance(p.get("id"), str)
            for p in response["products"]
        ):
            raise ValueError("Invalid product reference")
    elif not isinstance(response.get("code"), str) or not isinstance(response.get("error"), str):
        raise ValueError("Error response requires error/code")
    return data


def evaluate_assertion(spec, observation):
    actual = get_path(observation, spec.path)
    if actual is MISSING:
        return {"id": spec.id, "axis": spec.axis, "status": "NOT_OBSERVABLE"}
    other = get_path(observation, spec.expected) if spec.op in {"same", "increment"} else None
    if other is MISSING:
        return {"id": spec.id, "axis": spec.axis, "status": "NOT_OBSERVABLE"}
    if spec.op in {"same", "increment"} and (actual is None or other is None):
        return {"id": spec.id, "axis": spec.axis, "status": "NOT_OBSERVABLE"}
    if spec.op == "eq":
        passed = exact_equal(actual, spec.expected)
    elif spec.op == "contains":
        passed = isinstance(actual, list) and any(exact_equal(x, spec.expected) for x in actual)
    elif spec.op == "empty":
        passed = isinstance(actual, (list, dict, str)) and len(actual) == 0
    elif spec.op == "lte":
        passed = type(actual) in (int, float) and type(spec.expected) in (int, float)
        passed = passed and actual <= spec.expected
    elif spec.op == "same":
        passed = exact_equal(actual, other)
    else:
        passed = type(actual) is int and type(other) is int and actual == other + 1
    return {
        "id": spec.id,
        "axis": spec.axis,
        "status": "PASS" if passed else "FAIL",
        "critical": spec.critical,
    }


def option_invariants(response):
    """Inspect joins and eligible cards. Missing join evidence cannot pass."""
    if "optionSearch" not in response:
        return []
    search = response["optionSearch"]
    if not isinstance(search, dict) or not isinstance(search.get("evaluations"), list):
        return [{"id": "option_shape", "axis": "option", "status": "FAIL", "critical": True}]
    rows = search["evaluations"]
    if any(
        not isinstance(r, dict) or not all(k in r for k in ("productId", "optionId", "verdict"))
        for r in rows
    ):
        return [{"id": "option_rows", "axis": "option", "status": "FAIL", "critical": True}]
    pairs = {(r["productId"], r["optionId"]): r for r in rows}
    passed = len(pairs) == len(rows) and len(rows) <= 128
    passed = passed and search.get("evaluatedCount") == len(rows)
    passed = passed and type(search.get("exhaustive")) is bool
    passed = passed and type(search.get("pages")) is int and 0 <= search["pages"] <= 4
    if search.get("status") == "no_matches":
        passed = passed and search.get("exhaustive") is True
        passed = passed and all(r["verdict"] == "NOT_MATCH" for r in rows)
    cards = response["products"]
    passed = passed and response.get("resultType") in {
        "recommendations",
        "product_detail",
        "empty",
        "clarification",
    }
    passed = passed and len(cards) <= 6 and len({p["id"] for p in cards}) == len(cards)
    for card in cards:
        row = pairs.get((card["id"], card.get("optionId")))
        passed = passed and row is not None
        if row and response.get("resultType") == "recommendations":
            passed = passed and row["verdict"] == "MATCH"
    for row in rows:
        passed = passed and row["verdict"] in {"MATCH", "NOT_MATCH", "UNKNOWN", "ERROR"}
        conditions = row.get("ingredientConditions", []) + row.get("otherConditions", [])
        if row.get("budget") is not None:
            conditions = [row["budget"], *conditions]
        if any(c.get("verdict") == "NOT_MATCH" for c in conditions):
            passed = passed and row["verdict"] == "NOT_MATCH"
        if row["verdict"] == "MATCH":
            passed = passed and all(c.get("verdict") == "MATCH" for c in conditions)
    results = [
        {
            "id": "same_option_cards",
            "axis": "option",
            "status": "PASS" if passed else "FAIL",
            "critical": True,
        }
    ]
    links = response.get("optionClaimLinks", MISSING)
    claims = response.get("publishedClaims", MISSING)
    if links is MISSING or claims is MISSING:
        results.append({"id": "claim_join", "axis": "retrieval", "status": "NOT_OBSERVABLE"})
        return results
    if not isinstance(links, list) or not isinstance(claims, list):
        raise ValueError("Claim collections must be arrays")
    citations = {c["publicationId"] for c in claims}
    card_pairs = {(p["id"], p.get("optionId")) for p in cards}
    passed = len(citations) == len(claims)
    passed = passed and citations == {link.get("publicationId") for link in links}
    for link in links:
        pair = (link.get("productId"), link.get("optionId"))
        row = pairs.get(pair)
        passed = passed and bool(
            row
            and pair in card_pairs
            and link.get("publicationId") in citations
            and row.get("ingredientEvidenceId")
            and row.get("ingredientSourceVersion")
            and link.get("ingredientEvidenceId") == row.get("ingredientEvidenceId")
            and link.get("ingredientSourceVersion") == row.get("ingredientSourceVersion")
            and link.get("finishedProductEfficacy") == "unverified"
        )
    results.append(
        {
            "id": "claim_join",
            "axis": "retrieval",
            "status": "PASS" if passed else "FAIL",
            "critical": True,
        }
    )
    return results
