import type { SkinAnalysisResult } from '@/types/skin';

export function summarizeSkinResult(features: SkinAnalysisResult['features']) {
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
      indicator, grade: grades[indicator], status: grades[indicator] <= 2 ? 'good' as const : 'care' as const,
    })),
    acneDetected: features.acne === 1,
  };
}
