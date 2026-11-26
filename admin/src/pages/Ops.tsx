import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { OpsChatbot, OpsRecommendations, OpsSystem } from "../api/types";
import { LoadingError } from "./Commerce";

function RefreshStatus({ updatedAt, fetching, onRefresh }: {
  updatedAt: number;
  fetching: boolean;
  onRefresh: () => void;
}) {
  return (
    <div className="admin-refresh">
      <small>{updatedAt ? `마지막 조회 ${new Date(updatedAt).toLocaleTimeString("ko-KR")}` : "조회 기록 없음"}</small>
      <button type="button" className="secondary" disabled={fetching} onClick={onRefresh}>새로고침</button>
    </div>
  );
}

function ProbeStatus({ probe }: { probe: OpsChatbot["healthz"] }) {
  return <span className="badge" data-state={probe && !probe.ok ? "warning" : undefined}>
    {probe ? `${probe.ok ? "정상" : probe.status ? "점검 필요" : "연결 실패"}${probe.status ? ` · HTTP ${probe.status}` : ""}` : "미확인"}
  </span>;
}

export function OpsRecommendationsPage() {
  const q = useQuery({
    queryKey: ["ops-recommendations"],
    queryFn: () => api<OpsRecommendations>("/ops/recommendations"),
  });
  return (
    <>
      <h1>추천 집계</h1>
      <p>피부·AR·장바구니 추천 노출 집계와 실험 플래그(조회 전용).</p>
      <RefreshStatus updatedAt={q.dataUpdatedAt} fetching={q.isFetching} onRefresh={() => void q.refetch()} />
      <LoadingError pending={q.isPending} error={q.error} />
      {q.data && (
        <div className="panel">
          <div className="ops-metrics">
            <div className="metric">
              <span>추천 노출</span>
              <strong>{q.data.counts.recommendationImpressions.toLocaleString("ko-KR")}</strong>
            </div>
            <div className="metric">
              <span>스킨케어 이벤트</span>
              <strong>{q.data.counts.skincareEvents.toLocaleString("ko-KR")}</strong>
            </div>
            <div className="metric">
              <span>장바구니 추천 방문</span>
              <strong>{q.data.counts.cartRecommendationVisits.toLocaleString("ko-KR")}</strong>
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
      <h1>챗봇 상태</h1>
      <RefreshStatus updatedAt={q.dataUpdatedAt} fetching={q.isFetching} onRefresh={() => void q.refetch()} />
      <LoadingError pending={q.isPending} error={q.error} />
      {q.data && (
        <div className="panel">
          {!q.data.configured && (
            <p className="form-error">챗봇 주소가 설정되지 않았습니다. API의 CHATBOT_BASE_URL을 확인하세요.</p>
          )}
          <dl className="ops-dl">
            <div>
              <dt>챗봇 API 주소</dt>
              <dd>{q.data.baseUrl || "—"}</dd>
            </div>
            <div>
              <dt>서버 응답</dt>
              <dd><ProbeStatus probe={q.data.healthz} /></dd>
            </div>
            <div>
              <dt>요청 처리 준비</dt>
              <dd><ProbeStatus probe={q.data.readyz} /></dd>
            </div>
          </dl>
          {q.data.readyz?.body != null ? (
            <details><summary>진단 응답 보기</summary><pre className="ops-pre">{JSON.stringify(q.data.readyz.body, null, 2)}</pre></details>
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
      <h1>시스템</h1>
      <RefreshStatus updatedAt={q.dataUpdatedAt} fetching={q.isFetching} onRefresh={() => void q.refetch()} />
      <LoadingError pending={q.isPending} error={q.error} />
      {q.data && (
        <div className="panel">
          <dl className="ops-dl">
            <div>
              <dt>실행 환경</dt>
              <dd>{q.data.env}</dd>
            </div>
            <div>
              <dt>관리자 API</dt>
              <dd>{q.data.adminEnabled ? "활성" : "비활성"}</dd>
            </div>
            <div>
              <dt>DB 마이그레이션</dt>
              <dd>{q.data.alembicHead || "마이그레이션 버전 확인 필요"}</dd>
            </div>
            <div>
              <dt>립 평가 저장소</dt>
              <dd>
                {q.data.lipEvalDir}{" "}
                <span className="badge">
                  {q.data.lipEvalDirExists ? "경로 확인됨" : "경로 없음"}
                </span>
              </dd>
            </div>
            <div>
              <dt>자연스러움 채점 모델</dt>
              <dd>{q.data.llmConfigured ? "설정됨" : "API의 LLM 키와 모델 설정 필요"}</dd>
            </div>
            <div>
              <dt>웹 허용 주소</dt>
              <dd>{q.data.corsOriginCount}개</dd>
            </div>
          </dl>
        </div>
      )}
    </>
  );
}
