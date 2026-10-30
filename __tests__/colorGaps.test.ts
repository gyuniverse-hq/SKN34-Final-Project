import {
  amountToWear,
  buildColorQuery,
  deltaE,
  findColorGaps,
  naverShoppingUrl,
  recommendShades,
  type LookLine,
} from '@/lib/colorGaps';
import { DEMO_LOOKS } from '@/lib/devCatalog/demo';
import { DEV_TRYON_PRODUCTS } from '@/lib/devCatalog';
import type { MakeupState, Product } from '@/types';

const lipProduct = (id: string, hexes: string[]) =>
  ({
    id,
    brand: 'B',
    name: id,
    makeupZone: 'lip',
    texture: 'matte',
    shades: hexes.map((hex, i) => ({ id: `${id}-${i}`, name: `S${i}`, hex })),
  }) as unknown as Product;

const makeup = (hex: string): MakeupState => ({
  lip: { hex, intensity: 0.8, texture: 'velvet' },
  blush: null,
  eyeshadow: null,
  eyeliner: null,
  mascara: null,
  highlighter: null,
  contour: null,
});

describe('look color gaps', () => {
  it('reports nothing when the look product already wears the color', () => {
    const p = lipProduct('p', ['#B3202E']);
    const lines: LookLine[] = [{ product: p, shade: p.shades[0] }];
    expect(findColorGaps(makeup('#B5222F'), lines, [p])).toEqual([]);
  });

  it('wears a nearly identical catalog shade as is', () => {
    const p = lipProduct('p', ['#B3202E']);
    const [gap] = findColorGaps(makeup('#B8252F'), [], [p]);
    expect(gap.kind).toBe('nearest');
    if (gap.kind === 'nearest') {
      expect(gap.nearest.shade.id).toBe('p-0');
      expect(gap.amount).toBeNull();
    }
  });

  it('says to layer a lighter shade of the same hue to reach a deeper look color', () => {
    const p = lipProduct('p', ['#D1606B']);
    const [gap] = findColorGaps(makeup('#B3202E'), [], [p]);
    expect(gap.kind).toBe('nearest');
    if (gap.kind === 'nearest') {
      expect(gap.amount?.dir).toBe('thicker');
      expect(gap.amount && 'layers' in gap.amount ? gap.amount.layers : 0).toBeGreaterThanOrEqual(2);
    }
  });

  it('says to wear a deeper shade thinly to reach a lighter look color', () => {
    const p = lipProduct('p', ['#B3202E']);
    const [gap] = findColorGaps(makeup('#D1606B'), [], [p]);
    expect(gap.kind).toBe('nearest');
    if (gap.kind === 'nearest') expect(gap.amount).toEqual({ dir: 'thinner' });
  });

  it('searches the shopping site when no catalog shade is near or the hue is far off', () => {
    const blue = lipProduct('p', ['#2A4FA8']);
    const [far] = findColorGaps(makeup('#B3202E'), [], [blue]);
    expect(far).toMatchObject({ kind: 'search', query: '레드 립 벨벳' });
    const [empty] = findColorGaps(makeup('#B3202E'), [], []);
    expect(empty.kind).toBe('search');
  });

  it('ignores catalog shades of other zones', () => {
    const blush = { ...lipProduct('b', ['#B3202E']), makeupZone: 'blush' } as Product;
    const [gap] = findColorGaps(makeup('#B3202E'), [], [blush]);
    expect(gap.kind).toBe('search');
  });
});

describe('recommend shades', () => {
  it('puts the worn shade first and then nearer same-zone shades', () => {
    const close = lipProduct('close', ['#B3202E']);
    const far = lipProduct('far', ['#E8C4B8']);
    const worn = lipProduct('worn', ['#C25A6E']);
    const blush = { ...lipProduct('cheek', ['#B3202E']), makeupZone: 'blush' } as Product;
    const rows = recommendShades('#B3202E', 'lip', [far, close, worn, blush], {
      productId: 'worn',
      shadeId: 'worn-0',
    });
    expect(rows[0].product.id).toBe('worn');
    expect(rows[1].product.id).toBe('close');
    expect(rows.every((r) => r.product.makeupZone === 'lip')).toBe(true);
    expect(rows).toHaveLength(3);
  });
});

describe('color helpers', () => {
  it('measures zero between equal colors and builds Korean search keywords', () => {
    expect(deltaE('#C25A6E', '#C25A6E')).toBeCloseTo(0, 5);
    expect(buildColorQuery('mascara', '#121010', 'matte')).toBe('블랙 마스카라');
    expect(buildColorQuery('lip', '#C25A6E', 'glossy')).toContain('립 글로시');
  });

  it('gives no amount when the lightness barely differs, and a Naver Shopping search link', () => {
    expect(amountToWear('#B3202E', '#B5222F')).toBeNull();
    expect(naverShoppingUrl('레드 립')).toBe(
      'https://search.shopping.naver.com/search/all?query=%EB%A0%88%EB%93%9C%20%EB%A6%BD'
    );
  });
});

describe('a real look with a product missing from the shop', () => {
  const stage = DEMO_LOOKS.find((l) => l.id === 'demo-look-stage-red')!;
  const linesWithout = (productId: string): LookLine[] =>
    stage.items
      .filter((i) => i.productId !== productId)
      .flatMap((i) => {
        const product = DEV_TRYON_PRODUCTS.find((p) => p.id === i.productId);
        return product ? [{ product, shade: product.shades.find((sh) => sh.id === i.shadeId) }] : [];
      });

  it('has no gap when every product is there', () => {
    expect(findColorGaps(stage.makeup, linesWithout('none'), DEV_TRYON_PRODUCTS)).toEqual([]);
  });

  it('falls back to another catalog lip shade when the look lipstick is gone', () => {
    const gaps = findColorGaps(stage.makeup, linesWithout('demo-lip-velvet'), DEV_TRYON_PRODUCTS);
    expect(gaps.map((g) => g.zone)).toEqual(['lip']);
    expect(gaps[0].kind).toBe('nearest');
  });

  it('asks the shopping site when the shop has nothing near the color', () => {
    const noLips = DEV_TRYON_PRODUCTS.filter((p) => p.makeupZone !== 'lip');
    const gaps = findColorGaps(stage.makeup, linesWithout('demo-lip-velvet'), noLips);
    expect(gaps).toEqual([expect.objectContaining({ zone: 'lip', kind: 'search', query: '레드 립 벨벳' })]);
  });
});
