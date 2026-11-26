import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router";
import {
  isAuthConfigured,
  isStaffSession,
  loginErrorMessage,
  signInWithEmail,
  signInWithGoogle,
  STAFF_HOME,
} from "./auth";

export function LoginPage({
  signedIn,
  isStaff = false,
}: {
  signedIn: boolean;
  isStaff?: boolean;
}) {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [googleBusy, setGoogleBusy] = useState(false);
  const [error, setError] = useState("");
  const configured = isAuthConfigured();

  // Parent sets signedIn only after role is known.
  if (signedIn)
    return <Navigate to={isStaff ? STAFF_HOME : "/"} replace />;

  async function afterAuth() {
    if (await isStaffSession()) {
      navigate(STAFF_HOME, { replace: true });
      return;
    }
    navigate("/", { replace: true });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!configured) return;
    setBusy(true);
    setError("");
    try {
      await signInWithEmail(email.trim(), password);
      await afterAuth();
    } catch (issue) {
      setError(loginErrorMessage(issue));
    } finally {
      setBusy(false);
    }
  }

  async function google() {
    if (!configured) return;
    setGoogleBusy(true);
    setError("");
    try {
      await signInWithGoogle();
    } catch (issue) {
      setError(loginErrorMessage(issue));
      setGoogleBusy(false);
    }
  }

  return (
    <main className="auth-screen">
      <div className="auth-card">
        <p className="auth-top-title">로그인</p>
        <img className="auth-mascot" src="/mascot.png" alt="" width={96} height={96} />
        <h1>VISHUE에 오신 걸 환영해요</h1>
        <p className="auth-sub">
          로그인하면 룩 저장, 보상 적립, 멤버십을 이용할 수 있어요.
        </p>
        {!configured && (
          <p className="form-error" role="alert">
            아직 로그인을 사용할 수 없어요. 나중에 다시 시도해 주세요.
          </p>
        )}
        <form className="auth-form" onSubmit={(e) => void submit(e)}>
          <label className="sr-only" htmlFor="web-login-email">
            이메일
          </label>
          <input
            id="web-login-email"
            type="email"
            required
            autoComplete="email"
            placeholder="이메일"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={busy || googleBusy}
          />
          <label className="sr-only" htmlFor="web-login-password">
            비밀번호
          </label>
          <input
            id="web-login-password"
            type="password"
            required
            autoComplete="current-password"
            placeholder="비밀번호"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={busy || googleBusy}
          />
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button type="submit" disabled={busy || googleBusy || !configured}>
            {busy ? "확인 중…" : "로그인"}
          </button>
        </form>
        <button type="button" className="auth-link" disabled>
          비밀번호를 잊으셨나요?
        </button>
        <div className="auth-divider" />
        <button
          type="button"
          className="secondary auth-social"
          disabled
          title="준비 중"
        >
          Apple로 계속하기
        </button>
        <button
          type="button"
          className="secondary auth-social"
          disabled={busy || googleBusy || !configured}
          onClick={() => void google()}
        >
          {googleBusy ? "연결 중…" : "Google로 계속하기"}
        </button>
        <p className="auth-signup">
          <Link to="/signup">회원가입</Link>
        </p>
      </div>
    </main>
  );
}

