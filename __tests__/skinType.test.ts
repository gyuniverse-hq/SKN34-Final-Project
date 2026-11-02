import { resolveSkinType } from '@/lib/skinType';
import type { SkinTypePrediction } from '@/types/skin';

const measurement: SkinTypePrediction = {
  label: 'dry', probabilities: [.6, .3, .1], roiCount: 3, scoreType: 'mean_uncalibrated_softmax',
};

it('combines survey 40% and measurement 60% and preserves raw model scores', () => {
  const result = resolveSkinType(measurement, { tightness: 0, oiliness: 0, sensitivity: 0 });
  expect(result).toMatchObject({ type: 'balanced', source: 'combined' });
  expect(result.scores![0]).toBeCloseTo(.36);
  expect(result.scores![1]).toBeCloseTo(.58);
  expect(result.scores![2]).toBeCloseTo(.06);
  expect(measurement.probabilities).toEqual([.6, .3, .1]);
});

it('shares a combination survey vote between dry and oily instead of inventing a fourth model class', () => {
  const result = resolveSkinType(measurement, { tightness: 2, oiliness: 2, sensitivity: 2 });
  expect(result).toMatchObject({ type: 'dry', source: 'combined' });
  expect(result.scores![0]).toBeCloseTo(.56);
  expect(result.scores![1]).toBeCloseTo(.18);
  expect(result.scores![2]).toBeCloseTo(.26);
});

it('uses the measurement alone when the survey cannot classify a type, and preserves legacy survey results', () => {
  expect(resolveSkinType(measurement, { tightness: 'unknown', oiliness: 2, sensitivity: 0 }))
    .toEqual({ type: 'dry', source: 'analysis' });
  expect(resolveSkinType(undefined, { tightness: 2, oiliness: 0, sensitivity: 0 }))
    .toEqual({ type: 'dry', source: 'survey' });
});
