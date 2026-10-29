import type { CelebLook, IdolLook, IdolVideo, LookItem, MakeupZone } from '@/types';

const STEP_BY_ZONE: Record<MakeupZone, LookItem['step']> = {
  lip: 'lips',
  blush: 'cheeks',
  eyeshadow: 'eyes',
  eyeliner: 'eyes',
  mascara: 'eyes',
  brow: 'eyes',
  highlighter: 'cheeks',
  contour: 'cheeks',
  foundation: 'base',
};

/**
 * Offline-safe registration records. These deliberately contain no inferred title,
 * creator, product, colour or AR setting. The API replaces them after DB/API lookup.
 */
const VIDEOS: Array<
  Pick<IdolVideo, 'id' | 'videoId' | 'youtubeUrl' | 'startSeconds' | 'makeupLookId'> & {
    sampleTitle: string;
    sampleDescription: string;
  }
> = [
  {
    id: 'VIDEO-001',
    videoId: 'fDqBPI1SaWY',
    youtubeUrl: 'https://www.youtube.com/watch?v=fDqBPI1SaWY&t=1576s',
    startSeconds: 1576,
    makeupLookId: 'LOOK-001',
    sampleTitle: 'K-CELEBRITY LOOK 01',
    sampleDescription: 'Sample makeup video look',
  },
  {
    id: 'VIDEO-002',
    videoId: 'S2nXySh1WuU',
    youtubeUrl: 'https://www.youtube.com/watch?v=S2nXySh1WuU',
    startSeconds: 0,
    makeupLookId: 'LOOK-002',
    sampleTitle: 'K-CELEBRITY LOOK 02',
    sampleDescription: 'Sample makeup video look',
  },
  {
    id: 'VIDEO-003',
    videoId: 'mXUMB45414A',
    youtubeUrl: 'https://www.youtube.com/watch?v=mXUMB45414A',
    startSeconds: 0,
    makeupLookId: 'LOOK-003',
    sampleTitle: 'K-CELEBRITY LOOK 03',
    sampleDescription: 'Sample makeup video look',
  },
];

export const offlineIdolLooks: IdolLook[] = VIDEOS.map((video) => ({
  id: video.makeupLookId,
  displayName: video.sampleTitle,
  styleDescription: video.sampleDescription,
  isPublished: true,
  video: {
    ...video,
    title: video.sampleTitle,
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

/**
 * Use the registered samples while video metadata is unavailable, but prefer
 * metadata-ready cards as soon as the catalog supplies them.
 */
export function displayableIdolLooks(looks: IdolLook[] | undefined): IdolLook[] {
  const metadataReady = looks?.filter((look) => look.video.analysisStatus === 'metadata_ready') ?? [];
  return metadataReady.length ? metadataReady : offlineIdolLooks;
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
