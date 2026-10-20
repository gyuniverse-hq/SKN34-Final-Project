import type { ShoppingOffer } from '@/types';
import { TtlCache } from './cache';
import { serverEnv } from './env';
import { fetchWithTimeout } from './http';
import { decodeEntities } from './youtube';

const offerCache = new TtlCache<ShoppingOffer[]>(6 * 60 * 60 * 1000);
const imageCache = new TtlCache<string | null>(24 * 60 * 60 * 1000);

// Naver may answer SE05 (404) for shop.json on some applications. Back off instead of retrying every request.
const SHOP_UNAVAILABLE_BACKOFF_MS = 60 * 60 * 1000;
let shopUnavailableUntil = 0;

export function isNaverConfigured() {
  return Boolean(serverEnv.naverClientId && serverEnv.naverClientSecret);
}

function authHeaders() {
  return {
    'X-Naver-Client-Id': serverEnv.naverClientId ?? '',
    'X-Naver-Client-Secret': serverEnv.naverClientSecret ?? '',
  };
}

/**
 * Naver Shopping product images (price-comparison catalog and Smart Store). The
 * *.phinf.naver.net hosts have no HTTPS; the same paths are served from pstatic.
 */
export function toHttpsShoppingImage(url: string): string | null {
  const catalog = url.match(/^https?:\/\/(?:shopping\.phinf\.naver\.net|shopping-phinf\.pstatic\.net)(\/.+)$/);
  if (catalog) return `https://shopping-phinf.pstatic.net${catalog[1]}`;
  const store = url.match(/^https?:\/\/(?:shop1\.phinf\.naver\.net|shop-phinf\.pstatic\.net)(\/.+)$/);
  if (store) return `https://shop-phinf.pstatic.net${store[1]}`;
  return null;
}

async function naverFetch(url: string) {
  const res = await fetchWithTimeout(url, { headers: authHeaders() });
  if (res.status !== 429) return res;
  await new Promise((resolve) => setTimeout(resolve, 700));
  return fetchWithTimeout(url, { headers: authHeaders() });
}

interface NaverShopItem {
  title?: string;
  link?: string;
  image?: string;
  lprice?: string;
  mallName?: string;
}

export async function searchOffers(query: string, display = 5): Promise<ShoppingOffer[]> {
  if (!isNaverConfigured() || Date.now() < shopUnavailableUntil) return [];

  return offerCache.getOrLoad(`${query}|${display}`, async () => {
    const params = new URLSearchParams({ query, display: String(display), sort: 'sim' });
    const res = await naverFetch(`https://openapi.naver.com/v1/search/shop.json?${params}`);
    if (res.status === 404) {
      shopUnavailableUntil = Date.now() + SHOP_UNAVAILABLE_BACKOFF_MS;
      console.warn('[naver] shop.json unavailable for this application (SE05); offers disabled');
      return [];
    }
    if (!res.ok) throw new Error(`Naver shopping search failed (${res.status})`);
    const data = (await res.json()) as { items?: NaverShopItem[] };
    return (data.items ?? [])
      .filter((item) => item.link && item.lprice)
      .map((item) => ({
        title: decodeEntities((item.title ?? '').replace(/<[^>]+>/g, '')),
        mallName: item.mallName ?? '',
        priceKRW: Number(item.lprice) || 0,
        imageUrl: (item.image && toHttpsShoppingImage(item.image)) || item.image || '',
        link: item.link!,
      }))
      .filter((offer) => offer.priceKRW > 0);
  });
}

interface NaverImageItem {
  link?: string;
}

/**
 * Real product photo from Naver Shopping. Uses shopping search when available and
 * falls back to image search restricted to Naver Shopping product images
 * (never blog or social images, which have unclear licensing).
 */
export async function searchProductImage(query: string): Promise<string | null> {
  if (!isNaverConfigured()) return null;

  return imageCache.getOrLoad(query, async () => {
    try {
      const [offer] = await searchOffers(query, 1);
      if (offer?.imageUrl.startsWith('https://')) return offer.imageUrl;
    } catch {
      // fall through to image search
    }

    const params = new URLSearchParams({ query, display: '30', sort: 'sim' });
    const res = await naverFetch(`https://openapi.naver.com/v1/search/image.json?${params}`);
    if (!res.ok) throw new Error(`Naver image search failed (${res.status})`);
    const data = (await res.json()) as { items?: NaverImageItem[] };
    const urls = (data.items ?? [])
      .map((item) => (item.link ? toHttpsShoppingImage(item.link) : null))
      .filter((url): url is string => !!url);
    return urls.find((url) => url.startsWith('https://shopping-phinf.')) ?? urls[0] ?? null;
  });
}
