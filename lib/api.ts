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

/**
 * Fetches from the app's API routes. Relative URLs resolve to the dev server in
 * development and to the `origin` configured for expo-router in production builds.
 */
export async function apiGet<T>(path: string): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(path, { signal: controller.signal, headers: { Accept: 'application/json' } });
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
  return (await res.json()) as T;
}
