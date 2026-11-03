import type { SkinTypePrediction, SupportFusionResult, SupportFusionSettings, SupportFusionReason } from '@/types/skin';

/** Unvalidated initial heuristics, not medical thresholds or calibrated probabilities.
 * Replay stored settings; changes to category semantics or the formula require a new policy ID.
 */
export const SUPPORT_FUSION_V1: Readonly<SupportFusionSettings> = Object.freeze({
  highSignal: .60, lowSignal: .30, maxTopGap: .10, maxTargetGap: .10,
  maxAdjustment: .10, dryPostWashWeight: .60, oilTzoneWeight: .75,
});
const LABELS = ['dry', 'balanced', 'oily'] as const;
// Category strengths belong to policy v1, not to SOS/BSTQ scoring.
const POST_WASH = { none: 0, mild: .5, marked: 1 };
const AFTERNOON = { none: 0, slight: .5, marked: 1 };
const ONSET = { within1h: 1, after1to3h: .75, after3h: .25, notNoticed: 0 };
const EPS = 1e-12;

export function fuseSupportSkinType(prediction: SkinTypePrediction | undefined, survey: unknown,
  settings: Readonly<SupportFusionSettings> = SUPPORT_FUSION_V1): SupportFusionResult {
  if (Object.keys(settings).length !== Object.keys(SUPPORT_FUSION_V1).length || Object.keys(SUPPORT_FUSION_V1).some(key => typeof settings[key as keyof SupportFusionSettings] !== 'number') || Object.values(settings).some(v => !Number.isFinite(v) || v < 0 || v > 1) ||
      settings.lowSignal >= settings.highSignal || settings.maxAdjustment > .10) throw new Error('Invalid fusion settings');
  const base = { policy: 'support-dry-oily-v1' as const, settings: { ...settings } };
  if (!prediction) return { ...base, signals: null, scores: null, delta: null, type: 'unknown', reason: 'no-model', weight: 0, applied: false, changed: false };
  const raw = prediction.probabilities;
  if (prediction.roiCount !== 3 || prediction.scoreType !== 'mean_uncalibrated_softmax' || !Array.isArray(raw) || raw.length !== 3 ||
      raw.some(v => !Number.isFinite(v) || v < 0 || v > 1) || Math.abs(raw.reduce((a, b) => a + b, 0) - 1) > 1e-5 ||
      prediction.label !== LABELS[raw.reduce((at, v, i) => v > raw[at] ? i : at, 0)]) throw new Error('Invalid model scores');
  let signals: SupportFusionResult['signals'] = null;
  const unchanged = (reason: SupportFusionReason): SupportFusionResult => ({ ...base, signals,
    scores: [...raw], delta: [0, 0, 0], type: prediction.label, reason, weight: 0, applied: false, changed: false });
  if (!survey || typeof survey !== 'object') return unchanged('missing-survey');
  const q = survey as Record<string, unknown>;
  if (q.version !== 'skin-support-1') return unchanged('unsupported-survey');
  const fields = ['postWashDryness', 'afternoonTzoneOil', 'cheekState', 'oilOnset'] as const;
  if (fields.some(key => q[key] === undefined || q[key] === null)) return unchanged('missing-answer');
  const allowed: Record<typeof fields[number], readonly unknown[]> = {
    postWashDryness: [...Object.keys(POST_WASH), 'unknown'], afternoonTzoneOil: [...Object.keys(AFTERNOON), 'unknown'],
    cheekState: ['dry', 'comfortable', 'oily', 'variable', 'unknown'], oilOnset: [...Object.keys(ONSET), 'unknown'],
  };
  if (fields.some(key => !allowed[key].includes(q[key]))) return unchanged('invalid-answer');
  if (fields.some(key => q[key] === 'unknown') || q.cheekState === 'variable') return unchanged('ambiguous-survey');
  const tzone = (AFTERNOON[q.afternoonTzoneOil as keyof typeof AFTERNOON] + ONSET[q.oilOnset as keyof typeof ONSET]) / 2;
  signals = {
    dry: settings.dryPostWashWeight * POST_WASH[q.postWashDryness as keyof typeof POST_WASH] + (1 - settings.dryPostWashWeight) * Number(q.cheekState === 'dry'),
    oily: settings.oilTzoneWeight * tzone + (1 - settings.oilTzoneWeight) * Number(q.cheekState === 'oily'),
  };
  const { dry, oily } = signals;
  if (dry + EPS >= settings.highSignal && oily + EPS >= settings.highSignal) return unchanged('both-high');
  const target = dry + EPS >= settings.highSignal && oily <= settings.lowSignal + EPS ? 0
    : oily + EPS >= settings.highSignal && dry <= settings.lowSignal + EPS ? 2 : null;
  if (target === null) return unchanged('neutral');
  const ranked = [...raw].sort((a, b) => b - a);
  if (ranked[0] - ranked[1] > settings.maxTopGap + EPS) return unchanged('model-clear');
  if (ranked[0] - raw[target] > settings.maxTargetGap + EPS) return unchanged('target-distant');
  const weight = settings.maxAdjustment * Math.abs(dry - oily);
  if (weight <= EPS) return unchanged('neutral');
  const total = raw.reduce((a, b) => a + b, 0);
  const mixed = raw.map((p, i) => (1 - weight) * (p / total) + (i === target ? weight : 0));
  const sum = mixed.reduce((a, b) => a + b, 0);
  const scores = mixed.map(v => v / sum) as [number, number, number];
  let best = LABELS.indexOf(prediction.label);
  scores.forEach((v, i) => { if (v > scores[best] + EPS) best = i; });
  return { ...base, signals, scores, delta: scores.map((v, i) => v - raw[i]) as [number, number, number],
    type: LABELS[best], reason: target === 0 ? 'adjusted-dry' : 'adjusted-oily', weight, applied: true, changed: LABELS[best] !== prediction.label };
}
