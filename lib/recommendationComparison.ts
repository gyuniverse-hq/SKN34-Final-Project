import Constants from 'expo-constants';
import type { SkinProfile } from '@/types/skin';
import type { ComparisonAge, ComparisonGender, RecommendationComparisonInput, RecommendationComparisonResult } from '@/types/recommendationComparison';
import { buildSkinReport } from './skinReport';
import { deriveCareGoals } from './skincare';
import { ApiError } from './api';

/** Same anatomical aggregation as the supplied training metadata; preprocessing still differs. */
export function comparisonInput(profile: SkinProfile | null, ageGroup: ComparisonAge, gender: ComparisonGender): RecommendationComparisonInput {
  if (profile?.analysis.schema !== 'skin-analysis-mobile-v4') throw new Error('comparison.needV4');
  const p = profile.analysis.cautionProbabilities;
  if (!p) throw new Error('comparison.needV4');
  const mean = (...values: number[]) => {
    if (values.some(v => !Number.isFinite(v) || v < 0 || v > 1)) throw new Error('comparison.invalidScores');
    return values.reduce((sum, v) => sum + v, 0) / values.length;
  };
  const type = buildSkinReport(profile).skinType;
  if (!type || type === 'unknown') throw new Error('comparison.needType');
  return { ageGroup, gender, skinType: { dry: '건성', balanced: '중성', oily: '지성', combination: '복합성' }[type] as RecommendationComparisonInput['skinType'],
    analysisVersion: 'skin-analysis-v4', scoreKind: 'binary_caution_probability', aggregation: 'mean-cheeks-pore-tone-eyes-wrinkle-v1',
    irritationSignal: deriveCareGoals(profile).irritationSignal,
    scores: {
      pores: mean(p.pore_grade_cheek_image_left, p.pore_grade_cheek_image_right),
      pigmentation: mean(p.pigmentation_grade_cheek_image_left, p.pigmentation_grade_cheek_image_right),
      wrinkles: mean(p.wrinkle_grade_eye_image_left, p.wrinkle_grade_eye_image_right),
    } };
}

export async function fetchRecommendationComparison(body: RecommendationComparisonInput): Promise<RecommendationComparisonResult> {
  if (!__DEV__) throw new Error('comparison.unavailable');
  const host = Constants.expoConfig?.hostUri?.split(':')[0] || 'localhost';
  const base = process.env.EXPO_PUBLIC_RECOMMENDATION_COMPARE_URL || `http://${host}:8082`;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60000);
  try {
    const response = await fetch(`${base.replace(/\/$/, '')}/api/dev/recommendations/compare`, {
      method: 'POST', signal: controller.signal, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new ApiError(data.error || 'comparison.unavailable', response.status, data.code);
    return data as RecommendationComparisonResult;
  } finally { clearTimeout(timer); }
}
