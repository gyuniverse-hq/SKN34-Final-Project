import Constants from 'expo-constants';
import { getAccessToken } from '@/lib/auth';
import type { ApiErrorBody } from '@/types';

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

const TIMEOUT_MS = 12000;

/** Local backend gateway: infra/compose nginx, or a port-forward to the kind cluster. */
const DEV_GATEWAY_PORT = 8080;

/**
 * Backend origin. An explicit EXPO_PUBLIC_API_BASE_URL wins; in development the gateway runs on
 * the same PC as Metro. An empty result keeps paths relative (web served behind the same origin).
 */
export function resolveApiBaseUrl(options: {
  configured?: string;
  isDev: boolean;
  devHost?: string | null;
}): string {
  if (options.configured) return options.configured.replace(/\/+$/, '');
  if (options.isDev) return `http://${options.devHost || 'localhost'}:${DEV_GATEWAY_PORT}`;
  return '';
}

function devServerHost(): string | null {
  // "<LAN IP>:<Metro port>" in Expo Go, so a phone reaches the PC; on web, the page's host.
  const hostUri = Constants.expoConfig?.hostUri;
  if (hostUri) return hostUri.slice(0, hostUri.lastIndexOf(':')) || hostUri;
  return typeof window !== 'undefined' && window.location ? window.location.hostname : null;
}

export const API_BASE_URL = resolveApiBaseUrl({
  configured: process.env.EXPO_PUBLIC_API_BASE_URL,
  isDev: __DEV__,
  devHost: __DEV__ ? devServerHost() : null,
});

/** Sends a request to the backend (`path` starts with /api) with the Supabase access token. */
async function apiRequest(
  path: string,
  init: { method: 'GET' | 'POST' | 'DELETE'; headers?: Record<string, string>; body?: string }
): Promise<Response> {
  const token = await getAccessToken().catch(() => null);
  const headers: Record<string, string> = { Accept: 'application/json', ...init.headers };
  if (token) headers.Authorization = `Bearer ${token}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(`${API_BASE_URL}${path}`, { ...init, signal: controller.signal, headers });
  } catch (error) {
    throw new ApiError(
      error instanceof Error && error.name === 'AbortError' ? 'Request timed out' : 'Network error',
      0,
      'network'
    );
  } finally {
    clearTimeout(timer);
  }

  if (!res.ok) {
    let body: ApiErrorBody | undefined;
    try {
      body = (await res.json()) as ApiErrorBody;
    } catch {
      // non-JSON error body
    }
    throw new ApiError(body?.error ?? `Request failed (${res.status})`, res.status, body?.code);
  }
  return res;
}

export async function apiGet<T>(path: string): Promise<T> {
  const res = await apiRequest(path, { method: 'GET' });
  return (await res.json()) as T;
}

export async function apiPost<T>(
  path: string,
  body: unknown,
  options: { headers?: Record<string, string> } = {}
): Promise<T> {
  const res = await apiRequest(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...options.headers },
    body: JSON.stringify(body),
  });
  return (await res.json()) as T;
}

export async function apiDelete(path: string): Promise<void> {
  await apiRequest(path, { method: 'DELETE' });
}
