import { inRankingCategory, rankedProducts } from '@/lib/discovery';
import type { Product, ProductCategory } from '@/types';

function product(id: string, category: ProductCategory, tags: string[] = []): Product {
  return { id, category, tags } as Product;
}

describe('product rankings', () => {
  it('shows only explicitly ranked products in the correct category and rank order', () => {
    const products = [
      product('second', 'lip', ['rank:makeup:2']),
      product('unranked', 'base'),
      product('first', 'eye', ['rank:makeup:1']),
      product('skin', 'suncare', ['rank:skincare:1']),
      product('wrong-category', 'skincare', ['rank:makeup:3']),
    ];
    expect(rankedProducts(products, 'makeup').map(({ product: p, rank }) => [p.id, rank])).toEqual([['first', 1], ['second', 2]]);
    expect(rankedProducts(products, 'skincare').map(({ product: p }) => p.id)).toEqual(['skin']);
    expect(inRankingCategory(products[1], 'makeup')).toBe(true);
  });

  it('does not invent ranks for missing, malformed, duplicated or conflicting tags', () => {
    const products = [
      product('no-rank', 'lip'),
      product('invalid', 'lip', ['rank:makeup:0']),
      product('duplicate-a', 'eye', ['rank:makeup:1']),
      product('duplicate-b', 'base', ['rank:makeup:1']),
      product('multiple', 'cheek', ['rank:makeup:2', 'rank:makeup:3']),
    ];
    expect(rankedProducts(products, 'makeup')).toEqual([]);
  });
});
