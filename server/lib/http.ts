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
