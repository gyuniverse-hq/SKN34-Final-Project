import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  api,
  ApiError,
  isDemo,
  localAccountSetup,
  supabase,
} from "./api/client";
import type { Staff } from "./api/types";
import { loginErrorMessage } from "./api/authErrors";
import { LocalConsent } from "./LocalConsent";
import { AdminWorkspace } from "./Workspace";

const webBaseUrl =
  (import.meta.env.VITE_WEB_BASE_URL as string | undefined) ||
  "http://127.0.0.1:5174";

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
  useEffect(() => {
    if (!forbidden || localAccountSetup) return;
    window.location.assign(webBaseUrl.replace(/\/$/, "") + "/");
  }, [forbidden]);

  if (!ready) return <p role="status">로그인을 확인하고 있습니다…</p>;
  if (!signedIn) return <Login />;
  if (forbidden) {
    if (localAccountSetup)
      return (
        <main className="login auth-screen">
          <p className="eyebrow">LOCAL SETUP</p>
          <p>직원 권한이 없습니다. 로컬에서 약관 동의 후 회원으로 등록해 주세요.</p>
          <LocalConsent />
          <button onClick={() => void supabase?.auth.signOut()}>
            다른 계정으로 로그인
          </button>
        </main>
      );
    return (
      <main className="login auth-screen">
        <p role="status">소비자 웹으로 이동 중…</p>
        <button onClick={() => void supabase?.auth.signOut()}>로그아웃</button>
      </main>
    );
  }
  if (!staff) return <p role="status">직원 권한을 확인하고 있습니다…</p>;
  return children;
}

function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [googleBusy, setGoogleBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!supabase) return;
    setBusy(true);
    setError("");
    try {
      const { error: issue } = await supabase.auth.signInWithPassword({
        email: email.trim(),
        password,
      });
      if (issue) throw issue;
    } catch (issue) {
      setError(loginErrorMessage(issue));
    } finally {
      setBusy(false);
    }
  }

  async function google() {
    if (!supabase) return;
    setGoogleBusy(true);
    setError("");
    try {
      const { error: issue } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo: window.location.origin },
      });
      if (issue) throw issue;
    } catch (issue) {
      setError(loginErrorMessage(issue));
      setGoogleBusy(false);
    }
  }

  return (
    <main className="login auth-screen">
      <div className="auth-card">
        <p className="auth-top-title">로그인</p>
        <img className="auth-mascot" src="/mascot.png" alt="" width={96} height={96} />
        <h1>VISHUE에 오신 걸 환영해요</h1>
        <p className="auth-sub">
          로그인하면 룩 저장, 보상 적립, 멤버십을 이용할 수 있어요.
        </p>
        {!supabase && (
          <p role="alert">
            로그인 설정이 필요합니다. admin/.env.example의 공개 환경 변수를 설정해
            주세요.
          </p>
        )}
        <form className="auth-form" onSubmit={(e) => void submit(e)}>
          <label>
            이메일
            <input
              type="email"
              required
              autoComplete="email"
              placeholder="이메일"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              disabled={busy || googleBusy}
            />
          </label>
          <label>
            비밀번호
            <input
              type="password"
              required
              autoComplete="current-password"
              placeholder="비밀번호"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              disabled={busy || googleBusy}
            />
          </label>
          {error && <p role="alert">{error}</p>}
          <button type="submit" disabled={busy || googleBusy || !supabase}>
            {busy ? "확인 중…" : "로그인"}
          </button>
        </form>
        <div className="auth-divider" />
        <button
          type="button"
          className="secondary auth-social"
          disabled={busy || googleBusy || !supabase}
          onClick={() => void google()}
        >
          {googleBusy ? "연결 중…" : "Google로 계속하기"}
        </button>
      </div>
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
  return <AdminWorkspace staff={staff} onSignOut={async () => {
    if (isDemo) {
      window.location.assign("/");
      return;
    }
    const result = await supabase?.auth.signOut();
    if (result?.error) throw result.error;
  }} />;
}
