import { CARE_INGREDIENTS, SKIN_SAMPLE_PRODUCTS } from '@/constants/skinCare';
import type { SkinConcern } from '@/types';
import type { SkinAnswer } from '@/types/skin';
import type { CareIngredient, SkinRegion, SkinReport, SkinReportInput, SkinReportMetric, SkinSampleProduct } from '@/types/skinReport';
import { SKIN_CONCERNS } from './routes';
import { resolveSkinType } from './skinType';
import { skinGradeStatus } from './skinResult';

function surveyMetric(concern: SkinConcern, answer: SkinAnswer): SkinReportMetric {
  const known = answer === 0 || answer === 1 || answer === 2;
  return { concern, source: 'survey', status: !known ? 'unknown' : answer === 2 ? 'care' : 'good',
    value: known ? answer : null, maximum: null, regions: [] };
}

function modelMetric(concern: SkinConcern, maximum: number, values: [SkinRegion, number][]): SkinReportMetric {
  const known = values.every(([, v]) => Number.isInteger(v) && v >= 0 && v <= maximum);
  const value = known ? Math.max(...values.map(([, v]) => v)) : null;
  return { concern, source: 'analysis', value, maximum,
    status: value === null ? 'unknown' : concern === 'blemish' ? value === 1 ? 'care' : 'good' : skinGradeStatus(value),
    regions: known ? values.map(([region, v]) => ({ region, value: v })) : [] };
}

export function buildSkinReport(input: SkinReportInput): SkinReport {
  const f = input.analysis.features;
  const q = input.questionnaire;
  const resolvedType = resolveSkinType(input.analysis.skinType, q);
  const skinType = resolvedType.type;
  const metrics: SkinReportMetric[] = [
    input.analysis.skinType ? { concern: 'dryness', source: resolvedType.source, skinType,
      status: skinType === 'dry' ? 'care' : 'good', value: null, maximum: null, regions: [] }
      : surveyMetric('dryness', q.tightness),
    modelMetric('pigmentation', 5, [['forehead', f.pigmentation_grade_forehead], ['leftCheek', f.pigmentation_grade_cheek_image_left], ['rightCheek', f.pigmentation_grade_cheek_image_right]]),
    surveyMetric('oiliness', q.oiliness),
    modelMetric('wrinkles', 6, [['forehead', f.wrinkle_grade_forehead], ['glabella', f.wrinkle_grade_glabella], ['leftEye', f.wrinkle_grade_eye_image_left], ['rightEye', f.wrinkle_grade_eye_image_right]]),
    modelMetric('pores', 5, [['leftCheek', f.pore_grade_cheek_image_left], ['rightCheek', f.pore_grade_cheek_image_right]]),
    f.acne === undefined ? { concern: 'blemish', source: 'unavailable', status: 'unknown', value: null, maximum: null, regions: [] }
      : modelMetric('blemish', 1, [['overall', f.acne]]),
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

export function sampleProductMatches(concerns: readonly SkinConcern[]): { product: SkinSampleProduct; matchedConcerns: SkinConcern[] }[] {
  return SKIN_SAMPLE_PRODUCTS.map((product: SkinSampleProduct) => ({ product,
    matchedConcerns: SKIN_CONCERNS.filter((c) => concerns.includes(c) && product.concerns.includes(c)),
  })).filter((m) => m.matchedConcerns.length > 0)
    .sort((a, b) => b.matchedConcerns.length - a.matchedConcerns.length || a.product.id.localeCompare(b.product.id));
}
