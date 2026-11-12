import { lazy, Suspense, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { Link, Navigate, NavLink, Route, Routes } from "react-router";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, isDemo, supabase } from "./api/client";
import type { Staff } from "./api/types";
const Orders = lazy(() =>
  import("./pages/Commerce").then((m) => ({ default: m.Orders })),
);
const Products = lazy(() =>
  import("./pages/Commerce").then((m) => ({ default: m.Products })),
);
const AuditLog = lazy(() =>
  import("./pages/Commerce").then((m) => ({ default: m.AuditLog })),
);
const Evaluations = lazy(() =>
  import("./pages/Evaluations").then((m) => ({ default: m.Evaluations })),
);

export function AccessGate({
  ready,
  signedIn,
  staff,
  forbidden,
  children,
}: {
  ready: boolean;
  signedIn: boolean;
  staff?: Staff;
  forbidden: boolean;
  children: React.ReactNode;
}) {
  if (!ready) return <p role="status">로그인을 확인하고 있습니다…</p>;
  if (!signedIn) return <Login />;
  if (forbidden)
    return (
      <main className="login">
        <p className="eyebrow">ACCESS DENIED</p>
        <h1>권한 없음</h1>
        <p>
          직원 권한이 등록되지 않았습니다. 운영자에게 권한 등록을 요청해 주세요.
        </p>
        <button onClick={() => void supabase?.auth.signOut()}>
          다른 계정으로 로그인
        </button>
      </main>
    );
  if (!staff) return <p role="status">직원 권한을 확인하고 있습니다…</p>;
  return children;
}

function Login() {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!supabase) return;
    setBusy(true);
    setError("");
    try {
      const { error: issue } = sent
        ? await supabase.auth.verifyOtp({ email, token: code, type: "email" })
        : await supabase.auth.signInWithOtp({
            email,
            options: { shouldCreateUser: false },
          });
      if (issue) throw issue;
      setSent(true);
    } catch {
      setError("로그인 요청에 실패했습니다. 이메일과 코드를 확인해 주세요.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login">
      <div className="brand">
        VISHUE<span>ADMIN WORKSPACE</span>
      </div>
      <p className="eyebrow">팀의 운영 공간</p>
      <h1>
        함께 관리하는
        <br />더 나은 뷰티 경험.
      </h1>
      <p>등록된 직원 계정으로 로그인해 주세요.</p>
      {!supabase && (
        <p role="alert">
          로그인 설정이 필요합니다. admin/.env.example의 공개 환경 변수를 설정해
          주세요.
        </p>
      )}
      <form onSubmit={submit}>
        <label>
          이메일
          <input
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={sent}
          />
        </label>
        {sent && (
          <label>
            이메일 인증 코드
            <input
              required
              inputMode="numeric"
              autoComplete="one-time-code"
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </label>
        )}
        {error && <p role="alert">{error}</p>}
        <button disabled={busy || !supabase}>
          {busy ? "확인 중…" : sent ? "로그인" : "인증 코드 받기"}
        </button>
        {sent && (
          <button
            type="button"
            className="secondary"
            onClick={() => {
              setSent(false);
              setCode("");
            }}
          >
            이메일 다시 입력
          </button>
        )}
      </form>
      <small>
        이메일에는 인증 코드가 포함된 템플릿이 설정되어 있어야 합니다.
      </small>
    </main>
  );
}

export function App() {
  const cache = useQueryClient();
  const [auth, setAuth] = useState({ ready: false, signedIn: false });
  useEffect(() => {
    if (isDemo || !supabase) {
      setAuth({ ready: true, signedIn: false });
      return;
    }
    let alive = true;
    void supabase.auth.getSession().then(({ data, error }) => {
      if (alive) setAuth({ ready: true, signedIn: !error && !!data.session });
    });
    const { data } = supabase.auth.onAuthStateChange((_event, session) => {
      cache.clear();
      setAuth({ ready: true, signedIn: !!session });
    });
    return () => {
      alive = false;
      data.subscription.unsubscribe();
    };
  }, [cache]);
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => api<Staff>("/me"),
    enabled: auth.signedIn,
  });
  const denied = me.error instanceof ApiError && me.error.status === 403;
  if (isDemo)
    return (
      <>
        <div className="demo-banner">
          로컬 미리보기 · 예시 주문·상품 / 연구 보고서 v2 숫자 요약 · 변경 기능
          비활성
        </div>
        <Workspace
          staff={{ userId: "demo", email: "로컬 미리보기", role: "viewer" }}
        />
      </>
    );
  if (auth.signedIn && me.error && !denied)
    return (
      <main className="login">
        <h1>서버에 연결할 수 없습니다</h1>
        <p role="alert">관리자 API와 DB 설정을 확인해 주세요.</p>
        <button onClick={() => void me.refetch()}>다시 시도</button>
        <button onClick={() => void supabase?.auth.signOut()}>로그아웃</button>
      </main>
    );
  return (
    <AccessGate {...auth} staff={me.data} forbidden={denied} ready={auth.ready}>
      {me.data && <Workspace staff={me.data} />}
    </AccessGate>
  );
}

export function Workspace({ staff }: { staff: Staff }) {
  const items = [
    ["/", "대시보드"],
    ["/orders", "주문"],
    ["/products", "상품"],
    ["/evaluations", "AR 평가"],
    ...(staff.role === "admin" ? [["/audit", "감사 로그"]] : []),
  ];
  return (
    <div className="workspace">
      <aside>
        <Link className="brand" to="/">
          VISHUE<span>ADMIN WORKSPACE</span>
        </Link>
        <nav aria-label="주 메뉴">
          {items.map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="aside-note">
          내부 운영 도구
          <br />
          토스 테스트 결제 시연
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
            <button
              className="text-button"
              onClick={() => {
                if (isDemo) window.location.assign("/");
                else void supabase?.auth.signOut();
              }}
            >
              로그아웃
            </button>
          </div>
        </header>
        <main>
          <Suspense fallback={<p role="status">화면을 불러오는 중…</p>}>
            <Routes>
              <Route path="/" element={<Evaluations dashboard />} />
              <Route path="/orders/*" element={<Orders staff={staff} />} />
              <Route path="/products/*" element={<Products staff={staff} />} />
              <Route path="/evaluations" element={<Evaluations />} />
              <Route
                path="/audit"
                element={
                  staff.role === "admin" ? (
                    <AuditLog />
                  ) : (
                    <Navigate to="/" replace />
                  )
                }
              />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </Suspense>
        </main>
      </div>
    </div>
  );
}
