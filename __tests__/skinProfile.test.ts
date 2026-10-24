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
import { TRUSTED_SKIN_API_ORIGIN } from '@/constants/skinServer';
import { fetch as expoFetch } from 'expo/fetch';

jest.mock('expo/fetch', () => ({ fetch: jest.fn() }));

jest.mock('@/lib/skinAnalysis', () => ({
  __esModule: true,
  analyzeSkin: jest.fn(), cancelSkinAnalysis: jest.fn(() => Promise.resolve()), onSkinProgress: jest.fn(),
  skinAnalysisServerMode: false, skinAnalysisUsesWebView: false, createSkinWebRun: jest.fn(),
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
      timing: { ...timing('web'), runtime: 'wasm-cpu', memoryPssKb: null } };
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


it('uploads a completed server capture only once and ignores the response after cancellation', async () => {
  const webProperty = jest.replaceProperty(skinRuntime, 'skinAnalysisUsesWebView', true);
  const serverProperty = jest.replaceProperty(skinRuntime, 'skinAnalysisServerMode', true);
  const previous = process.env.EXPO_PUBLIC_SKIN_API_URL;
  process.env.EXPO_PUBLIC_SKIN_API_URL = TRUSTED_SKIN_API_ORIGIN;
  jest.mocked(skinRuntime.createSkinWebRun).mockReturnValue({ mode: 'server', assetsUrl: 'http://localhost:8081/skin-runtime/',
    run: { runId: 'remote', processId: 'session', firstInProcess: true, device: 'test', androidVersion: 'android', build: 'expo-go' } });
  let resolveResult!: (result: SkinAnalysisResult) => void;
  jest.mocked(uploadSkinPhoto).mockReturnValue(new Promise(resolve => { resolveResult = resolve; }));
  let flow!: ReturnType<typeof useSkinAnalysis>;
  function Harness() { flow = useSkinAnalysis(); return null; }
  let renderer!: ReturnType<typeof create>;
  await act(async () => { renderer = create(createElement(Harness)); });
  try {
    await act(async () => { await flow.start(); });
    await act(async () => { flow.onWebEvent({ type: 'captured' }); });
    await act(async () => { flow.onWebEvent({ type: 'capture-start', captureId: 'remote:jpeg', mime: 'image/jpeg', byteLength: 3, chunkCount: 1, captureMs: 4, alignmentMs: 1500 }); });
    await act(async () => { flow.onWebEvent({ type: 'capture-chunk', captureId: 'remote:jpeg', index: 0, data: '/9j/' }); });
    await act(async () => { flow.onWebEvent({ type: 'capture-end', captureId: 'remote:jpeg' }); });
    await act(async () => { flow.onWebEvent({ type: 'capture-end', captureId: 'remote:jpeg' }); });
    expect(uploadSkinPhoto).toHaveBeenCalledTimes(1);
    const signal = jest.mocked(uploadSkinPhoto).mock.calls[0][2];
    await act(async () => { flow.cancel(); });
    expect(signal.aborted).toBe(true);
    await act(async () => { resolveResult(analysis()); });
    expect(flow.phase).toBe('ready'); expect(await readSkinTimings()).toEqual([]);
    expect(useSkinProfileStore.getState().profile).toBeNull();
  } finally {
    await act(async () => { renderer.unmount(); }); webProperty.restore(); serverProperty.restore();
    if (previous === undefined) delete process.env.EXPO_PUBLIC_SKIN_API_URL;
    else process.env.EXPO_PUBLIC_SKIN_API_URL = previous;
  }
});

it('takes test-auth capture chunks through the upload adapter, survey and storage without saving the credential or JPEG', async () => {
  const webProperty = jest.replaceProperty(skinRuntime, 'skinAnalysisUsesWebView', true);
  const serverProperty = jest.replaceProperty(skinRuntime, 'skinAnalysisServerMode', true);
  const oldUrl = process.env.EXPO_PUBLIC_SKIN_API_URL, oldMode = process.env.EXPO_PUBLIC_SKIN_AUTH_MODE;
  process.env.EXPO_PUBLIC_SKIN_API_URL = TRUSTED_SKIN_API_ORIGIN;
  process.env.EXPO_PUBLIC_SKIN_AUTH_MODE = 'test-token';
  const fixtureToken = 'test-fixture-only-not-a-server-secret';
  const features = analysis().features;
  const response = { schema_version: 'skin-recommendation-features-v1', status: 'complete', features,
    feature_status: Object.fromEntries(Object.keys(features).map(key => [key, 'predicted'])),
    validation_status: 'experimental_unvalidated', roi_method: 'opencv_yunet_facebox_proportions_v1',
    acne: { status: 'predicted', label: 1, score: .7, threshold: .5 },
    execution: { runtime: 'pytorch-cuda', bundleVersion: 'a'.repeat(64), serverMs: 51 } };
  jest.mocked(expoFetch).mockResolvedValue({ ok: true, url: TRUSTED_SKIN_API_ORIGIN + '/analyze',
    json: async () => response } as Awaited<ReturnType<typeof expoFetch>>);
  jest.mocked(uploadSkinPhoto).mockImplementation(jest.requireActual('@/lib/skinServer').uploadSkinPhoto);
  jest.mocked(skinRuntime.createSkinWebRun).mockReturnValue({ mode: 'server', assetsUrl: 'http://localhost:8081/skin-runtime/',
    run: { runId: 'test-auth', processId: 'session', firstInProcess: true, device: 'test', androidVersion: 'android', build: 'expo-go' } });
  let flow!: ReturnType<typeof useSkinAnalysis>;
  function Harness() { flow = useSkinAnalysis(); return null; }
  let renderer!: ReturnType<typeof create>;
  await act(async () => { renderer = create(createElement(Harness)); });
  try {
    await act(async () => { await flow.start(); });
    expect(flow.phase).toBe('error'); expect(flow.error).toBe('auth');
    expect(skinRuntime.createSkinWebRun).not.toHaveBeenCalled();
    await act(async () => { flow.cancel(); flow.setTestToken(fixtureToken); });
    expect(flow.testTokenReady).toBe(true);
    await act(async () => { await flow.start(); });
    expect(flow.phase).toBe('camera');
    await act(async () => { flow.onWebEvent({ type: 'captured' }); });
    await act(async () => { flow.onWebEvent({ type: 'capture-start', captureId: 'test-auth:jpeg', mime: 'image/jpeg', byteLength: 3, chunkCount: 1, captureMs: 4, alignmentMs: 1500 }); });
    await act(async () => { flow.onWebEvent({ type: 'capture-chunk', captureId: 'test-auth:jpeg', index: 0, data: '/9j/' }); });
    await act(async () => { flow.onWebEvent({ type: 'capture-end', captureId: 'test-auth:jpeg' }); });
    expect(flow.phase).toBe('survey'); expect(flow.testTokenReady).toBe(false);
    expect(expoFetch).toHaveBeenCalledTimes(1);
    expect(expoFetch).toHaveBeenCalledWith(TRUSTED_SKIN_API_ORIGIN + '/analyze', expect.objectContaining({
      headers: expect.objectContaining({ Authorization: 'Bearer ' + fixtureToken }), redirect: 'error',
    }));
    await act(async () => { flow.setAnswers({ tightness: 0, oiliness: 'unknown', sensitivity: 2 }); });
    await act(async () => { await flow.finish(); });
    expect(flow.phase).toBe('done');
    const saved = (await readSkinProfile())!.analysis;
    expect(saved.schema).toBe('skin-analysis-server-v1'); expect(saved.features).toEqual(features);
    expect(Object.keys(saved.features)).toHaveLength(10);
    expect(saved.timing.serverMs).toBe(51); expect(saved.timing.requestMs).toEqual(expect.any(Number));
    expect(saved.timing.models).toEqual([]);
    const stored = JSON.stringify(await AsyncStorage.multiGet(Object.values(STORAGE_KEYS)));
    expect(stored).not.toContain(fixtureToken); expect(stored).not.toMatch(/Bearer|base64|data:image/);
    await act(async () => { flow.cancel(); await flow.start(); });
    expect(flow.phase).toBe('error'); expect(flow.error).toBe('auth');
  } finally {
    await act(async () => { renderer.unmount(); }); webProperty.restore(); serverProperty.restore();
    if (oldUrl === undefined) delete process.env.EXPO_PUBLIC_SKIN_API_URL; else process.env.EXPO_PUBLIC_SKIN_API_URL = oldUrl;
    if (oldMode === undefined) delete process.env.EXPO_PUBLIC_SKIN_AUTH_MODE; else process.env.EXPO_PUBLIC_SKIN_AUTH_MODE = oldMode;
  }
});
