import { lazy, Suspense, useEffect } from "react";
import { Link, Navigate, NavLink, Route, Routes } from "react-router";
import { useQuery } from "@tanstack/react-query";
import type { Staff } from "@admin/api/types";
import { ApiError, api } from "./api";
import { signOut } from "./auth";
import "../../admin/src/style.css";

const Orders = lazy(() =>
  import("@admin/pages/Commerce").then((m) => ({ default: m.Orders })),
);
const Products = lazy(() =>
  import("@admin/pages/Commerce").then((m) => ({ default: m.Products })),
);
const AuditLog = lazy(() =>
  import("@admin/pages/Commerce").then((m) => ({ default: m.AuditLog })),
);
const Evaluations = lazy(() =>
  import("@admin/pages/Evaluations").then((m) => ({ default: m.Evaluations })),
);
const OpsRecommendationsPage = lazy(() =>
  import("@admin/pages/Ops").then((m) => ({
    default: m.OpsRecommendationsPage,
  })),
);
const OpsChatbotPage = lazy(() =>
  import("@admin/pages/Ops").then((m) => ({ default: m.OpsChatbotPage })),
);
const OpsSystemPage = lazy(() =>
  import("@admin/pages/Ops").then((m) => ({ default: m.OpsSystemPage })),
);

/** Admin workspace on the same origin as shopping (/admin/*). */
export function StaffApp() {
  const me = useQuery({
    queryKey: ["staff-me"],
    queryFn: () => api<Staff>("/api/admin/me"),
    retry: false,
  });

  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 403) {
      window.location.replace("/");
    }
  }, [me.error]);

  if (me.isPending) return <p role="status">직원 권한을 확인하고 있습니다…</p>;
  if (me.error instanceof ApiError && me.error.status === 403)
    return <p role="status">쇼핑으로 이동 중…</p>;
  if (me.error || !me.data)
    return (
      <main className="login auth-screen">
        <h1>서버에 연결할 수 없습니다</h1>
        <p role="alert">관리자 API와 설정을 확인해 주세요.</p>
        <button type="button" onClick={() => void me.refetch()}>
          다시 시도
        </button>
        <button type="button" onClick={() => void signOut()}>
          로그아웃
        </button>
      </main>
    );

  const staff = me.data;
  const items: [string, string][] = [
    ["/admin", "대시보드"],
    ["/admin/orders", "주문"],
    ["/admin/products", "상품"],
    ["/admin/evaluations", "AR 평가"],
    ["/admin/ops/recommendations", "추천 Ops"],
    ["/admin/ops/chatbot", "챗봇 Ops"],
    ["/admin/ops/system", "시스템"],
    ...(staff.role === "admin"
      ? ([["/admin/audit", "감사 로그"]] as [string, string][])
      : []),
  ];

  return (
    <div className="workspace">
      <aside>
        <Link className="brand" to="/admin">
          VISHUE<span>ADMIN WORKSPACE</span>
        </Link>
        <nav aria-label="주 메뉴">
          {items.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/admin"}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="aside-note">
          내부 운영 도구
          <br />
          로그인 한 번 · 역할별 화면
        </div>
      </aside>
      <div className="content">
        <header>
          <span>운영 워크스페이스</span>
          <div>
            {staff.email || "직원 계정"}{" "}
            <b className="badge">
              {staff.role === "admin" ? "관리자" : "조회자"}
            </b>
            <Link to="/" className="text-button" style={{ marginRight: 8 }}>
              쇼핑
            </Link>
            <button
              type="button"
              className="text-button"
              onClick={() =>
                void signOut().then(() => window.location.assign("/login"))
              }
            >
              로그아웃
            </button>
          </div>
        </header>
        <main>
          <Suspense fallback={<p role="status">화면을 불러오는 중…</p>}>
            <Routes>
              <Route index element={<Evaluations dashboard />} />
              <Route path="orders/*" element={<Orders staff={staff} />} />
              <Route path="products/*" element={<Products staff={staff} />} />
              <Route path="evaluations" element={<Evaluations />} />
              <Route
                path="ops/recommendations"
                element={<OpsRecommendationsPage />}
              />
              <Route path="ops/chatbot" element={<OpsChatbotPage />} />
              <Route path="ops/system" element={<OpsSystemPage />} />
              <Route
                path="audit"
                element={
                  staff.role === "admin" ? (
                    <AuditLog />
                  ) : (
                    <Navigate to="/admin" replace />
                  )
                }
              />
              <Route path="*" element={<Navigate to="/admin" replace />} />
            </Routes>
          </Suspense>
        </main>
      </div>
    </div>
  );
}
