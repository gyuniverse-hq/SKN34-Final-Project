import { isYoutubeConfigured, searchVideos } from '@/server/clients/youtubeClient';
import type { YoutubeVideo } from '@/types';

export function isTutorialSearchConfigured() {
  return isYoutubeConfigured();
}

export function buildTutorialQuery(query: string) {
  const q = query.trim();
  return /makeup|tutorial|메이크업/i.test(q) ? q : `${q} makeup tutorial`;
}

export function searchTutorials(query: string, maxResults = 8): Promise<YoutubeVideo[]> {
  return searchVideos(buildTutorialQuery(query), maxResults);
}
