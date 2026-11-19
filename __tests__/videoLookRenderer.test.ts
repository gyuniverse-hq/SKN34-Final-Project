import { FACE_TRACKER_HTML } from '@/components/ar/faceTrackerHtml';

function lookHelpers() {
  const start = FACE_TRACKER_HTML.indexOf('  function profileGain(');
  const end = FACE_TRACKER_HTML.indexOf('  function profileCoverage(', start);
  if (start < 0 || end < 0) throw new Error('look helpers not found');
  return new Function(`
    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
    function clamp01(v) { return clamp(Number(v) || 0, 0, 1); }
    ${FACE_TRACKER_HTML.slice(start, end)}
    return { profileGain, profileSkin, profilePigment, profileLightAdapt };
  `)() as {
    profileGain(zone: object | null, key: string, max: number): number;
    profileSkin(zone: object | null): { tint: number[]; tone: number; clean: number } | null;
    profilePigment(zone: object | null, pigment: number[], skin: unknown): number[];
    profileLightAdapt(
      zone: object | null, pigment: number[], lightColor: unknown, exposure: unknown, conf: unknown,
    ): number[];
  };
}

describe('video look finish in the renderer', () => {
  it('is off (0) without a look value, so the product render is unchanged', () => {
    const h = lookHelpers();
    expect(h.profileGain(null, 'softLight', 8)).toBe(0);
    expect(h.profileGain({ texture: 'cream' }, 'softLight', 8)).toBe(0);
    expect(h.profileGain({ applicationProfile: { coverageMultiplier: 0.5 } }, 'glow', 4)).toBe(0);
    expect(h.profileGain({ applicationProfile: { softLight: NaN } }, 'softLight', 8)).toBe(0);
    for (const key of ['lipGradient', 'lipGloss', 'linerTaper', 'lashCurl', 'skinWide', 'underEyePearl', 'skinAdapt', 'lightAdapt']) {
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

  it('keeps video look glow active in both natural and legacy highlighter paths', () => {
    const html = FACE_TRACKER_HTML;
    const naturalStart = html.indexOf("'  if (hlA > 0.002 && uHlNat > 0.5) {',");
    const legacyStart = html.indexOf("'  } else if (hlA > 0.002) {',", naturalStart);
    const shadowStart = html.indexOf("'  if (shadowA > 0.002) {',", legacyStart);
    expect(naturalStart).toBeGreaterThan(-1);
    expect(legacyStart).toBeGreaterThan(naturalStart);
    expect(shadowStart).toBeGreaterThan(legacyStart);
    for (const branch of [html.slice(naturalStart, legacyStart), html.slice(legacyStart, shadowStart)]) {
      expect(branch).toContain("'    if (uHlGlow > 0.001) {',");
      expect(branch).toContain("'      float gm = glowMask(suv, lN);',");
      expect(branch).toContain('hlA * uHlGlow');
    }
    expect(lookHelpers().profileGain({ applicationProfile: { glow: 0.6 } }, 'glow', 4)).toBeCloseTo(0.6);
    expect(lookHelpers().profileGain({ applicationProfile: {} }, 'glow', 4)).toBe(0);
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

  it('lightAdapt is a no-op at 0 or neutral light, and shifts hue under warm light while keeping luminance', () => {
    const h = lookHelpers(), pigment = [0.55, 0.22, 0.28];
    const lum = (c: number[]) => 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
    expect(h.profileLightAdapt(null, pigment, [1.2, 1, 0.8], 1.1, 1)).toBe(pigment);
    expect(h.profileLightAdapt({ applicationProfile: {} }, pigment, [1.2, 1, 0.8], 1.1, 1)).toBe(pigment);
    expect(h.profileLightAdapt({ applicationProfile: { lightAdapt: 0 } }, pigment, [1.2, 1, 0.8], 1.1, 1)).toBe(pigment);
    const neutral = h.profileLightAdapt({ applicationProfile: { lightAdapt: 1 } }, pigment, [1, 1, 1], 1, 1);
    expect(neutral).toEqual(pigment);
    for (const bad of [null, [], [NaN, 1, 1], [1, -1, 1], 'warm']) {
      expect(h.profileLightAdapt({ applicationProfile: { lightAdapt: 1 } }, pigment, bad, 1.1, 1)).toBe(pigment);
    }
    for (const bad of [undefined, NaN, 0, -1, '1']) {
      expect(h.profileLightAdapt({ applicationProfile: { lightAdapt: 1 } }, pigment, [1.2, 1, 0.8], bad, 1)).toBe(pigment);
    }
    const warm = h.profileLightAdapt({ applicationProfile: { lightAdapt: 1 } }, pigment, [1.35, 1.05, 0.75], 1.15, 1);
    expect(warm[0] / warm[2]).toBeGreaterThan(pigment[0] / pigment[2]);
    expect(lum(warm)).toBeCloseTo(lum(pigment), 5);
    expect(h.profileLightAdapt({ applicationProfile: { lightAdapt: 1 } }, pigment, [1.35, 1.05, 0.75], 1.15, 0)).toBe(pigment);
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
    expect(html).toContain("'      cam = max(cam + (mix(low, even, uSkinEven) - low) * skinW * smoothstep(0.3, 0.6, lowSat) * (1.0 - smoothstep(0.0, 0.15, featureE)), vec3(0.0)); col = cam;',");
    expect(html).toContain("'    if (uBlushColor > 0.001) {',");
    expect(html).toContain("'    if (uLookLipColor > 0.001) layered = mix(layered, uLipAlbedo / max(lum(uLipAlbedo), 1e-4) * lum(layered), uLookLipColor * core);',");
    expect(html).toContain("gl.uniform1f(u.uSkinEven, profileGain(foundZ, 'skinEven', 1) * lookSkinGate);");
    expect(html).toContain("gl.uniform1f(u.uBlushColor, profileGain(blush, 'blushColor', 8));");
    expect(html).toContain("gl.uniform1f(u.uLookLipColor, profileGain(lip, 'lipColor', 1));");
    expect(html).toContain('profileLightAdapt(foundZ, lookSkin.tint, shown.color, shown.exposure, light.colorConf)');
    expect(html).toContain('profileLightAdapt(');
    expect(html).toContain("gl.uniform1f(u.uLookToneMap, profileGain(foundZ, 'toneMap', 1));");
    expect(html).toContain("'    if (uLookToneMap > 0.001) ink *= mix(1.0, clamp(lum(cam) / max(uSkinMeanLum, 1e-3), 0.55, 1.35), uLookToneMap);',");
    for (const name of ['uBlushSoft', 'uSkinTint', 'uSkinTone', 'uSkinClean', 'uHlGlow', 'uSkinEven', 'uBlushColor', 'uLookLipColor', 'uLookToneMap']) {
      expect(html).toContain(`'${name}'`);
    }
    expect(html).toContain('if (uLookLip.x > 0.001) cov *=');
    expect(html).toContain('if (uLookLip.y > 0.001) {');
    expect(html).toContain('if (tip && lookTaper > 0.001) {');
    expect(html).toContain("const lookCurl = profileGain(mascara, 'lashCurl', 1);");
    expect(html).toContain('const curlK = 0.5 + 0.5 * lookCurl;');
    expect(html).toContain('if (uSkinWide > 0.001) {');
    expect(html).toContain("gl.uniform1f(u.uSkinWide, profileGain(foundZ, 'skinWide', 1) * lookWideGate);");
    expect(html).toContain("const lookPearl = profileGain(shadow, 'underEyePearl', 1);");
    expect(html).toContain('if (lookPearl > 0.001 && ip) {');
  });
});
