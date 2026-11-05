import { SKIN_REPORT_EXAMPLE } from '@/constants/skinCare';
import { deriveCareGoals, skincareRequest } from '@/lib/skincare';
import type { SkinAnalysisResult, SkinProfileV3 } from '@/types/skin';
const profile: SkinProfileV3 = { version: 3, registeredAt: SKIN_REPORT_EXAMPLE.registeredAt,
  analysis: { ...SKIN_REPORT_EXAMPLE.analysis, schema: 'skin-analysis-mobile-v4', skinType: undefined,
    features: { ...SKIN_REPORT_EXAMPLE.analysis.features, pore_grade_cheek_image_left: 0, pore_grade_cheek_image_right: 0 } } as SkinAnalysisResult,
  questionnaire: { version: 'skin-support-1', postWashDryness: 'marked', afternoonTzoneOil: 'marked',
    cheekState: 'dry', oilOnset: 'within1h', cosmeticReaction: 'repeated', priority: 'wrinkles' } };
it('keeps user priority, derives dryness and reaction without treating oil as pores', () => {
  const result = deriveCareGoals(profile);
  expect(result.primary).toBe('wrinkles');
  expect(result.secondary).toEqual(expect.arrayContaining(['dryness','sensitivity']));
  expect(result.secondary).not.toContain('pores');
  expect(result.skinType).toBe('unknown');
});
it('transmits only derived information and canonical goals', () => {
  const req = skincareRequest(profile, 'wrinkles', ['dryness','dryness','wrinkles']);
  expect(req.secondaryGoals).toEqual(['dryness']);
  expect(req).not.toHaveProperty('analysis'); expect(req).not.toHaveProperty('questionnaire');
});
it('preserves unknown and permits manual care without model', () => {
  expect(deriveCareGoals(null).skinType).toBe('unknown');
  expect(skincareRequest(null, 'pores', []).primaryGoal).toBe('pores');
});
