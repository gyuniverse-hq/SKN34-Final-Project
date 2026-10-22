import { isNaverConfigured, searchProductImage } from '@/server/clients/naverClient';
import { mapWithConcurrency } from '@/server/lib/concurrency';
import {
  findAllLooks,
  findAllProducts,
  findAllStores,
  findLookById,
  findProductById,
} from '@/server/repositories/catalogRepository';
import type { Product, ProductCategory } from '@/types';

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
  return withLiveImages(filterProducts(await findAllProducts(), filter));
}

export async function getProduct(id: string) {
  const product = await findProductById(id);
  if (!product) return null;
  const [enriched] = await withLiveImages([product]);
  return enriched;
}

export function listLooks() {
  return findAllLooks();
}

export async function getLookWithProducts(id: string) {
  const look = await findLookById(id);
  if (!look) return null;
  const products = await listProducts({ ids: look.items.map((i) => i.productId) });
  return { look, products };
}

export async function listStores() {
  return (await findAllStores()).filter((s) => s.pickupAvailable);
}
