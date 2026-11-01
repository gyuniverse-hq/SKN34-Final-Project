import { matchCatalogProduct, normalizeCatalogText } from '@/lib/catalogMatch';
import type { Product } from '@/types';

const product: Product = {
  id: 'oy-a1',
  brand: '스킨푸드',
  name: '[기획] 스킨푸드 캐롯 카로틴 워터패드 60매',
  nameKo: '[기획] 스킨푸드 캐롯 카로틴 워터패드 60매',
  category: 'skincare',
  makeupZone: null,
  texture: 'satin',
  priceKRW: 18000,
  volume: '60',
  shades: [],
  description: '',
  keyIngredients: [],
  tags: ['oliveyoung', '스킨케어'],
  imageUrl: '',
  searchKeyword: '스킨푸드 캐롯',
};

describe('catalogMatch', () => {
  it('matches the same brand and a listed name contained in the catalog name', () => {
    expect(
      matchCatalogProduct({ brand: '스킨푸드', name: '캐롯 카로틴 워터패드' }, [product])?.id
    ).toBe('oy-a1');
  });

  it('does not match a different brand or a short label', () => {
    expect(matchCatalogProduct({ brand: '다른브랜드', name: '캐롯 카로틴 워터패드' }, [product])).toBeUndefined();
    expect(matchCatalogProduct({ brand: '렌즈미', name: '렌즈미' }, [product])).toBeUndefined();
  });

  it('strips punctuation for comparison', () => {
    expect(normalizeCatalogText('캐롯 카로틴-워터패드')).toBe(normalizeCatalogText('캐롯카로틴워터패드'));
  });
});
