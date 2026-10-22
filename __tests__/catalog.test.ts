import { LOOKS } from '@/data/catalog/looks';
import { PRODUCTS } from '@/data/catalog/products';
import { STORES } from '@/data/catalog/stores';
import { filterProducts, isCategory } from '@/server/services/catalogService';
import type { Product } from '@/types';

const HEX = /^#[0-9A-F]{6}$/i;

describe('catalog data integrity', () => {
  it('has unique product ids', () => {
    const ids = PRODUCTS.map((p) => p.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('has valid shades and try-on zones', () => {
    for (const p of PRODUCTS) {
      expect(p.nameKo.length).toBeGreaterThan(0);
      expect(p.priceKRW).toBeGreaterThan(0);
      expect(new Set(p.shades.map((s) => s.id)).size).toBe(p.shades.length);
      for (const s of p.shades) expect(s.hex).toMatch(HEX);
      if (p.makeupZone) expect(p.shades.length).toBeGreaterThan(0);
    }
  });

  it('only references existing products and shades in looks', () => {
    for (const look of LOOKS) {
      for (const item of look.items) {
        const product = PRODUCTS.find((p) => p.id === item.productId);
        expect(product).toBeDefined();
        if (item.shadeId) {
          expect(product!.shades.some((s) => s.id === item.shadeId)).toBe(true);
        }
      }
      for (const zone of [look.makeup.lip, look.makeup.blush, look.makeup.eyeshadow]) {
        if (zone) {
          expect(zone.hex).toMatch(HEX);
          expect(zone.intensity).toBeGreaterThanOrEqual(0);
          expect(zone.intensity).toBeLessThanOrEqual(1);
        }
      }
    }
  });

  it('has stores with valid coordinates', () => {
    for (const s of STORES) {
      expect(s.lat).toBeGreaterThan(33);
      expect(s.lat).toBeLessThan(39);
      expect(s.lng).toBeGreaterThan(124);
      expect(s.lng).toBeLessThan(132);
    }
  });
});

function fixture(overrides: Partial<Product> & Pick<Product, 'id'>): Product {
  return {
    brand: 'Brand',
    name: 'Product',
    nameKo: '제품',
    category: 'lip',
    makeupZone: 'lip',
    texture: 'matte',
    priceKRW: 10000,
    volume: '4g',
    shades: [],
    description: '',
    keyIngredients: [],
    tags: [],
    imageUrl: '',
    searchKeyword: '',
    ...overrides,
  };
}

const SAMPLE: Product[] = [
  fixture({ id: 'tint', brand: 'rom&nd', name: 'Juicy Tint', shades: [{ id: '06', name: '06 Figfig', hex: '#B5555E' }] }),
  fixture({ id: 'cushion', category: 'base', makeupZone: null, name: 'Cushion', nameKo: '쿠션 파운데이션' }),
  fixture({ id: 'toner', category: 'skincare', makeupZone: null, name: 'Toner' }),
];

describe('filterProducts', () => {
  it('filters by category', () => {
    expect(filterProducts(SAMPLE, { category: 'lip' }).map((p) => p.id)).toEqual(['tint']);
  });

  it('matches every search term across brand, name, Korean name and shades', () => {
    expect(filterProducts(SAMPLE, { q: 'romand figfig' })).toEqual([]);
    expect(filterProducts(SAMPLE, { q: 'rom&nd figfig' }).map((p) => p.id)).toEqual(['tint']);
    expect(filterProducts(SAMPLE, { q: '쿠션' }).map((p) => p.id)).toEqual(['cushion']);
  });

  it('filters by ids', () => {
    expect(filterProducts(SAMPLE, { ids: ['toner', 'nope'] })).toHaveLength(1);
  });

  it('validates categories', () => {
    expect(isCategory('lip')).toBe(true);
    expect(isCategory('shoes')).toBe(false);
    expect(isCategory(undefined)).toBe(false);
  });
});
