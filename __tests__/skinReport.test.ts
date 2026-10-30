import { SKIN_REPORT_EXAMPLE, SKIN_SAMPLE_PRODUCTS } from '@/constants/skinCare';
import { buildSkinReport, ingredientExamples, sampleProductMatches } from '@/lib/skinReport';
import type { SkinQuestionnaire } from '@/types/skin';
import type { SkinReportInput } from '@/types/skinReport';

function input(answers: Partial<SkinQuestionnaire> = {}): SkinReportInput {
  return { ...SKIN_REPORT_EXAMPLE,
    analysis: { ...SKIN_REPORT_EXAMPLE.analysis, features: { ...SKIN_REPORT_EXAMPLE.analysis.features } },
    questionnaire: { ...SKIN_REPORT_EXAMPLE.questionnaire, ...answers } };
}

it.each([
  [2, 0, 'dry'], [0, 2, 'oily'], [2, 2, 'combination'], [1, 1, 'balanced'],
  ['unknown', 2, 'unknown'], [2, 'unknown', 'unknown'],
] as const)('derives provisional type from survey %s / %s without treating unknown as balanced', (tightness, oiliness, expected) => {
  expect(buildSkinReport(input({ tightness, oiliness })).skinType).toBe(expected);
});

it('keeps model grades and survey answers distinct and preserves the original profile', () => {
  const source = input({ tightness: 2, oiliness: 'unknown' });
  const original = JSON.stringify(source);
  const report = buildSkinReport(source);
  expect(report.metrics.find((m) => m.concern === 'dryness')).toMatchObject({ source: 'survey', value: 2, maximum: null, status: 'care', regions: [] });
  expect(report.metrics.find((m) => m.concern === 'oiliness')).toMatchObject({ value: null, status: 'unknown' });
  expect(report.metrics.find((m) => m.concern === 'pores')).toMatchObject({ source: 'analysis', value: 3, maximum: 5, status: 'care',
    regions: [{ region: 'leftCheek', value: 2 }, { region: 'rightCheek', value: 3 }] });
  expect(JSON.stringify(source)).toBe(original);
});

it('uses the v3 skin type prediction without inventing moisture or oil grades', () => {
  const source = input({ tightness: 'unknown', oiliness: 'unknown', sensitivity: 2 });
  source.analysis.schema = 'skin-analysis-mobile-v2';
  source.analysis.skinType = { label: 'oily', probabilities: [.1, .2, .7], roiCount: 3, scoreType: 'mean_uncalibrated_softmax' };
  const report = buildSkinReport(source);
  expect(report).toMatchObject({ skinType: 'oily', skinTypeSource: 'analysis' });
  expect(report.concerns).toContain('oiliness');
  expect(report.metrics.find(metric => metric.concern === 'oiliness')).toMatchObject({ source: 'survey', value: null, regions: [] });
});

it('shows care concerns first without manufacturing a severity comparison across models', () => {
  const report = buildSkinReport(input());
  expect(report.concerns).toEqual(['dryness', 'pores']);
  expect(report.priorities.map((m) => m.concern)).toEqual(['dryness', 'pores']);
});

it('does not turn unavailable or invalid model output into a normal grade', () => {
  const source = input();
  source.analysis.features.pore_grade_cheek_image_left = NaN;
  const metric = buildSkinReport(source).metrics.find((m) => m.concern === 'pores');
  expect(metric).toMatchObject({ value: null, status: 'unknown', regions: [] });
});

it('treats acne as an overall binary result rather than an invented facial area or grade', () => {
  const source = input();
  source.analysis.features.acne = 1;
  const metric = buildSkinReport(source).metrics.find((m) => m.concern === 'blemish');
  expect(metric).toMatchObject({ value: 1, status: 'care', regions: [{ region: 'overall', value: 1 }] });
});

it('shows acne as unavailable in new four-model results, never as a normal result', () => {
  const source = input({ tightness: 0, oiliness: 0 });
  source.analysis.schema = 'skin-analysis-mobile-v3';
  source.analysis.skinType = { label: 'dry', probabilities: [.6, .3, .1], roiCount: 3, scoreType: 'mean_uncalibrated_softmax' };
  delete source.analysis.features.acne;
  const report = buildSkinReport(source);
  expect(report).toMatchObject({ skinType: 'balanced', skinTypeSource: 'combined' });
  expect(report.metrics.find(metric => metric.concern === 'blemish')).toMatchObject({
    source: 'unavailable', status: 'unknown', value: null, maximum: null, regions: [],
  });
  expect(report.concerns).not.toContain('blemish');
});

it('calculates the explicitly provisional four-week check-in across a year boundary', () => {
  const source = { ...input(), registeredAt: '2026-12-20T12:00:00.000Z' };
  expect(buildSkinReport(source).reviewAt).toBe('2027-01-17T12:00:00.000Z');
});

it('matches fictional products only to selected concerns and never fills an empty selection', () => {
  expect(sampleProductMatches([])).toEqual([]);
  const matches = sampleProductMatches(['pores']);
  expect(matches.map((m) => m.product.id)).toEqual(['sample-cleanser']);
  expect(matches[0].matchedConcerns).toEqual(['pores']);
  expect(sampleProductMatches(['dryness', 'sensitivity'])[0].matchedConcerns).toEqual(['dryness', 'sensitivity']);
  expect(SKIN_SAMPLE_PRODUCTS.every((p) => p.id.startsWith('sample-'))).toBe(true);
});

it('exposes editable ingredient examples independently of inferred model severity', () => {
  expect(ingredientExamples('dryness')).toEqual(['hyaluronic', 'ceramide', 'squalane']);
  expect(ingredientExamples('pores')).toEqual(['niacinamide', 'salicylic']);
});
