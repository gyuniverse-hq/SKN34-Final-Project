import { FACE_TRACKER_HTML } from '@/components/ar/faceTrackerHtml';
import { SHADOW_FINISHES, SHADOW_FINISH_IDS } from '@/lib/shadowFinishes';

const html = FACE_TRACKER_HTML;

describe('matte specular mask and softer outer edge (11-13)', () => {
  it('keeps the matte mask values in range and registers/sets its uniform', () => {
    const m = html.match(/matteSpecMask: \[([\d.]+), ([\d.]+), ([\d.]+)\]/);
    expect(m).not.toBeNull();
    const [strength, ridge, scale] = [Number(m![1]), Number(m![2]), Number(m![3])];
    expect(strength).toBeGreaterThanOrEqual(0);
    expect(strength).toBeLessThanOrEqual(0.15);
    expect(ridge).toBeGreaterThanOrEqual(0);
    expect(ridge).toBeLessThanOrEqual(1);
    expect(scale).toBeGreaterThanOrEqual(0.05);
    expect(scale).toBeLessThanOrEqual(0.2);
    expect(html).toContain("'uMatteSpec'");
    expect(html).toMatch(/gl\.uniform3f\(u\.uMatteSpec,/);
  });

  it('builds the mask from local luminance contrast and only for matte roughness', () => {
    expect(html).toContain("'    float matteW = uMatteSpec.x > 0.0 ? smoothstep(0.8, 0.9, uLipRough) * core * (1.0 - skinRefW) : 0.0;',");
    expect(html).toContain("'    float crease = clamp((wideL - camL) / (uMatteSpec.z * meanL), -1.0, 1.0);',");
    expect(html).toContain('1.0 - smoothstep(0.0, 1.0, crease) + uMatteSpec.y * smoothstep(0.0, 1.0, -crease)');
    // The mask multiplies every reflection term: form shine, sheen, glint and the kept camera highlight.
    expect(html).toContain("'    formSpec *= specMask; sheen *= specMask;',");
    expect(html).toContain('vec3(hl * keepHl * specMask)');
  });

  it('softens the outer edge with a 16-tap kernel and keeps the fixed values that do not move it', () => {
    expect(html).toContain("'  vec2 sd = so * 0.7071;',");
    expect(html).toContain("'  return edgeRemap(a / w);',");
    expect(html).toContain('lipEdgeBlurK: 1.5,');
    expect(html).toContain('lipEdgeSoftMax: 3.0,');
    // Unchanged on purpose: these do not move the on-screen edge (measured 11-13).
    expect(html).toContain('lipEdgePx: 2,');
    expect(html).toContain('lipFeatherPx: 3,');
  });
});

describe('lip finish plan D (11-23)', () => {
  it('registers and sets glossScale / rimTilt from the lip material (1 when absent, a lip oil / balm keeps 1)', () => {
    expect(html).toContain("'uniform float uGlossScale; uniform float uRimTilt;',");
    expect(html).toContain("'uGlossFlat', 'uGlossScale', 'uRimTilt', 'uGlossShape',");
    expect(html).toContain('gl.uniform1f(u.uGlossScale, careAny ? 1 : (lipMat.glossScale ?? 1));');
    expect(html).toContain('gl.uniform1f(u.uRimTilt, careAny ? 1 : (lipMat.rimTilt ?? 1));');
    expect(html).toContain('matteSpecMask: [0.05, 0.2, 0.10],');
  });

  it('scales the form highlight and bends only the shine normal, after the colour path', () => {
    const shader = html;
    const rim = shader.indexOf("'    if (uRimTilt < 0.999) {',");
    const midN = shader.indexOf("'    vec3 lipMidN = uWideDetail > 0.0 ? normalize(mix(lipFormN, lipDetailN, uWideDetail)) : lipFormN;',");
    const colour = shader.indexOf("'    layered *= mix(1.0, clamp(form, 0.35, 1.0), uLipVolume * cov * uFormOn);',");
    expect(rim).toBeGreaterThan(colour);
    expect(midN).toBeGreaterThan(rim);
    // only the upward tilt of the upper lip is scaled
    expect(shader).toContain("'      float kR = mix(1.0, uRimTilt, upW * step(0.0, dN.y));',");
    expect(shader).toContain("'    formSpec *= uGlossScale;',");
  });
});

describe('lip edge that scales with the lip (11-13)', () => {
  it('has the proportional radius, the inward remap and the two-ring kernel, each switched off by zero', () => {
    const fk = html.match(/lipEdgeFeatherK: ([\d.]+)/);
    const sk = html.match(/lipEdgeSoftMaxK: ([\d.]+)/);
    const inset = html.match(/lipEdgeInset: \[([\d.]+), ([\d.]+), ([\d.]+)\]/);
    expect(fk && sk && inset).toBeTruthy();
    expect(Number(fk![1])).toBeLessThanOrEqual(0.5);
    expect(Number(sk![1])).toBeLessThanOrEqual(1);
    expect(Number(inset![1])).toBeLessThan(Number(inset![2]));
    expect(Number(inset![3])).toBeLessThanOrEqual(1);
    expect(html).toContain("'uLipFeather'");
    expect(html).toMatch(/gl\.uniform3f\(u\.uLipFeather,/);
    expect(html).toContain("'    float soft = edgeSoft(suv, so);',");
    // The overlip test (skinRefW) uses the same kernel and remap as the paint edge, or the two disagree.
    expect(html).toContain("'    float insideBase = edgeSoftBase(suv, so);',");
    expect(html).toContain("'float edgeSoftBase(vec2 s, vec2 so) { return edgeKernel(s, so, true); }',");
    expect(html).toContain('float edgeRemap(float a) { return uLipFeather.x > 0.0 ? smoothstep(uLipFeather.x, uLipFeather.y, a) : a; }');
  });
});

describe('steady lip outline (11-15)', () => {
  it('smooths the camera-colour pull/push per vertex and the edge radius thickness', () => {
    const num = (k: string) => Number(html.match(new RegExp(`${k}: ([0-9.]+)`))![1]);
    expect(num('lipEdgePullSmooth')).toBeGreaterThan(0);
    expect(num('lipEdgePullSmooth')).toBeLessThanOrEqual(1);
    expect(num('lipEdgeStepMax')).toBeGreaterThan(0);
    expect(num('lipEdgeStepMax')).toBeLessThanOrEqual(0.15);
    expect(num('lipThickSmooth')).toBeGreaterThan(0);
    expect(html).toContain('lipPullSm[j] += clamp(k * (target - lipPullSm[j]), -cap, cap);');
    expect(html).toContain('lipThickSm = lipThickSm > 0 ? lipThickSm + TUNING.lipThickSmooth * (lipThickNow - lipThickSm) : lipThickNow;');
  });
});

describe('lashes and liner that sit on the eye (11-16)', () => {
  it('fits the lash line for a mascara-only look and starts roots inside it', () => {
    expect(html).toContain('if (liner || mascara) {');
    expect(html).toContain('lashRootInset: 0.006,');
    expect(html).toContain('const widthShrink = clamp(lashSpacePx / (2.2 * lashRootPx), 0.85, 1);');
  });
  it('keeps volume with a back row and a dense root, and softens the roots and liner edges', () => {
    const num = (k: string) => Number(html.match(new RegExp(`${k}: ([0-9.]+)`))![1]);
    expect(num('lashBackLayer')).toBeGreaterThan(0);
    expect(num('lashBackLayer')).toBeLessThan(1);
    expect(num('lashRootHold')).toBeLessThan(0.5);
    expect(num('lashRootBand')).toBeLessThanOrEqual(0.6);
    expect(num('linerShade')).toBeLessThanOrEqual(0.5);
    expect(html).toContain('lashG = max(lashG, smoothstep(0.10, 0.34, eyeC.g) * uLashBand);');
    expect(html).toContain('uLinerAA, 0.5 + 0.25 * (TUNING.linerEdgeSoft[0] + TUNING.linerEdgeSoft[1])');
  });
});

describe('natural lashes, liner on the lid edge, brow hair overlay (11-16)', () => {
  it('gives each strand its own darkness and a glint on the brow canvas R', () => {
    expect(html).toContain('0.75 + 0.2 * seeded(i + 700), 0.35 + 0.5 * seeded(i + 800), false);');
    expect(html).toContain("'float lashGlintAt(vec2 s) {',");
    expect(html).toContain('uLightColor * uExposure * uLightStrength * lashGlintAt(suv) * uLashGloss * mascaraA');
    const g = Number(html.match(/lashGloss: ([0-9.]+)/)![1]);
    expect(g).toBeGreaterThan(0);
    expect(g).toBeLessThanOrEqual(0.5);
  });
  it('draws lower roots inside the lid line, a lower shade line, and a liner that reaches the eye edge', () => {
    expect(html).toContain('lowerLineAlpha: 0.2,');
    expect(html).toContain('const sideCanvas = !!(browPaint || mascara);');
    expect(Number(html.match(/linerRootInset: ([0-9.]+)/)![1])).toBeLessThanOrEqual(0.03);
  });
  it('tints brow hairs (black ones too) and keeps the grain, no overlay', () => {
    expect(html).toContain('float newL = mix(camL, prodL * grain, uBrowShift);');
    expect(html).toContain("'float browZoneAt(vec2 s) {',");
    expect(html).not.toContain('ovCol');
    expect(html).toContain('hairDepth: 1.0,');
  });
  it('11-17: fringe hair over the brow stays uncoloured (segmenter hair class, hair above too)', () => {
    expect(html).toContain('return !!(makeup.foundation || jawline || makeup.brow || (TUNING.makeupOcclusion && occMakeupOn()));');
    expect(html).toContain('foundHairPrev[i] = foundHairPrev[i] * hk + (cat[i] === 1 ? 255 : 0) * (1 - hk);');
    expect(html).toContain('foundSkinRgba[i * 4 + 1] = foundHairPrev[i];');
    expect(html).toContain("region *= 1.0 - uBrowFringeOn * smoothstep(0.25, 0.6, hHere) * smoothstep(0.25, 0.6, hUp);");
    expect(html).toContain('gl.uniform1f(u.uBrowFringeOn, browZ && foundSkinReady ? EYEBROW_PRESET.fringeGuard : 0);');
    // The skin texture's red channel stays the face-skin share every other zone reads.
    expect(html).not.toMatch(/texture2D\(uFoundSkin, [^)]*\)\.r[^;]*uBrowFringeOn/);
  });
  it('11-17: product eyeshadow is layered (inner sheer, packed outer V / crease, lifting light shades); video looks keep theirs', () => {
    expect(html).toContain('const eyeZoned = !!(eye && !eye.applicationProfile);');
    expect(html).toContain("gl.uniform1f(u.uShadowZoned, eyeZoned ? 1 : 0);");
    expect(html).toContain("'    shadowA *= mix(uShadowInnerSheer, 1.0, smoothstep(-0.05, 0.45, sT));',");
    expect(html).toContain("'    darkA = max(0.5 * m2.b * (1.0 - upW), depthW) * uShadow2Cov;',");
    expect(html).toContain("'  float lift = uShadowLift * clamp(3.0 * (lum(pw) - lum(cam)) / max(lum(cam), 1e-3), 0.0, 1.0);',");
    // Without a point colour the same hex is packed again; the hex itself is never changed (1-1).
    expect(html).toContain('const eyeAlb2 = eye && eye.hexTo ? hexToLinear(eye.hexTo) : eyeSelf ? hexToLinear(eye.hex) : [0, 0, 0];');
    // Corner uniforms point at 133/33 and 362/263.
    expect(html).toContain('gl.uniform4f(u.uShadowEye0, FACE_UV[266], FACE_UV[267], FACE_UV[66], FACE_UV[67]);');
    expect(html).toContain("'uShadowZoned', 'uShadowLift', 'uShadowMetal', 'uShadowInnerSheer', 'uShadowEye0', 'uShadowEye1', 'uShadowUp',");
  });
  it('11-17: satin and metallic finishes match lib/shadowFinishes', () => {
    // 11-17 v7: satin is a chip; metallic is no chip any more (a metal product's glitter) but keeps its table row.
    expect(SHADOW_FINISH_IDS).toContain('satin');
    expect(SHADOW_FINISH_IDS).not.toContain('metallic');
    for (const id of ['satin', 'metallic'] as const) {
      const f = SHADOW_FINISHES[id];
      const row = html.match(new RegExp(id + ':\\s+\\{ opacity: ([0-9.]+), roughness: ([0-9.]+), sparkleDensity: ([0-9.]+), specular: ([0-9.]+)'));
      expect(row).not.toBeNull();
      expect([Number(row![1]), Number(row![2]), Number(row![3]), Number(row![4])]).toEqual([f.opacity, f.roughness, f.sparkleDensity, f.specular]);
    }
    expect(html).toContain('gl.uniform1f(u.uShadowMetal, eye && shadowFinish(eye).metal ? 1 : 0);');
  });
  it('11-17 v3: product lid finish has a 0..100 table and its own path per finish, matte has no pearl, video looks keep the old path', () => {
    const block = html.slice(html.indexOf('const SHADOW_PEARL = {'), html.indexOf('function pearlUniforms('));
    const keys = ['density', 'size', 'brightness', 'sparkle', 'specular', 'specWidth', 'roughness', 'micro', 'texture', 'crease', 'edge', 'spread', 'shape', 'orientation'];
    for (const id of ['matte', 'satin', 'shimmer', 'glitter', 'metallic', 'glossy']) {
      const row = block.match(new RegExp(id + ':\\s+\\{([^}]*)\\}'));
      expect(row).not.toBeNull();
      for (const k of keys) {
        const v = Number(row![1].match(new RegExp(k + ': (\\d+)'))![1]);
        expect(v).toBeGreaterThanOrEqual(0);
        expect(v).toBeLessThanOrEqual(100);
      }
    }
    expect(block).toMatch(/matte:\s+\{ density: 0, {2}size: 0, {2}brightness: 0, {2}sparkle: 0, {2}specular: 0,/);
    // Glossy: a wet coat on the lit folds.
    expect(html).toContain("'      float wet = smoothstep(1.0, 1.1, rel.z) * smoothstep(0.6, 1.0, camL / max(uSkinMeanLum, 1e-3));',");
    // Overlay keeps the lid's light and shade under the colour; the light terms are separate.
    expect(html).toContain("'    col = mix(col, toLin(overlayB(toSrgb(col), vec3(detail))), uPearlC.z * lidPaint);',");
    expect(html).toContain('const SHADOW_MODE = { matte: 0, satin: 1, shimmer: 2, metallic: 3, glitter: 4, glossy: 5 };');
    expect(html).toContain("'vec3 lidRelief(vec2 s, float camL) {',");
    expect(html).toContain("'    float shadeW = smoothstep(0.25, 0.9, camL / max(uSkinMeanLum, 1e-3));',");
    expect(html).toContain("'  if (uShadowZoned > 0.5 && lidPaint > 0.002) {',");
    expect(html).toContain("'    if (uShadowZoned < 0.5) {',");
    expect(html).toContain("'uPearlA', 'uPearlB', 'uPearlC', 'uPearlD',");
  });
  it('11-17 v6: shimmer / metallic / glitter use one Voronoi pearl each, with scale, detail and roughness from the sliders', () => {
    // Per-finish table: shimmer fine dots, metallic dense tight flakes, glitter large flakes with a gap.
    const voro = html.slice(html.indexOf('const SHADOW_VORO = {'), html.indexOf('function voroUniforms('));
    const num = (id: string, k: string) => Number(voro.match(new RegExp(id + ':\\s+\\{[^}]*\\b' + k + ': ([0-9.]+)'))![1]);
    // 11-19 v8: glitter grains are now finer than shimmer (user: smaller glitter, more grains than shimmer).
    expect(num('glitter', 'cell') * 130).toBeGreaterThan(num('shimmer', 'cell') * 260);
    expect(num('shimmer', 'fill')).toBe(0);
    expect(num('metallic', 'density')).toBe(1);
    expect(num('metallic', 'gap')).toBeLessThan(num('glitter', 'gap'));
    expect(num('glitter', 'flash')).toBeGreaterThan(num('shimmer', 'flash'));
    // Octaves weighted rough^n up to the detail, the flash widened by roughness, lid-fixed 3x3 search.
    expect(html).toContain("'vec4 lidVoroPearl(vec2 uv, vec3 nm, vec3 T, vec3 B, vec3 h) {',");
    expect(html).toContain("'    float w = o == 0 ? 1.0 : pow(mix(0.5, 1.0, rough), fo) * clamp(uVoroA.y - fo + 1.0, 0.0, 1.0);',");
    expect(html).toContain('* mix(1.0, 0.6, rough);');
    expect(html).toContain("'  float sharp = uVoroB.z * mix(1.0, 0.25, rough);',");
    expect(html).toContain("'      float d = length(q) - uVoroC.z * fract(jt.x * 7.13 + jt.y * 3.71);',");
    expect(html).toContain("'    w *= smoothstep(1.3, 2.6, px);',");
    expect(html).toContain("'uLidAxis', 'uVoroA', 'uVoroB', 'uVoroC', 'uVoroEdge', 'uVoroD',");
    // Point sparkle chips are gone.
    expect(html).not.toContain('sparkleSpots');
    expect(html).not.toContain('uSpotOn');
  });
  it('11-17 v7: fixed capture values, metallic glitter from the product, micro / glint / iridescent / sequin layers', () => {
    // The v6 slider values read on the phone captures, fixed; sliders gone.
    expect(html).toContain('const VORO_FIXED = { shimmer: [0.27, 0.45, 0.32], metallic: [0.27, 0.86, 0.22], glitter: [0.27, 0.6, 0.25] };');
    expect(html).not.toContain('pearlScale');
    // The glitter chip draws a metallic glitter for a metal product; glitter flakes are separated, not tiled.
    expect(html).toContain('if (base === SHADOW_FINISHES.glitter && zone.particle && zone.particle.metal && !zone.applicationProfile) base = SHADOW_FINISHES.metallic;');
    expect(html).toMatch(/glitter: {2}\{ cell: 2\.0, {2}detail: 1\.0, rough: 0\.2, {2}density: 0\.75, fill: 1, gap: 0\.14, dot: 0\.4, {2}sharp: 50,/);
    // Sequin flakes stay on the upper lid; the pearl leans toward the outer corner.
    expect(html).toContain('lidHexFlake(vUv, nm, Tp, Bp, hF) * smoothstep(-0.02, 0.06, spP.y);');
    expect(html).toContain('(1.0 + 0.35 * smoothstep(0.7, 1.0, spP.x))');
    // Layers and optics.
    expect(html).toContain("'vec4 lidMicroDust(vec2 uv, vec3 nm, vec3 T, vec3 B, vec3 h) {',");
    expect(html).toContain("'vec4 lidHexFlake(vec2 uv, vec3 nm, vec3 T, vec3 B, vec3 h) {',");
    expect(html).toContain("'      float st = exp(-abs(q.y) / sw) * exp(-abs(q.x) * 3.0) + exp(-abs(q.x) / sw) * exp(-abs(q.y) * 3.0);',");
    expect(html).toContain("'    vec3 film = 0.55 + 0.45 * cos(6.2832 * (1.5 * hash(cw + 5.7) + 0.9 / cv + vec3(0.0, 0.33, 0.67)));',");
    // Lid-centre reflection, the outer V, and no uLidOpen on the product pearl (kept on a closed lid).
    expect(html).toContain("lobeN(max(dot(nm, hS), 0.0), 0.45) * lit * latW);',");
    expect(html).toContain("'    float edgeW = smoothstep(0.0, uPearlC.w, max(m.b, darkA / max(uShadow2Cov, 1e-3)));',");
    const pwLine = html.match(/'      float pw = [^\n]*/)![0];
    expect(pwLine).not.toContain('uLidOpen');
  });
  it('11-19 v8: glitter grains are smaller and more numerous than shimmer; sequin products keep the v7 size', () => {
    const num = (re: RegExp) => Number(html.match(re)![1]);
    const row = (id: string, k: string) => num(new RegExp(id + ':\\s+\\{[^}]*\\b' + k + ': ([0-9.]+)'));
    const shimScale = num(/lidShimmerScale: (\d+),/);
    const glitScale = num(/lidGlitterScale: (\d+),/);
    const sizeMul = (v: number) => Math.pow(2, (0.5 - v) * 2);
    // fixed capture size 0.27 for both
    const shimF = shimScale * row('shimmer', 'cell') * sizeMul(0.27);
    const glitF = glitScale * row('glitter', 'cell') * sizeMul(0.27);
    expect(glitF).toBeGreaterThan(shimF);
    expect(glitF * glitF * row('glitter', 'density')).toBeGreaterThan(1.3 * shimF * shimF * row('shimmer', 'density'));
    // sequin products: v7 frequency (cell 1.0 at the large size)
    expect(row('glitter', 'largeCell')).toBe(1.0);
    expect(html).toContain('a: [(p.large && v.largeCell ? v.largeCell : v.cell) * Math.pow(2, (0.5 - size) * 2),');
    expect(html).toContain("'  float kk = min(uVoroA.x * 2.6, 4.0);',");
  });
  it('11-19 v9: product shadows cover more (pearl finishes most); glitter flakes carry the product colour', () => {
    const tbl = html.match(/const SHADOW_PRODUCT_OPACITY = (\{[^}]*\});/)![1];
    const prod = JSON.parse(tbl.replace(/(\w+):/g, '"$1":')) as Record<string, number>;
    for (const id of ['matte', 'satin', 'metallic', 'shimmer', 'glitter', 'glossy']) {
      const base = Number(html.match(new RegExp(id + ':\\s+\\{ opacity: ([0-9.]+)'))![1]);
      expect(prod[id]).toBeGreaterThanOrEqual(base);
    }
    expect(prod.glitter).toBeGreaterThanOrEqual(2 * 0.3);
    // video looks keep the old opacity
    expect(html).toContain('if (!zone || zone.applicationProfile) return f.opacity;');
    expect(html).toMatch(/glitter: {2}\{ cell: 2\.0,[^}]*body: 0\.6,/);
    expect(html).toContain("vec3 pearlTint = mix(mix(tintN, vec3(1.0), mix(0.45, 0.15, uVoroB.x)), tintN, isMetal);");
    expect(html).toContain('shadowDepthSelf: 0.55,');
  });
  it('11-17 v6: eye-only makeup draws the face mesh through a scissor around the eyes', () => {
    expect(html).toContain('const eyeOnly = !lip && !blush && !hl && !contourZ && !foundZ && !!(eye || liner || mascara || browZ);');
    expect(html).toContain('gl.scissor(sx0, sy0, Math.max(0, sx1 - sx0), Math.max(0, sy1 - sy0));');
    expect(html).toContain('eyeScissorPad: [0.12, 0.45],');
    // and the occlusion mask refreshes slower with eye zones only.
    expect(html).toContain('eyeSegEveryMs: 400,');
    expect(html).toContain('return Math.max(TUNING.eyeSegEveryMs, fps >= TUNING.segmentMinFps ? 0 : still ? TUNING.foundSegStillMs : TUNING.foundSegEveryLowFpsMs);');
  });
  it('11-17 v3: brow ring is soft and wide, head and tail fade on their own', () => {
    const num = (k: string) => Number(html.match(new RegExp(k + ': ([0-9.]+)'))![1]);
    expect(num('skinFloor')).toBeGreaterThanOrEqual(0.7);
    expect(num('skinFloor')).toBeLessThanOrEqual(0.95);
    expect(num('headSoft')).toBeLessThan(1);
    expect(num('tailFade')).toBeGreaterThan(0);
    expect(num('zoneSoft')).toBeGreaterThan(0.2);
    expect(html).toContain('browCtx.lineWidth = Math.max(1, EYEBROW_PRESET.ringWiden * browH * k);');
    expect(html).toContain("'uBrowHpx', 'uBrowSkinFloor', 'uBrowHairEdge', 'uBrowHeadSoft', 'uBrowTailFade', 'uBrowZoneSoft', 'uBrowFringeOn',");
    expect(html).toContain('vec3 ownOv = toLin(hardLight(toSrgb(layer(cam, uMascaraAlbedo, uSkinMeanLum, 1.0)), toSrgb(col))) * 0.85;');
  });
});
