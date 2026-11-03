import AsyncStorage from '@react-native-async-storage/async-storage';
import { buildSkinRecommendationRequest } from '@/lib/skinRecommendations';
import { buildSkinReport } from '@/lib/skinReport';
import { readSkinProfile, validateSkinAnalysis, writeSkinProfile } from '@/lib/skinProfile';
import { fuseSupportSkinType } from '@/lib/skinSupportFusion';
import type { SkinAnalysisResult, SkinProfileV4, SkinSurveyV3 } from '@/types/skin';

function profile(): SkinProfileV4 {
  const questionnaire: SkinSurveyV3 = { version: 'skin-support-1', postWashDryness: 'unknown',
    afternoonTzoneOil: 'unknown', cheekState: 'unknown', oilOnset: 'unknown',
    cosmeticReaction: 'unknown', priority: 'dryness' };
  const features = { pore_grade_cheek_image_left: 0, pore_grade_cheek_image_right: 1,
    pigmentation_grade_forehead: 0, pigmentation_grade_cheek_image_left: 0, pigmentation_grade_cheek_image_right: 0,
    wrinkle_grade_forehead: 0, wrinkle_grade_glabella: 0, wrinkle_grade_eye_image_left: 1, wrinkle_grade_eye_image_right: 0 };
  const analysis: SkinAnalysisResult = { schema: 'skin-analysis-mobile-v4', features,
    cautionProbabilities: Object.fromEntries(Object.entries(features).map(([key, label]) => [key, label ? .5 : .1])) as SkinAnalysisResult['cautionProbabilities'],
    skinType: { label: 'balanced', probabilities: [.1, .8, .1], roiCount: 3, scoreType: 'mean_uncalibrated_softmax' },
    roiMethod: 'opencv_haar_facebox_proportions_v1', validationStatus: 'experimental_unvalidated',
    preprocessing: 'skin-v3-embedded-enhancement', timing: { runId: 'v4', processId: 'test', firstInProcess: true,
      device: 'test', androidVersion: 'test', build: 'test', runtime: 'wasm', bundleVersion: 'a'.repeat(64),
      alignmentMs: 0, captureMs: 0, imagePreparationMs: 0, validationMs: 0, detectionMs: 0, nativeMs: 0,
      totalMs: 1, memoryPssKb: null, models: (['pore', 'pigmentation', 'wrinkle', 'skinType'] as const).map(indicator => ({
        indicator, sourceSha256: 'a'.repeat(64), sha256: 'b'.repeat(64), loadMs: 0, validationMs: 0, preprocessingMs: 0, inferenceMs: 0,
      })) } };
  return { version: 4, registeredAt: '2026-11-02T00:00:00Z', analysis, questionnaire,
    fusion: fuseSupportSkinType(analysis.skinType, questionnaire) };
}

it('persists binary evidence and uses any caution ROI consistently in the report and recommendation', async () => {
  await AsyncStorage.clear();
  const source = profile();
  await writeSkinProfile(source);
  const restored = await readSkinProfile();
  expect(restored).toEqual(source);
  const report = buildSkinReport(source);
  expect(report.metrics.find(m => m.concern === 'pores')).toMatchObject({ status: 'care', value: 1, maximum: 1 });
  expect(report.metrics.find(m => m.concern === 'wrinkles')).toMatchObject({ status: 'care', value: 1, maximum: 1 });
  expect(report.metrics.find(m => m.concern === 'pigmentation')).toMatchObject({ status: 'good', value: 0, maximum: 1 });
  expect(report.metrics.find(m => m.concern === 'blemish')).toMatchObject({ status: 'unknown' });
  expect(buildSkinRecommendationRequest(restored)).toEqual({ concerns: ['dryness', 'pores', 'wrinkles'], limit: 8 });
});

it('rejects grade values, missing scores and scores inconsistent with binary labels', () => {
  const source = profile().analysis;
  expect(() => validateSkinAnalysis(source)).not.toThrow();
  expect(() => validateSkinAnalysis({ ...source, features: { ...source.features, pore_grade_cheek_image_left: 3 } })).toThrow();
  expect(() => validateSkinAnalysis({ ...source, cautionProbabilities: undefined })).toThrow();
  expect(() => validateSkinAnalysis({ ...source, cautionProbabilities: { ...source.cautionProbabilities!, pore_grade_cheek_image_left: .5 } })).toThrow();
});
