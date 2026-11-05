// Camera/guidance only. No skin models, preprocessing, credentials or network upload.
import { CaptureGate, previewFace } from './gate.mjs';

const post = message => window.ReactNativeWebView?.postMessage(JSON.stringify(message));
const wait = () => new Promise(resolve => setTimeout(resolve, 0));
const MAX_BYTES = 10 * 1024 * 1024, CHUNK_CHARS = 48 * 1024;

export async function boot(config) {
  const video = document.querySelector('video'), canvas = document.querySelector('canvas');
  const button = document.querySelector('#capture');
  let stopped = false, capturing = false, stream, tracker;
  const stopCamera = () => {
    stream?.getTracks().forEach(track => track.stop());
    tracker?.close(); tracker = null; video.srcObject = null;
  };
  const cleanup = () => {
    stopped = true; stopCamera(); canvas.width = canvas.height = 0;
    button.disabled = true; button.onclick = null;
  };
  const check = () => { if (stopped) throw new Error('cancelled'); };
  const fail = error => {
    cleanup();
    if (error?.message !== 'cancelled') post({ type: 'error', code: error?.name === 'NotAllowedError' ? 'permission' : 'photo' });
  };
  window.addEventListener('pagehide', cleanup);
  document.addEventListener('visibilitychange', () => { if (document.hidden) cleanup(); });
  try {
    post({ type: 'camera', state: { guidance: 'loading', progress: 0 } });
    const base = 'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.1.1';
    const vision = await import(base + '/vision_bundle.mjs');
    const files = await vision.FilesetResolver.forVisionTasks(base + '/wasm');
    tracker = await vision.FaceLandmarker.createFromOptions(files, {
      baseOptions: { modelAssetPath: 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task', delegate: 'CPU' },
      runningMode: 'VIDEO', numFaces: 2, minFaceDetectionConfidence: .5, minTrackingConfidence: .5,
    });
    check();
    const next = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'user', width: { ideal: 720 }, height: { ideal: 960 } }, audio: false });
    if (stopped) { next.getTracks().forEach(track => track.stop()); return; }
    stream = next; video.srcObject = stream; await video.play(); check();
    const openedAt = performance.now(), gate = new CaptureGate(); gate.reset();
    let lastVideoTime = -1;
    async function capture() {
      if (stopped || capturing || video.readyState < 2 || !video.videoWidth || !video.videoHeight) return;
      capturing = true; button.disabled = true;
      try {
        const started = performance.now();
        canvas.width = video.videoWidth; canvas.height = video.videoHeight;
        canvas.getContext('2d').drawImage(video, 0, 0);
        stopCamera(); post({ type: 'captured' });
        const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', .95));
        check();
        if (!blob || !blob.size || blob.size > MAX_BYTES) throw new Error('photo');
        let encoded = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(String(reader.result).split(',')[1]);
          reader.onerror = reject; reader.readAsDataURL(blob);
        });
        check();
        const captureMs = performance.now() - started;
        const captureId = config.run.runId + ':jpeg';
        const chunkCount = Math.ceil(encoded.length / CHUNK_CHARS);
        post({ type: 'capture-start', captureId, mime: 'image/jpeg', byteLength: blob.size,
          chunkCount, captureMs, alignmentMs: started - openedAt });
        for (let index = 0; index < chunkCount; index++) {
          check(); post({ type: 'capture-chunk', captureId, index, data: encoded.slice(index * CHUNK_CHARS, (index + 1) * CHUNK_CHARS) });
          await wait();
        }
        check(); post({ type: 'capture-end', captureId });
        encoded = ''; cleanup();
      } catch (error) { fail(error); }
    }
    button.onclick = () => { void capture(); }; button.disabled = false;
    async function frame() {
      if (stopped || capturing) return;
      try {
        if (video.currentTime === lastVideoTime) { setTimeout(frame, 100); return; }
        lastVideoTime = video.currentTime;
        const now = performance.now(), result = tracker.detectForVideo(video, now);
        const bounds = video.getBoundingClientRect();
        const state = gate.update(result.faceLandmarks.map(points => previewFace(points, video.videoWidth, video.videoHeight, bounds.width, bounds.height)), now);
        post({ type: 'camera', state });
        if (state.progress >= 1) await capture();
        else setTimeout(frame, 100);
      } catch (error) { fail(error); }
    }
    void frame();
  } catch (error) { fail(error); }
}
