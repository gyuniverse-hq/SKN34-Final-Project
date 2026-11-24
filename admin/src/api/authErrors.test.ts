import { describe, expect, it } from "vitest";
import { loginErrorMessage } from "./authErrors";

describe("로그인 오류 안내", () => {
  it("인증 요청이 제한되면 잠시 기다리도록 안내한다", () => {
    expect(
      loginErrorMessage({ code: "over_email_send_rate_limit" }, false),
    ).toContain("잠시 기다린");
  });
  it("코드 발송 불가와 코드 검증 실패를 구분한다", () => {
    expect(loginErrorMessage({ code: "otp_disabled" }, false)).toContain(
      "기존 앱",
    );
    expect(loginErrorMessage({ code: "otp_expired" }, true)).toContain("만료");
  });
  it("오류 원문에 이메일이나 토큰이 있어도 노출하지 않는다", () => {
    const message = loginErrorMessage(
      { code: "unexpected_failure", message: "private@example.test secret" },
      false,
    );
    expect(message).toContain("unexpected_failure");
    expect(message).not.toContain("private@example.test");
    expect(message).not.toContain("secret");
  });
});
