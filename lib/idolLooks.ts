import type { CelebLook, IdolLook, IdolVideo, LookItem, MakeupZone } from '@/types';

const STEP_BY_ZONE: Record<MakeupZone, LookItem['step']> = {
  lip: 'lips',
  blush: 'cheeks',
  eyeshadow: 'eyes',
};

/**
 * Offline-safe registration records. These deliberately contain no inferred title,
 * creator, product, colour or AR setting. The API replaces them after DB/API lookup.
 */
const VIDEOS: Array<Pick<IdolVideo, 'id' | 'videoId' | 'youtubeUrl' | 'startSeconds' | 'makeupLookId'>> = [
  { id: 'VIDEO-001', videoId: 'fDqBPI1SaWY', youtubeUrl: 'https://www.youtube.com/watch?v=fDqBPI1SaWY&t=1576s', startSeconds: 1576, makeupLookId: 'LOOK-001' },
  { id: 'VIDEO-002', videoId: 'S2nXySh1WuU', youtubeUrl: 'https://www.youtube.com/watch?v=S2nXySh1WuU', startSeconds: 0, makeupLookId: 'LOOK-002' },
  { id: 'VIDEO-003', videoId: 'mXUMB45414A', youtubeUrl: 'https://www.youtube.com/watch?v=mXUMB45414A', startSeconds: 0, makeupLookId: 'LOOK-003' },
];

export const offlineIdolLooks: IdolLook[] = VIDEOS.map((video) => ({
  id: video.makeupLookId,
  displayName: `YouTube video ${video.videoId}`,
  styleDescription: 'Video is registered. Makeup style has not been verified.',
  isPublished: true,
  video: {
    ...video,
    title: `YouTube video ${video.videoId}`,
    channelName: '',
    thumbnailUrl: `https://i.ytimg.com/vi/${video.videoId}/hqdefault.jpg`,
    description: null,
    publishedAt: null,
    analysisStatus: 'metadata_unavailable',
    productMappingStatus: 'unreviewed',
  },
  products: [],
  arSettings: { lip: null, blush: null, eyeshadow: null },
}));

export function offlineIdolLook(id: string | undefined) {
  return offlineIdolLooks.find((look) => look.id === id);
}

export function hasIdolLookArSettings(look: IdolLook): boolean {
  return Boolean(look.arSettings.lip || look.arSettings.blush || look.arSettings.eyeshadow);
}

export function idolLookAsCelebLook(look: IdolLook): CelebLook {
  return {
    id: look.id,
    title: look.displayName,
    inspiration: '',
    description: look.styleDescription,
    thumbnailUrl: look.video.thumbnailUrl,
    tutorialQuery: '',
    items: look.products.flatMap((item) =>
      item.productId && item.shadeId
        ? [{
            productId: item.productId,
            shadeId: item.shadeId,
            step: STEP_BY_ZONE[item.makeupZone],
          }]
        : []
    ),
    makeup: look.arSettings,
    tags: [],
  };
}
