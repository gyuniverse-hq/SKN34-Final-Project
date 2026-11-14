import { DEMO_LOOK_AR } from '@/lib/demoLookAr';
import { DEMO_CELEBRITY_VIDEOS, DEMO_LOOK_PRODUCTS, DEMO_STYLE_LOOKS } from '@/lib/demoLookBundle';
import { FALSE_LASH_LOOKS } from '@/lib/falseLashLooks';
import { LOOK_LINERS, type LookLinerId } from '@/lib/linerLooks';
import { mascaraGeometry, type MascaraLookId } from '@/lib/mascaraLooks';
import { geometryFromStyle } from '@/lib/zoneRecipe';
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
    // 11-09: only 딸기 토끼상 shows attached bunches in its video; the others use a measured strand shape instead.
    expect(lashes).toHaveLength(1);
    for (const slot of lashes) {
      expect(slot.zone).toBe('mascara');
      expect(FALSE_LASH_LOOKS[slot.lashes!]).toBeDefined();
      expect(['video', 'recommended', 'measured']).toContain(slot.lashSource);
    }
  });

  test('every demo look carries a mascara shape read from its video close-ups and eye photo', () => {
    const style = (lookId: string) => DEMO_LOOK_AR[lookId].find((slot) => slot.zone === 'mascara')?.style as MascaraLookId;
    expect(style('ZAozXs-ZZik')).toBe('spiky_long');
    expect(style('4QR0tre9yBI')).toBe('short_light');
    expect(style('kWI7_DkDjZ0')).toBe('fine_short');
    expect(style('n5otfjJSSQc')).toBe('thin_lower');
    expect(style('e1gSkUdG6Bo')).toBe('long_fan');
    expect(style('fDqBPI1SaWY')).toBe('fine_dense');
    // the six shapes differ from each other: no look collapses into another one's lashes
    expect(new Set(Object.keys(DEMO_LOOK_AR).map((id) => JSON.stringify(mascaraGeometry(style(id)!)))).size).toBe(6);
  });

  test('the 설윤 lashes fan out a little and curl (the straight comb is gone); the fine looks are denser, the light ones sparser', () => {
    const fan = mascaraGeometry('long_fan');
    expect(fan.lashSweep).toBeGreaterThan(0);
    // 11-13: a wide 55° fan read as drawn comb teeth next to the finished frame; a soft fan stays.
    expect(fan.lashFan).toBeGreaterThanOrEqual(20);
    expect(fan.lashFan).toBeLessThanOrEqual(40);
    expect(fan.lashWidth).toBeLessThanOrEqual(1);
    expect(fan.lower).toBe(true);
    expect(mascaraGeometry('fine_dense').lashCount).toBeGreaterThan(fan.lashCount!);
    expect(mascaraGeometry('short_light').lashCount).toBeLessThan(fan.lashCount!);
    // 카리나·청초 show small pointed bunches in the eye photos (clump above the old 0.04 / 0.02)
    expect(mascaraGeometry('thin_lower').lashClump).toBeGreaterThanOrEqual(0.12);
    expect(mascaraGeometry('fine_short').lashClump).toBeGreaterThanOrEqual(0.1);
  });

  test('five demo looks carry the liner shape read from their eye photos; 청초 물복숭아 has no liner', () => {
    const liner = (lookId: string) => DEMO_LOOK_AR[lookId].find((slot) => slot.zone === 'eyeliner');
    expect(liner('kWI7_DkDjZ0')).toBeUndefined();
    const want: Record<string, LookLinerId> = {
      'ZAozXs-ZZik': 'strawberry_droop', '4QR0tre9yBI': 'yearend_brown', n5otfjJSSQc: 'karina_wing',
      e1gSkUdG6Bo: 'sullyoon_wing', fDqBPI1SaWY: 'winter_wing',
    };
    for (const [lookId, id] of Object.entries(want)) {
      expect({ lookId, style: liner(lookId)?.style }).toEqual({ lookId, style: id });
      expect(geometryFromStyle('eyeliner', id)).toEqual(LOOK_LINERS[id]);
    }
    // ranges the renderer draws as a real line (thickness / eye width, wing / eye width, degrees)
    for (const g of Object.values(LOOK_LINERS)) {
      expect(g.thickness).toBeGreaterThanOrEqual(0.04);
      expect(g.thickness).toBeLessThanOrEqual(0.15);
      expect(g.length).toBeGreaterThanOrEqual(0);
      expect(g.length).toBeLessThanOrEqual(0.45);
      expect(g.angle).toBeGreaterThanOrEqual(-15);
      expect(g.angle).toBeLessThanOrEqual(25);
    }
    // the five shapes differ, and 설윤 has the boldest, longest wing; 딸기 droops
    expect(new Set(Object.values(LOOK_LINERS).map((g) => JSON.stringify(g))).size).toBe(5);
    expect(LOOK_LINERS.sullyoon_wing.thickness!).toBeGreaterThan(LOOK_LINERS.karina_wing.thickness!);
    expect(LOOK_LINERS.sullyoon_wing.length!).toBeGreaterThan(LOOK_LINERS.karina_wing.length!);
    expect(LOOK_LINERS.strawberry_droop.angle).toBeLessThan(0);
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
