import { fuseSupportSkinType, SUPPORT_FUSION_V1 } from '@/lib/skinSupportFusion';
import type { SkinSurveyV3, SkinTypePrediction } from '@/types/skin';

const dry: SkinSurveyV3 = { version: 'skin-support-1', postWashDryness: 'marked', afternoonTzoneOil: 'none',
  cheekState: 'dry', oilOnset: 'notNoticed', cosmeticReaction: 'unknown', priority: 'pores' };
const oily: SkinSurveyV3 = { ...dry, postWashDryness: 'none', afternoonTzoneOil: 'marked', cheekState: 'oily', oilOnset: 'within1h' };
function model(probabilities: [number, number, number]): SkinTypePrediction {
  return { probabilities, label: (['dry', 'balanced', 'oily'] as const)[probabilities.indexOf(Math.max(...probabilities))],
    roiCount: 3, scoreType: 'mean_uncalibrated_softmax' };
}
const image = model([.42, .46, .12]);
it('boosts a dry-dominant signal and preserves the original model while changing the final class', () => {
  const original = JSON.stringify(image);
  const result = fuseSupportSkinType(image, dry);
  expect(result).toMatchObject({ applied: true, changed: true, type: 'dry', reason: 'adjusted-dry', signals: { dry: 1, oily: 0 } });
  expect(result.scores![0]).toBeGreaterThan(image.probabilities[0]);
  expect(JSON.stringify(image)).toBe(original);
});
it('boosts oily with one combined T-zone contribution', () => {
  expect(fuseSupportSkinType(model([.1, .47, .43]), oily)).toMatchObject({ applied: true, changed: true, type: 'oily', signals: { dry: 0, oily: 1 } });
  const result = fuseSupportSkinType(image, { ...dry, afternoonTzoneOil: 'marked', oilOnset: 'within1h' });
  expect(result).toMatchObject({ reason: 'both-high', applied: false, signals: { dry: 1, oily: .75 } });
  expect(result.scores).toEqual(image.probabilities);
});
it('does not manufacture a balanced vote from neutral or conflicting answers', () => {
  for (const q of [
    { ...dry, postWashDryness: 'none', cheekState: 'comfortable' },
    { ...oily, postWashDryness: 'marked' },
  ]) {
    const p = model([.48, .45, .07]);
    expect(fuseSupportSkinType(p, q)).toMatchObject({ applied: false, type: p.label });
  }
});
it('keeps raw scores for missing, unsupported, uncertain and malformed surveys', () => {
  for (const [q, reason] of [
    [undefined, 'missing-survey'], [{ ...dry, version: 'sos-bstq-1' }, 'unsupported-survey'],
    [{ ...dry, oilOnset: undefined }, 'missing-answer'], [{ ...dry, oilOnset: 'fast' }, 'invalid-answer'],
    [{ ...dry, cheekState: 'variable' }, 'ambiguous-survey'], [{ ...dry, postWashDryness: 'unknown' }, 'ambiguous-survey'],
  ] as const) expect(fuseSupportSkinType(image, q)).toMatchObject({ reason, applied: false, scores: image.probabilities, type: image.label });
  expect(fuseSupportSkinType(undefined, dry)).toMatchObject({ type: 'unknown', scores: null, reason: 'no-model' });
});
it('ignores sensitivity and priority entirely, including their absence', () => {
  expect(fuseSupportSkinType(image, { ...dry, cosmeticReaction: 'avoided', priority: 'sensitivity' })).toEqual(fuseSupportSkinType(image, dry));
  expect(fuseSupportSkinType(image, { ...dry, cosmeticReaction: undefined, priority: undefined })).toEqual(fuseSupportSkinType(image, dry));
});
it('requires both an image near-tie and a close target, including the threshold boundary', () => {
  expect(fuseSupportSkinType(model([.45, .55, 0]), dry).applied).toBe(true);
  expect(fuseSupportSkinType(model([.449, .551, 0]), dry).reason).toBe('model-clear');
  expect(fuseSupportSkinType(model([.48, .47, .05]), oily).reason).toBe('target-distant');
});
it('normalizes every adjusted vector and respects the maximum change over a score grid', () => {
  for (let a = 0; a <= 20; a++) for (let b = 0; b <= 20 - a; b++) {
    const p = model([a / 20, b / 20, (20 - a - b) / 20]);
    for (const q of [dry, oily]) {
      const result = fuseSupportSkinType(p, q);
      expect(result.scores!.reduce((x, y) => x + y, 0)).toBeCloseTo(1, 10);
      expect(result.scores!.every(v => v >= 0 && v <= 1)).toBe(true);
      expect(result.delta!.every(v => Math.abs(v) <= .10 + 1e-12)).toBe(true);
      expect(result.weight).toBeLessThanOrEqual(.10);
    }
  }
});
it('supports explicit tuning while rejecting invalid settings and malformed model scores', () => {
  expect(fuseSupportSkinType(image, dry, { ...SUPPORT_FUSION_V1, maxAdjustment: 0 }).applied).toBe(false);
  expect(() => fuseSupportSkinType(image, dry, { ...SUPPORT_FUSION_V1, maxAdjustment: .11 })).toThrow();
  expect(() => fuseSupportSkinType(image, dry, { ...SUPPORT_FUSION_V1, lowSignal: .8 })).toThrow();
  expect(() => fuseSupportSkinType({ ...image, probabilities: [NaN, .5, .5] }, dry)).toThrow();
});
it('retains the original class on an exact adjusted tie', () => {
  const p = model([.45, .55, 0]);
  const tie = model([9 / 19, 10 / 19, 0]);
  expect(fuseSupportSkinType(tie, dry, { ...SUPPORT_FUSION_V1, maxAdjustment: .05 })).toMatchObject({ applied: true, type: 'balanced', changed: false });
  expect(fuseSupportSkinType(p, dry).type).toBe('dry');
});
