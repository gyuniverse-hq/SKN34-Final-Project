import { SKIN_REPORT_EXAMPLE } from '@/constants/skinCare';
import { deriveCareGoals, displayCareGoal, displayCareGroups } from '@/lib/skincare';
import { buildSkinReport } from '@/lib/skinReport';
import type { SkinAnalysisResult, SkinProfileV3 } from '@/types/skin';
import type { HybridResponse } from '@/types/skincare';
const profile: SkinProfileV3 = { version: 3, registeredAt: SKIN_REPORT_EXAMPLE.registeredAt,
  analysis: { ...SKIN_REPORT_EXAMPLE.analysis, schema: 'skin-analysis-mobile-v4', skinType: undefined,
    features: { ...SKIN_REPORT_EXAMPLE.analysis.features, pore_grade_cheek_image_left: 0, pore_grade_cheek_image_right: 0 } } as SkinAnalysisResult,
  questionnaire: { version: 'skin-support-1', postWashDryness: 'marked', afternoonTzoneOil: 'marked',
    cheekState: 'dry', oilOnset: 'within1h', cosmeticReaction: 'repeated', priority: 'wrinkles' } };
it('includes only concerns marked for care, independently of stored survey priority', () => {
  const result = deriveCareGoals(profile);
  expect(deriveCareGoals({ ...profile, questionnaire: { ...profile.questionnaire, priority: 'pores' } })).toEqual(result);
  expect(result.detectedConcerns).toEqual(expect.arrayContaining([
    { goal: 'sensitivity', sources: ['survey'] },
  ]));
  expect(result.detectedConcerns.map(c => c.goal)).not.toContain('pores');
  expect(result.detectedConcerns.map(c => c.goal)).not.toContain('dryness');
  expect(result.detectedConcerns.map(c => c.goal)).not.toContain('oiliness');
  expect(result.detectedConcerns.map(c => c.goal).sort()).toEqual(
    buildSkinReport(profile).metrics.filter(m => m.status === 'care').map(m => m.concern).sort(),
  );
  expect(result.skinType).toBe('unknown');
});
it('includes mobile v4 care results once and excludes good results and the chosen goal', () => {
  const mixed: SkinProfileV3 = { ...profile, analysis: { ...profile.analysis,
    features: { ...profile.analysis.features, pigmentation_grade_forehead: 0,
      pigmentation_grade_cheek_image_left: 0, pigmentation_grade_cheek_image_right: 0,
      wrinkle_grade_forehead: 0, wrinkle_grade_glabella: 0,
      wrinkle_grade_eye_image_left: 0, wrinkle_grade_eye_image_right: 0,
      pore_grade_cheek_image_left: 1, pore_grade_cheek_image_right: 1 } } };
  const req = deriveCareGoals(mixed);
  expect(req.detectedConcerns).toContainEqual({ goal: 'pores', sources: ['analysis'] });
  expect(req.detectedConcerns.filter(c => c.goal === 'pores')).toHaveLength(1);
  expect(req.detectedConcerns.map(c => c.goal)).not.toContain('wrinkles');
  expect(req.detectedConcerns.map(c => c.goal)).not.toContain('pigmentation');
});
it('transmits only derived profile information and preserves unknown values', () => {
  expect(Object.keys(deriveCareGoals(profile)).sort()).toEqual(['detectedConcerns', 'irritationSignal', 'skinType']);
  expect(deriveCareGoals(null)).toEqual({ detectedConcerns: [], irritationSignal: 'unknown', skinType: 'unknown' });
});
it('keeps missing acne analysis out of detected concerns', () => {
  const noAcne = { ...profile, analysis: { ...profile.analysis, features: { ...profile.analysis.features, acne: undefined } } };
  expect(deriveCareGoals(noAcne).detectedConcerns.map(c => c.goal)).not.toContain('blemish');
});

function scoredProfile(): SkinProfileV3 {
  const features = Object.fromEntries(Object.keys(profile.analysis.features)
    .filter(key => key !== 'acne').map(key => [key, 0])) as SkinAnalysisResult['features'];
  const cautionProbabilities = Object.fromEntries(Object.keys(features).map(key => [key, 0.1])) as
    NonNullable<SkinAnalysisResult['cautionProbabilities']>;
  cautionProbabilities.pore_grade_cheek_image_left = 0.9;
  cautionProbabilities.pigmentation_grade_forehead = 0.45;
  features.pore_grade_cheek_image_left = 1;
  return { ...profile, analysis: { ...profile.analysis, features, cautionProbabilities } };
}

it('sends ROI maxima for both good and care analyses without changing their status', () => {
  const input = scoredProfile();
  const result = deriveCareGoals(input);
  expect(result.analysisScores).toEqual({ pores: 0.9, pigmentation: 0.45, wrinkles: 0.1 });
  expect(result.detectedConcerns.map(c => c.goal)).toContain('pores');
  expect(result.detectedConcerns.map(c => c.goal)).not.toContain('pigmentation');
  expect(buildSkinReport(input).metrics.find(m => m.concern === 'pigmentation')?.status).toBe('good');
  expect(Object.keys(result).sort()).toEqual(['analysisScores', 'detectedConcerns', 'irritationSignal', 'skinType']);
});

it('does not invent scores for legacy models or incomplete and invalid ROIs', () => {
  const input = scoredProfile();
  const legacy = { ...input, analysis: { ...input.analysis, schema: 'skin-analysis-mobile-v3' as const } };
  expect(deriveCareGoals(legacy).analysisScores).toBeUndefined();
  for (const value of [undefined, NaN, Infinity, -0.1, 1.1]) {
    const invalid = { ...input, analysis: { ...input.analysis, cautionProbabilities: {
      ...input.analysis.cautionProbabilities!, pore_grade_cheek_image_left: value,
    } as NonNullable<SkinAnalysisResult['cautionProbabilities']> } };
    expect(deriveCareGoals(invalid).analysisScores).toEqual({ pigmentation: 0.45, wrinkles: 0.1 });
  }
});

it('combines balance results without duplicate products and keeps a usable coverage status', () => {
  const first = { product: { id: 'a' } };
  const second = { product: { id: 'b' } };
  const response = {
    coverage: [{ goal: 'dryness', status: 'no_matches' }, { goal: 'oiliness', status: 'ok' }],
    byConcern: { dryness: [first], oiliness: [first, second] },
  } as unknown as HybridResponse;
  expect(displayCareGoal('oiliness')).toBe('dryness');
  expect(displayCareGroups(response)).toEqual([
    { goal: 'dryness', status: 'ok', matches: [first, second] },
  ]);
});

it('shows up to five distinct products for each concern and for balance', () => {
  const matches = Array.from({ length: 6 }, (_, i) => ({ product: { id: String(i) } }));
  const coverage = [{ goal: 'dryness', status: 'ok' }, { goal: 'oiliness', status: 'ok' }];
  const byConcern = { dryness: matches.slice(0, 3), oiliness: [matches[0], ...matches.slice(3)] };
  const merged = { coverage, byConcern } as unknown as HybridResponse;
  expect(displayCareGroups(merged)[0].matches).toEqual(matches.slice(0, 5));
  const withBalance = { coverage, byConcern, balanceMatches: matches } as unknown as HybridResponse;
  expect(displayCareGroups(withBalance)[0].matches).toEqual(matches.slice(0, 5));
});
