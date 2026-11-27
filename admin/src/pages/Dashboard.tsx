import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { api } from "../api/client";
import type { LipEvalProductList, OpsChatbot, OpsSystem, Order, Page } from "../api/types";
import { LoadingError } from "./Commerce";

export default function Dashboard({ basePath }: { basePath: string }) {
  const paid = useQuery({
    queryKey: ["orders", "dashboard", "paid"],
    queryFn: () => api<Page<Order>>("/orders?status=paid&limit=5"),
  });
  const preparing = useQuery({
    queryKey: ["orders", "dashboard", "preparing"],
    queryFn: () => api<Page<Order>>("/orders?status=preparing&limit=5"),
  });
  const evaluations = useQuery({
    queryKey: ["lip-eval-products"],
    queryFn: () => api<LipEvalProductList>("/lip-eval/products"),
  });
  const chatbot = useQuery({
    queryKey: ["ops-chatbot"],
    queryFn: () => api<OpsChatbot>("/ops/chatbot"),
  });
  const system = useQuery({
    queryKey: ["ops-system"],
    queryFn: () => api<OpsSystem>("/ops/system"),
  });
  const unfinished = evaluations.data?.items.filter((product) => !product.aggregate.finalized);
  const services = [
    { label: "챗봇", path: "ops/chatbot", request: chatbot, state: !chatbot.data?.configured ? "미설정" : chatbot.data.healthz?.ok && chatbot.data.readyz?.ok ? "정상" : "점검 필요" },
    { label: "자연스러움 채점", path: "ops/system", request: system, state: system.data?.llmConfigured ? "설정됨" : "미설정" },
    { label: "AR 평가 저장소", path: "ops/system", request: system, state: system.data?.lipEvalDirExists ? "경로 확인됨" : "점검 필요" },
  ];

  return (
    <>
      <h1>오늘 처리할 일</h1>
      <div className="admin-dashboard">
        <section className="panel">
          <h2>처리 대기 주문</h2>
          {[{ label: "결제 완료", status: "paid", request: paid }, { label: "준비 중", status: "preparing", request: preparing }].map(({ label, status, request }) => (
            <div className="admin-dashboard-row" key={status}>
              <Link to={`${basePath}/orders?status=${status}`}>{label} 주문</Link>
              <LoadingError pending={request.isPending} error={request.error} onRetry={() => void request.refetch()} />
              {request.data && <strong>{request.data.nextCursor ? "6개 이상" : `${request.data.items.length}개`}</strong>}
            </div>
          ))}
        </section>
        <section className="panel">
          <h2>미완료 AR 평가</h2>
          <LoadingError pending={evaluations.isPending} error={evaluations.error} onRetry={() => void evaluations.refetch()} />
          {unfinished && <p>{unfinished.length}개 제품 평가 대기</p>}
          <Link className="admin-action-link" to={`${basePath}/evaluations`}>제품 평가 열기</Link>
        </section>
        <section className="panel">
          <h2>서비스 상태</h2>
          {services.map(({ label, path, request, state }) => (
            <div className="admin-dashboard-row" key={label}>
              <Link to={`${basePath}/${path}`}>{label}</Link>
              <span className="badge" data-state={request.error || state === "점검 필요" ? "warning" : undefined}>
                {request.isPending ? "확인 중" : request.error ? "조회 실패" : state}
              </span>
            </div>
          ))}
        </section>
      </div>
    </>
  );
}
