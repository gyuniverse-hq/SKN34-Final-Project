import { ApiError, api, supabase } from "./api";

/** Same-origin staff home (no second Vite port). */
export const STAFF_HOME = "/admin";

export type StaffMe = {
  userId: string;
  email: string | null;
  role: "admin" | "viewer";
};

/** Keep in sync with constants/legal.ts and backend member_service.TERMS_VERSION. */
export const TERMS_VERSION = "2026-11-26";
export const MIN_PASSWORD_LENGTH = 8;

export function isAuthConfigured() {
  return !!supabase;
}

export function isValidEmail(email: string) {
  // Strip invisible/fullwidth junk users often paste from messengers.
  const cleaned = email
    .normalize("NFKC")
    .replace(/[\u200B-\u200D\uFEFF]/g, "")
    .trim()
    .toLowerCase();
  return /^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/.test(
    cleaned,
  );
}

export function newPasswordError(password: string, confirm: string): string | null {
  if (password.length < MIN_PASSWORD_LENGTH)
    return `비밀번호는 ${MIN_PASSWORD_LENGTH}자 이상으로 정해 주세요.`;
  if (password !== confirm) return "비밀번호가 서로 달라요.";
  return null;
}

function normalizeEmail(email: string) {
  return email
    .normalize("NFKC")
    .replace(/[\u200B-\u200D\uFEFF]/g, "")
    .trim()
    .toLowerCase();
}

export async function signInWithEmail(email: string, password: string) {
  if (!supabase) throw new Error("not_configured");
  const { error } = await supabase.auth.signInWithPassword({
    email: normalizeEmail(email),
    password,
  });
  if (error) throw error;
}

/** Opens Google OAuth in the same tab; returns when redirect begins. */
export async function signInWithGoogle() {
  if (!supabase) throw new Error("not_configured");
  const redirectTo = `${window.location.origin}/login`;
  const { error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo, skipBrowserRedirect: false },
  });
  if (error) throw error;
}

export async function signUpWithEmail(email: string, password: string) {
  if (!supabase) throw new Error("not_configured");
  const address = normalizeEmail(email);
  if (!isValidEmail(address)) {
    const err = new Error("email_address_invalid") as Error & { code: string };
    err.code = "email_address_invalid";
    throw err;
  }
  const { data, error } = await supabase.auth.signUp({
    email: address,
    password,
  });
  if (error) throw error;
  if (data.user && data.user.identities?.length === 0) {
    const err = new Error("user_already_exists") as Error & { code: string };
    err.code = "user_already_exists";
    throw err;
  }
  return { needsVerification: !data.session };
}

export async function verifySignupCode(email: string, code: string) {
  if (!supabase) throw new Error("not_configured");
  const { error } = await supabase.auth.verifyOtp({
    email: normalizeEmail(email),
    token: code,
    type: "signup",
  });
  if (error) throw error;
}

export async function resendSignupCode(email: string) {
  if (!supabase) throw new Error("not_configured");
  const { error } = await supabase.auth.resend({
    type: "signup",
    email: normalizeEmail(email),
  });
  if (error) throw error;
}

export async function agreeToTerms() {
  return api<{ version: string; agreedVersion: string | null }>("/api/me/terms", {
    method: "POST",
    body: JSON.stringify({ version: TERMS_VERSION }),
  });
}

export async function signOut() {
  await supabase?.auth.signOut();
}

/** Staff → true; non-staff / unavailable → false. */
export async function isStaffSession(): Promise<boolean> {
  try {
    await api<StaffMe>("/api/admin/me");
    return true;
  } catch (e) {
    if (e instanceof ApiError && (e.status === 401 || e.status === 403 || e.status === 503))
      return false;
    throw e;
  }
}

export function goAdminWorkspace() {
  window.location.assign(STAFF_HOME);
}

export function loginErrorMessage(error: unknown): string {
  const details =
    error && typeof error === "object"
      ? (error as { code?: unknown; message?: unknown; name?: unknown })
      : {};
  const code =
    typeof details.code === "string" && /^[a-z0-9_]{1,64}$/.test(details.code)
      ? details.code
      : error instanceof Error && error.message === "user_already_exists"
        ? "user_already_exists"
        : "";
  if (details.name === "AuthRetryableFetchError")
    return "인증 서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.";
  switch (code) {
    case "invalid_credentials":
      return "이메일 또는 비밀번호가 올바르지 않아요.";
    case "email_address_invalid":
      return "이메일 형식이 올바르지 않아요. 예: name@gmail.com (공백·특수문자 없이).";
    case "email_not_confirmed":
      return "이메일 인증이 완료되지 않았어요. 메일함의 코드를 확인해 주세요.";
    case "user_not_found":
      return "이 계정을 확인할 수 없어요. 가입한 이메일인지 확인해 주세요.";
    case "user_already_exists":
      return "이미 가입된 이메일이에요. 로그인해 주세요.";
    case "weak_password":
      return "비밀번호가 너무 약해요. 더 길게 입력해 주세요.";
    case "otp_expired":
      return "코드가 올바르지 않거나 만료되었어요.";
    case "over_request_rate_limit":
    case "over_email_send_rate_limit":
      return "인증 메일 발송 한도를 넘었어요. 몇 분 뒤 다시 시도해 주세요.";
    case "email_provider_disabled":
      return "이메일 로그인이 비활성화되어 있어요.";
    default:
      if (error instanceof Error && error.message === "not_configured")
        return "아직 로그인을 사용할 수 없어요. 나중에 다시 시도해 주세요.";
      return `요청을 처리하지 못했어요.${code ? ` (오류 코드: ${code})` : ""}`;
  }
}
