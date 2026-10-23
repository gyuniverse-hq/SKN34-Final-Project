import AsyncStorage from '@react-native-async-storage/async-storage';
import { appendSkinTiming, clearSkinTimings, comparableSkinTimings, readSkinProfile, readSkinTimings, summarizeSkinTimings, validateSkinAnalysis } from '@/lib/skinProfile';
import { STORAGE_KEYS } from '@/lib/storage';
import { useSkinProfileStore } from '@/store/skinProfileStore';
import type { SkinAnalysisResult, SkinProfile, SkinTiming } from '@/types/skin';
import { createElement } from 'react';
import { act, create } from 'react-test-renderer';
import { useSkinAnalysis } from '@/hooks/useSkinAnalysis';
import { analyzeSkin } from '@/lib/skinAnalysis';

jest.mock('@/lib/skinAnalysis', () => ({
  analyzeSkin: jest.fn(), cancelSkinAnalysis: jest.fn(() => Promise.resolve()), onSkinProgress: jest.fn(),
}));

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
