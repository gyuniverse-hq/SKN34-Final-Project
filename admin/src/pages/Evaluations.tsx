import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Estimate, EvalRun, EvalSummary, Factor } from "../api/types";
import { LoadingError } from "./Commerce";
const names: Record<Factor, string> = {
  total: "총점",
  texture: "질감",
  shading: "명암",
  gloss: "윤기",
  boundary: "경계",
  adhesion: "밀착감",
};
const num = (n: number | null | undefined) =>
  n === null || n === undefined ? "미측정" : n.toFixed(2);
function estimate(v: Estimate) {
  return v.estimate === null
    ? "미측정"
    : `${num(v.estimate)} (95% CI ${num(v.low)}–${num(v.high)}, 얼굴 ${v.n})`;
}
export function Unmeasured({ items }: { items: string[] }) {
  return (
    <section className="panel">
      <h2>미측정 항목</h2>
      {items.length ? (
        items.map((x) => (
          <p key={x}>
            <span className="badge">미측정</span> {x}
          </p>
        ))
      ) : (
        <p>보고된 미측정 항목이 없습니다.</p>
      )}
    </section>
  );
}
function Reliability({ summary }: { summary: EvalSummary }) {
  const r = summary.reliability;
  return (
    <section className="panel">
      <h2>평가자 신뢰도</h2>
      <p>{r.raterCount}명 평가 · 렌더 범위</p>
      <dl>
        <dt>ICC(2,1)</dt>
        <dd>{num(r.icc21)}</dd>
        <dt>ICC(2,k)</dt>
        <dd>{num(r.icc2k)}</dd>
        <dt>정규화 ICC</dt>
        <dd>{num(r.normalizedIcc)}</dd>
        <dt>Krippendorff α</dt>
        <dd>{num(r.alpha)}</dd>
        <dt>MDC95 · 사진 한 장</dt>
        <dd>{num(summary.mdc95)}</dd>
        <dt>VLM 판정</dt>
        <dd>{summary.vlmVerdict}</dd>
      </dl>
      <h3>코드 지표와 사람 점수</h3>
      {summary.correlations.length ? (
        summary.correlations.map((c) => (
          <p key={c.metric}>
            {c.metric} · Spearman {num(c.spearman)}
          </p>
        ))
      ) : (
        <p>미측정</p>
      )}
      <small>
        팀원 소표본의 탐색 결과입니다. 품질 합격선이나 실물 발색 정확도를 뜻하지
        않습니다.
      </small>
    </section>
  );
}
export function compareRuns(previous: EvalRun, current: EvalRun) {
  const compatible =
    previous.kind === current.kind &&
    previous.benchmarkSha256 === current.benchmarkSha256 &&
    previous.rubricVersion === current.rubricVersion &&
    previous.metricVersion === current.metricVersion;
  const a = previous.summaryJson.factors.total.estimate,
    b = current.summaryJson.factors.total.estimate;
  return {
    compatible,
    delta: compatible && a !== null && b !== null ? b - a : null,
  };
}
export function comparisonVerdict(previous: EvalRun, current: EvalRun) {
  if (!compareRuns(previous, current).compatible) return null;
  const paired = current.summaryJson.pairedComparison;
  if (
    !paired ||
    paired.previousRendererCommit !== previous.rendererCommit ||
    paired.method !== "face-paired-bootstrap" ||
    paired.totalDelta.n < 2
  )
    return null;
  const { low, high } = paired.totalDelta;
  if (low === null || high === null) return null;
  return low > 0 ? "improved" : high < 0 ? "worse" : "undetected";
}
function Comparison({
  previous,
  current,
}: {
  previous: EvalRun;
  current: EvalRun;
}) {
  const comparison = compareRuns(previous, current);
  const verdict = comparisonVerdict(previous, current);
  const labels = {
    improved: "좋아짐",
    worse: "나빠짐",
    undetected: "차이 없음 (유의한 변화 미검출)",
  };
  const paired = current.summaryJson.pairedComparison;
  return (
    <section className="panel">
      <h2>이전 실행과 비교</h2>
      <p className="badge">
        {verdict ? labels[verdict] : "판정 불가 · 짝 비교 필요"}
      </p>
      {comparison.compatible ? (
        <>
          <p>
            총점 변화 {num(comparison.delta)} · 이전{" "}
            {estimate(previous.summaryJson.factors.total)} · 현재{" "}
            {estimate(current.summaryJson.factors.total)}
          </p>
          <p>
            MDC95 이전 {num(previous.summaryJson.mdc95)} / 현재{" "}
            {num(current.summaryJson.mdc95)} · 사진 한 장 기준, 버전 평균의
            판정선으로 사용하지 않습니다.
          </p>
          {verdict && paired ? (
            <p>
              판정 근거: 같은 얼굴의 짝 차이에 대한 부트스트랩 95% CI{" "}
              {num(paired.totalDelta.low)}–{num(paired.totalDelta.high)}, 얼굴{" "}
              {paired.totalDelta.n}명. 0 포함 여부로 변화 검출을 판단하며
              동등성을 증명하지 않습니다.
            </p>
          ) : (
            <p>
              개별 실행의 신뢰구간만으로 버전 평균의 변화를 확정할 수 없습니다.
              같은 얼굴 묶음의 짝 비교 요약이 필요합니다.
            </p>
          )}
        </>
      ) : (
        <p>종류·벤치마크·척도·지표 버전이 달라 직접 비교하지 않습니다.</p>
      )}
    </section>
  );
}
function Trend({ runs, factor }: { runs: EvalRun[]; factor: Factor }) {
  const list = [...runs].reverse();
  const comparable =
    list.length > 0 && list.every((r) => compareRuns(list[0], r).compatible);
  if (!comparable)
    return (
      <p>동일한 벤치마크·척도·종류의 실행을 선택하면 추이를 표시합니다.</p>
    );
  const values = list.map((r) => r.summaryJson.factors[factor].estimate);
  const max = factor === "total" ? 5 : 1;
  return (
    <>
      <svg
        className="trend"
        viewBox="0 0 620 150"
        role="img"
        aria-label={`${names[factor]} 버전별 추이`}
      >
        <line x1="20" y1="130" x2="600" y2="130" stroke="#ddd" />
        {values.map((v, i) =>
          v === null ? null : (
            <g key={list[i].id}>
              {i > 0 && values[i - 1] !== null && (
                <line
                  x1={20 + ((i - 1) * 580) / Math.max(1, list.length - 1)}
                  y1={130 - (values[i - 1]! * 110) / max}
                  x2={20 + (i * 580) / Math.max(1, list.length - 1)}
                  y2={130 - (v * 110) / max}
                  stroke="#913c55"
                  strokeWidth="2"
                />
              )}
              <circle
                cx={20 + (i * 580) / Math.max(1, list.length - 1)}
                cy={130 - (v * 110) / max}
                r="4"
                fill="#913c55"
              />
              <title>
                {list[i].rendererCommit}: {v}
              </title>
            </g>
          ),
        )}
      </svg>
      <div className="trend-labels">
        {list.map((r) => (
          <small key={r.id}>
            {r.rendererCommit.slice(0, 7)}
            {r.rendererDirty ? " + 변경" : ""}
          </small>
        ))}
      </div>
    </>
  );
}
export function Evaluations({ dashboard = false }: { dashboard?: boolean }) {
  const [kind, setKind] = useState("human");
  const [selected, setSelected] = useState("");
  const [factor, setFactor] = useState<Factor>("total");
  const q = useQuery({
    queryKey: ["evals", kind],
    queryFn: () =>
      api<{ items: EvalRun[] }>(`/eval-runs?kind=${kind}&limit=30`),
  });
  const runs = q.data?.items || [];
  const current = runs.find((r) => r.id === selected) || runs[0];
  const index = runs.findIndex((r) => r.id === current?.id);
  const previous = runs[index + 1];
  return (
    <>
      <p className="eyebrow">
        {dashboard ? "OPERATIONS OVERVIEW" : "AR QUALITY · REPORT ONLY"}
      </p>
      <h1>{dashboard ? "운영 대시보드" : "AR 평가"}</h1>
      <p>숫자로 살펴보는 AR 현실감. 이미지 확인은 로컬 보고서에서.</p>
      <div className="toolbar">
        <label>
          평가 종류
          <select
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setSelected("");
            }}
          >
            <option value="human">사람 평가</option>
            <option value="bench">코드 벤치마크</option>
            <option value="judge">VLM 평가</option>
          </select>
        </label>
        <label>
          실행
          <select
            value={current?.id || ""}
            onChange={(e) => setSelected(e.target.value)}
          >
            <option value="" disabled>
              실행 선택
            </option>
            {runs.map((r) => (
              <option key={r.id} value={r.id}>
                {new Date(r.createdAt).toLocaleDateString("ko-KR")} ·{" "}
                {r.rendererCommit.slice(0, 7)}
              </option>
            ))}
          </select>
        </label>
      </div>
      <LoadingError pending={q.isPending} error={q.error} />
      {!q.isPending && !q.error && !current && (
        <section className="panel empty">
          <h2>아직 등록된 평가가 없습니다</h2>
          <p>로컬 보고서의 숫자 요약을 검토한 뒤 업로드해 주세요.</p>
          <Unmeasured
            items={["색 재현", "피팅 안정성", "VLM 판정", "짝 비교"]}
          />
        </section>
      )}
      {current && (
        <>
          <div className="metrics">
            <section className="metric">
              <span>렌더 평균 총점</span>
              <strong>
                {num(current.summaryJson.factors.total.estimate)}
                <small> / 5</small>
              </strong>
              <p>
                95% CI {num(current.summaryJson.factors.total.low)}–
                {num(current.summaryJson.factors.total.high)}
              </p>
            </section>
            <section className="metric">
              <span>렌더러 버전</span>
              <strong className="commit">
                {current.rendererCommit.slice(0, 7)}
              </strong>
              <p>
                {current.rendererDirty ? "미커밋 변경 포함" : "커밋과 일치"} ·{" "}
                {new Date(current.createdAt).toLocaleDateString("ko-KR")}
              </p>
            </section>
            <section className="metric">
              <span>평가자 / 얼굴 수</span>
              <strong>
                {current.summaryJson.reliability.raterCount}
                <small>명 / {current.summaryJson.factors.total.n}명</small>
              </strong>
              <p>{current.rubricVersion}</p>
            </section>
          </div>
          <section className="panel">
            <div className="panel-heading">
              <h2>요인별 추이</h2>
              <label>
                요인
                <select
                  value={factor}
                  onChange={(e) => setFactor(e.target.value as Factor)}
                >
                  {Object.entries(names).map(([k, v]) => (
                    <option value={k} key={k}>
                      {v}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <Trend runs={runs} factor={factor} />
            <div className="factor-list">
              {Object.entries(current.summaryJson.factors).map(([k, v]) => (
                <div key={k}>
                  <b>{names[k as Factor]}</b>
                  <span>{estimate(v)}</span>
                </div>
              ))}
            </div>
          </section>
          {previous && <Comparison previous={previous} current={current} />}
          <div className="columns">
            <Reliability summary={current.summaryJson} />
            <div>
              {(["itaBins", "finishes", "mouths"] as const).map((key, i) => (
                <section className="panel" key={key}>
                  <h2>{["피부톤 ITA 구간", "제형", "입 상태"][i]}</h2>
                  {current.summaryJson[key].length ? (
                    <table>
                      <thead>
                        <tr>
                          <th>구간</th>
                          <th>총점 · 95% CI</th>
                        </tr>
                      </thead>
                      <tbody>
                        {current.summaryJson[key].map((g) => (
                          <tr key={g.label}>
                            <td>{g.label}</td>
                            <td>{estimate(g.total)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  ) : (
                    <p>미측정</p>
                  )}
                </section>
              ))}
            </div>
          </div>
          {!!current.summaryJson.codeMetrics?.length && (
            <section className="panel">
              <h2>코드 벤치마크</h2>
              <p>보고용 중앙값이며 품질 판정이 아닙니다.</p>
              {current.summaryJson.codeMetrics.map((metric) => (
                <p key={metric.metric}>
                  {metric.metric} · {estimate(metric.value)}
                </p>
              ))}
            </section>
          )}
          <Unmeasured items={current.summaryJson.unmeasured} />
        </>
      )}
    </>
  );
}
