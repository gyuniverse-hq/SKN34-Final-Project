import { inRankingCategory, orderCatalogProducts } from '@/lib/discovery';
import type { Product, ProductCategory } from '@/types';

function product(id: string, category: ProductCategory, tags: string[] = []): Product {
  return { id, category, tags } as Product;
}

describe('product rankings', () => {
  it('maps product IDs in server order regardless of catalog position or old tags', () => {
    const first = product('first', 'eye');
    const second = product('second', 'lip', ['rank:makeup:1']);
    const unranked = product('unranked', 'base', ['rank:makeup:2']);
    const catalog = new Map([second, unranked, first].map(item => [item.id, item]));

    expect(orderCatalogProducts(['first', 'second'], catalog)).toEqual([
      { product: first, rank: 1 },
      { product: second, rank: 2 },
    ]);
  });

  it('preserves server positions when resolving a filtered or partially loaded catalog', () => {
    const remaining = product('remaining', 'skincare');
    const catalog = new Map([[remaining.id, remaining]]);

    expect(orderCatalogProducts(['missing', 'remaining'], catalog)).toEqual([
      { product: remaining, rank: 2 },
    ]);
  });

  it('includes base and sun care in their respective browse categories', () => {
    expect(inRankingCategory(product('base', 'base'), 'makeup')).toBe(true);
    expect(inRankingCategory(product('sun', 'suncare'), 'skincare')).toBe(true);
    expect(inRankingCategory(product('tool', 'tool'), 'makeup')).toBe(false);
  });
});
