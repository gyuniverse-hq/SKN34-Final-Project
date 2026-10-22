import type { YoutubeVideo } from '@/types';
import { TtlCache } from '@/server/lib/cache';
import { serverEnv } from '@/server/lib/env';
import { fetchWithTimeout } from '@/server/lib/http';
import { decodeEntities } from '@/server/lib/text';

// search.list costs 100 quota units per call (10,000/day default) — cache aggressively.
const searchCache = new TtlCache<YoutubeVideo[]>(12 * 60 * 60 * 1000);

export function isYoutubeConfigured() {
  return Boolean(serverEnv.youtubeApiKey);
}

interface SearchItem {
  id?: { videoId?: string };
  snippet?: {
    title?: string;
    channelTitle?: string;
    publishedAt?: string;
    thumbnails?: Record<string, { url?: string } | undefined>;
  };
}

export async function searchVideos(q: string, maxResults = 8): Promise<YoutubeVideo[]> {
  const key = serverEnv.youtubeApiKey;
  if (!key) return [];
  const cacheKey = `${q.toLowerCase()}|${maxResults}`;

  return searchCache.getOrLoad(cacheKey, async () => {
    const params = new URLSearchParams({
      part: 'snippet',
      type: 'video',
      q,
      maxResults: String(maxResults),
      safeSearch: 'strict',
      videoEmbeddable: 'true',
      key,
    });
    const res = await fetchWithTimeout(`https://www.googleapis.com/youtube/v3/search?${params}`);
    if (!res.ok) {
      throw new Error(`YouTube search failed (${res.status})`);
    }
    const data = (await res.json()) as { items?: SearchItem[] };
    return (data.items ?? [])
      .filter((item) => item.id?.videoId && item.snippet)
      .map((item) => ({
        videoId: item.id!.videoId!,
        title: decodeEntities(item.snippet!.title ?? ''),
        channelTitle: decodeEntities(item.snippet!.channelTitle ?? ''),
        publishedAt: item.snippet!.publishedAt ?? '',
        thumbnailUrl:
          item.snippet!.thumbnails?.high?.url ??
          item.snippet!.thumbnails?.medium?.url ??
          item.snippet!.thumbnails?.default?.url ??
          '',
      }));
  });
}
