import { DEV_CATALOG_PRODUCTS, DEV_TRYON_PRODUCTS, withDevTryOnFallback } from '@/lib/devCatalog';

const HEX = /^#[0-9A-F]{6}$/i;

describe('development try-on fallback', () => {
  it('uses Olive Young try-on products in development when the backend has none', () => {
    type P = { makeupZone?: string | null; shades: { hex: string }[] };
    const oyTryOn = DEV_CATALOG_PRODUCTS.filter((p: P) => p.makeupZone);
    expect(DEV_TRYON_PRODUCTS).toHaveLength(oyTryOn.length);
    expect(DEV_TRYON_PRODUCTS.every((p: P) => p.makeupZone)).toBe(true);
    expect(DEV_TRYON_PRODUCTS.every((p) => !p.id.startsWith('demo-'))).toBe(true);
    const lipShades = DEV_TRYON_PRODUCTS.filter((p: P) => p.makeupZone === 'lip').reduce(
      (n: number, p: P) => n + p.shades.length,
      0
    );
    expect(lipShades).toBeGreaterThanOrEqual(168);
    expect(DEV_TRYON_PRODUCTS.some((p: P) => p.shades.some((s) => HEX.test(s.hex)))).toBe(true);
    expect(withDevTryOnFallback([], true)).toBe(DEV_TRYON_PRODUCTS);
    expect(withDevTryOnFallback([], false)).toEqual([]);
    const full = ['lip', 'blush', 'eyeshadow', 'eyeliner', 'brow', 'foundation'].map(
      (zone) => DEV_TRYON_PRODUCTS.find((p) => p.makeupZone === zone)!
    );
    expect(withDevTryOnFallback(full, true)).toBe(full);
  });

  it('fills only the zones the backend has no products for, in development only', () => {
    // A backend on an older seed: lip / blush / eyeshadow, no eyeliner, brow or foundation.
    const api = DEV_TRYON_PRODUCTS.filter((p) => p.makeupZone === 'lip' || p.makeupZone === 'blush' || p.makeupZone === 'eyeshadow').slice(0, 3);
    const merged = withDevTryOnFallback(api, true);
    expect(merged.slice(0, api.length)).toEqual(api);
    for (const zone of ['eyeliner', 'brow', 'foundation'] as const) {
      expect(merged.some((p) => p.makeupZone === zone && p.shades.length > 0)).toBe(true);
    }
    const apiZones = new Set(api.map((p) => p.makeupZone));
    expect(merged.slice(api.length).every((p) => !apiZones.has(p.makeupZone))).toBe(true);
    expect(withDevTryOnFallback(api, false)).toBe(api);
  });
});
