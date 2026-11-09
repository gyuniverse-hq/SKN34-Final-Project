import { FACE_TRACKER_HTML } from '@/components/ar/faceTrackerHtml';
import { FACE_UV } from '@/components/ar/faceUV';
import { CONTOUR_STYLE_IDS, FACE_SHAPES, HIGHLIGHTER_STYLE_IDS, parseFaceFit, parseFaceFitStatus, parseFaceShape } from '@/lib/faceFit';
import { en } from '@/lib/i18n/en';
import { ja } from '@/lib/i18n/ja';
import { ko } from '@/lib/i18n/ko';
import { zh } from '@/lib/i18n/zh';
import modelJson from '@/research/face_shape/model.json';
import parity from './fixtures/faceShapeParity.json';

type ParityCase = { w: number; h: number; x: number[]; y: number[]; z: number[]; features: Record<string, number>; probs: number[] };

const script = FACE_TRACKER_HTML;

describe('face-fit hints', () => {
  it('keeps only known hint keys and rejects malformed messages', () => {
    expect(parseFaceFit({ rec: ['cheek_wide', 'face_long'] })).toEqual(['cheek_wide', 'face_long']);
    expect(parseFaceFit({ rec: ['round_face', 'balanced'] })).toEqual(['balanced']);
    expect(parseFaceFit({ rec: ['oval'] })).toBeNull();
    expect(parseFaceFit({})).toBeNull();
  });
});

describe('face-fit page', () => {
  it('has a template for every style id the app offers', () => {
    for (const id of HIGHLIGHTER_STYLE_IDS) expect(script).toContain('    ' + id + ': [');
    for (const id of CONTOUR_STYLE_IDS) expect(script).toContain('    ' + id + ': [');
    expect(CONTOUR_STYLE_IDS).toEqual(['jawline', 'nose']);
    expect(script).toContain("jawline: [{ t: 'ribbon' }]");
  });

  it('measures on frontal frames, freezes, and sends ratios and hint keys only', () => {
    expect(script).toContain('const yawGate = acc.loose ? TUNING.faceFitYawLoose : TUNING.faceFitYaw;');
    expect(script).toContain("post({ type: 'face_fit', ratios:");
    expect(script).not.toMatch(/face_fit[^\n]*(landmarks|image|frame)/);
  });

  it('redraws only when the style or the measurement changes, and leaves the default layers alone otherwise', () => {
    expect(script).toContain('if (key !== faceFitKey && masks && masks.repaintHlContour)');
    expect(script).toContain('if (hlCache.key !== hKey) hlCache = { key: hKey, h: hlT ? layer(() => drawTemplate(hlT, fit), TUNING.hlFeatherPx) : highlight };');
    expect(script).toContain('const k = jawEdge ? jawRibbon(fit) : coT ? layer(() => drawTemplate(coT, fit), TUNING.contourFeatherPx) : contour;');
  });

  // Jawline shading (11-05 /ar-debug): one continuous UV ribbon, run here on the real atlas.
  const S = 1024;
  const U = (i: number): [number, number] => [FACE_UV[2 * i] * S, FACE_UV[2 * i + 1] * S];
  const lerp = (a: number[], b: number[], t: number) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
  // The page's own ribbon + face-shape code, cut out of the script (no copy to drift).
  function pageShape() {
    const src = script.slice(script.indexOf('  const JAW_RIBBON = {'), script.indexOf('  // end faceShape'));
    return new Function(
      src + '; return { JAW_RIBBON, ribbonField, faceShapeFeatures, shapeProbs, jawProfile, JAW_SKIRT_TAPER, JAW_SHAPE_RULES };',
    )();
  }
  function jawMask(probs: number[] | null = null, t = 1) {
    const { JAW_RIBBON: R, ribbonField, jawProfile } = pageShape();
    const midU = [1, 4, 5, 6, 168, 152, 10, 0, 17].reduce((acc, i) => acc + U(i)[0], 0) / 9;
    const jaw = Math.hypot(U(123)[0] - U(147)[0], U(123)[1] - U(147)[1]);
    const prof = jawProfile(modelJson.classes, probs, t);
    const reach = prof.reach.map((v: number) => v * jaw);
    const out = new Float32Array(S * S);
    const side = R.ids.map(U);
    ribbonField(side, prof.weight, reach, prof.core, S, out, undefined, prof.edge);
    ribbonField(side.map((q: number[]) => [2 * midU - q[0], q[1]]), prof.weight, reach, prof.core, S, out, undefined, prof.edge);
    const at = (p: number[]) => out[Math.round(p[1]) * S + Math.round(p[0])];
    return { R, at, prof };
  }

  it('paints the jawline as one ribbon from under the ear to the chin, continuous on both sides', () => {
    const { R, at } = jawMask();
    expect(R.ids[0]).toBe(93);
    expect(R.ids[R.ids.length - 1]).toBe(152);
    expect(R.weight[0]).toBe(0);
    // The strongest point of every inward cross-section, from 132 round the chin to 361: no gap, no seam. Strong at the sides,
    // lighter (but present) at the chin by design.
    const peakIn = (i: number, toward: number) => Math.max(...[0.02, 0.04, 0.06, 0.08, 0.12].map((t) => at(lerp(U(i), U(toward), t))));
    for (const i of [132, 58, 172, 136, 150]) expect(peakIn(i, 50)).toBeGreaterThan(0.7);
    for (const i of [149, 176, 148, 152]) expect(peakIn(i, 50)).toBeGreaterThan(0.4);
    for (const i of [361, 288, 397, 365, 379]) expect(peakIn(i, 280)).toBeGreaterThan(0.7);
    for (const i of [378, 400, 377]) expect(peakIn(i, 280)).toBeGreaterThan(0.4);
  });

  it('has no step on the mesh outline: edge value, a peak just inside, then a smooth fade to zero', () => {
    const { at, prof } = jawMask();
    // On the outline the paint is edge × weight (the skirt starts at exactly this value, so the seam matches).
    expect(at(U(58))).toBeCloseTo(prof.edge[2] * prof.weight[2], 1);
    const section = [0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5].map((t) => at(lerp(U(58), U(50), t)));
    const peak = Math.max(...section);
    expect(section[0]).toBeLessThan(peak - 0.2);
    expect(peak).toBeGreaterThan(0.9);
    const after = section.slice(section.indexOf(peak));
    for (let j = 1; j < after.length; j++) expect(after[j]).toBeLessThanOrEqual(after[j - 1] + 1e-6);
    expect(after.some((v) => v > 0.1 && v < 0.9)).toBe(true);
    expect(section[section.length - 1]).toBe(0);
  });

  it('stays off the cheek, lips and ear', () => {
    const { at } = jawMask();
    for (const i of [50, 280, 147, 123, 17, 18, 61, 291, 199, 234]) expect(at(U(i))).toBe(0);
    expect(at(U(177))).toBeLessThan(0.2);
  });

  it('keeps the chin light on the chin / neck line: no beard-like band, no skirt under the chin', () => {
    const { at, prof } = jawMask();
    const { JAW_SKIRT_TAPER } = pageShape();
    expect(at(U(152))).toBeLessThan(0.25);
    expect(at(U(148))).toBeLessThan(0.25);
    expect(prof.edge[9] * prof.weight[9]).toBeLessThan(0.2);
    expect(JAW_SKIRT_TAPER.slice(7)).toEqual([0, 0, 0]);
    // The darkest part of the jaw angle is still strong and sits inside the outline.
    expect(Math.max(...[0.05, 0.1, 0.15].map((t) => at(lerp(U(58), U(50), t))))).toBeGreaterThan(0.9);
  });

  it('has one jawline profile: no inward hinge quad, an outward skirt on the jaw sides, mask-gated', () => {
    expect(script).not.toContain('JAW_HINGE');
    expect(script).not.toContain('jawHinge');
    // Skirt: same landmarks as the ribbon on both sides to the chin, strength = the ribbon's own on the outline.
    expect(script).toContain('const JAW_SKIRT = [JAW_RIBBON.ids, [323, 361, 288, 397, 365, 379, 378, 400, 377, 152]];');
    expect(script).toContain('let jawSkirtW = JAW_RIBBON.weight.map((v, i) => v * JAW_RIBBON.edge[i] * JAW_SKIRT_TAPER[i]);');
    expect(script).toContain('jawSkirtW = prof.weight.map((v, i) => v * prof.edge[i] * JAW_SKIRT_TAPER[i]);');
    expect(script).toContain('if (nx * (sx[v] - sx[4]) * W + ny * (sy[v] - sy[4]) * H < 0) { nx = -nx; ny = -ny; }');
    expect(script).toContain("contourA *= uFoundSkinOn > 0.5 ? texture2D(uFoundSkin, suv).r : 0.0;");
    expect(script).toContain('if (jawShadeOn && foundSkinReady && TUNING.jawSkirt > 0)');
    expect(script).toContain("const jawEdge = !!(coT && coT[0] && coT[0].t === 'ribbon');");
    expect(script).toContain('rgba2[i * 4 + 1] = Math.round(clamp01(k[i] * (jawEdge ? 1 : inside)) * 255);');
    expect(script).toContain('rgba2[i * 4] = Math.round(clamp01(h[i] * inside) * 255);');
    expect(script).toContain('if (uJawCullOn > 0.5)');
    expect(script).toContain('const jawYaw = (sz[234] - sz[454]) / jawSpan;');
    expect(script).toContain('contourA *= max(texture2D(uFoundSkin, suv).r, vUv.x < 0.5 ? uJawFloor.x : uJawFloor.y);');
    expect(script).toContain('gl.uniform2f(u.uJawFloor, jawFloor * jawOcc[0], jawFloor * jawOcc[1]);');
    expect(script).toContain('jawOcc[side] = smooth01(0.8, 1.0, hit / JAW_COVER_PTS[side].length);');
    expect(script).toContain("const jawline = makeup.contour && makeup.contour.geometry && makeup.contour.geometry.contourStyle === 'jawline';");
    expect(script).toContain('contourDebug: false');
  });

  // Face shape (11-05, user request): a probability from 8 landmark features, shown by name with the percentage.
  it('computes the face-shape features and probabilities exactly like the Python the model was fitted with', () => {
    const { faceShapeFeatures, shapeProbs } = pageShape();
    for (const c of parity as ParityCase[]) {
      const f = faceShapeFeatures(c.x, c.y, c.z, c.w, c.h);
      for (const k of Object.keys(c.features)) expect(f[k]).toBeCloseTo(c.features[k], 4);
      const p = shapeProbs(modelJson, f);
      p.forEach((v: number, i: number) => expect(v).toBeCloseTo(c.probs[i], 5));
      expect(p.reduce((a: number, b: number) => a + b, 0)).toBeCloseTo(1, 6);
    }
  });

  it('embeds exactly the numbers of research/face_shape/model.json', () => {
    const m = script.match(/faceShapeModel: (\{.*\}),\n/);
    expect(m).not.toBeNull();
    expect(JSON.parse((m as RegExpMatchArray)[1])).toEqual(modelJson);
    expect(modelJson.classes).toEqual([...FACE_SHAPES]);
  });

  it('measures only on frontal frames and reports the class key and probability, nothing else', () => {
    expect(script).toContain('roll <= (acc.loose ? TUNING.faceFitRollLooseDeg : TUNING.faceFitRollDeg)');
    expect(script).toContain("post({ type: 'face_fit', ratios:");
    expect(script).toContain('rec: out.rec, shape, conf: Math.round(conf * 100) / 100 });');
    expect(script).not.toMatch(/face_fit[^\n]*(landmarks|image|frame)/);
  });

  it('blends the shading rules by probability: a longer or narrower chin means less chin shade, no jumps', () => {
    const w = (probs: number[]) => jawMask(probs).prof.weight[9];
    const onehot = (k: string) => modelJson.classes.map((c: string) => (c === k ? 1 : 0));
    expect(w(onehot('oblong'))).toBeLessThan(w(onehot('round')));
    expect(w(onehot('heart'))).toBeLessThan(w(onehot('oblong')));
    expect(w(onehot('oval'))).toBeLessThan(w(onehot('round')));
    // Halfway between two classes lies between them.
    const half = modelJson.classes.map((c: string) => (c === 'round' || c === 'heart' ? 0.5 : 0));
    expect(w(half)).toBeCloseTo((w(onehot('round')) + w(onehot('heart'))) / 2, 6);
    // The square rule keeps the angle lighter than round and blends wider around it.
    const sq = jawMask(onehot('square')).prof, ro = jawMask(onehot('round')).prof;
    expect(sq.weight[2]).toBeLessThan(ro.weight[2]);
    expect(sq.reach[2]).toBeGreaterThan(ro.reach[2]);
    // Unmeasured: the plain ribbon.
    expect(jawMask(null).prof.weight).toEqual(pageShape().JAW_RIBBON.weight);
  });

  it('shows the shape name with its probability on the shading chip, in all four languages', () => {
    for (const key of ['measuring', 'fallback', 'result', 'note']) for (const dict of [en, ko, ja, zh]) expect(dict).toHaveProperty(['ar.faceShape.' + key]);
    for (const shape of FACE_SHAPES) {
      for (const dict of [en, ko, ja, zh] as Record<string, string>[]) {
        expect(dict['ar.faceShape.name.' + shape]).toBeTruthy();
        expect(dict['ar.faceShape.rule.' + shape]).toBeTruthy();
      }
    }
    expect(ko['ar.faceShape.result']).toContain('{pct}');
  });

  // The real measurement step, driven by a simulated camera (11-05 /ar-debug: "judge within 3 s").
  function measureHarness() {
    const cut = (from: string, to: string) => {
      const a = script.indexOf(from);
      return script.slice(a, script.indexOf(to, a));
    };
    const src = [
      cut('  const TUNING = {', '\n  };\n') + '\n  };',
      'function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }',
      cut('  const JAW_RIBBON = {', '  // end faceShape'),
      cut('  function faceFitFrom(r) {', '  function paintMasks() {'),
      'const sx = new Float32Array(478), sy = new Float32Array(478), sz = new Float32Array(478); const W = 720, H = 1280;',
      'const posted = []; const post = (m) => posted.push(m);',
      "let faceFitAcc = null, faceFitState = null, faceFitSeenAt = 0, faceFitKey = 'default'; let faceFitMs = 0, faceFitUsed = '';",
      cut("  let faceFitStatus = 'default'", '  function faceFitStep(now) {'),
      cut('  function faceFitStep(now) {', '  let masks = null;'),
      'return { sx, sy, sz, posted, step: faceFitStep, state: () => faceFitState, status: () => faceFitStatus, TUNING };',
    ].join('\n');
    return new Function(src)();
  }
  function setFace(h: ReturnType<typeof measureHarness>, c: ParityCase, noseShift = 0) {
    // Parity landmarks are normalised for c.w × c.h; rescale x / y so the face keeps its pixel shape in a 720 × 1280 frame.
    for (let i = 0; i < 468; i++) {
      h.sx[i] = 0.5 + (c.x[i] - 0.5) * (c.w / 720);
      h.sy[i] = 0.5 + (c.y[i] - 0.5) * (c.h / 1280);
      h.sz[i] = c.z[i] * (c.w / 720);
    }
    h.sx[1] += noseShift;
  }

  it('judges a frontal face in well under 3 s even at a segmenter-loaded 8 fps', () => {
    const h = measureHarness();
    setFace(h, (parity as ParityCase[])[0]);
    let t = 1000;
    while (!h.state() && t < 10000) { h.step(t); t += 125; }
    expect(h.state()).not.toBeNull();
    expect(t - 1000).toBeLessThanOrEqual(1500);
    const fit = h.posted.find((m: { type: string }) => m.type === 'face_fit');
    expect(FACE_SHAPES).toContain(fit.shape);
    expect(h.status()).toBe('personalized');
  });

  it('still answers within 3 s when the head is a little turned (looser gate after the deadline)', () => {
    const h = measureHarness();
    setFace(h, (parity as ParityCase[])[0], 0.03); // yaw ratio 1.22: outside the strict gate, inside the loose one
    let t = 1000;
    while (!h.state() && t < 10000) { h.step(t); t += 125; }
    expect(h.state()).not.toBeNull();
    expect(t - 1000).toBeLessThanOrEqual(3000);
  });

  it('averages landmarks, so identical frames give exactly the single-frame features', () => {
    const h = measureHarness();
    const c = (parity as ParityCase[])[0];
    setFace(h, c);
    for (let k = 0; k < 10; k++) h.step(1000 + 125 * k);
    const { faceShapeFeatures } = pageShape();
    const single = faceShapeFeatures(h.sx, h.sy, h.sz, 720, 1280);
    expect(h.state().ratios.cheekWide).toBeCloseTo(single.cheekWide, 5);
    expect(h.state().ratios.faceLong).toBeCloseTo(single.faceLong, 5);
  });

  it('starts over when the face leaves mid-measurement, instead of tripping the deadline', () => {
    const h = measureHarness();
    setFace(h, (parity as ParityCase[])[0]);
    h.step(1000); h.step(1125);
    h.step(5000);   // back after a long gap
    expect(h.state()).toBeNull();
  });

  it('never blocks the default shading: a face that is never frontal ends in fallback, then personalizes on a later glance', () => {
    const h = measureHarness();
    const c = (parity as ParityCase[])[0];
    setFace(h, c, 0.06); // yaw ratio ~1.5: outside even the loose gate
    let t = 1000;
    for (; t < 1000 + 4000; t += 125) h.step(t);
    expect(h.state()).toBeNull();
    expect(h.status()).toBe('fallback');
    expect(h.posted.map((m: { type: string; state?: string }) => m.state).filter(Boolean)).toEqual(['analyzing', 'fallback']);
    setFace(h, c); // now looks straight
    const back = t;
    while (!h.state() && t < back + 5000) { h.step(t); t += 125; }
    expect(h.status()).toBe('personalized');
    expect(t - back).toBeLessThanOrEqual(1500);
  });

  it('paints the default ribbon from the first tracked frame and steps into the personalized one', () => {
    // Before any result the repaint key is the default one, so the ribbon is painted at once (no wait for the analysis).
    expect(script).toContain("(faceFitState ? faceFitState.rec.join() + '|' + faceFitState.shape + '|' + blend : 'none')");
    expect(script).toContain('masks.repaintHlContour(hlStyle, coStyle, faceFitState ? Object.assign({}, faceFitState.fit, { blend }) : null);');
    // t = 0 is exactly the default, t = 1 the personalized profile, steps lie in between: no jump.
    const one = modelJson.classes.map((c: string) => (c === 'heart' ? 1 : 0));
    const p0 = jawMask(one, 0).prof, ph = jawMask(one, 0.5).prof, p1 = jawMask(one, 1).prof, pd = jawMask(null).prof;
    expect(p0.weight).toEqual(pd.weight);
    expect(p0.reach).toEqual(pd.reach);
    for (let i = 1; i < 10; i++) {
      expect(ph.weight[i]).toBeCloseTo((p0.weight[i] + p1.weight[i]) / 2, 6);
      expect(ph.reach[i]).toBeCloseTo((p0.reach[i] + p1.reach[i]) / 2, 6);
    }
    expect(p1.weight[9]).toBeLessThan(p0.weight[9]); // the personalized design really differs (narrow chin: less chin shade)
  });

  it('reports default / analyzing / personalized / fallback to the app and the HUD', () => {
    expect(script).toContain("post({ type: 'face_fit_status', state: st });");
    expect(script).toContain("'ms  ' + faceFitStatus + ' blend ' + f(jawBlendNow) + '  paint '");
    expect(parseFaceFitStatus({ state: 'fallback' })).toBe('fallback');
    expect(parseFaceFitStatus({ state: 'done' })).toBeNull();
  });

  it('parses the shape of a face_fit message and rejects anything else', () => {
    expect(parseFaceShape({ shape: 'round', conf: 0.72 })).toEqual({ shape: 'round', conf: 0.72 });
    expect(parseFaceShape({ shape: 'oval', conf: 7 })).toEqual({ shape: 'oval', conf: 1 });
    expect(parseFaceShape({ shape: 'diamond', conf: 0.5 })).toBeNull();
    expect(parseFaceShape({ shape: 'round' })).toBeNull();
    expect(parseFaceShape({ shape: 'round', conf: Number.NaN })).toBeNull();
    expect(parseFaceShape({})).toBeNull();
  });

  it('keeps the volume terms off by default and gates the light direction by its confidence', () => {
    expect(script).toContain('hlContourVolume: false');
    expect(script).toContain('TUNING.hlContourVolume ? TUNING.volumeGain[0] : 0');
    expect(script).toContain('uLightConf * uVolLight');
    expect(script).toContain('contourA *= clamp(1.0 + uVolume.x * (0.7 - volFace), 0.6, 1.5);');
  });
});
