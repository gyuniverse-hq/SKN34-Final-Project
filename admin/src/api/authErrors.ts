/** Public, allow-listed Auth error codes only: never display provider messages or credentials. */
export function loginErrorMessage(error: unknown): string {
  const details =
    error && typeof error === "object"
      ? (error as { code?: unknown; name?: unknown })
      : {};
  const code =
    typeof details.code === "string" && /^[a-z0-9_]{1,64}$/.test(details.code)
      ? details.code
      : "";
  if (details.name === "AuthRetryableFetchError")
    return "인증 서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.";
  switch (code) {
    case "invalid_credentials":
      return "이메일 또는 비밀번호가 올바르지 않아요.";
    case "over_email_send_rate_limit":
    case "over_request_rate_limit":
      return "요청이 너무 잦아요. 잠시 기다린 뒤 다시 시도해 주세요.";
    case "otp_disabled":
      return "이 이메일이 기존 앱에 등록되지 않았거나 로그인이 허용되지 않았어요. 기존 앱 계정과 인증 설정을 확인해 주세요.";
    case "signup_disabled":
      return "신규 계정 등록이 허용되지 않는 상태예요. 프로젝트 관리자에게 문의해 주세요.";
    case "user_not_found":
      return "이 계정을 확인할 수 없어요. 기존 앱에 가입한 이메일인지 확인해 주세요.";
    case "email_not_confirmed":
      return "기존 계정의 이메일 인증이 완료되지 않았어요. 기존 앱에서 확인해 주세요.";
    case "email_address_invalid":
    case "validation_failed":
      return "이메일 형식을 확인해 주세요.";
    case "otp_expired":
      return "인증 코드가 올바르지 않거나 만료됐어요. 코드를 다시 요청해 주세요.";
    case "email_provider_disabled":
      return "이메일 로그인이 비활성화되어 있어요. 프로젝트 관리자에게 문의해 주세요.";
    default:
      return `로그인하지 못했어요.${code ? ` (오류 코드: ${code})` : ""}`;
  }
}
