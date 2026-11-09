import { DEMO_LOOK_AR } from '@/lib/demoLookAr';
import { DEMO_CELEBRITY_VIDEOS, DEMO_LOOK_PRODUCTS, DEMO_STYLE_LOOKS } from '@/lib/demoLookBundle';
import { FALSE_LASH_LOOKS } from '@/lib/falseLashLooks';
import type { Product } from '@/types';

const nodeFs = jest.requireActual('fs') as { readFileSync: (path: string, encoding: string) => string };
const catalogs: Record<string, Product[]> = {
  bundle: DEMO_LOOK_PRODUCTS,
  devCatalog: JSON.parse(nodeFs.readFileSync('lib/devCatalog/oyCatalog.json', 'utf8')).products,
  seed: JSON.parse(nodeFs.readFileSync('backend/api/seed/catalog.json', 'utf8')).products,
};

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
}

const DARK_ZONES = new Set(['eyeliner', 'mascara', 'brow']);

describe.each(Object.entries(catalogs))('demo look slots resolve in %s', (_name, products) => {
  const byId = new Map(products.map((p) => [p.id, p]));
  const slots = Object.entries(DEMO_LOOK_AR).flatMap(([lookId, list]) => list.map((slot) => ({ lookId, slot })));

  test.each(slots.map(({ lookId, slot }) => [`${lookId}/${slot.zone}`, slot] as const))('%s', (_label, slot) => {
    const product = byId.get(slot.productId);
    expect(product).toBeDefined();
    expect(product!.makeupZone).toBe(slot.zone);
    expect(product!.texture).toBeTruthy();
    const shade = product!.shades.find((s) => s.id === slot.shadeId);
    expect(shade).toBeDefined();
    expect(shade!.hex).toMatch(/^#[0-9A-F]{6}$/i);
    expect(shade!.hex.toUpperCase()).not.toBe('#FFFFFF');
    if (DARK_ZONES.has(slot.zone)) expect(luminance(shade!.hex)).toBeLessThan(0.8);
    if (slot.to) {
      const toShade = byId.get(slot.to.productId)?.shades.find((s) => s.id === slot.to!.shadeId);
      expect(toShade?.hex).toMatch(/^#[0-9A-F]{6}$/i);
    }
  });
});

describe('demo look coverage', () => {
  test('every look paints lip, eyeshadow, blush and mascara and names its video products', () => {
    for (const [lookId, list] of Object.entries(DEMO_LOOK_AR)) {
      const zones = list.map((slot) => slot.zone);
      for (const zone of ['lip', 'eyeshadow', 'blush', 'mascara']) {
        expect({ lookId, zone, has: zones.includes(zone as never) }).toEqual({ lookId, zone, has: true });
      }
      expect(new Set(zones).size).toBe(zones.length);
      for (const slot of list) expect(slot.video?.length).toBeGreaterThan(0);
    }
  });

  test('false lashes only ride on mascara slots and use known presets', () => {
    const lashes = Object.values(DEMO_LOOK_AR).flat().filter((slot) => slot.lashes);
    expect(lashes).toHaveLength(6);
    for (const slot of lashes) {
      expect(slot.zone).toBe('mascara');
      expect(FALSE_LASH_LOOKS[slot.lashes!]).toBeDefined();
      expect(['video', 'recommended']).toContain(slot.lashSource);
    }
  });

  test('looks whose video lists no false lashes are marked recommended, never video', () => {
    const recommended = Object.entries(DEMO_LOOK_AR)
      .filter(([, list]) => list.some((slot) => slot.lashSource === 'recommended'))
      .map(([lookId]) => lookId)
      .sort();
    expect(recommended).toEqual(['4QR0tre9yBI', 'ZAozXs-ZZik']);
    const mascaraLashes = (lookId: string) => DEMO_LOOK_AR[lookId].find((slot) => slot.zone === 'mascara')?.lashes;
    expect(mascaraLashes('ZAozXs-ZZik')).toBe('upper');
    expect(mascaraLashes('4QR0tre9yBI')).toBe('upper_dense');
  });

  test('the false lash set is the seven YouCam eyelash types', () => {
    expect(Object.keys(FALSE_LASH_LOOKS).sort()).toEqual(
      ['artistic', 'natural', 'upper', 'upper_dense', 'upper_lower', 'winged', 'wispies'],
    );
    expect(FALSE_LASH_LOOKS.upper_lower.some((cl) => cl.edge === 'lower')).toBe(true);
    expect(FALSE_LASH_LOOKS.upper.every((cl) => cl.edge === 'upper')).toBe(true);
  });

  test('false lash presets stay inside the renderer ranges', () => {
    for (const clusters of Object.values(FALSE_LASH_LOOKS)) {
      for (const cl of clusters) {
        expect(cl.u).toBeGreaterThan(0);
        expect(cl.u).toBeLessThanOrEqual(1);
        expect(cl.mm).toBeGreaterThanOrEqual(3);
        expect(cl.mm).toBeLessThanOrEqual(16);
        expect(cl.strands).toBeGreaterThanOrEqual(1);
        expect(cl.strands).toBeLessThanOrEqual(8);
        expect(cl.converge).toBeGreaterThanOrEqual(0);
        expect(cl.converge).toBeLessThanOrEqual(1);
      }
    }
  });
});

describe('demo look bundle (shipped in the app, no network)', () => {
  const seed = new Map((JSON.parse(nodeFs.readFileSync('backend/api/seed/catalog.json', 'utf8')).products as Product[]).map((p) => [p.id, p]));

  test('bundled shades are the served catalog values (re-run scripts/data/build_demo_look_bundle.py if this fails)', () => {
    for (const product of DEMO_LOOK_PRODUCTS) {
      const served = seed.get(product.id)!;
      expect({ id: product.id, zone: product.makeupZone, texture: product.texture })
        .toEqual({ id: served.id, zone: served.makeupZone, texture: served.texture });
      for (const shade of product.shades) {
        expect({ id: product.id, shade: shade.id, hex: shade.hex })
          .toEqual({ id: product.id, shade: shade.id, hex: served.shades.find((s) => s.id === shade.id)?.hex });
      }
    }
  });

  test('the six look entries are the backend entries', () => {
    const served = [
      ...JSON.parse(nodeFs.readFileSync('backend/api/app/catalog_data/celebrity_videos.json', 'utf8')),
      ...JSON.parse(nodeFs.readFileSync('backend/api/app/catalog_data/style_looks.json', 'utf8')),
    ] as { id: string }[];
    const bundled = [...DEMO_CELEBRITY_VIDEOS, ...DEMO_STYLE_LOOKS];
    expect(bundled.map((item) => item.id).sort()).toEqual(Object.keys(DEMO_LOOK_AR).sort());
    for (const item of bundled) expect(item).toEqual(served.find((entry) => entry.id === item.id));
  });
});
