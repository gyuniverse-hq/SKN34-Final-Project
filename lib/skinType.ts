import type { SkinQuestionnaire, SkinTypePrediction } from '@/types/skin';
import type { SkinType } from '@/types/skinReport';

/** Policy weights, not calibrated diagnostic probabilities. Raw model scores remain unchanged. */
export function resolveSkinType(prediction: SkinTypePrediction | undefined, answers: SkinQuestionnaire): {
  type: SkinType; source: 'survey' | 'analysis' | 'combined'; scores?: [number, number, number];
} {
  const survey: SkinType = answers.tightness === 'unknown' || answers.oiliness === 'unknown' ? 'unknown'
    : answers.tightness === 2 && answers.oiliness === 2 ? 'combination'
      : answers.tightness === 2 ? 'dry' : answers.oiliness === 2 ? 'oily' : 'balanced';
  if (!prediction) return { type: survey, source: 'survey' };
  if (survey === 'unknown') return { type: prediction.label, source: 'analysis' };
  const surveyScores = survey === 'dry' ? [1, 0, 0] : survey === 'oily' ? [0, 0, 1]
    : survey === 'combination' ? [.5, 0, .5] : [0, 1, 0];
  const scores = prediction.probabilities.map((value, i) => value * .6 + surveyScores[i] * .4) as [number, number, number];
  const best = scores.reduce((at, value, i) => value > scores[at] ? i : at, 0);
  return { type: (['dry', 'balanced', 'oily'] as const)[best], source: 'combined', scores };
}
