"""Build a standalone HTML review form from Glowpick candidate CSV."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

HTML_TEMPLATE = r"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Glowpick 후보 검수</title>
<style>
:root{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;color:#271f24;background:#faf8f9}*{box-sizing:border-box}body{margin:0}header{position:sticky;top:0;z-index:2;background:#fff;border-bottom:1px solid #e7dfe3;padding:16px max(16px,calc((100vw - 1080px)/2))}h1{font-size:22px;margin:0 0 6px}.hint{font-size:14px;color:#655b61;margin:0 0 12px}.toolbar{display:flex;gap:10px;align-items:center;flex-wrap:wrap}input[type=search]{flex:1;min-width:220px;padding:10px 12px;border:1px solid #d8cdd2;border-radius:10px;font-size:15px}button{border:0;border-radius:10px;padding:11px 16px;background:#682b4a;color:#fff;font-weight:700;cursor:pointer}button.secondary{background:#eee7eb;color:#342831}.stats{font-size:13px;color:#665c62}.wrap{max-width:1080px;margin:0 auto;padding:18px 16px 48px}.card{background:#fff;border:1px solid #e5dce0;border-radius:14px;padding:18px;margin:0 0 16px;box-shadow:0 1px 3px #25131a0d}.card-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.num{font-weight:800;color:#793a59}.ytid{font-size:12px;color:#82777e;word-break:break-all}.source{font-size:18px;font-weight:750;margin:8px 0 4px}.meta{font-size:13px;color:#756b71;margin-bottom:12px}.choices{display:grid;gap:8px}.choice{display:flex;gap:10px;align-items:flex-start;border:1px solid #e8e0e4;border-radius:10px;padding:11px;cursor:pointer}.choice:has(input:checked){border-color:#8b4568;background:#fff8fb}.choice input{margin-top:4px;accent-color:#793a59}.candidate{flex:1;min-width:0}.candidate-title{font-weight:700}.candidate-sub{font-size:13px;color:#655b61;margin-top:3px}.candidate a{color:#783955;text-decoration:none}.other-note{display:none;margin:8px 0 0 28px;width:min(600px,calc(100% - 28px));padding:9px;border:1px solid #d8cdd2;border-radius:8px;font-size:14px}.other-note.show{display:block}.empty{padding:50px 12px;text-align:center;color:#766b72}@media(max-width:600px){header{padding:12px}.wrap{padding:12px}.card{padding:13px}.source{font-size:16px}}
</style>
</head>
<body>
<header>
  <h1>Glowpick 제품 후보 검수</h1>
  <p class="hint">유튜브 조사 상품과 같은 Glowpick 상품 하나를 선택해 주세요. 해당 후보가 없으면 ‘일치 후보 없음’, 판단이 보류되거나 다른 후보가 있으면 ‘기타’를 선택하고 메모를 남겨 주세요. 선택은 이 브라우저에 자동 저장됩니다.</p>
  <div class="toolbar"><input id="search" type="search" placeholder="브랜드명, 제품명 또는 ID 검색"><button id="download">검수 결과 CSV 다운로드</button><button id="clear" class="secondary">선택 초기화</button></div>
  <div id="stats" class="stats"></div>
</header>
<main id="cards" class="wrap"></main>
<script>
const DATA = __DATA__;
const STORAGE_KEY = "glowpick-candidate-review-v1";
let answers = {};
try { answers = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}"); } catch (_) { answers = {}; }
const root = document.getElementById("cards");
const search = document.getElementById("search");
const save = () => localStorage.setItem(STORAGE_KEY, JSON.stringify(answers));
function candidateLabel(candidate) {
  const brand = candidate.glowpick_brand ? candidate.glowpick_brand + " · " : "";
  const score = Number(candidate.similarity_score || 0);
  const price = candidate.search_price_krw ? Number(candidate.search_price_krw).toLocaleString("ko-KR") + "원" : "가격 후보 없음";
  return { title: brand + candidate.glowpick_product_name, detail: `유사도 ${score.toFixed(4)} · ${price} · ${candidate.candidate_source || "검색 경로 미상"}` };
}
function makeChoice(group, decision, title, detail, candidate) {
  const label = document.createElement("label"); label.className = "choice";
  const radio = document.createElement("input"); radio.type = "radio"; radio.name = "pick-" + group.yt_product_id; radio.value = decision;
  const prior = answers[group.yt_product_id] || {};
  radio.checked = prior.decision === decision && (decision !== "candidate" || prior.selected_glowpick_product_id === candidate.glowpick_product_id);
  const body = document.createElement("div"); body.className = "candidate";
  const name = document.createElement("div"); name.className = "candidate-title";
  if (candidate) {
    const link = document.createElement("a"); link.href = candidate.glowpick_product_url || `https://www.glowpick.com/products/${candidate.glowpick_product_id}`; link.target = "_blank"; link.rel = "noopener"; link.textContent = title;
    link.addEventListener("click", (event) => event.stopPropagation()); name.append(link);
  } else { name.textContent = title; }
  body.append(name);
  if (detail) { const sub = document.createElement("div"); sub.className = "candidate-sub"; sub.textContent = detail; body.append(sub); }
  label.append(radio, body);
  radio.addEventListener("change", () => {
    const next = { ...(answers[group.yt_product_id] || {}), decision };
    if (decision !== "other") next.other_note = "";
    if (candidate) Object.assign(next, { selected_glowpick_product_id: candidate.glowpick_product_id, selected_brand: candidate.glowpick_brand, selected_product_name: candidate.glowpick_product_name, selected_url: candidate.glowpick_product_url, selected_similarity: candidate.similarity_score, selected_candidate_source: candidate.candidate_source });
    else { next.selected_glowpick_product_id = ""; next.selected_brand = ""; next.selected_product_name = ""; next.selected_url = ""; next.selected_similarity = ""; next.selected_candidate_source = ""; }
    answers[group.yt_product_id] = next; save(); renderStats();
  });
  return label;
}
function render() {
  root.replaceChildren();
  const query = search.value.trim().toLocaleLowerCase("ko");
  let visible = 0;
  DATA.forEach((group, index) => {
    const haystack = [group.yt_product_id, group.source_brand, group.source_product_name].join(" ").toLocaleLowerCase("ko");
    if (query && !haystack.includes(query)) return;
    visible++;
    const card = document.createElement("section"); card.className = "card";
    const head = document.createElement("div"); head.className = "card-head";
    const number = document.createElement("div"); number.className = "num"; number.textContent = `${index + 1} / ${DATA.length}`;
    const id = document.createElement("div"); id.className = "ytid"; id.textContent = group.yt_product_id;
    head.append(number, id); card.append(head);
    const source = document.createElement("div"); source.className = "source"; source.textContent = `${group.source_brand || "브랜드 미상"} · ${group.source_product_name || "제품명 미상"}`; card.append(source);
    const meta = document.createElement("div"); meta.className = "meta"; meta.textContent = `현재 카테고리: ${group.source_category_current || "없음"} · Glowpick 후보 ${group.candidates.length}개`; card.append(meta);
    const choices = document.createElement("div"); choices.className = "choices";
    group.candidates.forEach((candidate) => { const option = candidateLabel(candidate); choices.append(makeChoice(group, "candidate", option.title, option.detail, candidate)); });
    choices.append(makeChoice(group, "no_match", "일치 후보 없음", "현재 표시된 후보 중 같은 상품이 없음", null));
    const other = makeChoice(group, "other", "기타 / 확인 필요", "다른 후보가 있거나 지금은 판단하기 어려움", null);
    choices.append(other);
    const note = document.createElement("input"); note.type = "text"; note.className = "other-note"; note.placeholder = "기타 사유 또는 확인할 상품명·링크 메모"; note.value = (answers[group.yt_product_id] || {}).other_note || "";
    const otherRadio = other.querySelector("input");
    const syncNote = () => note.classList.toggle("show", otherRadio.checked);
    otherRadio.addEventListener("change", syncNote); syncNote();
    note.addEventListener("input", () => { answers[group.yt_product_id] = { ...(answers[group.yt_product_id] || {}), decision: "other", other_note: note.value }; save(); renderStats(); });
    choices.append(note); card.append(choices); root.append(card);
  });
  if (!visible) { const empty = document.createElement("div"); empty.className = "empty"; empty.textContent = "검색 결과가 없습니다."; root.append(empty); }
  renderStats();
}
function renderStats() {
  const reviewed = DATA.filter((group) => answers[group.yt_product_id]?.decision).length;
  document.getElementById("stats").textContent = `후보 여러 개 상품 ${DATA.length}개 · 현재 검수 ${reviewed}개 · 미검수 ${DATA.length - reviewed}개`;
}
function csvCell(value) { return '"' + String(value ?? "").replaceAll('"', '""') + '"'; }
document.getElementById("download").addEventListener("click", () => {
  const columns = ["yt_product_id","source_brand","source_product_name","source_category_current","decision","selected_glowpick_product_id","selected_brand","selected_product_name","selected_url","selected_similarity","selected_candidate_source","other_note"];
  const lines = [columns.map(csvCell).join(",")];
  DATA.forEach((group) => {
    const answer = answers[group.yt_product_id] || {};
    lines.push([group.yt_product_id,group.source_brand,group.source_product_name,group.source_category_current,answer.decision || "",answer.selected_glowpick_product_id || "",answer.selected_brand || "",answer.selected_product_name || "",answer.selected_url || "",answer.selected_similarity || "",answer.selected_candidate_source || "",answer.other_note || ""].map(csvCell).join(","));
  });
  const blob = new Blob(["\ufeff" + lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = "youtube-glowpick-candidate-decisions.csv"; link.click(); URL.revokeObjectURL(url);
});
document.getElementById("clear").addEventListener("click", () => { if (confirm("이 브라우저에 저장된 모든 선택을 지울까요?")) { answers = {}; save(); render(); } });
search.addEventListener("input", render);
render();
</script>
</body>
</html>"""


def _groups(csv_path: Path) -> list[dict]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("glowpick_product_id"):
                grouped[row["yt_product_id"]].append(row)

    result = []
    for yt_id, candidates in grouped.items():
        if len(candidates) < 2:
            continue
        candidates.sort(
            key=lambda row: (
                -float(row.get("similarity_score") or 0),
                row.get("candidate_rank") or "",
            )
        )
        first = candidates[0]
        result.append(
            {
                "yt_product_id": yt_id,
                "source_brand": first.get("source_brand", ""),
                "source_product_name": first.get("source_product_name", ""),
                "source_category_current": first.get("source_category_current", ""),
                "candidates": [
                    {
                        "glowpick_product_id": row.get("glowpick_product_id", ""),
                        "glowpick_brand": row.get("glowpick_brand", ""),
                        "glowpick_product_name": row.get("glowpick_product_name", ""),
                        "similarity_score": row.get("similarity_score", ""),
                        "search_price_krw": row.get("search_price_krw", ""),
                        "glowpick_product_url": row.get("glowpick_product_url", ""),
                        "candidate_source": row.get("candidate_source", ""),
                    }
                    for row in candidates
                ],
            }
        )
    result.sort(
        key=lambda group: (
            group["source_brand"],
            group["source_product_name"],
            group["yt_product_id"],
        )
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path, required=True, help="Glowpick enrichment review CSV"
    )
    parser.add_argument(
        "--output", type=Path, required=True, help="Output standalone HTML path"
    )
    args = parser.parse_args()
    groups = _groups(args.input)
    payload = json.dumps(groups, ensure_ascii=False).replace("<", "\\u003c")
    html = HTML_TEMPLATE.replace("__DATA__", payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(html, encoding="utf-8")
    print(f"Products with multiple candidates: {len(groups):,}")
    print(f"Wrote review HTML: {args.output}")


if __name__ == "__main__":
    main()
