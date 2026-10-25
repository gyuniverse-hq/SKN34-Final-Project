/**
 * Self-contained page that runs MediaPipe Face Landmarker on the front camera and
 * renders makeup. Runs fully on-device: frames are never stored or sent.
 *
 * Rendering (AR_SPEC 6-4, 6-5, PBR_DEMO_SPEC 6): the 468-point face mesh is drawn with the
 * canonical model's UVs (components/ar/faceUV.ts), so masks painted once in UV space stay on
 * the lips, cheeks and lids when the head turns. Mouth and eyes are holes in the mesh.
 * Lips are layered, not painted over (AR_SPEC 6-5-3): the camera pixel is light × shading × bare-lip
 * color, and lipstick only changes the lip color. The page measures the bare-lip color, builds the
 * lipstick layer on top of it (opaque pigment covers it, sheer/gloss tints it like a dye) and
 * multiplies the camera pixel by layered / bare reflectance. Camera wrinkles, light and noise stay.
 * The product hex is the mid-tone: UV position then splits lightness and chroma (upper lip and
 * corners darker and richer, lower-lip centre lighter and a little softer) so a flat selfie still
 * shows a lipstick gradient. Sheen is the same colour, brighter; white GGX is only a small lower-
 * centre peak. Coverage = 1 - (1 - a1)^layers (6-7). Pixels outside the masks are discarded.
 * Each new camera frame is uploaded first and the landmarks are detected on that same frame, so
 * the makeup never trails the image. The lip outline is drawn in screen space each frame from the
 * smoothed landmarks (sharp corners, no mesh-triangle kinks), softened by the measured camera blur.
 * Paint darkens toward that outline (lip volume). Coverage fades slightly toward the inner (wet)
 * line and the mouth corners.
 * Light (6-6-1): color from background Gray World (selfie multiclass segmenter), direction
 * and strength from skin brightness vs. mesh normals, both every 0.5 s.
 * Requires WebGL; without it the page reports `unavailable` and the host shows swatches.
 * Double-tap the view to toggle a debug HUD (FPS, light estimate). Tune values in TUNING.
 *
 * Protocol
 *   host → page : {"type":"makeup","makeup":MakeupState} | {"type":"compare","value":boolean}
 *   page → host : {"type":"hello"} | {"type":"status","status":ArStatus,"detail"?:string}
 */
import { FACE_MOUTH_TRIANGLES, FACE_TRIANGLES, FACE_UV } from './faceUV';

export const MEDIAPIPE_VERSION = '1.1.1';

export type ArStatus = 'loading' | 'tracking' | 'no-face' | 'denied' | 'unavailable';

export const FACE_TRACKER_HTML = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no" />
<style>
  html, body { margin: 0; padding: 0; height: 100%; background: #000; overflow: hidden; }
  video { position: absolute; width: 1px; height: 1px; opacity: 0; pointer-events: none; }
  canvas { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
  #hud { position: absolute; left: 8px; top: 84px; padding: 6px 8px; border-radius: 6px; display: none;
         background: rgba(0,0,0,0.55); color: #fff; font: 11px/1.4 monospace; white-space: pre; pointer-events: none; }
</style>
</head>
<body>
<video id="video" playsinline muted autoplay></video>
<canvas id="canvas"></canvas>
<canvas id="overlay" style="pointer-events: none"></canvas>
<div id="hud"></div>
<script type="module">
  const VERSION = '${MEDIAPIPE_VERSION}';
  const MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task';
  const SEG_MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/image_segmenter/selfie_multiclass_256x256/float32/latest/selfie_multiclass_256x256.tflite';
  const FACE_UV = ${JSON.stringify(FACE_UV)};
  const FACE_TRIANGLES = ${JSON.stringify(FACE_TRIANGLES)};
  const FACE_MOUTH_TRIANGLES = ${JSON.stringify(FACE_MOUTH_TRIANGLES)};
  const NL = String.fromCharCode(10);

  // ── Tuning: adjust these on real devices ─────────────────────────────
  const TUNING = {
    // One Euro on each point's offset from the raw face centre (the centre itself is unfiltered).
    smoothMinCutoff: 1.5,       // lower = steadier when still (more lag in expression changes)
    smoothBeta: 25,             // higher = less lag when the face changes shape or turns
    smoothDCutoff: 2.0,         // speed estimate cutoff: 1.0 made the filter open late when motion began
    maskSize: 1024,             // UV mask texture size
    lipFeatherPx: 3,            // UV-space blur radii (≈ screen px at a normal distance)
    lipEdgePx: 2,               // outer lip line: crisp like a real lipstick edge
    innerFadePx: 6,             // coverage fades over this width toward the inner (wet) lip line
    innerFadeStrength: 0.3,     // coverage lost right at the inner line
    // A real lipstick reaches the mouth corners (10-25 reference photo); 0.12 / 0.35 left the corner
    // tip at 0.22 of the lip's color on 60 real faces, now 0.50 together with lipFill.
    cornerFadeSize: 0.06,       // mouth-corner fade radius as a share of the mouth width
    cornerFadeStrength: 0.1,    // coverage lost right at the corners
    // The UV mask says where the lip is, not how much paint: its soft edge, the thin corner wedge and
    // the inner fade all read as half-painted lip. × this, capped at 1: full color up to a ~1 px
    // edge (outer 2 px of the lip 0.35 → 0.68 of the core color; LaPa miss 19.4% → 16.5%, spill
    // 15.7% → 18.4%).
    lipFill: 1.6,
    layersPerIntensity: 3,      // intensity slider → number of swipes (0.35 ≈ 1, 0.85 ≈ 2.5)
    lipBandPx: 5,               // UV band around the lips where lip fragments are drawn (the outline decides inside it)
    refineMinContrast: 0.02,    // lip-vs-skin redness gap below which the lip/skin tests are off
    // Outline in screen space (10-25 close-ups: the UV spline warped per mesh triangle into kinks and
    // beak corners, and the 256 px UV redness band grew lumps). Drawn each frame from the landmarks.
    lipOutlinePx: 512,          // longest side of the outline crop texture
    lipOutlineSmooth: 0.5,      // Taubin smoothing of the landmark ring (corners and Cupid's bow fixed)
    innerInset: [0.05, 0.2],    // open mouth: inner line moved into the mouth (share of lip thickness), slightly → wide open
    // Lip form (10-25 "직접 바른 느낌", user request): each lip is a rounded body built from this
    // person's outline (upper and lower lip apart, split at the inner line). Its normal shades the
    // paint (Lambert under the estimated light) and places each finish's GGX highlight, so a gloss
    // shines on the lower-lip centre and upper-lip ridge and a matte stays dull. The 10-25 edge band
    // darkening read as a drawn liner on thin, open lips.
    lipForm: true,
    formReach: 0.45,            // form blur radius as a share of this lip's thickness
    formFieldPx: 160,           // longest side of the blurred form field
    formTilt: 1.0,              // max tilt of the form normal at the lip line (≈ 45°)
    lipVolume: 0.6,             // share of the form's Lambert falloff applied to the paint
    seamPx: 0.12,               // closed mouth: seam split width as a share of the lip thickness
    glossMax: [0.04, 0.85],     // form highlight peak: matte → glossy (by (1 - roughness)³; satin ≈ 0.2)
    glossGain: 3.0,             // highlight peak = glossMax × skin luminance × this (light sources ≫ skin)
    frontGloss: 0.6,            // share of the peak from the always-present frontal source (screen, room)
    lightSize: [0.35, 0.6],      // light size (roughness units): the source's sharp reflection, the glow around it
    wideGloss: 0.3,             // glow peak relative to the sharp reflection
    grainMax: 0.2,              // cap on the measured relative camera grain
    blurMax: 4,                 // cap on the measured camera blur (px): sets grain size and mask edge softness
    lipGlint: 1.5,              // glints on lip ridges (absolute), scaled by (1 - roughness)²
    glintThreshold: 0.04,       // fine detail below this share of the lip mean (camera noise) never glints
    diffuseCap: 1.3,            // camera brightness above this × lip mean counts as highlight, not color
    specFill: 0.7,              // floor on light-dir mix so PBR sheen never fully turns off
    creaseGain: 1.0,            // scale on material detail (how much of the camera's wrinkle contrast stays)
    paperWhite: 0.85,           // reflectance of the swatch paper: tint transmittance² = product color / this
    ratioMax: 4.0,              // cap on layered/bare reflectance per channel (bright paint on dark lips)
    lumGainMax: 1.15,           // estimated chip hex may not make the lip brighter than bare × this
    creaseCover: 0.15,          // matte pigment collects in creases (+), gloss thins on ridges (−)
    mouthClosedGap: 0.06,       // inner-lip gap / mouth width below which the mouth hole is painted
    lipRayOutlier: 0.2,         // a lip-edge ray this far (share of lip) from its neighbours' median is skipped
    hlLocal: 1.15,              // camera highlight must exceed the local 3px mean by this (a peak, not a lit area)
    hlSat: [0.3, 0.55],         // ...and be desaturated: lip color saturation ~0.6, specular ~0.2
    hlBlown: 2.2,               // or be this × lip mean (a wide reflection has no local peak in its middle)
    opaqueShadeGamma: 0.6,      // large-scale brightness swing kept under fully opaque paint (1 = all, 0 = flat sticker)
    lowReach: 0.35,             // radius of the large-scale lip brightness, share of the lip thickness
    lipSpecMax: 0.18,           // cap on the added clear-coat highlight (tinted, lower-centre only)
    lipSheen: 0.25,             // broad clear-coat sheen × (1 - roughness)²; coarse mesh normals miss the narrow peak
    hlKeep: [0.15, 1.0],        // camera highlight kept under the paint: matte → glossy (by 1 - roughness); never amplified
    blushFeatherPx: 28,
    // Highlighter and contour (10-25, user request): product color on fixed UV regions only, like
    // blush. Intensity 0 leaves the image untouched; no shape change (AR_SPEC 1-2, 1-3).
    hlFeatherPx: 18,
    contourFeatherPx: 28,
    faceEdgeFadePx: 36,         // contour / highlighter fade-out width inside the face outline (UV px)
    hlCoverage: 0.5,
    contourCoverage: 0.55,
    powderTint: 0.6,            // blush / contour: share that tints the skin (translucent) instead of covering it
    faceSheen: 0.5,             // finish sheen on blush / shadow / highlighter: peak × skin luminance, by smoothness
    // Eyeliner and mascara: drawn in screen space each frame from the lid landmarks (thin lines
    // must follow the lid exactly; a UV line warps per mesh triangle).
    eyeCanvasPx: 512,
    liner: { length: 0.18, angle: 15, thickness: 0.045 }, // defaults: wing length / eye width, degrees, outer thickness / eye width
    linerInnerThin: 0.3,        // inner-corner thickness as a share of the outer thickness
    lashCount: 32,              // mascara strands per upper lid
    lashLength: 0.1,            // longest strand, share of the eye width (front view foreshortens lashes)
    lashWidth: 0.012,           // strand width, share of the eye width
    lowerLash: 0.4,             // lower lashes: length share of the upper
    shadowFeatherPx: 10,
    blushSize: [0.17, 0.11],    // ellipse radii relative to the UV face width
    shadowCrease: 0.6,          // how far toward the brow the shadow reaches (0..1)
    blushCoverage: 0.6,         // coverage = intensity × this
    shadowCoverage: 0.8,
    skinRefLum: 0.34,           // assumed skin reflectance (linear Y) for exposure scaling
    exposureRange: [0.2, 1.6],
    specMax: 0.85,
    flakeDensity: 0.985,        // share of UV cells without a shimmer flake
    shimmerFlake: 0.9,
    lightEveryMs: 500,
    segmentEveryMs: 2000,       // background segmentation (light color) is heavier: run less often
    segmentMinFps: 20,          // and skip it while the frame rate is low
    lightSmoothing: 0.35,
    lightColorClamp: [0.75, 1.3],
    bgMinFraction: 0.15,        // Gray World needs this share of background pixels
    bgMaxChroma: 1.6,           // max/min channel ratio above which the background is "one color"
    clipLin: 0.92,              // linear value treated as blown out
    darkLum: 0.02,
    lightConfR2: [0.1, 0.4],    // R² of the normal→brightness fit mapped to confidence 0..1
  };
  // roughness/specular/flake: PBR_DEMO_SPEC 5 starting values, then detail/specular nudged
  // toward finish medians in research/data/reference/lip_texture/lip_texture.sqlite (Pexels/Unsplash
  // direction of change vs. bare lips — not a1 or colour ground truth; 6-15 still owns measured a1).
  // a1: share of the lip covered by one swipe; translucent: 0 = paint over, 1 = tint like a filter;
  // detail: how much of the camera's wrinkle contrast stays under the paint (1 = all of it).
  // Lip shading itself is never a material value: it is the real camera shading (layering, 6-5-3).
  const MATERIALS = {
    matte:   { roughness: 0.90, specular: 0.35, flake: 0, a1: 0.72, translucent: 0.0, detail: 1.15 },
    velvet:  { roughness: 0.75, specular: 0.45, flake: 0, a1: 0.66, translucent: 0.0, detail: 1.10 },
    cream:   { roughness: 0.55, specular: 0.60, flake: 0, a1: 0.58, translucent: 0.12, detail: 1.05 },
    satin:   { roughness: 0.42, specular: 0.85, flake: 0, a1: 0.50, translucent: 0.12, detail: 1.15 },
    sheer:   { roughness: 0.32, specular: 0.90, flake: 0, a1: 0.38, translucent: 0.8, detail: 1.05 },
    glossy:  { roughness: 0.16, specular: 1.15, flake: 0, a1: 0.46, translucent: 0.28, detail: 0.95 },
    shimmer: { roughness: 0.38, specular: 0.90, flake: 1, a1: 0.55, translucent: 0.12, detail: 1.10 },
  };
  function lipCoverage(zone, mat) {
    const layers = Math.max(0.3, clamp01(zone.intensity) * TUNING.layersPerIntensity);
    return 1 - Math.pow(1 - mat.a1, layers);
  }

  const LIPS_OUTER = [61,185,40,39,37,0,267,269,270,409,291,375,321,405,314,17,84,181,91,146];
  const LIPS_INNER = [78,191,80,81,82,13,312,311,310,415,308,324,318,402,317,14,87,178,88,95];
  const EYES = [
    { lid: [33,246,161,160,159,158,157,173,133], brow: [46,53,52,65,55],
      contour: [33,7,163,144,145,153,154,155,133,173,157,158,159,160,161,246] },
    { lid: [263,466,388,387,386,385,384,398,362], brow: [276,283,282,295,285],
      contour: [263,249,390,373,374,380,381,382,362,398,384,385,386,387,388,466] },
  ];
  const BROWS = [70,63,105,66,107,55,65,52,53,46,300,293,334,296,336,285,295,282,283,276];
  const CHEEKS = [
    { inner: 50, outer: 116, low: 205 },
    { inner: 280, outer: 345, low: 425 },
  ];
  const FACE_EDGES = [234, 454];
  const N_MESH = 468;
  const N_LANDMARKS = 478;

  const video = document.getElementById('video');
  const glCanvas = document.getElementById('canvas');
  const hud = document.getElementById('hud');
  const overlay = document.getElementById('overlay');
  const overlayCtx = overlay.getContext('2d');

  let makeup = { lip: null, blush: null, eyeshadow: null, eyeliner: null, mascara: null, highlighter: null, contour: null };
  let compare = false;
  let landmarker = null;
  let landmarkerDelegate = '-';
  let segmenter = null;
  let lastVideoTime = -1;
  let lastFaceAt = 0;
  let hasFace = false;
  let status = null;
  let renderer = null;

  // ── Messaging ────────────────────────────────────────────────────────
  function post(message) {
    const text = JSON.stringify(message);
    if (window.ReactNativeWebView) window.ReactNativeWebView.postMessage(text);
    else if (window.parent !== window) window.parent.postMessage(text, '*');
  }
  function setStatus(next, detail) {
    if (status === next) return;
    status = next;
    post({ type: 'status', status: next, detail });
  }
  function handleMessage(raw) {
    let msg;
    try { msg = typeof raw === 'string' ? JSON.parse(raw) : raw; } catch (e) { return; }
    if (!msg || typeof msg !== 'object') return;
    if (msg.type === 'makeup' && msg.makeup) makeup = msg.makeup;
    if (msg.type === 'compare') compare = !!msg.value;
  }
  window.__kb = { receive: handleMessage };
  window.addEventListener('message', (e) => handleMessage(e.data));
  document.addEventListener('message', (e) => handleMessage(e.data));

  // ── Color helpers (sRGB EOTF, AR_SPEC 6-5) ───────────────────────────
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function clamp01(v) { return clamp(Number(v) || 0, 0, 1); }
  function toLin(c) { return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }
  function hexToLinear(hex) {
    const h = String(hex || '').replace('#', '');
    const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16) || 0;
    return [toLin(((n >> 16) & 255) / 255), toLin(((n >> 8) & 255) / 255), toLin((n & 255) / 255)];
  }
  function lumOf(r, g, b) { return 0.2126 * r + 0.7152 * g + 0.0722 * b; }

  // ── One Euro filter over all landmarks (no per-frame allocation) ─────
  const sx = new Float32Array(N_LANDMARKS);
  const sy = new Float32Array(N_LANDMARKS);
  const sz = new Float32Array(N_LANDMARKS);
  const dvx = new Float32Array(N_LANDMARKS);
  const dvy = new Float32Array(N_LANDMARKS);
  let filterReady = false;
  let filterT = 0;
  function euroAlpha(cutoff, dt) { const tau = 1 / (2 * Math.PI * cutoff); return 1 / (1 + tau / dt); }
  // Anchors follow the raw landmarks with no filter, and One Euro smooths only each point's offset from
  // its anchor: a head shake or turn moves the makeup in the same frame (device 10-25: it trailed
  // behind), while a still face keeps its steadiness. The anchor is the mouth centre near the mouth
  // and the face centre elsewhere, blended by canonical distance (no seam). Simulated at 30 fps, ±60 px:
  // 2 Hz shake max error 20.8 → 2.2 px, turn (mouth moving more than the face) 27.3 → 2.2 px.
  const ox = new Float32Array(N_LANDMARKS);
  const oy = new Float32Array(N_LANDMARKS);
  let mouthW = null;
  function mouthWeights() {
    const w = new Float32Array(N_LANDMARKS);
    let mx = 0, my = 0;
    for (const i of LIPS_OUTER) { mx += FACE_UV[2 * i]; my += FACE_UV[2 * i + 1]; }
    mx /= LIPS_OUTER.length; my /= LIPS_OUTER.length;
    const mw = Math.hypot(FACE_UV[2 * 61] - FACE_UV[2 * 291], FACE_UV[2 * 61 + 1] - FACE_UV[2 * 291 + 1]);
    for (let i = 0; i < N_MESH; i++) {
      const d = Math.hypot(FACE_UV[2 * i] - mx, FACE_UV[2 * i + 1] - my) / mw;
      const s = clamp((d - 0.6) / 0.9, 0, 1);
      w[i] = 1 - s * s * (3 - 2 * s);
    }
    return w;
  }
  function filterLandmarks(face, t) {
    const n = Math.min(N_LANDMARKS, face.length);
    if (!mouthW) mouthW = mouthWeights();
    let cx = 0, cy = 0, mx = 0, my = 0;
    for (let i = 0; i < n; i++) { cx += face[i].x; cy += face[i].y; }
    cx /= n; cy /= n;
    for (const i of LIPS_OUTER.concat(LIPS_INNER)) { mx += face[i].x; my += face[i].y; }
    mx /= LIPS_OUTER.length + LIPS_INNER.length; my /= LIPS_OUTER.length + LIPS_INNER.length;
    const ax = (i) => cx + mouthW[i] * (mx - cx), ay = (i) => cy + mouthW[i] * (my - cy);
    if (!filterReady || t - filterT > 0.5) {
      for (let i = 0; i < n; i++) { ox[i] = face[i].x - ax(i); oy[i] = face[i].y - ay(i); sz[i] = face[i].z || 0; dvx[i] = 0; dvy[i] = 0; }
      filterReady = true; filterT = t;
    } else {
      const dt = Math.max(0.001, t - filterT);
      filterT = t;
      const ad = euroAlpha(TUNING.smoothDCutoff, dt);
      for (let i = 0; i < n; i++) {
        const x = face[i].x - ax(i), y = face[i].y - ay(i);
        dvx[i] += ad * ((x - ox[i]) / dt - dvx[i]);
        dvy[i] += ad * ((y - oy[i]) / dt - dvy[i]);
        const speed = Math.sqrt(dvx[i] * dvx[i] + dvy[i] * dvy[i]);
        const a = euroAlpha(TUNING.smoothMinCutoff + TUNING.smoothBeta * speed, dt);
        ox[i] += a * (x - ox[i]);
        oy[i] += a * (y - oy[i]);
        sz[i] += a * ((face[i].z || 0) - sz[i]);
      }
    }
    for (let i = 0; i < n; i++) { sx[i] = ax(i) + ox[i]; sy[i] = ay(i) + oy[i]; }
  }

  // ── UV masks: painted once (R = lips, G = blush, B = eyeshadow) ──────
  function lerp(a, b, t) { return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]; }
  function dist(a, b) { return Math.hypot(b[0] - a[0], b[1] - a[1]); }
  function centroid(list) {
    let x = 0, y = 0;
    for (const p of list) { x += p[0]; y += p[1]; }
    return [x / list.length, y / list.length];
  }
  function splinePath(c, p) {
    const n = p.length;
    c.moveTo(p[0][0], p[0][1]);
    for (let i = 0; i < n; i++) {
      const p0 = p[(i - 1 + n) % n], p1 = p[i], p2 = p[(i + 1) % n], p3 = p[(i + 2) % n];
      c.bezierCurveTo(
        p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6,
        p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6,
        p2[0], p2[1]
      );
    }
    c.closePath();
  }
  function boxBlur(src, S, r) { return boxBlurRect(src, S, S, r); }
  // Two box passes (≈ a smooth bell) over a W × H field.
  function boxBlurRect(src, W, H, r) {
    if (r < 1) return src;
    let a = src;
    const b = new Float32Array(W * H);
    const w = 2 * r + 1;
    for (let pass = 0; pass < 2; pass++) {
      for (let y = 0; y < H; y++) {
        const row = y * W;
        let acc = 0;
        for (let x = -r; x <= r; x++) acc += a[row + clamp(x, 0, W - 1)];
        for (let x = 0; x < W; x++) {
          b[row + x] = acc / w;
          acc += a[row + Math.min(W - 1, x + r + 1)] - a[row + Math.max(0, x - r)];
        }
      }
      const c = pass === 0 ? new Float32Array(W * H) : a;
      for (let x = 0; x < W; x++) {
        let acc = 0;
        for (let y = -r; y <= r; y++) acc += b[clamp(y, 0, H - 1) * W + x];
        for (let y = 0; y < H; y++) {
          c[y * W + x] = acc / w;
          acc += b[Math.min(H - 1, y + r + 1) * W + x] - b[Math.max(0, y - r) * W + x];
        }
      }
      a = c;
    }
    return a;
  }
  function paintMasks() {
    const S = TUNING.maskSize;
    const canvas = document.createElement('canvas');
    canvas.width = S; canvas.height = S;
    const c = canvas.getContext('2d', { willReadFrequently: true });
    const U = (i) => [FACE_UV[2 * i] * S, FACE_UV[2 * i + 1] * S];
    const pts = (list) => list.map(U);
    function layer(draw, feather) {
      c.globalCompositeOperation = 'source-over';
      c.clearRect(0, 0, S, S);
      draw();
      const d = c.getImageData(0, 0, S, S).data;
      const out = new Float32Array(S * S);
      for (let i = 0; i < S * S; i++) out[i] = d[i * 4 + 3] / 255;
      return boxBlur(out, S, Math.round(feather / 2));
    }
    const lipShape = layer(() => {
      c.fillStyle = '#fff';
      c.beginPath();
      splinePath(c, pts(LIPS_OUTER));
      c.fill();
    }, TUNING.lipEdgePx);
    const innerGlow = layer(() => {
      c.fillStyle = '#fff';
      c.strokeStyle = '#fff';
      c.lineWidth = TUNING.innerFadePx;
      c.lineJoin = 'round';
      c.beginPath();
      splinePath(c, pts(LIPS_INNER));
      c.fill();
      c.stroke();
    }, TUNING.innerFadePx);
    const cornerR = dist(U(61), U(291)) * TUNING.cornerFadeSize;
    const cornerGlow = layer(() => {
      for (const p of [U(61), U(291)]) {
        const g = c.createRadialGradient(p[0], p[1], 0, p[0], p[1], cornerR);
        g.addColorStop(0, 'rgba(255,255,255,1)');
        g.addColorStop(1, 'rgba(255,255,255,0)');
        c.fillStyle = g;
        c.beginPath(); c.arc(p[0], p[1], cornerR, 0, Math.PI * 2); c.fill();
      }
    }, 0);
    const lip = new Float32Array(S * S);
    const lipFade = new Float32Array(S * S);
    const corner = new Float32Array(S * S);
    for (let i = 0; i < S * S; i++) {
      corner[i] = 1 - TUNING.cornerFadeStrength * cornerGlow[i];
      lipFade[i] = (1 - TUNING.innerFadeStrength * innerGlow[i]) * corner[i];
      lip[i] = lipShape[i] * lipFade[i];
    }
    const band = layer(() => {
      c.fillStyle = '#fff';
      c.strokeStyle = '#fff';
      c.lineWidth = TUNING.lipBandPx * 2;
      c.lineJoin = 'round';
      c.beginPath();
      splinePath(c, pts(LIPS_OUTER));
      c.fill();
      c.stroke();
    }, TUNING.lipFeatherPx);
    const faceW = dist(U(FACE_EDGES[0]), U(FACE_EDGES[1]));
    const blush = layer(() => {
      for (const cheek of CHEEKS) {
        const inner = U(cheek.inner), outer = U(cheek.outer);
        const center = lerp(lerp(inner, outer, 0.4), U(cheek.low), 0.25);
        c.save();
        c.translate(center[0], center[1]);
        c.rotate(Math.atan2(outer[1] - inner[1], outer[0] - inner[0]));
        c.scale(faceW * TUNING.blushSize[0], faceW * TUNING.blushSize[1]);
        const g = c.createRadialGradient(0, 0, 0, 0, 0, 1);
        g.addColorStop(0, 'rgba(255,255,255,1)');
        g.addColorStop(0.4, 'rgba(255,255,255,0.75)');
        g.addColorStop(0.75, 'rgba(255,255,255,0.3)');
        g.addColorStop(1, 'rgba(255,255,255,0)');
        c.fillStyle = g;
        c.beginPath(); c.arc(0, 0, 1, 0, Math.PI * 2); c.fill();
        c.restore();
      }
    }, TUNING.blushFeatherPx);
    const shadow = layer(() => {
      for (const eye of EYES) {
        const lid = pts(eye.lid);
        const crease = eye.brow.map((bi, j) => {
          const li = Math.round((j * (lid.length - 1)) / (eye.brow.length - 1));
          return lerp(lid[li], U(bi), TUNING.shadowCrease);
        });
        const lidC = centroid(lid), creaseC = centroid(crease);
        const g = c.createLinearGradient(lidC[0], lidC[1], creaseC[0], creaseC[1]);
        g.addColorStop(0, 'rgba(255,255,255,1)');
        g.addColorStop(0.55, 'rgba(255,255,255,0.67)');
        g.addColorStop(1, 'rgba(255,255,255,0.15)');
        c.fillStyle = g;
        c.beginPath(); splinePath(c, lid.concat(crease.slice().reverse())); c.fill();
      }
    }, TUNING.shadowFeatherPx);
    // Highlighter and contour, drawn on one side and mirrored about the face midline.
    const midU = [1, 4, 5, 6, 168, 152, 10, 0, 17].reduce((a, i) => a + U(i)[0], 0) / 9;
    function bothSides(drawSide) {
      drawSide();
      c.save(); c.translate(2 * midU, 0); c.scale(-1, 1); drawSide(); c.restore();
    }
    function polyStroke(ids, width, alpha) {
      c.globalAlpha = alpha; c.lineWidth = width; c.lineCap = 'round'; c.lineJoin = 'round';
      c.beginPath(); ids.map(U).forEach((q, i) => (i ? c.lineTo(q[0], q[1]) : c.moveTo(q[0], q[1]))); c.stroke();
    }
    function ellipse(center, toward, rMajor, rMinor, alpha) {
      c.save(); c.globalAlpha = alpha; c.translate(center[0], center[1]);
      c.rotate(Math.atan2(toward[1] - center[1], toward[0] - center[0]));
      c.beginPath(); c.ellipse(0, 0, rMajor, rMinor, 0, 0, Math.PI * 2); c.fill(); c.restore();
    }
    const noseW = dist(U(6), U(122));
    const highlight = layer(() => {
      c.fillStyle = '#fff'; c.strokeStyle = '#fff';
      bothSides(() => {
        // Cheekbone apex, long toward the temple; inner eye corner.
        const apex = lerp(U(111), U(143), 0.3);
        ellipse(apex, U(34), 0.55 * dist(U(117), U(34)), 0.16 * dist(U(117), U(34)), 1);
        const eyeW = dist(U(33), U(133));
        c.globalAlpha = 0.5; c.beginPath(); const ic = lerp(U(133), U(168), 0.25); c.arc(ic[0], ic[1], 0.12 * eyeW, 0, Math.PI * 2); c.fill();
      });
      // Nose bridge and above the Cupid's bow (on the midline).
      polyStroke([168, 6, 197, 195, 5], 0.9 * noseW, 0.7);
      c.globalAlpha = 0.6; c.beginPath(); const cb = lerp(U(0), U(164), 0.55); c.arc(cb[0], cb[1], 0.35 * dist(U(0), U(164)), 0, Math.PI * 2); c.fill();
      c.globalAlpha = 1;
    }, TUNING.hlFeatherPx);
    const contour = layer(() => {
      c.strokeStyle = '#fff';
      bothSides(() => {
        const base = dist(U(123), U(147));
        // Hollow under the cheekbone, ear → toward the mouth, thinning out.
        polyStroke([93, 177], 1.0 * base, 0.9); polyStroke([177, 147], 0.8 * base, 0.8); polyStroke([147, 187], 0.5 * base, 0.55);
        // Jawline and forehead / temple edge (half of each stroke falls off the face, leaving an inner band).
        polyStroke([132, 58, 172, 136, 150, 149, 176], 0.7 * base, 0.8);
        polyStroke([127, 162, 21, 54, 103, 67, 109], 0.8 * base, 0.6);
        // Sides of the nose.
        polyStroke([193, 122, 196, 3], 0.5 * noseW, 0.5);
      });
      c.globalAlpha = 1;
    }, TUNING.contourFeatherPx);
    // 0 at the face outline, 1 a little inside: the mesh edge often sits on background or hair, and a
    // contour band painted there drew a pale outline around the face (LaPa 10-25).
    const FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152,
      148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109];
    const faceFill = layer(() => { c.fillStyle = '#fff'; c.beginPath(); pts(FACE_OVAL).forEach((q, i) => (i ? c.lineTo(q[0], q[1]) : c.moveTo(q[0], q[1]))); c.closePath(); c.fill(); }, TUNING.faceEdgeFadePx);
    const rgba2 = new Uint8Array(S * S * 4);
    for (let i = 0; i < S * S; i++) {
      const inside = clamp01((faceFill[i] - 0.5) * 2);
      rgba2[i * 4] = Math.round(clamp01(highlight[i] * inside) * 255);
      rgba2[i * 4 + 1] = Math.round(clamp01(contour[i] * inside) * 255);
      rgba2[i * 4 + 3] = 255;
    }
    const rgba = new Uint8Array(S * S * 4);
    for (let i = 0; i < S * S; i++) {
      // R: only the inner and corner fades (over the whole band); the screen-space outline cuts the
      // outer edge, so the UV spline's per-triangle warp never shows (10-25).
      rgba[i * 4] = Math.round(clamp01(band[i] > 0.01 ? lipFade[i] : 0) * 255);
      rgba[i * 4 + 1] = Math.round(clamp01(blush[i]) * 255);
      rgba[i * 4 + 2] = Math.round(clamp01(shadow[i]) * 255);
      rgba[i * 4 + 3] = Math.round(clamp01(band[i] * corner[i]) * 255);
    }
    const at = (arr, i) => arr[clamp(Math.round(FACE_UV[2 * i + 1] * S), 0, S - 1) * S + clamp(Math.round(FACE_UV[2 * i] * S), 0, S - 1)];
    const lipVerts = [], skinVerts = [];
    const excluded = new Set(BROWS.concat(EYES[0].contour, EYES[1].contour));
    for (let i = 0; i < N_MESH; i++) {
      if (at(lip, i) > 0.6) lipVerts.push(i);
      else if (at(lip, i) < 0.01 && at(shadow, i) < 0.01 && !excluded.has(i)) skinVerts.push(i);
    }
    return { size: S, rgba, rgba2, lipVerts, skinVerts };
  }

  // ── Mesh (positions, normals) ────────────────────────────────────────
  const meshPos = new Float32Array(N_MESH * 3);
  const meshNrm = new Float32Array(N_MESH * 3);
  const scr = new Float32Array(N_MESH * 3);
  // Inner-lip gap (13–14) relative to mouth width (61–291), in landmark space.
  function mouthClosed() {
    const gap = Math.hypot(sx[13] - sx[14], sy[13] - sy[14]);
    const width = Math.hypot(sx[61] - sx[291], sy[61] - sy[291]);
    return width > 1e-4 && gap / width < TUNING.mouthClosedGap;
  }
  // ── Lip thickness: edge widths will follow this person's lips, never an average (6-5-3) ──
  // Outer/inner lip point pairs at the left, centre and right of each lip.
  const LIP_THICK_PAIRS = {
    up: [[37, 82], [0, 13], [267, 312]],
    low: [[84, 87], [17, 14], [314, 317]],
  };
  const lipThick = { up: 0, low: 0, upRatio: 0, lowRatio: 0, upBase: 0, lowBase: 0, uvScale: 0 };
  function meanPairLen(pairs, fx, fy, fz) {
    let s = 0;
    for (const [a, b] of pairs) s += Math.hypot((sx[a] - sx[b]) * fx, (sy[a] - sy[b]) * fy, (sz[a] - sz[b]) * fz);
    return s / pairs.length;
  }
  function uvPairLen(pairs) {
    let s = 0;
    for (const [a, b] of pairs) {
      s += Math.hypot(FACE_UV[2 * a] - FACE_UV[2 * b], FACE_UV[2 * a + 1] - FACE_UV[2 * b + 1]) * TUNING.maskSize;
    }
    return s / pairs.length;
  }
  const UV_LIP_THICK = uvPairLen(LIP_THICK_PAIRS.up) + uvPairLen(LIP_THICK_PAIRS.low);
  function measureLipThickness(W, H) {
    // Screen px (what the edge width is compared with), and that over the 3D mouth width: distance-free,
    // and head yaw does not change it (MediaPipe z is in the same scale as x). Thickness itself stays 2D:
    // the inner lip points sit deeper than the outer ones, so a 3D length hides how thin the lips are.
    lipThick.up = meanPairLen(LIP_THICK_PAIRS.up, W, H, 0);
    lipThick.low = meanPairLen(LIP_THICK_PAIRS.low, W, H, 0);
    const width3d = Math.max(1e-4, Math.hypot((sx[61] - sx[291]) * W, (sy[61] - sy[291]) * H, (sz[61] - sz[291]) * W));
    lipThick.upRatio = lipThick.up / width3d;
    lipThick.lowRatio = lipThick.low / width3d;
    // Screen px per UV-mask px at the lips: how wide the baked edge feather and band really are.
    lipThick.uvScale = (lipThick.up + lipThick.low) / Math.max(1e-4, UV_LIP_THICK);
    // Baseline: closed mouth, roughly frontal (both corners at a similar depth). Smiling or opening
    // stretches the lips thinner, so only this pose defines the person's own thickness. Memory only.
    const frontal = Math.abs(sz[61] - sz[291]) * W < 0.15 * width3d;
    if (mouthClosed() && frontal) {
      const k = lipThick.upBase ? 0.1 : 1;
      lipThick.upBase += k * (lipThick.upRatio - lipThick.upBase);
      lipThick.lowBase += k * (lipThick.lowRatio - lipThick.lowBase);
    }
  }
  // Where the real lip ends, from the camera: walk from each inner lip point out past its outer
  // partner and find the last red-enough sample. 1.0 = the landmark outer line is on the real edge,
  // < 1 = the landmarks sit outside the lip (paint spills onto skin). Corners skipped. Memory only.
  // 60 rays: each outer/inner landmark segment j → j+1 (wrapping) split at 0, 1/3, 2/3, so the edge
  // between the 20 model points comes from the camera, not from the average face's curve.
  const LIP_RAYS = LIPS_OUTER.length * 3;
  const lipEdge = { up: 1, low: 1, samples: 0, t: new Float32Array(LIP_RAYS).fill(1), conf: new Float32Array(LIP_RAYS) };
  function rayEnds(r) {
    const j = Math.floor(r / 3), f = (r % 3) / 3, j2 = (j + 1) % LIPS_OUTER.length;
    const o1 = LIPS_OUTER[j], o2 = LIPS_OUTER[j2], n1 = LIPS_INNER[j], n2 = LIPS_INNER[j2];
    return [sx[n1] + f * (sx[n2] - sx[n1]), sy[n1] + f * (sy[n2] - sy[n1]),
            sx[o1] + f * (sx[o2] - sx[o1]), sy[o1] + f * (sy[o2] - sy[o1])];
  }
  const edgeCrop = document.createElement('canvas');
  const edgeCropCtx = edgeCrop.getContext('2d', { willReadFrequently: true });
  function measureLipEdge(W, H) {
    if (light.lipRed - light.skinRed < TUNING.refineMinContrast) return;
    let x0 = 1, y0 = 1, x1 = 0, y1 = 0;
    for (const i of LIPS_OUTER) { x0 = Math.min(x0, sx[i]); x1 = Math.max(x1, sx[i]); y0 = Math.min(y0, sy[i]); y1 = Math.max(y1, sy[i]); }
    const padY = 0.6 * (y1 - y0), padX = (padY * H) / W;
    x0 = clamp(x0 - padX, 0, 1); x1 = clamp(x1 + padX, 0, 1); y0 = clamp(y0 - padY, 0, 1); y1 = clamp(y1 + padY, 0, 1);
    const srcW = (x1 - x0) * W, srcH = (y1 - y0) * H;
    if (srcW < 8 || srcH < 8) return;
    const cw = Math.min(256, Math.round(srcW)), ch = Math.max(1, Math.round((cw * srcH) / srcW));
    if (edgeCrop.width !== cw || edgeCrop.height !== ch) { edgeCrop.width = cw; edgeCrop.height = ch; }
    edgeCropCtx.drawImage(video, x0 * W, y0 * H, srcW, srcH, 0, 0, cw, ch);
    const d = edgeCropCtx.getImageData(0, 0, cw, ch).data;
    // Redness and, for reflections, brightness and saturation of a 3×3 neighbourhood (linear RGB).
    const sampleAt = (nx, ny) => {
      const cx = Math.floor(((nx - x0) / (x1 - x0)) * cw), cy = Math.floor(((ny - y0) / (y1 - y0)) * ch);
      let r = 0, g = 0, b = 0;
      for (let oy = -1; oy <= 1; oy++) for (let ox = -1; ox <= 1; ox++) {
        const k = (clamp(cy + oy, 0, ch - 1) * cw + clamp(cx + ox, 0, cw - 1)) * 4;
        r += toLin(d[k] / 255); g += toLin(d[k + 1] / 255); b += toLin(d[k + 2] / 255);
      }
      const hi = Math.max(r, g, b);
      return { red: (r - g) / (r + g + b + 1e-4), lum: lumOf(r, g, b) / 9, sat: (hi - Math.min(r, g, b)) / Math.max(hi, 1e-4) };
    };
    const mid = light.skinRed + 0.5 * (light.lipRed - light.skinRed);
    // A reflection on the lip is white, not red: inside the landmark lip, a bright desaturated sample
    // continues the lip instead of ending it (skin, even pale skin, stays more saturated than this).
    const isReflection = (s) => s.sat < TUNING.hlSat[0] && s.lum > TUNING.diffuseCap * light.lipMeanLum;
    // One ray per LIP_RAYS entry: t = 0 inner line, 1 landmark outer line. Start past the wet inner
    // lip, stop on a sustained drop below the lip/skin midpoint.
    const found = new Float32Array(LIP_RAYS);
    for (let r = 0; r < LIP_RAYS; r++) {
      const ray = rayEnds(r);
      const step = 1.45 / 40;
      let last = -1, lastV = 0, edge = -1;
      for (let s = 0; s <= 40; s++) {
        const t = 0.15 + s * step;
        const smp = sampleAt(ray[0] + t * (ray[2] - ray[0]), ray[1] + t * (ray[3] - ray[1]));
        const v = t <= 1 && isReflection(smp) ? Math.max(smp.red, mid) : smp.red;
        if (v >= mid) { last = t; lastV = v; edge = -1; }
        else if (last >= 0) {
          // Sub-step: where the redness crosses the midpoint between the last lip and first skin sample.
          if (edge < 0 && t - last < step * 1.5) edge = last + step * clamp((lastV - mid) / Math.max(1e-4, lastV - v), 0, 1);
          if (t - last > 0.12) break;
        }
      }
      found[r] = last > 0 ? (edge > 0 ? edge : last) : -1;
    }
    // Outliers: a ray far from the median of its 4 neighbours (glare, teeth, beard) is skipped this time.
    const first = lipEdge.samples++ === 0;
    const k = first ? 1 : TUNING.lightSmoothing;
    for (let r = 0; r < LIP_RAYS; r++) {
      const near = [-2, -1, 1, 2].map((d) => found[(r + d + LIP_RAYS) % LIP_RAYS]).filter((v) => v > 0).sort((p, q) => p - q);
      const med = near.length ? near[near.length >> 1] : -1;
      const ok = found[r] > 0 && (med < 0 || Math.abs(found[r] - med) < TUNING.lipRayOutlier);
      if (ok) lipEdge.t[r] = first || lipEdge.conf[r] === 0 ? found[r] : lipEdge.t[r] + k * (found[r] - lipEdge.t[r]);
      lipEdge.conf[r] += k * ((ok ? 1 : 0) - lipEdge.conf[r]);
    }
    // Summary per lip, corners excluded: upper = segments 1..8, lower = 11..18.
    const pick = (a, b) => trimmedMean(Array.from({ length: (b - a + 1) * 3 }, (_, i) => a * 3 + i)
      .filter((r) => lipEdge.conf[r] > 0.5).map((r) => lipEdge.t[r]));
    const up = pick(1, 8), low = pick(11, 18);
    if (up !== null) lipEdge.up = up;
    if (low !== null) lipEdge.low = low;
  }
  // Lip outline in screen space, redrawn every frame from the smoothed landmarks: a curve through the
  // outer points with sharp mouth corners, minus the inner curve when the mouth is open. Drawn on the
  // screen it never bends at mesh triangle edges (10-25 close-ups: kinks, beak corners). White on an
  // opaque black crop; the shader reads it in video coordinates (suv). Memory only.
  // (A2, the camera-measured outline, was removed: on 200 LaPa faces it matched the lip worse than the
  // landmarks, IoU 0.703 vs 0.736, and on device it grew onto warm, reddish skin.)
  const outlineCanvas = document.createElement('canvas');
  const outlineCtx = outlineCanvas.getContext('2d');
  // Lip form field: the form channel drawn small and blurred by a share of the lip thickness, so the
  // shader reads a smooth round (a few-tap ring left contour stripes inside the lips).
  const formCanvas = document.createElement('canvas');
  const formCtx = formCanvas.getContext('2d', { willReadFrequently: true });
  let formImg = null;
  const formStep = [0, 0];
  function drawLipForm(srcW, srcH) {
    const fw = Math.max(8, Math.min(TUNING.formFieldPx, Math.ceil(outlineCanvas.width / 3)));
    const fh = Math.max(4, Math.round((fw * outlineCanvas.height) / outlineCanvas.width));
    if (formCanvas.width !== fw || formCanvas.height !== fh) { formCanvas.width = fw; formCanvas.height = fh; formImg = null; }
    formCtx.drawImage(outlineCanvas, 0, 0, fw, fh);
    const d = formCtx.getImageData(0, 0, fw, fh).data;
    const g = new Float32Array(fw * fh);
    for (let i = 0; i < fw * fh; i++) g[i] = d[i * 4 + 1] / 255;
    const thickPx = 0.5 * (lipThick.up + lipThick.low) * (fw / srcW);
    const r = Math.max(1, Math.round((TUNING.formReach * thickPx) / 2));
    const h = boxBlurRect(g, fw, fh, r);
    if (!formImg) formImg = formCtx.createImageData(fw, fh);
    const o = formImg.data;
    for (let i = 0; i < fw * fh; i++) { const v = Math.round(clamp01(h[i]) * 255); o[i * 4] = v; o[i * 4 + 1] = v; o[i * 4 + 2] = v; o[i * 4 + 3] = 255; }
    formCtx.putImageData(formImg, 0, 0);
    // One field texel in video coordinates, and how far (texels) the field rises from 0 to 1.
    formStep[0] = srcW / fw; formStep[1] = 2 * r + 1;
  }
  const outlineRect = [0, 0, 1, 1];
  // Ring positions that stay put while smoothing: mouth corners (both rings) and the Cupid's bow (outer).
  const OUTER_FIXED = [0, 4, 5, 6, 10];
  const INNER_FIXED = [0, 10];
  // inset: move each point this share of the way from its partner ring, away from it (inner ring →
  // into the mouth).
  function lipRing(ids, fixed, W, H, partner, inset) {
    let p = ids.map((i, j) => {
      const k = partner ? inset : 0, q = partner ? partner[j] : i;
      return [(sx[i] + k * (sx[i] - sx[q])) * W, (sy[i] + k * (sy[i] - sy[q])) * H];
    });
    const n = p.length, k = TUNING.lipOutlineSmooth;
    // Taubin λ|μ: removes landmark zigzag without shrinking the lip.
    for (const w of [k, -1.06 * k]) {
      p = p.map((q, i) => {
        if (fixed.includes(i)) return q;
        const a = p[(i - 1 + n) % n], b = p[(i + 1) % n];
        return [q[0] + w * ((a[0] + b[0]) / 2 - q[0]), q[1] + w * ((a[1] + b[1]) / 2 - q[1])];
      });
    }
    return p;
  }
  // Cubic curve through the ring; at corner points (index 0 and 10) the tangent is 0, so they stay sharp.
  function ringPath(c, p, map) {
    const n = p.length;
    const tan = (i) => {
      if (i % 10 === 0) return [0, 0];
      const a = p[(i - 1 + n) % n], b = p[(i + 1) % n];
      return [(b[0] - a[0]) / 6, (b[1] - a[1]) / 6];
    };
    const q0 = map(p[0]);
    c.moveTo(q0[0], q0[1]);
    for (let i = 0; i < n; i++) {
      const j = (i + 1) % n, ti = tan(i), tj = tan(j);
      const c1 = map([p[i][0] + ti[0], p[i][1] + ti[1]]), c2 = map([p[j][0] - tj[0], p[j][1] - tj[1]]), e = map(p[j]);
      c.bezierCurveTo(c1[0], c1[1], c2[0], c2[1], e[0], e[1]);
    }
    c.closePath();
  }
  function drawLipOutline(W, H) {
    const outer = lipRing(LIPS_OUTER, OUTER_FIXED, W, H);
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const q of outer) { x0 = Math.min(x0, q[0]); x1 = Math.max(x1, q[0]); y0 = Math.min(y0, q[1]); y1 = Math.max(y1, q[1]); }
    const pad = 0.08 * (x1 - x0) + 4;
    x0 -= pad; x1 += pad; y0 -= pad; y1 += pad;
    const srcW = x1 - x0, srcH = y1 - y0;
    if (srcW < 8 || srcH < 4) return false;
    const cw = Math.min(TUNING.lipOutlinePx, Math.ceil(srcW)), ch = Math.max(4, Math.ceil((cw * srcH) / srcW));
    if (outlineCanvas.width !== cw || outlineCanvas.height !== ch) { outlineCanvas.width = cw; outlineCanvas.height = ch; }
    const map = (q) => [((q[0] - x0) / srcW) * cw, ((q[1] - y0) / srcH) * ch];
    // R = where to paint, G = lip form (upper and lower lip as separate bodies).
    const c = outlineCtx;
    c.fillStyle = '#000';
    c.fillRect(0, 0, cw, ch);
    c.fillStyle = '#ff0';
    c.beginPath(); ringPath(c, outer, map); c.fill();
    // The landmark inner line sits short of the wet inner lip on open mouths: 13% of the real lip
    // (LaPa, 1,132 open mouths) lay inside it, unpainted. Best shift by openness (gap / width):
    // < 0.2 → 0.15 (IoU 0.698 → 0.717), 0.2–0.5 → 0.15–0.2 (0.647 → 0.683), wider → 0.2 (n = 25).
    // Rendered on 200 phone-size faces, 0.15 on slightly open mouths painted teeth (IoU 0.624 → 0.615):
    // start small and grow with the opening.
    const open = Math.hypot(sx[13] - sx[14], sy[13] - sy[14]) / Math.max(1e-4, Math.hypot(sx[61] - sx[291], sy[61] - sy[291]));
    const s = clamp((open - 0.1) / 0.4, 0, 1);
    const inset = TUNING.innerInset[0] + (TUNING.innerInset[1] - TUNING.innerInset[0]) * s * s * (3 - 2 * s);
    const inner = lipRing(LIPS_INNER, INNER_FIXED, W, H, LIPS_OUTER, mouthClosed() ? 0 : inset);
    if (!mouthClosed()) {
      // Open mouth: the inner curve is a hole (teeth, tongue) in both.
      c.fillStyle = '#000';
      c.beginPath(); ringPath(c, inner, map); c.fill();
    } else {
      // Closed: the thin gap is painted, but the form splits there so each lip keeps its own round.
      c.strokeStyle = '#f00';
      c.lineWidth = Math.max(1, TUNING.seamPx * 0.5 * (lipThick.up + lipThick.low) * (cw / srcW));
      c.lineJoin = 'round';
      c.beginPath(); ringPath(c, inner, map); c.stroke();
    }
    outlineRect[0] = x0 / W; outlineRect[1] = y0 / H; outlineRect[2] = srcW / W; outlineRect[3] = srcH / H;
    if (TUNING.lipForm) drawLipForm(srcW, srcH);
    return true;
  }
  // ── Eyeliner and mascara: screen-space eye canvas (R = liner, G = mascara), redrawn each frame ──
  // Upper lid outer → inner corner, lower lid outer → inner, and the brow (which side is "up").
  const EYE_LINES = [
    { upper: [33, 246, 161, 160, 159, 158, 157, 173, 133], lower: [33, 7, 163, 144, 145, 153, 154, 155, 133], brow: [70, 63, 105, 66, 107], center: 159 },
    { upper: [263, 466, 388, 387, 386, 385, 384, 398, 362], lower: [263, 249, 390, 373, 374, 380, 381, 382, 362], brow: [300, 293, 334, 296, 336], center: 386 },
  ];
  // The mesh has holes for the eyes; these fans cover them so lashes can overhang the eye opening.
  const EYE_HOLE_TRIANGLES = [];
  for (const e of EYES) for (let j = 1; j < e.contour.length - 1; j++) EYE_HOLE_TRIANGLES.push(e.contour[0], e.contour[j], e.contour[j + 1]);
  const eyeCanvas = document.createElement('canvas');
  const eyeCtx = eyeCanvas.getContext('2d');
  const eyeRect = [0, 0, 1, 1];
  // Deterministic per-strand jitter: the same lash keeps its length and angle every frame.
  function seeded(i) { const x = Math.sin(i * 12.9898 + 4.1) * 43758.5453; return x - Math.floor(x); }
  function drawEyes(W, H, liner, mascara) {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const e of EYE_LINES) for (const i of e.upper.concat(e.lower, e.brow)) {
      x0 = Math.min(x0, sx[i] * W); x1 = Math.max(x1, sx[i] * W); y0 = Math.min(y0, sy[i] * H); y1 = Math.max(y1, sy[i] * H);
    }
    const pad = 0.12 * (x1 - x0);
    x0 -= pad; x1 += pad; y0 -= pad; y1 += pad;
    const srcW = x1 - x0, srcH = y1 - y0;
    if (srcW < 16 || srcH < 8) return false;
    const cw = Math.min(TUNING.eyeCanvasPx, Math.ceil(srcW)), ch = Math.max(4, Math.ceil((cw * srcH) / srcW));
    if (eyeCanvas.width !== cw || eyeCanvas.height !== ch) { eyeCanvas.width = cw; eyeCanvas.height = ch; }
    const k = cw / srcW;
    const map = (q) => [(q[0] - x0) * k, (q[1] - y0) * k];
    const path = (pts) => { eyeCtx.beginPath(); pts.map(map).forEach((q, i) => (i ? eyeCtx.lineTo(q[0], q[1]) : eyeCtx.moveTo(q[0], q[1]))); };
    const c = eyeCtx;
    c.globalCompositeOperation = 'source-over'; c.globalAlpha = 1;
    c.fillStyle = '#000'; c.fillRect(0, 0, cw, ch);
    c.globalCompositeOperation = 'lighter';
    const P = (i) => [sx[i] * W, sy[i] * H];
    for (const e of EYE_LINES) {
      const up = e.upper.map(P), low = e.lower.map(P);
      const outer = up[0], inner = up[up.length - 1];
      const eyeW = dist(outer, inner);
      if (eyeW < 4) continue;
      const axis = [(outer[0] - inner[0]) / eyeW, (outer[1] - inner[1]) / eyeW];
      // "Up" = perpendicular to the corner-to-corner axis, on the brow side (stable through a blink).
      const brow = centroid(e.brow.map(P)), mid = lerp(outer, inner, 0.5);
      let nUp = [-axis[1], axis[0]];
      if (nUp[0] * (brow[0] - mid[0]) + nUp[1] * (brow[1] - mid[1]) < 0) nUp = [-nUp[0], -nUp[1]];
      // The far eye of a turned head is foreshortened; fade both with the eye's facing.
      const fade = clamp((meshNrm[e.center * 3 + 2] - 0.15) / 0.35, 0, 1);
      if (fade <= 0) continue;
      c.globalAlpha = fade;
      if (liner) {
        const g = Object.assign({}, TUNING.liner, liner.geometry || {});
        const n = up.length, thickOuter = g.thickness * eyeW;
        const top = [], bottom = [];
        for (let j = 0; j < n; j++) {
          const t = 1 - j / (n - 1); // 1 at the outer corner
          const th = thickOuter * (TUNING.linerInnerThin + (1 - TUNING.linerInnerThin) * Math.pow(t, 1.3));
          const a = up[Math.max(0, j - 1)], b = up[Math.min(n - 1, j + 1)];
          let nl = [-(b[1] - a[1]), b[0] - a[0]];
          const ln = Math.hypot(nl[0], nl[1]) || 1;
          nl = [nl[0] / ln, nl[1] / ln];
          if (nl[0] * nUp[0] + nl[1] * nUp[1] < 0) nl = [-nl[0], -nl[1]];
          // Mostly the lid's own normal, steadied toward "up" (the lid line kinks while blinking).
          const d = [0.6 * nl[0] + 0.4 * nUp[0], 0.6 * nl[1] + 0.4 * nUp[1]];
          const dl = Math.hypot(d[0], d[1]) || 1;
          top.push([up[j][0] + (d[0] / dl) * th, up[j][1] + (d[1] / dl) * th]);
          bottom.push([up[j][0] - (d[0] / dl) * 0.15 * th, up[j][1] - (d[1] / dl) * 0.15 * th]);
        }
        // Wing: from the outer corner along the eye axis, lifted by the angle toward the brow.
        const ang = (g.angle * Math.PI) / 180, len = g.length * eyeW;
        const wdir = [axis[0] * Math.cos(ang) + nUp[0] * Math.sin(ang), axis[1] * Math.cos(ang) + nUp[1] * Math.sin(ang)];
        const tip = [outer[0] + wdir[0] * len, outer[1] + wdir[1] * len];
        c.fillStyle = '#f00';
        path(bottom.slice().reverse().concat(len > 0.5 ? [tip] : [], top));
        c.closePath(); c.fill();
      }
      if (mascara) {
        const lengthen = 0.75 + 0.5 * clamp01(mascara.intensity);
        c.strokeStyle = '#0f0'; c.lineCap = 'round'; c.lineJoin = 'round';
        // Open eye: lashes rise from the margin and curl up. Closed: they hang down over the lid.
        const gap = dist(lerp(up[3], up[5], 0.5), lerp(low[3], low[5], 0.5)) / eyeW;
        const openness = clamp((gap - 0.06) / 0.18, 0, 1);
        const lashUp = [nUp[0] * (2 * openness - 1), nUp[1] * (2 * openness - 1)];
        const lashUpLen = Math.hypot(lashUp[0], lashUp[1]) || 1;
        const lu = Math.abs(2 * openness - 1) < 0.2 ? [-nUp[0], -nUp[1]] : [lashUp[0] / lashUpLen, lashUp[1] / lashUpLen];
        // A strand: thick root half, thin tip (mascara coats the base), with the tip pulled toward
        // its clump. Front view foreshortens lashes, so they read short.
        const strand = (root, dir, curl, L, w, pull) => {
          const mid = [root[0] + dir[0] * 0.5 * L, root[1] + dir[1] * 0.5 * L];
          const end = [root[0] + dir[0] * L + curl[0] * 0.35 * L + pull[0], root[1] + dir[1] * L + curl[1] * 0.35 * L + pull[1]];
          const r = map(root), m = map(mid), e2 = map(end), cc = map(lerp(mid, end, 0.3));
          c.lineWidth = Math.max(0.8, w * k);
          c.beginPath(); c.moveTo(r[0], r[1]); c.lineTo(m[0], m[1]); c.stroke();
          c.lineWidth = Math.max(0.5, 0.45 * w * k);
          c.beginPath(); c.moveTo(m[0], m[1]); c.quadraticCurveTo(cc[0], cc[1], e2[0], e2[1]); c.stroke();
        };
        const along = (pts, u) => {
          const f = u * (pts.length - 1), j = Math.min(pts.length - 2, Math.floor(f));
          return lerp(pts[j], pts[j + 1], f - j);
        };
        // Upper lashes inner (u = 0) → outer corner (u = 1): uneven spacing, fanning outward,
        // longest past the middle, tips gathered in clumps of about three.
        const upIn = up.slice().reverse(), lowIn = low.slice().reverse();
        const nUpper = TUNING.lashCount;
        const tips = [];
        for (let i = 0; i < nUpper; i++) {
          const u = clamp(0.06 + (0.94 * (i + 0.6 * (seeded(i + 300) - 0.5))) / (nUpper - 1), 0.04, 1);
          const th = ((u - 0.35) * 50 * Math.PI) / 180 + (seeded(i) - 0.5) * 0.3;
          const dir = [lu[0] * Math.cos(th) + axis[0] * Math.sin(th), lu[1] * Math.cos(th) + axis[1] * Math.sin(th)];
          const L = eyeW * TUNING.lashLength * lengthen * (0.5 + 0.5 * Math.sin(Math.PI * Math.min(1, u * 1.15))) * (0.8 + 0.4 * seeded(i + 100));
          tips.push({ root: along(upIn, u), dir, L });
        }
        for (let i = 0; i < nUpper; i++) {
          const g = Math.floor(i / 3) * 3, gEnd = Math.min(nUpper, g + 3);
          let cx = 0, cy = 0;
          for (let j = g; j < gEnd; j++) { cx += tips[j].root[0] + tips[j].dir[0] * tips[j].L; cy += tips[j].root[1] + tips[j].dir[1] * tips[j].L; }
          cx /= gEnd - g; cy /= gEnd - g;
          const t0 = tips[i], own = [t0.root[0] + t0.dir[0] * t0.L, t0.root[1] + t0.dir[1] * t0.L];
          const pull = [(cx - own[0]) * 0.5 * clamp01(mascara.intensity), (cy - own[1]) * 0.5 * clamp01(mascara.intensity)];
          strand(t0.root, t0.dir, lu, t0.L, eyeW * TUNING.lashWidth, pull);
        }
        // Lower lashes: few, short, faint, pointing down (only when the eye is open).
        c.globalAlpha = fade * 0.5 * openness;
        const nLow = Math.round(TUNING.lashCount / 3);
        for (let i = 0; i < nLow && openness > 0; i++) {
          const u = 0.3 + (0.65 * (i + 0.5 * (seeded(i + 400) - 0.5))) / (nLow - 1);
          const th = ((u - 0.4) * 40 * Math.PI) / 180;
          const dir = [-nUp[0] * Math.cos(th) + axis[0] * Math.sin(th), -nUp[1] * Math.cos(th) + axis[1] * Math.sin(th)];
          const L = eyeW * TUNING.lashLength * TUNING.lowerLash * lengthen * (0.7 + 0.3 * seeded(i + 200));
          strand(along(lowIn, u), dir, [-nUp[0], -nUp[1]], L, 0.7 * eyeW * TUNING.lashWidth, [0, 0]);
        }
        // Lash line: the coated roots darken and thicken the upper lid margin (the most visible
        // mascara change at selfie distance).
        c.globalAlpha = fade;
        c.lineWidth = Math.max(1, 0.035 * eyeW * k);
        path(up.slice(0, -1)); c.stroke();
      }
    }
    c.globalAlpha = 1; c.globalCompositeOperation = 'source-over';
    eyeRect[0] = x0 / W; eyeRect[1] = y0 / H; eyeRect[2] = srcW / W; eyeRect[3] = srcH / H;
    return true;
  }
  const mouthN = [0, 0, 1];
  function updateMesh(W, H) {
    for (let i = 0; i < N_MESH; i++) {
      // Clip space of the mirrored display; MediaPipe z: smaller = closer, so depth LESS keeps the near surface.
      meshPos[i * 3] = 1 - 2 * sx[i];
      meshPos[i * 3 + 1] = 1 - 2 * sy[i];
      meshPos[i * 3 + 2] = clamp(sz[i], -0.99, 0.99);
      // Shading frame: x right on the (mirrored) screen, y up, z toward the viewer, in pixels.
      scr[i * 3] = -sx[i] * W;
      scr[i * 3 + 1] = -sy[i] * H;
      scr[i * 3 + 2] = -sz[i] * W;
    }
    meshNrm.fill(0);
    for (let t = 0; t < FACE_TRIANGLES.length; t += 3) {
      const a = FACE_TRIANGLES[t] * 3, b = FACE_TRIANGLES[t + 1] * 3, c = FACE_TRIANGLES[t + 2] * 3;
      const ux = scr[b] - scr[a], uy = scr[b + 1] - scr[a + 1], uz = scr[b + 2] - scr[a + 2];
      const vx = scr[c] - scr[a], vy = scr[c + 1] - scr[a + 1], vz = scr[c + 2] - scr[a + 2];
      const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
      for (const k of [a, b, c]) { meshNrm[k] += nx; meshNrm[k + 1] += ny; meshNrm[k + 2] += nz; }
    }
    let zSum = 0;
    for (let i = 0; i < N_MESH; i++) zSum += meshNrm[i * 3 + 2];
    const sign = zSum < 0 ? -1 : 1;
    for (let i = 0; i < N_MESH; i++) {
      const k = i * 3;
      const len = Math.hypot(meshNrm[k], meshNrm[k + 1], meshNrm[k + 2]) || 1;
      meshNrm[k] = (sign * meshNrm[k]) / len;
      meshNrm[k + 1] = (sign * meshNrm[k + 1]) / len;
      meshNrm[k + 2] = (sign * meshNrm[k + 2]) / len;
    }
    // Mouth orientation: mean normal of the lip rings (upper lip faces down, lower up; the mean is the mouth).
    let mx = 0, my = 0, mz = 0;
    for (const i of LIPS_OUTER.concat(LIPS_INNER)) { mx += meshNrm[i * 3]; my += meshNrm[i * 3 + 1]; mz += meshNrm[i * 3 + 2]; }
    const ml = Math.hypot(mx, my, mz) || 1;
    mouthN[0] = mx / ml; mouthN[1] = my / ml; mouthN[2] = mz / ml;
  }

  // ── Scene / light estimation every 0.5 s (AR_SPEC 6-6-1) ─────────────
  const grainCanvas = document.createElement('canvas');
  grainCanvas.width = 24; grainCanvas.height = 24;
  const grainCtx = grainCanvas.getContext('2d', { willReadFrequently: true });
  // Camera grain: std of the 3×3 high-pass of linear luminance on a cheek patch, relative to its mean.
  // Camera blur: how far that noise spreads, from the lag-1 correlation of the residual from a 5×5 mean
  // (≈ 0 for sharp per-pixel noise, about (w - 1) / w for noise smeared over w px by focus or compression).
  function measureCamera(W, H) {
    const cheek = meshNrm[50 * 3 + 2] >= meshNrm[280 * 3 + 2] ? 50 : 280;
    const N = 24;
    const x0 = clamp(Math.round(sx[cheek] * W) - N / 2, 0, W - N), y0 = clamp(Math.round(sy[cheek] * H) - N / 2, 0, H - N);
    grainCtx.drawImage(video, x0, y0, N, N, 0, 0, N, N);
    const d = grainCtx.getImageData(0, 0, N, N).data;
    const L = new Float32Array(N * N);
    for (let i = 0; i < N * N; i++) L[i] = lumOf(toLin(d[i * 4] / 255), toLin(d[i * 4 + 1] / 255), toLin(d[i * 4 + 2] / 255));
    let sum = 0, sq = 0, mean = 0, n = 0;
    for (let y = 1; y < N - 1; y++) {
      for (let x = 1; x < N - 1; x++) {
        let m = 0;
        for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) m += L[(y + dy) * N + x + dx];
        const hp = L[y * N + x] - m / 9;
        sum += hp; sq += hp * hp; mean += L[y * N + x]; n++;
      }
    }
    const sd = Math.sqrt(Math.max(0, sq / n - (sum / n) * (sum / n)));
    const R = new Float32Array(N * N);
    for (let y = 2; y < N - 2; y++) {
      for (let x = 2; x < N - 2; x++) {
        let m = 0;
        for (let dy = -2; dy <= 2; dy++) for (let dx = -2; dx <= 2; dx++) m += L[(y + dy) * N + x + dx];
        R[y * N + x] = L[y * N + x] - m / 25;
      }
    }
    let rr = 0, rl = 0;
    for (let y = 2; y < N - 3; y++) {
      for (let x = 2; x < N - 3; x++) {
        const r = R[y * N + x];
        rr += r * r;
        rl += r * (R[y * N + x + 1] + R[(y + 1) * N + x]) / 2;
      }
    }
    const rho = rr > 1e-12 ? clamp(rl / rr, 0, 0.95) : 0;
    return {
      grain: clamp(sd / Math.max(1e-3, mean / n), 0, TUNING.grainMax),
      blur: clamp(1 / (1 - rho), 1, TUNING.blurMax),
    };
  }
  const stats = document.createElement('canvas');
  const statsCtx = stats.getContext('2d', { willReadFrequently: true });
  const light = {
    color: [1, 1, 1], colorConf: 0, dir: [0, 0.3, 0.95], strength: 1, dirConf: 0,
    lipMeanLum: 0.12, skinMeanLum: TUNING.skinRefLum, bgFraction: 0, samples: 0,
    lipRed: 0.2, skinRed: 0.2, grain: 0, blur: 1, lipColor: [0.12, 0.06, 0.06], lipUpLow: 1,
  };
  let masks = null;
  let lastLightAt = 0;
  let lastSegmentAt = -1e9;

  function trimmedMean(values) {
    if (!values.length) return null;
    values.sort((p, q) => p - q);
    const lo = Math.floor(values.length * 0.25), hi = Math.max(lo + 1, Math.ceil(values.length * 0.75));
    let s = 0;
    for (let i = lo; i < hi; i++) s += values[i];
    return s / (hi - lo);
  }
  function solve4(A, b) {
    const M = A.map((row, i) => row.concat([b[i]]));
    for (let col = 0; col < 4; col++) {
      let piv = col;
      for (let r = col + 1; r < 4; r++) if (Math.abs(M[r][col]) > Math.abs(M[piv][col])) piv = r;
      if (Math.abs(M[piv][col]) < 1e-9) return null;
      const tmp = M[col]; M[col] = M[piv]; M[piv] = tmp;
      for (let r = 0; r < 4; r++) {
        if (r === col) continue;
        const f = M[r][col] / M[col][col];
        for (let k = col; k < 5; k++) M[r][k] -= f * M[col][k];
      }
    }
    return M.map((row, i) => row[4] / row[i]);
  }
  function fitLight(samples) {
    const A = [[0,0,0,0],[0,0,0,0],[0,0,0,0],[0,0,0,0]], b = [0,0,0,0];
    for (const s of samples) {
      const f = [1, s[0], s[1], s[2]];
      for (let i = 0; i < 4; i++) { b[i] += f[i] * s[3]; for (let j = 0; j < 4; j++) A[i][j] += f[i] * f[j]; }
    }
    return solve4(A, b);
  }
  function sampleScene(now, W, H) {
    const sw = 128, sh = Math.max(1, Math.round((128 * H) / W));
    if (stats.width !== sw || stats.height !== sh) { stats.width = sw; stats.height = sh; }
    statsCtx.drawImage(video, 0, 0, sw, sh);
    const data = statsCtx.getImageData(0, 0, sw, sh).data;
    const linAt = (nx, ny) => {
      const x = clamp(Math.round(nx * sw), 0, sw - 1), y = clamp(Math.round(ny * sh), 0, sh - 1);
      const k = (y * sw + x) * 4;
      return [toLin(data[k] / 255), toLin(data[k + 1] / 255), toLin(data[k + 2] / 255)];
    };
    const lumAt = (nx, ny) => { const c = linAt(nx, ny); return lumOf(c[0], c[1], c[2]); };
    // Same redness measure as the shader: (r - g) / (r + g + b) in linear RGB.
    const redAt = (nx, ny) => { const c = linAt(nx, ny); return (c[0] - c[1]) / (c[0] + c[1] + c[2] + 1e-4); };
    // First sample is taken as-is so the defaults never show (e.g. over-bright lip highlights at start).
    const k = light.samples++ === 0 ? 1 : TUNING.lightSmoothing;

    // Lip body samples: lerp outer→inner lip line, skip mouth corners (indices 0 and 10).
    // Mesh vertices inside the lip mask can hit the open mouth or a highlight and flatten shading.
    const lipBody = [];
    for (let i = 0; i < LIPS_OUTER.length; i++) {
      if (i === 0 || i === 10) continue;
      const ox = sx[LIPS_OUTER[i]], oy = sy[LIPS_OUTER[i]];
      const ix = sx[LIPS_INNER[i]], iy = sy[LIPS_INNER[i]];
      for (const t of [1 / 3, 0.5, 2 / 3]) lipBody.push([ox + t * (ix - ox), oy + t * (iy - oy)]);
    }
    const lipLum = trimmedMean(lipBody.map((p) => lumAt(p[0], p[1])));
    // Upper lip = outer/inner indices 1..9, lower = 11..19 (3 samples each, corners skipped).
    const upperLum = trimmedMean(lipBody.slice(0, 27).map((p) => lumAt(p[0], p[1])));
    const lowerLum = trimmedMean(lipBody.slice(27).map((p) => lumAt(p[0], p[1])));
    if (upperLum && lowerLum) light.lipUpLow += k * (upperLum / lowerLum - light.lipUpLow);
    // Close-ups cut the face off: a vertex outside the frame would read the edge pixel and skew the
    // light (10-25: highlights on the lower rim of the lower lip, "light from below").
    const inFrame = (i) => sx[i] > 0.01 && sx[i] < 0.99 && sy[i] > 0.01 && sy[i] < 0.99;
    const skinIn = masks.skinVerts.filter((i) => meshNrm[i * 3 + 2] >= 0.35 && inFrame(i));
    const samples = [];
    for (const i of skinIn) {
      samples.push([meshNrm[i * 3], meshNrm[i * 3 + 1], meshNrm[i * 3 + 2], lumAt(sx[i], sy[i])]);
    }
    const skinLum = trimmedMean(samples.map((s) => s[3]));
    if (lipLum) light.lipMeanLum += k * (lipLum - light.lipMeanLum);
    try {
      const cam = measureCamera(W, H);
      light.grain += k * (cam.grain - light.grain);
      light.blur += k * (cam.blur - light.blur);
    } catch (e) { /* grain and blur are best-effort */ }
    // Bare-lip color as the camera sees it (linear RGB): the layer below the virtual lipstick.
    const lipCols = lipBody.map((p) => linAt(p[0], p[1]));
    const lipColor = [0, 1, 2].map((j) => trimmedMean(lipCols.map((c) => c[j])));
    if (lipColor.every((v) => v !== null)) {
      for (let j = 0; j < 3; j++) light.lipColor[j] += k * (lipColor[j] - light.lipColor[j]);
    }
    const lipRed = trimmedMean(lipBody.map((p) => redAt(p[0], p[1])));
    const skinRed = trimmedMean(skinIn.map((i) => redAt(sx[i], sy[i])));
    if (lipRed !== null) light.lipRed += k * (lipRed - light.lipRed);
    if (skinRed !== null) light.skinRed += k * (skinRed - light.skinRed);
    if (skinLum) light.skinMeanLum += k * (skinLum - light.skinMeanLum);

    // Direction and strength only (skin color is not used): brightness ≈ a + b·n, refit without outliers.
    if (samples.length >= 30) {
      let fit = fitLight(samples);
      if (fit) {
        const resid = samples.map((s) => Math.abs(s[3] - (fit[0] + fit[1] * s[0] + fit[2] * s[1] + fit[3] * s[2])));
        const cut = resid.slice().sort((p, q) => p - q)[Math.floor(resid.length * 0.8)];
        const kept = samples.filter((_, i) => resid[i] <= cut);
        fit = fitLight(kept) || fit;
        let ssRes = 0, ssTot = 0;
        const mean = kept.reduce((s, v) => s + v[3], 0) / kept.length;
        for (const s of kept) {
          const pred = fit[0] + fit[1] * s[0] + fit[2] * s[1] + fit[3] * s[2];
          ssRes += (s[3] - pred) * (s[3] - pred);
          ssTot += (s[3] - mean) * (s[3] - mean);
        }
        const r2 = ssTot > 1e-9 ? 1 - ssRes / ssTot : 0;
        let dx = fit[1], dy = fit[2], dz = Math.max(fit[3], 0);
        const mag = Math.hypot(dx, dy, dz);
        if (mag > 1e-6) {
          dx /= mag; dy /= mag; dz /= mag;
          if (dz < 0.15) { dz = 0.15; const m2 = Math.hypot(dx, dy, dz); dx /= m2; dy /= m2; dz /= m2; }
          light.dir = [0, 1, 2].map((j) => light.dir[j] + k * ([dx, dy, dz][j] - light.dir[j]));
          const dl = Math.hypot(light.dir[0], light.dir[1], light.dir[2]) || 1;
          light.dir = light.dir.map((v) => v / dl);
        }
        const conf = clamp((r2 - TUNING.lightConfR2[0]) / (TUNING.lightConfR2[1] - TUNING.lightConfR2[0]), 0, 1);
        light.dirConf += k * (conf - light.dirConf);
        const strength = clamp((fit[0] + mag) / TUNING.skinRefLum, 0.3, 1.5);
        light.strength += k * (strength - light.strength);
      }
    }

    // Color: Gray World over background pixels (segmenter class 0), blown-out and dark pixels excluded.
    if (segmenter && now - lastSegmentAt > TUNING.segmentEveryMs && (lastSegmentAt < 0 || fps >= TUNING.segmentMinFps)) {
      lastSegmentAt = now;
      try {
        segmenter.segmentForVideo(video, now, (result) => {
          const mask = result.categoryMask;
          if (!mask) return;
          const mw = mask.width, mh = mask.height, cat = mask.getAsUint8Array();
          let r = 0, g = 0, bl = 0, n = 0;
          for (let y = 0; y < sh; y++) {
            for (let x = 0; x < sw; x++) {
              if (cat[Math.floor((y * mh) / sh) * mw + Math.floor((x * mw) / sw)] !== 0) continue;
              const q = (y * sw + x) * 4;
              const R = toLin(data[q] / 255), G = toLin(data[q + 1] / 255), B = toLin(data[q + 2] / 255);
              if (Math.max(R, G, B) > TUNING.clipLin || lumOf(R, G, B) < TUNING.darkLum) continue;
              r += R; g += G; bl += B; n++;
            }
          }
          light.bgFraction = n / (sw * sh);
          const Y = lumOf(r, g, bl);
          if (n > 0 && Y > 0) {
            const lo = TUNING.lightColorClamp[0], hi = TUNING.lightColorClamp[1];
            const c = [clamp(r / Y, lo, hi), clamp(g / Y, lo, hi), clamp(bl / Y, lo, hi)];
            const cy = lumOf(c[0], c[1], c[2]);
            for (let j = 0; j < 3; j++) light.color[j] += k * (c[j] / cy - light.color[j]);
            const chroma = Math.max(r, g, bl) / Math.max(1e-6, Math.min(r, g, bl));
            const ok = light.bgFraction >= TUNING.bgMinFraction && chroma <= TUNING.bgMaxChroma ? 1 : 0;
            light.colorConf += k * (ok - light.colorConf);
          }
        });
      } catch (e) { /* segmentation is best-effort */ }
    }
  }

  // ── WebGL renderer ───────────────────────────────────────────────────
  const PRECISION = [
    '#ifdef GL_FRAGMENT_PRECISION_HIGH',
    'precision highp float;',
    '#else',
    'precision mediump float;',
    '#endif',
  ].join(NL);

  const BG_VERT = [
    'attribute vec2 aPos;',
    'varying vec2 vUv;',
    'void main() { vUv = vec2(0.5 - aPos.x * 0.5, 0.5 - aPos.y * 0.5); gl_Position = vec4(aPos, 0.0, 1.0); }',
  ].join(NL);
  const BG_FRAG = [
    PRECISION,
    'varying vec2 vUv;',
    'uniform sampler2D uVideo;',
    'void main() { gl_FragColor = vec4(texture2D(uVideo, vUv).rgb, 1.0); }',
  ].join(NL);

  const MESH_VERT = [
    'attribute vec3 aPos; attribute vec2 aUv; attribute vec3 aNormal;',
    'varying vec2 vUv; varying vec3 vNormal;',
    'void main() { vUv = aUv; vNormal = aNormal; gl_Position = vec4(aPos, 1.0); }',
  ].join(NL);
  const MESH_FRAG = [
    PRECISION,
    'varying vec2 vUv; varying vec3 vNormal;',
    'uniform sampler2D uVideo; uniform sampler2D uMask; uniform vec2 uViewport;',
    'uniform vec3 uLightColor; uniform vec3 uLightDir; uniform float uLightStrength; uniform float uLightConf; uniform float uExposure;',
    'uniform float uLipMeanLum; uniform float uSkinMeanLum;',
    'uniform vec3 uLipAlbedo; uniform float uLipCov; uniform float uLipRough; uniform float uLipSpec; uniform float uLipFlake; uniform float uLipOn;',
    'uniform vec3 uBlushAlbedo; uniform float uBlushCov;',
    'uniform vec3 uShadowAlbedo; uniform float uShadowCov; uniform float uShadowFlake;',
    'uniform sampler2D uMask2; uniform vec3 uHlAlbedo; uniform float uHlCov; uniform float uHlFlake; uniform vec3 uContourAlbedo; uniform float uContourCov;',
    'uniform vec3 uFaceRough; uniform float uFaceSheen; uniform float uEyeHole; uniform float uPowderTint;',
    'uniform sampler2D uEye; uniform vec4 uEyeRect; uniform vec3 uLinerAlbedo; uniform float uLinerCov; uniform float uLinerGloss; uniform vec3 uMascaraAlbedo; uniform float uMascaraCov; uniform float uEyeSoft;',
    'uniform float uSpecMax; uniform float uFlakeDensity;',
    'uniform vec2 uTexel; uniform float uLipRed; uniform float uSkinRed; uniform float uRefine;',
    'uniform float uLipDetailGain; uniform float uLipGlint; uniform float uGlintThreshold;',
    'uniform float uDiffuseCap; uniform float uSkinRef;',
    'uniform float uSpecFill; uniform vec3 uLipColor; uniform float uPaperWhite; uniform float uRatioMax;',
    'uniform float uLipSpecMax; uniform vec2 uHlKeep;',
    'uniform float uLumGainMax; uniform float uCreaseCover;',
    'uniform float uLipTranslucent; uniform float uMaskBias; uniform float uLipSheen;',
    'uniform sampler2D uOutline; uniform vec4 uOutlineRect; uniform float uOutlineSoft;',
    'uniform sampler2D uForm; uniform vec2 uFormStep; uniform float uFormTilt; uniform float uLowPx; uniform float uLipVolume; uniform float uFormOn; uniform vec2 uGlossMax; uniform vec2 uLightSize; uniform float uWideGloss; uniform vec3 uMouthN; uniform float uGlossGain; uniform float uFrontGloss;',
    'uniform float uHlLocal; uniform vec2 uHlSat; uniform float uHlBlown; uniform float uOpaqueShadeGamma; uniform float uLipFill;',
    'float redness(vec3 c) { return (c.r - c.g) / (c.r + c.g + c.b + 1e-4); }',
    // Screen-space lip outline (video coordinates): r = paint area, g = lip form; 0 outside.
    'vec2 outline2(vec2 s) {',
    '  vec2 p = (s - uOutlineRect.xy) / uOutlineRect.zw;',
    '  return (p.x < 0.0 || p.y < 0.0 || p.x > 1.0 || p.y > 1.0) ? vec2(0.0) : texture2D(uOutline, p).rg;',
    '}',
    'float outlineAt(vec2 s) { return outline2(s).r; }',
    // Screen-space eye canvas (video coordinates): r = eyeliner, g = mascara.
    'vec2 eyeAt(vec2 s) {',
    '  vec2 p = (s - uEyeRect.xy) / uEyeRect.zw;',
    '  return (p.x < 0.0 || p.y < 0.0 || p.x > 1.0 || p.y > 1.0) ? vec2(0.0) : texture2D(uEye, p).rg;',
    '}',
    'float formAt(vec2 s) {',
    '  vec2 p = (s - uOutlineRect.xy) / uOutlineRect.zw;',
    '  return (p.x < 0.0 || p.y < 0.0 || p.x > 1.0 || p.y > 1.0) ? 0.0 : texture2D(uForm, p).r;',
    '}',
    'vec3 toLin(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(0.04045, c)); }',
    'vec3 toSrgb(vec3 c) { c = clamp(c, 0.0, 1.0); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c)); }',
    'float lum(vec3 c) { return dot(c, vec3(0.2126, 0.7152, 0.0722)); }',
    'float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }',
    // GGX (Trowbridge-Reitz) with Smith-Schlick geometry and Schlick Fresnel, F0 = 0.04.
    'float ggx(vec3 n, vec3 l, vec3 v, float rough) {',
    '  vec3 h = normalize(l + v);',
    '  float nh = max(dot(n, h), 0.0); float nl = max(dot(n, l), 0.0); float nv = max(dot(n, v), 1e-3);',
    // Clamp a2 and the denominator so mediump GPUs never underflow to 0 (D = inf → NaN pixels).
    '  float a = rough * rough; float a2 = max(a * a, 1e-3);',
    '  float d = nh * nh * (a2 - 1.0) + 1.0;',
    '  float D = a2 / (3.14159 * max(d * d, 1e-4));',
    '  float k = (rough + 1.0) * (rough + 1.0) / 8.0;',
    '  float G = (nl / (nl * (1.0 - k) + k)) * (nv / (nv * (1.0 - k) + k));',
    '  float F = 0.04 + 0.96 * pow(1.0 - max(dot(h, v), 0.0), 5.0);',
    '  return D * G * F / (4.0 * nv);',
    '}',
    // Peak-normalized GGX lobe (1 where the normal faces the half vector).
    'float lobeN(float nh, float r) { float a2 = max(r * r * r * r, 1e-4); float q = a2 / (nh * nh * (a2 - 1.0) + 1.0); return q * q; }',
    // Flakes are fixed to UV cells so they stay on the face when the head turns.
    'float flake(vec2 uv, vec3 n, vec3 l, vec3 v) {',
    '  vec2 cell = floor(uv * 700.0);',
    '  if (hash(cell) < uFlakeDensity) return 0.0;',
    '  vec3 jitter = vec3(hash(cell + 1.3), hash(cell + 7.1), hash(cell + 3.7)) - 0.5;',
    '  vec3 fn = normalize(n + jitter * 0.9);',
    '  return pow(max(dot(fn, normalize(l + v)), 0.0), 60.0);',
    '}',
    // Powder sheen (blush, shadow, highlighter): broad GGX lobe on the mesh normal, key light or the
    // always-present frontal source, peak by smoothness and scene brightness. Matte ≈ 0.
    'float powderSheen(vec3 n, vec3 l, vec3 v, float rough) {',
    '  float r = sqrt(rough * rough + 0.2);',
    '  float lobe = max(lobeN(max(dot(n, normalize(l + v)), 0.0), r), 0.6 * lobeN(max(dot(n, normalize(vec3(0.0, 0.3, 1.0) + v)), 0.0), r));',
    '  float sm = 1.0 - rough;',
    '  return lobe * sm * sm * sm * uFaceSheen * uSkinMeanLum * 3.0;',
    '}',
    // Product albedo under the current light, shaded by the real camera brightness relative to the zone mean.
    'vec3 layer(vec3 cam, vec3 albedo, float refLum, float shadeMax) {',
    '  float shade = clamp(lum(cam) / max(refLum, 1e-3), 0.0, shadeMax);',
    '  return albedo * uLightColor * shade * uExposure;',
    '}',
    // Translucent powder: the camera skin filtered by the pigment (thin film), so a light shade on deep
    // skin tints it instead of laying an ashy patch over it (LaPa 10-25).
    'vec3 powder(vec3 cam, vec3 albedo) {',
    '  vec3 tint = cam * sqrt(clamp(albedo / uPaperWhite, 0.0, 1.0));',
    '  return mix(layer(cam, albedo, uSkinMeanLum, 1.6), tint, uPowderTint);',
    '}',
    'void main() {',
    // Mip bias softens the mask edges as much as the camera image itself is blurred.
    '  vec4 m = texture2D(uMask, vUv, uMaskBias);',
    '  m.r = min(m.r * uLipFill, 1.0);',
    '  float blushA = m.g * uBlushCov; float shadowA = m.b * uShadowCov;',
    '  float lipZone = m.a * uLipOn;',
    '  vec2 suv = vec2(1.0 - gl_FragCoord.x / uViewport.x, 1.0 - gl_FragCoord.y / uViewport.y);',
    '  vec2 m2 = texture2D(uMask2, vUv, uMaskBias).rg;',
    '  float hlA = m2.r * uHlCov; float contourA = m2.g * uContourCov;',
    // Softened by the camera's own blur like the lip outline: crisp 1 px lashes on a soft phone image
    // read as pasted on.
    // 3×3 binomial at the measured blur width (5 taps at half of it still left lashes crisp on a
    // σ 2.5 px blurred frame); only read where the eye canvas is on.
    '  vec2 eyeC = vec2(0.0);',
    '  if (uEyeRect.x > -1.0) {',
    '    vec2 eo = uTexel * uEyeSoft;',
    '    eyeC = 4.0 * eyeAt(suv)',
    '      + 2.0 * (eyeAt(suv + vec2(eo.x, 0.0)) + eyeAt(suv - vec2(eo.x, 0.0)) + eyeAt(suv + vec2(0.0, eo.y)) + eyeAt(suv - vec2(0.0, eo.y)))',
    '      + eyeAt(suv + eo) + eyeAt(suv - eo) + eyeAt(suv + vec2(eo.x, -eo.y)) + eyeAt(suv + vec2(-eo.x, eo.y));',
    '    eyeC /= 16.0;',
    '  }',
    '  float linerA = eyeC.r * uLinerCov; float mascaraA = eyeC.g * uMascaraCov;',
    // Eye-opening triangles carry only lashes (no shadow feather or lip band on the eyeball).
    '  if (uEyeHole > 0.5) { blushA = 0.0; shadowA = 0.0; lipZone = 0.0; hlA = 0.0; contourA = 0.0; linerA = 0.0; }',
    '  if (lipZone + blushA + shadowA + hlA + contourA + linerA + mascaraA < 0.002) discard;',
    '  vec3 cam = toLin(texture2D(uVideo, suv).rgb);',
    '  vec3 n = normalize(vNormal); vec3 v = vec3(0.0, 0.0, 1.0); vec3 l = normalize(uLightDir);',
    '  float lipM = 0.0; float lipEdgeW = 0.0; float redN = 0.0; vec3 lipFormN = n; vec3 lipBaseN = n; vec3 camN = cam;',
    '  float lN = lum(cam);',
    '  float wideL = lN; float hlCap = 0.0; float hlPeak = 0.0; float hlWide = 0.0;',
    '  if (lipZone > 0.002) {',
    // Neighbors: local mean brightness (lip volume vs. wrinkles) and a denoised color for the edge test.
    '    vec2 o = uTexel * 1.5;',
    '    vec3 c1 = toLin(texture2D(uVideo, suv + vec2(o.x, 0.0)).rgb);',
    '    vec3 c2 = toLin(texture2D(uVideo, suv - vec2(o.x, 0.0)).rgb);',
    '    vec3 c3 = toLin(texture2D(uVideo, suv + vec2(0.0, o.y)).rgb);',
    '    vec3 c4 = toLin(texture2D(uVideo, suv - vec2(0.0, o.y)).rgb);',
    '    lN = 0.25 * (lum(c1) + lum(c2) + lum(c3) + lum(c4));',
    '    redN = redness(c1 + c2 + c3 + c4);',
    '    camN = 0.2 * (cam + c1 + c2 + c3 + c4);',
    '    wideL = 0.25 * (lum(toLin(texture2D(uVideo, suv + uTexel * 3.0).rgb)) + lum(toLin(texture2D(uVideo, suv - uTexel * 3.0).rgb))',
    '      + lum(toLin(texture2D(uVideo, suv + vec2(uTexel.x, -uTexel.y) * 3.0).rgb)) + lum(toLin(texture2D(uVideo, suv + vec2(-uTexel.x, uTexel.y) * 3.0).rgb)));',
    // Light reflected by the lip: brighter than the lip and desaturated, and either a peak over the
    // local 3px mean or a wide reflection far above the lip mean. It is white, not red, but it is
    // still lip: it keeps the paint, and below it becomes the gloss and crease detail (device 10-25:
    // reflections were read as skin and left unpainted).
    '    float meanL0 = max(uLipMeanLum, 1e-3);',
    '    float camL0 = max(lum(cam), 1e-4);',
    '    float camSat = (max(cam.r, max(cam.g, cam.b)) - min(cam.r, min(cam.g, cam.b))) / max(max(cam.r, max(cam.g, cam.b)), 1e-4);',
    '    float desat = 1.0 - smoothstep(uHlSat.x, uHlSat.y, camSat);',
    '    hlCap = max(camL0 - uDiffuseCap * meanL0, 0.0) * desat;',
    // Peak: narrow reflection on a ridge or crease edge (the lip surface). Wide: the bare lip's wet shine.
    '    hlPeak = max(camL0 - uHlLocal * wideL, 0.0) * desat;',
    '    hlWide = max(camL0 - uHlBlown * meanL0, 0.0) * desat;',
    // Outer edge and open-mouth hole from the screen-space outline, softened as much as the camera
    // image is blurred; the UV mask only adds the inner and corner fades. No per-pixel redness test:
    // at close range it grew lumps along the line (10-25). Reflections are inside the outline, so lip.
    '    vec2 so = uTexel * uOutlineSoft;',
    '    float inside = (2.0 * outlineAt(suv) + outlineAt(suv + vec2(so.x, 0.0)) + outlineAt(suv - vec2(so.x, 0.0))',
    '      + outlineAt(suv + vec2(0.0, so.y)) + outlineAt(suv - vec2(0.0, so.y))) / 6.0;',
    '    lipM = m.r * inside;',
    // Lip form: the blurred form field says how deep inside each lip (1 deep inside, ~0.5 on its line)
    // and its slope points into the lip, so each lip is a rounded body whose normal tilts outward
    // toward its line (≈ 1 at the line, scaled by the rise width). Video coordinates run left and down
    // on the mirrored screen, hence the sign.
    '    if (lipM > 0.002) {',
    '      vec2 e = uTexel * uFormStep.x;',
    '      float h0 = formAt(suv);',
    '      vec2 grad = vec2(formAt(suv + vec2(e.x, 0.0)) - formAt(suv - vec2(e.x, 0.0)), formAt(suv + vec2(0.0, e.y)) - formAt(suv - vec2(0.0, e.y))) * 0.5 * uFormStep.y;',
    '      lipEdgeW = 1.0 - smoothstep(0.5, 0.97, h0);',
    // The mesh normal already tilts the lower lip up and the upper lip down (20–60°, coarse lip
    // vertices), which pushed a frontal-light highlight to the lower rim: its up/down part comes from
    // the mouth's mean orientation (a little of its own), while left/right keeps the mesh, so the lips
    // still wrap around the teeth and a turned face shows its near side. Tilt saturates at the line
    // (a steep tilt there drew a dark ring, LaPa 10-25).
    '      lipBaseN = normalize(vec3(n.x, mix(uMouthN.y, n.y, 0.3), n.z));',
    '      vec2 tilt = grad * inversesqrt(1.0 + dot(grad, grad)) * uFormTilt * uFormOn;',
    '      lipFormN = normalize(lipBaseN + vec3(tilt.x, tilt.y, 0.0));',
    '    }',
    '  }',
    '  if (lipM + blushA + shadowA + hlA + contourA + linerA + mascaraA < 0.002) discard;',
    '  vec3 col = cam;',
    // Face → eyes → lips, each a product layer over the camera (a mixed product color shaded by the
    // camera brightness), so intensity 0 leaves the pixel as it was.
    '  if (contourA > 0.002) col = mix(col, powder(cam, uContourAlbedo), contourA);',
    '  if (blushA > 0.002) col = mix(col, powder(cam, uBlushAlbedo), blushA) + uBlushAlbedo * uLightColor * powderSheen(n, l, v, uFaceRough.x) * blushA;',
    // Highlighter: a little of its light color, then its own sheen and shimmer where the face meets the light.
    '  if (hlA > 0.002) {',
    '    col = mix(col, layer(cam, uHlAlbedo, uSkinMeanLum, 1.6), 0.35 * hlA);',
    '    col += mix(uHlAlbedo, vec3(1.0), 0.3) * uLightColor * powderSheen(n, l, v, uFaceRough.z) * hlA + vec3(uHlFlake * flake(vUv, n, l, v) * uLightStrength) * hlA;',
    '  }',
    '  if (shadowA > 0.002) {',
    '    vec3 s = layer(cam, uShadowAlbedo, uSkinMeanLum, 1.6) + vec3(uShadowFlake * flake(vUv, n, l, v) * uLightStrength);',
    '    col = mix(col, s, shadowA) + uShadowAlbedo * uLightColor * powderSheen(n, l, v, uFaceRough.y) * shadowA;',
    '  }',
    // Liner and mascara: dense pigment, so the product color shaded by the camera (no skin through);
    // a liquid liner keeps a faint wet line.
    '  if (linerA > 0.002) col = mix(col, layer(cam, uLinerAlbedo, uSkinMeanLum, 1.2), linerA) + uLightColor * uLinerGloss * powderSheen(n, l, v, 0.2) * linerA;',
    '  if (mascaraA > 0.002) col = mix(col, layer(cam, uMascaraAlbedo, uSkinMeanLum, 1.0), mascaraA);',
    '  if (lipM > 0.002) {',
    '    float core = smoothstep(0.5, 0.95, lipM);',
    '    float meanL = max(uLipMeanLum, 1e-3);',
    '    float camL = max(lum(cam), 1e-4);',
    '    float hpAbs = camL - lN;',
    // Layering (AR_SPEC 6-5-3): camera = light × shading × bare-lip color. The lipstick only changes the
    // lip color, so multiply the camera pixel by (layered / bare) reflectance. Wrinkles, upper-lip
    // shade, lower-lip volume, light color, noise and blur all come from the real camera pixel.
    '    vec3 rLip = max(uLipColor / max(uLightColor * uExposure, vec3(1e-3)), vec3(1e-3));',
    // Per-pixel bare lip: the mean lip reflectance with this pixel's own chromaticity. A redder upper
    // lip and a paler lower lip are both covered by the pigment, so the result is one lipstick color
    // (shaded by the camera) instead of the bare-lip color difference multiplied up.
    // Color direction from the 5-pixel mean: a single pixel's color noise, divided out here, came back
    // multiplied by the product/bare ratio.
    '    vec3 chromPx = camN / max(lum(camN), 1e-4);',
    '    vec3 chromLip = uLipColor / max(lum(uLipColor), 1e-4);',
    '    vec3 rPx = max(rLip * clamp(chromPx / max(chromLip, vec3(1e-3)), 0.25, 4.0), vec3(1e-3));',
    // Real lipstick sits unevenly: matte pigment collects in creases, gloss thins on ridges.
    '    float creaseW = clamp((wideL - camL) / (0.15 * meanL), -1.0, 1.0);',
    '    float smoothT = 1.0 - uLipRough;',
    '    float uneven = 1.0 + uCreaseCover * (max(creaseW, 0.0) * (1.0 - smoothT) - max(-creaseW, 0.0) * smoothT);',
    '    float cov = clamp(lipM * uLipCov * uneven, 0.0, 1.0);',
    // Coverage first moves the bare lip toward the product color; only the see-through share of the
    // film then filters it like the dye on white paper. Filtering the bare red by a nude made a sheer
    // nude a darker red than the bare lip (L* 43 vs 47, 10-25).
    '    vec3 paint = mix(rPx, uLipAlbedo, cov);',
    '    vec3 mixCol = paint * mix(vec3(1.0), clamp(uLipAlbedo / uPaperWhite, 0.0, 1.0), cov * uLipTranslucent);',
    // Light and shade come only from the camera and the light-driven lip form; no lightness or chroma
    // fixed by UV position (that drew the upper lip dark and the lower centre light whatever the light).
    '    vec3 ratio = clamp(mixCol / rPx, 0.0, uRatioMax);',
    // Chip hex is an estimate and often brighter than the real bullet: never lift the lip past bare × cap.
    '    float lumGain = dot(ratio * rPx, vec3(0.2126, 0.7152, 0.0722)) / max(lum(rPx), 1e-4);',
    // Pigment that covers the lip may lighten it (B1, 10-25: the cap left a thin film over dark lips);
    // the cap holds only for the uncovered, see-through share.
    '    float gainCap = mix(uRatioMax, uLumGainMax, uLipTranslucent * (1.0 - cov));',
    '    float gainScale = min(1.0, gainCap / max(lumGain, 1e-4));',
    '    ratio *= gainScale;',
    // Camera highlights are surface reflection, not lip color: take them out of the ratio, then keep
    // them by texture (matte dulls them, gloss keeps them). With no paint (cov 0) the pixel is unchanged.
    // Only real reflections: a desaturated peak over the local 3px mean (creases and ridges, kept by
    // every finish as surface detail), or a wide one far above the lip mean: the bare lip's wet shine,
    // which a matte pigment covers and a gloss keeps, so it counts by smoothness. A broadly brighter
    // (paler or lit) lower lip is diffuse shading, kept under the paint (device 10-25 white film).
    '    float hl = min(hlCap, max(hlPeak, hlWide * smoothT)) * core;',
    '    vec3 camDiffuse = cam * (1.0 - hl / camL);',
    // Texture detail: matte fills creases a little (pulls toward the local mean), gloss keeps them.
    '    float fill = 1.0 + (lN / camL - 1.0) * (1.0 - uLipDetailGain) * cov;',
    // Where pigment covers (coverage, every finish: the film's color is already mixed in mixCol) only
    // the camera's brightness (light, shade, creases) carries over. Per-channel ratios there multiplied
    // the camera's color noise (yellow-green speckle on a dark red lip under a nude, 10-25); the
    // uncovered share keeps the camera's own color.
    '    float opaqueW = cov * (1.0 - uLipTranslucent);',
    '    vec3 lumOnly = mixCol * gainScale * (lum(camDiffuse) / max(lum(rPx), 1e-4));',
    '    vec3 layered = mix(camDiffuse * ratio, lumOnly, cov) * clamp(fill, 0.6, 1.6);',
    // Opaque pigment hides the bare lip's own light/dark patches; the camera mixes those with real
    // shading, so under opaque paint the large-scale brightness swing is compressed (not removed):
    // upper-lip shade and lower-lip volume stay, a pale patch no longer glows through (10-25). Only
    // that low-pass part: the lip mean over 8 points at a share of the lip thickness (lip pixels only,
    // no skin or teeth). Fine creases ride on top untouched (compressing them too left a smooth
    // color sheet on flat selfies, 10-25).
    '    float sl = 0.0, sw = 0.0;',
    '    for (int k = 0; k < 8; k++) {',
    '      float a = float(k) * 0.785398;',
    '      vec2 q = suv + uTexel * uLowPx * vec2(cos(a), sin(a));',
    '      float w = outlineAt(q);',
    '      sl += w * min(lum(toLin(texture2D(uVideo, q).rgb)), uDiffuseCap * meanL); sw += w;',
    '    }',
    '    float sLow = sw > 1.0 ? sl / sw : lN;',
    '    float shadeRel = clamp(sLow / meanL, 0.15, 4.0);',
    '    layered *= pow(shadeRel, (uOpaqueShadeGamma - 1.0) * opaqueW);',
    // Skin under the outline is brighter because skin is lighter, not because it is lit more: opaque
    // paint on it takes the lip's base, so the line has no pale rim (sticker look, device 10-25).
    '    float skinW = (1.0 - smoothstep(mix(uSkinRed, uLipRed, 0.25), mix(uSkinRed, uLipRed, 0.75), redN)) * lipEdgeW * uRefine;',
    '    layered *= mix(1.0, min(1.0, meanL / max(uSkinMeanLum, 1e-3)), skinW * opaqueW);',
    // Volume: the paint follows the lip form under the estimated light (Lambert of the form normal
    // relative to the mesh), so it rounds off toward the line instead of a dark band (blurry close-ups
    // carry no camera shading of their own, 10-25). A weak light direction falls back to frontal.
    '    vec3 lV = normalize(mix(vec3(0.0, 0.25, 1.0), l, uLightConf));',
    '    float form = max(dot(lipFormN, lV), 0.0) / max(dot(lipBaseN, lV), 0.2);',
    '    layered *= mix(1.0, clamp(form, 0.35, 1.0), uLipVolume * cov * uFormOn);',
    // A light shade on a bright spot must stay that shade, not clip to white: soft knee on the peak
    // channel, whole color scaled (hue kept, light/dark order kept). Real speculars are added below.
    '    float pk = max(layered.r, max(layered.g, layered.b));',
    '    float pkSoft = pk < 0.7 ? pk : 0.7 + 0.3 * (1.0 - exp(-(pk - 0.7) / 0.3));',
    '    layered *= pkSoft / max(pk, 1e-4);',
    '    float smooth1 = smoothT;',
    '    float keepHl = mix(1.0, mix(uHlKeep.x, uHlKeep.y, smooth1), cov);',
    // Clear coat: GGX on the real mesh normal toward the estimated light, plus glints on lip ridges.
    '    float glint = max(hpAbs - uGlintThreshold * meanL, 0.0) * uLipGlint * smooth1 * smooth1;',
    '    float lightMix = max(uLightConf, uSpecFill);',
    '    float specPbr = ggx(n, l, v, uLipRough) * max(dot(n, l), 0.0) * uLightStrength * uExposure * uSkinRef * lightMix;',
    '    float peakMask = pow(max(dot(n, normalize(l + v)), 0.0), mix(28.0, 64.0, uLipRough)) * core;',
    '    float sheen = pow(max(dot(lipFormN, normalize(l + v)), 0.0), mix(4.0, 10.0, smooth1)) * smooth1 * smooth1 * uLipSheen * lightMix * core;',
    // Finish highlight on the lip form: GGX at the finish's roughness, the light's color and strength,
    // capped from a matte's faint sheen to a gloss's near-white streak. Lands where the form faces the
    // half vector: lower-lip centre and upper-lip ridge under frontal light, shifting with the light.
    // A gloss reflects the light source itself, so its peak follows the scene's brightness (skin
    // luminance), not the diffuse light-strength fit (0.06–0.56 on LaPa: the gloss vanished).
    '    float glossCap = mix(uGlossMax.x, uGlossMax.y, smooth1 * smooth1 * smooth1) * uSkinMeanLum * uGlossGain;',
    // Two lobes, each the GGX shape at the finish roughness widened by a light size, peak-normalized:
    // the light source's own sharp reflection (a gloss's near-white spot) and the wide glow around it
    // (a satin's sheen). A rough finish makes both broad and alike. One lobe widened for a big light
    // read as satin on gloss (10-25, LaPa next to a real gloss).
    '    float nh = max(dot(lipFormN, normalize(lV + v)), 0.0);',
    // A selfie always has a soft frontal source too (phone screen, the room in front): with a strong
    // side key light no lip normal faces its half vector, but the gloss still catches the front.
    '    float nf = max(dot(lipFormN, normalize(vec3(0.0, 0.3, 1.0) + v)), 0.0);',
    '    float rS = sqrt(uLipRough * uLipRough + uLightSize.x * uLightSize.x);',
    '    float rW = sqrt(uLipRough * uLipRough + uLightSize.y * uLightSize.y);',
    // The source's reflection has a defined edge (a window or panel is a shape, not a blur); the
    // smoother the finish, the crisper that edge.
    '    float edgeLo = mix(0.0, 0.3, smooth1 * smooth1);',
    '    float sharpK = smoothstep(edgeLo, edgeLo + 0.35, lobeN(nh, rS)), sharpF = smoothstep(edgeLo, edgeLo + 0.35, lobeN(nf, rS));',
    '    float lobe = max(sharpK + uWideGloss * lobeN(nh, rW), uFrontGloss * (sharpF + uWideGloss * lobeN(nf, rW)));',
    '    float formSpec = glossCap * lobe * core * uFormOn;',
    '    float spec = (min(specPbr * uLipSpec * peakMask, uLipSpecMax) * (1.0 - uFormOn) + min(glint, 0.05) + sheen) * cov;',
    '    vec3 specTint = mix(uLipAlbedo, vec3(1.0), 0.16);',
    // Gloss is the color brightened toward the light: a clear coat (glossy) reflects the light's own
    // color, a pigmented satin or cream sheen stays the product color (no white band on satin lips).
    '    vec3 hue = uLipAlbedo / max(max(uLipAlbedo.r, max(uLipAlbedo.g, uLipAlbedo.b)), 1e-3);',
    '    vec3 sheenCol = uLightColor * mix(hue, vec3(1.0), smooth1 * smooth1 * smooth1);',
    '    float fl = uLipFlake * flake(vUv, n, l, v) * uLightStrength * core;',
    '    col += layered + vec3(hl * keepHl) - cam + specTint * spec + sheenCol * formSpec * cov + vec3(fl) * lipM;',
    '  }',
    '  gl_FragColor = vec4(toSrgb(col), 1.0);',
    '}',
  ].join(NL);

  function createGLRenderer() {
    const opts = { alpha: false, antialias: false, premultipliedAlpha: false, depth: true };
    let gl = glCanvas.getContext('webgl2', opts);
    const version = gl ? 'webgl2' : 'webgl';
    if (!gl) gl = glCanvas.getContext('webgl', opts);
    if (!gl) return null;
    function shader(type, src) {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) || 'shader');
      return s;
    }
    function program(vs, fs, uniforms) {
      const p = gl.createProgram();
      gl.attachShader(p, shader(gl.VERTEX_SHADER, vs));
      gl.attachShader(p, shader(gl.FRAGMENT_SHADER, fs));
      gl.linkProgram(p);
      if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) || 'link');
      const u = {};
      for (const n of uniforms) u[n] = gl.getUniformLocation(p, n);
      return { p, u };
    }
    const bg = program(BG_VERT, BG_FRAG, ['uVideo']);
    const mesh = program(MESH_VERT, MESH_FRAG, ['uVideo', 'uMask', 'uViewport', 'uLightColor', 'uLightDir',
      'uLightStrength', 'uLightConf', 'uExposure', 'uLipMeanLum', 'uSkinMeanLum', 'uLipAlbedo', 'uLipCov',
      'uLipRough', 'uLipSpec', 'uLipFlake', 'uLipOn', 'uBlushAlbedo', 'uBlushCov', 'uShadowAlbedo', 'uShadowCov',
      'uShadowFlake', 'uSpecMax', 'uFlakeDensity', 'uTexel', 'uLipRed', 'uSkinRed', 'uRefine', 'uLipDetailGain',
      'uLipGlint', 'uGlintThreshold', 'uDiffuseCap', 'uSkinRef',
      'uLipTranslucent', 'uMaskBias',
      'uSpecFill', 'uLipColor', 'uPaperWhite', 'uRatioMax', 'uLipSpecMax', 'uHlKeep',
      'uLumGainMax', 'uCreaseCover', 'uLipSheen',
      'uOutline', 'uOutlineRect', 'uOutlineSoft', 'uForm', 'uFormStep', 'uFormTilt', 'uLowPx', 'uLipVolume', 'uFormOn', 'uGlossMax', 'uLightSize', 'uWideGloss', 'uMouthN', 'uGlossGain', 'uFrontGloss',
      'uHlLocal', 'uHlSat', 'uHlBlown', 'uOpaqueShadeGamma', 'uLipFill',
      'uMask2', 'uHlAlbedo', 'uHlCov', 'uHlFlake', 'uContourAlbedo', 'uContourCov', 'uFaceRough', 'uFaceSheen', 'uEyeHole', 'uPowderTint',
      'uEye', 'uEyeRect', 'uLinerAlbedo', 'uLinerCov', 'uLinerGloss', 'uMascaraAlbedo', 'uMascaraCov', 'uEyeSoft']);
    const bgPos = gl.getAttribLocation(bg.p, 'aPos');
    const aPos = gl.getAttribLocation(mesh.p, 'aPos');
    const aUv = gl.getAttribLocation(mesh.p, 'aUv');
    const aNormal = gl.getAttribLocation(mesh.p, 'aNormal');

    function buffer(target, data, usage) {
      const b = gl.createBuffer();
      gl.bindBuffer(target, b);
      gl.bufferData(target, data, usage);
      return b;
    }
    const quadBuf = buffer(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const posBuf = buffer(gl.ARRAY_BUFFER, meshPos, gl.DYNAMIC_DRAW);
    const nrmBuf = buffer(gl.ARRAY_BUFFER, meshNrm, gl.DYNAMIC_DRAW);
    const uvBuf = buffer(gl.ARRAY_BUFFER, new Float32Array(FACE_UV), gl.STATIC_DRAW);
    const idxBuf = buffer(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(FACE_TRIANGLES), gl.STATIC_DRAW);
    const mouthBuf = buffer(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(FACE_MOUTH_TRIANGLES), gl.STATIC_DRAW);
    const eyeHoleBuf = buffer(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(EYE_HOLE_TRIANGLES), gl.STATIC_DRAW);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);

    const videoTex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE0);
    gl.bindTexture(gl.TEXTURE_2D, videoTex);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    const maskTex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE1);
    gl.bindTexture(gl.TEXTURE_2D, maskTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, masks.size, masks.size, 0, gl.RGBA, gl.UNSIGNED_BYTE, masks.rgba);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    // Highlighter (R) and contour (G) UV masks, painted once.
    const mask2Tex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE2);
    gl.bindTexture(gl.TEXTURE_2D, mask2Tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, masks.size, masks.size, 0, gl.RGBA, gl.UNSIGNED_BYTE, masks.rgba2);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    // Screen-space eye canvas (eyeliner, mascara), refreshed every frame they are on.
    const eyeTex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE5);
    gl.bindTexture(gl.TEXTURE_2D, eyeTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4));
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    // Blurred lip form field, refreshed with the outline.
    const formTex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE4);
    gl.bindTexture(gl.TEXTURE_2D, formTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4));
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    // Screen-space lip outline crop, refreshed every frame from outlineCanvas.
    const outlineTex = gl.createTexture();
    gl.activeTexture(gl.TEXTURE3);
    gl.bindTexture(gl.TEXTURE_2D, outlineTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 1, 1, 0, gl.RGBA, gl.UNSIGNED_BYTE, new Uint8Array(4));
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);

    let lost = false;
    glCanvas.addEventListener('webglcontextlost', (e) => { e.preventDefault(); lost = true; });

    function attrib(loc, buf, size) {
      if (loc < 0) return;
      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.enableVertexAttribArray(loc);
      gl.vertexAttribPointer(loc, size, gl.FLOAT, false, 0, 0);
    }
    function disableAll() {
      for (const loc of [bgPos, aPos, aUv, aNormal]) if (loc >= 0) gl.disableVertexAttribArray(loc);
    }
    function material(zone) {
      return MATERIALS[zone && zone.texture] || MATERIALS.matte;
    }

    return {
      name: version,
      get lost() { return lost; },
      // Snapshot the current camera frame before detection, so image and landmarks are the same frame.
      upload() {
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, videoTex);
        gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, video);
      },
      render(W, H) {
        if (glCanvas.width !== W || glCanvas.height !== H) { glCanvas.width = W; glCanvas.height = H; }
        gl.viewport(0, 0, W, H);
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, videoTex);

        // 1. Camera image (mirrored).
        disableAll();
        gl.disable(gl.DEPTH_TEST);
        gl.useProgram(bg.p);
        gl.uniform1i(bg.u.uVideo, 0);
        attrib(bgPos, quadBuf, 2);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);

        const lip = makeup.lip, blush = makeup.blush, eye = makeup.eyeshadow;
        const liner = makeup.eyeliner || null, mascara = makeup.mascara || null;
        const hl = makeup.highlighter || null, contourZ = makeup.contour || null;
        if (!hasFace || compare || !(lip || blush || eye || liner || mascara || hl || contourZ)) return;

        gl.bindBuffer(gl.ARRAY_BUFFER, posBuf);
        gl.bufferSubData(gl.ARRAY_BUFFER, 0, meshPos);
        gl.bindBuffer(gl.ARRAY_BUFFER, nrmBuf);
        gl.bufferSubData(gl.ARRAY_BUFFER, 0, meshNrm);

        // 2. Face mesh with makeup; depth test keeps the near side when the head turns.
        gl.enable(gl.DEPTH_TEST);
        gl.depthFunc(gl.LESS);
        gl.clear(gl.DEPTH_BUFFER_BIT);
        disableAll();
        gl.useProgram(mesh.p);
        attrib(aPos, posBuf, 3);
        attrib(aUv, uvBuf, 2);
        attrib(aNormal, nrmBuf, 3);
        gl.activeTexture(gl.TEXTURE1);
        gl.bindTexture(gl.TEXTURE_2D, maskTex);
        const u = mesh.u;
        gl.activeTexture(gl.TEXTURE2);
        gl.bindTexture(gl.TEXTURE_2D, mask2Tex);
        gl.uniform1i(u.uMask2, 2);
        const eyesOn = liner || mascara ? drawEyes(W, H, liner, mascara) : false;
        gl.activeTexture(gl.TEXTURE5);
        gl.bindTexture(gl.TEXTURE_2D, eyeTex);
        if (eyesOn) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, eyeCanvas);
        gl.uniform1i(u.uEye, 5);
        if (eyesOn) gl.uniform4f(u.uEyeRect, eyeRect[0], eyeRect[1], eyeRect[2], eyeRect[3]);
        else gl.uniform4f(u.uEyeRect, -2, -2, 1, 1);
        gl.uniform1f(u.uEyeHole, 0);
        gl.uniform1f(u.uEyeSoft, Math.max(0.6, 0.9 * light.blur));
        const hlMat = material(hl), blushMat = material(blush), linerMat = material(liner);
        const hlAlb = hl ? hexToLinear(hl.hex) : [0, 0, 0], contourAlb = contourZ ? hexToLinear(contourZ.hex) : [0, 0, 0];
        const linerAlb = liner ? hexToLinear(liner.hex) : [0, 0, 0], mascaraAlb = mascara ? hexToLinear(mascara.hex) : [0, 0, 0];
        gl.uniform3f(u.uHlAlbedo, hlAlb[0], hlAlb[1], hlAlb[2]);
        gl.uniform1f(u.uHlCov, hl ? clamp01(hl.intensity) * TUNING.hlCoverage : 0);
        gl.uniform1f(u.uHlFlake, hl ? hlMat.flake * TUNING.shimmerFlake * clamp01(hl.intensity) : 0);
        gl.uniform3f(u.uContourAlbedo, contourAlb[0], contourAlb[1], contourAlb[2]);
        gl.uniform1f(u.uContourCov, contourZ ? clamp01(contourZ.intensity) * TUNING.contourCoverage : 0);
        gl.uniform3f(u.uFaceRough, blushMat.roughness, material(eye).roughness, hlMat.roughness);
        gl.uniform1f(u.uFaceSheen, TUNING.faceSheen);
        gl.uniform1f(u.uPowderTint, TUNING.powderTint);
        gl.uniform3f(u.uLinerAlbedo, linerAlb[0], linerAlb[1], linerAlb[2]);
        gl.uniform1f(u.uLinerCov, liner ? 0.55 + 0.4 * clamp01(liner.intensity) : 0);
        gl.uniform1f(u.uLinerGloss, liner ? 1 - linerMat.roughness : 0);
        gl.uniform3f(u.uMascaraAlbedo, mascaraAlb[0], mascaraAlb[1], mascaraAlb[2]);
        gl.uniform1f(u.uMascaraCov, mascara ? 0.5 + 0.45 * clamp01(mascara.intensity) : 0);
        const outlineOn = lip ? drawLipOutline(W, H) : false;
        gl.activeTexture(gl.TEXTURE3);
        gl.bindTexture(gl.TEXTURE_2D, outlineTex);
        if (outlineOn) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, outlineCanvas);
        gl.uniform1i(u.uOutline, 3);
        // No outline (no lip shade) → rect off screen, so outlineAt is 0 everywhere.
        if (outlineOn) gl.uniform4f(u.uOutlineRect, outlineRect[0], outlineRect[1], outlineRect[2], outlineRect[3]);
        else gl.uniform4f(u.uOutlineRect, -2, -2, 1, 1);
        // Outline edge as soft as the camera's own blur; volume reach a share of this lip's thickness.
        gl.uniform1f(u.uOutlineSoft, Math.max(0.5, 0.5 * light.blur));
        gl.activeTexture(gl.TEXTURE4);
        gl.bindTexture(gl.TEXTURE_2D, formTex);
        if (outlineOn && TUNING.lipForm) gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, formCanvas);
        gl.uniform1i(u.uForm, 4);
        gl.uniform2f(u.uFormStep, formStep[0], formStep[1]);
        gl.uniform1f(u.uFormTilt, TUNING.formTilt);
        gl.uniform1f(u.uLowPx, Math.max(3, TUNING.lowReach * 0.5 * (lipThick.up + lipThick.low)));
        gl.uniform1f(u.uLipVolume, TUNING.lipVolume);
        gl.uniform1f(u.uFormOn, TUNING.lipForm ? 1 : 0);
        gl.uniform2f(u.uGlossMax, TUNING.glossMax[0], TUNING.glossMax[1]);
        gl.uniform2f(u.uLightSize, TUNING.lightSize[0], TUNING.lightSize[1]);
        gl.uniform1f(u.uWideGloss, TUNING.wideGloss);
        gl.uniform3f(u.uMouthN, mouthN[0], mouthN[1], mouthN[2]);
        gl.uniform1f(u.uGlossGain, TUNING.glossGain);
        gl.uniform1f(u.uFrontGloss, TUNING.frontGloss);
        gl.uniform1f(u.uHlLocal, TUNING.hlLocal);
        gl.uniform1f(u.uHlBlown, TUNING.hlBlown);
        gl.uniform1f(u.uLipFill, TUNING.lipFill);
        gl.uniform2f(u.uHlSat, TUNING.hlSat[0], TUNING.hlSat[1]);
        gl.uniform1f(u.uOpaqueShadeGamma, TUNING.opaqueShadeGamma);
        const lipMat = material(lip), eyeMat = material(eye);
        const lipAlb = lip ? hexToLinear(lip.hex) : [0, 0, 0];
        const blushAlb = blush ? hexToLinear(blush.hex) : [0, 0, 0];
        const eyeAlb = eye ? hexToLinear(eye.hex) : [0, 0, 0];
        const exposure = clamp(light.skinMeanLum / TUNING.skinRefLum, TUNING.exposureRange[0], TUNING.exposureRange[1]);
        gl.uniform1i(u.uVideo, 0);
        gl.uniform1i(u.uMask, 1);
        gl.uniform2f(u.uViewport, W, H);
        gl.uniform3f(u.uLightColor, light.color[0], light.color[1], light.color[2]);
        gl.uniform3f(u.uLightDir, light.dir[0], light.dir[1], light.dir[2]);
        gl.uniform1f(u.uLightStrength, light.strength);
        gl.uniform1f(u.uLightConf, light.dirConf);
        gl.uniform1f(u.uExposure, exposure);
        gl.uniform1f(u.uLipMeanLum, light.lipMeanLum);
        gl.uniform1f(u.uSkinMeanLum, light.skinMeanLum);
        gl.uniform3f(u.uLipAlbedo, lipAlb[0], lipAlb[1], lipAlb[2]);
        gl.uniform1f(u.uLipCov, lip ? lipCoverage(lip, lipMat) : 0);
        gl.uniform1f(u.uLipRough, lipMat.roughness);
        gl.uniform1f(u.uLipSpec, lipMat.specular);
        gl.uniform1f(u.uLipFlake, lip ? lipMat.flake * TUNING.shimmerFlake * clamp01(lip.intensity) : 0);
        gl.uniform1f(u.uLipOn, lip ? 1 : 0);
        gl.uniform3f(u.uBlushAlbedo, blushAlb[0], blushAlb[1], blushAlb[2]);
        gl.uniform1f(u.uBlushCov, blush ? clamp01(blush.intensity) * TUNING.blushCoverage : 0);
        gl.uniform3f(u.uShadowAlbedo, eyeAlb[0], eyeAlb[1], eyeAlb[2]);
        gl.uniform1f(u.uShadowCov, eye ? clamp01(eye.intensity) * TUNING.shadowCoverage : 0);
        gl.uniform1f(u.uShadowFlake, eye ? eyeMat.flake * TUNING.shimmerFlake * clamp01(eye.intensity) : 0);
        gl.uniform1f(u.uSpecMax, TUNING.specMax);
        gl.uniform1f(u.uFlakeDensity, TUNING.flakeDensity);
        gl.uniform2f(u.uTexel, 1 / W, 1 / H);
        gl.uniform1f(u.uLipRed, light.lipRed);
        gl.uniform1f(u.uSkinRed, light.skinRed);
        gl.uniform1f(u.uRefine, clamp((light.lipRed - light.skinRed - TUNING.refineMinContrast) / TUNING.refineMinContrast, 0, 1));
        gl.uniform1f(u.uLipDetailGain, lipMat.detail * TUNING.creaseGain);
        gl.uniform1f(u.uLipTranslucent, lipMat.translucent);
        gl.uniform1f(u.uMaskBias, Math.log2(Math.max(1, light.blur)));
        gl.uniform1f(u.uLipGlint, TUNING.lipGlint);
        gl.uniform1f(u.uGlintThreshold, TUNING.glintThreshold);
        gl.uniform1f(u.uDiffuseCap, TUNING.diffuseCap);
        gl.uniform1f(u.uSkinRef, TUNING.skinRefLum);
        gl.uniform1f(u.uSpecFill, TUNING.specFill);
        gl.uniform3f(u.uLipColor, light.lipColor[0], light.lipColor[1], light.lipColor[2]);
        gl.uniform1f(u.uPaperWhite, TUNING.paperWhite);
        gl.uniform1f(u.uRatioMax, TUNING.ratioMax);
        gl.uniform1f(u.uLipSpecMax, TUNING.lipSpecMax);
        gl.uniform2f(u.uHlKeep, TUNING.hlKeep[0], TUNING.hlKeep[1]);
        gl.uniform1f(u.uLumGainMax, TUNING.lumGainMax);
        gl.uniform1f(u.uCreaseCover, TUNING.creaseCover);
        gl.uniform1f(u.uLipSheen, TUNING.lipSheen);
        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, idxBuf);
        gl.drawElements(gl.TRIANGLES, FACE_TRIANGLES.length, gl.UNSIGNED_SHORT, 0);
        // The mouth hole too: the outline paints the thin gap of closed lips and leaves an open mouth
        // (teeth) unpainted along the smooth inner curve, not the mesh's straight hole edges.
        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, mouthBuf);
        gl.drawElements(gl.TRIANGLES, FACE_MOUTH_TRIANGLES.length, gl.UNSIGNED_SHORT, 0);
        // Eye openings: only lashes overhang them.
        if (mascara && eyesOn) {
          gl.uniform1f(u.uEyeHole, 1);
          gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, eyeHoleBuf);
          gl.drawElements(gl.TRIANGLES, EYE_HOLE_TRIANGLES.length, gl.UNSIGNED_SHORT, 0);
        }
      },
    };
  }

  // ── Debug HUD (double-tap) ───────────────────────────────────────────
  let hudOn = false;
  let lastTap = 0;
  let fps = 0, fpsFrames = 0, fpsAt = 0;
  let wbLocked = false, colorTempK = null;
  function toggleHud() {
    hudOn = !hudOn;
    hud.style.display = hudOn ? 'block' : 'none';
    if (!hudOn) overlayCtx.clearRect(0, 0, overlay.width, overlay.height);
  }
  // HUD only: landmark outer lip line (white) and camera-measured lip edge (green = trusted,
  // red = not found / outlier). Same size and mirroring as the WebGL canvas, so dots sit on the video.
  function drawLipPoints(W, H) {
    if (overlay.width !== W || overlay.height !== H) { overlay.width = W; overlay.height = H; }
    overlayCtx.clearRect(0, 0, W, H);
    if (!hasFace) return;
    const r = Math.max(1.5, W / 400);
    const dot = (x, y, color) => {
      overlayCtx.fillStyle = color;
      overlayCtx.beginPath(); overlayCtx.arc((1 - x) * W, y * H, r, 0, Math.PI * 2); overlayCtx.fill();
    };
    for (const i of LIPS_OUTER) dot(sx[i], sy[i], 'rgba(255,255,255,0.9)');
    for (let k = 0; k < LIP_RAYS; k++) {
      const e = rayEnds(k), t = lipEdge.t[k];
      dot(e[0] + t * (e[2] - e[0]), e[1] + t * (e[3] - e[1]), lipEdge.conf[k] > 0.5 ? '#3cff6a' : '#ff4040');
    }
  }
  document.addEventListener('touchend', () => {
    const t = Date.now();
    if (t - lastTap < 300) toggleHud();
    lastTap = t;
  });
  document.addEventListener('dblclick', toggleHud);
  function updateHud() {
    if (!hudOn) return;
    const f = (v) => v.toFixed(2);
    hud.textContent = [
      'fps ' + fps + '  ' + (renderer ? renderer.name : '-') + '  face ' + landmarkerDelegate,
      'light rgb ' + light.color.map(f).join(' ') + '  conf ' + f(light.colorConf),
      'bg ' + f(light.bgFraction) + '  seg ' + (segmenter ? 'on' : 'off'),
      'dir ' + light.dir.map(f).join(' ') + '  conf ' + f(light.dirConf),
      'strength ' + f(light.strength) + '  lip ' + f(light.lipMeanLum) + '  skin ' + f(light.skinMeanLum),
      'mouth gap ' + f(Math.hypot(sx[13] - sx[14], sy[13] - sy[14]) / Math.max(1e-4, Math.hypot(sx[61] - sx[291], sy[61] - sy[291]))) + (mouthClosed() ? ' closed' : ' open'),
      'lip thick up ' + lipThick.up.toFixed(1) + 'px low ' + lipThick.low.toFixed(1) + 'px  /w ' + f(lipThick.upRatio) + ' ' + f(lipThick.lowRatio),
      'thick base ' + (lipThick.upBase ? f(lipThick.upBase) + ' ' + f(lipThick.lowBase) + '  now/base ' + f(lipThick.upRatio / lipThick.upBase) + ' ' + f(lipThick.lowRatio / lipThick.lowBase) : '- (close mouth, face front)'),
      'edge ' + (TUNING.lipEdgePx * lipThick.uvScale).toFixed(1) + 'px  band ' + (TUNING.lipBandPx * lipThick.uvScale).toFixed(1) + 'px  (share of up ' + f(TUNING.lipEdgePx * lipThick.uvScale / Math.max(1e-4, lipThick.up)) + ')',
      'real edge / landmark  up ' + f(lipEdge.up) + '  low ' + f(lipEdge.low) + (lipEdge.samples ? '' : '  (no lip/skin contrast)'),
      'lip outline ' + outlineCanvas.width + 'x' + outlineCanvas.height + '  form reach ' + (TUNING.formReach * 0.5 * (lipThick.up + lipThick.low)).toFixed(1) + 'px',
      'lip up/low ' + f(light.lipUpLow),
      'lip rgb ' + light.lipColor.map(f).join(' ') + '  red lip ' + f(light.lipRed) + '  skin ' + f(light.skinRed) + '  grain ' + f(light.grain) + '  blur ' + f(light.blur),
      'wb ' + (wbLocked ? 'locked' : 'auto') + (colorTempK ? '  ' + colorTempK + 'K' : ''),
    ].join(NL);
  }

  // ── Main loop ────────────────────────────────────────────────────────
  // Runs once per new camera frame: upload → detect on that frame → draw.
  function processFrame(now) {
    if (video.readyState < 2) return;
    const W = video.videoWidth, H = video.videoHeight;
    if (!W || !H) return;
    if (renderer.lost) { setStatus('unavailable', 'webgl context lost'); return; }
    try { renderer.upload(); } catch (e) { return; }

    if (landmarker) {
      try {
        const result = landmarker.detectForVideo(video, now);
        const face = result.faceLandmarks && result.faceLandmarks[0];
        if (face) {
          filterLandmarks(face, now / 1000);
          hasFace = true;
          lastFaceAt = now;
          setStatus('tracking');
        } else if (now - lastFaceAt > 700) {
          hasFace = false;
          lipThick.upBase = 0; lipThick.lowBase = 0;
          lipEdge.samples = 0; lipEdge.conf.fill(0);
          filterReady = false;
          setStatus('no-face');
        }
      } catch (e) { /* skip frame */ }
    }

    if (hasFace) {
      updateMesh(W, H);
      if (now - lastLightAt > TUNING.lightEveryMs) {
        lastLightAt = now;
        try { sampleScene(now, W, H); } catch (e) { /* light estimation is best-effort */ }
        measureLipThickness(W, H);
        try { measureLipEdge(W, H); } catch (e) { /* edge measurement is best-effort */ }
        updateHud();
      }
    }

    fpsFrames++;
    if (now - fpsAt >= 1000) { fps = fpsFrames; fpsFrames = 0; fpsAt = now; }

    try { renderer.render(W, H); } catch (e) { /* skip frame */ }
    if (hudOn) drawLipPoints(W, H);
  }
  // Prefer requestVideoFrameCallback (fires once per camera frame, AR_SPEC 6-1); else poll with rAF.
  function onVideoFrame() {
    video.requestVideoFrameCallback(onVideoFrame);
    processFrame(performance.now());
  }
  function onAnimationFrame(now) {
    requestAnimationFrame(onAnimationFrame);
    if (video.currentTime === lastVideoTime) return;
    lastVideoTime = video.currentTime;
    processFrame(now);
  }
  function startLoop() {
    if (typeof video.requestVideoFrameCallback === 'function') video.requestVideoFrameCallback(onVideoFrame);
    else requestAnimationFrame(onAnimationFrame);
  }

  async function createLandmarker(vision, files, delegate) {
    return vision.FaceLandmarker.createFromOptions(files, {
      baseOptions: { modelAssetPath: MODEL_URL, delegate },
      runningMode: 'VIDEO',
      numFaces: 1,
      minFaceDetectionConfidence: 0.5,
      minTrackingConfidence: 0.5,
    });
  }
  async function createSegmenter(vision, files, delegate) {
    return vision.ImageSegmenter.createFromOptions(files, {
      baseOptions: { modelAssetPath: SEG_MODEL_URL, delegate },
      runningMode: 'VIDEO',
      outputCategoryMask: true,
      outputConfidenceMasks: false,
    });
  }

  // Camera info (6-6-1 ③): read color temperature, lock white balance after auto WB settles. Optional.
  function tryLockWhiteBalance(track) {
    try {
      const caps = track.getCapabilities ? track.getCapabilities() : {};
      const settings = track.getSettings ? track.getSettings() : {};
      if (settings.colorTemperature) colorTempK = settings.colorTemperature;
      if (caps.whiteBalanceMode && caps.whiteBalanceMode.indexOf('manual') >= 0) {
        track.applyConstraints({ advanced: [{ whiteBalanceMode: 'manual' }] })
          .then(() => { wbLocked = true; })
          .catch(() => {});
      }
    } catch (e) { /* not supported */ }
  }

  async function start() {
    setStatus('loading');
    post({ type: 'hello' });
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus('unavailable', 'getUserMedia not supported');
      return;
    }
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user', width: { ideal: 720 }, height: { ideal: 960 } },
        audio: false,
      });
      video.srcObject = stream;
      await video.play();
    } catch (e) {
      const name = e && e.name;
      setStatus(name === 'NotAllowedError' || name === 'SecurityError' ? 'denied' : 'unavailable', String(e && e.message));
      return;
    }
    const track = stream.getVideoTracks()[0];
    if (track) setTimeout(() => tryLockWhiteBalance(track), 2000);

    try {
      masks = paintMasks();
      renderer = createGLRenderer();
    } catch (e) {
      renderer = null;
    }
    if (!renderer) {
      setStatus('unavailable', 'webgl unavailable');
      return;
    }
    startLoop();

    let vision, files;
    try {
      vision = await import('https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@' + VERSION + '/vision_bundle.mjs');
      files = await vision.FilesetResolver.forVisionTasks('https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@' + VERSION + '/wasm');
      try { landmarker = await createLandmarker(vision, files, 'GPU'); landmarkerDelegate = 'gpu'; }
      catch (e) { landmarker = await createLandmarker(vision, files, 'CPU'); landmarkerDelegate = 'cpu'; }
    } catch (e) {
      setStatus('unavailable', 'model: ' + String(e && e.message));
      return;
    }
    // Segmenter only feeds the light color; AR keeps running without it.
    try { segmenter = await createSegmenter(vision, files, 'GPU'); }
    catch (e) {
      try { segmenter = await createSegmenter(vision, files, 'CPU'); } catch (e2) { segmenter = null; }
    }
  }

  document.addEventListener('visibilitychange', () => {
    const stream = video.srcObject;
    if (!stream) return;
    stream.getVideoTracks().forEach((t) => { t.enabled = !document.hidden; });
  });

  start();
</script>
</body>
</html>`;
