import { RateLimiter } from '@/server/cache';
import { clientKey, errorResponse, json, stringParam } from '@/server/http';
import { isYoutubeConfigured, searchTutorials } from '@/server/youtube';
import type { YoutubeSearchResult } from '@/types';

const limiter = new RateLimiter(20, 60 * 1000);

export async function GET(request: Request) {
  const url = new URL(request.url);
  const q = stringParam(url, 'q', 80);
  if (!q) return errorResponse(400, 'Missing query', 'missing_query');

  if (!isYoutubeConfigured()) {
    return json<YoutubeSearchResult>({ configured: false, videos: [] });
  }
  if (!limiter.allow(clientKey(request))) {
    return errorResponse(429, 'Too many searches. Please wait a moment.', 'rate_limited');
  }

  const max = Math.min(Math.max(Number(url.searchParams.get('max')) || 8, 1), 12);
  try {
    const videos = await searchTutorials(q, max);
    return json<YoutubeSearchResult>({ configured: true, videos }, { maxAgeSeconds: 3600 });
  } catch (error) {
    console.error('[youtube]', error);
    return errorResponse(502, 'Tutorial search is temporarily unavailable', 'upstream_error');
  }
}
