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
    op: Literal["eq", "contains", "empty", "lte", "same", "different", "increment", "nonempty"]
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
        if "error" in response or "code" in response:
            raise ValueError("Successful chat cannot contain error fields")
    else:
        if not isinstance(response.get("code"), str) or not isinstance(response.get("error"), str):
            raise ValueError("Error response requires error/code")
        if "answer" in response or "products" in response:
            raise ValueError("Error response cannot contain success fields")
    return data


def evaluate_assertion(spec, observation):
    actual = get_path(observation, spec.path)
    if actual is MISSING:
        return {"id": spec.id, "axis": spec.axis, "status": "NOT_OBSERVABLE"}
    other = (
        get_path(observation, spec.expected)
        if spec.op in {"same", "different", "increment"}
        else None
    )
    if other is MISSING:
        return {"id": spec.id, "axis": spec.axis, "status": "NOT_OBSERVABLE"}
    if spec.op in {"same", "different", "increment"} and (actual is None or other is None):
        return {"id": spec.id, "axis": spec.axis, "status": "NOT_OBSERVABLE"}
    if (
        spec.path.endswith(".resultSetId")
        and spec.op in {"same", "different"}
        and not all(isinstance(value, str) and value.strip() for value in (actual, other))
    ):
        return {"id": spec.id, "axis": spec.axis, "status": "FAIL", "critical": spec.critical}
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
    elif spec.op == "different":
        passed = not exact_equal(actual, other)
    elif spec.op == "nonempty":
        passed = isinstance(actual, str) and bool(actual.strip())
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
        not isinstance(r, dict)
        or not isinstance(r.get("productId"), str)
        or not isinstance(r.get("optionId"), str)
        or not isinstance(r.get("verdict"), str)
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
        ingredient_conditions = row.get("ingredientConditions")
        other_conditions = row.get("otherConditions", [])
        if "budget" not in row:
            raise ValueError("Option budget field is required")
        budget = row.get("budget")
        if not isinstance(ingredient_conditions, list) or not isinstance(other_conditions, list):
            raise ValueError("Option conditions must be arrays")
        if budget is not None and not isinstance(budget, dict):
            raise ValueError("Option budget must be an object or null")
        conditions = (
            ingredient_conditions + other_conditions + ([budget] if budget is not None else [])
        )
        if any(
            not isinstance(c, dict)
            or not isinstance(c.get("verdict"), str)
            or c["verdict"] not in {"MATCH", "NOT_MATCH", "UNKNOWN", "ERROR"}
            for c in conditions
        ):
            raise ValueError("Invalid option condition verdict")
        if any(
            c.get("condition") != "ingredient"
            or not isinstance(c.get("productId"), str)
            or "shadeId" not in c
            or "optionId" not in c
            or (c["shadeId"] is not None and not isinstance(c["shadeId"], str))
            or (c["optionId"] is not None and not isinstance(c["optionId"], str))
            or not isinstance(c.get("reason"), str)
            or not isinstance(c.get("ingredientName"), str)
            or not c["ingredientName"]
            or c.get("operator") not in {"includes", "excludes"}
            for c in ingredient_conditions
        ):
            raise ValueError("Invalid ingredient condition")
        if any(
            c.get("condition") not in {"fragrance_free", "product_query", "stock"}
            or not isinstance(c.get("reason"), str)
            for c in other_conditions
        ):
            raise ValueError("Invalid other condition")
        if budget is not None and (
            budget.get("priceBasis") not in {"current_sale", "collected_sale"}
            or type(budget.get("maxPriceKRW")) is not int
            or not isinstance(budget.get("reason"), str)
        ):
            raise ValueError("Invalid budget condition")
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
    if any(not isinstance(c, dict) or not isinstance(c.get("publicationId"), str) for c in claims):
        raise ValueError("Invalid claim citation")
    if any(not isinstance(link, dict) for link in links):
        raise ValueError("Invalid claim link")
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


def answer_invariants(obs, option_checks):
    """Check observable structure and citations, not the meaning of natural language."""
    from urllib.parse import urlsplit

    response = obs["response"]
    checks = []

    def add(name, status):
        checks.append({"id": name, "axis": "answer", "status": status, "critical": True})

    if obs["httpStatus"] != 200:
        valid = bool(response["error"].strip() and response["code"].strip())
        add("answer_error_structure", "PASS" if valid else "FAIL")
        return checks

    add("answer_nonempty", "PASS" if response["answer"].strip() else "FAIL")
    join = next((c for c in option_checks if c["id"] == "claim_join"), None)
    if join:
        add("answer_option_claim_links", join["status"])
    search = response.get("optionSearch")
    if isinstance(search, dict) and isinstance(search.get("evaluations"), list):
        for index, row in enumerate(search["evaluations"]):
            if not isinstance(row, dict) or not isinstance(row.get("ingredientConditions"), list):
                continue
            absent = any(
                isinstance(c, dict)
                and c.get("operator") == "excludes"
                and c.get("verdict") == "MATCH"
                for c in row["ingredientConditions"]
            )
            if absent:
                coverage, verification = (
                    row.get("ingredientCoverage"),
                    row.get("ingredientVerification"),
                )
                if coverage is None or verification is None:
                    add(f"answer_absence_coverage_{index}", "NOT_OBSERVABLE")
                else:
                    valid = coverage == "full" and verification == "verified"
                    add(f"answer_absence_coverage_{index}", "PASS" if valid else "FAIL")
    status = response.get("claimStatus", MISSING)
    claims = response.get("publishedClaims", MISSING)
    if status is MISSING and claims is MISSING:
        return checks
    if status is MISSING or claims is MISSING:
        add("answer_claim_status", "NOT_OBSERVABLE")
        return checks
    if status not in {"available", "not_found", "unavailable"} or not isinstance(claims, list):
        add("answer_claim_status", "FAIL")
        return checks
    consistent = bool(claims) == (status == "available")
    add("answer_claim_status", "PASS" if consistent else "FAIL")
    if not claims:
        return checks
    if any(not isinstance(c, dict) for c in claims):
        add("answer_citations", "FAIL")
        return checks
    if any("sourceUrl" not in c or "sourceTitle" not in c for c in claims):
        add("answer_citations", "NOT_OBSERVABLE")
        return checks
    for claim in claims:
        url, title = claim["sourceUrl"], claim["sourceTitle"]
        if not isinstance(url, str) or not isinstance(title, str) or not title.strip():
            add("answer_citations", "FAIL")
            return checks
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            add("answer_citations", "FAIL")
            return checks
        # Explanation responses explicitly print the citation; option cards need not.
        if "optionSearch" not in response and url not in response["answer"]:
            add("answer_citations", "FAIL")
            return checks
    add("answer_citations", "PASS")
    return checks
