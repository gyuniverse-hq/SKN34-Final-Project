import { comparisonInput } from '@/lib/recommendationComparison';
import { SKIN_REPORT_EXAMPLE } from '@/constants/skinCare';
import type { SkinProfile } from '@/types/skin';

jest.mock('@/lib/api', () => ({ ApiError: Error }));
jest.mock('@/lib/skinReport', () => ({ buildSkinReport: () => ({ skinType: 'oily' }) }));
jest.mock('@/lib/skincare', () => ({ deriveCareGoals: () => ({ irritationSignal: 'caution' }) }));

function profile(): SkinProfile {
  return { ...SKIN_REPORT_EXAMPLE, version: 1, analysis: {
    ...SKIN_REPORT_EXAMPLE.analysis, schema: 'skin-analysis-mobile-v4',
    roiMethod: 'opencv_haar_facebox_proportions_v1', validationStatus: 'experimental_unvalidated',
    timing: { runId: 'test', processId: 'test', firstInProcess: true, device: 'test',
      androidVersion: 'test', build: 'test', runtime: 'wasm', bundleVersion: 'test',
      alignmentMs: 0, captureMs: 0, imagePreparationMs: 0, validationMs: 0,
      detectionMs: 0, nativeMs: 0, totalMs: 0, memoryPssKb: null, models: [] },
    cautionProbabilities: {
      pore_grade_cheek_image_left: 0.2, pore_grade_cheek_image_right: 0.6,
      pigmentation_grade_forehead: 1, pigmentation_grade_cheek_image_left: 0.1,
      pigmentation_grade_cheek_image_right: 0.3, wrinkle_grade_forehead: 1,
      wrinkle_grade_glabella: 1, wrinkle_grade_eye_image_left: 0.5, wrinkle_grade_eye_image_right: 0.7,
    },
  } };
}

it('uses the two supported ROI means, retains irritation, and transmits no image/profile metadata', () => {
  const original = profile();
  const before = JSON.stringify(original);
  const request = comparisonInput(original, '30대', '여성');
  expect(request.scores).toEqual({ pores: 0.4, pigmentation: 0.2, wrinkles: 0.6 });
  expect(request.skinType).toBe('지성');
  expect(request.irritationSignal).toBe('caution');
  expect(Object.keys(request).sort()).toEqual([
    'ageGroup', 'aggregation', 'analysisVersion', 'gender', 'irritationSignal', 'scoreKind', 'scores', 'skinType',
  ]);
  expect(JSON.stringify(original)).toBe(before);
});

it('rejects legacy grade results and missing/non-finite scores rather than inserting zero', () => {
  expect(() => comparisonInput(null, '30대', '여성')).toThrow('comparison.needV4');
  const legacy = profile(); legacy.analysis.schema = 'skin-analysis-mobile-v3';
  expect(() => comparisonInput(legacy, '30대', '여성')).toThrow('comparison.needV4');
  const missing = profile(); missing.analysis.cautionProbabilities = undefined;
  expect(() => comparisonInput(missing, '30대', '여성')).toThrow('comparison.needV4');
  const invalid = profile(); invalid.analysis.cautionProbabilities!.pore_grade_cheek_image_left = NaN;
  expect(() => comparisonInput(invalid, '30대', '여성')).toThrow('comparison.invalidScores');
});
