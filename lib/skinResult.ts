import type { SkinAnalysisResult } from '@/types/skin';

export function skinGradeStatus(grade: number) {
  return !Number.isInteger(grade) || grade < 0 ? 'unknown' as const
    : grade <= 3 ? 'good' as const : 'care' as const;
}

export function summarizeSkinResult(features: SkinAnalysisResult['features'], schema?: SkinAnalysisResult['schema']) {
  // Keep the most affected area visible instead of averaging it away.
  const grades = {
    pore: Math.max(features.pore_grade_cheek_image_left, features.pore_grade_cheek_image_right),
    pigmentation: Math.max(features.pigmentation_grade_forehead,
      features.pigmentation_grade_cheek_image_left, features.pigmentation_grade_cheek_image_right),
    wrinkle: Math.max(features.wrinkle_grade_forehead, features.wrinkle_grade_glabella,
      features.wrinkle_grade_eye_image_left, features.wrinkle_grade_eye_image_right),
  };
  return {
    grades: (['pore', 'pigmentation', 'wrinkle'] as const).map(indicator => ({
      indicator, grade: grades[indicator], status: schema === 'skin-analysis-mobile-v4'
        ? grades[indicator] === 1 ? 'care' as const : grades[indicator] === 0 ? 'good' as const : 'unknown' as const
        : skinGradeStatus(grades[indicator]),
    })),
    acneDetected: features.acne === undefined ? null : features.acne === 1,
  };
}
