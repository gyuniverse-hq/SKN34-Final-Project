import AsyncStorage from '@react-native-async-storage/async-storage';
import { appendSkinTiming, clearSkinTimings, comparableSkinTimings, readSkinProfile, readSkinTimings, summarizeSkinTimings, validateSkinAnalysis } from '@/lib/skinProfile';
import { STORAGE_KEYS } from '@/lib/storage';
import { useSkinProfileStore } from '@/store/skinProfileStore';
import type { SkinAnalysisResult, SkinProfile, SkinTiming } from '@/types/skin';
import { createElement } from 'react';
import { act, create } from 'react-test-renderer';
import { useSkinAnalysis } from '@/hooks/useSkinAnalysis';
import { analyzeSkin } from '@/lib/skinAnalysis';
import * as skinRuntime from '@/lib/skinAnalysis';
import { uploadSkinPhoto } from '@/lib/skinServer';
import { skinWebHtml } from '@/lib/skinWebHtml';
import { summarizeSkinResult } from '@/lib/skinResult';
import { useSkinPreviewStore } from '@/store/skinPreviewStore';

jest.mock('@/lib/skinAnalysis', () => ({
  __esModule: true,
  analyzeSkin: jest.fn(), cancelSkinAnalysis: jest.fn(() => Promise.resolve()), onSkinProgress: jest.fn(),
  skinAnalysisUsesWebView: false, createSkinWebRun: jest.fn(),
}));

jest.mock('@/lib/skinServer', () => ({ ...jest.requireActual('@/lib/skinServer'), uploadSkinPhoto: jest.fn() }));

function timing(id = 'run'): SkinTiming {
  return { runId: id, processId: 'process', firstInProcess: true, device: 'Android test', androidVersion: '16',
    build: 'test:release', runtime: 'cpu', bundleVersion: 'bundle', alignmentMs: 1500, captureMs: 20,
    imagePreparationMs: 20, validationMs: 0, detectionMs: 40, nativeMs: 1000, totalMs: 1020, memoryPssKb: 200000,
    models: (['acne', 'pore', 'pigmentation', 'wrinkle'] as const).map(indicator => ({
      indicator, sha256: 'a'.repeat(64), sourceSha256: 'b'.repeat(64), loadMs: 10, validationMs: 0, preprocessingMs: 10, inferenceMs: 10,
    })) };
}
function analysis(): SkinAnalysisResult {
  return { schema: 'skin-analysis-mobile-v1', roiMethod: 'opencv_haar_facebox_proportions_v1',
    validationStatus: 'experimental_unvalidated', acneScore: .7, acneThreshold: .5,
    features: { acne: 1, pore_grade_cheek_image_left: 2, pore_grade_cheek_image_right: 3,
      pigmentation_grade_forehead: 1, pigmentation_grade_cheek_image_left: 2, pigmentation_grade_cheek_image_right: 3,
      wrinkle_grade_forehead: 1, wrinkle_grade_glabella: 2, wrinkle_grade_eye_image_left: 3, wrinkle_grade_eye_image_right: 4 }, timing: timing() };
}
function profile(): SkinProfile {
  return { version: 1, registeredAt: '2026-10-23T00:00:00Z', analysis: analysis(),
    questionnaire: { tightness: 0, oiliness: 'unknown', sensitivity: 2 } };
}

beforeEach(async () => {
  await clearSkinTimings();
  await AsyncStorage.clear();
  useSkinProfileStore.getState().reset();
  jest.clearAllMocks();
});

it.each([0, 1, 2, 3, 4, 5, 6])('labels grade %i at the good/care boundary without changing model values', grade => {
  const features = analysis().features;
  features.pore_grade_cheek_image_left = Math.min(grade, 5);
  features.pore_grade_cheek_image_right = 0;
  features.pigmentation_grade_forehead = 0;
  features.pigmentation_grade_cheek_image_left = Math.min(grade, 5);
  features.pigmentation_grade_cheek_image_right = 0;
  features.wrinkle_grade_forehead = 0;
  features.wrinkle_grade_glabella = 0;
  features.wrinkle_grade_eye_image_left = 0;
  features.wrinkle_grade_eye_image_right = grade;
  const original = { ...features };
  const summary = summarizeSkinResult(features);
  expect(summary.grades.map(row => row.status)).toEqual(Array(3).fill(grade <= 2 ? 'good' : 'care'));
  expect(summary.grades.map(row => row.grade)).toEqual([Math.min(grade, 5), Math.min(grade, 5), grade]);
  expect(features).toEqual(original);
});

it('uses the highest area grade and reports acne only as presence or absence', () => {
  const features = analysis().features;
  expect(summarizeSkinResult(features)).toEqual({ grades: [
    { indicator: 'pore', grade: 3, status: 'care' },
    { indicator: 'pigmentation', grade: 3, status: 'care' },
    { indicator: 'wrinkle', grade: 4, status: 'care' },
  ], acneDetected: true });
  features.acne = 0;
  expect(summarizeSkinResult(features).acneDetected).toBe(false);
});

it('persists all 10 areas and unknown answers, and restores after a new store session', async () => {
  const input = profile();
  await useSkinProfileStore.getState().save(input);
  useSkinProfileStore.getState().reset();
  await useSkinProfileStore.getState().hydrate();
  expect(useSkinProfileStore.getState().profile).toEqual(input);
  expect(Object.keys((await readSkinProfile())!.analysis.features)).toHaveLength(10);
  expect(await AsyncStorage.getItem(STORAGE_KEYS.skinProfile)).not.toMatch(/imageUri|base64|jpeg|data:image/);
});

it('keeps the existing registration when a replacement write fails', async () => {
  const original = profile();
  await useSkinProfileStore.getState().save(original);
  jest.mocked(AsyncStorage.setItem).mockRejectedValueOnce(new Error('disk full'));
  await expect(useSkinProfileStore.getState().save({ ...original, registeredAt: '2026-10-24T00:00:00Z' })).rejects.toThrow('disk full');
  expect(useSkinProfileStore.getState().profile).toEqual(original);
  expect(await readSkinProfile()).toEqual(original);
});

it('does not register missing, invalid, or contradictory model outputs', () => {
  const missing = analysis();
  delete (missing.features as Partial<typeof missing.features>).wrinkle_grade_forehead;
  expect(() => validateSkinAnalysis(missing)).toThrow();
  const invalid = analysis();
  invalid.features.pore_grade_cheek_image_left = 6;
  expect(() => validateSkinAnalysis(invalid)).toThrow();
  const contradictory = analysis();
  contradictory.features.acne = 0;
  expect(() => validateSkinAnalysis(contradictory)).toThrow();
});

it('serializes concurrent timing writes and deduplicates registration retries', async () => {
  await Promise.all([appendSkinTiming(timing('one')), appendSkinTiming(timing('two')), appendSkinTiming(timing('one'))]);
  expect((await readSkinTimings()).map(row => row.runId)).toEqual(['two', 'one']);
  await clearSkinTimings();
  expect(await readSkinTimings()).toEqual([]);
});

it('does not mix debug builds or different model bundles into a release comparison', () => {
  const old = { ...timing('old'), build: 'test:debug' };
  const other = { ...timing('other'), bundleVersion: 'older' };
  const current = timing('current');
  expect(comparableSkinTimings([old, other, current])).toEqual([current]);
  expect(summarizeSkinTimings([timing('one'), { ...timing('two'), totalMs: 2020 }])).toEqual({
    count: 2, min: 1020, max: 2020, median: 1520,
  });
});

it('requires all answers, preserves them on a failed write, then completes after retry', async () => {
  let flow!: ReturnType<typeof useSkinAnalysis>;
  function Harness() { flow = useSkinAnalysis(); return null; }
  let renderer!: ReturnType<typeof create>;
  jest.mocked(analyzeSkin).mockResolvedValue(analysis());
  await act(async () => { renderer = create(createElement(Harness)); });
  try {
    await act(async () => { await flow.start(); });
    await act(async () => { flow.onCapture({ guidance: 'capturing', progress: 1, captureId: 'private-id' }); });
    expect(flow.phase).toBe('survey');
    await act(async () => { await flow.finish(); });
    expect(flow.phase).toBe('survey');
    expect(useSkinProfileStore.getState().profile).toBeNull();
    await act(async () => { flow.setAnswers({ tightness: 0, oiliness: 'unknown', sensitivity: 2 }); });
    jest.mocked(AsyncStorage.setItem).mockRejectedValueOnce(new Error('disk full'));
    await act(async () => { await flow.finish(); });
    expect(flow.phase).toBe('survey');
    expect(flow.error).toBe('storage');
    expect(flow.answers.oiliness).toBe('unknown');
    expect(useSkinProfileStore.getState().profile).toBeNull();
    await act(async () => { await flow.finish(); });
    expect(flow.phase).toBe('done');
    expect(useSkinProfileStore.getState().profile?.questionnaire).toEqual(flow.answers);
    expect(useSkinProfileStore.getState().profile?.analysis).toEqual(flow.result);
    const saved = await readSkinProfile();
    await act(async () => { flow.cancel(); });
    expect(flow.result).toBeUndefined();
    expect(await readSkinProfile()).toEqual(saved);
    await act(async () => { await flow.start(); });
    expect(flow.phase).toBe('camera');
    expect(flow.answers).toEqual({});
    expect(useSkinProfileStore.getState().profile).toEqual(saved);
  } finally { await act(async () => { renderer.unmount(); }); }
});

it('ignores a late native result after cancellation', async () => {
  let flow!: ReturnType<typeof useSkinAnalysis>;
  let resolveResult!: (value: SkinAnalysisResult) => void;
  jest.mocked(analyzeSkin).mockReturnValue(new Promise(resolve => { resolveResult = resolve; }));
  function Harness() { flow = useSkinAnalysis(); return null; }
  let renderer!: ReturnType<typeof create>;
  await act(async () => { renderer = create(createElement(Harness)); });
  try {
    await act(async () => { await flow.start(); });
    await act(async () => { flow.onCapture({ guidance: 'capturing', progress: 1, captureId: 'private-id' }); });
    expect(flow.phase).toBe('analysis');
    await act(async () => { flow.cancel(); });
    await act(async () => { resolveResult(analysis()); });
    expect(flow.phase).toBe('ready');
    expect(useSkinProfileStore.getState().profile).toBeNull();
    expect(await readSkinTimings()).toEqual([]);
  } finally { await act(async () => { renderer.unmount(); }); }
});

it('accepts WebView camera results without native inference and ignores events from a cancelled run', async () => {
  const property = jest.replaceProperty(skinRuntime, 'skinAnalysisUsesWebView', true);
  jest.mocked(skinRuntime.createSkinWebRun).mockReturnValue({ assetsUrl: 'http://localhost:8081/skin-runtime/',
    run: { runId: 'web-run', processId: 'js-session', firstInProcess: true, device: 'test', androidVersion: 'android 36', build: 'expo-go' } });
  let flow!: ReturnType<typeof useSkinAnalysis>;
  function Harness() { flow = useSkinAnalysis(); return null; }
  let renderer!: ReturnType<typeof create>;
  await act(async () => { renderer = create(createElement(Harness)); });
  try {
    await act(async () => { await flow.start(); });
    expect(flow.webRun?.run.runId).toBe('web-run');
    await act(async () => { flow.onWebEvent({ type: 'captured' }); });
    expect(flow.phase).toBe('analysis');
    const late = flow.onWebEvent;
    await act(async () => { flow.cancel(); });
    await act(async () => { late({ type: 'result', result: analysis() }); });
    expect(flow.phase).toBe('ready');
    await act(async () => { await flow.start(); });
    await act(async () => { flow.onWebEvent({ type: 'captured' }); });
    const web = { ...analysis(), preprocessing: 'opencv4.12-turbojpeg95-wasm-v1' as const,
      timing: { ...timing('web-run'), runtime: 'wasm-cpu', memoryPssKb: null } };
    await act(async () => { flow.onWebEvent({ type: 'result', result: web }); });
    expect(flow.phase).toBe('survey');
    expect(analyzeSkin).not.toHaveBeenCalled();
    await act(async () => { flow.setAnswers({ tightness: 0, oiliness: 'unknown', sensitivity: 2 }); });
    await act(async () => { await flow.finish(); });
    expect(flow.phase).toBe('done');
    expect((await readSkinProfile())?.analysis.preprocessing).toBe(web.preprocessing);
    expect((await readSkinProfile())?.analysis.timing.memoryPssKb).toBeNull();
  } finally { await act(async () => { renderer.unmount(); }); property.restore(); }
});


it('ignores legacy photo events even if the old server mode is configured', async () => {
  const webProperty = jest.replaceProperty(skinRuntime, 'skinAnalysisUsesWebView', true);
  const oldMode = process.env.EXPO_PUBLIC_SKIN_ANALYSIS_MODE;
  process.env.EXPO_PUBLIC_SKIN_ANALYSIS_MODE = 'server';
  jest.mocked(skinRuntime.createSkinWebRun).mockReturnValue({ assetsUrl: 'http://localhost:8081/skin-runtime/',
    run: { runId: 'local', processId: 'session', firstInProcess: true, device: 'test', androidVersion: 'android', build: 'expo-go' } });
  let flow!: ReturnType<typeof useSkinAnalysis>;
  function Harness() { flow = useSkinAnalysis(); return null; }
  let renderer!: ReturnType<typeof create>;
  await act(async () => { renderer = create(createElement(Harness)); });
  try {
    await act(async () => { await flow.start(); });
    await act(async () => { flow.onWebEvent({ type: 'captured' }); });
    for (const event of [
      { type: 'capture-start', captureId: 'local:jpeg', mime: 'image/jpeg', byteLength: 3, chunkCount: 1 },
      { type: 'capture-chunk', captureId: 'local:jpeg', index: 0, data: '/9j/' },
      { type: 'capture-end', captureId: 'local:jpeg' },
    ]) await act(async () => { flow.onWebEvent(event as never); });
    expect(uploadSkinPhoto).not.toHaveBeenCalled();
    expect(flow.phase).toBe('analysis');
    await act(async () => { flow.onWebEvent({ type: 'result', result: { ...analysis(), timing: timing('local') } }); });
    expect(flow.phase).toBe('survey');
  } finally {
    await act(async () => { renderer.unmount(); }); webProperty.restore();
    if (oldMode === undefined) delete process.env.EXPO_PUBLIC_SKIN_ANALYSIS_MODE;
    else process.env.EXPO_PUBLIC_SKIN_ANALYSIS_MODE = oldMode;
  }
});

it('loads only the on-device WebView runtime even with a legacy server-mode configuration', () => {
  const config = { mode: 'server', assetsUrl: 'http://localhost:8081/skin-runtime/',
    run: { runId: 'local', processId: 'session', firstInProcess: true, device: 'test', androidVersion: 'android', build: 'expo-go' } };
  const html = skinWebHtml(config, 'Capture');
  expect(html).toContain("import(config.assetsUrl+'runtime.mjs')");
  expect(html).not.toContain('capture.mjs');
});

it('waits for camera readiness, times out a stalled startup, and permits a fresh retry', async () => {
  jest.useFakeTimers();
  const webProperty = jest.replaceProperty(skinRuntime, 'skinAnalysisUsesWebView', true);
  jest.mocked(skinRuntime.createSkinWebRun).mockReturnValue({ assetsUrl: 'http://localhost:8081/skin-runtime/',
    run: { runId: 'camera-run', processId: 'session', firstInProcess: true, device: 'test', androidVersion: 'android', build: 'expo-go' } });
  let flow!: ReturnType<typeof useSkinAnalysis>;
  function Harness() { flow = useSkinAnalysis(); return null; }
  let screen!: ReturnType<typeof create>;
  try {
    await act(async () => { screen = create(createElement(Harness)); });
    await act(async () => { await flow.start(); });
    expect(flow.camera.guidance).toBe('loading');
    await act(async () => { jest.advanceTimersByTime(60000); });
    expect(flow.phase).toBe('error');
    expect(flow.error).toBe('model');
    await act(async () => { flow.onWebEvent({ type: 'camera', state: { guidance: 'noFace', progress: 0 } }); });
    expect(flow.phase).toBe('error');
    await act(async () => { await flow.start(); });
    await act(async () => { flow.onWebEvent({ type: 'camera', state: { guidance: 'noFace', progress: 0 } }); });
    await act(async () => { jest.advanceTimersByTime(60000); });
    expect(flow.phase).toBe('camera');
    await act(async () => { flow.onWebEvent({ type: 'error', code: 'camera' }); });
    expect(flow.error).toBe('camera');
    await act(async () => { await flow.start(); });
    await act(async () => { flow.onWebEvent({ type: 'camera', state: { guidance: 'loadingGuide', progress: 0 } }); });
    await act(async () => { jest.advanceTimersByTime(60000); });
    expect(flow.phase).toBe('error');
    expect(flow.error).toBe('guide');
  } finally {
    if (screen) await act(async () => { screen.unmount(); });
    webProperty.restore(); jest.useRealTimers();
  }
});


it('retains a new photo only in temporary memory after saving and clears it on cancellation', async () => {
  const webProperty = jest.replaceProperty(skinRuntime, 'skinAnalysisUsesWebView', true);
  jest.mocked(skinRuntime.createSkinWebRun).mockReturnValue({ assetsUrl: 'http://localhost:8081/skin-runtime/',
    run: { runId: 'photo-run', processId: 'session', firstInProcess: true, device: 'test', androidVersion: 'android', build: 'expo-go' } });
  const outline = Array.from({ length: 36 }, (_, i) => [0.5 + .3 * Math.cos(i * Math.PI / 18), 0.5 + .3 * Math.sin(i * Math.PI / 18)] as [number, number]);
  const boxes = Array.from({ length: 6 }, () => [.1, .1, .5, .5] as [number, number, number, number]);
  let flow!: ReturnType<typeof useSkinAnalysis>;
  function Harness() { flow = useSkinAnalysis(); return null; }
  let renderer!: ReturnType<typeof create>;
  await act(async () => { renderer = create(createElement(Harness)); });
  try {
    await act(async () => { await flow.start(); });
    await act(async () => { flow.onWebEvent({ type: 'captured' }); });
    await act(async () => { flow.onWebEvent({ type: 'preview-start', runId: 'photo-run', width: 100, height: 120, outline, boxes, length: 4 }); });
    await act(async () => { flow.onWebEvent({ type: 'preview-chunk', runId: 'photo-run', index: 0, data: '/9j/' }); });
    await act(async () => { flow.onWebEvent({ type: 'preview-end', runId: 'photo-run' }); });
    expect(useSkinPreviewStore.getState().preview).toBeNull();
    await act(async () => { flow.onWebEvent({ type: 'result', result: { ...analysis(), timing: timing('photo-run') } }); });
    await act(async () => { flow.setAnswers({ tightness: 0, oiliness: 1, sensitivity: 2 }); });
    await act(async () => { await flow.finish(); });
    expect(useSkinPreviewStore.getState().preview?.jpeg).toBe('/9j/');
    expect(JSON.stringify(await AsyncStorage.multiGet(Object.values(STORAGE_KEYS)))).not.toContain('/9j/');
    await act(async () => { flow.cancel(); });
    expect(useSkinPreviewStore.getState().preview).toBeNull();
  } finally { await act(async () => { renderer.unmount(); }); webProperty.restore(); useSkinPreviewStore.getState().clear(); }
});


it('keeps a native preview out of the persisted analysis result', async () => {
  const outline = Array.from({ length: 36 }, (_, i) => [0.5 + .3 * Math.cos(i * Math.PI / 18), 0.5 + .3 * Math.sin(i * Math.PI / 18)] as [number, number]);
  const boxes = Array.from({ length: 6 }, () => [.1, .1, .5, .5] as [number, number, number, number]);
  jest.mocked(analyzeSkin).mockResolvedValue({ ...analysis(), preview: { width: 100, height: 120, outline, boxes, jpeg: '/9j/' } });
  let flow!: ReturnType<typeof useSkinAnalysis>;
  function Harness() { flow = useSkinAnalysis(); return null; }
  let renderer!: ReturnType<typeof create>;
  await act(async () => { renderer = create(createElement(Harness)); });
  try {
    await act(async () => { await flow.start(); });
    await act(async () => { flow.onCapture({ guidance: 'capturing', progress: 1, captureId: 'native' }); });
    expect(flow.phase).toBe('survey');
    expect(JSON.stringify(flow.result)).not.toContain('/9j/');
    await act(async () => { flow.setAnswers({ tightness: 0, oiliness: 1, sensitivity: 2 }); });
    await act(async () => { await flow.finish(); });
    expect(useSkinPreviewStore.getState().preview?.jpeg).toBe('/9j/');
    expect(JSON.stringify(await AsyncStorage.multiGet(Object.values(STORAGE_KEYS)))).not.toContain('/9j/');
  } finally { await act(async () => { renderer.unmount(); }); useSkinPreviewStore.getState().clear(); }
});
