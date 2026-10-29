import { FACE_TRACKER_HTML, MEDIAPIPE_VERSION } from '@/components/ar/faceTrackerHtml';

function moduleScript(html: string) {
  const match = html.match(/<script type="module">([\s\S]*?)<\/script>/);
  if (!match) throw new Error('module script not found');
  return match[1];
}

describe('face tracker page', () => {
  it('embeds a syntactically valid script', () => {
    // The page script lives inside a template string, so typecheck/lint never see it.
    expect(() => new Function(moduleScript(FACE_TRACKER_HTML))).not.toThrow();
  });

  it('pins the MediaPipe version and keeps the host protocol', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    expect(script).toContain(`'${MEDIAPIPE_VERSION}'`);
    for (const token of ["type: 'hello'", "type: 'status'", "msg.type === 'makeup'", "msg.type === 'compare'"]) {
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
    // the bare lip only survives a smooth finish (a matte pigment covers it).
    expect(script).toContain('float hl = min(hlCap, max(hlPeak, hlWide * smoothT)) * core;');
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
    expect(script).toContain('vec3 sheenCol = uLightColor * mix(hue, vec3(1.0), smooth1 * smooth1 * smooth1);');
    expect(script).toContain('vec3 specTint = mix(uLipAlbedo, vec3(1.0), 0.16)');
    // Layering stays. No painted-over lip shape, drawn grooves, noise texture, or a normal drawn from
    // a template. The one lip normal allowed is the form built from this person's own outline
    // (lipFormN, 10-25 user request: finish highlights must appear even when the camera shows none).
    for (const synthetic of ['formShape', 'sin(across', 'lipN ', 'lipN=', 'vnoise', 'uPigmentHeadroom']) {
      expect(script).not.toContain(synthetic);
    }
    // Sheen never fully turns off when the light direction is untrusted.
    expect(script).toContain('specFill');
    expect(script).toContain('max(uLightConf, uSpecFill)');
    // The outer edge comes from the screen-space outline, never from a per-pixel redness test that
    // grew lumps along the line at close range (10-25).
    expect(script).toContain('lipM = m.r * inside;');
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
    expect(script).toContain('lo: -0.01, hi: 0.05,');
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
    expect(script).toContain('uFrontGloss * (sharpF + uWideGloss * lobeN(nf, rW))');
    expect(script).toContain('* uSkinMeanLum * uGlossGain');
    // Flat selfie: form gloss rises when the camera has no specular; matte (smooth1²) stays dull.
    expect(script).toContain('uGlossFlat * (1.0 - smoothstep(0.02, 0.12, camSpec)) * smooth1 * smooth1');
    expect(script).toMatch(/glossFlat:\s*1\.2/);
    // No pale rim where opaque paint crosses onto skin.
    expect(script).toContain('layered *= mix(1.0, min(1.0, meanL / max(uSkinMeanLum, 1e-3)), skinW * opaqueW);');
    // Matte stays dull: its highlight peak is far below a gloss's.
    const pair = script.match(/glossMax:\s*\[([0-9.]+),\s*([0-9.]+)\]/);
    expect(Number(pair?.[1])).toBeLessThan(0.1);
    expect(Number(pair?.[2])).toBeGreaterThan(0.5);
  });

  it('paints the wet inner lip on open mouths and ignores face points outside the frame', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // Inner line moved into the mouth by openness (LaPa: 13% of open-mouth lip lay inside it).
    expect(script).toContain('const inner = lipRing(LIPS_INNER, INNER_FIXED, W, H, LIPS_OUTER, mouthClosed() ? 0 : inset);');
    expect(script).toContain('innerInset: [0.05, 0.2]');
    // Close-ups: vertices outside the frame never feed the light estimate.
    expect(script).toContain('const skinIn = masks.skinVerts.filter((i) => meshNrm[i * 3 + 2] >= 0.35 && inFrame(i));');
  });

  it('moves the makeup with the face in the same frame (no trailing on a head shake)', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // Raw anchors (mouth centre near the mouth, face centre elsewhere); One Euro only on the offsets.
    expect(script).toContain('const x = face[i].x - ax(i), y = face[i].y - ay(i);');
    expect(script).toContain('for (let i = 0; i < n; i++) { sx[i] = ax(i) + ox[i]; sy[i] = ay(i) + oy[i]; }');
  });

  it('draws eyeliner and mascara from the lid landmarks, following blinks (10-25)', () => {
    const script = moduleScript(FACE_TRACKER_HTML);
    // Screen-space eye canvas, uploaded only while a liner or mascara is on.
    expect(script).toContain('const mascara = null, hl = null, contourZ = null;');
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
    expect(script).toContain('gl.uniform1f(u.uContourCov, contourZ ? clamp01(contourZ.intensity) * TUNING.contourCoverage : 0);');
    expect(script).toContain('gl.uniform1f(u.uFoundCov, foundZ ? clamp01(foundZ.intensity) * TUNING.foundCoverage : 0);');
    expect(script).toContain('gl.uniform1f(u.uBrowCov, browZ ? clamp01(browZ.intensity) * EYEBROW_PRESET.baseOpacity : 0);');
    expect(script).toContain('if (foundA > 0.002) col = mix(col, powder(cam, uFoundAlbedo), foundA);');
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
    expect(script).toContain('rgba2[i * 4 + 3] = Math.round(clamp01(inside * (1 - lipShape[i]) * (1 - eyesCut[i]) * (1 - browCut[i])) * 255);');
    expect(script).toContain('if (browPaint) {');
    expect(script).toContain('path(lower.concat(upper));');
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
    expect(script).toContain('const nLash = clamp(Math.round(TUNING.lashCount * mg.thickness), 12, 72);');
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
    expect(script).toContain('const nLow = mg.lower === false ? 0 : Math.round(nLash / 3);');
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
});
