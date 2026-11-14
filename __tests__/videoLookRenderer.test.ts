import { FACE_TRACKER_HTML } from '@/components/ar/faceTrackerHtml';

function lookHelpers() {
  const start = FACE_TRACKER_HTML.indexOf('  function profileGain(');
  const end = FACE_TRACKER_HTML.indexOf('  function profileCoverage(', start);
  if (start < 0 || end < 0) throw new Error('look helpers not found');
  return new Function(`
    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
    function clamp01(v) { return clamp(Number(v) || 0, 0, 1); }
    ${FACE_TRACKER_HTML.slice(start, end)}
    return { profileGain, profileSkin, profilePigment };
  `)() as {
    profileGain(zone: object | null, key: string, max: number): number;
    profileSkin(zone: object | null): { tint: number[]; tone: number; clean: number } | null;
    profilePigment(zone: object | null, pigment: number[], skin: unknown): number[];
  };
}

describe('video look finish in the renderer', () => {
  it('is off (0) without a look value, so the product render is unchanged', () => {
    const h = lookHelpers();
    expect(h.profileGain(null, 'softLight', 8)).toBe(0);
    expect(h.profileGain({ texture: 'cream' }, 'softLight', 8)).toBe(0);
    expect(h.profileGain({ applicationProfile: { coverageMultiplier: 0.5 } }, 'glow', 4)).toBe(0);
    expect(h.profileGain({ applicationProfile: { softLight: NaN } }, 'softLight', 8)).toBe(0);
    for (const key of ['lipGradient', 'lipGloss', 'linerTaper', 'lashCurl', 'skinWide', 'underEyePearl', 'skinAdapt']) {
      for (const value of [undefined, NaN, Infinity, '1', null, -1]) {
        expect(h.profileGain({ applicationProfile: { [key]: value } }, key, 3)).toBe(0);
      }
    }
    expect(h.profileSkin({ applicationProfile: {} })).toBeNull();
    expect(h.profileSkin({ applicationProfile: { skin: { tint: 'pink', tone: 1, clean: 1 } } })).toBeNull();
  });

  it('bounds the look values', () => {
    const h = lookHelpers();
    expect(h.profileGain({ applicationProfile: { softLight: 99 } }, 'softLight', 8)).toBe(8);
    expect(h.profileGain({ applicationProfile: { glow: -1 } }, 'glow', 4)).toBe(0);
    expect(h.profileSkin({ applicationProfile: { skin: { tint: '#FF8000', tone: 2, clean: -1 } } }))
      .toEqual({ tint: [1, 128 / 255, 0], tone: 1, clean: 0 });
  });

  it('adapts only warm skin with valid look controls, keeping pigment luminance and the Sullyoon reference', () => {
    const h = lookHelpers(), pigment = [0.4, 0.12, 0.18];
    const zone = { applicationProfile: { skinAdapt: 0.8, skinWarmth: 0.28 } };
    const reference = [0.583, 0.361, 0.312], warm = [0.781, 0.337, 0.217];
    expect(h.profilePigment(zone, pigment, reference)).toBe(pigment);
    expect(h.profilePigment(null, pigment, warm)).toBe(pigment);
    for (const bad of [undefined, NaN, Infinity, '0.28', null, -1, 2]) {
      expect(h.profilePigment({ applicationProfile: { skinAdapt: 1, skinWarmth: bad } }, pigment, warm)).toBe(pigment);
    }
    for (const bad of [null, [], [NaN, 0.2, 0.1], [1, -1, 0], [1, 2, 0]]) expect(h.profilePigment(zone, pigment, bad)).toBe(pigment);
    const result = h.profilePigment(zone, pigment, warm);
    expect(result[2] / result[1]).toBeLessThan(pigment[2] / pigment[1]);
    const lum = (c: number[]) => 0.2126*c[0] + 0.7152*c[1] + 0.0722*c[2];
    expect(lum(result)).toBeCloseTo(lum(pigment), 10);
  });

  it('runs every look statement only when its value is set, and keeps the powder blush otherwise', () => {
    const html = FACE_TRACKER_HTML;
    expect(html).toContain("'    if (uBlushSoft > 0.001) col = mix(col, toLin(softLight(toSrgb(col), toSrgb(uBlushAlbedo))), 1.0 - exp(-blushA * uBlushSoft));',");
    expect(html).toContain("'    else col = mix(col, powder(cam, uBlushAlbedo), blushA);',");
    expect(html).toContain("'    col += uBlushAlbedo * uLightColor * powderSheen(n, l, v, uFaceRough.x) * blushA;',");
    expect(html).toMatch(/if \(uSkinClean > 0\.001\) \{ cam = mix\(cam, skinClean\(cam, suv\)/);
    expect(html).toContain("'    if (uSkinTone > 0.001) {',");
    expect(html).toContain("'      float lift = clamp((lum(toLin(uSkinTint)) - uSkinMeanLum - 0.1) * 5.0, 0.0, 1.0);',");
    expect(html).toContain("'      col = mix(col, cam / max(lum(cam), 1e-4) * lum(col), 0.5 * skinW);',");
    expect(html).toContain("'    if (uHlGlow > 0.001) {',");
    expect(html).toContain("'      float gm = glowMask(suv, lN);',");
    // 11-14: frequency-separated skin evening, colour-blend blush and lip, all off at 0
    expect(html).toContain("'    if (uSkinEven > 0.001) {',");
    expect(html).toContain("'      cam = max(cam + (mix(low, even, uSkinEven) - low) * skinW * (1.0 - smoothstep(0.0, 0.15, featureE)), vec3(0.0)); col = cam;',");
    expect(html).toContain("'    if (uBlushColor > 0.001) {',");
    expect(html).toContain("'    if (uLookLipColor > 0.001) layered = mix(layered, uLipAlbedo / max(lum(uLipAlbedo), 1e-4) * lum(layered), uLookLipColor * core);',");
    expect(html).toContain("gl.uniform1f(u.uSkinEven, profileGain(foundZ, 'skinEven', 1));");
    expect(html).toContain("gl.uniform1f(u.uBlushColor, profileGain(blush, 'blushColor', 8));");
    expect(html).toContain("gl.uniform1f(u.uLookLipColor, profileGain(lip, 'lipColor', 1));");
    for (const name of ['uBlushSoft', 'uSkinTint', 'uSkinTone', 'uSkinClean', 'uHlGlow', 'uSkinEven', 'uBlushColor', 'uLookLipColor']) {
      expect(html).toContain(`'${name}'`);
    }
    expect(html).toContain('if (uLookLip.x > 0.001) cov *=');
    expect(html).toContain('if (uLookLip.y > 0.001) {');
    expect(html).toContain('if (tip && lookTaper > 0.001) {');
    expect(html).toContain("const lookCurl = profileGain(mascara, 'lashCurl', 1);");
    expect(html).toContain('if (lookCurl > 0.001) {');
    expect(html).toContain('if (uSkinWide > 0.001) {');
    expect(html).toContain("gl.uniform1f(u.uSkinWide, profileGain(foundZ, 'skinWide', 1));");
    expect(html).toContain("const lookPearl = profileGain(shadow, 'underEyePearl', 1);");
    expect(html).toContain('if (lookPearl > 0.001 && ip) {');
  });
});
