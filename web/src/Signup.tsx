import { signupAgreement } from "../../constants/signupAgreement";
import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router";
import {
  agreeToTerms,
  isAuthConfigured,
  isStaffSession,
  isValidEmail,
  loginErrorMessage,
  MIN_PASSWORD_LENGTH,
  newPasswordError,
  resendSignupCode,
  signUpWithEmail,
  STAFF_HOME,
  verifySignupCode,
} from "./auth";

const MIN_CODE_LENGTH = 6;

const agreement = signupAgreement.ko;
type Consent = { terms: boolean; privacy: boolean };

export function SignupPage({
  signedIn,
  isStaff = false,
}: {
  signedIn: boolean;
  isStaff?: boolean;
}) {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [consent, setConsent] = useState<Consent>({
    terms: false,
    privacy: false,
  });
  const [code, setCode] = useState("");
  const [step, setStep] = useState<"form" | "verify" | "consent">("form");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const configured = isAuthConfigured();
  const address = email
    .normalize("NFKC")
    .replace(/[\u200B-\u200D\uFEFF]/g, "")
    .trim()
    .toLowerCase();
  const allConsent = consent.terms && consent.privacy;

  if (signedIn && step === "form")
    return <Navigate to={isStaff ? STAFF_HOME : "/"} replace />;

  async function finish() {
    try {
      await agreeToTerms();
    } catch {
      setStep("consent");
      setError("동의 내용을 저장하지 못했어요. 다시 시도해 주세요.");
      return;
    }
    if (await isStaffSession()) {
      navigate(STAFF_HOME, { replace: true });
      return;
    }
    navigate("/", { replace: true });
  }

  async function submitForm(event: FormEvent) {
    event.preventDefault();
    if (!configured) return;
    if (!isValidEmail(address)) {
      setError("올바른 이메일 주소를 입력해 주세요.");
      return;
    }
    const problem = newPasswordError(password, confirm);
    if (problem) {
      setError(problem);
      return;
    }
    if (!allConsent) {
      setError("필수 약관에 모두 동의해 주세요.");
      return;
    }
    setBusy(true);
    setError("");
    setInfo("");
    try {
      const { needsVerification } = await signUpWithEmail(address, password);
      if (needsVerification) setStep("verify");
      else await finish();
    } catch (issue) {
      setError(loginErrorMessage(issue));
    } finally {
      setBusy(false);
    }
  }

  async function submitCode(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setInfo("");
    try {
      await verifySignupCode(address, code.trim());
      await finish();
    } catch (issue) {
      setError(loginErrorMessage(issue));
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setBusy(true);
    setError("");
    setInfo("");
    try {
      await resendSignupCode(address);
      setInfo("새 코드를 보냈어요.");
    } catch (issue) {
      setError(loginErrorMessage(issue));
    } finally {
      setBusy(false);
    }
  }

  if (step === "consent") {
    return <main className="auth-screen"><div className="auth-card">
      <p role="alert">{error}</p>
      <button type="button" className="primary" disabled={busy} onClick={async () => {
        setBusy(true);
        try { await finish(); } finally { setBusy(false); }
      }}>다시 시도</button>
    </div></main>;
  }

  if (step === "verify") {
    return (
      <main className="auth-screen">
        <div className="auth-card">
          <p className="auth-top-title">회원가입</p>
          <img className="auth-mascot" src="/mascot.png" alt="" width={96} height={96} />
          <h1>이메일을 확인해 주세요</h1>
          <p className="auth-sub">{address}(으)로 보낸 코드를 입력해 주세요.</p>
          <form className="auth-form" onSubmit={(e) => void submitCode(e)}>
            <label className="sr-only" htmlFor="web-signup-code">
              인증 코드
            </label>
            <input
              id="web-signup-code"
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="인증 코드"
              value={code}
              maxLength={10}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
              disabled={busy}
            />
            {error && (
              <p className="form-error" role="alert">
                {error}
              </p>
            )}
            {info && (
              <p className="auth-info" role="status">
                {info}
              </p>
            )}
            <button type="submit" disabled={busy || code.length < MIN_CODE_LENGTH}>
              {busy ? "확인 중…" : "인증하기"}
            </button>
          </form>
          <button
            type="button"
            className="secondary auth-social"
            disabled={busy}
            onClick={() => void resend()}
          >
            코드 다시 받기
          </button>
          <p className="auth-signup">
            <Link to="/login">로그인으로</Link>
          </p>
        </div>
      </main>
    );
  }

  return (
    <main className="auth-screen">
      <div className="auth-card">
        <p className="auth-top-title">회원가입</p>
        <img className="auth-mascot" src="/mascot.png" alt="" width={96} height={96} />
        <h1>회원가입</h1>
        <p className="auth-sub">룩 저장, 보상 적립, 멤버십을 이용할 수 있어요.</p>
        {!configured && (
          <p className="form-error" role="alert">
            아직 가입을 사용할 수 없어요. 나중에 다시 시도해 주세요.
          </p>
        )}
        <form className="auth-form" onSubmit={(e) => void submitForm(e)}>
          <label className="sr-only" htmlFor="web-signup-email">
            이메일
          </label>
          <input
            id="web-signup-email"
            type="email"
            required
            autoComplete="email"
            placeholder="이메일"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            disabled={busy}
          />
          <label className="sr-only" htmlFor="web-signup-password">
            비밀번호
          </label>
          <input
            id="web-signup-password"
            type="password"
            required
            autoComplete="new-password"
            placeholder="비밀번호"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            disabled={busy}
          />
          <label className="sr-only" htmlFor="web-signup-confirm">
            비밀번호 확인
          </label>
          <input
            id="web-signup-confirm"
            type="password"
            required
            autoComplete="new-password"
            placeholder="비밀번호 확인"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            disabled={busy}
          />
          <p className="auth-hint">{MIN_PASSWORD_LENGTH}자 이상 입력해 주세요.</p>
          <fieldset className="auth-consent">
            <legend className="sr-only">약관 동의</legend>
            {(["terms", "privacy"] as const).map(key => (
              <div key={key}>
                <label>
                  <input type="checkbox" checked={consent[key]}
                    onChange={e => setConsent({ ...consent, [key]: e.target.checked })} />
                  {agreement[key === "terms" ? "consent.terms" : "consent.privacy"]}
                </label>
                <details>
                  <summary>{agreement[key === "terms" ? "consent.viewTerms" : "consent.viewData"]}</summary>
                  <p style={{ whiteSpace: "pre-line" }}>
                    {agreement[key === "terms" ? "consent.termsText" : "consent.dataText"]}
                  </p>
                </details>
              </div>
            ))}
            <p className="auth-hint">{agreement["consent.cameraNotice"]}</p>
          </fieldset>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={
              busy ||
              !configured ||
              !address ||
              !password ||
              !confirm ||
              !allConsent
            }
          >
            {busy ? "가입 중…" : "가입하기"}
          </button>
        </form>
        <p className="auth-signup">
          <Link to="/login">이미 계정이 있나요? 로그인</Link>
        </p>
      </div>
    </main>
  );
}
