import type { ApiErrorBody } from '@/types';

export function json<T>(body: T, init?: { status?: number; maxAgeSeconds?: number }) {
  const headers: Record<string, string> = { 'Content-Type': 'application/json; charset=utf-8' };
  if (init?.maxAgeSeconds) {
    headers['Cache-Control'] = `public, max-age=${init.maxAgeSeconds}, s-maxage=${init.maxAgeSeconds}`;
  } else {
    headers['Cache-Control'] = 'no-store';
  }
  return new Response(JSON.stringify(body), { status: init?.status ?? 200, headers });
}

export function errorResponse(status: number, error: string, code?: string) {
  const body: ApiErrorBody = { error, code };
  return json(body, { status });
}

export function clientKey(request: Request): string {
  return (
    request.headers.get('cf-connecting-ip') ??
    request.headers.get('x-forwarded-for')?.split(',')[0]?.trim() ??
    'anonymous'
  );
}

export async function fetchWithTimeout(url: string, init: RequestInit = {}, timeoutMs = 5000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(url, { ...init, signal: controller.signal });
  } finally {
    clearTimeout(timer);
  }
}

export function stringParam(url: URL, name: string, maxLength = 100): string | undefined {
  const value = url.searchParams.get(name)?.trim();
  if (!value) return undefined;
  return value.slice(0, maxLength);
}
