import type { Product } from '@/types';

export type RankingCategory = 'makeup' | 'skincare';

export function inRankingCategory(product: Product, category: RankingCategory): boolean {
  return category === 'skincare'
    ? product.category === 'skincare' || product.category === 'suncare'
    : product.category === 'lip' || product.category === 'cheek' || product.category === 'eye' || product.category === 'base';
}

/** Preserve positions from the server when a product is missing from the current catalog results. */
export function orderCatalogProducts(productIds: readonly string[], productsById: ReadonlyMap<string, Product>) {
  const entries: { product: Product; rank: number }[] = [];
  productIds.forEach((id, index) => {
    const product = productsById.get(id);
    if (product) entries.push({ product, rank: index + 1 });
  });
  return entries;
}
