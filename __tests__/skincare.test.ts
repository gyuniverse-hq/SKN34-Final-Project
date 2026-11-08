import { SKIN_REPORT_EXAMPLE } from '@/constants/skinCare';
import { deriveCareGoals, displayCareGoal, displayCareGroups, skincareRequest } from '@/lib/skincare';
import { buildSkinReport } from '@/lib/skinReport';
import type { SkinAnalysisResult, SkinProfileV3 } from '@/types/skin';
import type { HybridResponse } from '@/types/skincare';
const profile: SkinProfileV3 = { version: 3, registeredAt: SKIN_REPORT_EXAMPLE.registeredAt,
  analysis: { ...SKIN_REPORT_EXAMPLE.analysis, schema: 'skin-analysis-mobile-v4', skinType: undefined,
    features: { ...SKIN_REPORT_EXAMPLE.analysis.features, pore_grade_cheek_image_left: 0, pore_grade_cheek_image_right: 0 } } as SkinAnalysisResult,
  questionnaire: { version: 'skin-support-1', postWashDryness: 'marked', afternoonTzoneOil: 'marked',
    cheekState: 'dry', oilOnset: 'within1h', cosmeticReaction: 'repeated', priority: 'wrinkles' } };
it('keeps user priority and includes only concerns marked for care in the report', () => {
  const result = deriveCareGoals(profile);
  expect(result.primary).toBe('wrinkles');
  expect(result.detectedConcerns).toEqual(expect.arrayContaining([
    { goal: 'sensitivity', sources: ['survey'] },
  ]));
  expect(result.detectedConcerns.map(c => c.goal)).not.toContain('pores');
  expect(result.detectedConcerns.map(c => c.goal)).not.toContain('dryness');
  expect(result.detectedConcerns.map(c => c.goal)).not.toContain('oiliness');
  expect(result.detectedConcerns.map(c => c.goal).sort()).toEqual(
    buildSkinReport(profile).metrics.filter(m => m.status === 'care').map(m => m.concern).sort(),
  );
  expect(skincareRequest(profile, 'wrinkles', []).secondaryGoals).toEqual([]);
  expect(result.skinType).toBe('unknown');
});
it('includes mobile v4 care results once and excludes good results and the chosen goal', () => {
  const mixed: SkinProfileV3 = { ...profile, analysis: { ...profile.analysis,
    features: { ...profile.analysis.features, pigmentation_grade_forehead: 0,
      pigmentation_grade_cheek_image_left: 0, pigmentation_grade_cheek_image_right: 0,
      wrinkle_grade_forehead: 0, wrinkle_grade_glabella: 0,
      wrinkle_grade_eye_image_left: 0, wrinkle_grade_eye_image_right: 0,
      pore_grade_cheek_image_left: 1, pore_grade_cheek_image_right: 1 } } };
  const req = skincareRequest(mixed, 'wrinkles', []);
  expect(req.detectedConcerns).toContainEqual({ goal: 'pores', sources: ['analysis'] });
  expect(req.detectedConcerns.filter(c => c.goal === 'pores')).toHaveLength(1);
  expect(req.detectedConcerns.map(c => c.goal)).not.toContain('wrinkles');
  expect(req.detectedConcerns.map(c => c.goal)).not.toContain('pigmentation');
});
it('transmits only derived information and canonical goals', () => {
  const req = skincareRequest(profile, 'wrinkles', ['dryness','dryness','wrinkles']);
  expect(req.secondaryGoals).toEqual(['dryness', 'oiliness']);
  expect(req.balanceGoal).toBe('secondary');
  expect(req).not.toHaveProperty('analysis'); expect(req).not.toHaveProperty('questionnaire');
});
it('preserves unknown and permits manual care without model', () => {
  expect(deriveCareGoals(null).skinType).toBe('unknown');
  expect(skincareRequest(null, 'pores', []).primaryGoal).toBe('pores');
});
it('supports oiliness and blemish goals while keeping missing analysis unknown', () => {
  expect(skincareRequest(null, 'oiliness', ['blemish']).secondaryGoals).toEqual(['blemish']);
  expect(skincareRequest(null, 'oiliness', ['blemish']).balanceGoal).toBe('primary');
  expect(skincareRequest(null, 'blemish', ['oiliness']).primaryGoal).toBe('blemish');
  expect(skincareRequest(null, 'blemish', ['oiliness']).secondaryGoals).toEqual(['dryness', 'oiliness']);
  const noAcne = { ...profile, analysis: { ...profile.analysis, features: { ...profile.analysis.features, acne: undefined } } };
  expect(deriveCareGoals(noAcne).detectedConcerns.map(c => c.goal)).not.toContain('blemish');
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
  expect(skincareRequest(null, 'dryness', []).balanceGoal).toBe('primary');
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
