import type { Href } from 'expo-router';
import { API_BASE_URL } from '@/lib/api';

export const LOOK_COMMUNITY = '/api/look-community';
export type LookProduct = { productId: string; shadeId?: string | null };
export type LookPost = {
  id: string;
  title: string;
  example?: boolean;
  displayName?: string | null;
  description: string;
  products: LookProduct[];
  votes: number;
  hidden: boolean;
  createdAt: string;
};

export const lookPhoto = (id: string, revision?: number) =>
  `${API_BASE_URL}${LOOK_COMMUNITY}/${id}/photo${revision === undefined ? '' : `?v=${revision}`}`;
export const communityWriteHref = (params: { id?: string; title?: string; products?: string } = {}) =>
  ({ pathname: '/community-write', params } as Href);
export const communityPostHref = (id: string) => ({ pathname: '/community-post', params: { id } } as Href);
export const communityMineHref = '/community-mine' as Href;
export const communityFeedHref = { pathname: '/celeb', params: { section: 'community' } } as Href;

export function parseSharedProducts(value?: string): LookProduct[] {
  try {
    const items: unknown = JSON.parse(value ?? '[]');
    if (!Array.isArray(items)) return [];
    return items.filter((item): item is LookProduct =>
      item && typeof item.productId === 'string' && /^[A-Za-z0-9_.:-]{1,96}$/.test(item.productId) &&
      (item.shadeId == null || typeof item.shadeId === 'string' && /^[A-Za-z0-9_.:-]{1,96}$/.test(item.shadeId))
    ).slice(0, 12);
  } catch {
    return [];
  }
}
