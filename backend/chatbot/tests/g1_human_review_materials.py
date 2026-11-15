"""Prepare review context for real captured E3 runs without deciding any verdict."""

import argparse
import json
import sys
from pathlib import Path

# The collector and this script are also executed by file path on Windows.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.run_g1_evaluation import CONTRACT, read_jsonl, required_runs, verify_evidence  # noqa: E402


def make_materials(observations, evidence_root):
    cases = read_jsonl(CONTRACT / "g1_cases_PROPOSED.jsonl")
    result = [
        "# G1 E3 사람 검토 자료",
        "",
        "판정은 비어 있습니다. 실제 검토자가 기존 평가표에 직접 입력해야 합니다.",
        "제공 모델 ID가 별칭이면 고정 모델 버전의 증거가 아닙니다.",
        "",
    ]
    for key, _, human, required, case in required_runs(cases):
        if not human:
            continue
        matches = [
            o
            for o in observations
            if (o.get("caseId"), o.get("variantId", "default"), o.get("environment")) == key
            and o.get("caseRevision") == case["caseRevision"]
        ]
        obs = matches[0] if len(matches) == 1 else None
        valid = (
            bool(obs)
            and obs.get("isMock") is False
            and obs.get("isSynthetic") is False
            and verify_evidence(obs, key, required, evidence_root)
        )
        result.extend([f"## {key[0]}", "", "상태: NOT_RUN (사람 판정 미입력)", ""])
        result.extend(["### 질문", "", case["input"]["message"], ""])
        oracle = case["expected"].get("semanticOracle", {})
        result.extend(["### 필수 조건", ""])
        result.extend(f"- {item}" for item in oracle.get("essentialBehaviors", []))
        result.extend(["", "### 실제 응답", ""])
        if not valid:
            result.extend(["실행 또는 검증된 증빙이 없습니다.", ""])
            continue
        response = obs.get("response", {})
        answer = response.get("answer") if isinstance(response, dict) else None
        result.extend([answer if isinstance(answer, str) and answer.strip() else "응답 없음", ""])
        if not obs.get("model", {}).get("responseId"):
            result.extend(
                ["실제 모델 응답이 관측되지 않아 모델 기반 검토 조건을 충족하지 못했습니다.", ""]
            )
        result.extend(
            [
                f"- 실행 ID: {obs['runId']}",
                f"- 모델 ID: {obs.get('llmModelId', '미확인')}",
                f"- 프롬프트 버전: {obs.get('model', {}).get('promptVersion', '미확인')}",
                f"- 모델 응답 ID: {obs.get('model', {}).get('responseId', '미확인')}",
                f"- 응답 증빙: {obs.get('responseEvidenceRef', '')}",
                "- 도구 및 Catalog 증빙: "
                + obs.get("evidenceRefs", {}).get("tool_trace_or_no_tool_trace", ""),
                f"- Git HEAD: {obs.get('gitCommit', '미확인')}",
                f"- 실행 경로: {obs.get('executionPath', '미확인')}",
                "",
                "### 응답 상품",
                "",
                "```json",
                json.dumps(response.get("products", []), ensure_ascii=False, indent=2),
                "```",
                "",
                "검토자: __________  검토일: __________  판정: __________",
                "",
                "미충족 조건 및 사유: __________",
                "",
            ]
        )
    return "\n".join(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    repository = CONTRACT.parents[2].resolve()
    if output == repository or repository in output.parents:
        parser.error("Human review materials must stay outside the repository")
    output.write_text(
        make_materials(read_jsonl(args.observations), args.evidence_root.resolve()),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
