"""Run: python -B -m tests.run_product_eval (stdout only, controlled plans, no model eval)."""


def main():
    import hashlib
    import importlib.util
    import json
    import os
    import sys
    from collections import Counter
    from pathlib import Path
    from unittest.mock import patch

    os.environ["LLM_API_KEY"] = ""
    os.environ["LLM_MODEL"] = ""
    os.environ["ENV"] = "local"
    root = Path(__file__).resolve().parents[3]
    p = root / "docs/ai-alignment"

    def readjl(path):
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]

    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    watched = [x for x in p.rglob("*") if x.is_file()]
    before = {str(x): sha(x) for x in watched}
    cases = readjl(p / "03_future_full_eval/cases_v1.3.jsonl")
    by = {x["id"]: x for x in cases}
    reviews = readjl(p / "02_latest_review/VISHUE_review_cumulative_359_20261030.jsonl")
    reviewby = {x["case_id"]: x for x in reviews}
    inputs = readjl(p / "01_run_1A/resolved_inputs_359_fixture_patch.jsonl")
    world = json.loads((p / "01_run_1A/fixtures_world_patched.json").read_text(encoding="utf-8"))
    spec = importlib.util.spec_from_file_location(
        "existing_eval", p / "03_future_full_eval/run_evals_v1.3.py"
    )
    grader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(grader)
    approved = grader.approved_records(
        p / "02_latest_review/VISHUE_review_cumulative_359_20261030.jsonl", cases
    )
    audit = grader.audit_fixtures(cases, inputs, world)
    import httpx
    from fastapi.testclient import TestClient

    from app.clients.catalog_client import CatalogClient
    from app.clients.llm_client import LlmClient
    from app.core.ratelimit import MemoryRateLimiter, get_rate_limiter
    from app.main import create_app
    from app.schemas.catalog import CatalogProduct
    from app.schemas.chat import ChatRequest
    from app.services.chat_service import ChatService, get_chat_service
    from tests.product_eval_adapter import normalize_response, summarize_observations
    from tests.test_beauty_consultation import PlanLlm

    # Structural read projection only. No colors, descriptions, brands or ingredients invented.
    projection = []
    for original in world["products"]:
        row = dict(original)
        row.update(
            brand="",
            nameKo=original["name"],
            texture=original.get("finish"),
            description="",
            tags=[],
            shades=[],
        )
        row["category"] = {"blush": "cheek", "foundation": "base"}.get(
            row["category"], row["category"]
        )
        projection.append(row)
    plans = {
        "E-PR-01": dict(intent="detail", scope="previous"),
        "E-PR-02": dict(intent="detail", scope="previous"),
        "E-PR-03": dict(intent="detail", scope="previous", ordinal=2),
        "E-PR-04": dict(
            intent="search",
            scope="catalog",
            category="lip",
            maxPriceKRW=20000,
            moisturizing=True,
            fragranceFree=True,
        ),
        "E-PR-05": dict(intent="detail", scope="previous"),
        "E-PR-06": dict(intent="detail", scope="previous"),
        "E-PR-07": dict(
            intent="search", scope="catalog", category="lip", query="롬앤 쥬시 래스팅 틴트"
        ),
        "E-PR-08": dict(intent="detail", scope="previous"),
        "E-PR-09": dict(intent="detail", scope="previous", ordinal=2),
        "E-PR-10": dict(intent="price", scope="previous"),
    }
    network = []
    paid_calls = []

    def respond(req):
        assert req.url.host == "fixture.local", "UNEXPECTED NETWORK: " + str(req.url)
        network.append(str(req.url))
        path = req.url.path
        if path == "/api/products":
            # Deliberately do not hide missing client-side filters.
            return httpx.Response(200, json={"products": projection})
        if path.startswith("/api/products/"):
            pid = path.rsplit("/", 1)[-1]
            product = next((x for x in projection if x["id"] == pid), None)
            return (
                httpx.Response(200, json={"product": product})
                if product
                else httpx.Response(404, json={"error": "fixture missing", "code": "not_found"})
            )
        raise AssertionError("Unexpected endpoint")

    original_async = httpx.AsyncClient

    def fixture_client(**kw):
        return original_async(transport=httpx.MockTransport(respond), **kw)

    async def forbid_paid(*args, **kw):
        paid_calls.append(1)
        raise AssertionError("Real LLM must never run")

    import logging

    logging.disable(logging.CRITICAL)
    app = create_app()
    logging.disable(logging.CRITICAL)
    app.dependency_overrides[get_rate_limiter] = lambda: MemoryRateLimiter(limit=100)
    rows = []

    def dependency_for(service):
        return lambda: service

    with (
        patch("httpx.AsyncClient", fixture_client),
        patch.object(LlmClient, "complete", forbid_paid),
        patch("app.services.beauty_consultation_service.time.time", return_value=1000000),
        TestClient(app) as client,
    ):
        for x in inputs:
            cid = x["case_id"]
            if cid not in plans:
                continue
            inp = x["test_input"]
            ctx = inp["context"]
            case = by[cid]
            result = {}
            for mode in ("legacy_context_probe", "mapped_chat_context"):
                llm = PlanLlm(**plans[cid])
                service = ChatService(None, llm, CatalogClient("http://fixture.local"))

                app.dependency_overrides[get_chat_service] = dependency_for(service)
                body = {
                    "message": inp["user_utterances"][0],
                    "locale": inp["locale"],
                    "requestType": "beauty_consultation",
                }
                if mode == "legacy_context_probe":
                    body.update(screenId=inp["screen_id"], context=ctx)
                else:
                    rs = world["resultSets"].get(ctx.get("resultSetId"))
                    if rs:
                        body["chatContext"] = {
                            "version": 1,
                            "issuedAt": 1000000 - (601 if rs["status"] == "expired" else 0),
                            "filters": {},
                            "candidateIds": rs["orderedProductIds"],
                            "scopeIds": rs["orderedProductIds"],
                            "selectedProductId": ctx.get("selectedProductId"),
                        }
                start = len(network)
                parsed = ChatRequest.model_validate(body)
                r = client.post(
                    "/api/chat",
                    json=body,
                    headers={"X-Vishue-Anonymous-Id": "fixture-eval-session-0123456789-abcdefgh"},
                )
                assert r.status_code == 200, (cid, mode, r.status_code, r.text)
                response = r.json()
                result[mode] = {
                    "actualRequest": body,
                    "parsedChatContextPresent": parsed.chat_context is not None,
                    "response": response,
                    "mockInterpretation": plans[cid],
                    "mockCalls": llm.calls,
                    "catalogRequests": network[start:],
                }
            response = result["mapped_chat_context"]["response"]
            normalized = normalize_response(response)
            pred = normalized["prediction"]
            context = response.get("chatContext") or {}
            evidence = response.get("evidence") or []
            entry = {"case_id": cid, "prediction": pred}
            graded = grader.grade_case(case, entry, approved)
            required_missing = [
                key
                for key in ("intent_id", "applied", "checkoutExecuted", "commands")
                if key not in pred
            ]
            answer = response["answer"]
            product_ids = [q["id"] for q in response["products"]]
            observations = {
                "allReturnedIdsExistInOriginalFixture": set(product_ids)
                <= {q["id"] for q in world["products"]},
                "realLlmCalled": False,
                "independentAppOrArObservation": "NOT_OBSERVABLE",
            }
            if cid == "E-PR-01":
                observations.update(
                    parfumMentioned="Parfum" in answer,
                    onlyPBReturned=product_ids == ["P-B"],
                    fullIngredientsDroppedByCurrentSchema=not any(
                        name in ("full_ingredients", "fullIngredients")
                        or field.alias == "fullIngredients"
                        for name, field in CatalogProduct.model_fields.items()
                    ),
                )
            elif cid == "E-PR-02":
                observations.update(
                    fullListUnknownExplained="전성분" in answer and "미확인" in answer,
                    fragranceUnknown=all(e["fragranceStatus"] == "unknown" for e in evidence),
                )
            elif cid == "E-PR-03":
                observations.update(
                    expiryExplained="유효 시간" in answer,
                    clarifies=response["resultType"] == "clarification",
                    noProduct=not product_ids,
                )
            elif cid == "E-PR-04":
                observations.update(
                    empty=response["resultType"] == "empty",
                    filters=context.get("filters"),
                    unknownFragranceExplained="미확인" in answer,
                )
            elif cid == "E-PR-05":
                observations.update(
                    keyK1Explained="가상 성분 K1" in answer,
                    fullListNotClaimed=all(e["ingredientCoverage"] == "key_only" for e in evidence),
                )
            elif cid == "E-PR-06":
                observations.update(
                    clarifies=response["resultType"] == "clarification",
                    catalogRequestCount=len(result["mapped_chat_context"]["catalogRequests"]),
                )
            elif cid == "E-PR-07":
                observations.update(
                    originalCatalogBrandAbsent=ctx["catalogContainsBrand"] is False,
                    empty=not product_ids,
                )
            elif cid == "E-PR-08":
                observations.update(
                    shadeSimilarityOperationPresent=False,
                    colorEvidence=ctx.get("colorLab"),
                    branchProbeOnly=True,
                )
            elif cid == "E-PR-09":
                observations.update(
                    actualSelected=context.get("selectedProductId"),
                    originalR1Order=world["resultSets"]["R1"]["orderedProductIds"],
                    orderPreserved=context.get("candidateIds")
                    == world["resultSets"]["R1"]["orderedProductIds"],
                )
            elif cid == "E-PR-10":
                observations.update(
                    fixtureLivePrice=ctx["verifiedLivePrice"],
                    fixtureReferencePrice=next(
                        p["priceKRW"]
                        for p in world["products"]
                        if p["id"] == ctx["selectedProductId"]
                    ),
                    referencePriceExplicitInAnswer="19,000" in answer or "19000" in answer,
                    explicitLivePriceUnavailable="오늘의 실제 판매가·판매처·확인 시각은 미확인"
                    in answer,
                    ingredientTemplateUsed="주요 성분:" in answer,
                )

            checks_by_case = {
                "E-PR-01": {
                    "selectedPB": product_ids == ["P-B"],
                    "verifiedParfumExplained": "Parfum" in answer,
                },
                "E-PR-02": {"unknownFullListExplained": "전성분" in answer and "미확인" in answer},
                "E-PR-03": {
                    "expiredClarification": response["resultType"] == "clarification"
                    and "유효 시간" in answer
                },
                "E-PR-04": {
                    "noUnverifiedCandidates": not product_ids
                    and context.get("filters", {}).get("fragranceFree") is True
                },
                "E-PR-05": {"keyIngredientsOnly": "가상 성분 K1" in answer and "전성분" in answer},
                "E-PR-06": {
                    "clarifiesWithoutSelection": response["resultType"] == "clarification"
                    and not product_ids
                },
                "E-PR-07": {"originalZeroResults": not product_ids},
                "E-PR-08": {},
                "E-PR-09": {
                    "ordinalFromFixtureOrder": product_ids
                    == [world["resultSets"]["R1"]["orderedProductIds"][1]]
                },
                "E-PR-10": {
                    "referencePriceDisclosed": "19,000" in answer,
                    "livePriceUnknown": "오늘의 실제 판매가·판매처·확인 시각은 미확인" in answer,
                    "syntheticClearlyLabeled": "합성 가격" in answer,
                },
            }
            assessment = summarize_observations(
                normalized,
                checks_by_case[cid],
                policy_hold=cid in ("E-PR-04", "E-PR-06", "E-PR-08"),
                catalog_mode="FIXED_SYNTHETIC_FIXTURE",
            )
            rows.append(
                {
                    "id": cid,
                    "reviewStatus": reviewby[cid]["review_status"],
                    "originalInput": inp,
                    "expected": case["expected"],
                    "forbidden": case["forbid"],
                    "runs": result,
                    "assessment": assessment,
                    "adapter": normalized,
                    "normalizedObservedOnly": pred,
                    "notObservable": required_missing
                    + ["resultSetId", "screenContext", "actual app/AR state"],
                    "existingGraderVerdict": graded["verdict"],
                    "schemaErrors": graded["schema_errors"],
                    "observations": observations,
                }
            )
    assert not paid_calls
    assert all(sha(Path(path)) == h for path, h in before.items()), (
        "Original evaluation material changed"
    )
    out = {
        "executionEnvironment": {
            "python": sys.version.split()[0],
            "catalogMode": "FIXED_SYNTHETIC_FIXTURE_HTTP_MOCK",
            "catalogVersion": world["meta"],
            "clock": 1000000,
            "paidCalls": len(paid_calls),
            "reportFilesWritten": 0,
            "originalEvalFilesHashUnchanged": True,
            "fixtureAudit": audit,
            "approvedGoldRecords": len(approved),
            "reviewStatuses": dict(Counter(r["review_status"] for r in reviews)),
        },
        "sourceHashes": {
            str(path.relative_to(root)): before[str(path)]
            for path in (
                p / "03_future_full_eval/cases_v1.3.jsonl",
                p / "02_latest_review/VISHUE_review_cumulative_359_20261030.jsonl",
                p / "01_run_1A/fixtures_world_patched.json",
                p / "01_run_1A/resolved_inputs_359_fixture_patch.jsonl",
                p / "03_future_full_eval/run_evals_v1.3.py",
            )
        },
        "catalogProjectionOmissions": [
            "brand absent: empty structural string",
            "nameKo mirrors original Korean name",
            "description/tags absent: empty structural fields",
            "shade IDs lack required name/hex: shades not supplied to projection",
            "fullIngredients supplied upstream but ignored by current CatalogProduct schema",
        ],
        "rows": rows,
    }
    print(json.dumps(out, ensure_ascii=True))


if __name__ == "__main__":
    main()
