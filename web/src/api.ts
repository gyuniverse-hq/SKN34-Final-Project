import { createClient } from "@supabase/supabase-js";

const url = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const key = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string | undefined;
export const apiBase = import.meta.env.VITE_DEV_API_PROXY_ACTIVE
  ? ""
  : (import.meta.env.VITE_API_BASE_URL as string) || "";
export const arAppUrl =
  (import.meta.env.VITE_AR_APP_URL as string) || "https://vishue.app/ar";
export const appStoreUrl = (import.meta.env.VITE_APP_STORE_URL as string) || "";

export const supabase = url && key ? createClient(url, key) : null;

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (!headers.has("Content-Type") && init.body)
    headers.set("Content-Type", "application/json");
  if (supabase) {
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (token) headers.set("Authorization", `Bearer ${token}`);
  }
  let response: Response;
  try {
    response = await fetch(`${apiBase}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(
      0,
      "서버에 연결하지 못했어요. 네트워크·CORS 설정을 확인한 뒤 다시 시도해 주세요.",
    );
  }
  if (!response.ok) {
    let message = response.statusText;
    try {
      const body = await response.json();
      message = body.error || body.message || message;
    } catch {
      /* ignore */
    }
    throw new ApiError(response.status, message || "요청에 실패했어요.");
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export type Product = {
  id: string;
  name: string;
  brand: string;
  category: string;
  priceKRW: number;
  imageUrl?: string | null;
  shades?: { id: string; name: string; hex: string }[];
};

export type ProductDiscoveryOrder = {
  hot: string[];
  makeup: string[];
  skincare: string[];
  newArrivals: string[];
};

export type CartLine = {
  productId: string;
  productName: string;
  brand: string;
  shadeId: string;
  shadeName: string;
  unitPriceKRW: number;
  quantity: number;
};
