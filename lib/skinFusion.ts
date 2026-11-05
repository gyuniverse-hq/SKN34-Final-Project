import type { SkinFusionResult, SkinTypePrediction } from '@/types/skin';

/** Experimental service policy, not learned calibration or diagnostic probabilities. Freeze by policy version. */
export const SOS_OILY_V1 = Object.freeze({ sosMinimum: 20, maxGap: .10, step: .025, maxWeight: .10 });
const LABELS = ['dry', 'balanced', 'oily'] as const;
export function fuseSkinType(prediction: SkinTypePrediction | undefined, sosTotal: number): SkinFusionResult {
  if (!Number.isInteger(sosTotal) || sosTotal < 6 || sosTotal > 26) throw new Error('Invalid SOS total');
  const base = { policy: 'sos-oily-v1' as const, settings: { ...SOS_OILY_V1 }, sosTotal };
  if (!prediction) return { ...base, scores: null, delta: null, type: 'unknown', reason: 'no-model', weight: 0, changed: false };
  const p = prediction.probabilities;
  if (prediction.roiCount !== 3 || prediction.scoreType !== 'mean_uncalibrated_softmax' || !Array.isArray(p) || p.length !== 3 || p.some(v => !Number.isFinite(v) || v < 0 || v > 1) ||
      Math.abs(p.reduce((a, b) => a + b, 0) - 1) > 1e-5 ||
      prediction.label !== LABELS[p.reduce((at, v, i) => v > p[at] ? i : at, 0)]) throw new Error('Invalid model scores');
  const reason = prediction.label === 'oily' ? 'already-oily' : sosTotal < SOS_OILY_V1.sosMinimum ? 'low-sos'
    : Math.max(...p) - p[2] > SOS_OILY_V1.maxGap + 1e-12 ? 'large-gap' : 'adjusted';
  const weight = reason === 'adjusted' ? Math.min(SOS_OILY_V1.maxWeight, SOS_OILY_V1.step * (sosTotal - 19)) : 0;
  const scores = p.map((v, i) => (1 - weight) * v + (i === 2 ? weight : 0)) as [number, number, number];
  let best = LABELS.indexOf(prediction.label);
  scores.forEach((v, i) => { if (v > scores[best] + 1e-12) best = i; });
  return { ...base, scores, delta: scores.map((v, i) => v - p[i]) as [number, number, number],
    type: LABELS[best], reason, weight, changed: LABELS[best] !== prediction.label };
}
