import { createPreprocessor, detectRegions, inputCrop } from './preprocessing.mjs';
import { createJpegRoundTrip } from './jpeg.mjs';
import { CaptureGate, previewFace } from './gate.mjs';
import { validateModelManifest, decodeGrade, meanSkinType } from './model-contract.mjs';

const FACE_OVAL = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109];
const CHUNK_SIZE = 48 * 1024, MAX_PREVIEW_CHARS = 4 * 1024 * 1024;
const post = message => window.ReactNativeWebView?.postMessage(JSON.stringify(message));
const elapsed = since => performance.now() - since;
const sleepFrame = () => new Promise(resolve => requestAnimationFrame(resolve));
const parts = {
  pore: [['pore_grade_cheek_image_left', 4], ['pore_grade_cheek_image_right', 5]],
  pigmentation: [['pigmentation_grade_forehead', 0], ['pigmentation_grade_cheek_image_left', 4], ['pigmentation_grade_cheek_image_right', 5]],
  wrinkle: [['wrinkle_grade_forehead', 0], ['wrinkle_grade_glabella', 1], ['wrinkle_grade_eye_image_left', 2], ['wrinkle_grade_eye_image_right', 3]],
  skinType: [['forehead', 0], ['leftCheek', 4], ['rightCheek', 5]],
};
function script(url) {
  return new Promise((resolve, reject) => {
    const element = document.createElement('script'); element.src = url;
    element.onload = resolve; element.onerror = () => reject(new Error('model'));
    document.head.appendChild(element);
  });
}

export async function boot(config) {
  const startupAt = performance.now(), base = config.assetsUrl;
  const video = document.querySelector('video'), canvas = document.querySelector('canvas');
  const captureButton = document.querySelector('#capture');
  let stopped = false, stream, tracker, cv, tensor, manifest, startupMs, ort, cache;
  const abort = new AbortController(), cacheHits = new Set();
  const stopCamera = () => { stream?.getTracks().forEach(track => track.stop()); tracker?.close(); tracker = null; video.srcObject = null; };
  const cleanup = () => {
    stopped = true; abort.abort(); stopCamera(); canvas.width = canvas.height = 0;
    captureButton.disabled = true; captureButton.onclick = null;
  };
  window.addEventListener('pagehide', cleanup);
  document.addEventListener('visibilitychange', () => { if (document.hidden) cleanup(); });
  const check = () => { if (stopped) throw new Error('cancelled'); };
  const fetchBytes = async name => {
    const response = await fetch(base + name, { signal: abort.signal });
    if (!response.ok) throw new Error('model');
    return new Uint8Array(await response.arrayBuffer());
  };
  const asset = async name => {
    if (!Object.hasOwn(manifest.assets, name)) throw new Error('model');
    const url = base + manifest.bundleVersion + '/' + name;
    const cached = name.endsWith('.onnx') && cache ? await cache.match(url).catch(() => null) : null;
    const bytes = cached ? new Uint8Array(await cached.arrayBuffer()) : await fetchBytes(manifest.bundleVersion + '/' + name);
    check();
    const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
    if (Array.from(hash, b => b.toString(16).padStart(2, '0')).join('') !== manifest.assets[name]) {
      if (cached) await cache.delete(url); throw new Error('model');
    }
    check();
    if (cached) cacheHits.add(name);
    else if (name.endsWith('.onnx') && cache) await cache.put(url, new Response(bytes)).catch(() => {});
    return bytes;
  };
  const imageFromBytes = async bytes => {
    const image = new Image(), url = URL.createObjectURL(new Blob([bytes]));
    try {
      await new Promise((resolve, reject) => { image.onload = resolve; image.onerror = reject; image.src = url; });
      const temporary = document.createElement('canvas'); temporary.width = image.width; temporary.height = image.height;
      temporary.getContext('2d', { willReadFrequently: true }).drawImage(image, 0, 0);
      return cv.imread(temporary);
    } finally { URL.revokeObjectURL(url); }
  };
  const run = async (session, values) => {
    const input = new ort.Tensor('float32', values, [1, 3, 256, 256]);
    let output;
    try { output = await session.run({ image: input }); return Float32Array.from(output.logits.data); }
    finally { input.dispose(); if (output) Object.values(output).forEach(value => value.dispose()); }
  };

  async function analyze(image, capturedAt, captureMs, alignmentMs) {
    const validationAt = performance.now();
    const fixtures = JSON.parse(new TextDecoder().decode(await asset('fixtures.json')));
    let jpegFixtureMaxError = 0;
    for (const fixture of fixtures) {
      check();
      const picture = await imageFromBytes(await asset(fixture.image));
      try {
        const actual = await tensor(picture, fixture.bbox);
        const bytes = await asset(fixture.tensor), expected = new Float32Array(bytes.buffer, bytes.byteOffset, bytes.byteLength / 4);
        let max = 0;
        for (let i = 0; i < actual.length; i++) max = Math.max(max, Math.abs(actual[i] - expected[i]));
        // TurboJPEG's browser build uses a different DCT than OpenCV. Preserve this measured difference explicitly.
        if (fixture.bbox) jpegFixtureMaxError = max;
        else if (max > fixture.maxAbsoluteError) throw new Error('model');
      } finally { picture.delete(); }
    }
    const validationMs = elapsed(validationAt), detectedAt = performance.now();
    cv.FS_createDataFile('/', 'face.xml', await asset('face.xml'), true, false, false);
    const detector = new cv.CascadeClassifier();
    let regions;
    try { if (!detector.load('face.xml')) throw new Error('model'); regions = detectRegions(cv, image, detector); }
    finally { detector.delete(); cv.FS_unlink('/face.xml'); }
    const detectionMs = elapsed(detectedAt), features = {}, models = [];
    let skinType;
    for (const model of manifest.models) {
      check(); post({ type: 'progress', indicator: model.indicator }); await sleepFrame();
      const downloadAt = performance.now(); let bytes = await asset(model.file);
      const downloadMs = elapsed(downloadAt), loadAt = performance.now();
      const session = await ort.InferenceSession.create(bytes, { executionProviders: ['wasm'], graphOptimizationLevel: 'all' });
      bytes = null;
      const loadMs = elapsed(loadAt), modelValidationAt = performance.now();
      try {
        const fixture = await asset(model.fixture);
        const actual = await run(session, new Float32Array(fixture.buffer, fixture.byteOffset, fixture.byteLength / 4));
        if (actual.length !== model.outputs || actual.some((v, i) => !Number.isFinite(v) || Math.abs(v - model.expectedLogits[i]) > 1e-4 + 1e-3 * Math.abs(model.expectedLogits[i]))) throw new Error('model');
        const modelValidationMs = elapsed(modelValidationAt);
        let preprocessingMs = 0, inferenceMs = 0;
        const typeLogits = [];
        for (const [key, region] of parts[model.indicator]) {
          check(); const preparedAt = performance.now();
          const input = await tensor(image, regions[region]);
          preprocessingMs += elapsed(preparedAt);
          const inferenceAt = performance.now(), logits = await run(session, input);
          inferenceMs += elapsed(inferenceAt);
          if (logits.length !== model.outputs || logits.some(v => !Number.isFinite(v))) throw new Error('model');
          if (model.indicator === 'skinType') typeLogits.push(logits);
          else features[key] = decodeGrade(logits[0], model.maxGrade);
        }
        if (model.indicator === 'skinType') skinType = meanSkinType(typeLogits);
        models.push({ indicator: model.indicator, sourceSha256: model.sourceSha256, sha256: model.sha256,
          downloadMs, cacheHit: cacheHits.has(model.file), loadMs, validationMs: modelValidationMs, preprocessingMs, inferenceMs });
      } finally { await session.release(); }
    }
    check();
    return { regions: regions.map(box => inputCrop(box, image.cols, image.rows)), result: { schema: 'skin-analysis-mobile-v3', features, skinType,
      roiMethod: 'opencv_haar_facebox_proportions_v1', validationStatus: 'experimental_unvalidated',
      preprocessing: 'skin-v3-embedded-enhancement',
      timing: { ...config.run, runtime: 'onnxruntime-web-1.30.0/wasm-cpu/threads=1',
        bundleVersion: manifest.bundleVersion, alignmentMs, captureMs, startupMs, jpegFixtureMaxError,
        imagePreparationMs: 0, validationMs, detectionMs, nativeMs: 0, totalMs: elapsed(capturedAt), memoryPssKb: null, models } } };
  }

  async function prepareAnalysis() {
    ort = await import(base + 'ort.wasm.min.mjs');
    check();
    await Promise.all([script(base + 'opencv.js'), script(base + 'jpeg.js')]);
    const cvModule = window.cv;
    if (cvModule instanceof Promise) cv = await cvModule;
    else { if (!cvModule.Mat) await new Promise(resolve => { cvModule.onRuntimeInitialized = resolve; }); cv = cvModule; }
    const jpeg = await window.libjpegturbowasm({ locateFile: name => base + name });
    tensor = createPreprocessor(cv, createJpegRoundTrip(jpeg));
    ort.env.wasm.numThreads = 1; ort.env.wasm.wasmPaths = base;
    manifest = JSON.parse(new TextDecoder().decode(await fetchBytes('manifest.json')));
    validateModelManifest(manifest);
    // Cache API availability/quota varies between WebViews. Cache misses remain explicit in timings.
    cache = window.caches ? await window.caches.open(`skin-web-models-${manifest.bundleVersion}`).catch(() => null) : null;
    check();
  }

  try {
    post({ type: 'camera', state: { guidance: 'openingCamera', progress: 0 } });
    try {
      const next = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 720 }, height: { ideal: 960 } }, audio: false });
      if (stopped) { next.getTracks().forEach(track => track.stop()); return; }
      stream = next; video.srcObject = stream; await video.play(); check();
    } catch (error) {
      cleanup();
      if (error?.message !== 'cancelled') post({ type: 'error', code: error?.name === 'NotAllowedError' ? 'permission' : 'camera' });
      return;
    }
    // Only face alignment is needed before capture; OpenCV/ONNX/JPEG load afterward.
    post({ type: 'camera', state: { guidance: 'loadingGuide', progress: 0 } });
    const visionRoot = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.1.1';
    const vision = await import(visionRoot + '/vision_bundle.mjs');
    const files = await vision.FilesetResolver.forVisionTasks(visionRoot + '/wasm');
    tracker = await vision.FaceLandmarker.createFromOptions(files, {
      baseOptions: { modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task', delegate: 'CPU' },
      runningMode: 'VIDEO', numFaces: 2, minFaceDetectionConfidence: .5, minTrackingConfidence: .5,
    });
    check();
    startupMs = elapsed(startupAt);
    const openedAt = performance.now(), gate = new CaptureGate(); gate.reset();
    let lastVideoTime = -1, capturing = false;
    async function capture() {
      // Manual and automatic capture share one operation; ignore double taps and late frames.
      if (stopped || capturing || video.readyState < 2 || !video.videoWidth || !video.videoHeight) return;
      capturing = true; captureButton.disabled = true;
      try {
        const capturedAt = performance.now();
        // Capture landmarks from the same video frame as the image, not a prior guide frame.
        let outline = null;
        try {
          const faces = tracker.detectForVideo(video, capturedAt).faceLandmarks;
          if (faces.length === 1) {
            const points = FACE_OVAL.map(index => faces[0][index]);
            if (points.every(p => p && Number.isFinite(p.x) && Number.isFinite(p.y) && p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1)) {
              outline = points.map(p => [p.x, p.y]);
            }
          }
        } catch { /* Numeric analysis can still complete without a preview. */ }
        canvas.width = video.videoWidth; canvas.height = video.videoHeight;
        canvas.getContext('2d', { willReadFrequently: true }).drawImage(video, 0, 0);
        const captureMs = elapsed(capturedAt);
        let image;
        try {
          stopCamera(); post({ type: 'captured' }); await sleepFrame();
          const preparationAt = performance.now();
          await prepareAnalysis();
          image = cv.imread(canvas);
          const imagePreparationMs = elapsed(preparationAt);
          const output = await analyze(image, capturedAt, captureMs, capturedAt - openedAt);
          output.result.timing.imagePreparationMs = imagePreparationMs;
          if (outline) try {
            const dataUrl = canvas.toDataURL('image/jpeg', .8);
            const data = dataUrl.startsWith('data:image/jpeg;base64,') ? dataUrl.slice(23) : '';
            if (data.length && data.length <= MAX_PREVIEW_CHARS) {
              const boxes = output.regions.map(([l, t, r, b]) => [l / canvas.width, t / canvas.height, r / canvas.width, b / canvas.height]);
              post({ type: 'preview-start', runId: config.run.runId, width: canvas.width, height: canvas.height, outline, boxes, length: data.length });
              for (let i = 0; i < data.length; i += CHUNK_SIZE) {
                check(); post({ type: 'preview-chunk', runId: config.run.runId, index: i / CHUNK_SIZE, data: data.slice(i, i + CHUNK_SIZE) });
              }
              post({ type: 'preview-end', runId: config.run.runId });
            }
          } catch { /* A preview failure must not replace a valid numeric result. */ }
          check();
          output.result.timing.totalMs = elapsed(capturedAt);
          post({ type: 'result', result: output.result });
        } finally { image?.delete(); cleanup(); }
      } catch (error) { cleanup(); if (error?.message !== 'cancelled') post({ type: 'error', code: error?.message === 'photo' ? 'photo' : 'model' }); }
    }
    captureButton.onclick = () => { void capture(); };
    captureButton.disabled = false;
    async function frame() {
      if (stopped || capturing) return;
      try {
        if (video.readyState < 2 || !video.videoWidth || !video.videoHeight || video.currentTime === lastVideoTime) { setTimeout(frame, 100); return; }
        lastVideoTime = video.currentTime;
        const now = performance.now(), result = tracker.detectForVideo(video, now);
        const bounds = video.getBoundingClientRect();
        const state = gate.update(result.faceLandmarks.map(points => previewFace(points, video.videoWidth, video.videoHeight, bounds.width, bounds.height)), now);
        post({ type: 'camera', state });
        if (state.progress < 1) { setTimeout(frame, 100); return; }
        await capture();
      } catch (error) { cleanup(); post({ type: 'error', code: error?.message === 'photo' ? 'photo' : 'model' }); }
    }
    frame();
  } catch (error) {
    cleanup();
    if (error?.message !== 'cancelled') post({ type: 'error', code: 'guide' });
  }
}
