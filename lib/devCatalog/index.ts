import type { CelebLook, Product, ProductCategory } from '@/types';
import { DEMO_LOOKS, DEMO_PRODUCTS, DEMO_SHOP_LIP } from './demo';

export { DEMO_SHOP_LIP };

/** Shop list in development: the one AR-check lip, without replacing the AR try-on catalog. */
export function withDevShopLip(
  products: Product[],
  params: { q?: string; category?: ProductCategory } = {}
): Product[] {
  if (!__DEV__) return products;
  const q = (params.q ?? '').trim().toLowerCase();
  const matchesCategory = !params.category || DEMO_SHOP_LIP.category === params.category;
  const matchesQuery =
    !q ||
    [DEMO_SHOP_LIP.name, DEMO_SHOP_LIP.nameKo, DEMO_SHOP_LIP.brand].some((s) => s.toLowerCase().includes(q));
  if (!matchesCategory || !matchesQuery) return products;
  if (products.some((p) => p.id === DEMO_SHOP_LIP.id)) return products;
  return [DEMO_SHOP_LIP, ...products];
}

// The Olive Young catalog is large generated data. It is required only when __DEV__ is true, so the
// production bundler drops this branch and the file never ships in a release build.
const OLIVEYOUNG_PRODUCTS: Product[] = __DEV__
  ? (require('./oliveyoung') as typeof import('./oliveyoung')).OLIVEYOUNG_PRODUCTS
  : [];

/**
 * Try-on products for testing AR in development when the backend has none (empty seed or no
 * local backend running). Olive Young colors are estimates from option chips (measureMethod
 * "estimated"); demo colors are not real products. Never used in production builds.
 */
export const DEV_TRYON_PRODUCTS: Product[] = [...OLIVEYOUNG_PRODUCTS, ...DEMO_PRODUCTS].filter(
  (p) => p.makeupZone
);

/** Demo looks for development, shown when the backend has none (the production list is the backend seed). */
export const DEV_LOOKS: CelebLook[] = DEMO_LOOKS;

/** A demo look with its products, in the same shape as `/api/looks/:id`; null for any other id. */
export function devLookDetail(id: string): { look: CelebLook; products: Product[] } | null {
  const look = DEV_LOOKS.find((l) => l.id === id);
  if (!look) return null;
  const ids = new Set(look.items.map((i) => i.productId));
  return { look, products: DEV_TRYON_PRODUCTS.filter((p) => ids.has(p.id)) };
}

/** Backend try-on products, or the development set when the backend has none. */
export function withDevTryOnFallback(apiTryOn: Product[], isDev: boolean): Product[] {
  return apiTryOn.length || !isDev ? apiTryOn : DEV_TRYON_PRODUCTS;
}
