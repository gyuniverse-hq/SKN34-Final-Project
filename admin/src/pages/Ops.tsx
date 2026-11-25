import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { OpsChatbot, OpsRecommendations, OpsSystem } from "../api/types";
import { LoadingError } from "./Commerce";

export function OpsRecommendationsPage() {
  const q = useQuery({
    queryKey: ["ops-recommendations"],
    queryFn: () => api<OpsRecommendations>("/ops/recommendations"),
  });
  return (
    <>
      <p className="eyebrow">OPS</p>
      <h1>추천 Ops</h1>
      <p>피부·AR·장바구니 추천 노출 집계와 실험 플래그(조회 전용).</p>
      <LoadingError pending={q.isPending} error={q.error} />
      {q.data && (
        <div className="panel">
          <div className="metrics" style={{ marginTop: 0 }}>
            <div className="metric">
              <span>추천 노출</span>
              <strong>{q.data.counts.recommendationImpressions}</strong>
            </div>
            <div className="metric">
              <span>스킨케어 이벤트</span>
              <strong>{q.data.counts.skincareEvents}</strong>
            </div>
            <div className="metric">
              <span>장바구니 추천 방문</span>
              <strong>{q.data.counts.cartRecommendationVisits}</strong>
            </div>
          </div>
          <dl className="ops-dl">
            <div>
              <dt>AR 팔레트 모드</dt>
              <dd>{q.data.arPaletteMode}</dd>
            </div>
            <div>
              <dt>AR 실험</dt>
              <dd>{q.data.arPaletteExperiment || "—"}</dd>
            </div>
            <div>
              <dt>장바구니 실험</dt>
              <dd>{q.data.cartRecommendationExperiment || "—"}</dd>
            </div>
          </dl>
        </div>
      )}
    </>
  );
}

export function OpsChatbotPage() {
  const q = useQuery({
    queryKey: ["ops-chatbot"],
    queryFn: () => api<OpsChatbot>("/ops/chatbot"),
    refetchInterval: 30_000,
  });
  return (
    <>
      <p className="eyebrow">OPS</p>
      <h1>챗봇 Ops</h1>
      <p>챗봇 health/ready 프로브. Neo4j는 운영에서 비활성(ADR-0012)일 수 있습니다.</p>
      <LoadingError pending={q.isPending} error={q.error} />
      {q.data && (
        <div className="panel">
          {!q.data.configured && (
            <p className="form-error">{q.data.error || "CHATBOT_BASE_URL 미설정"}</p>
          )}
          <dl className="ops-dl">
            <div>
              <dt>Base URL</dt>
              <dd>{q.data.baseUrl || "—"}</dd>
            </div>
            <div>
              <dt>healthz</dt>
              <dd>
                {q.data.healthz
                  ? `${q.data.healthz.ok ? "OK" : "FAIL"} (${q.data.healthz.status ?? "—"})`
                  : "—"}
              </dd>
            </div>
            <div>
              <dt>readyz</dt>
              <dd>
                {q.data.readyz
                  ? `${q.data.readyz.ok ? "OK" : "FAIL"} (${q.data.readyz.status ?? "—"})`
                  : "—"}
              </dd>
            </div>
          </dl>
          {q.data.readyz?.body != null ? (
            <pre className="ops-pre">{JSON.stringify(q.data.readyz.body, null, 2)}</pre>
          ) : null}
        </div>
      )}
    </>
  );
}

export function OpsSystemPage() {
  const q = useQuery({
    queryKey: ["ops-system"],
    queryFn: () => api<OpsSystem>("/ops/system"),
  });
  return (
    <>
      <p className="eyebrow">OPS</p>
      <h1>시스템</h1>
      <p>ADMIN_ENABLED, 마이그레이션, 립 평가 디렉터리, LLM 설정 여부.</p>
      <LoadingError pending={q.isPending} error={q.error} />
      {q.data && (
        <div className="panel">
          <dl className="ops-dl">
            <div>
              <dt>ENV</dt>
              <dd>{q.data.env}</dd>
            </div>
            <div>
              <dt>ADMIN_ENABLED</dt>
              <dd>{q.data.adminEnabled ? "true" : "false"}</dd>
            </div>
            <div>
              <dt>Alembic</dt>
              <dd>{q.data.alembicHead || "—"}</dd>
            </div>
            <div>
              <dt>립 평가 디렉터리</dt>
              <dd>
                {q.data.lipEvalDir}{" "}
                <span className="badge">
                  {q.data.lipEvalDirExists ? "존재" : "없음"}
                </span>
              </dd>
            </div>
            <div>
              <dt>LLM(자연스러움)</dt>
              <dd>{q.data.llmConfigured ? "설정됨" : "미설정"}</dd>
            </div>
            <div>
              <dt>CORS origins</dt>
              <dd>{q.data.corsOriginCount}</dd>
            </div>
          </dl>
        </div>
      )}
    </>
  );
}
