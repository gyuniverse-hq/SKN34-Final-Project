import { FACE_TRACKER_HTML } from '@/components/ar/faceTrackerHtml';
import { applicationProfileFor, lookApplicationProfileFor, validatedApplicationProfile, validatedLookApplicationProfile } from '@/lib/applicationProfiles';
import type { ApplicationProfile, LookApplicationProfile } from '@/types';

const evidence: ApplicationProfile = {
  source: 'video-fit', videoId: 'example', fitFrameSeconds: 10, validationFrameSeconds: 20, validationView: 'different-angle',
  fitErrorBefore: 10, fitErrorAfter: 8, validationErrorBefore: 12, validationErrorAfter: 9,
  overrides: { material: { a1: 0.4 }, coverageMultiplier: 0.8 },
};

const lookEvidence: LookApplicationProfile = {
  source: 'video-fit', videoId: '4QR0tre9yBI', fitFrame: 'final.png', validationFrame: 'left.png', validationView: 'left',
  fitErrorBefore: 10, fitErrorAfter: 8, validationErrorBefore: 12, validationErrorAfter: 9,
  overrides: { coverageMultiplier: 0.8 }, geometry: { blushSize: 0.9 },
};

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
    return { MATERIALS, SHADOW_FINISHES, material, shadowFinish, profileCoverage };
  `)() as {
    MATERIALS: Record<string, Record<string, number>>;
    SHADOW_FINISHES: Record<string, Record<string, number>>;
    material(zone: object | null): Record<string, number>;
    shadowFinish(zone: object | null): Record<string, number>;
    profileCoverage(zone: object | null, original: number): number;
  };
}

describe('application profile evidence', () => {
  it('ships no unvalidated video-derived profiles', () => {
    expect(applicationProfileFor('oy-a000000229303', '03')).toBeUndefined();
    expect(applicationProfileFor('unknown', 'unknown')).toBeUndefined();
  });

  it('requires distinct frames and improvements in fitting and validation', () => {
    expect(validatedApplicationProfile(evidence)).toEqual(evidence.overrides);
    expect(validatedApplicationProfile({ ...evidence, fitErrorAfter: 10 })).toBeUndefined();
    expect(validatedApplicationProfile({ ...evidence, validationErrorAfter: 12 })).toBeUndefined();
    expect(validatedApplicationProfile({ ...evidence, validationFrameSeconds: 10 })).toBeUndefined();
    expect(validatedApplicationProfile({ ...evidence, validationView: 'same-angle' as 'different-angle' })).toBeUndefined();
    expect(validatedApplicationProfile({ ...evidence, fitErrorAfter: NaN })).toBeUndefined();
  });

  it('requires a distinct scene and improvement for look profiles', () => {
    expect(lookApplicationProfileFor('4QR0tre9yBI', 'blush')).toBeUndefined();
    expect(validatedLookApplicationProfile(lookEvidence)).toEqual(lookEvidence);
    expect(validatedLookApplicationProfile({ ...lookEvidence, validationView: 'open' })).toEqual({ ...lookEvidence, validationView: 'open' });
    expect(validatedLookApplicationProfile({ ...lookEvidence, validationFrame: 'final.png' })).toBeUndefined();
    expect(validatedLookApplicationProfile({ ...lookEvidence, fitErrorAfter: 10 })).toBeUndefined();
    expect(validatedLookApplicationProfile({ ...lookEvidence, validationErrorAfter: 12 })).toBeUndefined();
    expect(validatedLookApplicationProfile({ ...lookEvidence, validationView: 'same-angle' as 'left' })).toBeUndefined();
    expect(validatedLookApplicationProfile(lookEvidence, 'lip')).toBeUndefined();
    const lip = { ...lookEvidence, lipOpenValidation: { frame: 'open.png', errorBefore: 10, errorAfter: 8 } };
    expect(validatedLookApplicationProfile(lip, 'lip')).toEqual(lip);
    expect(validatedLookApplicationProfile({ ...lip, lipOpenValidation: { ...lip.lipOpenValidation, errorAfter: 10 } }, 'lip')).toBeUndefined();
    expect(validatedLookApplicationProfile({ ...lip, validationView: 'open' }, 'lip')).toBeUndefined();
  });
});

describe('application profile renderer controls', () => {
  it('returns the original texture and finish objects and coverage when no profile exists', () => {
    const h = rendererProfileHarness();
    for (const texture of ['matte', 'velvet', 'cream', 'satin', 'sheer', 'glossy', 'shimmer']) {
      expect(h.material({ texture })).toBe(h.MATERIALS[texture]);
    }
    expect(h.shadowFinish({ texture: 'shimmer' })).toBe(h.SHADOW_FINISHES.shimmer);
    expect(h.shadowFinish({ texture: 'matte', geometry: { shadowFinish: 'glitter' } })).toBe(h.SHADOW_FINISHES.glitter);
    for (const value of [0, 0.123456789, 0.9, 1]) expect(h.profileCoverage({ texture: 'matte' }, value)).toBe(value);
  });

  it('bounds explicit controls, preserves unspecified values and never mutates the defaults', () => {
    const h = rendererProfileHarness();
    const original = { ...h.MATERIALS.matte };
    const material = h.material({ texture: 'matte', applicationProfile: { material: { a1: 2, detail: 0.8, specular: NaN } } });
    expect(material).toMatchObject({ a1: 1, detail: 0.8, specular: original.specular, roughness: original.roughness });
    expect(h.MATERIALS.matte).toEqual(original);
    expect(h.shadowFinish({ texture: 'shimmer', applicationProfile: { shadowFinish: { opacity: -1, specular: 3 } } }))
      .toMatchObject({ opacity: 0, specular: 2, sparkleDensity: h.SHADOW_FINISHES.shimmer.sparkleDensity });
    expect(h.profileCoverage({ applicationProfile: { coverageMultiplier: 99 } }, 0.7)).toBe(1);
    expect(h.profileCoverage({ applicationProfile: { coverageMultiplier: NaN } }, 0.7)).toBe(0.7);
  });
});
