import { FACE_TRACKER_HTML, MEDIAPIPE_VERSION } from '@/components/ar/faceTrackerHtml';

function moduleScript(html: string) {
  const match = html.match(/<script type="module">([\s\S]*?)<\/script>/);
  if (!match) throw new Error('module script not found');
  return match[1];
}

type RenderState = { face: boolean; drawn: boolean; lost: boolean; failDraw: boolean; failFilter: boolean; values: number[] };

function renderHarness() {
  const script = moduleScript(FACE_TRACKER_HTML);
  const messaging = script.slice(script.indexOf('  function post(message) {'), script.indexOf('  window.__kb'));
  const frame = script.slice(script.indexOf('  function processFrame(now) {'), script.indexOf('  // Prefer requestVideoFrameCallback'));
  const state: RenderState = { face: true, drawn: true, lost: false, failDraw: false, failFilter: false, values: [] };
  const messages: Record<string, unknown>[] = [];
  const build = new Function('state', 'messages', `
    let makeup = { lip: null }, pendingRender = null, pendingRenderZone = null, pendingRestore = null, commandRendererId = null, lastRenderSeq = -1, lastStateSeq = -1;
    let status = null, hasFace = true, lastFaceAt = 0, lastLightAt = 1, fpsFrames = 0, fpsAt = 0, fps = 0;
    let landmarker = { detectForVideo: () => ({ faceLandmarks: state.face ? [{}] : [] }) };
    let renderer = { get lost() { return state.lost; }, upload() {}, render() {
      if (state.failDraw) throw Error('draw failed');
      state.values.push(makeup.lip && makeup.lip.intensity);
      return state.drawn;
    } };
    const window = { ReactNativeWebView: { postMessage: (s) => messages.push(JSON.parse(s)) } };
    const video = { readyState: 2, videoWidth: 100, videoHeight: 100 };
    const filterLandmarks = () => { if (state.failFilter) throw Error('landmarks failed'); }, updateMesh = () => {}, TUNING = { lightEveryMs: 1000 };
    const wantSkinMask = () => false, occGate = { lip: 1, eye: 1, cheek: 1 };
    const hudOn = false, guide = null;
    let renderErrors = 0, renderErrLast = '';   // the render's catch records the error it used to swallow
    const console = { error: () => {} };
    ${messaging}
    ${frame}
    return { handleMessage, processFrame };
  `) as (s: RenderState, m: Record<string, unknown>[]) => {
    handleMessage: (message: object) => void;
    processFrame: (now: number) => void;
  };
  return { state, messages, ...build(state, messages) };
}

function renderCommand(value: number, renderSeq = 1, rendererId = 'renderer-1') {
  return { type: 'render_command', commandId: 'command-1', renderSeq, rendererId, makeup: { lip: { intensity: value } } };
}

function restoreCommand(value: number | null, renderSeq = 2, rendererId = 'renderer-1', restoreId = 'restore-1') {
  return { type: 'restore_command', commandId: 'command-1', restoreId, renderSeq, rendererId,
    makeup: { lip: value === null ? null : { intensity: value } } };
}

it('acknowledges a blush command after drawing a fresh frame without a lip product', () => {
  const h = renderHarness();
  h.handleMessage({ ...renderCommand(0.4), zone: 'blush', makeup: { blush: { intensity: 0.4 } } });
  expect(h.messages).toEqual([]);
  h.processFrame(2);
  expect(h.messages).toContainEqual(expect.objectContaining({ type: 'render_result', status: 'rendered' }));
});

describe('face tracker page', () => {
  it.each([0, 0.01, 0.5, 1])('acknowledges intensity %s only after a matching face and draw', (value) => {
    const h = renderHarness();
    h.handleMessage(renderCommand(value));
    expect(h.messages).toEqual([]);
    h.processFrame(2);
    expect(h.state.values).toEqual([value]);
    expect(h.messages).toContainEqual({ type: 'render_result', commandId: 'command-1', renderSeq: 1, rendererId: 'renderer-1', status: 'rendered' });
    h.processFrame(3);
    expect(h.messages.filter((message) => message.type === 'render_result')).toHaveLength(1);
  });

  it('bypasses only lip shading at zero and restores it without changing the product', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    const source = script.slice(script.indexOf('  function lipEffectEnabled('), script.indexOf('\n', script.indexOf('  function lipEffectEnabled(')));
    const enabled = new Function(`${source}; return lipEffectEnabled;`)() as (zone: { intensity: number } | null) => boolean;
    const product = { productId: 'p1', shadeId: 's1', intensity: 0.5 };
    expect(enabled(product)).toBe(true);
    product.intensity = 0;
    expect(enabled(product)).toBe(false);
    expect(product).toEqual({ productId: 'p1', shadeId: 's1', intensity: 0 });
    product.intensity = 0.5;
    expect(enabled(product)).toBe(true);
    expect(enabled({ intensity: 0.01 })).toBe(true);
    expect(enabled({ intensity: 1 })).toBe(true);
    expect(script).toContain('gl.uniform1f(u.uLipOn, lipEffectEnabled(lip) ? 1 : 0);');
    expect(script).toContain('float lipZone = m.a * uLipOn;');
  });

  it('does not let an older makeup message replace a newer command', () => {
    const h = renderHarness();
    h.handleMessage({ ...renderCommand(0.5, 2), stateSeq: 2 });
    h.handleMessage({ type: 'makeup', stateSeq: 1, makeup: { lip: { intensity: 0.3 } } });
    h.processFrame(2);
    expect(h.state.values).toEqual([0.5]);
    expect(h.messages).toContainEqual({ type: 'render_result', commandId: 'command-1', renderSeq: 2, rendererId: 'renderer-1', status: 'rendered' });
  });

  it('waits for a fresh face and a real lip draw, not stale tracking', () => {
    const h = renderHarness();
    h.handleMessage(renderCommand(0.5));
    h.state.face = false;
    h.processFrame(2);
    h.state.face = true;
    h.state.failFilter = true;
    h.processFrame(2.5);
    h.state.failFilter = false;
    h.state.drawn = false;
    h.processFrame(3);
    expect(h.messages.filter((message) => message.type === 'render_result')).toEqual([]);
    h.state.drawn = true;
    h.processFrame(4);
    expect(h.messages.filter((message) => message.type === 'render_result')).toHaveLength(1);
  });

  it('cancels an old command and refuses older or other-instance messages', () => {
    const h = renderHarness();
    h.handleMessage(renderCommand(0.5, 2));
    h.handleMessage({ type: 'makeup', makeup: { lip: { intensity: 0.3 } } });
    h.handleMessage(renderCommand(0.5, 1));
    h.handleMessage(renderCommand(0.5, 3, 'old-renderer'));
    h.processFrame(2);
    expect(h.state.values).toEqual([0.3]);
    expect(h.messages.filter((message) => message.type === 'render_result')).toEqual([]);
  });

  it.each([0.2, null])('confirms restoration of the latest makeup %s only after a fresh draw', (value) => {
    const h = renderHarness();
    h.handleMessage(renderCommand(0.5));
    h.handleMessage(restoreCommand(value));
    h.state.face = false;
    h.processFrame(2);
    expect(h.messages).toEqual([]);
    h.state.face = true;
    h.processFrame(3);
    expect(h.state.values.at(-1)).toBe(value);
    expect(h.messages.filter((message) => message.type === 'restore_result')).toEqual([{ type: 'restore_result', commandId: 'command-1', restoreId: 'restore-1',
      renderSeq: 2, rendererId: 'renderer-1', status: 'rendered' }]);
  });

  it('draws a replacement frame after a candidate was already drawn', () => {
    const h = renderHarness();
    h.handleMessage(renderCommand(0.5));
    h.processFrame(2);
    h.handleMessage(restoreCommand(0.2));
    h.processFrame(3);
    expect(h.state.values).toEqual([0.5, 0.2]);
    expect(h.messages.filter((message) => message.type === 'restore_result')).toEqual([
      { type: 'restore_result', commandId: 'command-1', restoreId: 'restore-1', renderSeq: 2,
        rendererId: 'renderer-1', status: 'rendered' },
    ]);
  });

  it('restores only the newest sequence and ignores old instance and old candidate messages', () => {
    const h = renderHarness();
    h.handleMessage({ ...renderCommand(0.5, 1), stateSeq: 1 });
    h.handleMessage({ ...restoreCommand(0.3, 2), stateSeq: 2 });
    h.handleMessage({ ...restoreCommand(0.2, 3, 'renderer-1', 'restore-2'), stateSeq: 3 });
    h.handleMessage({ ...restoreCommand(0.8, 4, 'old-renderer'), stateSeq: 4 });
    h.handleMessage({ ...restoreCommand(0.1, 4, 'renderer-1', 'restore-3'), stateSeq: 4 });
    h.processFrame(2);
    expect(h.state.values).toEqual([0.1]);
    expect(h.messages.filter((message) => message.type === 'restore_result')).toEqual([{ type: 'restore_result', commandId: 'command-1', restoreId: 'restore-3',
      renderSeq: 4, rendererId: 'renderer-1', status: 'rendered' }]);
  });

  it.each(['lost', 'failDraw'] as const)('reports restoration %s without reporting success', (failure) => {
    const h = renderHarness();
    h.handleMessage(renderCommand(0.5));
    h.handleMessage(restoreCommand(0.2));
    h.state[failure] = true;
    h.processFrame(2);
    expect(h.messages.filter((message) => message.type === 'restore_result')).toEqual([{ type: 'restore_result', commandId: 'command-1', restoreId: 'restore-1',
      renderSeq: 2, rendererId: 'renderer-1', status: 'failed' }]);
  });

  it('never confirms a pending restore after a newer ordinary makeup update', () => {
    const h = renderHarness();
    h.handleMessage({ ...restoreCommand(0.2), stateSeq: 1 });
    h.handleMessage({ type: 'makeup', stateSeq: 2, makeup: { lip: { intensity: 0.8 } } });
    h.processFrame(2);
    expect(h.state.values).toEqual([0.8]);
    expect(h.messages.filter((message) => message.type === 'restore_result')).toEqual([]);
  });

  it.each(['lost', 'failDraw'] as const)('reports a %s failure without reporting success', (failure) => {
    const h = renderHarness();
    h.handleMessage(renderCommand(0.5));
    h.state[failure] = true;
    h.processFrame(2);
    expect(h.messages.filter((message) => message.type === 'render_result')).toEqual([
      { type: 'render_result', commandId: 'command-1', renderSeq: 1, rendererId: 'renderer-1', status: 'failed' },
    ]);
  });
  it('embeds a syntactically valid script', () => {
    // The page script lives inside a template string, so typecheck/lint never see it.
    expect(() => new Function(moduleScript(FACE_TRACKER_HTML))).not.toThrow();
  });

  it('pins the MediaPipe version and keeps the host protocol', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    expect(script).toContain(`'${MEDIAPIPE_VERSION}'`);
    for (const token of ["type: 'hello'", "type: 'status'", "type: 'light_hint'", "msg.type === 'makeup'", "msg.type === 'compare'", "msg.type === 'preview'"]) {
      expect(script).toContain(token);
    }
  });

  it('never uploads or stores camera frames', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    expect(script).not.toMatch(/fetch\(|XMLHttpRequest|localStorage|indexedDB|toDataURL|toBlob/);
  });

  it('layers lipstick over the real lip instead of painting a synthetic lip shape (6-5-3)', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // Bare-lip color and brightness are measured on the lip body (between outer and inner lines).
    expect(script).toContain('LIPS_OUTER[i]');
    expect(script).toContain('LIPS_INNER[i]');
    expect(script).toContain('light.lipColor');
    // Camera pixel × (layered / bare) reflectance: shading, wrinkles, light and noise come from the camera.
    expect(script).toContain('vec3 paint = mix(rPx, uLipAlbedo, cov)');
    // Per-pixel bare lip keeps one lipstick color across a redder upper / paler lower lip (device 10-23).
    expect(script).toContain('vec3 rPx = max(rLip * clamp(chromPx / max(chromLip, vec3(1e-3)), 0.25, 4.0), vec3(1e-3))');
    expect(script).toContain('vec3 ratio = clamp(mixCol / rPx, 0.0, uRatioMax)');
    // Bare-lip color direction from the 5-pixel mean, so single-pixel color noise is not multiplied back.
    expect(script).toContain('vec3 chromPx = camN / max(lum(camN), 1e-4);');
    // Highlight split only on the lip (no grey halo on skin), and only for real reflections: a
    // desaturated local peak or wide reflection. A broadly paler lower lip must not become a white
    // film (device 10-25).
    expect(script).toContain('float desat = 1.0 - smoothstep(uHlSat.x, uHlSat.y, camSat);');
    expect(script).toContain('hlPeak = max(camL0 - uHlLocal * wideL, 0.0) * desat;');
    // Narrow reflections (creases, ridges) are surface detail for every finish; the wide wet shine of
    // the bare lip only survives a smooth finish (a matte pigment covers it). 11-03: the lip's small
    // sparkles count by being whiter than their neighbours, not white (on a red lip they stay pinkish).
    expect(script).toContain('float hl = max(min(hlCap, max(hlPeak, hlWide * smoothT)), hlSpark * uHlSparkle) * core;');
    expect(script).toContain('* smoothstep(0.0, 0.1, satR - camSat);');
    // Opaque paint may lighten the lip (cap only for see-through finishes), hides bare-lip patches
    // partly, and never clips a light shade to white.
    expect(script).toContain('float gainCap = mix(uRatioMax, uLumGainMax, uLipTranslucent * (1.0 - cov))');
    expect(script).toContain('layered *= pow(shadeRel, (uOpaqueShadeGamma - 1.0) * opaqueW)');
    expect(script).toContain('layered *= pkSoft / max(pk, 1e-4)');
    // Estimated chip hex cannot brighten the uncovered, see-through share beyond the cap.
    expect(script).toContain('uLumGainMax');
    // Coverage blends toward the product first; the see-through share then tints by hue only (a sheer nude or coral must not darken a red lip).
    expect(script).toContain('vec3 mixCol = paint * mix(vec3(1.0), filt / max(lum(filt), 1e-3), cov * uLipTranslucent);');
    // Covered share takes only the camera brightness (no per-channel noise amplification); uncovered keeps the camera color.
    expect(script).toContain('vec3 layered = mix(camDiffuse * ratio, lumOnly, cov) * clamp(fill, 0.6, 1.6);');
    // Light is drawn once: no lightness/chroma fixed by UV position, camera highlights never amplified,
    // the opaque compression acts on the large-scale lip brightness only (creases untouched).
    expect(script).not.toContain('uLipValue');
    expect(script).not.toContain('uGradeAmt');
    expect(script).toContain('hlKeep: [0.15, 1.0]');
    expect(script).toContain('float shadeRel = clamp(sLow / meanL, 0.15, 4.0);');
    // A pigmented sheen is the product color brightened; only a clear coat reflects the light's color.
    // 11-02 round 2: the highlight colour is the (partly neutralised) light colour over a hue-to-white mix, not near-white all over.
    expect(script).toContain('vec3 sheenCol = mix(uLightColor, vec3(1.0), uGlossTone.y) * mix(hue, vec3(1.0), smooth1 * smooth1 * smooth1 * mix(uGlossTone.x, 1.0, peakness));');
    expect(script).toContain('vec3 specTint = mix(uLipAlbedo, vec3(1.0), 0.16)');
    // Layering stays. No painted-over lip shape, drawn grooves, noise texture, or a normal drawn from
    // a template or an image file. Lip normals come only from this person: the form built from the
    // own outline (lipFormN, 10-25) and, on top of it, the camera's own lip lines read live from the
    // 4 neighbours (lipDetailN, 11-03 user decision: the shine must follow the lip's texture).
    for (const synthetic of ['formShape', 'sin(across', 'lipN ', 'lipN=', 'vnoise', 'uPigmentHeadroom', 'uNormalMap', 'uBumpMap']) {
      expect(script).not.toContain(synthetic);
    }
    expect(script).toContain('lipDG = vec2(lum(c1) - lum(c2), lum(c3) - lum(c4)) / max(lN, 1e-4);');
    expect(script).toContain('lipDetailN = normalize(lipFormN + vec3(dT.x, dT.y, 0.0));');
    // 11-03 (5 still faces): the shine follows the lip's lines through the camera's own crease shading
    // (cavity), sparkles stay; the tilted normal, its satin mix and anisotropy did not help and stay off.
    expect(script).toContain('float cav = pow(clamp(camL / max(wideL, 1e-4), 0.3, 2.0), uGlossCavity); formSpec *= cav; sheen *= cav;');
    expect(script).toContain('glossCavity: 2,');
    expect(script).toContain('hlSparkle: 1,');
    expect(script).toContain('lipDetail: 0,');
    expect(script).toContain('wideDetail: 0,');
    expect(script).toContain('glossAniso: 0,');
    // Sheen never fully turns off when the light direction is untrusted.
    expect(script).toContain('specFill');
    expect(script).toContain('max(uLightConf, uSpecFill)');
    // The outer edge comes from the screen-space outline, never from a per-pixel redness test that
    // grew lumps along the line at close range (10-25). 11-03: teeth near the inner line are taken out
    // (the landmark inner line can lie on them): far less red than this person's bare lip and not the dark
    // cavity, inside the mouth zone only. 11-04: shaded teeth count (no "brighter than the lip"); a thin band
    // only needs its neighbours along the mouth, and only inside the drawn ring of an open mouth.
    expect(script).toContain('lipM = m.r * inside * (1.0 - teethW);');
    expect(script).toContain('float redT = max(redness(cam), uMouthOpen * zone.x > 0.5 ? rA : redN);');
    expect(script).toContain('teethW = smoothstep(uTeethFirm.x, uTeethFirm.y, raw) * zone.y;');
    expect(script).toContain('teethBright: [0.3, 0.5],');
    expect(script).not.toContain('uBandGrow');
    expect(script).not.toContain('uEdge');
  });

  it('paints the lip full up to its line and corners, like a real bullet (10-25 reference)', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // The mask decides where the lip is; inside it the color is full, not a soft half-painted ramp.
    expect(script).toContain('m.r = min(m.r * uLipFill, 1.0);');
    const num = (key: string) => Number(script.match(new RegExp(`${key}:\\s*([0-9.]+)`))?.[1]);
    expect(num('lipFill')).toBeGreaterThan(1);
    expect(num('innerFadeStrength')).toBe(0);
    // Corners keep only a slight fade at the very tip.
    expect(num('cornerFadeStrength')).toBeLessThanOrEqual(0.15);
    expect(num('cornerFadeSize')).toBeLessThanOrEqual(0.08);
  });

  it('keeps the foundation on the lower face while the skin mask is a few frames old (11-02 clip of a moving head)', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    const num = (key: string) => Number(script.match(new RegExp(`${key}:\\s*([0-9.]+)`))?.[1]);
    const pair = (key: string) => script.match(new RegExp(`${key}:\\s*\\[([0-9.]+),\\s*([0-9.]+)\\]`))!.slice(1).map(Number);
    // Below the eyes the paint follows the landmark outline; the mask clips it only while a hand or hair covers the lower face.
    expect(script).toContain('skinM = max(skinM, uFoundFloor * (1.0 - smoothstep(uFoundLowerV.x, uFoundLowerV.y, vUv.y)));');
    expect(script).toContain('if (uCap < 0.5) skinM = max(');           // the forehead cap and the upper face keep the mask
    expect(script).toContain('gl.uniform1f(u.uFoundFloor, foundZ && foundSkinReady ? TUNING.foundLowerFloor * foundOcc : 0);'); // 0 without a mask
    expect(num('foundLowerFloor')).toBeGreaterThan(0.5);
    expect(num('foundLowerFloor')).toBeLessThanOrEqual(1);
    // v is up (forehead 0.89, eyes 0.62, nose tip 0.45): the lower face ends under the eyes and starts above the nose tip.
    const [vLo, vHi] = pair('foundLowerV');
    expect(vHi).toBeLessThan(0.62);
    expect(vLo).toBeGreaterThan(0.45);
    // A hand or hair over the cheeks turns the floor off: judged on cheek / chin landmarks, none on the lips or eyes.
    const ids = script.match(/FOUND_COVER_PTS = \[([0-9, ]+)\]/)![1].split(',').map(Number);
    expect(ids.length).toBeGreaterThanOrEqual(20);
    for (const lipOrEye of [0, 13, 14, 17, 61, 291, 33, 133, 159, 145, 263, 362, 386, 374]) expect(ids).not.toContain(lipOrEye);
    expect(script).toContain('foundOcc = smooth01(TUNING.foundOccCover[0], TUNING.foundOccCover[1], hit / FOUND_COVER_PTS.length);');
    const [cLo, cHi] = pair('foundOccCover');
    expect(cLo).toBeLessThan(cHi);
  });

  it('clips lip, eye and cheek paint where a hand or object covers the region, and leaves bangs / foundation alone', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    expect(script).toContain('makeupOcclusion: true');
    expect(script).toContain('function wantSkinMask()');
    expect(script).toContain('TUNING.makeupOcclusion && occMakeupOn()');
    expect(script).toContain('if (wantSkinMask())');
    expect(script).toContain('occPointOk(cat, allowAccessory)');
    expect(script).toContain('return cat === 3 || (allowAccessory && cat === 5)');
    expect(script).toContain('glideOcc(\'eye\', occVisShare(OCC_EYE_PTS, cat, mw, mh, true))');
    expect(script).toContain('glideOcc(\'lip\', occVisShare(OCC_LIP_PTS, cat, mw, mh, false))');
    expect(script).toContain('lipM *= mix(occSkin, 1.0, uOccGate.x);');
    expect(script).toContain('blushA *= mix(occSkin, 1.0, uOccGate.z);');
    expect(script).toContain('shadowA *= mix(occSkin, 1.0, uOccGate.y);');
    expect(script).toContain('gl.uniform1f(u.uOccOn, occOn ? 1 : 0);');
    expect(script).not.toContain('foundA *= mix(occSkin');
    expect(script).toContain('gl.uniform1f(u.uFoundSkinOn, (foundZ || jawShadeOn) && foundSkinReady ? 1 : 0);');
    expect(script).toContain('OCC_LIP_PTS = LIPS_OUTER');
    expect(script).toContain('OCC_EYE_PTS = EYES[0].contour.concat(EYES[1].contour)');
  });

  it('keeps a lip gloss small, soft and in the colour of the lip instead of a white layer on top (11-02 round 2)', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    const arr = (key: string) => script.match(new RegExp(`${key}:\\s*\\[([0-9., ]+)\\]`))![1].split(',').map(Number);
    const [width, focus, lumFollow, lightFollow] = arr('glossShape');
    const [halo, neutral, screen] = arr('glossTone');
    // A peaked lobe, not a flat-topped patch: the old width of 0.35 saturated the highlight into a uniformly bright plate.
    expect(width).toBeGreaterThanOrEqual(0.7);
    // Held to the lip centre, and the exposure and the estimated light direction move it only half as much.
    expect(focus).toBeGreaterThanOrEqual(0.5);
    expect(lumFollow).toBeLessThanOrEqual(0.5);
    expect(lightFollow).toBeLessThanOrEqual(0.5);
    // Colour kept: the falloff around the peak stays mostly the product's own hue and the warm light colour is made partly neutral.
    expect(halo).toBeLessThanOrEqual(0.3);
    expect(neutral).toBeGreaterThanOrEqual(0.4);
    // No screen blend: on a saturated lip it adds most to the dark channels and whitens more than adding does.
    expect(screen).toBe(0);
    expect(script).toContain('float formSpec = glossCap * lobe * core * uFormOn * mix(1.0, exp(-cd * cd), uGlossShape.y);');
    expect(script).toContain('vec3 lG = normalize(mix(vec3(0.0, 0.25, 1.0), l, uLightConf * uGlossShape.w));');
    expect(script).toContain('mix(0.25, uSkinMeanLum, uGlossShape.z)');
  });

  it('softens the paint edge with the camera blur, capped so a blurry video does not smear (11-02 survey)', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    const num = (key: string) => Number(script.match(new RegExp(`${key}:\\s*([0-9.]+)`))?.[1]);
    // Offline the paint edge was 2.1 px against ~8 px for the photo's own lip edge; 0.5 × blur was too crisp.
    expect(num('lipEdgeBlurK')).toBeGreaterThanOrEqual(0.8);
    expect(num('lipEdgeSoftMax')).toBeLessThanOrEqual(3);
    expect(script).toContain('clamp(TUNING.lipEdgeBlurK * light.blur, 0.5, TUNING.lipEdgeSoftMax)');
  });

  it('treats light reflected by the lip as lip, so it carries gloss and creases (device 10-25)', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // A white reflection is not red, but inside the outline it is lip: coverage never tests color.
    expect(script).not.toMatch(/lipM = [^;]*redness/);
    // The edge rays walk through a reflection inside the landmark lip instead of ending the lip there.
    expect(script).toContain('const v = t <= 1 && isReflection(smp) ? Math.max(smp.red, mid) : smp.red;');
  });

  it("measures this person's lip thickness instead of assuming an average", () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // Left, centre and right outer/inner pairs per lip, in screen px and as a 3D share of mouth width.
    expect(script).toContain('up: [[37, 82], [0, 13], [267, 312]]');
    expect(script).toContain('low: [[84, 87], [17, 14], [314, 317]]');
    // Baseline only from a closed, frontal mouth; reset when the face is lost; shown on the HUD.
    expect(script).toContain('if (mouthClosed() && frontal)');
    expect(script).toContain('lipThick.upBase = 0; lipThick.lowBase = 0;');
    expect(script).toContain("'lip thick up '");
    expect(script).toContain('measureLipThickness(W, H);');
    // Real lip edge from camera redness, as a share of the landmark lip (spill check on thin lips).
    expect(script).toContain('measureLipEdge(W, H);');
    expect(script).toContain("'real edge / landmark  up '");
  });

  it('measures the lip edge on 60 camera rays, not on the average face curve between landmarks', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // 3 rays per outer/inner landmark segment, per-ray time smoothing and neighbour outlier rejection.
    expect(script).toContain('const LIP_RAYS = LIPS_OUTER.length * 3');
    expect(script).toContain('TUNING.lipRayOutlier');
    // Measured points are drawn only while the debug HUD is on.
    expect(script).toContain('if (hudOn || guide) drawOverlay(W, H);');
  });

  it('HUD draws upper-lid liner indices with one mirror, liner off or on', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    expect(script).toContain('function drawEyeLinePoints(W, H)');
    expect(script).toContain('if (hudOn) { drawLipPoints(W, H); drawEyeLinePoints(W, H); }');
    const hud = script.slice(script.indexOf('function drawEyeLinePoints'), script.indexOf('function drawGuide'));
    expect(hud).toContain('for (const e of EYE_LINES)');
    expect(hud).toContain('e.upper.map(toScreen)');
    expect(hud).toContain('e.lower.map(toScreen)');
    expect(hud).toContain('const toScreen = (i) => [(1 - sx[i]) * W, sy[i] * H]');
    expect(hud).not.toMatch(/makeup\.eyeliner|linerLiftY/);
    expect(hud.match(/1 - sx\[i\]/g)?.length).toBe(1);
  });

  it('finds the lash line from the camera per eye, with no per-person lift table', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    expect(script).not.toContain('linerLiftY');
    expect(script).not.toContain('linerDropY');
    const drawEyes = script.slice(script.indexOf('function drawEyes'), script.indexOf('function updateMesh'));
    // Landmarks stay raw: the fit moves copies of the lid points, so the mesh and the eye holes do not move.
    expect(drawEyes).toContain('const P = (i) => [sx[i] * W, sy[i] * H];');
    expect(drawEyes).toContain('const fit = fitLidLine(EYE_LINES.indexOf(e), e, up, low, eyeW, nUp, fade, W, H, nowMs);');
    expect(drawEyes).toContain("never changes the eye's size");
    // Every number is a share of that eye's width; the same values for both eyes.
    const fitCode = script.slice(script.indexOf('function readEyeCrop'), script.indexOf('function drawEyes'));
    expect(fitCode).toContain('d[i] * eyeW');
    expect(fitCode).toContain('const enabled = eyeW >= L.minEyePx && gap >= L.blinkGap && facing >= L.faceZ && fade > 0;');
    expect(fitCode).toContain('const crop = enabled ? readEyeCrop(');
    expect(fitCode).not.toMatch(/fetch|XMLHttpRequest|localStorage|sendBeacon/);
    // Offsets are clamped to the range, and a weak or missing edge falls back to the prior.
    expect(fitCode).toContain('target[i] = clamp(num / den, lo, hi);');
    expect(fitCode).toContain('let num = L.priorWeight * prior, den = L.priorWeight;');
    // 11-07: no upward bias: the line stays on the lid points unless the lash line is read, and rises at most 1.5%.
    expect(script).toContain('d0: 0,');
    expect(script).toContain('lo: -0.04, hi: 0.015,');
    expect(script).toContain('if (side.ready && side.measured && side.offS < L.holdS) { side.active = false; side.conf.fill(0); return side.x; }');
    expect(script).toContain('lowD0: 0.005, lowLo: -0.01, lowHi: 0.03');
    // Face lost: the offsets are dropped, so nobody inherits the last person's lash line.
    expect(script).toContain('resetLidFit();');
    const filter = script.slice(script.indexOf('function filterLandmarks'), script.indexOf('function lerp'));
    expect(filter).not.toContain('lidFit');
  });

  it('draws the lip outline in screen space with sharp corners and smooth sides (10-25 close-ups)', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // Redrawn every frame from the smoothed landmarks, not warped through mesh triangles.
    expect(script).toContain('const outlineOn = lip ? drawLipOutline(W, H, lip.geometry) : false;');
    // Mouth corners keep a zero tangent (no rounded beak); the ring is smoothed without shrinking.
    expect(script).toContain('if (i % 10 === 0) return [0, 0];');
    expect(script).toContain('for (const w of [k, -1.06 * k])');
    // Open mouth: the inner curve is the hole; closed: the gap is painted.
    expect(script).toContain('if (!mouthClosed()) {');
    expect(script).toContain("float inside = mix(soft, o0, uMouthOpen * (1.0 - smoothstep(0.18, 0.55, o0)));");
    // The A2 measured outline is gone (worse than landmarks on 200 real faces).
    expect(script).not.toContain('drawLipShape');
  });

  it('rounds each lip from its own outline and places finish highlights on it (10-25 "직접 바른 느낌")', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // Form field: the outline's form channel, blurred by a share of this lip's thickness, uploaded per frame.
    expect(script).toContain('const h = boxBlurRect(g, fw, fh, r);');
    expect(script).toContain('if (TUNING.lipForm) drawLipForm(srcW, srcH);');
    // Closed lips split at the seam so each lip has its own round.
    expect(script).toContain("c.strokeStyle = '#f0f';");
    // Up/down from the mouth's mean orientation, left/right from the mesh (dental arch), tilt saturates.
    expect(script).toContain('lipBaseN = normalize(vec3(n.x, mix(uMouthN.y, n.y, 0.3), n.z));');
    expect(script).toContain('vec2 tilt = grad * inversesqrt(1.0 + dot(grad, grad)) * uFormTilt * uFormOn;');
    // Volume = Lambert of the form under the estimated light; highlight = sharp source reflection + glow,
    // also from the always-present frontal source, scaled by scene brightness and finish smoothness.
    expect(script).toContain('float form = max(dot(lipFormN, lV), 0.0) / max(dot(lipBaseN, lV), 0.2);');
    expect(script).toContain('uFrontGloss * (sharpF + uWideGloss * wF)');
    expect(script).toContain('* mix(0.25, uSkinMeanLum, uGlossShape.z) * uGlossGain');
    // Flat selfie: form gloss rises when the camera has no specular; matte (smooth1²) stays dull.
    expect(script).toContain('uGlossFlat * (1.0 - smoothstep(0.02, 0.12, camSpec)) * smooth1 * smooth1');
    // 11-02: 1.2 → 0.6 (survey: gloss read as plastic). Stays above 0, or a gloss looks matte on a flat selfie again (10-25).
    expect(Number(script.match(/glossFlat:\s*([0-9.]+)/)?.[1])).toBeGreaterThan(0);
    // No pale rim where opaque paint crosses onto skin.
    expect(script).toContain('layered *= mix(1.0, min(1.0, meanL / max(uSkinMeanLum, 1e-3)), skinW * opaqueW);');
    // Matte stays dull: its highlight peak is far below a gloss's.
    const pair = script.match(/glossMax:\s*\[([0-9.]+),\s*([0-9.]+)\]/);
    expect(Number(pair?.[1])).toBeLessThan(0.1);
    // Gloss peak 0.85 → 0.45 on 11-02 (survey); it must stay well above a matte's, at least 5×.
    expect(Number(pair?.[2])).toBeGreaterThan(5 * Number(pair?.[1]));
  });

  it('paints the wet inner lip on open mouths and ignores face points outside the frame', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // Inner line moved into the mouth by openness (LaPa: 13% of open-mouth lip lay inside it).
    expect(script).toContain('const fixedInset = mouthClosed() ? 0 : inset;');
    expect(script).toContain('? LIPS_INNER.map((_, j) => Math.max(fixedInset, lipInner.conf[j] >= 0.5 ? lipInner.t[j] : fixedInset)) : fixedInset);');
    expect(script).toContain('innerInset: [0.12, 0.28]');
    // Close-ups: vertices outside the frame never feed the light estimate.
    expect(script).toContain('const skinIn = masks.skinVerts.filter((i) => meshNrm[i * 3 + 2] >= 0.35 && inFrame(i));');
  });

  it('moves the makeup with the face in the same frame (no trailing on a head shake)', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // Raw anchors (mouth centre near the mouth, face centre elsewhere); One Euro only on the offsets.
    expect(script).toContain('const x = face[i].x - ax(i), y = face[i].y - ay(i);');
    expect(script).toContain('for (let i = 0; i < n; i++) { sx[i] = ax(i) + ox[i]; sy[i] = ay(i) + oy[i]; }');
  });

  it('keeps the eye canvas opaque: the brow is its own texture, never packed into alpha (11-06 /ar-debug)', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // A 2D canvas stores premultiplied colour: alpha 0 outside the brow wiped liner (r) and mascara (g) in every look
    // with a brow (phone and headless both reported a0 'lost'). The brow canvas goes up on texture unit 9 instead.
    expect(script).not.toContain('putImageData(packed');
    expect(script).not.toContain('eyeC.a');
    expect(script).not.toMatch(/eyeAt\([^)]*\)\.a/);
    expect(script).toContain("'float browAt(vec2 s) {',");
    expect(script).toContain("texture2D(uBrowTex, p).g");
    expect(script).toContain("'uEye', 'uBrowTex', 'uEyeRect',");
    expect(script).toContain('if (eyesOn && browZ) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, browCanvas);');
    expect(script).toContain('gl.uniform1i(u.uBrowTex, 9);');
  });

  it('draws eyeliner and mascara from the lid landmarks, following blinks (10-25)', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // Screen-space eye canvas, uploaded only while a liner or mascara is on.
    expect(script).toContain('const mascara = makeup.mascara || null;');
    expect(script).toContain('const hl = makeup.highlighter || null;');
    expect(script).toContain('const contourZ = makeup.contour || null;');
    expect(script).toContain('const eyesOn = liner || mascara || innerPt || browZ ? drawEyes(W, H, liner, mascara, eye, browZ) : false;');
    // Wing from the stable corner-to-corner axis (the lid tangent flips while blinking); geometry overridable.
    expect(script).toContain('const wdir = [axis[0] * Math.cos(ang) + nUp[0] * Math.sin(ang), axis[1] * Math.cos(ang) + nUp[1] * Math.sin(ang)];');
    expect(script).toContain('const g = Object.assign({}, TUNING.liner, liner.geometry || {});');
    // Lashes rise on an open eye and hang down on a closed one; strands are seeded, never random per frame.
    expect(script).toContain('const openness = clamp((gap - 0.06) / 0.18, 0, 1);');
    expect(script).toContain('function seeded(i)');
    expect(script).not.toMatch(/Math\.random\(/);
    // The far eye of a turned head fades; eye-opening triangles carry lashes only.
    expect(script).toContain('const fade = clamp((meshNrm[e.center * 3 + 2] - 0.15) / 0.35, 0, 1);');
    expect(script).toContain('if (uEyeHole > 0.5) { blushA = 0.0; shadowA = 0.0; lipZone = 0.0; hlA = 0.0; contourA = 0.0; linerA = 0.0; darkA = 0.0; innerA = 0.0; foundA = 0.0; browA = 0.0; }');
  });

  it('lays highlighter and contour as product color on fixed regions only (AR_SPEC 1-2, 1-3)', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // Fixed UV regions, mirrored about the midline, faded out before the face outline.
    expect(script).toContain('c.save(); c.translate(2 * midU, 0); c.scale(-1, 1); drawSide(); c.restore();');
    expect(script).toContain('const inside = clamp01((faceFill[i] - 0.5) * 2);');
    // Intensity off → zero coverage (pixel untouched).
    expect(script).toContain('gl.uniform1f(u.uHlCov, hl ? clamp01(hl.intensity) * TUNING.hlCoverage * hlGain : 0);');
    expect(script).toContain("gl.uniform1f(u.uContourCov, contourZ ? clamp01(contourZ.intensity) * (jawShade ? 0.85 : TUNING.contourCoverage) : 0);");
    expect(script).toContain('gl.uniform1f(u.uFoundCov, foundZ ? span(TUNING.foundCoverage) : 0);');
    expect(FACE_TRACKER_HTML).toContain('object-fit: cover');
    expect(script).toContain('foundSkinBin[i] = cat[i] === 3 ? 255 : 0;');
    // The skin mask still gates the paint (11-02: below the eyes it gets a floor, see the lower-face test).
    expect(script).toContain('float skinM = uFoundSkinOn > 0.5 ? texture2D(uFoundSkin, suv).r');
    expect(script).toContain('foundA *= skinM;');
    expect(script).toContain('foundSegEveryMs: 120');
    expect(script).toContain('foundSegEveryLowFpsMs: 400');
    // Forehead: the mesh stops at landmark 10, so a foundation-only cap continues it to the hairline; the skin mask cuts the hair.
    expect(script).toContain('const FOREHEAD_CAP = [127, 162, 21, 54, 103, 67, 109, 10, 338, 297, 332, 284, 251, 389, 356];');
    expect(script).toContain('gl.drawElements(gl.TRIANGLES, capIdx.length, gl.UNSIGNED_SHORT, 0);');
    expect(script).toContain('outputConfidenceMasks: true');
    expect(script).toContain('foundSegMixRise: 0.12');
    expect(script).toContain('function openFrontCamera()');
    expect(script).toContain('height: { ideal: 720, max: 960 }');
    expect(script).toContain('fps >= TUNING.segmentMinFps || !foundSkinReady');
    expect(script).not.toContain('blurPass');
    expect(script).toContain('zoomMin: 1');
    expect(script).toContain('zoomMax: 4');
    expect(script).toContain('function applyViewZoom()');
    expect(script).toContain('pinchStartZoom * (d / pinchStartDist)');
    expect(script).toContain("canvas.style.transform = t");
    expect(script).toContain("overlay.style.transform = t");
    expect(script).not.toContain('aspectRatio: { ideal: 9 / 16 }');
    expect(script).toContain('gl.uniform1f(u.uBrowCov, browZ ? clamp01(browZ.intensity) * EYEBROW_PRESET.baseOpacity : 0);');
    expect(script).toContain('col = mix(col, mix(film, pigment, uFoundOpaque), foundA);');
    expect(script).toContain('baseOpacity: 1.0');
    expect(script).toContain('headDensity: 0.4');
    expect(script).toContain('archDensity: 0.85');
    expect(script).toContain('tailDensity: 0.9');
    expect(script).toContain('hairFloor: 0.0');
    expect(script).toContain('extraDrop: 0.0');
    // Brow as a real product: a translucent pencil/powder film in a feathered shape, then brow mascara on
    // the hairs only (camera brightness kept, chromaticity moved). No generated strands, no flat color.
    expect(script).toContain('uniform vec2 uBrowSkin[12];');
    expect(script).toContain('float skinRef = max(max(sBelow, sAbove) / 3.0, 1e-3);');
    expect(script).toContain('float hairW = smoothstep(0.10, 0.45, 1.0 - camL / skinRef)');
    expect(script).toContain('col = mix(col, powder(cam, uBrowAlbedo), browA * uBrowPowder);');
    expect(script).toContain('vec3 tinted = col * clamp(chromaP / max(chromaC, vec3(1e-4)), 0.0, 1.5);');
    expect(script).toContain('col = mix(col, tinted, browA * hairW);');
    expect(script).toContain('vec2 bo = uTexel * uBrowSoft;');
    expect(script).toContain('function browGuides(W, H)');
    for (const gone of ['uBrowStrand', 'strandFreq', 'recol', 'uBrowHue', 'vec3 dyed', 'localMax']) expect(script).not.toContain(gone);
    expect(script).toContain('towardEye');
    expect(script).toContain('dropTowardEye');
    expect(script).not.toContain('browLumAt');
    expect(script).not.toContain('ringLum');
    expect(script).toContain('createLinearGradient(h[0], h[1], t[0], t[1])');
    expect(script).not.toContain('mix(col, layer(cam, uBrowAlbedo, uSkinMeanLum, 1.2), browA)');
    expect(script).not.toMatch(/bisenet|huggingface|stable.?diffusion|psgan|face-parsing/i);
    expect(script).toContain('rgba2[i * 4 + 3] = Math.round(clamp01(foundInside * (1 - lipShape[i]) * (1 - eyesCut[i]) * (1 - browCut[i])) * 255);');
    expect(script).toContain('if (browPaint) {');
    expect(script).toContain('pathOn(browCtx, lower.concat(upper));');
    expect(script).toContain('vec4 eyeAt(vec2 s) {');
    expect(script).toContain('float browG = uEyeRect.x > -1.0 ? browAt(suv) : 0.0;');
    expect(script).toContain('for (const ids of [BROWS.slice(0, 10), BROWS.slice(10)]) {');
    expect(script).not.toContain('0.07 * eyeW');
    // Translucent powder tints the skin (no ashy patch on deep skin); no skin smoothing anywhere.
    expect(script).toContain("'  return mix(layer(cam, albedo, uSkinMeanLum, 1.6), tint, uPowderTint);',");
    expect(script).not.toMatch(/bilateral|smoothSkin|skinSmooth/i);
  });

  it('shades a two-tone eyeshadow from its own lid landmarks and shapes liner and lashes by geometry (gal look)', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // Second color: wedge at the outer corner and a stroke along the lower lash line, per eye, in UV mask 2 (B).
    expect(script).toContain('const shadowDark = layer(() => {');
    expect(script).toContain("rgba2[i * 4 + 2] = Math.round(clamp01(shadowDark[i] * inside) * 255);");
    expect(script).toContain("if (darkA > 0.002) col = mix(col, powder(cam, uShadow2Albedo), darkA);");
    expect(script).toContain('gl.uniform1f(u.uShadow2Cov, eye && eye.hexTo ? clamp01(eye.intensity) * TUNING.shadow2Coverage : 0);');
    // Without a second color the shadow is unchanged (coverage 0), and the eyeball is never painted.
    expect(script).toContain('darkA = 0.0; innerA = 0.0; foundA = 0.0; browA = 0.0; }');
    // Mascara length and density come from geometry (defaults 1, clamped), never random per frame.
    expect(script).toContain("const mg = Object.assign({ length: 1, thickness: 1 }, mascara.geometry || {});");
    // 11-07 natural mascara lash: few strands, tapered C-curve ribbons fading to the tip, faint lash line and lower lashes.
    expect(script).toContain('const nLash = clamp(Math.round(TUNING.lashCount * mg.thickness), 8, 24);');
    expect(script).toContain('lashCount: 14,');
    expect(script).toContain('const hw = 0.5 * Math.max(0.9, w * k) * Math.pow(1 - t, 0.9);');
    expect(script).toContain('const g = Math.round(255 * (1 - TUNING.lashTipFade * (t0 + t1) * 0.5));');
    expect(script).toContain('const pull = [(cx - own[0]) * TUNING.lashClump * clamp01(mascara.intensity), (cy - own[1]) * TUNING.lashClump * clamp01(mascara.intensity)];');
    expect(script).toContain('const L = eyeW * TUNING.lashLength * lengthen * prof * (0.78 + 0.34 * seeded(i + 100)) * wisp;');
    expect(script).toContain('c.lineWidth = Math.max(0.6, TUNING.lashLineWidth * eyeW * k);');
    expect(script).not.toContain('0.035 * eyeW * k');
    expect(script).not.toContain('smoothstep(0.05, 0.45, lashG)');
    expect(script).not.toMatch(/Math\.random\(/);
    // Highlighter also covers the forehead centre and under the eyes.
    expect(script).toContain('ellipse(fc, [fc[0] + 1, fc[1]], 0.9 * fw, 0.5 * fw, 0.55);');
  });

  it('draws an overlip on the skin with the skin as the bare reference, never over the teeth (retro / semi gal look)', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // The expanded ring is the paint area (R, G); the landmark ring stays in B, so the band between is skin.
    expect(script).toContain('function overlipRing(base, shape)');
    expect(script).toContain("c.fillStyle = '#00f';");
    expect(script).toContain('skinRefW = clamp((inside - insideBase) / max(inside, 1e-3), 0.0, 1.0);');
    // Corners never move, the extension fades to zero there, and it shrinks as the mouth opens.
    expect(script).toContain('if (i === 0 || i === 10) return q;');
    expect(script).toContain('const f = 1 - TUNING.overlipOpenReduce * clamp((open - 0.12) / 0.35, 0, 1);');
    // On the band the bare reference is the measured skin (color, brightness), not the lip mean.
    expect(script).toContain('vec3 refCol = mix(uLipColor, uSkinColor, skinRefW);');
    expect(script).toContain('float meanL = mix(max(uLipMeanLum, 1e-3), max(uSkinMeanLum, 1e-3), skinRefW);');
    // Lip-centre highlight is brightness only (a multiplier), placed from landmarks 0 and 17, not a UV template.
    expect(script).toContain('layered *= 1.0 + uCenterHl * exp(-cd * cd)');
    expect(script).toContain('((sx[0] + sx[17]) / 2) * W');
    // With no overlip the outline is the landmark ring itself (nothing changes for other looks).
    expect(script).toContain('if (!over && !peak) return base;');
  });

  it('adds the inner-corner pearl, keeps the wing on the face, and picks highlighter areas by name', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    expect(script).toContain('const ip = shadow && shadow.geometry && shadow.geometry.innerPoint;');
    expect(script).toContain('const len = Math.min(g.length * eyeW, 0.8 * dist(outer, edgeP));');
    expect(script).toContain('const nLow = mg.lower === false ? 0 : Math.round(nLash / 4);');
    // Named areas come from mask 3; with none named the default mask (and its pixels) is used.
    expect(script).toContain('float hlMask = uHlLegacy > 0.5 ? m2.r : clamp(dot(m3, uHlAreas), 0.0, 1.0);');
    expect(script).toContain("gl.uniform1f(u.uHlLegacy, hlAreas ? 0 : 1);");
    // Highlighter stays a product color on fixed regions (AR_SPEC 1-2, 1-3): no luminance-only skin lift.
    expect(script).not.toMatch(/uBrighten|mode: 'brighten'/);
  });

  it('draws the cheek from the face points with its own placement, size and softness (soft peach coral look)', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // Two rotated ellipses in the face's UV space, clipped to below the lower lid; the default baked mask otherwise.
    expect(script).toContain('float blushM = uBlushDyn > 0.5 ? max(blushEll(vUv, uBlushE0, uBlushR0), blushEll(vUv, uBlushE1, uBlushR1)) : m.g;');
    expect(script).toContain('return a * (1.0 - smoothstep(r.z - 0.012, r.z, uv.y));');
    expect(script).toContain('const LOWER_LID_MID = [145, 374];');
    expect(script).toContain("if (placement === 'under_eye') ctr = lerp(ctr, lid, 0.5);");
    expect(script).toContain('const blushDyn = !!(blushGeo && (blushGeo.blushPlacement');
    // The apple sits under the pupil (lower-lid point and cheek point); the baked default mask is left as it was.
    expect(script).toContain('let ctr = [lid[0] + (low[0] - lid[0]) * 0.5');
    expect(script).toContain('const blush = layer(() => {');
  });

  it('gates the uploaded light color by Gray World confidence and snaps when skin Lab jumps', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // Untrusted color mixes toward white; direction and strength stay on their own uniforms.
    expect(script).toContain('const w = clamp(light.colorConf, 0, 1);');
    expect(script).toContain('1 + w * (light.color[0] - 1)');
    expect(script).toContain('gl.uniform3f(u.uLightDir, light.dir[0], light.dir[1], light.dir[2]);');
    expect(script).toContain('gl.uniform1f(u.uLightStrength, light.strength);');
    expect(script).toContain('lightChangeDelta: 6');
    expect(script).toContain('cie76(lab, light.refSkinLab) > TUNING.lightChangeDelta');
    expect(script).toContain('const kc = light.colorSamples++ === 0 || snap ? 1');
    expect(script).toContain("type: 'light_hint'");
    expect(script).toContain('blownFaceFraction: 0.15');
    const gate = (color: number[], conf: number) => color.map((c) => 1 + conf * (c - 1));
    const warm = [1.25, 1.05, 0.8];
    expect(gate(warm, 0)).toEqual([1, 1, 1]);
    expect(gate(warm, 1)).toEqual(warm);
    const mid = gate(warm, 0.5);
    expect(mid[0]).toBeCloseTo(1.125);
    expect(mid[2]).toBeCloseTo(0.9);
    const linToLab = (rgb: number[]) => {
      const x = (0.4124 * rgb[0] + 0.3576 * rgb[1] + 0.1805 * rgb[2]) / 0.95047;
      const y = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2];
      const z = (0.0193 * rgb[0] + 0.1192 * rgb[1] + 0.9505 * rgb[2]) / 1.08883;
      const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
      const fx = f(x), fy = f(y), fz = f(z);
      return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)] as const;
    };
    const cie76 = (a: readonly number[], b: readonly number[]) =>
      Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
    const daylight = linToLab([0.42, 0.28, 0.22]);
    const tungsten = linToLab([0.55, 0.32, 0.18]);
    expect(cie76(daylight, daylight)).toBe(0);
    expect(cie76(daylight, tungsten)).toBeGreaterThan(6);
  });

  it('glides the light direction only behind its switch and snaps the estimate past the snap angle', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    expect(script).toContain('lightDirGlide: false,');
    expect(script).toContain('lightDirSec: 0.4,');
    expect(script).toContain('lightDirSnapDeg: 25,');
    // Switch off: the shader still gets the 0.5 s estimate exactly as before.
    expect(script).toContain('gl.uniform1f(u.uLightConf, light.dirConf);');
    expect(script).toContain('gl.uniform3f(u.uLightDir, shown.dir[0], shown.dir[1], shown.dir[2]);');
    expect(script).toContain('const kd = TUNING.lightDirGlide && turn > TUNING.lightDirSnapDeg ? 1 : k;');
    expect(script).toContain("'light ms ' + lightMs.toFixed(1)");

    const glideSrc = script.slice(script.indexOf('  function glideLight(now) {'), script.indexOf('    return shownLight;\n  }') + '    return shownLight;\n  }'.length);
    const run = (glideOn: boolean) =>
      new Function('glideOn', `
        const TUNING = { lightDirGlide: glideOn, lightDirSec: 0.4, lightDisplaySec: 0.6, skinRefLum: 0.34, exposureRange: [0.2, 1.6] };
        const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
        const light = { color: [1, 1, 1], colorConf: 0, dir: [1, 0, 0], strength: 1.5, dirConf: 1, skinMeanLum: 0.34, sh: [1, 0, 0, 0, 0, 0, 0, 0, 0] };
        const shownLight = { color: [1, 1, 1], exposure: 1, skinMeanLum: 0.34, dir: [0, 0, 1], strength: 1, conf: 0, sh: [1, 0, 0, 0, 0, 0, 0, 0, 0], t: 0 };
        ${glideSrc}
        glideLight(1000);
        light.dir = [0, 0, 1];
        const steps = [];
        for (let t = 1000 + 1000 / 30; t < 1500; t += 1000 / 30) steps.push(glideLight(t).dir[2]);
        return { steps, shown: shownLight };
      `)(glideOn) as { steps: number[]; shown: { dir: number[]; strength: number; conf: number } };

    const off = run(false);
    expect(off.shown.dir).toEqual([0, 0, 1]);
    expect(off.shown.conf).toBe(0);
    const on = run(true);
    // A face just found (t = 0) jumps; after that each frame moves part of the way, never all at once.
    expect(on.shown.strength).toBeCloseTo(1.5);
    expect(on.shown.conf).toBeCloseTo(1);
    expect(on.steps[0]).toBeGreaterThan(0);
    expect(on.steps[0]).toBeLessThan(0.3);
    expect(on.steps.every((z, i) => i === 0 || z >= on.steps[i - 1])).toBe(true);
    expect(on.steps[on.steps.length - 1]).toBeGreaterThan(0.6);
  });

  it('fits the light with Huber IRLS only behind its switch, and mixes in the relative signal for confidence', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    expect(script).toContain('lightRobust: false,');
    expect(script).toContain('lightHuberC: 1.345,');
    expect(script).toContain('lightConfRel: [0.3, 0.6],');
    // Switch off: the 20% cut and the R²-only confidence stay as they were.
    expect(script).toContain('const cut = resid.slice().sort((p, q) => p - q)[Math.floor(resid.length * 0.8)];');
    expect(script).toContain('let conf = clamp((r2 - TUNING.lightConfR2[0]) / (TUNING.lightConfR2[1] - TUNING.lightConfR2[0]), 0, 1);');
    expect(script).toContain('if (TUNING.lightRobust) {\n          conf = Math.max(conf,');

    const src = script.slice(script.indexOf('  function solve4(A, b) {'), script.indexOf('  function ensureFoundSkinBuffers('));
    const res = new Function(`
      const TUNING = { lightHuberC: 1.345, lightIrlsIters: 4 };
      ${src}
      // Lambert skin lit from 45° to the side, plus a few blown specular dots facing the camera.
      const L = [Math.SQRT1_2, 0, Math.SQRT1_2];
      const samples = [];
      let seed = 7;
      const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
      for (let i = 0; i < 200; i++) {
        const t = rnd() * Math.PI * 0.9 - Math.PI * 0.45, p = rnd() * Math.PI * 0.8 - Math.PI * 0.4;
        const n = [Math.sin(t) * Math.cos(p), Math.sin(p), Math.cos(t) * Math.cos(p)];
        let y = 0.1 + 0.3 * Math.max(0, n[0] * L[0] + n[1] * L[1] + n[2] * L[2]);
        if (i % 12 === 0 && n[2] > 0.8) y = 0.95;
        samples.push([n[0], n[1], n[2], y]);
      }
      const ang = (f) => {
        const m = Math.hypot(f[1], f[2], f[3]);
        return Math.acos((f[1] * L[0] + f[2] * L[1] + f[3] * L[2]) / m) * 180 / Math.PI;
      };
      const plain = fitLight(samples);
      const rob = fitLightRobust(samples);
      return { plain: ang(plain), robust: ang(rob.fit), same: fitLight(samples, samples.map(() => 1)).every((v, i) => Math.abs(v - plain[i]) < 1e-12) };
    `)() as { plain: number; robust: number; same: boolean };
    expect(res.same).toBe(true);
    expect(res.robust).toBeLessThan(res.plain);
  });

  it('fits SH9 light only behind lightModel, falls back to the linear fit, and keeps the linear shader path', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    expect(script).toContain("lightModel: 'linear',");
    expect(script).toContain("if (TUNING.lightModel === 'sh9') {");
    // Linear: the lip volume ratio and the gloss light size are set exactly as before.
    expect(script).toContain('float form = max(dot(lipFormN, lV), 0.0) / max(dot(lipBaseN, lV), 0.2);');
    expect(script).toContain('if (uLightModel > 0.5) {');
    expect(script).toContain('gl.uniform2f(u.uLightSize, TUNING.lightSize[0], TUNING.lightSize[1]);');
    expect(script).toContain("gl.uniform1f(u.uLightModel, TUNING.lightModel === 'sh9' && TUNING.lightShVolume ? 1 : 0);");
    expect(script).toContain('lightShVolume: false,');
    expect(script).toContain('lightShSizeSpread: 0,');

    const src = script.slice(script.indexOf('  function solve4(A, b) {'), script.indexOf('  function ensureFoundSkinBuffers('));
    const res = new Function(`
      const TUNING = { lightHuberC: 1.345, lightIrlsIters: 4, lightShIters: 6, lightShMinSamples: 60, lightShMaxCond: 1e5 };
      ${src}
      const ev = symEigen([[2, 1, 0], [1, 2, 0], [0, 0, 5]]).sort((p, q) => p - q);
      // Lambert skin plus ambient on front-facing normals, lit 60° from the side: the shadowed cheek is flat, which tilts a
      // straight-line fit toward the side.
      const L = [Math.sin(Math.PI / 3), 0, Math.cos(Math.PI / 3)];
      const samples = [];
      let seed = 11;
      const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
      while (samples.length < 300) {
        const x = rnd() * 2 - 1, y = rnd() * 2 - 1;
        if (x * x + y * y > 1 - 0.35 * 0.35) continue;
        const n = [x, y, Math.sqrt(1 - x * x - y * y)];
        samples.push([n[0], n[1], n[2], 0.06 + 0.3 * Math.max(0, n[0] * L[0] + n[1] * L[1] + n[2] * L[2])]);
      }
      const ang = (f) => Math.acos(Math.min(1, (f[1] * L[0] + f[2] * L[1] + f[3] * L[2]) / Math.hypot(f[1], f[2], f[3]))) * 180 / Math.PI;
      const lin = fitLight(samples);
      const lam = fitLightLambert(samples);
      const sh = lambertToSH([0.06, 0.3 * L[0], 0.3 * L[1], 0.3 * L[2]]);
      const shAt = (n) => shBasis(n[0], n[1], n[2]).reduce((s, v, i) => s + v * sh[i], 0);
      return { ev, lin: ang(lin), lam: ang(lam.fit), cond: lam.cond, few: fitLightLambert(samples.slice(0, 59)),
               peak: shAt(L), away: shAt([-L[0], -L[1], -L[2]]) };
    `)() as { ev: number[]; lin: number; lam: number; cond: number; few: unknown; peak: number; away: number };
    expect(res.ev[0]).toBeCloseTo(1, 6);
    expect(res.ev[1]).toBeCloseTo(3, 6);
    expect(res.ev[2]).toBeCloseTo(5, 6);
    expect(res.cond).toBeGreaterThan(1);
    expect(res.few).toBeNull();
    expect(res.lin).toBeGreaterThan(5);
    expect(res.lam).toBeLessThan(0.5);
    // SH9 of ambient + clamped cosine: about 0.06 + 0.3 toward the light, about the ambient facing away.
    expect(res.peak).toBeCloseTo(0.36, 1);
    expect(Math.abs(res.away - 0.06)).toBeLessThan(0.03);
  });

  it('mixes Gray-Edge into the background light color only behind its switch', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    expect(script).toContain('lightColorEdge: false,');
    expect(script).toContain('lightColorEdgeMix: [0.25, 0.75],');
    // Off: the Gray World estimate and the one-color check on the raw sums, as before.
    expect(script).toContain('let est = [r / Y, g / Y, bl / Y];');
    expect(script).toContain('let chroma = Math.max(r, g, bl) / Math.max(1e-6, Math.min(r, g, bl));');
    expect(script).toContain('if (TUNING.lightColorEdge && eY > 0) {');

    const src = script.slice(script.indexOf('  function bgColorSums('), script.indexOf('  function runSegmenter('));
    const sums = (edge: boolean) =>
      new Function('edge', `
        const TUNING = { lightColorEdge: edge, clipLin: 0.92, darkLum: 0.02 };
        function toLin(c) { return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }
        function lumOf(r, g, b) { return 0.2126 * r + 0.7152 * g + 0.0722 * b; }
        ${src}
        // 3 x 1 frame: two background pixels side by side, the third is the person (class 3).
        const data = new Uint8ClampedArray([200, 100, 100, 255, 100, 200, 100, 255, 100, 100, 200, 255]);
        return bgColorSums(new Uint8Array([0, 0, 3]), 3, 1, data, 3, 1);
      `)(edge) as { r: number; g: number; bl: number; n: number; er: number; eg: number; eb: number };
    const toLin = (c: number) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
    const off = sums(false), on = sums(true);
    expect(off.n).toBe(2);
    expect(off.r).toBeCloseTo(toLin(200 / 255) + toLin(100 / 255), 6);
    expect([off.er, off.eg, off.eb]).toEqual([0, 0, 0]);
    expect([on.r, on.g, on.bl, on.n]).toEqual([off.r, off.g, off.bl, off.n]);
    // One pair of neighbours; the person pixel is left out.
    expect(on.er).toBeCloseTo(toLin(200 / 255) - toLin(100 / 255), 6);
    expect(on.eg).toBeCloseTo(toLin(200 / 255) - toLin(100 / 255), 6);
    expect(on.eb).toBeCloseTo(0, 6);
  });

  it('keeps the open-mouth paint off the teeth: guard band, camera inner line, outer line pulled in only', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    expect(script).toContain('lipTeethGuard: true,');
    expect(script).toContain('lipInnerMeasure: true,');
    expect(script).toContain('lipEdgePull: true,');
    // Guard: only inside the inner-line band (outline G, drawn after the lip form read G).
    expect(script).toContain("'      lipM *= 1.0 - band * max(notRed * pale * flatL, dark);',");
    expect(script.indexOf('if (TUNING.lipForm) drawLipForm(srcW, srcH);')).toBeLessThan(script.indexOf("c.globalCompositeOperation = 'multiply';"));
    // Pull-in never pushes the outer line out.
    expect(script).toContain('return j % 10 === 0 || lipEdge.conf[r] <= 0.5 || t >= 1 ? 0 : -Math.min(1 - t, TUNING.lipEdgePullMax);');

    const ring = script.slice(script.indexOf('  function lipRing('), script.indexOf('  // Cubic curve through the ring'));
    const inner = script.slice(script.indexOf('  const lipInner = {'), script.indexOf('  // Lip outline in screen space'));
    const run = new Function(`
      const TUNING = { lipOutlineSmooth: 0, lipInnerEveryMs: 100, refineMinContrast: 0.02, teethDark: 0.3, innerInset: [0.12, 0.28] };
      const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
      const toLin = (c) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
      const lumOf = (r, g, b) => 0.2126 * r + 0.7152 * g + 0.0722 * b;
      // 20 outer / inner points: upper lip y 0.4 -> 0.5, lower lip y 0.8 -> 0.7, x 0.3..0.7.
      const LIPS_OUTER = Array.from({ length: 20 }, (_, j) => j), LIPS_INNER = Array.from({ length: 20 }, (_, j) => 20 + j);
      const sx = new Array(40).fill(0), sy = new Array(40).fill(0);
      for (let j = 0; j < 20; j++) {
        const up = j <= 10, x = 0.3 + 0.4 * (up ? j / 10 : (20 - j) / 10);
        sx[j] = x; sx[20 + j] = x;
        sy[j] = up ? 0.4 : 0.8; sy[20 + j] = up ? 0.5 : 0.7;
      }
      let closed = false;
      const mouthClosed = () => closed;
      const light = { lipRed: 0.5, skinRed: 0.1, lipMeanLum: 0.1 };
      const video = {};
      // Camera: lip red up to 0.1 of the thickness past each inner point, white teeth between.
      const edgeCrop = { width: 0, height: 0 };
      const edgeCropCtx = { drawImage() {}, getImageData: () => {
        const d = new Uint8ClampedArray(edgeCrop.width * edgeCrop.height * 4);
        for (let y = 0; y < edgeCrop.height; y++) for (let x = 0; x < edgeCrop.width; x++) {
          const ny = 0.4 + (0.4 * (y + 0.5)) / edgeCrop.height, lip = ny < 0.51 || ny > 0.69, k = (y * edgeCrop.width + x) * 4;
          d[k] = lip ? 200 : 240; d[k + 1] = lip ? 40 : 240; d[k + 2] = lip ? 40 : 240; d[k + 3] = 255;
        }
        return { data: d };
      } };
      ${ring}
      ${inner}
      measureLipInner(1000, 1000, 1000);
      measureLipInner(1000, 1000, 1050);
      const conf1 = Array.from(lipInner.conf);
      measureLipInner(1000, 1000, 1200);
      const t = Array.from(lipInner.t), conf = Array.from(lipInner.conf);
      closed = true;
      measureLipInner(1000, 1000, 1400);
      const confClosed = Array.from(lipInner.conf);
      // Per-point inset: point 1 moves 0.1 of its thickness away from its partner, the others stay.
      const moved = lipRing([0, 1, 2], [], 1, 1, [20, 21, 22], [0, 0.1, 0]);
      return { t, conf, conf1, confClosed, moved };
    `)() as { t: number[]; conf: number[]; conf1: number[]; confClosed: number[]; moved: number[][] };
    // Corners are not measured; the others find the lip end about 0.1 into the mouth, within one step.
    expect(run.conf[0]).toBe(0);
    expect(run.conf[10]).toBe(0);
    for (const j of [1, 5, 9, 11, 15, 19]) {
      expect(run.t[j]).toBeGreaterThanOrEqual(0.119);
      expect(run.t[j]).toBeLessThan(0.16);
      expect(run.conf[j]).toBeGreaterThanOrEqual(0.5);
    }
    // A second call within lipInnerEveryMs is skipped.
    expect(run.conf1[1]).toBe(0.5);
    expect(run.confClosed.every((c) => c === 0)).toBe(true);
    expect(run.moved[0][0]).toBeCloseTo(0.3, 6);
    expect(run.moved[0][1]).toBeCloseTo(0.4, 6);
    expect(run.moved[2][1]).toBeCloseTo(0.4, 6);
    expect(run.moved[1][1]).toBeCloseTo(0.4 + 0.1 * (0.4 - 0.5), 6);
  });

  it('sizes lid grains on screen, flashes glitter toward a fixed light, and fades both while blinking', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    expect(script).toContain('lidSparkle: true,');
    // Off: the old grains, flakes and cell scales.
    expect(script).toContain("'  float rad = 0.16;',");
    expect(script).toContain("'      float spec = lidFlake(vUv, n, l, v);',");
    expect(script).toContain('gl.uniform1f(u.uShadowFlakeScale, isGlitter ? TUNING.glitterScale : TUNING.shimmerScale);');
    // Glitter does not read the estimated light direction; shimmer reads it only through its confidence.
    const glint = script.slice(script.indexOf("'float lidGlint("), script.indexOf("'float shadowSheen("));
    expect(glint).not.toMatch(/\bl\b/);
    expect(script).toContain("'      vec3 lS = normalize(mix(vec3(0.0, 0.25, 1.0), l, uLightConf));',");

    const src = script.slice(script.indexOf('  const lidSparkle = {'), script.indexOf('  function drawEyes('));
    const run = new Function(`
      const TUNING = { lidOpenGap: [0.08, 0.18] };
      // One triangle (corners 0, 8 and point 17 above corner 0): 0.1 / 0.05 UV and 100 / 50 px, a uniform 1000 px per UV.
      const EYE_LINES = [{ upper: [0, 1, 2, 3, 4, 5, 6, 7, 8], lower: [0, 9, 10, 11, 12, 13, 14, 15, 8] }];
      const N_MESH = 18, FACE_TRIANGLES = [0, 8, 17];
      const FACE_UV = new Array(36).fill(0);
      FACE_UV[16] = 0.1; FACE_UV[35] = -0.05;
      const sx = new Array(18).fill(0.5), sy = new Array(18).fill(0.5);
      sx[17] = 0.4; sy[17] = 0.45;
      const clamp01 = (v) => Math.max(0, Math.min(1, v));
      function lerp(a, b, t) { return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]; }
      function dist(a, b) { return Math.hypot(b[0] - a[0], b[1] - a[1]); }
      ${src}
      // A 100 px eye on a 1000 px frame, lids 30 px apart, then nearly closed (5 px).
      const setEye = (gapPx) => {
        sx[0] = 0.4; sx[8] = 0.5;
        for (const i of [3, 5]) { sx[i] = 0.45; sy[i] = 0.5 - gapPx / 2000; }
        for (const i of [11, 13]) { sx[i] = 0.45; sy[i] = 0.5 + gapPx / 2000; }
      };
      setEye(30);
      const open = Object.assign({}, lidSparkleState(1000, 1000));
      setEye(5);
      const shut = Object.assign({}, lidSparkleState(1000, 1000));
      setEye(30);
      const metric = Array.from(fillLidMetric(1000, 1000, 100).slice(0, 3));
      sx[17] = 0.45;
      const sheared = Array.from(fillLidMetric(1000, 1000, 100).slice(0, 3));
      return { open, shut, metric, sheared };
    `)() as { open: { pxPerUv: number; open: number }; shut: { pxPerUv: number; open: number }; metric: number[]; sheared: number[] };
    // 100 px over 0.1 UV: 1000 px per UV.
    expect(run.open.pxPerUv).toBeCloseTo(1000, 3);
    // 100 cells per UV: 10 px a cell, no stretch (metric 100 * identity); a sheared triangle is not round.
    expect(run.metric[0]).toBeCloseTo(100, 3);
    expect(run.metric[1]).toBeCloseTo(0, 3);
    expect(run.metric[2]).toBeCloseTo(100, 3);
    expect(Math.abs(run.sheared[1])).toBeGreaterThan(10);
    expect(run.open.open).toBe(1);
    expect(run.shut.open).toBe(0);
    expect(run.shut.pxPerUv).toBeCloseTo(1000, 3);
  });

  it('locks white balance once the room color settles, at the settled temperature, and follows faster when unlocked', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // No fixed 2 s timer: the lock waits for a tracked face and two background color estimates that agree.
    expect(script).not.toContain('setTimeout(() => tryLockWhiteBalance(track), 2000)');
    expect(script).toContain('const settled = light.colorSamples >= 2 && light.colorDelta < TUNING.wbStableDelta;');
    expect(script).toContain('if (!settled && age < TUNING.wbLockMaxMs) return;');
    // The current temperature goes with the lock so the image does not jump to a default.
    expect(script).toContain('wb.colorTemperature = colorTempK;');
    // Unlocked (iPhone): the light color is estimated more often and follows faster.
    expect(script).toContain('const segEvery = wbLocked ? TUNING.segmentEveryMs : TUNING.segmentEveryMsAuto;');
    expect(script).toContain('wbLocked ? TUNING.lightSmoothing : TUNING.lightSmoothingAuto');
  });

  it('draws the drawing guide on the overlay canvas from the filtered landmarks, per step', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // The app switches it on and off with one message; off clears the canvas.
    expect(script).toContain("if (msg.type === 'guide') {");
    expect(script).toContain('if (!guide) overlayCtx.clearRect(0, 0, overlay.width, overlay.height);');
    // Mirrored like the WebGL canvas, so the lines sit on the video.
    expect(script).toContain('const P = (i) => [(1 - sx[i]) * W, sy[i] * H];');
    for (const step of ['eyebrow', 'eyeshadow', 'eyeliner', 'lip']) expect(script).toContain("step === '" + step + "'");
    // Brow guide: three lines from the nose wing through the inner corner, the pupil and the outer corner.
    expect(script).toContain('const NOSE_WING = [129, 358];');
    expect(script).toContain('const EYE_CORNERS = [{ inner: 133, outer: 33, iris: 468 }, { inner: 362, outer: 263, iris: 473 }];');
    // The wing angle comes from the look, not a fixed number. Three liner styles share that angle.
    expect(script).toContain('const theta = ((Number(guide.angle) || 15) * Math.PI) / 180;');
    expect(script).toContain("style === 'tightline'");
    expect(script).toContain("style === 'puppy'");
    expect(script).toContain("String(guide.style || 'classic_winged')");
    // No network or storage in the page (AR_SPEC 1-4): the guide only reads landmarks.
    const guideCode = script.slice(script.indexOf('function drawGuide'), script.indexOf('function drawOverlay'));
    expect(guideCode).not.toMatch(/fetch|XMLHttpRequest|localStorage|postMessage|toDataURL/);
  });

  it('keeps tutorial finish labels aligned with the blush / liner / shadow shader', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    const blushPow = (rough: number) => {
      const t = Math.min(1, Math.max(0, (rough - 0.16) / 0.74));
      return 1.7 * (1 - t) + 0.5 * t;
    };
    // Matte powder: wider edge (lower pow). Glossy cream: tighter edge.
    expect(blushPow(0.9)).toBeLessThan(blushPow(0.16));
    expect(blushPow(0.9)).toBeCloseTo(0.5);
    expect(blushPow(0.16)).toBeCloseTo(1.7);
    // Eyeliner has no finish (10-29): matte / glossy no longer change how it renders.
    expect(script).not.toContain('uLinerGloss');
    expect(script).toContain('flake: 0');
    expect(script).toContain('flake: 1');
    expect(script).toContain('flakeScaleShimmer: 480');
  });

  it('ties blush edge, liner smudge, and shimmer flake size to finish roughness', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // Blush mask falloff follows face roughness: glossy tightens, matte spreads.
    expect(script).toContain('float blushPow = mix(1.7, 0.5, clamp((uFaceRough.x - 0.16) / 0.74, 0.0, 1.0));');
    expect(script).toContain('blushM = pow(max(blushM, 0.0), blushPow);');
    // Every liner is one flat opaque ink (10-29): a half-texel anti-alias read, the core snapped to full coverage,
    // no matte halo and no gloss sheen; a smudge style only adds a halo and never lowers the core.
    expect(script).not.toContain('halo');
    expect(script).toContain('linerR = smoothstep(0.05, 0.45, linerR);');
    expect(script).toContain('linerR = max(linerR, mix(linerR, min(wide * (1.0 + 2.5 * uLinerSoft), 1.0), uLinerSoft));');
    expect(script).toContain('col = mix(col, uLinerAlbedo * uLightColor * uExposure, linerA);');
    expect(script).not.toContain('layer(cam, uLinerAlbedo');
    expect(script).not.toContain('uLinerCrisp');
    expect(script).toContain('thickness: 0.09');
    expect(script).toContain('function openSpline(p, samples)');
    expect(script).not.toContain('EYELINER_PRESET.lineWing');
    expect(script).not.toContain('function drawLineWing(');
    expect(script).not.toContain("g.linerShape === 'line'");
    expect(script).not.toContain('irisDrop');
    expect(script).not.toContain('lowerThickness');
    expect(script).not.toContain('dualWing');
    expect(script).not.toContain('TubeGeometry');
    expect(script).not.toContain('cleanWing');
    expect(script).not.toContain('slimWing');
    expect(script).not.toContain('sharpWing');
    // The lid wing design is gone; one band + wing path serves every style, deep black and never under 1.5 texels.
    expect(script).not.toContain('lidWing');
    expect(script).not.toContain('isLidWing');
    expect(script).not.toContain('linerShape');
    expect(script).toContain('opacity: 1.0,');
    expect(script).toContain('minPx: 1.5,');
    expect(script).toContain('gl.uniform1f(u.uLinerCov, liner ? EYELINER_DARK.opacity : 0);');
    expect(script).toContain('const th = Math.max(thickOuter * (innerShare + (1 - innerShare) * Math.pow(t, taper)), floorPx);');
    expect(script).not.toContain('uLinerFeather');
    // Blink: eyelid and iris points use their own One Euro values so the liner does not trail the lid.
    expect(script).toContain('eyeSmooth: { minCutoff: 3.0, beta: 200, dCutoff: 6.0 },');
    expect(script).toContain('const a = eyeI ? euroAlpha(ES.minCutoff + ES.beta * speed, dt)');
    expect(script).not.toContain('(d[0] / dl) * 0.8 * th');
    expect(script).not.toContain('(d[0] / dl) * 0.2 * th');
    expect(script).not.toContain('const lift = 0.3 * thickOuter');
    // Shimmer uses larger UV flake cells; matte still has flake 0 so no sparks.
    expect(script).toContain('vec2 cell = floor(uv * uFlakeScale);');
    expect(script).toContain('flakeScaleShimmer: 480');
    expect(script).toContain(
      'gl.uniform1f(u.uFlakeScale, (eyeMat.flake || hlMat.flake || lipMat.flake) ? TUNING.flakeScaleShimmer : TUNING.flakeScale)',
    );
  });

  it('brightens the lid centre without particles and tints a sheer film by hue only', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // Pearl: brightness only (a multiplier), placed by the mesh normal so it slides with the head.
    expect(script).toContain('col *= 1.0 + uPearl * lidMid * lidLobe * shadowA;');
    // Particles can be switched off per look; the highlighter has its own strength multiple.
    expect(script).toContain('eye && eyeFinish.sparkleDensity > 0 ? clamp01(eye.intensity) : 0');
    expect(script).toContain('const hlGain = hl && hl.geometry && hl.geometry.intensity != null');
    // A sheer film tints by the dye's hue only: a full-color filter after the blend darkened a red lip twice.
    expect(script).toContain('vec3 filt = clamp(uLipAlbedo / uPaperWhite, 0.0, 1.0);');
  });

  it('paints lid finishes from opacity, roughness, and pearl-share density', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    expect(script).toContain('float lidGrain(vec2 uv)');
    expect(script).toContain('float lidFlake(vec2 uv, vec3 n, vec3 l, vec3 v)');
    expect(script).toContain('float shadowSheen(vec3 n, vec3 l, vec3 v, float rough)');
    expect(script).toContain('shimmer: { opacity: 0.3,  roughness: 0.4, sparkleDensity: 0.35, specular: 0.4 }');
    expect(script).toContain('glitter: { opacity: 0.3,  roughness: 0.2, sparkleDensity: 0.75, specular: 0.95 }');
    expect(script).toContain('matte:   { opacity: 0.7,  roughness: 1.0, sparkleDensity: 0.0, specular: 0.0 }');
    expect(script).toContain('glossy:  { opacity: 0.25, roughness: 0.05, sparkleDensity: 0.0, specular: 0.9 }');
    expect(script).toContain('shimmerScale: 520');
    expect(script).toContain('float lidPearlFade(float maskB)');
    expect(script).toContain('col = mix(col, col * tint, shadowA)');
    expect(script).toContain('float isGloss = (1.0 - hasPearl) * (1.0 - step(0.97, uFaceRough.y));');
    expect(script).toContain('vec3(0.93, 0.96, 1.0)');
    expect(script).toContain('glitterScale: 600');
    expect(script).toContain('if (hash(cell) >= uShadowFlakeDensity) return 0.0;');
    expect(script).not.toContain('hash(cell + 9.2)');
    expect(script).toContain('if (rough > 0.97) return 0.0;');
    expect(script).toContain('float r = max(rough, 0.05);');
    expect(script).toContain('isGloss * 2.2 * shadowA');
    expect(script).toContain('hasPearl * pearlW * uShadowSpec * 1.4 * uShadowFlake * spec');
    expect(script).toContain('float rad = 0.16;');
    expect(script).toContain('return grain * pow(ndh, 6.0);');
    expect(script).not.toContain('sparkleSheen:');
    expect(script).not.toContain('lidNdh * lidNdh');
    expect(script).not.toContain('uniform float uGlitter');
    expect(script).toContain('gl.uniform1f(u.uShadowCov, eye ? clamp01(eye.intensity) * eyeFinish.opacity : 0)');
    expect(script).toContain('YouCam glowIntensity stays 0');
    expect(script).not.toContain('makeupar.com');
    expect(script).not.toContain('YOUCAM_API_KEY');
    expect(script).toContain("g.addColorStop(0.55, 'rgba(255,255,255,0.85)')");
    expect(script).toContain('const low = pts(eye.contour.slice(0, 9))');
  });

  it('keeps a sheer coral from darkening a red lip (model of the shader mix, linear light)', () => {
    // Same arithmetic as the shader's lip mix: coverage blends the bare lip toward the product, then the
    // see-through share tints by the dye's hue with its brightness kept.
    const lin = (c: number) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));
    const rgb = (hex: string) => [1, 3, 5].map((i) => lin(parseInt(hex.slice(i, i + 2), 16) / 255));
    const lum = (c: number[]) => 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
    const sheer = (bare: number[], hex: string, a1: number, layers: number, translucent: number) => {
      const albedo = rgb(hex);
      const cov = 1 - Math.pow(1 - a1, layers);
      const paint = bare.map((b, k) => b + (albedo[k] - b) * cov);
      const filt = albedo.map((v) => Math.min(1, v / 0.85));
      const fl = lum(filt);
      return paint.map((p, k) => p * (1 + (filt[k] / fl - 1) * cov * translucent));
    };
    const coral = '#F2735B';
    // Red and pale-red bare lips (linear, as the camera sees them): the result keeps at least the brightness of the
    // darker of bare lip and product, never a double-filtered drop.
    for (const bare of [[0.32, 0.12, 0.1], [0.5, 0.22, 0.2], [0.2, 0.06, 0.06]]) {
      const out = sheer(bare, coral, 0.38, 3 * 0.56, 0.8);
      expect(lum(out)).toBeGreaterThan(Math.min(lum(bare), lum(rgb(coral))) * 0.97);
    }
  });

  it('keeps medium satin coverage below a sticker-like full cover', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    const block = script.match(/satin:\s*\{[^}]+\}/);
    expect(block).toBeTruthy();
    const a1 = Number(block![0].match(/a1:\s*([0-9.]+)/)?.[1]);
    const layers = 0.6 * 3;
    const coverage = 1 - (1 - a1) ** layers;
    expect(a1).toBeGreaterThan(0.3);
    expect(a1).toBeLessThan(0.75);
    expect(coverage).toBeLessThan(0.8);
  });

  it('tells the app when WebGL is lost and releases models and camera on pagehide', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    expect(script).toMatch(/webglcontextlost.*type: 'crash'/);
    expect(script).toContain("addEventListener('pagehide'");
    expect(script).toContain('landmarker.close()');
    expect(script).toContain('segmenter.close()');
    expect(script).toContain('t.stop()');
  });
});
