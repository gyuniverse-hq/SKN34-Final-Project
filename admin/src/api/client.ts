import { createClient } from "@supabase/supabase-js";
declare global {
  interface Window {
    __VISHUE_ADMIN_CONFIG__?: {
      supabaseUrl?: string;
      supabasePublishableKey?: string;
      apiBaseUrl?: string;
    };
  }
}
const config = window.__VISHUE_ADMIN_CONFIG__;
const url = config?.supabaseUrl || import.meta.env.VITE_SUPABASE_URL;
const key =
  config?.supabasePublishableKey ||
  import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY;
const apiBase = config?.apiBaseUrl || import.meta.env.VITE_API_BASE_URL || "";
export const supabase = url && key ? createClient(url, key) : null;
export const isDemo =
  import.meta.env.DEV &&
  new URLSearchParams(window.location.search).get("demo") === "1";
// This helper never runs in a published build or against a remote API.
export const localAccountSetup =
  import.meta.env.DEV &&
  ["localhost", "127.0.0.1"].includes(window.location.hostname) &&
  ["http://localhost:8000", "http://127.0.0.1:8000"].includes(apiBase);

export async function registerLocalConsent(): Promise<void> {
  if (!localAccountSetup || !supabase)
    throw new Error("로컬 설정을 확인해 주세요.");
  const token = (await supabase.auth.getSession()).data.session?.access_token;
  if (!token) throw new Error("다시 로그인해 주세요.");
  const headers = {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
  const account = await fetch(`${apiBase}/api/me`, { headers });
  if (!account.ok) throw new Error("로컬 회원 정보를 확인하지 못했습니다.");
  const record: { terms?: { version?: string } } = await account.json();
  if (!record.terms?.version)
    throw new Error("약관 버전을 확인하지 못했습니다.");
  const saved = await fetch(`${apiBase}/api/me/terms`, {
    method: "POST",
    headers,
    body: JSON.stringify({ version: record.terms.version }),
  });
  if (!saved.ok) throw new Error("로컬 회원 등록을 완료하지 못했습니다.");
}
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}
const errorMessages: Record<string, string> = {
  forbidden: "이 작업을 수행할 권한이 없습니다.",
  unauthorized: "다시 로그인해 주세요.",
  admin_unavailable: "관리자 API가 아직 활성화되지 않았습니다.",
  invalid_transition:
    "주문 상태가 변경되었습니다. 새로고침 후 다시 확인해 주세요.",
  out_of_stock: "판매 가능한 재고가 부족합니다.",
  payment_cancel_failed:
    "결제 취소를 확인하지 못했습니다. 상태를 확인한 뒤 다시 시도해 주세요.",
  invalid_request: "입력 내용을 확인해 주세요.",
  not_found: "요청한 항목을 찾을 수 없습니다.",
  astra_unavailable: "Astra(LLM) 설정이 없습니다. API 키와 모델을 확인하세요.",
  astra_failed: "Astra 채점에 실패했습니다. 잠시 후 다시 시도해 주세요.",
};

async function parseAdmin<T>(response: Response): Promise<T> {
  const data = await response.json();
  if (!response.ok)
    throw new ApiError(
      response.status,
      data.code,
      errorMessages[data.code] || "요청을 처리하지 못했습니다.",
    );
  return data as T;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (isDemo) {
    if (init.method && init.method !== "GET")
      throw new Error("미리보기에서는 변경할 수 없습니다");
    const { demoResponse } = await import("./demo");
    return demoResponse(path) as T;
  }
  const token = (await supabase?.auth.getSession())?.data.session?.access_token;
  const response = await fetch(`${apiBase}/api/admin${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init.headers,
    },
  });
  return parseAdmin<T>(response);
}

/** Multipart upload; do not set Content-Type so the browser adds the boundary. */
export async function apiForm<T>(path: string, form: FormData): Promise<T> {
  if (isDemo) throw new Error("미리보기에서는 채점을 실행할 수 없습니다");
  const token = (await supabase?.auth.getSession())?.data.session?.access_token;
  const response = await fetch(`${apiBase}/api/admin${path}`, {
    method: "POST",
    body: form,
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  return parseAdmin<T>(response);
}

/** Authenticated binary fetch for stored eval images (blob URL). */
export async function apiBlob(path: string): Promise<string> {
  if (isDemo) throw new Error("미리보기에서는 이미지를 불러올 수 없습니다");
  const token = (await supabase?.auth.getSession())?.data.session?.access_token;
  const response = await fetch(`${apiBase}/api/admin${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    let code = "invalid_request";
    try {
      const data = await response.json();
      code = data.code || code;
    } catch {
      /* ignore */
    }
    throw new ApiError(
      response.status,
      code,
      errorMessages[code] || "이미지를 불러오지 못했습니다.",
    );
  }
  const blob = await response.blob();
  return URL.createObjectURL(blob);
}
