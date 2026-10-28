import { buildCartLines } from '@/hooks/useCartLines';
import { joinRecommendations } from '@/hooks/useSimilarRecommendations';
import { canTryOn, pickShade, resolveShade } from '@/lib/catalog';
import { findOffer, isSafeExternalUrl } from '@/lib/externalLink';
import { addCompareItem, MAX_COMPARE } from '@/store/compareStore';
import type { Product, ShoppingOffer } from '@/types';

function product(id: string, shades: string[], extra: Partial<Product> = {}): Product {
  return {
    id,
    brand: 'Brand',
    name: `Product ${id}`,
    nameKo: `제품 ${id}`,
    category: 'lip',
    makeupZone: 'lip',
    texture: 'matte',
    priceKRW: 10000,
    volume: '4g',
    shades: shades.map((s) => ({ id: s, name: `Shade ${s}`, hex: '#C0485A' })),
    description: '',
    keyIngredients: [],
    tags: [],
    imageUrl: '',
    searchKeyword: '',
    ...extra,
  };
}

describe('catalog availability', () => {
  it('resolves product + exact shade, and flags removed data', () => {
    const p = product('a', ['01', '02']);
    expect(resolveShade(p, '02')).toEqual({ availability: 'available', shade: p.shades[1] });
    expect(resolveShade(p, undefined)).toEqual({ availability: 'available' });
    expect(resolveShade(p, '99')).toEqual({ availability: 'shade_unavailable' });
    expect(resolveShade(undefined, '01')).toEqual({ availability: 'product_unavailable' });
  });

  it('falls back to the first shade for display and detects try-on support', () => {
    const p = product('a', ['01', '02']);
    expect(pickShade(p, '99')?.id).toBe('01');
    expect(canTryOn(p)).toBe(true);
    expect(canTryOn(product('b', [], { makeupZone: null, category: 'skincare' }))).toBe(false);
    expect(canTryOn(product('c', []))).toBe(false);
  });
});

describe('cart lines keep product + shade', () => {
  it('prices only available lines and keeps changed lines visible', () => {
    const lines = buildCartLines(
      [
        { productId: 'a', shadeId: '01', quantity: 2 },
        { productId: 'a', shadeId: '02', quantity: 1 },
        { productId: 'a', shadeId: '99', quantity: 1 },
        { productId: 'gone', shadeId: '01', quantity: 1 },
      ],
      [product('a', ['01', '02'])]
    );
    expect(lines.map((l) => [l.key, l.availability, l.lineTotal])).toEqual([
      ['a::01', 'available', 20000],
      ['a::02', 'available', 10000],
      ['a::99', 'shade_unavailable', 0],
      ['gone::01', 'product_unavailable', 0],
    ]);
    expect(lines[0].shade?.id).toBe('01');
  });
});

describe('compare list', () => {
  it('holds one entry per product and refuses more than the maximum', () => {
    let items = addCompareItem([], { productId: 'a', shadeId: '01' })!;
    items = addCompareItem(items, { productId: 'a', shadeId: '02' })!;
    expect(items).toEqual([{ productId: 'a', shadeId: '02' }]);
    for (let i = items.length; i < MAX_COMPARE; i++) items = addCompareItem(items, { productId: `p${i}` })!;
    expect(items).toHaveLength(MAX_COMPARE);
    expect(addCompareItem(items, { productId: 'extra' })).toBeNull();
  });
});

describe('recommendations', () => {
  it('joins matches with products and drops entries missing from the response', () => {
    const items = joinRecommendations({
      source: { productId: 'a', shadeId: '01', hex: '#C0485A', makeupZone: 'lip' },
      matches: [
        { productId: 'b', shadeId: '10', deltaE: 1.2, reasons: ['close_color'] },
        { productId: 'b', shadeId: '99', deltaE: 2, reasons: [] },
        { productId: 'missing', shadeId: '01', deltaE: 3, reasons: [] },
      ],
      products: [product('b', ['10'])],
    });
    expect(items.map((i) => [i.product.id, i.shade.id, i.deltaE, i.reasons])).toEqual([['b', '10', 1.2, ['close_color']]]);
    expect(joinRecommendations(undefined)).toEqual([]);
  });
});

describe('external links', () => {
  const offers: ShoppingOffer[] = [
    { title: 't', mallName: 'Mall', priceKRW: 1, imageUrl: '', link: 'https://shop.example/item/1' },
  ];

  it('allows plain https only', () => {
    expect(isSafeExternalUrl('https://shop.example/a')).toBe(true);
    expect(isSafeExternalUrl('http://shop.example/a')).toBe(false);
    expect(isSafeExternalUrl('javascript:alert(1)')).toBe(false);
    expect(isSafeExternalUrl('https://user:pass@shop.example/')).toBe(false);
    expect(isSafeExternalUrl('not a url')).toBe(false);
  });

  it("opens only a link from this product's offers", () => {
    expect(findOffer(offers, 'https://shop.example/item/1')).toBe(offers[0]);
    expect(findOffer(offers, 'https://evil.example/')).toBeUndefined();
    expect(findOffer(undefined, 'https://shop.example/item/1')).toBeUndefined();
  });
});
