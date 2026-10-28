import {
  displayableIdolLooks,
  hasIdolLookArSettings,
  idolLookAsCelebLook,
  offlineIdolLooks,
} from '@/lib/idolLooks';
import { useMakeupStore } from '@/store/makeupStore';
import type { IdolLook } from '@/types';

const LOOK: IdolLook = {
  id: 'LOOK-002',
  displayName: 'Muted rosy look',
  styleDescription: 'Approximate AR recreation',
  isPublished: true,
  video: {
    id: 'VIDEO-002',
    videoId: 'S2nXySh1WuU',
    youtubeUrl: 'https://www.youtube.com/watch?v=S2nXySh1WuU',
    startSeconds: 0,
    title: 'Muted rosy look',
    channelName: 'Channel',
    thumbnailUrl: 'https://i.ytimg.com/vi/S2nXySh1WuU/hqdefault.jpg',
    description: 'Official description',
    publishedAt: '2026-10-27T00:00:00Z',
    makeupLookId: 'LOOK-002',
    analysisStatus: 'metadata_ready',
    productMappingStatus: 'no_verified_products',
  },
  products: [],
  arSettings: {
    lip: { hex: '#B45F6B', intensity: 0.58, texture: 'velvet' },
    blush: { hex: '#C98B92', intensity: 0.34, texture: 'sheer' },
    eyeshadow: { hex: '#8F6B66', intensity: 0.3, texture: 'matte' },
  },
};

beforeEach(() => useMakeupStore.getState().reset());

describe('idol look AR flow', () => {
  it('shows only verified video metadata in customer-facing collections', () => {
    expect(displayableIdolLooks([LOOK, offlineIdolLooks[0]])).toEqual([LOOK]);
  });

  it('shows named sample videos when no verified metadata is available', () => {
    expect(displayableIdolLooks([])).toEqual(offlineIdolLooks);
    expect(offlineIdolLooks.map((look) => look.displayName)).not.toContain(expect.stringMatching(/^YouTube video/));
  });

  it('enables AR only when at least one preset zone exists', () => {
    expect(hasIdolLookArSettings(LOOK)).toBe(true);
    expect(hasIdolLookArSettings(offlineIdolLooks[0])).toBe(false);
  });

  it('converts and applies all three preset zones to the makeup store', () => {
    const celebLook = idolLookAsCelebLook(LOOK);
    useMakeupStore.getState().applyLook(celebLook, []);

    const state = useMakeupStore.getState();
    expect(state.makeup).toEqual(LOOK.arSettings);
    expect(state.activeLook).toEqual({ id: LOOK.id, title: LOOK.displayName });
    expect(state.selections).toEqual({});
  });
});
