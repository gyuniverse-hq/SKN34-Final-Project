import type { Product } from '@/types';
import { DEMO_PRODUCTS } from './demo';
import { OLIVEYOUNG_PRODUCTS } from './oliveyoung';

/**
 * Try-on products for testing AR in development when the backend has none (empty seed or no
 * local backend running). Olive Young colors are estimates from option chips (measureMethod
 * "estimated"); demo colors are not real products. Never used in production builds.
 */
export const DEV_TRYON_PRODUCTS: Product[] = [...OLIVEYOUNG_PRODUCTS, ...DEMO_PRODUCTS].filter(
  (p) => p.makeupZone
);

/** Backend try-on products, or the development set when the backend has none. */
export function withDevTryOnFallback(apiTryOn: Product[], isDev: boolean): Product[] {
  return apiTryOn.length || !isDev ? apiTryOn : DEV_TRYON_PRODUCTS;
}
