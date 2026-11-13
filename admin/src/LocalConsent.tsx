import { useState } from "react";
import { registerLocalConsent } from "./api/client";

export function LocalConsent({
  onRegister = registerLocalConsent,
}: {
  onRegister?: () => Promise<void>;
}) {
  const [terms, setTerms] = useState(false);
  const [privacy, setPrivacy] = useState(false);
  const [age, setAge] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setBusy(true);
    setError("");
    try {
      await onRegister();
      setDone(true);
    } catch {
      setError("로컬 회원 등록에 실패했습니다. 관리자 서버를 확인해 주세요.");
    } finally {
      setBusy(false);
    }
  }

  if (done)
    return (
      <p role="status">
        로컬 회원 등록이 끝났습니다. 운영자에게 관리자 권한 등록을 요청해 주세요.
      </p>
    );
  return (
    <section className="local-consent">
      <h2>로컬 테스트 계정 등록</h2>
      <p>
        이 PC의 테스트 DB에만 기록됩니다. 항목을 확인한 뒤 직접 동의해 주세요.
      </p>
      <label>
        <input
          type="checkbox"
          checked={terms}
          onChange={(e) => setTerms(e.target.checked)}
        />{" "}
        이용약관에 동의합니다{" "}
        <a
          href="http://localhost:8081/legal/terms"
          target="_blank"
          rel="noreferrer"
        >
          내용 보기
        </a>
      </label>
      <label>
        <input
          type="checkbox"
          checked={privacy}
          onChange={(e) => setPrivacy(e.target.checked)}
        />{" "}
        개인정보 수집·이용에 동의합니다{" "}
        <a
          href="http://localhost:8081/legal/privacy"
          target="_blank"
          rel="noreferrer"
        >
          내용 보기
        </a>
      </label>
      <label>
        <input
          type="checkbox"
          checked={age}
          onChange={(e) => setAge(e.target.checked)}
        />{" "}
        만 14세 이상입니다
      </label>
      {error && <p role="alert">{error}</p>}
      <button
        disabled={!terms || !privacy || !age || busy}
        onClick={() => void submit()}
      >
        {busy ? "등록 중…" : "동의하고 로컬 회원 등록"}
      </button>
    </section>
  );
}
