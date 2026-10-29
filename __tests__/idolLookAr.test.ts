import { displayableIdolLooks, hasIdolLookArSettings, idolLookAsCelebLook } from '@/lib/idolLooks';
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

const UNVERIFIED_LOOK: IdolLook = {
  ...LOOK,
  id: 'LOOK-003',
  video: { ...LOOK.video, id: 'VIDEO-003', analysisStatus: 'metadata_unavailable' },
  arSettings: { lip: null, blush: null, eyeshadow: null },
};

beforeEach(() => useMakeupStore.getState().reset());

describe('idol look AR flow', () => {
  it('shows only verified video metadata in customer-facing collections', () => {
    expect(displayableIdolLooks([LOOK, UNVERIFIED_LOOK])).toEqual([LOOK]);
  });

  it('shows nothing when no verified metadata is available', () => {
    expect(displayableIdolLooks([UNVERIFIED_LOOK])).toEqual([]);
    expect(displayableIdolLooks(undefined)).toEqual([]);
  });

  it('enables AR only when at least one preset zone exists', () => {
    expect(hasIdolLookArSettings(LOOK)).toBe(true);
    expect(hasIdolLookArSettings(UNVERIFIED_LOOK)).toBe(false);
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
