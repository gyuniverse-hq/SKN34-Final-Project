import { surveySensitivity } from './skinSurvey';
import { CARE_INGREDIENTS } from '@/constants/skinCare';
import type { SkinConcern } from '@/types';
import type { SkinAnswer, SkinQuestionnaire } from '@/types/skin';
import type { CareIngredient, SkinRegion, SkinReport, SkinReportInput, SkinReportMetric } from '@/types/skinReport';
import { SKIN_CONCERNS } from './routes';
import { resolveSkinType } from './skinType';
import { skinGradeStatus } from './skinResult';

function surveyMetric(concern: SkinConcern, answer: SkinAnswer): SkinReportMetric {
  const known = answer === 0 || answer === 1 || answer === 2;
  return { concern, source: 'survey', status: !known ? 'unknown' : answer === 2 ? 'care' : 'good',
    value: known ? answer : null, maximum: null, regions: [] };
}

function modelMetric(concern: SkinConcern, maximum: number, values: [SkinRegion, number][], modelScore?: number): SkinReportMetric {
  const known = values.every(([, v]) => Number.isInteger(v) && v >= 0 && v <= maximum);
  const value = known ? Math.max(...values.map(([, v]) => v)) : null;
  return { concern, source: 'analysis', value, maximum,
    status: value === null ? 'unknown' : maximum === 1 ? value === 1 ? 'care' : 'good' : skinGradeStatus(value),
    ...(known && modelScore !== undefined ? { modelScore } : {}),
    regions: known ? values.map(([region, v]) => ({ region, value: v })) : [] };
}

function imageMetrics(analysis: SkinReportInput['analysis']) {
  const { features, cautionProbabilities, acneScore } = analysis;
  const binary = analysis.schema === 'skin-analysis-mobile-v4';
  const isScore = (value: number | undefined): value is number =>
    value !== undefined && Number.isFinite(value) && value >= 0 && value <= 1;
  function metric(concern: SkinConcern, maxGrade: number, regions: [SkinRegion, Exclude<keyof typeof features, 'acne'>][]) {
    const scores = regions.map(([, feature]) => cautionProbabilities?.[feature]);
    const score = binary && scores.every(isScore) ? Math.max(...scores) : undefined;
    return modelMetric(concern, binary ? 1 : maxGrade,
      regions.map(([region, feature]) => [region, features[feature]]), score);
  }
  return {
    pigmentation: metric('pigmentation', 5, [
      ['forehead', 'pigmentation_grade_forehead'], ['leftCheek', 'pigmentation_grade_cheek_image_left'],
      ['rightCheek', 'pigmentation_grade_cheek_image_right'],
    ]),
    wrinkles: metric('wrinkles', 6, [
      ['forehead', 'wrinkle_grade_forehead'], ['glabella', 'wrinkle_grade_glabella'],
      ['leftEye', 'wrinkle_grade_eye_image_left'], ['rightEye', 'wrinkle_grade_eye_image_right'],
    ]),
    pores: metric('pores', 5, [['leftCheek', 'pore_grade_cheek_image_left'], ['rightCheek', 'pore_grade_cheek_image_right']]),
    blemish: features.acne === undefined
      ? { concern: 'blemish', source: 'unavailable', status: 'unknown', value: null, maximum: null, regions: [] } as const
      : modelMetric('blemish', 1, [['overall', features.acne]], isScore(acneScore) ? acneScore : undefined),
  } satisfies Record<'pigmentation' | 'wrinkles' | 'pores' | 'blemish', SkinReportMetric>;
}

export function buildSkinReport(input: SkinReportInput): SkinReport {
  if (input.version !== 2 && input.version !== 3 && input.version !== 4) return buildLegacySkinReport(input);
  const q = input.questionnaire;
  const { pigmentation, wrinkles, pores, blemish } = imageMetrics(input.analysis);
  const skinType = input.version === 2 || input.version === 4 ? input.fusion.type : input.analysis.skinType?.label ?? 'unknown';
  const source = (input.version === 2 && input.fusion.reason === 'adjusted') || (input.version === 4 && input.fusion.applied) ? 'combined' as const : 'analysis' as const;
  const typeMetric: SkinReportMetric = { concern: 'dryness', source, skinType,
    status: skinType === 'unknown' ? 'unknown' : skinType === 'dry' ? 'care' : 'good', value: null, maximum: null, regions: [] };
  const metrics: SkinReportMetric[] = [
    typeMetric,
    pigmentation,
    { concern: 'oiliness', source, status: skinType === 'unknown' ? 'unknown' : skinType === 'oily' ? 'care' : 'good', value: null, maximum: null, regions: [] },
    wrinkles, pores, blemish,
    { concern: 'sensitivity', source: 'survey', status: surveySensitivity(q), value: null, maximum: null, regions: [] },
  ];
  const care = metrics.filter(m => m.status === 'care');
  const priority = metrics.find(m => m.concern === q.priority)!;
  const review = new Date(input.registeredAt); review.setUTCDate(review.getUTCDate() + 28);
  return { skinType, skinTypeSource: source, registeredAt: input.registeredAt, reviewAt: review.toISOString(), metrics,
    ...(input.version === 2
      ? { assessment: { fusion: input.fusion, raw: input.analysis.skinType, questionnaire: input.questionnaire } }
      : { supportAssessment: { raw: input.analysis.skinType, questionnaire: input.questionnaire, ...(input.version === 4 ? { fusion: input.fusion } : {}) } }),
    priorities: [priority, ...care.filter(m => m !== priority), ...metrics.filter(m => m !== priority && m.status !== 'care')].slice(0, 2),
    concerns: [q.priority, ...SKIN_CONCERNS.filter(c => c !== q.priority && care.some(m => m.concern === c))] };
}

function buildLegacySkinReport(input: Extract<SkinReportInput, { questionnaire: SkinQuestionnaire }>): SkinReport {
  const { pigmentation, wrinkles, pores, blemish } = imageMetrics(input.analysis);
  const q = input.questionnaire;
  const resolvedType = resolveSkinType(input.analysis.skinType, q);
  const skinType = resolvedType.type;
  const metrics: SkinReportMetric[] = [
    input.analysis.skinType ? { concern: 'dryness', source: resolvedType.source, skinType,
      status: skinType === 'dry' ? 'care' : 'good', value: null, maximum: null, regions: [] }
      : surveyMetric('dryness', q.tightness),
    pigmentation,
    surveyMetric('oiliness', q.oiliness),
    wrinkles, pores, blemish,
    surveyMetric('sensitivity', q.sensitivity),
  ];
  const review = new Date(input.registeredAt);
  review.setUTCDate(review.getUTCDate() + 28);
  const care = metrics.filter((m) => m.status === 'care');
  return { skinType, skinTypeSource: resolvedType.source, registeredAt: input.registeredAt, reviewAt: review.toISOString(), metrics,
    priorities: [...care, ...metrics.filter((m) => m.status !== 'care')].slice(0, 2),
    concerns: SKIN_CONCERNS.filter((c) => care.some((m) => m.concern === c) ||
      (resolvedType.source !== 'survey' && skinType === 'dry' && c === 'dryness') ||
      (resolvedType.source !== 'survey' && skinType === 'oily' && c === 'oiliness')) };
}

export function ingredientExamples(concern: SkinConcern): readonly CareIngredient[] {
  return CARE_INGREDIENTS[concern];
}
