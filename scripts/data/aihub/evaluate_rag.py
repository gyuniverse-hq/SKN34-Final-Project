"""Run the three G5 strategies without giving the models the evaluation rubric."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend" / "chatbot"))

from app.services.knowledge_service import consult_knowledge  # noqa: E402


async def evaluate(questions, strategies, concurrency):
    gate = asyncio.Semaphore(concurrency)
    criteria = {
        "not_applicable": 0, "answerable": 0, "answered": 0, "adequate_context": 0,
        "contexts": 0, "negative_correct": 0, "negative": 0, "errors": 0,
        "claims": 0, "flags": 0, "tokens_in": 0, "tokens_out": 0, "cached_tokens": 0,
        "calls": 0, "usd": 0,
    }
    totals = {name: dict(criteria) for name in strategies}
    calls = []

    async def one(qid, item, strategy):
        async with gate:
            return qid, item, strategy, await consult_knowledge(item["question"], strategy)

    for strategy in strategies:
        calls.extend(one(q, item, strategy) for q, item in questions.items())
    latency = {name: [] for name in strategies}
    for waiting in asyncio.as_completed(calls):
        qid, item, strategy, output = await waiting
        reply, trace = output.reply, output.trace
        known = item.get("has_reference", item.get("answerable"))
        cell = totals[strategy]
        if known is True:
            cell["answerable"] += 1
            cell["answered"] += reply.status == "answered"
            cell["adequate_context"] += bool(trace.get("detect", {}).get("adequateContext"))
        elif known is False:
            cell["negative"] += 1
            cell["negative_correct"] += reply.status == "insufficient_evidence"
        else:
            cell["not_applicable"] += 1
        cell["contexts"] += bool(trace.get("contextTokens"))
        cell["errors"] += reply.status == "error"
        cell["claims"] += len(reply.claims)
        cell["flags"] += len(reply.findings)
        latency[strategy].append(trace.get("totalMs", 0))
        search = trace.get("search", {})
        embedding = search.get("embeddingInputTokens", 0)
        cell["tokens_in"] += embedding
        cell["calls"] += bool(embedding)
        cell["usd"] += embedding * .13 / 1e6
        for name in ("select", "answer", "detect"):
            stage = trace.get(name)
            if stage:
                cell["tokens_in"] += stage["inputTokens"]
                cell["tokens_out"] += stage["outputTokens"]
                cell["cached_tokens"] += stage["cachedTokens"]
                cell["calls"] += stage["attempts"]
                cell["usd"] += stage["estimatedUsd"]
        print(json.dumps({
            "case": qid, "strategy": strategy, "reply": reply.model_dump(mode="json"),
            "trace": trace, "answerable": known,
        }, ensure_ascii=False), flush=True)
    from statistics import median

    for strategy in strategies:
        totals[strategy]["median_ms"] = median(latency[strategy])
    print(json.dumps({"summary": totals}, ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question_json", type=Path, help="Object keyed by question ID")
    parser.add_argument("--strategies", nargs="+", choices=("large", "section", "qa"),
                        default=("large", "section", "qa"))
    parser.add_argument("--concurrency", type=int, choices=range(1, 9), default=5)
    parser.add_argument("--ids", nargs="+")
    args = parser.parse_args()
    data = json.loads(args.question_json.read_text(encoding="utf-8"))
    cases = data.get("questions", data)
    if args.ids:
        cases = {k: cases[k] for k in args.ids}
    asyncio.run(evaluate(cases, args.strategies, args.concurrency))


if __name__ == "__main__":
    main()
