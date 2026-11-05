import type { Product, ProductQuery } from '@/types';
import { CONCERN_TO_TAGS, type CareTag } from '@/lib/skinFilters';

// Snapshot built from the Olive Young makeup v29 CSV. Skincare v1 and makeup v23 are not included.
// Required only when __DEV__ is true, so a production bundle does not ship this file.
const OY_CATALOG_PRODUCTS: Product[] = __DEV__
  ? (require('./oyCatalog.json') as { products: Product[] }).products
  : [];

/** Shop and product pages in development when the API catalog is empty. */
export const DEV_CATALOG_PRODUCTS: Product[] = OY_CATALOG_PRODUCTS;

/**
 * Try-on products for AR in development when the backend has none. Olive Young hex values
 * are the stored swatch colors (measureMethod "estimated"). Never used in production builds.
 */
export const DEV_TRYON_PRODUCTS: Product[] = OY_CATALOG_PRODUCTS.filter((p) => p.makeupZone);

/**
 * Backend try-on products. In development, zones the backend has no products for are filled from the development set
 * (a backend on an older seed served lip / blush / eyeshadow only, so the eyeliner, brow and foundation tabs were empty).
 */
export function withDevTryOnFallback(apiTryOn: Product[], isDev: boolean): Product[] {
  if (!isDev) return apiTryOn;
  if (!apiTryOn.length) return DEV_TRYON_PRODUCTS;
  const apiZones = new Set(apiTryOn.map((p) => p.makeupZone));
  const apiIds = new Set(apiTryOn.map((p) => p.id));
  const missing = DEV_TRYON_PRODUCTS.filter((p) => !apiZones.has(p.makeupZone) && !apiIds.has(p.id));
  return missing.length ? apiTryOn.concat(missing) : apiTryOn;
}

/** Local catalog when the API returns nothing. Concern filters use cosmetic care tags from product names. */
export function devCatalogProducts(params: ProductQuery = {}): Product[] {
  if (!__DEV__) return [];
  const q = (params.q ?? '').trim().toLowerCase();
  const careTags = params.concerns?.length
    ? new Set(params.concerns.flatMap((concern) => CONCERN_TO_TAGS[concern] ?? []))
    : null;
  return DEV_CATALOG_PRODUCTS.filter((product) => {
    if (params.category && product.category !== params.category) return false;
    if (careTags && !product.tags.some((tag) => careTags.has(tag as CareTag))) return false;
    if (!q) return true;
    return [product.name, product.nameKo, product.brand, product.searchKeyword].some((value) =>
      value.toLowerCase().includes(q)
    );
  });
}

export function devCatalogProduct(id: string): Product | undefined {
  if (!__DEV__) return undefined;
  return DEV_CATALOG_PRODUCTS.find((product) => product.id === id);
}
