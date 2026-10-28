import { DEMO_TAG } from '@/constants/demo';
import { DEMO_LOOKS, DEMO_PRODUCTS, DEMO_SHOP_LIP } from '@/lib/devCatalog/demo';
import { MAKEUP_ZONES } from '@/store/makeupStore';

const HEX = /^#[0-9A-F]{6}$/i;

describe('demo catalog (development only)', () => {
  it('marks every demo product and look as demo', () => {
    for (const p of DEMO_PRODUCTS) {
      expect(p.tags).toContain(DEMO_TAG);
      expect(p.nameKo).toContain('실제 제품 아님');
    }
    for (const look of DEMO_LOOKS) {
      expect(look.tags).toContain(DEMO_TAG);
      expect(look.inspiration).toMatch(/not real products/);
    }
  });

  it('offers demo colors for every try-on zone', () => {
    for (const zone of MAKEUP_ZONES) {
      expect(DEMO_PRODUCTS.some((p) => p.makeupZone === zone && p.shades.every((sh) => HEX.test(sh.hex)))).toBe(true);
    }
  });

  it('offers the five demo lip colors in all seven textures', () => {
    const lips = DEMO_PRODUCTS.filter((p) => /^demo-lip-(matte|velvet|cream|satin|sheer|glossy|shimmer)$/.test(p.id));
    expect(new Set(lips.map((p) => p.texture)).size).toBe(7);
    for (const p of lips) expect(p.shades.map((s) => s.id)).toEqual(['demo-rose', 'demo-coral', 'demo-red', 'demo-berry', 'demo-nude']);
  });

  it('has valid shades and unique ids', () => {
    expect(new Set(DEMO_PRODUCTS.map((p) => p.id)).size).toBe(DEMO_PRODUCTS.length);
    for (const p of DEMO_PRODUCTS) for (const s of p.shades) expect(s.hex).toMatch(HEX);
  });

  it('has one shop lip for the product-page AR check', () => {
    expect(DEMO_SHOP_LIP.id).toBe('demo-lip-tryon');
    expect(DEMO_SHOP_LIP.makeupZone).toBe('lip');
    expect(DEMO_SHOP_LIP.shades).toHaveLength(1);
    expect(DEMO_SHOP_LIP.shades[0].hex).toMatch(HEX);
    expect(DEMO_PRODUCTS.some((p) => p.id === 'demo-lip-tryon')).toBe(true);
  });

  it('builds looks only from demo shades, with the same colors and textures', () => {
    expect(DEMO_LOOKS).toHaveLength(7);
    for (const look of DEMO_LOOKS) {
      for (const item of look.items) {
        const product = DEMO_PRODUCTS.find((p) => p.id === item.productId);
        expect(product).toBeDefined();
        const shade = product!.shades.find((s) => s.id === item.shadeId);
        expect(shade).toBeDefined();
        const zone = look.makeup[product!.makeupZone!];
        expect(zone?.hex).toBe(shade!.hex);
        expect(zone?.texture).toBe(product!.texture);
      }
    }
  });
});

describe('gal demo look', () => {
  const gal = DEMO_LOOKS.find((l) => l.id === 'demo-look-gal-classic')!;

  it('sets every zone the gal look is made of, with a two-tone shadow and a long wing liner', () => {
    expect(gal).toBeDefined();
    for (const zone of ['lip', 'eyeshadow', 'eyeliner', 'mascara', 'highlighter'] as const) expect(gal.makeup[zone]).toBeTruthy();
    expect(gal.makeup.eyeshadow?.hexTo).toMatch(HEX);
    expect(gal.makeup.eyeliner?.geometry?.length).toBeGreaterThan(0.18); // longer than the default wing
    expect(gal.makeup.mascara?.geometry?.thickness).toBeGreaterThan(1); // denser than the default
  });

  it('keeps out what the spec rules out: no skin-covering base and no lip drawn outside the lips', () => {
    expect(gal.makeup.contour ?? null).toBeNull();
    expect(JSON.stringify(gal)).not.toMatch(/overlip|tan|foundation/i);
    expect(gal.inspiration).not.toMatch(/[가-힣]/); // concept label only, never a person's name (1-6)
  });

  it('is served in development as a look with its products, and only for demo ids', () => {
    const { devLookDetail, DEV_LOOKS } = jest.requireActual('@/lib/devCatalog');
    expect(DEV_LOOKS).toBe(DEMO_LOOKS);
    const detail = devLookDetail('demo-look-gal-classic');
    expect(detail.look.id).toBe('demo-look-gal-classic');
    expect(detail.products.map((p: { id: string }) => p.id).sort()).toEqual(gal.items.map((i) => i.productId).sort());
    expect(devLookDetail('not-a-demo-look')).toBeNull();
  });
});

describe('retro and semi gal demo look', () => {
  const semi = DEMO_LOOKS.find((l) => l.id === 'demo-look-semi-gyaru-retro')!;

  it('sets lip with an overlip, a two-tone shadow with an inner pearl, a long liner, full lashes, named highlighter areas and contour', () => {
    expect(semi).toBeDefined();
    for (const zone of ['lip', 'eyeshadow', 'eyeliner', 'mascara', 'highlighter', 'contour'] as const) expect(semi.makeup[zone]).toBeTruthy();
    const lip = semi.makeup.lip!.geometry!;
    expect(lip.overlip).toBeGreaterThan(0);
    expect(lip.overlip).toBeLessThanOrEqual(0.06);
    expect(lip.peakOverdraw).toBeLessThanOrEqual(0.05);
    expect(lip.centerHighlight).toBeLessThanOrEqual(0.3);
    expect(semi.makeup.eyeshadow?.geometry?.innerPoint?.hex).toMatch(HEX);
    expect(semi.makeup.eyeshadow?.hexTo).toMatch(HEX);
    expect(semi.makeup.eyeliner?.geometry?.length).toBeGreaterThan(0.18);
    expect(semi.makeup.mascara?.geometry?.lower).toBe(true);
    expect(semi.makeup.highlighter?.geometry?.areas).toEqual(['forehead', 'nose_bridge', 'under_eye']);
    expect(semi.tags).toEqual(expect.arrayContaining(['Y2K', 'festival', 'photoshoot', 'bold']));
  });

  it('adds no skin-covering base (tanning waits for a base zone) and no person name', () => {
    expect(Object.keys(semi.makeup)).not.toContain('base');
    expect(JSON.stringify(semi)).not.toMatch(/foundation|tanning/i);
    expect(semi.inspiration).not.toMatch(/[가-힣]/);
  });

  it('is served in development with all its products', () => {
    const { devLookDetail } = jest.requireActual('@/lib/devCatalog');
    const detail = devLookDetail('demo-look-semi-gyaru-retro');
    expect(detail.products.map((p: { id: string }) => p.id).sort()).toEqual(semi.items.map((i) => i.productId).sort());
  });
});

describe('soft peach coral demo look', () => {
  const peach = DEMO_LOOKS.find((l) => l.id === 'demo-look-soft-peach-coral')!;

  it('shares one peach coral between the lids and the cheeks, linked so a product swap carries over', () => {
    expect(peach).toBeDefined();
    expect(peach.colorLinks).toEqual([{ zones: ['eyeshadow', 'blush'], hex: '#F4A78A', followOnChange: true }]);
    expect(peach.makeup.blush?.hex).toBe(peach.colorLinks![0].hex);
    expect(peach.makeup.eyeshadow?.hex).toBe(peach.colorLinks![0].hex);
  });

  it('keeps the look light: sheer tint and blush, particle-free shimmer, short liner, no lower lashes, no base', () => {
    expect(peach.makeup.lip?.texture).toBe('sheer');
    expect(peach.makeup.blush?.texture).toBe('sheer');
    expect(peach.makeup.blush?.geometry?.blushPlacement).toBe('apple');
    expect(peach.makeup.eyeshadow?.geometry?.sparkle).toBe(0);
    expect(peach.makeup.eyeshadow?.geometry?.pearl).toBeGreaterThan(0);
    expect(peach.makeup.eyeliner?.geometry?.length).toBeLessThan(0.18); // shorter than the default wing
    expect(peach.makeup.mascara?.geometry?.lower).toBe(false);
    expect(peach.makeup.highlighter?.geometry?.areas).toEqual(['nose_bridge', 'under_eye']);
    expect(Object.keys(peach.makeup)).not.toContain('base');
    expect(peach.tags).toEqual(expect.arrayContaining(['spring', 'summer', 'date', 'selfie', 'natural']));
  });
});

describe('snake-eye idol demo look', () => {
  const idol = DEMO_LOOKS.find((l) => l.id === 'demo-look-snake-eye-idol')!;

  it('wears an upturned long wing, a semi-smoky lower lash line, lower lashes and a high under-eye flush', () => {
    expect(idol).toBeDefined();
    expect(idol.makeup.eyeliner?.geometry?.length).toBeGreaterThan(0.18); // longer than the default wing
    expect(idol.makeup.eyeliner?.geometry?.angle).toBeGreaterThan(15); // and lifted more
    expect(idol.makeup.eyeshadow?.hexTo).toBeDefined();
    expect(idol.makeup.mascara?.geometry?.lower).toBe(true);
    expect(idol.makeup.blush?.geometry?.blushPlacement).toBe('under_eye');
    expect(idol.makeup.lip?.texture).toBe('glossy');
  });

  it('names a concept, never a real person (AR_SPEC 1-6)', () => {
    const text = [idol.title, idol.inspiration, idol.description, idol.tutorialQuery].join(' ').toLowerCase();
    expect(text).not.toMatch(/karina|aespa|카리나|에스파|whiplash/);
  });
});

describe('development try-on fallback', () => {
  it('uses bundled colors only in development when the backend has no try-on products', () => {
    const { DEV_TRYON_PRODUCTS, withDevTryOnFallback } = jest.requireActual('@/lib/devCatalog');
    const { OLIVEYOUNG_PRODUCTS } = jest.requireActual('@/lib/devCatalog/oliveyoung');
    type P = { makeupZone?: string | null; shades: unknown[] };
    // Every Olive Young try-on product plus every demo product; products without a zone are left out.
    const oyTryOn = OLIVEYOUNG_PRODUCTS.filter((p: P) => p.makeupZone);
    expect(DEV_TRYON_PRODUCTS).toHaveLength(oyTryOn.length + DEMO_PRODUCTS.length);
    expect(DEV_TRYON_PRODUCTS.every((p: P) => p.makeupZone)).toBe(true);
    const lipShades = DEV_TRYON_PRODUCTS.filter((p: P) => p.makeupZone === 'lip').reduce((n: number, p: P) => n + p.shades.length, 0);
    expect(lipShades).toBeGreaterThanOrEqual(168);
    expect(withDevTryOnFallback([], true)).toBe(DEV_TRYON_PRODUCTS);
    expect(withDevTryOnFallback([], false)).toEqual([]);
    const api = [DEV_TRYON_PRODUCTS[0]];
    expect(withDevTryOnFallback(api, true)).toBe(api);
  });
});
