import { lazy, Suspense, useState } from "react";
import { Link, Navigate, NavLink, Route, Routes } from "react-router";
import type { Staff } from "./api/types";

const Orders = lazy(() => import("./pages/Commerce").then(({ Orders }) => ({ default: Orders })));
const Products = lazy(() => import("./pages/Commerce").then(({ Products }) => ({ default: Products })));
const AuditLog = lazy(() => import("./pages/Commerce").then(({ AuditLog }) => ({ default: AuditLog })));
const Evaluations = lazy(() => import("./pages/Evaluations").then(({ Evaluations }) => ({ default: Evaluations })));
const Recommendations = lazy(() => import("./pages/Ops").then(({ OpsRecommendationsPage }) => ({ default: OpsRecommendationsPage })));
const Chatbot = lazy(() => import("./pages/Ops").then(({ OpsChatbotPage }) => ({ default: OpsChatbotPage })));
const System = lazy(() => import("./pages/Ops").then(({ OpsSystemPage }) => ({ default: OpsSystemPage })));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const LookCommunity = lazy(() => import("./pages/LookCommunity"));

const navigation = [
  { label: "운영 홈", links: [["", "대시보드"]] },
  { label: "쇼핑 운영", links: [["orders", "주문 관리"], ["products", "상품 관리"]] },
  { label: "품질 관리", links: [["evaluations", "AR 평가"]] },
  { label: "운영 상태", links: [["ops/recommendations", "추천 집계"], ["ops/chatbot", "챗봇 상태"], ["ops/system", "시스템"]] },
];

export function AdminWorkspace({ staff, basePath = "", onSignOut }: {
  staff: Staff;
  basePath?: string;
  onSignOut: () => void | Promise<void>;
}) {
  const home = basePath || "/";
  const groups = staff.role === "admin"
    ? [...navigation, { label: "변경 이력", links: [["audit", "감사 로그"]] }]
    : navigation;
  const [signOutBusy, setSignOutBusy] = useState(false);
  const [signOutFailed, setSignOutFailed] = useState(false);

  async function logout() {
    setSignOutBusy(true);
    setSignOutFailed(false);
    try {
      await onSignOut();
    } catch {
      setSignOutFailed(true);
    } finally {
      setSignOutBusy(false);
    }
  }

  return (
    <div className="workspace admin-workspace">
      <aside className="admin-sidebar">
        <Link className="brand" to={home}>VISHUE<span>관리자 센터</span></Link>
        <nav aria-label="주 메뉴">
          {groups.map(({ label, links }) => (
            <div className="admin-nav-group" key={label}>
              <p>{label}</p>
              {links.map(([path, title]) => (
                <NavLink key={path} to={path ? `${basePath}/${path}` : home} end={!path}>{title}</NavLink>
              ))}
            </div>
          ))}
          {staff.role === "admin" && <div className="admin-nav-group">
            <p>커뮤니티</p>
            <NavLink to={`${basePath}/look-community`}>룩 게시물 신고</NavLink>
          </div>}
        </nav>
      </aside>
      <div className="content">
        <header className="admin-topbar">
          <span>운영 워크스페이스</span>
          <div className="admin-account">
            <span className="admin-account-email" title={staff.email ?? undefined}>{staff.email || "직원 계정"}</span>
            <span className="badge">{staff.role === "admin" ? "관리자" : "조회자"}</span>
            <button className="secondary" type="button" disabled={signOutBusy} onClick={() => void logout()}>
              {signOutBusy ? "로그아웃 중…" : "로그아웃"}
            </button>
          </div>
        </header>
        <main>
          {signOutFailed && <p className="form-error" role="alert">로그아웃에 실패했습니다. 다시 시도해 주세요.</p>}
          <Suspense fallback={<p role="status">화면을 불러오는 중…</p>}>
            <Routes>
              <Route index element={<Dashboard basePath={basePath} />} />
              <Route path="orders/*" element={<Orders staff={staff} />} />
              <Route path="products/*" element={<Products staff={staff} />} />
              <Route path="evaluations" element={<Evaluations canScore={staff.role === "admin"} />} />
              <Route path="ops/recommendations" element={<Recommendations />} />
              <Route path="ops/chatbot" element={<Chatbot />} />
              <Route path="ops/system" element={<System />} />
              {staff.role === "admin" && <Route path="audit" element={<AuditLog />} />}
              {staff.role === "admin" && <Route path="look-community" element={<LookCommunity />} />}
              <Route path="*" element={<Navigate to={home} replace />} />
            </Routes>
          </Suspense>
        </main>
      </div>
    </div>
  );
}
