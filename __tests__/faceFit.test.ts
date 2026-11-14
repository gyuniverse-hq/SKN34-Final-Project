import { FACE_TRACKER_HTML } from '@/components/ar/faceTrackerHtml';
import { FACE_UV } from '@/components/ar/faceUV';
import {
  CONTOUR_STYLE_IDS,
  FACE_FIT_STATUSES,
  FACE_SHAPES,
  HIGHLIGHTER_STYLE_IDS,
  parseFaceFit,
  parseFaceFitStatus,
  parseFaceShape,
} from '@/lib/faceFit';
import { en } from '@/lib/i18n/en';
import { ja } from '@/lib/i18n/ja';
import { ko } from '@/lib/i18n/ko';
import { zh } from '@/lib/i18n/zh';
import modelJson from '@/research/face_shape/model.json';
import parity from './fixtures/faceShapeParity.json';

type ParityCase = { w: number; h: number; x: number[]; y: number[]; z: number[]; features: Record<string, number>; probs: number[] };

const script = FACE_TRACKER_HTML;

// The project has no Node typings; read the screen source (to prove the chips are gone) through jest's real modules.
declare const __dirname: string;
const nodeFs = jest.requireActual('fs') as { readFileSync: (path: string, encoding: string) => string };
const nodePath = jest.requireActual('path') as { join: (...parts: string[]) => string };

describe('face-fit hints', () => {
  it('keeps only known hint keys and rejects malformed messages', () => {
    expect(parseFaceFit({ rec: ['cheek_wide', 'face_long'] })).toEqual(['cheek_wide', 'face_long']);
    expect(parseFaceFit({ rec: ['round_face', 'balanced'] })).toEqual(['balanced']);
    expect(parseFaceFit({ rec: ['oval'] })).toBeNull();
    expect(parseFaceFit({})).toBeNull();
  });

  it('parses the face shape name and the shading status of the page, and rejects anything else', () => {
    expect(parseFaceShape({ shape: 'round' })).toBe('round');
    expect(parseFaceShape({ shape: 'diamond' })).toBeNull();
    expect(parseFaceShape({})).toBeNull();
    for (const state of FACE_FIT_STATUSES) expect(parseFaceFitStatus({ state })).toBe(state);
    expect(parseFaceFitStatus({ state: 'done' })).toBeNull();
    expect(parseFaceFitStatus({})).toBeNull();
  });
});

describe('face-fit page', () => {
  const S = 1024;
  const U = (i: number): [number, number] => [FACE_UV[2 * i] * S, FACE_UV[2 * i + 1] * S];
  const lerp = (a: number[], b: number[], t: number) => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
  const cut = (from: string, to: string) => {
    const a = script.indexOf(from);
    expect(a).toBeGreaterThanOrEqual(0);
    return script.slice(a, script.indexOf(to, a));
  };
  // The page's own shading data and face-shape code, cut out of the script (no copy to drift).
  function page() {
    const src = cut('  const JAW_RIBBON = {', '  function paintMasks() {');
    return new Function(
      src +
        '; return { JAW_RIBBON, NOSE_SHADE, CHEEK_SHADE, ribbonField, ribbonFieldGen, drive, faceShapeFeatures, shapeProbs, shadeProfile, SHAPE_RULES };',
    )();
  }
  const midU = [1, 4, 5, 6, 168, 152, 10, 0, 17].reduce((acc, i) => acc + U(i)[0], 0) / 9;
  const jawRef = Math.hypot(U(123)[0] - U(147)[0], U(123)[1] - U(147)[1]);
  const noseRef = Math.hypot(U(6)[0] - U(122)[0], U(6)[1] - U(122)[1]);

  // One shading part on both sides, run on the real atlas (the canvas cut of the nose is checked in the headless browser).
  function partMask(part: 'jaw' | 'nose' | 'cheek', probs: number[] | null = null, t = 1) {
    const { JAW_RIBBON, NOSE_SHADE, CHEEK_SHADE, ribbonField, shadeProfile } = page();
    const R = part === 'jaw' ? JAW_RIBBON : part === 'nose' ? NOSE_SHADE : CHEEK_SHADE;
    const prof = shadeProfile(part, modelJson.classes, probs, t);
    const pts: number[][] = part === 'jaw' ? R.ids.map(U) : R.pts.map((q: number[]) => lerp(U(q[0]), U(q[1]), q[2]));
    const unit = part === 'nose' ? noseRef : jawRef;
    const reach = prof.reach.map((v: number) => v * unit);
    const out = new Float32Array(S * S);
    ribbonField(pts, prof.weight, reach, prof.core, S, out);
    ribbonField(pts.map((q) => [2 * midU - q[0], q[1]]), prof.weight, reach, prof.core, S, out);
    const at = (p: number[]) => out[Math.round(p[1]) * S + Math.round(p[0])];
    return { R, pts, at, prof };
  }

  it('has a template for every style id the app offers', () => {
    for (const id of HIGHLIGHTER_STYLE_IDS) expect(script).toContain('    ' + id + ': [');
    for (const id of CONTOUR_STYLE_IDS) expect(script).toContain('    ' + id + ': [');
    expect(CONTOUR_STYLE_IDS).toEqual(['jawline', 'nose']);
    expect(script).toContain("jawline: [{ t: 'ribbon' }]");
  });

  it('redraws only when the style or the measurement changes, and reuses the cached shading mask for the highlighter', () => {
    expect(script).toContain('if (key !== faceFitKey && masks && masks.repaintHlContour)');
    expect(script).toContain('const h = hlT ? layer(() => drawTemplate(hlT, fit), TUNING.hlFeatherPx) : layout ? layer(() => drawHlFace(layout.shape, layout.areas), TUNING.hlFeatherPx) : highlight;');
    expect(script).toContain('const g = currentAuto();');
    expect(script).toContain("const k = jawEdge ? jawRibbon(fit) : contourStyle === 'nose' ? noseShade(fit) : coT ? layer(() => drawTemplate(coT, fit), TUNING.contourFeatherPx) : contour;");
  });

  // ── jawline ──
  it('paints the jawline as one ribbon from under the ear to the chin, continuous on both sides', () => {
    const { R, at } = partMask('jaw');
    expect(R.ids[0]).toBe(93);
    expect(R.ids[R.ids.length - 1]).toBe(152);
    expect(R.weight[0]).toBe(0);
    // Just inside the outline, every jaw point from 132 round the chin to 361 keeps at least half strength: no gap, no seam.
    const left = [132, 58, 172, 136, 150, 149, 176, 148, 152];
    const right = [377, 400, 378, 379, 365, 397, 288, 361];
    for (const i of left) expect(at(lerp(U(i), U(50), 0.06))).toBeGreaterThan(0.5);
    for (const i of right) expect(at(lerp(U(i), U(280), 0.06))).toBeGreaterThan(0.5);
  });

  it('fades the jawline inward with no hard edge and stays off the cheek, lips and ear', () => {
    const { at } = partMask('jaw');
    const section = [0, 0.1, 0.2, 0.3, 0.4, 0.5].map((t) => at(lerp(U(58), U(50), t)));
    expect(section[0]).toBeGreaterThan(0.9);
    for (let j = 1; j < section.length; j++) expect(section[j]).toBeLessThanOrEqual(section[j - 1] + 1e-6);
    expect(section.some((v) => v > 0.1 && v < 0.9)).toBe(true);
    expect(section[section.length - 1]).toBe(0);
    for (const i of [50, 280, 147, 123, 17, 18, 61, 291, 199, 234]) expect(at(U(i))).toBe(0);
    expect(at(U(177))).toBeLessThan(0.2);
  });

  it('has one jawline profile: no inward hinge quad, an outward skirt that starts at the ribbon weight, mask-gated', () => {
    expect(script).not.toContain('JAW_HINGE');
    expect(script).not.toContain('jawHinge');
    expect(script).toContain('const JAW_SKIRT = [JAW_RIBBON.ids.slice(0, NSK), [323, 361, 288, 397, 365, 379, 378]];');
    expect(script).toContain('const JAW_SKIRT_W = JAW_RIBBON.weight.slice(0, NSK).map((v, i) => (i === NSK - 1 ? 0 : v));');
    expect(script).toContain('if (nx * (sx[v] - sx[4]) * W + ny * (sy[v] - sy[4]) * H < 0) { nx = -nx; ny = -ny; }');
    expect(script).toContain('contourA *= uFoundSkinOn > 0.5 ? texture2D(uFoundSkin, fuv).r : 0.0;');
    expect(script).toContain('if (jawShadeOn && foundSkinReady && TUNING.jawSkirt > 0)');
    expect(script).toContain('rgba2[i * 4] = Math.round(clamp01(h[i] * inside) * 255);');
    expect(script).toContain('if (uJawCullOn > 0.5)');
    expect(script).toContain('const jawYaw = (sz[234] - sz[454]) / jawSpan;');
    expect(script).toContain('contourA *= mix(1.0, max(texture2D(uFoundSkin, fuv).r, vUv.x < 0.5 ? uJawFloor.x : uJawFloor.y), jawZone);');
    expect(script).toContain('gl.uniform2f(u.uJawFloor, jawFloor * jawOcc[0], jawFloor * jawOcc[1]);');
    expect(script).toContain('jawOcc[side] = smooth01(0.8, 1.0, hit / JAW_COVER_PTS[side].length);');
    expect(script).toContain('const jawline = !!makeup.contour;');
    expect(script).toContain('contourDebug: false');
  });

  // ── nose: side wall of the bridge + the groove outside the nostril wing ──
  it('runs the nose shading from under the brow head down the side wall and round the outside of the nostril wing', () => {
    const { R, pts, at } = partMask('nose');
    expect(R.pts[0].slice(0, 2)).toEqual([193, 55]);
    expect(R.weight[0]).toBe(0);
    expect(R.weight[R.weight.length - 1]).toBe(0);
    for (let j = 1; j < pts.length - 2; j++) expect(at(lerp(pts[j], pts[j + 1], 0.5))).toBeGreaterThan(0.5);
    for (const q of [lerp(U(102), U(129), 0.25), lerp(U(64), U(203), 0.3)]) expect(at(q)).toBeGreaterThan(0.6);
    const side = [0, 0.4, 0.7, 0.9, 1.1].map((t) => at(lerp(pts[3], [pts[3][0] - 30, pts[3][1]], t / 1.1)));
    expect(side.some((v) => v > 0.15 && v < 0.75)).toBe(true);
  });

  it('keeps the nose shading off the cheek, the mouth and the jaw', () => {
    const { at } = partMask('nose');
    for (const i of [50, 280, 36, 266, 142, 371, 205, 425, 203, 423, 0, 13, 17, 61, 291, 164, 152, 33, 263]) expect(at(U(i))).toBe(0);
  });

  // ── cheek hollow (11-06): under the cheekbone, from in front of the ear toward the mouth corner ──
  it('paints a soft hollow under the cheekbone that fades out before the mouth corner', () => {
    const { R, pts, at } = partMask('cheek');
    expect(R.pts[0].slice(0, 2)).toEqual([137, 227]);
    expect(R.weight[R.weight.length - 1]).toBe(0);
    for (let j = 0; j < pts.length - 2; j++) expect(at(lerp(pts[j], pts[j + 1], 0.5))).toBeGreaterThan(0.3);
    // Not on the cheekbone / blush centre, the eye, the mouth, the nose or the jaw ribbon's chin.
    for (const i of [50, 280, 116, 117, 118, 119, 123, 33, 133, 159, 145, 61, 291, 0, 17, 13, 14, 152, 6, 4, 234]) expect(at(U(i))).toBeLessThan(0.1);
    // A soft band, not a line: strength falls off gradually across it.
    const across = [0, 0.3, 0.6, 0.9, 1.2].map((t) => at([pts[2][0], pts[2][1] + t * 0.85 * jawRef]));
    expect(across.some((v) => v > 0.1 && v < 0.7)).toBe(true);
  });

  it('keeps the turn cull and the lagging-mask floor to the jaw: the nose box is outside it, the cheek hollow and the jaw inside', () => {
    expect(script).toContain("'    float jawZone = 1.0 - smoothstep(0.28, 0.34, vUv.y) * (1.0 - smoothstep(0.14, 0.18, abs(vUv.x - 0.5)));',");
    expect(script).toContain("'    contourA *= 1.0 - max(hideL, hideR) * jawZone;',");
    // The skin-mask gate (with its lagging-mask floor) applies in the jaw zone only: the nose bridge is never cut by it.
    expect(script).toContain('contourA *= mix(1.0, max(texture2D(uFoundSkin, fuv).r, vUv.x < 0.5 ? uJawFloor.x : uJawFloor.y), jawZone);');
    const ss = (a: number, b: number, x: number) => { const r = Math.min(1, Math.max(0, (x - a) / (b - a))); return r * r * (3 - 2 * r); };
    const jawZone = (u: number, v: number) => 1 - ss(0.28, 0.34, v) * (1 - ss(0.14, 0.18, Math.abs(u - 0.5)));
    const nose = partMask('nose').at, jaw = partMask('jaw').at, cheek = partMask('cheek').at;
    let painted = 0;
    for (let y = 0; y < S; y += 4) for (let x = 0; x < S; x += 4) {
      if (nose([x, y]) > 0.02) { painted++; expect(jawZone(x / S, y / S)).toBeLessThan(0.02); }
      if (jaw([x, y]) > 0.02) expect(jawZone(x / S, y / S)).toBeGreaterThan(0.98);
      // The hollow's faint tail touches the nose box edge; everything strong in it sits in the jaw zone (turn cull applies).
      if (cheek([x, y]) > 0.3) expect(jawZone(x / S, y / S)).toBeGreaterThan(0.9);
    }
    expect(painted).toBeGreaterThan(100);
  });

  // ── the auto repaint, run as written in the page with small stand-ins ──
  function repaintWith(contourStyle: string) {
    const a = script.indexOf('    function repaintHlContour(hlStyle, contourStyle, fit, layout) {');
    const b = script.indexOf('    return {\n      size: S, rgba, rgba2, rgba3, lipVerts, skinVerts, repaintHlContour,');
    const calls = { layer: 0, jaw: 0, nose: 0, auto: 0 };
    const autoField = new Uint8Array([230, 100, 0, 77]);
    const rgba2 = new Uint8Array(16);
    const make = new Function(
      'S', 'TUNING', 'HL_TEMPLATES', 'CONTOUR_TEMPLATES', 'layer', 'drawTemplate', 'jawRibbon', 'noseShade', 'currentAuto', 'contour', 'highlight', 'faceFill', 'rgba2', 'clamp01',
      script.slice(a, b) + '; return repaintHlContour;',
    );
    const repaint = make(
      2, { contourCoverage: 0.8, contourFeatherPx: 28, hlFeatherPx: 18 }, {}, { jawline: [{ t: 'ribbon' }], nose: [{ t: 'noseShade' }] },
      () => { calls.layer++; return [0, 0, 0, 0]; }, () => undefined,
      () => { calls.jaw++; return [0.9, 0.9, 0, 0.7]; }, () => { calls.nose++; return [0, 0, 0.8, 0.8]; },
      () => { calls.auto++; return autoField; },
      [0.3, 0.3, 0.3, 0.3], [0.2, 0.2, 0.2, 0.2], [1, 1, 1, 0.5], rgba2, (x: number) => Math.min(1, Math.max(0, x)),
    );
    repaint('', contourStyle, null);
    return { g: [0, 1, 2, 3].map((i) => rgba2[i * 4 + 1]), r: [0, 1, 2, 3].map((i) => rgba2[i * 4]), calls };
  }

  it('paints the shading zone from the cached mask, so a highlighter change never recomputes it', () => {
    const auto = repaintWith('auto');
    expect(auto.g).toEqual([230, 100, 0, 77]);   // exactly the cached shading (jaw + nose + cheek), not scaled by the outline fade again
    expect(auto.r).toEqual([51, 51, 51, 0]);     // highlighter (0.2) fades at the outline (pixel 3: faceFill 0.5 -> 0)
    expect(auto.calls).toEqual({ layer: 0, jaw: 0, nose: 0, auto: 1 });
    // The old single-style paths are unchanged (looks and chat may still name them).
    const only = repaintWith('nose');
    expect(only.g).toEqual([0, 0, 204, 0]);
    const jaw = repaintWith('jawline');
    expect(jaw.g).toEqual([230, 230, 0, 179]);
    expect(script).toContain("const coStyle = contourZ ? 'auto' : '';");
    expect(script).toContain('const jawShadeOn = !!contourZ;');
    expect(script).toContain('const jawShade = !!contourZ;');
  });

  it('builds the whole shading channel from jaw + nose + cheek, the ribbon keeping the outline and the others fading at it', () => {
    expect(script).toContain('const jk = yield* jawRibbonGen(shadeProfile(\'jaw\', cls, probs, 1));');
    expect(script).toContain('const nk = yield* noseShadeGen(shadeProfile(\'nose\', cls, probs, 1));');
    // The cheek hollow is a switch (off until it has been seen on a device): the default shading is jaw + nose.
    expect(script).toContain('cheekHollow: false,');
    expect(script).toContain('const ck = TUNING.cheekHollow ? yield* cheekShadeGen(shadeProfile(\'cheek\', cls, probs, 1)) : null;');
    expect(script).toContain('g[i] = Math.round(clamp01(Math.max(jk[i], (ck ? Math.max(nk[i], ck[i]) : nk[i]) * inside * scale)) * 255);');
    expect(script).toContain('const scale = Math.min(1, TUNING.contourCoverage / 0.85);');
  });

  // ── time-sliced masks ──
  it('slices the ribbon and the blur into many short steps that give exactly the result of the one-shot run', () => {
    const { ribbonFieldGen, ribbonField, JAW_RIBBON } = page();
    const reach = JAW_RIBBON.reach.map((v: number) => v * jawRef);
    const side = JAW_RIBBON.ids.map(U);
    const sliced = new Float32Array(S * S);
    const gen = ribbonFieldGen(side, JAW_RIBBON.weight, reach, JAW_RIBBON.core, S, sliced);
    let steps = 0;
    for (let r = gen.next(); !r.done; r = gen.next()) steps++;
    const whole = new Float32Array(S * S);
    ribbonField(side, JAW_RIBBON.weight, reach, JAW_RIBBON.core, S, whole);
    expect(steps).toBeGreaterThan(40);          // short slices: a few ms each on a phone
    expect(sliced).toEqual(whole);

    const blurSrc = new Function('clamp', cut('  function* boxBlurGen', '  function boxBlurRect') + '; return boxBlurGen;')(
      (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v)),
    );
    const img = new Float32Array(256 * 256);
    for (let i = 0; i < img.length; i++) img[i] = ((i * 7919) % 97) / 97;
    const g2 = blurSrc(img.slice(), 256, 256, 6);
    let blurSteps = 0;
    let r2 = g2.next();
    for (; !r2.done; r2 = g2.next()) blurSteps++;
    const g3 = blurSrc(img.slice(), 256, 256, 6);
    let r3 = g3.next();
    while (!r3.done) r3 = g3.next();
    expect(blurSteps).toBeGreaterThan(8);
    expect(r2.value).toEqual(r3.value);
    // The shared blur (lips, blush, ...) is the original synchronous code; the sliced copy must give exactly its result.
    const syncBlur = new Function('clamp', cut('  function boxBlurRect', '  // ── Face-fit style templates') + '; return boxBlurRect;')(
      (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v)),
    );
    expect(script).not.toContain('function boxBlurRect(src, W, H, r) { return drive(');
    expect(syncBlur(img.slice(), 256, 256, 6)).toEqual(r3.value);
  });

  it('runs the background jobs a few ms per frame, never blocks, and drops a job that throws', () => {
    expect(script).toContain('if (masks && masks.stepJob) masks.stepJob(TUNING.jobBudgetMs);');
    expect(script).toContain('masks.startDefault();');
    const src = cut('    function startJob(label, gen) {', '    // The default shading is needed from the first tracked frame');
    const make = new Function('performance', 'jawRibbonMsRef', `let autoDefaultG = null, autoPersonalG = null, job = null, lastJob = null; let jawRibbonMs = 0;\n${src}\nreturn { startJob, stepJob, state: () => ({ autoDefaultG, autoPersonalG, job, lastJob }) };`);
    let now = 0;
    const perf = { now: () => (now += 1.5) };   // every generator step "costs" 1.5 ms
    const j = make(perf, null);
    function* work(n: number) { for (let i = 0; i < n; i++) yield; return new Uint8Array([n]); }
    j.startJob('default', work(20));
    j.stepJob(4);
    expect(j.state().job.steps).toBeLessThanOrEqual(3);   // 4 ms budget: stops after a few steps, the frame goes on
    for (let k = 0; k < 20 && j.state().job; k++) j.stepJob(4);
    expect(j.state().autoDefaultG).toEqual(new Uint8Array([20]));
    expect(j.state().lastJob.label).toBe('default');
    expect(j.state().lastJob.maxStep).toBeGreaterThan(0);   // the longest single step is measured (HUD): it decides whether a frame drops
    function* bad() { yield; throw new Error('boom'); }
    j.startJob('personal', bad());
    expect(() => { j.stepJob(4); j.stepJob(4); }).not.toThrow();
    expect(j.state().job).toBeNull();
    expect(j.state().autoPersonalG).toBeNull();
  });

  it('reads back and blurs only the rectangle the nose cut lives in, in short steps', () => {
    expect(script).toContain('function* layerRectGen(draw, feather, x0, y0, w, h) {');
    expect(script).toContain('const d = c.getImageData(x0, y0, w, h).data;');
    expect(script).toContain('}, Math.round(R.cutFeather * nw), rx0, ry0, rw, rh);');
    expect(script).toContain('if ((i & 0x7fff) === 0x7fff) yield;');
    // The rectangle covers every cut point on both sides plus the blur: the cut never ends in a hard edge.
    const { NOSE_SHADE: R } = page();
    const nw = noseRef, pad = Math.ceil(R.midWidth * nw + R.cutFeather * nw) + 8;
    const xs = R.cut.concat(R.mid).flatMap((id: number) => [U(id)[0], 2 * midU - U(id)[0]]);
    expect(Math.max(0, Math.floor(Math.min(...xs) - pad))).toBeGreaterThan(0);
    expect(Math.ceil(Math.max(...xs) + pad) - Math.floor(Math.min(...xs) - pad)).toBeLessThan(S * 0.6);   // well under the full atlas
  });

  // ── face shape ──
  it('computes the face-shape features and probabilities exactly like the Python the model was fitted with', () => {
    const { faceShapeFeatures, shapeProbs } = page();
    for (const c of parity as ParityCase[]) {
      const f = faceShapeFeatures(c.x, c.y, c.z, c.w, c.h);
      for (const k of Object.keys(c.features)) expect(f[k]).toBeCloseTo(c.features[k], 4);
      const p = shapeProbs(modelJson, f);
      p.forEach((v: number, i: number) => expect(v).toBeCloseTo(c.probs[i], 5));
      expect(p.reduce((a: number, b: number) => a + b, 0)).toBeCloseTo(1, 6);
    }
  });

  it('embeds exactly the numbers of research/face_shape/model.json and names only the classes the app can show', () => {
    const m = script.match(/faceShapeModel: (\{.*\}),\n/);
    expect(m).not.toBeNull();
    expect(JSON.parse((m as RegExpMatchArray)[1])).toEqual(modelJson);
    expect(modelJson.classes).toEqual([...FACE_SHAPES]);
    expect(Object.keys(page().SHAPE_RULES)).toEqual([...FACE_SHAPES]);
  });

  it('blends the shading rules by probability for all three parts: continuous, t = 0 is the default, no jumps', () => {
    const { shadeProfile, JAW_RIBBON, NOSE_SHADE, CHEEK_SHADE } = page();
    const onehot = (k: string) => modelJson.classes.map((c: string) => (c === k ? 1 : 0));
    const base = { jaw: JAW_RIBBON, nose: NOSE_SHADE, cheek: CHEEK_SHADE } as Record<string, { weight: number[]; reach: number[]; core: number }>;
    for (const part of ['jaw', 'nose', 'cheek']) {
      // Unmeasured or t = 0: exactly the default shape.
      expect(shadeProfile(part, modelJson.classes, null, 1).weight).toEqual(base[part].weight);
      expect(shadeProfile(part, modelJson.classes, onehot('oblong'), 0).weight).toEqual(base[part].weight);
      expect(shadeProfile(part, modelJson.classes, onehot('oblong'), 0).reach).toEqual(base[part].reach);
      // A halfway t is exactly halfway between the default and the personalized shape.
      const p1 = shadeProfile(part, modelJson.classes, onehot('heart'), 1), ph = shadeProfile(part, modelJson.classes, onehot('heart'), 0.5);
      for (let i = 1; i < p1.weight.length; i++) {
        expect(ph.weight[i]).toBeCloseTo((base[part].weight[i] + p1.weight[i]) / 2, 6);
        expect(ph.reach[i]).toBeCloseTo((base[part].reach[i] + p1.reach[i]) / 2, 6);
      }
      // Halfway between two classes lies between them.
      const half = modelJson.classes.map((c: string) => (c === 'round' || c === 'heart' ? 0.5 : 0));
      const w = (pr: number[]) => shadeProfile(part, modelJson.classes, pr, 1).reach[3];
      expect(w(half)).toBeCloseTo((w(onehot('round')) + w(onehot('heart'))) / 2, 6);
    }
    // The user's table: a longer or narrower chin means less chin shade; a square jaw keeps the angle lighter but blends wider.
    const chin = (k: string) => shadeProfile('jaw', modelJson.classes, onehot(k), 1).weight[9];
    expect(chin('oblong')).toBeLessThan(chin('round'));
    expect(chin('heart')).toBeLessThan(chin('oblong'));
    const sq = shadeProfile('jaw', modelJson.classes, onehot('square'), 1), ro = shadeProfile('jaw', modelJson.classes, onehot('round'), 1);
    expect(sq.weight[2]).toBeLessThan(ro.weight[2]);
    expect(sq.reach[2]).toBeGreaterThan(ro.reach[2]);
    // The personalized design really differs from the default in every part.
    for (const part of ['jaw', 'nose', 'cheek']) {
      const a = shadeProfile(part, modelJson.classes, onehot('round'), 1), b = shadeProfile(part, modelJson.classes, onehot('oval'), 1);
      expect(a.reach).not.toEqual(b.reach);
    }
  });

  // ── the measurement step, driven by a simulated camera (8 fps: the segmenter is on) ──
  function measureHarness() {
    const src = [
      cut('  const TUNING = {', '\n  };\n') + '\n  };',
      'function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }',
      cut('  const JAW_RIBBON = {', '  function paintMasks() {'),
      // No W / H here on purpose: in the page they are not globals either (11-06 a free `W` threw in every frame).
      'const sx = new Float32Array(478), sy = new Float32Array(478), sz = new Float32Array(478);',
      'const posted = []; const post = (m) => posted.push(m);',
      cut('  let faceFitAcc = null, faceFitState = null', '  let masks = null;'),
      'return { sx, sy, sz, posted, step: (now) => faceFitStep(now, 720, 1280), state: () => faceFitState, status: () => faceFitStatus, TUNING };',
    ].join('\n');
    return new Function(src)();
  }
  function personalized() {
    const h = measureHarness();
    h.TUNING.shadePersonalize = true;   // the analysis is a switch (off by default)
    return h;
  }
  function setFace(h: ReturnType<typeof measureHarness>, c: ParityCase, noseShift = 0) {
    // Parity landmarks are normalised for c.w x c.h; rescale x / y so the face keeps its pixel shape in a 720 x 1280 frame.
    for (let i = 0; i < 468; i++) {
      h.sx[i] = 0.5 + (c.x[i] - 0.5) * (c.w / 720);
      h.sy[i] = 0.5 + (c.y[i] - 0.5) * (c.h / 1280);
      h.sz[i] = c.z[i] * (c.w / 720);
    }
    h.sx[1] += noseShift;
  }
  const states = (h: ReturnType<typeof measureHarness>) => h.posted.map((m: { type: string; state?: string }) => m.state).filter(Boolean);

  it('is off by default for the shading: placement hints and the shape name (highlighter only, 11-11), no status, no shading work', () => {
    const h = measureHarness();
    expect(h.TUNING.shadePersonalize).toBe(false);
    setFace(h, (parity as ParityCase[])[0]);
    let t = 1000;
    while (!h.state() && t < 10000) { h.step(t); t += 125; }
    expect(h.state()).not.toBeNull();
    // 11-11: the shape is read for the highlighter layout; the shading gets no class probabilities (shapeP) from it.
    expect(['round', 'square', 'oblong', 'heart', 'oval']).toContain(h.state().shape);
    expect(h.state().fit.shapeP).toBeUndefined();
    expect(h.status()).toBe('default');
    expect(h.posted.map((m: { type: string }) => m.type)).toEqual(['face_fit']);
    expect(Object.keys(h.posted[0]).sort()).toEqual(['ratios', 'rec', 'shape', 'type']);
    // A face that is never frontal still never produces a status (nothing to wait for, nothing to show).
    const g = measureHarness();
    setFace(g, (parity as ParityCase[])[0], 0.06);
    for (let k = 0; k < 60; k++) g.step(1000 + 125 * k);
    expect(g.posted).toEqual([]);
    expect(g.status()).toBe('default');
    expect(script).toContain('shadePersonalize: false,');
    expect(script).toContain('if (TUNING.shadePersonalize && gl.getParameter(gl.MAX_TEXTURE_IMAGE_UNITS) >= 9) {');
    expect(script).toContain('if (TUNING.shadePersonalize && contourZ && masks) guard(');
    expect(script).toContain('if (!TUNING.shadePersonalize || st === faceFitStatus) return;');
  });

  it('judges a frontal face in well under 3 s at 8 fps and reports the shape name only', () => {
    const h = personalized();
    setFace(h, (parity as ParityCase[])[0]);
    let t = 1000;
    while (!h.state() && t < 10000) { h.step(t); t += 125; }
    expect(h.state()).not.toBeNull();
    expect(t - 1000).toBeLessThanOrEqual(1500);
    const fit = h.posted.find((m: { type: string }) => m.type === 'face_fit');
    expect(FACE_SHAPES).toContain(fit.shape);
    expect(Object.keys(fit).sort()).toEqual(['ratios', 'rec', 'shape', 'type']);   // no probability crosses to the app
    expect(h.state().fit.shapeP).toHaveLength(5);
    expect(states(h)).toEqual(['analyzing', 'personalized']);
  });

  it('still answers within 3 s when the head is a little turned (looser gate after the deadline)', () => {
    const h = personalized();
    setFace(h, (parity as ParityCase[])[0], 0.03); // yaw ratio 1.22: outside the strict gate, inside the loose one
    let t = 1000;
    while (!h.state() && t < 10000) { h.step(t); t += 125; }
    expect(h.state()).not.toBeNull();
    expect(t - 1000).toBeLessThanOrEqual(3000);
  });

  it('averages landmarks, so identical frames give exactly the single-frame features', () => {
    const h = personalized();
    const c = (parity as ParityCase[])[0];
    setFace(h, c);
    for (let k = 0; k < 10; k++) h.step(1000 + 125 * k);
    const single = page().faceShapeFeatures(h.sx, h.sy, h.sz, 720, 1280);
    expect(h.state().ratios.cheekWide).toBeCloseTo(single.cheekWide, 5);
    expect(h.state().ratios.faceLong).toBeCloseTo(single.faceLong, 5);
  });

  it('starts over when the face leaves mid-measurement, instead of tripping the deadline', () => {
    const h = personalized();
    setFace(h, (parity as ParityCase[])[0]);
    h.step(1000); h.step(1125);
    h.step(5000);   // back after a long gap
    expect(h.state()).toBeNull();
    expect(h.status()).toBe('analyzing');
  });

  it('never waits forever: a face that is never frontal ends in fallback at 3 s, then personalizes on a later glance', () => {
    const h = personalized();
    const c = (parity as ParityCase[])[0];
    setFace(h, c, 0.06); // yaw ratio ~1.5: outside even the loose gate
    let t = 1000;
    for (; t < 1000 + 3300; t += 125) h.step(t);
    expect(h.state()).toBeNull();
    expect(h.status()).toBe('fallback');
    expect(states(h)).toEqual(['analyzing', 'fallback']);
    setFace(h, c); // now looks straight
    const back = t;
    while (!h.state() && t < back + 5000) { h.step(t); t += 125; }
    expect(h.status()).toBe('personalized');
    expect(t - back).toBeLessThanOrEqual(1500);
  });

  // ── default -> personalized shading on the GPU side, with stand-ins for the GL calls ──
  function shadeHarness(xfadeOn: boolean) {
    const src = cut("    const shade = { fitFor: null, phase: 'default'", '    // Selectable highlighter areas (mask 3)');
    const log: string[] = [];
    let ready = false;
    const masks = {
      startPersonal: () => log.push('start'), personalReady: () => ready, snapshotPrev: () => { log.push('snapshot'); return new Uint8Array(1); },
      setAuto: (k: string) => log.push('set:' + k), blendAuto: (t: number) => log.push('blend:' + t.toFixed(2)),
    };
    const make = new Function(
      'masks', 'TUNING', 'xfadeOn', 'uploadPrev', 'uploadMask2',
      'let faceFitState = null;\n' + src + '\nreturn { shade, shadeStep, contourMix, setFit: (v) => { faceFitState = v; } };',
    );
    const h = make(masks, { contourFadeMs: 450 }, xfadeOn, () => log.push('upload-prev'), () => log.push('upload'));
    return { ...h, log, setReady: (v: boolean) => { ready = v; } };
  }

  it('keeps the default shading while the analysis runs or fails, then mixes into the personalized one without a jump', () => {
    const h = shadeHarness(true);
    // No measurement (analysis failed or still running): nothing happens, the mix stays 1 (= the current mask).
    h.shadeStep(0); h.shadeStep(500);
    expect(h.shade.phase).toBe('default');
    expect(h.log).toEqual([]);
    expect(h.contourMix(500)).toBe(1);
    // A measurement starts the background build only; the screen is untouched until the mask is ready.
    h.setFit({ fit: {} });
    h.shadeStep(1000);
    expect(h.shade.phase).toBe('building');
    h.shadeStep(1200);
    expect(h.log).toEqual(['start']);
    // Ready: the previous mask is kept for the mix, the new one uploaded once, the mix runs 0 -> 1 over contourFadeMs.
    h.setReady(true);
    h.shadeStep(2000);
    expect(h.log).toEqual(['start', 'snapshot', 'upload-prev', 'set:personal', 'upload']);
    expect(h.shade.phase).toBe('fading');
    const mix = [2000, 2100, 2225, 2350, 2450].map((t) => h.contourMix(t));
    expect(mix[0]).toBe(0);
    for (let i = 1; i < mix.length; i++) expect(mix[i]).toBeGreaterThanOrEqual(mix[i - 1]);
    expect(mix[mix.length - 1]).toBe(1);
    h.shadeStep(2460);
    expect(h.shade.phase).toBe('personalized');
    expect(h.log.length).toBe(5);   // no further uploads: the transition costs one upload, not one per frame
  });

  it('uses three stepped repaints on a device without the ninth texture unit', () => {
    const h = shadeHarness(false);
    h.setFit({ fit: {} });
    h.shadeStep(0);
    h.setReady(true);
    h.shadeStep(100);
    expect(h.shade.phase).toBe('stepping');
    for (const t of [150, 300, 560]) h.shadeStep(t);
    expect(h.log.filter((l: string) => l.startsWith('blend'))).toEqual(['blend:0.33', 'blend:0.67']);
    expect(h.log[h.log.length - 2]).toBe('set:personal');
    expect(h.shade.phase).toBe('personalized');
    expect(h.contourMix(300)).toBe(1);
  });

  it('builds the cross-fade variant only when the device has the texture unit, and falls back to the plain program if it fails', () => {
    expect(script).toContain("'#ifdef XFADE',");
    expect(script).toContain("'  if (uContourMix < 0.999) cg = mix(texture2D(uMask2Prev, vUv, uMaskBias).g, m2.g, uContourMix);',");
    expect(script).toContain("'  float hlA = hlMask * uHlCov; float contourA = cg * uContourCov; float darkA = m2.b * uShadow2Cov;',");
    expect(script).toContain('if (TUNING.shadePersonalize && gl.getParameter(gl.MAX_TEXTURE_IMAGE_UNITS) >= 9) {');
    expect(script).toContain("try { mesh = program(MESH_VERT, '#define XFADE' + NL + MESH_FRAG, MESH_UNIFORMS); xfadeOn = true; } catch (e) { mesh = null; }");
    expect(script).toContain('if (!mesh) mesh = program(MESH_VERT, MESH_FRAG, MESH_UNIFORMS);');
    expect(script).toContain('gl.uniform1i(u.uMask2Prev, 8);');
    expect(script).toContain("'jaw ' + (makeup.contour ? 'shade ' + faceHud() + '  mask ' + shadeHud()");
  });

  // ── the screen ──
  it('removes the jawline / nose chips and shows the status: one colour choice, never a wait, in all four languages', () => {
    const tsx = nodeFs.readFileSync(nodePath.join(__dirname, '..', 'app', '(tabs)', 'ar.tsx'), 'utf8');
    expect(tsx).not.toContain('CONTOUR_STYLE_IDS');
    expect(tsx).not.toContain('ar.contourStyle.');
    expect(tsx).not.toContain("patchGeometry('contour', { contourStyle");
    expect(tsx).toContain("t('ar.contourPlacement.auto')");
    expect(tsx).toContain("faceFitStatus === 'fallback' ? 'ar.faceShape.fallback' : faceFitStatus === 'analyzing' ? 'ar.faceShape.analyzing' : 'ar.faceShape.default'");
    expect(tsx).toContain("t('ar.faceShape.result', { name: t(`ar.faceShape.name.${faceShape}` as TranslationKey) })");
    // The highlighter keeps its style and area chips, and both zones keep their intensity bar.
    expect(tsx).toContain('HIGHLIGHTER_STYLE_IDS.map');
    expect(tsx).toContain('HIGHLIGHTER_AREAS.map');
    expect(tsx).toContain('toggleHighlighterArea(painted, area)');
    // 11-11: face-type chips (auto + six types) set the regions; the region chips show exactly what is painted.
    expect(tsx).toContain('HIGHLIGHT_FACES.map');
    expect(tsx).toContain('const painted = effectiveHighlighterAreas(makeup.highlighter?.geometry, faceShape);');
    expect(tsx).toContain("patchGeometry('highlighter', { hlFace: undefined, areas: undefined, hlStyle: undefined })");
    for (const dict of [en, ko, ja, zh] as Record<string, string>[]) {
      for (const key of ['ar.hlFace.auto', 'ar.hlFace.autoWith', 'looks.area.philtrum', 'looks.area.cheekbone']) expect(dict[key]).toBeTruthy();
      for (const face of ['round', 'square', 'oblong', 'oval', 'heart', 'gaunt']) expect(dict['ar.hlFace.tip.' + face]).toBeTruthy();
      // One name per face shape in the shading and the highlighter panels: the highlighter reads the shading's keys (11-11 user).
      expect(dict['ar.hlFace.name.gaunt']).toBeTruthy();
      for (const face of ['round', 'square', 'oblong', 'oval', 'heart']) expect(Object.keys(dict)).not.toContain('ar.hlFace.name.' + face);
    }
    expect(tsx).toContain("value={zone === 'highlighter' ? makeup.highlighter!.intensity : makeup.contour!.intensity}");
    for (const dict of [en, ko, ja, zh] as Record<string, string>[]) {
      for (const key of ['contourPlacement.auto', 'faceShape.default', 'faceShape.analyzing', 'faceShape.fallback', 'faceShape.result']) expect(dict['ar.' + key]).toBeTruthy();
      for (const shape of FACE_SHAPES) {
        expect(dict['ar.faceShape.name.' + shape]).toBeTruthy();
        expect(dict['ar.faceShape.rule.' + shape]).toBeTruthy();
      }
      expect(Object.keys(dict).filter((k) => k.startsWith('ar.contourStyle.'))).toEqual([]);
      // A name, never a probability.
      for (const k of Object.keys(dict).filter((key) => key.startsWith('ar.faceShape.'))) expect(dict[k]).not.toMatch(/%|\{pct\}|\{conf\}/);
    }
    expect(ko['ar.faceShape.default']).toBe('기본 쉐딩');
    expect(ko['ar.faceShape.analyzing']).toBe('기본 쉐딩 · 얼굴형 분석 중');
    expect(ko['ar.faceShape.fallback']).toBe('기본 쉐딩 유지');
  });

  // ── the 11-06 incident: a free `W` in faceFitStep threw in every frame, the render's catch swallowed it, nothing was drawn ──
  it('has no identifier the page script uses without defining it (the class of bug behind "W is not defined")', () => {
    const { Linter } = jest.requireActual('eslint') as { Linter: new () => { verify: (code: string, config: object) => { line: number; message: string }[] } };
    const globalsPkg = jest.requireActual('globals') as { browser: Record<string, boolean>; es2021: Record<string, boolean> };
    const tags = [...script.matchAll(/<script[^>]*>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
    const code = tags[tags.length - 1];
    expect(code.length).toBeGreaterThan(100000);
    const messages = new Linter().verify(code, {
      languageOptions: {
        ecmaVersion: 2022,
        sourceType: 'module',
        // `canvas` is the page's <canvas id="canvas"> reached through the window's named access (worked before this check existed).
        globals: { ...globalsPkg.browser, ...globalsPkg.es2021, canvas: 'readonly' },
      },
      rules: { 'no-undef': 'error' },
    });
    expect(messages.map((m) => m.line + ': ' + m.message)).toEqual([]);
  });

  it('never lets the measurement, the repaint or the transition stop the drawing, and shows swallowed errors', () => {
    const guardSrc = cut('  let guardErrors = 0, guardLast', '  let faceFitAcc = null');
    const calls: string[] = [];
    const errors: string[] = [];
    const g = new Function('console', guardSrc + '; return { guard, errors: () => [guardErrors, guardLast] };')({ error: (m: string) => errors.push(m) });
    expect(g.guard('measure', () => 42)).toBe(42);
    expect(g.guard('measure', () => { calls.push('x'); throw new ReferenceError('W is not defined'); })).toBeUndefined();   // does not throw
    expect(g.errors()).toEqual([1, 'measure: W is not defined']);
    expect(errors).toEqual(['AR measure: W is not defined']);
    for (let i = 0; i < 10; i++) g.guard('measure', () => { throw new Error('again'); });
    expect(errors.length).toBe(3);   // the console is not flooded; the count keeps going
    // The render calls them through the guard, with the frame size passed in (never read as a global).
    expect(script).toContain("guard('measure', () => faceFitStep(performance.now(), W, H));");
    expect(script).toContain("guard('repaint', () => {");
    expect(script).toContain("guard('shade', () => shadeStep(performance.now()));");
    expect(script).toContain('function faceFitStep(now, W, H) {');
    // The catch around the render used to be empty of any record: now the error is counted, logged once and shown in the HUD.
    expect(script).toContain('renderErrors++;');
    expect(script).toContain("console.error('AR render: ' + renderErrLast);");
    expect(script).toContain("'ERR guard ' + guardErrors");
  });

  it('keeps the volume terms off by default and gates the light direction by its confidence', () => {
    expect(script).toContain('hlContourVolume: false');
    expect(script).toContain('TUNING.hlContourVolume ? TUNING.volumeGain[0] : 0');
    expect(script).toContain('uLightConf * uVolLight');
    expect(script).toContain('contourA *= clamp(1.0 + uVolume.x * (0.7 - volFace), 0.6, 1.5);');
  });
});
