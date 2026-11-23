"""Publish aggregate numbers only. No images or image identifiers leave this process.

Run with `uv run --project backend/api python research/lip_rubric/publish_eval.py --help`.
The backend's strict request schema is reused to prevent uploader/API contract drift.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import statistics
import sys
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend" / "api"))
from app.schemas.admin import EvalCreate  # noqa: E402


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def unknown():
    return {"estimate": None, "low": None, "high": None, "n": 0}


def estimate(value):
    bounds = value.get("ci95", [None, None])
    return {"estimate": value.get("estimate"), "low": bounds[0], "high": bounds[1],
            "n": value.get("clusters", 0)}


def build_payload(db_path, results, benchmark, kind="human", run_id=None):
    # mode=ro prevents accidental SQLite creation/writes. Select only needed columns.
    with sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        query = "SELECT run_id,renderer_commit,renderer_dirty,benchmark_sha256 FROM runs WHERE kind=?"
        values = ["pack" if kind == "human" else "bench"]
        if run_id:
            query += " AND run_id=?"
            values.append(run_id)
        runs = list(con.execute(query, values))
        if len(runs) != 1:
            raise ValueError("실행이 하나여야 합니다. 여러 실행은 --run-id로 지정하세요")
        run = runs[0]
        digest = hashlib.sha256(Path(benchmark).read_bytes()).hexdigest()
        if run["benchmark_sha256"] and run["benchmark_sha256"] != digest:
            raise ValueError("벤치마크가 실행 기록과 다릅니다")
        factors = {key: unknown() for key in ("total", "texture", "shading", "gloss", "boundary", "adhesion")}
        summary = {"factors": factors, "reliability": {"raterCount": 0}, "mdc95": None,
                   "finishes": [], "mouths": [], "itaBins": [], "correlations": [],
                   "codeMetrics": [], "vlmVerdict": "판정 불가",
                   "unmeasured": ["색 재현", "피팅 안정성", "VLM 판정", "짝 비교"]}
        rubric, metric = "unmeasured", "unmeasured"
        if kind == "human":
            versions = {r[0] for r in con.execute(
                "SELECT DISTINCT metric_version FROM code_metrics WHERE run_id=?", (run["run_id"],)
            )}
            if len(versions) == 1:
                metric = versions.pop()
            source = read_json(Path(results) / "human_summary.json")
            if source.get("status") != "measured":
                raise ValueError("사람 평가 집계가 없습니다")
            rubric = source["rubric_version"]
            report = source["render_report_only"]
            for key, name in zip(factors, ("total_mean", "q1_mean", "q2_mean", "q3_mean", "q4_mean", "q5_mean"), strict=True):
                factors[key] = estimate(report["all"]["all"][name])
            for key, dimension in (("finishes", "finish"), ("mouths", "mouth"), ("itaBins", "ita_bin")):
                summary[key] = [{"label": label, "total": estimate(item["total_mean"])}
                                for label, item in report[dimension].items()]
            # Optional exploratory files contain individual records too: allow-list only aggregates.
            severity_path = Path(results) / "adhoc_severity.json"
            reliability_path = Path(results) / "adhoc_v2_analysis.json"
            mdc_path = Path(results) / "adhoc_mdc_disagreement.json"
            reliability = {"raterCount": source["rater_count"]}
            if reliability_path.exists():
                count = con.execute("SELECT count(*) FROM images WHERE kind='render' AND repeat_of IS NULL").fetchone()[0]
                matches = [r for r in read_json(reliability_path)["reliability"]
                           if r["n_images"] == count and len(r["raters"]) == source["rater_count"]]
                if len(matches) == 1:
                    r = matches[0]
                    reliability.update(icc21=r["icc_2_1"], icc2k=r["icc_2_k"], alpha=r["overall_alpha"])
            if severity_path.exists():
                s = read_json(severity_path)
                count = s.get("raters", [])
                count = len(count) if isinstance(count, list) else count
                if count == source["rater_count"]:
                    reliability["normalizedIcc"] = s["z_by_render"]["icc_2_k"]
                    summary["correlations"] = [{"metric": name, "spearman": value["raw_mean"]["spearman"]}
                                               for name, value in s["code_metric_vs_total_5raters"].items()]
            if mdc_path.exists() and reliability.get("icc2k") is not None:
                m = read_json(mdc_path)["mdc"]["raw_icc_2_k"]
                if m["icc"] == reliability["icc2k"]:
                    summary["mdc95"] = m["mdc95_points"]
            summary["reliability"] = reliability
        else:
            rows = list(con.execute("SELECT metric,value,metric_version FROM code_metrics WHERE run_id=? AND value IS NOT NULL", (run["run_id"],)))
            versions = {r["metric_version"] for r in rows}
            if len(versions) != 1:
                raise ValueError("코드 지표 버전이 없거나 섞여 있습니다")
            metric = versions.pop()
            for name in sorted({r["metric"] for r in rows}):
                vals = [r["value"] for r in rows if r["metric"] == name]
                summary["codeMetrics"].append({"metric": name, "value": {
                    "estimate": statistics.median(vals), "low": None, "high": None, "n": len(vals)}})
            summary["unmeasured"].append("사람 평가")
        payload = {"kind": kind, "rendererCommit": run["renderer_commit"],
                   "rendererDirty": bool(run["renderer_dirty"]), "rubricVersion": rubric,
                   "metricVersion": metric, "benchmarkSha256": digest, "summaryJson": summary}
    return EvalCreate.model_validate(payload).model_dump(mode="json", by_alias=True)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def publish(payload, api_base, token, sender=None):
    # Validate again immediately before sending, even if a caller changed the generated object.
    clean = EvalCreate.model_validate(payload).model_dump(mode="json", by_alias=True)
    url = urlsplit(api_base)
    if not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in ("", "/"):
        raise ValueError("API base는 인증정보·경로·쿼리가 없는 origin이어야 합니다")
    if url.scheme != "https" and not (url.scheme == "http" and url.hostname in ("localhost", "127.0.0.1", "::1")):
        raise ValueError("HTTPS 또는 로컬 HTTP만 허용합니다")
    if not token:
        raise ValueError("VISHUE_ADMIN_TOKEN이 필요합니다")
    sender = sender or build_opener(NoRedirect()).open
    request = Request(api_base.rstrip("/") + "/api/admin/eval-runs", method="POST",
                      data=json.dumps(clean, ensure_ascii=False, allow_nan=False).encode(),
                      headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    with sender(request, timeout=20) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--results", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--kind", choices=("human", "bench"), default="human")
    parser.add_argument("--run-id")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--api-base")
    parser.add_argument("--paired-comparison", type=Path,
                        help="동일 얼굴 묶음의 짝 차이 집계 JSON (개별 기록은 금지)")
    args = parser.parse_args()
    payload = build_payload(args.db, args.results, args.benchmark, args.kind, args.run_id)
    if args.paired_comparison:
        payload["summaryJson"]["pairedComparison"] = read_json(args.paired_comparison)
        payload["summaryJson"]["unmeasured"] = [
            item for item in payload["summaryJson"]["unmeasured"] if item != "짝 비교"
        ]
        payload = EvalCreate.model_validate(payload).model_dump(mode="json", by_alias=True)
    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False))
    else:
        if not args.api_base:
            parser.error("업로드는 --api-base가 필요합니다")
        result = publish(payload, args.api_base, os.environ.get("VISHUE_ADMIN_TOKEN"))
        print(json.dumps({"id": result["id"], "kind": result["kind"]}))


if __name__ == "__main__":
    main()
