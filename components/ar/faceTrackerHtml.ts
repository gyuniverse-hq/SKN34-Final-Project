/**
 * Self-contained page that runs MediaPipe Face Landmarker on the front camera and
 * renders makeup. Runs fully on-device: frames are never stored or sent.
 *
 * Rendering: low-res 2D canvases build soft masks (lips/eye openings at 1/2, blush/
 * eyeshadow at 1/4 resolution); a WebGL shader recolors lips in LAB space (keeping the
 * original lip lightness and texture) and blends blush/eyeshadow. Falls back to a 2D
 * canvas compositor when WebGL is unavailable. Tune values in TUNING on real devices.
 *
 * Protocol
 *   host → page : {"type":"makeup","makeup":MakeupState} | {"type":"compare","value":boolean}
 *   page → host : {"type":"hello"} | {"type":"status","status":ArStatus,"detail"?:string}
 */
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
</style>
</head>
<body>
<video id="video" playsinline muted autoplay></video>
<canvas id="canvas"></canvas>
<canvas id="canvas2d" style="display:none"></canvas>
<script type="module">
  const VERSION = '${MEDIAPIPE_VERSION}';
  const MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task';
  const NL = String.fromCharCode(10);

  // ── Tuning: adjust these on real devices ─────────────────────────────
  const TUNING = {
    smoothMinCutoff: 1.5,       // One Euro: lower = steadier when still
    smoothBeta: 12,             // One Euro: higher = less lag when moving
    smoothDCutoff: 1.0,
    lipDetail: 0.85,            // how much original lip texture survives the recolor
    lipChroma: 0.88,            // share of product hue/chroma vs. original lip
    lipAmount: [0.45, 0.5],     // opacity = base + intensity * k
    sheerFactor: 0.6,
    glossStrength: 0.3,
    blushAmount: [0.25, 0.7],
    blushSize: [0.17, 0.11],    // ellipse radii relative to face width
    eyeAmount: [0.25, 0.6],
    shadowCrease: 0.6,          // how far toward the brow the shadow reaches (0..1)
    shimmerStrength: 0.35,
    lightRefL: 68,              // skin lightness (LAB L) treated as neutral lighting
    lightGainRange: [0.72, 1.08],
    statsEveryNFrames: 8,
  };
  const TEXTURES = {
    matte: { gloss: 0, matte: 1 },
    velvet: { gloss: 0, matte: 0.7 },
    glossy: { gloss: 1, matte: 0 },
    satin: { gloss: 0.5, matte: 0.2 },
    sheer: { gloss: 0.6, matte: 0 },
    cream: { gloss: 0.3, matte: 0.3 },
    shimmer: { gloss: 0.4, matte: 0 },
  };

  const LIPS_OUTER = [61,185,40,39,37,0,267,269,270,409,291,375,321,405,314,17,84,181,91,146];
  const LIPS_INNER = [78,191,80,81,82,13,312,311,310,415,308,324,318,402,317,14,87,178,88,95];
  const EYES = [
    { lid: [33,246,161,160,159,158,157,173,133], brow: [46,53,52,65,55],
      contour: [33,7,163,144,145,153,154,155,133,173,157,158,159,160,161,246] },
    { lid: [263,466,388,387,386,385,384,398,362], brow: [276,283,282,295,285],
      contour: [263,249,390,373,374,380,381,382,362,398,384,385,386,387,388,466] },
  ];
  const CHEEKS = [
    { inner: 50, outer: 116, low: 205, edge: 234 },
    { inner: 280, outer: 345, low: 425, edge: 454 },
  ];
  const NOSE_TIP = 1;
  const FACE_EDGES = [234, 454];
  const SKIN_SAMPLES = [10, 151, 9, 50, 280, 205, 425];
  const N_LANDMARKS = 478;

  const video = document.getElementById('video');
  const glCanvas = document.getElementById('canvas');
  const fallbackCanvas = document.getElementById('canvas2d');

  let makeup = { lip: null, blush: null, eyeshadow: null };
  let compare = false;
  let landmarker = null;
  let lastVideoTime = -1;
  let lastFaceAt = 0;
  let hasFace = false;
  let status = null;
  let frameNo = 0;
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

  // ── Color helpers ────────────────────────────────────────────────────
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function clamp01(v) { return clamp(Number(v) || 0, 0, 1); }
  function hexToRgb(hex) {
    const h = String(hex || '').replace('#', '');
    const n = parseInt(h.length === 3 ? h.split('').map((c) => c + c).join('') : h, 16) || 0;
    return [((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255];
  }
  function toLin(c) { return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4); }
  function rgbToLab(r, g, b) {
    const R = toLin(r), G = toLin(g), B = toLin(b);
    const x = (0.4124 * R + 0.3576 * G + 0.1805 * B) / 0.95047;
    const y = 0.2126 * R + 0.7152 * G + 0.0722 * B;
    const z = (0.0193 * R + 0.1192 * G + 0.9505 * B) / 1.08883;
    const f = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
    const fx = f(x), fy = f(y), fz = f(z);
    return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
  }
  function rgba255(rgb, a) {
    return 'rgba(' + Math.round(rgb[0] * 255) + ',' + Math.round(rgb[1] * 255) + ',' + Math.round(rgb[2] * 255) + ',' + a + ')';
  }

  // ── One Euro filter over all landmarks (no per-frame allocation) ─────
  const sx = new Float32Array(N_LANDMARKS);
  const sy = new Float32Array(N_LANDMARKS);
  const dvx = new Float32Array(N_LANDMARKS);
  const dvy = new Float32Array(N_LANDMARKS);
  let filterReady = false;
  let filterT = 0;
  function euroAlpha(cutoff, dt) { const tau = 1 / (2 * Math.PI * cutoff); return 1 / (1 + tau / dt); }
  function filterLandmarks(face, t) {
    const n = Math.min(N_LANDMARKS, face.length);
    if (!filterReady || t - filterT > 0.5) {
      for (let i = 0; i < n; i++) { sx[i] = face[i].x; sy[i] = face[i].y; dvx[i] = 0; dvy[i] = 0; }
      filterReady = true; filterT = t;
      return;
    }
    const dt = Math.max(0.001, t - filterT);
    filterT = t;
    const ad = euroAlpha(TUNING.smoothDCutoff, dt);
    for (let i = 0; i < n; i++) {
      const x = face[i].x, y = face[i].y;
      dvx[i] += ad * ((x - sx[i]) / dt - dvx[i]);
      dvy[i] += ad * ((y - sy[i]) / dt - dvy[i]);
      const speed = Math.sqrt(dvx[i] * dvx[i] + dvy[i] * dvy[i]);
      const a = euroAlpha(TUNING.smoothMinCutoff + TUNING.smoothBeta * speed, dt);
      sx[i] += a * (x - sx[i]);
      sy[i] += a * (y - sy[i]);
    }
  }

  // ── Geometry ─────────────────────────────────────────────────────────
  function P(i, w, h) { return [sx[i] * w, sy[i] * h]; }
  function pts(list, w, h) { return list.map((i) => P(i, w, h)); }
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
  function faceWidth(w, h) { return dist(P(FACE_EDGES[0], w, h), P(FACE_EDGES[1], w, h)); }
  function cheekVisibility(w, h) {
    const nose = P(NOSE_TIP, w, h);
    const dl = dist(nose, P(FACE_EDGES[0], w, h));
    const dr = dist(nose, P(FACE_EDGES[1], w, h));
    const ratio = dl / Math.max(1e-6, dl + dr);
    return [Math.pow(clamp(ratio * 2, 0, 1), 1.5), Math.pow(clamp((1 - ratio) * 2, 0, 1), 1.5)];
  }
  function shadowShape(eye, w, h) {
    const lid = pts(eye.lid, w, h);
    const crease = eye.brow.map((bi, j) => {
      const li = Math.round((j * (lid.length - 1)) / (eye.brow.length - 1));
      return lerp(lid[li], P(bi, w, h), TUNING.shadowCrease);
    });
    return { shape: lid.concat(crease.slice().reverse()), lidC: centroid(lid), creaseC: centroid(crease) };
  }

  // ── Masks (shared by WebGL and 2D fallback) ──────────────────────────
  const crisp = document.createElement('canvas');
  const soft = document.createElement('canvas');
  const crispCtx = crisp.getContext('2d');
  const softCtx = soft.getContext('2d');

  function drawCrispMask() {
    const c = crispCtx, w = crisp.width, h = crisp.height;
    c.globalCompositeOperation = 'source-over';
    c.fillStyle = '#000';
    c.fillRect(0, 0, w, h);
    if (!hasFace) return;
    c.globalCompositeOperation = 'lighter';
    if (makeup.lip) {
      c.fillStyle = 'rgb(255,0,0)';
      c.beginPath();
      splinePath(c, pts(LIPS_OUTER, w, h));
      splinePath(c, pts(LIPS_INNER, w, h));
      c.fill('evenodd');
    }
    if (makeup.eyeshadow) {
      c.fillStyle = 'rgb(0,255,0)';
      c.strokeStyle = 'rgb(0,255,0)';
      c.lineWidth = Math.max(1, faceWidth(w, h) * 0.012);
      for (const eye of EYES) {
        c.beginPath();
        splinePath(c, pts(eye.contour, w, h));
        c.fill();
        c.stroke();
      }
    }
  }

  function drawSoftMask() {
    const c = softCtx, w = soft.width, h = soft.height;
    c.globalCompositeOperation = 'source-over';
    c.fillStyle = '#000';
    c.fillRect(0, 0, w, h);
    if (!hasFace) return;
    c.globalCompositeOperation = 'lighter';
    const faceW = faceWidth(w, h);
    if (makeup.blush) {
      const vis = cheekVisibility(w, h);
      CHEEKS.forEach((cheek, k) => {
        const inner = P(cheek.inner, w, h), outer = P(cheek.outer, w, h);
        const center = lerp(lerp(inner, outer, 0.4), P(cheek.low, w, h), 0.25);
        const v = vis[k];
        if (v < 0.02) return;
        c.save();
        c.translate(center[0], center[1]);
        c.rotate(Math.atan2(outer[1] - inner[1], outer[0] - inner[0]));
        c.scale(faceW * TUNING.blushSize[0] * (0.6 + 0.4 * v), faceW * TUNING.blushSize[1]);
        const g = c.createRadialGradient(0, 0, 0, 0, 0, 1);
        g.addColorStop(0, 'rgba(255,0,0,' + v + ')');
        g.addColorStop(0.4, 'rgba(255,0,0,' + 0.75 * v + ')');
        g.addColorStop(0.75, 'rgba(255,0,0,' + 0.3 * v + ')');
        g.addColorStop(1, 'rgba(255,0,0,0)');
        c.fillStyle = g;
        c.beginPath(); c.arc(0, 0, 1, 0, Math.PI * 2); c.fill();
        c.restore();
      });
    }
    if (makeup.eyeshadow) {
      for (const eye of EYES) {
        const s = shadowShape(eye, w, h);
        const g = c.createLinearGradient(s.lidC[0], s.lidC[1], s.creaseC[0], s.creaseC[1]);
        g.addColorStop(0, 'rgb(0,255,0)');
        g.addColorStop(0.55, 'rgb(0,170,0)');
        g.addColorStop(1, 'rgb(0,40,0)');
        c.fillStyle = g;
        c.beginPath(); splinePath(c, s.shape); c.fill();
      }
    }
  }

  // ── Scene statistics for lighting adaptation ─────────────────────────
  const stats = document.createElement('canvas');
  const statsCtx = stats.getContext('2d', { willReadFrequently: true });
  let lipMeanL = 50;
  let skinMeanL = TUNING.lightRefL;
  function sampleStats(W, H) {
    const sw = 96, sh = Math.max(1, Math.round((96 * H) / W));
    if (stats.width !== sw || stats.height !== sh) { stats.width = sw; stats.height = sh; }
    statsCtx.drawImage(video, 0, 0, sw, sh);
    const data = statsCtx.getImageData(0, 0, sw, sh).data;
    const L = (nx, ny) => {
      const x = clamp(Math.round(nx * sw), 0, sw - 1), y = clamp(Math.round(ny * sh), 0, sh - 1);
      const k = (y * sw + x) * 4;
      return rgbToLab(data[k] / 255, data[k + 1] / 255, data[k + 2] / 255)[0];
    };
    let lip = 0;
    for (let i = 0; i < LIPS_OUTER.length; i++) {
      const a = LIPS_OUTER[i], b = LIPS_INNER[i];
      lip += L((sx[a] + sx[b]) / 2, (sy[a] + sy[b]) / 2);
    }
    lip /= LIPS_OUTER.length;
    let skin = 0;
    for (const i of SKIN_SAMPLES) skin += L(sx[i], sy[i]);
    skin /= SKIN_SAMPLES.length;
    lipMeanL = lipMeanL * 0.6 + lip * 0.4;
    skinMeanL = skinMeanL * 0.6 + skin * 0.4;
  }
  function lightGain() {
    return clamp(skinMeanL / TUNING.lightRefL, TUNING.lightGainRange[0], TUNING.lightGainRange[1]);
  }
  function zoneAmount(zone, range) { return zone ? range[0] + range[1] * clamp01(zone.intensity) : 0; }

  // ── WebGL renderer ───────────────────────────────────────────────────
  const VERT = [
    'attribute vec2 aPos;',
    'varying vec2 vUv;',
    'void main() { vUv = vec2(aPos.x * 0.5 + 0.5, 0.5 - aPos.y * 0.5); gl_Position = vec4(aPos, 0.0, 1.0); }',
  ].join(NL);

  const FRAG = [
    '#ifdef GL_FRAGMENT_PRECISION_HIGH',
    'precision highp float;',
    '#else',
    'precision mediump float;',
    '#endif',
    'varying vec2 vUv;',
    'uniform sampler2D uVideo; uniform sampler2D uCrisp; uniform sampler2D uSoft;',
    'uniform vec2 uCrispTexel; uniform vec2 uSoftTexel;',
    'uniform float uCompare; uniform float uTime;',
    'uniform vec3 uLipLab; uniform float uLipAmt; uniform float uLipMeanL;',
    'uniform float uGloss; uniform float uMatte; uniform float uLipDetail; uniform float uLipChroma; uniform float uGlossStrength;',
    'uniform vec3 uBlushColor; uniform float uBlushAmt;',
    'uniform vec3 uEyeColor; uniform float uEyeAmt; uniform float uShimmer;',
    'const mat3 TO_XYZ = mat3(0.4124, 0.2126, 0.0193, 0.3576, 0.7152, 0.1192, 0.1805, 0.0722, 0.9505);',
    'const mat3 TO_RGB = mat3(3.2406, -0.9689, 0.0557, -1.5372, 1.8758, -0.2040, -0.4986, 0.0415, 1.0570);',
    'const vec3 WHITE = vec3(0.95047, 1.0, 1.08883);',
    'vec3 toLin(vec3 c) { return mix(c / 12.92, pow((c + 0.055) / 1.055, vec3(2.4)), step(0.04045, c)); }',
    'vec3 toSrgb(vec3 c) { c = clamp(c, 0.0, 1.0); return mix(c * 12.92, 1.055 * pow(c, vec3(1.0 / 2.4)) - 0.055, step(0.0031308, c)); }',
    'vec3 rgb2lab(vec3 c) {',
    '  vec3 xyz = (TO_XYZ * toLin(c)) / WHITE;',
    '  vec3 f = mix(7.787 * xyz + 16.0 / 116.0, pow(max(xyz, vec3(1e-6)), vec3(1.0 / 3.0)), step(0.008856, xyz));',
    '  return vec3(116.0 * f.y - 16.0, 500.0 * (f.x - f.y), 200.0 * (f.y - f.z));',
    '}',
    'vec3 lab2rgb(vec3 lab) {',
    '  float fy = (lab.x + 16.0) / 116.0;',
    '  vec3 f = vec3(fy + lab.y / 500.0, fy, fy - lab.z / 200.0);',
    '  vec3 f3 = f * f * f;',
    '  vec3 xyz = mix((f - 16.0 / 116.0) / 7.787, f3, step(0.008856, f3)) * WHITE;',
    '  return toSrgb(TO_RGB * xyz);',
    '}',
    'vec3 softLight(vec3 a, vec3 b) { return (1.0 - 2.0 * b) * a * a + 2.0 * b * a; }',
    'float hash(vec2 p) { return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }',
    'vec4 tap5(sampler2D t, vec2 uv, vec2 d) {',
    '  return (texture2D(t, uv) * 2.0 + texture2D(t, uv + vec2(d.x, 0.0)) + texture2D(t, uv - vec2(d.x, 0.0))',
    '    + texture2D(t, uv + vec2(0.0, d.y)) + texture2D(t, uv - vec2(0.0, d.y))) / 6.0;',
    '}',
    'void main() {',
    '  vec2 uv = vec2(1.0 - vUv.x, vUv.y);',
    '  vec3 col = texture2D(uVideo, uv).rgb;',
    // In comparison mode both sides originate from this same video texture; only the left half skips AR.
    '  if (uCompare > 0.5 && vUv.x < 0.5) { gl_FragColor = vec4(col, 1.0); return; }',
    '  vec4 cm = tap5(uCrisp, uv, uCrispTexel);',
    '  vec4 sm = tap5(uSoft, uv, uSoftTexel * 1.5);',
    '  float em = sm.g * (1.0 - smoothstep(0.1, 0.6, cm.g)) * uEyeAmt;',
    '  if (em > 0.002) {',
    '    vec3 shaded = mix(col * uEyeColor, softLight(col, uEyeColor), 0.45);',
    '    float sparkle = step(0.985, hash(floor(gl_FragCoord.xy * 0.5) + floor(uTime * 6.0))) * uShimmer;',
    '    shaded += vec3(sparkle + uShimmer * 0.12);',
    '    col = mix(col, shaded, em);',
    '  }',
    '  float bm = sm.r * uBlushAmt;',
    '  if (bm > 0.002) {',
    '    vec3 tinted = mix(softLight(col, uBlushColor), col * uBlushColor, 0.35);',
    '    col = mix(col, tinted, bm);',
    '  }',
    '  float lm = cm.r * uLipAmt;',
    '  if (lm > 0.002) {',
    '    vec3 lab = rgb2lab(col);',
    // Feathered edge pixels are mostly skin (brighter than lips): damp their detail and gloss to avoid a light halo.
    '    float core = smoothstep(0.55, 0.95, cm.r);',
    '    float detail = clamp(lab.x - uLipMeanL, -22.0, 16.0) * mix(0.3, 1.0, core);',
    '    float L = uLipLab.x + detail * uLipDetail - max(detail - 4.0, 0.0) * uMatte * 0.6;',
    '    vec2 ab = mix(lab.yz, uLipLab.yz, uLipChroma);',
    '    vec3 lip = lab2rgb(vec3(clamp(L, 0.0, 100.0), ab));',
    '    lip += vec3(smoothstep(6.0, 16.0, detail) * uGloss * uGlossStrength * core);',
    '    col = mix(col, lip, lm);',
    '  }',
    '  gl_FragColor = vec4(col, 1.0);',
    '}',
  ].join(NL);

  function createGLRenderer() {
    const gl = glCanvas.getContext('webgl', { alpha: false, antialias: false, premultipliedAlpha: false });
    if (!gl) return null;
    function shader(type, src) {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) || 'shader');
      return s;
    }
    const prog = gl.createProgram();
    gl.attachShader(prog, shader(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, shader(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog) || 'link');
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
    const aPos = gl.getAttribLocation(prog, 'aPos');
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);

    const textures = [0, 1, 2].map((unit) => {
      const t = gl.createTexture();
      gl.activeTexture(gl.TEXTURE0 + unit);
      gl.bindTexture(gl.TEXTURE_2D, t);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      return t;
    });
    const names = ['uVideo', 'uCrisp', 'uSoft', 'uCrispTexel', 'uSoftTexel', 'uCompare', 'uTime', 'uLipLab', 'uLipAmt',
      'uLipMeanL', 'uGloss', 'uMatte', 'uLipDetail', 'uLipChroma', 'uGlossStrength', 'uBlushColor', 'uBlushAmt',
      'uEyeColor', 'uEyeAmt', 'uShimmer'];
    const u = {};
    for (const n of names) u[n] = gl.getUniformLocation(prog, n);
    gl.uniform1i(u.uVideo, 0);
    gl.uniform1i(u.uCrisp, 1);
    gl.uniform1i(u.uSoft, 2);

    let lost = false;
    glCanvas.addEventListener('webglcontextlost', (e) => { e.preventDefault(); lost = true; });

    function upload(unit, source) {
      gl.activeTexture(gl.TEXTURE0 + unit);
      gl.bindTexture(gl.TEXTURE_2D, textures[unit]);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, source);
    }

    return {
      name: 'webgl',
      get lost() { return lost; },
      render(W, H, now) {
        if (glCanvas.width !== W || glCanvas.height !== H) { glCanvas.width = W; glCanvas.height = H; }
        gl.viewport(0, 0, W, H);
        upload(0, video);
        const active = hasFace;
        if (active) {
          drawCrispMask();
          drawSoftMask();
          upload(1, crisp);
          upload(2, soft);
        }
        const gain = lightGain();
        const lip = active ? makeup.lip : null;
        const blush = active ? makeup.blush : null;
        const eye = active ? makeup.eyeshadow : null;
        const lipTex = TEXTURES[lip && lip.texture] || TEXTURES.matte;
        const lipLab = lip ? rgbToLab.apply(null, hexToRgb(lip.hex)) : [0, 0, 0];
        const blushRgb = blush ? hexToRgb(blush.hex) : [1, 1, 1];
        const eyeRgb = eye ? hexToRgb(eye.hex) : [1, 1, 1];

        gl.uniform2f(u.uCrispTexel, 1 / crisp.width, 1 / crisp.height);
        gl.uniform2f(u.uSoftTexel, 1 / soft.width, 1 / soft.height);
        gl.uniform1f(u.uCompare, compare ? 1 : 0);
        gl.uniform1f(u.uTime, now / 1000);
        gl.uniform3f(u.uLipLab, lipLab[0] * gain, lipLab[1], lipLab[2]);
        gl.uniform1f(u.uLipAmt, zoneAmount(lip, TUNING.lipAmount) * (lip && lip.texture === 'sheer' ? TUNING.sheerFactor : 1));
        gl.uniform1f(u.uLipMeanL, lipMeanL);
        gl.uniform1f(u.uGloss, lipTex.gloss);
        gl.uniform1f(u.uMatte, lipTex.matte);
        gl.uniform1f(u.uLipDetail, TUNING.lipDetail);
        gl.uniform1f(u.uLipChroma, TUNING.lipChroma);
        gl.uniform1f(u.uGlossStrength, TUNING.glossStrength);
        gl.uniform3f(u.uBlushColor, Math.min(1, blushRgb[0] * gain), Math.min(1, blushRgb[1] * gain), Math.min(1, blushRgb[2] * gain));
        gl.uniform1f(u.uBlushAmt, zoneAmount(blush, TUNING.blushAmount));
        gl.uniform3f(u.uEyeColor, Math.min(1, eyeRgb[0] * gain), Math.min(1, eyeRgb[1] * gain), Math.min(1, eyeRgb[2] * gain));
        gl.uniform1f(u.uEyeAmt, zoneAmount(eye, TUNING.eyeAmount));
        gl.uniform1f(u.uShimmer, eye && eye.texture === 'shimmer' ? TUNING.shimmerStrength * clamp01(eye.intensity) : 0);
        gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      },
    };
  }

  // ── 2D fallback renderer ─────────────────────────────────────────────
  function create2DRenderer() {
    glCanvas.style.display = 'none';
    fallbackCanvas.style.display = 'block';
    const ctx = fallbackCanvas.getContext('2d');
    const fx = document.createElement('canvas');
    const fctx = fx.getContext('2d');
    return {
      name: '2d',
      lost: false,
      render(W, H) {
        if (fallbackCanvas.width !== W || fallbackCanvas.height !== H) { fallbackCanvas.width = W; fallbackCanvas.height = H; }
        const fw = Math.round(W / 2), fh = Math.round(H / 2);
        if (fx.width !== fw || fx.height !== fh) { fx.width = fw; fx.height = fh; }
        ctx.save();
        ctx.setTransform(-1, 0, 0, 1, W, 0);
        ctx.globalCompositeOperation = 'source-over';
        ctx.globalAlpha = 1;
        ctx.drawImage(video, 0, 0, W, H);
        if (hasFace) {
          paintColorLayer(fctx, fw, fh);
          ctx.globalCompositeOperation = 'multiply';
          if (compare) {
            ctx.save(); ctx.beginPath(); ctx.rect(W / 2, 0, W / 2, H); ctx.clip(); ctx.drawImage(fx, 0, 0, W, H); ctx.restore();
          } else ctx.drawImage(fx, 0, 0, W, H);
          ctx.globalCompositeOperation = 'source-over';
          ctx.globalAlpha = 0.35;
          ctx.drawImage(fx, 0, 0, W, H);
        }
        ctx.restore();
      },
    };
  }

  function paintColorLayer(c, w, h) {
    c.globalCompositeOperation = 'source-over';
    c.clearRect(0, 0, w, h);
    const faceW = faceWidth(w, h);
    const eye = makeup.eyeshadow;
    if (eye) {
      const rgb = hexToRgb(eye.hex), a = zoneAmount(eye, TUNING.eyeAmount);
      for (const e of EYES) {
        const s = shadowShape(e, w, h);
        const g = c.createLinearGradient(s.lidC[0], s.lidC[1], s.creaseC[0], s.creaseC[1]);
        g.addColorStop(0, rgba255(rgb, a));
        g.addColorStop(1, rgba255(rgb, a * 0.15));
        c.fillStyle = g;
        c.beginPath(); splinePath(c, s.shape); c.fill();
      }
    }
    const blush = makeup.blush;
    if (blush) {
      const rgb = hexToRgb(blush.hex), a = zoneAmount(blush, TUNING.blushAmount), vis = cheekVisibility(w, h);
      CHEEKS.forEach((cheek, k) => {
        const inner = P(cheek.inner, w, h), outer = P(cheek.outer, w, h);
        const center = lerp(lerp(inner, outer, 0.4), P(cheek.low, w, h), 0.25);
        c.save();
        c.translate(center[0], center[1]);
        c.rotate(Math.atan2(outer[1] - inner[1], outer[0] - inner[0]));
        c.scale(faceW * TUNING.blushSize[0] * (0.6 + 0.4 * vis[k]), faceW * TUNING.blushSize[1]);
        const g = c.createRadialGradient(0, 0, 0, 0, 0, 1);
        g.addColorStop(0, rgba255(rgb, a * vis[k]));
        g.addColorStop(1, rgba255(rgb, 0));
        c.fillStyle = g;
        c.beginPath(); c.arc(0, 0, 1, 0, Math.PI * 2); c.fill();
        c.restore();
      });
    }
    const lip = makeup.lip;
    if (lip) {
      c.fillStyle = rgba255(hexToRgb(lip.hex), zoneAmount(lip, TUNING.lipAmount));
      c.beginPath();
      splinePath(c, pts(LIPS_OUTER, w, h));
      splinePath(c, pts(LIPS_INNER, w, h));
      c.fill('evenodd');
    }
  }

  // ── Main loop ────────────────────────────────────────────────────────
  function ensureMaskSize(W, H) {
    const cw = Math.round(W / 2), ch = Math.round(H / 2);
    if (crisp.width !== cw || crisp.height !== ch) { crisp.width = cw; crisp.height = ch; }
    const sw = Math.round(W / 4), sh = Math.round(H / 4);
    if (soft.width !== sw || soft.height !== sh) { soft.width = sw; soft.height = sh; }
  }

  function frame(now) {
    requestAnimationFrame(frame);
    if (video.readyState < 2) return;
    const W = video.videoWidth, H = video.videoHeight;
    if (!W || !H) return;
    ensureMaskSize(W, H);

    if (landmarker && video.currentTime !== lastVideoTime) {
      lastVideoTime = video.currentTime;
      try {
        const result = landmarker.detectForVideo(video, now);
        const face = result.faceLandmarks && result.faceLandmarks[0];
        if (face) {
          filterLandmarks(face, now / 1000);
          hasFace = true;
          lastFaceAt = now;
          setStatus('tracking', renderer && renderer.name);
        } else if (now - lastFaceAt > 700) {
          hasFace = false;
          filterReady = false;
          setStatus('no-face');
        }
      } catch (e) { /* skip frame */ }
    }

    if (hasFace && frameNo++ % TUNING.statsEveryNFrames === 0) {
      try { sampleStats(W, H); } catch (e) { /* stats are best-effort */ }
    }

    if (renderer && renderer.lost) renderer = create2DRenderer();
    try {
      renderer.render(W, H, now);
    } catch (e) {
      if (renderer.name === 'webgl') renderer = create2DRenderer();
    }
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

  async function start() {
    setStatus('loading');
    post({ type: 'hello' });
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setStatus('unavailable', 'getUserMedia not supported');
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
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

    try { renderer = createGLRenderer(); } catch (e) { renderer = null; }
    if (!renderer) renderer = create2DRenderer();
    requestAnimationFrame(frame);

    try {
      const vision = await import('https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@' + VERSION + '/vision_bundle.mjs');
      const files = await vision.FilesetResolver.forVisionTasks('https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@' + VERSION + '/wasm');
      try { landmarker = await createLandmarker(vision, files, 'GPU'); }
      catch (e) { landmarker = await createLandmarker(vision, files, 'CPU'); }
    } catch (e) {
      setStatus('unavailable', 'model: ' + String(e && e.message));
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
