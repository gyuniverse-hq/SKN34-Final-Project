import type { Product } from '@/types';

export type RankingCategory = 'makeup' | 'skincare';

export function inRankingCategory(product: Product, category: RankingCategory): boolean {
  return category === 'skincare'
    ? product.category === 'skincare' || product.category === 'suncare'
    : product.category === 'lip' || product.category === 'cheek' || product.category === 'eye' || product.category === 'base';
}

/** Only an explicit catalog tag establishes rank; ordinary catalog order is never a popularity ranking. */
export function rankedProducts(products: Product[], category: RankingCategory): { product: Product; rank: number }[] {
  const seen = new Map<number, { product: Product; rank: number }[]>();
  for (const product of products) {
    if (!inRankingCategory(product, category)) continue;
    const tags = product.tags.map((tag) => new RegExp(`^rank:${category}:([1-9][0-9]{0,3})$`).exec(tag)).filter((match) => match !== null);
    if (tags.length !== 1) continue;
    const rank = Number(tags[0]![1]);
    const entries = seen.get(rank) ?? [];
    entries.push({ product, rank });
    seen.set(rank, entries);
  }
  return [...seen.values()].filter((entries) => entries.length === 1).map((entries) => entries[0]).sort((a, b) => a.rank - b.rank);
}
