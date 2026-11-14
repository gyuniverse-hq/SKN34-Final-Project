import { getAccessToken } from '@/lib/auth';
import { getSupabase, isAuthConfigured } from '@/lib/auth/client';
import { getAnonymousChatId } from '@/lib/chatIdentity';
import type { ApiErrorBody } from '@/types';
import Constants from 'expo-constants';

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

const TIMEOUT_MS = 30000;

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

/** A separate chat origin is optional; gateways still use the shared backend origin. */
export function resolveChatApiBaseUrl(configured: string | undefined, fallback: string): string {
  return configured?.trim().replace(/\/+$/, '') || fallback;
}

export const CHAT_API_BASE_URL = resolveChatApiBaseUrl(process.env.EXPO_PUBLIC_CHAT_API_BASE_URL, API_BASE_URL);

/** Sends a request to the backend (`path` starts with /api) with the Supabase access token. */
async function apiRequest(
  path: string,
  init: { method: 'GET' | 'POST' | 'DELETE'; headers?: Record<string, string>; body?: string },
  options: { baseUrl?: string; timeoutMs?: number; fixedToken?: { value: string | null } } = {}
): Promise<Response> {
  const baseUrl = (options.baseUrl ?? API_BASE_URL).replace(/\/+$/, '');
  if (options.baseUrl && baseUrl !== API_BASE_URL && !/^https?:\/\/[^/@?#\\\s]+(?:\/[^?#\\\s]*)?$/i.test(baseUrl)) {
    throw new ApiError('Invalid backend URL', 0, 'invalid_base_url');
  }
  const token = options.fixedToken ? options.fixedToken.value : await getAccessToken().catch(() => null);
  const headers: Record<string, string> = { Accept: 'application/json', ...init.headers };
  if (token) headers.Authorization = `Bearer ${token}`;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(`${baseUrl}${path}`, { ...init, signal: controller.signal, headers });
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

export async function apiGet<T>(path: string, options: { timeoutMs?: number } = {}): Promise<T> {
  const res = await apiRequest(path, { method: 'GET' }, options);
  return (await res.json()) as T;
}

export async function apiPost<T>(
  path: string,
  body: unknown,
  options: { headers?: Record<string, string>; baseUrl?: string; timeoutMs?: number; expectedUserId?: string } = {}
): Promise<T> {
  // Feedback belongs to the user who saw the recommendation, even across an account switch.
  const credentials = options.expectedUserId === undefined ? undefined : await arCredentials();
  if (credentials && (credentials.owner.kind !== 'user' || credentials.owner.id !== options.expectedUserId)) {
    throw new ApiError('Request owner changed', 0, 'owner_changed');
  }
  const res = await apiRequest(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...options.headers },
    body: JSON.stringify(body),
  }, { ...options, ...(credentials ? { fixedToken: { value: credentials.token } } : {}) });
  return (await res.json()) as T;
}

/** Identifies the principal used for an AR request; never contains a token. */
export type ArRequestOwner = { kind: 'guest' | 'user'; id: string };

type OwnedCredentials = { owner: ArRequestOwner; token: string | null };

async function arCredentials(): Promise<OwnedCredentials> {
  try {
    const client = getSupabase();
    if (!client && isAuthConfigured()) throw new Error('Authentication is unavailable');
    const first = client ? await client.auth.getSession() : null;
    if (first?.error) throw first.error;
    const session = first?.data.session ?? null;
    if (!session) {
      const id = await getAnonymousChatId();
      // A sign-in while the anonymous ID was read must not silently switch principals.
      const latest = client ? await client.auth.getSession() : null;
      if (latest?.error || latest?.data.session) throw new Error('Authentication changed');
      return { owner: { kind: 'guest', id }, token: null };
    }
    const token = session.access_token;
    if (!token || !client) throw new Error('Missing access token');
    const verified = await client.auth.getClaims(token);
    const claims = verified.data?.claims;
    if (verified.error || !claims || typeof claims.sub !== 'string' || !claims.sub || claims.role !== 'authenticated' ||
        !session.user?.id || session.user.id !== claims.sub) {
      throw new Error('Unverified access token');
    }
    // Verify the same token is still current after any asynchronous verification.
    const latest = await client.auth.getSession();
    if (latest.error || latest.data.session?.access_token !== token || latest.data.session.user?.id !== claims.sub) {
      throw new Error('Authentication changed');
    }
    return { owner: { kind: 'user', id: claims.sub }, token };
  } catch {
    throw new ApiError('Authentication is unavailable', 0, 'ar_owner_unavailable');
  }
}

/** A synchronous identity epoch; token refresh for the same user does not invalidate AR. */
export function subscribeArIdentityChange(listener: () => void): () => void {
  const client = getSupabase();
  if (!client) return () => {};
  let previous: string | null | undefined;
  let active = true;
  const subscription = client.auth.onAuthStateChange((event, session) => {
    const next = session?.user.id ?? null;
    if ((previous !== undefined && previous !== next) ||
        (previous === undefined && event !== 'INITIAL_SESSION' && event !== 'TOKEN_REFRESHED')) listener();
    previous = next;
  }).data.subscription;
  void client.auth.getSession().then(({ data, error }) => {
    if (active && previous === undefined) {
      if (error) listener();
      else previous = data.session?.user.id ?? null;
    }
  }).catch(() => { if (active) listener(); });
  return () => { active = false; subscription.unsubscribe(); };
}

/** AR calls are bound to the credential actually sent, never to a later login. */
export async function apiPostOwned<T>(
  path: string,
  body: unknown,
  options: { expectedOwner?: ArRequestOwner; timeoutMs?: number } = {}
): Promise<{ data: T; owner: ArRequestOwner }> {
  let changed = false;
  const unsubscribe = subscribeArIdentityChange(() => { changed = true; });
  try {
    const { owner, token } = await arCredentials();
    if (changed || (options.expectedOwner && (owner.kind !== options.expectedOwner.kind || owner.id !== options.expectedOwner.id))) {
      throw new ApiError('AR request owner changed', 0, 'ar_owner_changed');
    }
    // Do not send the guest ID with a user token: an invalid token must not fall back to guest.
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (owner.kind === 'guest') headers['X-Vishue-Anonymous-Id'] = owner.id;
    const res = await apiRequest(path, { method: 'POST', headers, body: JSON.stringify(body) }, {
      baseUrl: CHAT_API_BASE_URL, timeoutMs: options.timeoutMs, fixedToken: { value: token },
    });
    const data = (await res.json()) as T;
    const latest = await arCredentials();
    if (changed || owner.kind !== latest.owner.kind || owner.id !== latest.owner.id) {
      throw new ApiError('AR request owner changed', 0, 'ar_owner_changed');
    }
    return { data, owner };
  } finally {
    unsubscribe();
  }
}

/** Pin chat to the credential owner actually sent; AR proposal/ACK behavior stays unchanged. */
export async function apiPostChat<T>(
  body: unknown,
  options: { expectedUserId?: string | null; timeoutMs?: number } = {}
): Promise<T> {
  if (typeof body === 'object' && body && 'chatContext' in body &&
    typeof body.chatContext === 'object' && body.chatContext && 'session' in body.chatContext &&
    body.chatContext.session && options.expectedUserId === undefined) {
    throw new ApiError('Chat identity required for session references', 0, 'chat_owner_unavailable');
  }
  const client = getSupabase();
  let changed = false;
  let boundUserId = options.expectedUserId;
  const subscription = client?.auth.onAuthStateChange((_event, session) => {
    if (boundUserId !== undefined && (session?.user.id ?? null) !== boundUserId) changed = true;
  }).data.subscription;
  try {
    const { owner, token } = await arCredentials();
    boundUserId ??= owner.kind === 'user' ? owner.id : null;
    if (changed || (options.expectedUserId !== undefined &&
      (owner.kind === 'user' ? owner.id : null) !== options.expectedUserId)) {
      throw new ApiError('Chat owner changed', 0, 'chat_owner_changed');
    }
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (owner.kind === 'guest') headers['X-Vishue-Anonymous-Id'] = owner.id;
    const response = await apiRequest('/api/chat', { method: 'POST', headers, body: JSON.stringify(body) }, {
      baseUrl: CHAT_API_BASE_URL, timeoutMs: options.timeoutMs, fixedToken: { value: token },
    });
    const data = (await response.json()) as T;
    const latest = await arCredentials();
    if (changed || owner.kind !== latest.owner.kind || owner.id !== latest.owner.id) {
      throw new ApiError('Chat owner changed', 0, 'chat_owner_changed');
    }
    return data;
  } catch (error) {
    if (changed) throw new ApiError('Chat owner changed', 0, 'chat_owner_changed');
    if (error instanceof ApiError && error.code === 'ar_owner_unavailable') {
      throw new ApiError('Chat identity unavailable', 0, 'chat_owner_unavailable');
    }
    throw error;
  } finally {
    subscription?.unsubscribe();
  }
}

export async function apiDelete(path: string): Promise<void> {
  await apiRequest(path, { method: 'DELETE' });
}
