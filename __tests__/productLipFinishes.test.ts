import { FACE_TRACKER_HTML } from '@/components/ar/faceTrackerHtml';
import {
  PRODUCT_LIP_FINISHES,
  productLipFinishFor,
  productLipFinishKey,
} from '@/lib/productLipFinishes';

const MURMUR = {
  productId: 'oy-a000000148167',
  shadeId: 'a000000148167-017',
} as const;

function rendererProfileHarness() {
  const start = FACE_TRACKER_HTML.indexOf('  const MATERIALS = {');
  const end = FACE_TRACKER_HTML.indexOf('  // Brow: product hex', start);
  const materialStart = FACE_TRACKER_HTML.indexOf('    function material(zone) {');
  const materialEnd = FACE_TRACKER_HTML.indexOf('\n\n    return {', materialStart);
  if (start < 0 || end < 0 || materialStart < 0 || materialEnd < 0) throw new Error('renderer helpers not found');
  return new Function(`
    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
    function clamp01(v) { return clamp(Number(v) || 0, 0, 1); }
    ${FACE_TRACKER_HTML.slice(start, end)}
    ${FACE_TRACKER_HTML.slice(materialStart, materialEnd)}
    return { MATERIALS, material, profileCoverage };
  `)() as {
    MATERIALS: Record<string, Record<string, number>>;
    material(zone: object | null): Record<string, number>;
    profileCoverage(zone: object | null, original: number): number;
  };
}

describe('product lip finishes', () => {
  it('registers only the 3CE Murmuring soft-matte override for now', () => {
    expect(Object.keys(PRODUCT_LIP_FINISHES)).toEqual([productLipFinishKey(MURMUR.productId, MURMUR.shadeId)]);
    expect(
      productLipFinishFor({ id: MURMUR.productId, makeupZone: 'lip' }, { id: MURMUR.shadeId }),
    ).toMatchObject({
      coverageMultiplier: 0.9,
      material: { a1: 0.52, glossScale: 0.2, opacity: 0.92 },
    });
    expect(
      productLipFinishFor({ id: MURMUR.productId, makeupZone: 'blush' }, { id: MURMUR.shadeId }),
    ).toBeUndefined();
    expect(
      productLipFinishFor({ id: MURMUR.productId, makeupZone: 'lip' }, { id: 'other-shade' }),
    ).toBeUndefined();
  });

  it('applies Murmuring material overrides without mutating matte defaults or changing hex path', () => {
    const h = rendererProfileHarness();
    const original = { ...h.MATERIALS.matte };
    const finish = productLipFinishFor({ id: MURMUR.productId, makeupZone: 'lip' }, { id: MURMUR.shadeId })!;
    const material = h.material({ texture: 'matte', applicationProfile: finish });
    expect(material).toMatchObject({
      a1: 0.52,
      roughness: 0.88,
      specular: 0.22,
      detail: 1.05,
      translucent: 0.05,
      glossScale: 0.2,
      overlay: 0.12,
      opacity: 0.92,
      cavity: 1.6,
    });
    expect(h.profileCoverage({ applicationProfile: finish }, 0.7)).toBeCloseTo(0.63, 5);
    expect(h.MATERIALS.matte).toEqual(original);
    expect(h.material({ texture: 'matte' })).toBe(h.MATERIALS.matte);
  });
});
