import { LOOKS } from '@/data/catalog/looks';
import { PRODUCTS } from '@/data/catalog/products';
import { STORES } from '@/data/catalog/stores';
import type { CelebLook, Product, ProductCategory } from '@/types';
import { isNaverConfigured, searchProductImage } from './naver';

export const CATEGORIES: ProductCategory[] = ['lip', 'cheek', 'eye', 'base', 'skincare', 'suncare'];

export interface ProductFilter {
  q?: string;
  category?: ProductCategory;
  ids?: string[];
}

export function isCategory(value: string | undefined): value is ProductCategory {
  return !!value && (CATEGORIES as string[]).includes(value);
}

export function filterProducts(products: Product[], filter: ProductFilter): Product[] {
  let list = products;
  if (filter.ids) {
    const wanted = new Set(filter.ids);
    list = list.filter((p) => wanted.has(p.id));
  }
  if (filter.category) {
    list = list.filter((p) => p.category === filter.category);
  }
  if (filter.q) {
    const terms = filter.q.toLowerCase().split(/\s+/).filter(Boolean);
    list = list.filter((p) => {
      const haystack = [p.brand, p.name, p.nameKo, p.description, ...p.tags, ...p.shades.map((s) => s.name)]
        .join(' ')
        .toLowerCase();
      return terms.every((t) => haystack.includes(t));
    });
  }
  return list;
}

// Naver Search API rejects bursts (HTTP 429), so cap concurrent upstream lookups.
const IMAGE_LOOKUP_CONCURRENCY = 3;

async function mapWithConcurrency<T, R>(items: T[], limit: number, fn: (item: T) => Promise<R>): Promise<R[]> {
  const results = new Array<R>(items.length);
  let next = 0;
  const workers = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) {
      const index = next++;
      results[index] = await fn(items[index]);
    }
  });
  await Promise.all(workers);
  return results;
}

/** Replace placeholder images with real product photos when Naver search is configured. */
async function withLiveImages(products: Product[]): Promise<Product[]> {
  if (!isNaverConfigured()) return products;
  return mapWithConcurrency(products, IMAGE_LOOKUP_CONCURRENCY, async (p) => {
    try {
      const imageUrl = await searchProductImage(p.searchKeyword);
      return imageUrl ? { ...p, imageUrl } : p;
    } catch {
      return p;
    }
  });
}

export async function listProducts(filter: ProductFilter) {
  return withLiveImages(filterProducts(PRODUCTS, filter));
}

export async function getProduct(id: string) {
  const product = PRODUCTS.find((p) => p.id === id);
  if (!product) return null;
  const [enriched] = await withLiveImages([product]);
  return enriched;
}

export function getProductSync(id: string) {
  return PRODUCTS.find((p) => p.id === id) ?? null;
}

export function listLooks(): CelebLook[] {
  return LOOKS;
}

export async function getLookWithProducts(id: string) {
  const look = LOOKS.find((l) => l.id === id);
  if (!look) return null;
  const products = await listProducts({ ids: look.items.map((i) => i.productId) });
  return { look, products };
}

export function listStores() {
  return STORES.filter((s) => s.pickupAvailable);
}
